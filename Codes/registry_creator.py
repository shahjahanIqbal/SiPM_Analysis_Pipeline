#!/usr/bin/env python3
import numpy as np
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm


def fetchPacketIndices(data, START_FRAME, END_FRAME):
    print("Fetching Packet Indices...")
    header = (data >> 16) & 0xFFFF
    all_start_index = np.where(header == START_FRAME)[0]
    all_end_index   = np.where(header == END_FRAME)[0]
    return all_start_index, all_end_index


def process_chunk(args):
    
    filepath, dtype, start_chunk, all_start_index, all_end_index = args

    
    data = np.memmap(filepath, dtype=dtype, mode="r")

    local_registry = {}

    for si in start_chunk:
        # si is an element of all_start_index, so its sorted position in that array is found via searchsorted.
        i = np.searchsorted(all_start_index, si)

        event_id    = int(data[si + 2] & 0x7FFFFFFF)
        CDM_ID      = int((data[si + 5] >> 18) & 0x1F)
        DDB_ID      = int((data[si + 5] >> 16) & 0x3)

        if event_id not in local_registry:
            local_registry[event_id] = {"packets": [], "quality": 3}

        next_start = int(all_start_index[i + 1]) if i + 1 < len(all_start_index) else len(data)

        start_idx = np.searchsorted(all_end_index, si, side="right")
        end_idx   = np.searchsorted(all_end_index, next_start, side="left")

        candidate_ends = all_end_index[start_idx:end_idx]

        if len(candidate_ends) == 0:
            logging.error(f"No end frame for packet at {si} (CDM {CDM_ID} DDB {DDB_ID})")
            local_registry[event_id]["quality"] = min(local_registry[event_id]["quality"], 1)
            continue

        if len(candidate_ends) > 1:
            # Multiple end frames between two starts —> missing start frames 
            logging.error(f"Multiple end frames found after {si} (CDM {CDM_ID} DDB {DDB_ID})")
            local_registry[event_id]["quality"] = min(local_registry[event_id]["quality"], 1)

        ei = int(candidate_ends[0])

        calculated_packet_size = int(data[si] & 0x0000FFFF)
        observed_packet_size   = int(data[ei] & 0x0000FFFF)
        no_of_words            = calculated_packet_size          
        actual_size            = ei - si + 1

        if len({calculated_packet_size, observed_packet_size, no_of_words, actual_size}) != 1:
            logging.error(
                f"Packet size mismatch in event {event_id} "
                f"CDM {CDM_ID} DDB {DDB_ID}: "
                f"calc={calculated_packet_size} obs={observed_packet_size} "
                f"actual={actual_size}"
            )
            local_registry[event_id]["quality"] = min(local_registry[event_id]["quality"], 2)
            continue

        local_registry[event_id]["packets"].append((si, ei))

    return local_registry


def _merge_registries(results):
    registry = {}
    for local in results:
        for event_id, val in local.items():
            if event_id not in registry:
                registry[event_id] = {"packets": [], "quality": 3}
            registry[event_id]["packets"].extend(val["packets"])
            registry[event_id]["quality"] = min(registry[event_id]["quality"], val["quality"])
    return registry


def build_event_registry_parallel(
    data,
    all_start_index,
    all_end_index,
    n_workers=None,
):
   
    if n_workers is None:
        n_workers = max(1, os.cpu_count() - 1)

    print(f"Building event registry ({n_workers} workers)...")

    
    filepath = data.filename
    dtype    = data.dtype

    # Convert to plain Python ints so numpy arrays inside args are minimal.
    all_start_index = np.asarray(all_start_index)
    all_end_index   = np.asarray(all_end_index)

    chunks = np.array_split(all_start_index, n_workers)

    args = [
        (filepath, dtype, chunk, all_start_index, all_end_index)
        for chunk in chunks if len(chunk) > 0
    ]

    results = []
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        future_to_chunk = {executor.submit(process_chunk, arg): i for i, arg in enumerate(args)}

        for future in tqdm(as_completed(future_to_chunk), total=len(args), desc="Building registry"):
            chunk_idx = future_to_chunk[future]
            try:
                results.append(future.result())
            except Exception as exc:
                logging.error(f"Chunk {chunk_idx} raised: {exc}")

    return _merge_registries(results)


def build_event_registry(data, all_start_index, all_end_index):
    """Serial fallback - useful for small files or debugging."""
    print("Building event registry (serial)...")
    registry = {}

    for i, si in enumerate(all_start_index):
        event_id = int(data[si + 2] & 0x7FFFFFFF)
        CDM_ID   = int((data[si + 5] >> 18) & 0x1F)
        DDB_ID   = int((data[si + 5] >> 16) & 0x3)

        if event_id not in registry:
            registry[event_id] = {"packets": [], "quality": 3}

        next_start = int(all_start_index[i + 1]) if i + 1 < len(all_start_index) else len(data)

        start_idx = np.searchsorted(all_end_index, si, side="right")
        end_idx   = np.searchsorted(all_end_index, next_start, side="left")

        candidate_ends = all_end_index[start_idx:end_idx]

        if len(candidate_ends) == 0:
            logging.error(f"No end frame for packet at {si} (CDM {CDM_ID} DDB {DDB_ID})")
            registry[event_id]["quality"] = min(registry[event_id]["quality"], 1)
            continue

        if len(candidate_ends) > 1:
            registry[event_id]["quality"] = min(registry[event_id]["quality"], 1)

        ei = int(candidate_ends[0])

        calculated_packet_size = int(data[si] & 0x0000FFFF)
        observed_packet_size   = int(data[ei] & 0x0000FFFF)
        no_of_words            = calculated_packet_size
        actual_size            = ei - si + 1

        if len({calculated_packet_size, observed_packet_size, no_of_words, actual_size}) != 1:
            logging.error(
                f"Packet size mismatch in event {event_id} "
                f"CDM {CDM_ID} DDB {DDB_ID}: "
                f"calc={calculated_packet_size} obs={observed_packet_size} "
                f"actual={actual_size}"
            )
            registry[event_id]["quality"] = min(registry[event_id]["quality"], 2)
            continue

        registry[event_id]["packets"].append((si, ei))

    return registry
