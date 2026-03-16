import numpy as np
import logging

def fetchPacketIndices(data, START_FRAME, END_FRAME):
    
    all_start_index = np.where(((data >> 16) & 0xFFFF) == START_FRAME)[0]
    all_end_index   = np.where(((data >> 16) & 0xFFFF) == END_FRAME)[0]

    
    return all_start_index, all_end_index


def build_event_registry(data, all_start_index, all_end_index):

    registry = {}

    for i, si in enumerate(all_start_index):

        event_id = data[si + 2] & 0x7FFFFFFF

        # quality: 
        # 3 -> Complete packets; 
        # 2 -> Packet size mismatch from expected value, either missing or additional data is present; 
        # 1 -> Missing packets in event (missing start or end frames)

        if event_id not in registry:
            registry[event_id] = {
                "packets": [],
                "quality": 3 # Quality is not being used yet 
            }

        next_start = all_start_index[i+1] if i+1 < len(all_start_index) else len(data)
        candidate_ends = all_end_index[
            (all_end_index > si) & (all_end_index < next_start)
        ]

        if len(candidate_ends) == 0:
            logging.error(f"No end frame for packet at {si}")
            quality = 1
            registry[event_id]["quality"] = min(registry[event_id]["quality"], quality)
            continue
        # WHAT IF len(candidate_ends) > 1? NEED TO FIX FOR MULTIPLE ENDS OR MISSING STARTS
        # If start frames are missing, the packet is not read
        if len(candidate_ends) > 1:
            registry[event_id]["quality"] = min(registry[event_id]["quality"], 1)
        
        ei = candidate_ends[0]

        calculated_packet_size = data[si] & 0x0000FFFF
        observed_packet_size   = data[ei] & 0x0000FFFF
        CDM_ID = (data[si+5] >> 18) & 0x1f
        DDB_ID = (data[si+5] >> 16) & 0x3
        no_of_words = np.size(data[si:si + calculated_packet_size])
        actual_size = ei - si + 1

        if len({calculated_packet_size, observed_packet_size, no_of_words, actual_size}) != 1:
                logging.error(f"Packet size mismatch error in event {event_id} CDM: {CDM_ID} DDB: {DDB_ID}")
                quality = 2
                registry[event_id]["quality"] = min(registry[event_id]["quality"], quality)
                continue

        registry[event_id]["packets"].append((si, ei))
        

    return registry