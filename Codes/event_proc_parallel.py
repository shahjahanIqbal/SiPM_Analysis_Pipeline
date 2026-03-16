import os
os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"

import numpy as np
import logging
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import os
import h5py
from config_loader import load_config
from geometry import CameraLayout
from registry_creator import fetchPacketIndices, build_event_registry
from data_extractor import dataExtractor
import logging
from logging.handlers import RotatingFileHandler
import datetime
from tqdm import tqdm




class EventProcessor():
    START_FRAME = 0xFBDA
    END_FRAME   = 0xEDAC

    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.evb_path = None#Path(evb_path)
        self.output_dir = None
        self.config = None
        self.geometry = None
        self.registry = None
        self.extracted_events = []

    def setup(self):
        logging.info("Loading configuration")
        self.config = load_config(self.config_path)

        logging.info("Initializing geometry")
        self.geometry = CameraLayout(self.config)
        self.evb_path = Path(self.config["data"]["evbfilepath"])
        
        self.output_dir = Path(self.config["io"]["output"])
        if not self.output_dir.exists():
            self.output_dir.mkdir(exist_ok=True)
        
        if not self.evb_path.exists():
            raise FileNotFoundError(f"EVB file not found: {self.evb_path}")

        logging.info(f"Loading EVB file: {self.evb_path}")
        self.data = np.memmap(self.evb_path, dtype=np.uint32, mode="r")

    def buildRegistry(self):
        start_indices, end_indices = fetchPacketIndices(
            self.data,
            self.START_FRAME,
            self.END_FRAME
        )

        self.registry = build_event_registry(
            self.data,
            start_indices,
            end_indices
        )


    def extractEventsParallel(self):

        logging.info("Preparing event jobs")

        ROI = self.config["camera_geometry"]["readout"]["roi_samples"]

        jobs = []

        # ---------------- Build Jobs ----------------
        for event_id, event_info in self.registry.items():

            packet_ranges = event_info["packets"]

            if not packet_ranges:
                continue

            start = min(si for si, _ in packet_ranges)
            end   = max(ei for _, ei in packet_ranges)

            data_slice = self.data[start:end+1]

            adjusted_packets = [
                (si - start, ei - start)
                for si, ei in packet_ranges
            ]

            event_info_local = {
                "packets": adjusted_packets,
                "quality": event_info["quality"]
            }

            jobs.append((event_id, event_info_local, data_slice)) #DO NOT CREATE ARRAY COPIES OF DATASLICE, PASS self.data AND INDICES TO SAVE MEMORY

        logging.info(f"Submitting {len(jobs)} events to workers")

        # ---------------- Parallel Execution ----------------
        

        # ---------------- Write HDF5 ----------------
        N_GLOBAL_CH = self.geometry.N_GLOBAL_CH

        #output_dir = Path("../output")
        #output_dir.mkdir(exist_ok=True)

        with h5py.File(self.output_dir / "evts.h5", "w") as h5f:

            nevents = len(self.registry)

            d_event = h5f.create_dataset("events/event_id", (nevents,), dtype="i4")

            d_adc = h5f.create_dataset(
                "adc/roi_data",
                (nevents, N_GLOBAL_CH, ROI),
                dtype="i2",
                compression="gzip",
                chunks=(1, N_GLOBAL_CH, ROI),
            )

            d_cstop = h5f.create_dataset(
                "adc/cstop",
                (nevents, N_GLOBAL_CH),
                dtype="i2"
            )

            d_roi_cell = h5f.create_dataset(
                "adc/roi_cell",
                (nevents, N_GLOBAL_CH),
                dtype="i2"
            )

            d_skip_cell = h5f.create_dataset(
                "adc/skip_cell",
                (nevents, N_GLOBAL_CH),
                dtype="i2"
            )

            d_time_stamp = h5f.create_dataset(
                "adc/time_stamp",
                (nevents, N_GLOBAL_CH),
                dtype="f4"
            )

            d_time_elapsed = h5f.create_dataset(
                "adc/time_elapsed",
                (nevents, N_GLOBAL_CH),
                dtype="i4"
            )

            d_qual = h5f.create_dataset(
                "adc/quality",
                (nevents,),
                dtype="i2"
            )
            with ProcessPoolExecutor(max_workers= max(1, os.cpu_count() - 1)) as executor:

                futures = [
                    executor.submit(
                        dataExtractor,
                        event_id,
                        event_info,
                        data_slice,
                        self.geometry,
                        ROI
                    )
                    for event_id, event_info, data_slice in jobs
                ]

                for future in tqdm(as_completed(futures),
                                   total=len(futures),
                                   desc="Processing events",
                                   unit="event"):
                    try:
                        result = future.result()
                        
                        idx = result["event_id"] 
                        d_event[idx] = result["event_number"]
                        d_adc[idx] = result["adc"]
                        d_cstop[idx] = result["cstop"]
                        d_skip_cell[idx] = result["skip_cell"]
                        d_qual[idx] = result["quality"] 
                        d_roi_cell[idx] = result["roi_cell"]
                        #d_time_stamp[idx] = result["time_stamp"]
                        #d_time_elapsed[idx] = result["time_elapsed"]

                    except Exception as e:
                        logging.error(f"Worker crashed: {e}")

            logging.info("Parallel extraction complete")
          
                       
    def run(self):
        self.setup()
        self.buildRegistry()
        self.extractEventsParallel()
    


def setup_logging():

    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s - %(processName)s - %(levelname)s - %(message)s"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    log_dir = Path("../log")
    
    if not log_dir.exists():
         log_dir.mkdir(parents=True, exist_ok=True)

    # Rotating file handler
    timestamp = datetime.datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    file_handler = RotatingFileHandler(
        log_dir / f'event_proc_{timestamp}.log',
        maxBytes=50_000_000,  # 50 MB
        backupCount=3
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    #logger.addHandler(console_handler)
    logger.addHandler(file_handler)

if __name__ == "__main__":

    setup_logging()


    pipeline = EventProcessor(
        config_path="../config/config.yaml"
    )

    pipeline.run()
