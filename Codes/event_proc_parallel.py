#!/usr/bin/env python3
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
from registry_creator import fetchPacketIndices, build_event_registry_parallel
from data_extractor import dataExtractor
from logging.handlers import RotatingFileHandler
import datetime
from tqdm import tqdm




class EventProcessor():
    batch_size= 5000

    START_FRAME = 0xFBDA
    END_FRAME   = 0xEDAC

    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.evb_path = None
        self.evb_files = []
        self.output_dir = None
        self.config = None
        self.geometry = None
        self.registry = None
        self.extracted_events = []


    def setup(self):
        '''
        Input: none (uses self)
        Output: none; populates self.config, self.geometry, self.evb_files, self.output_dir
        Loads the config via load_config, instantiates CameraLayout, resolves the EVB
        input path from the config (single file or batch text file listing multiple
        paths), and creates the output directory. 
        Raises ValueError if evbfilepath is unset, FileNotFoundError if a listed file is absent.

        '''
        logging.info("Loading configuration")
        self.config = load_config(self.config_path)
        print("Config loaded")
        logging.info("Initializing geometry")
        self.geometry = CameraLayout(self.config)

        # Reading input file paths. It accepts either a path to a single evb file or a text file for batch processing
        self.evb_path = self.config["data"]["evbfilepath"]

        if not self.evb_path:
            raise ValueError("Config error: 'data.evbfilepath' is not set.")

        
        if (self.evb_path.split('/')[-1].split('.')[-1] == 'txt'):

            for evtfile in np.atleast_1d(np.loadtxt(self.evb_path, dtype=str)):
                if not Path(evtfile).exists():
                    raise FileNotFoundError(f"{evtfile} file not found. Skipping...")
                    
                self.evb_files.append(Path(evtfile.strip()))
                
        else:
            if not Path(self.evb_path).exists():
                raise FileNotFoundError(f"EVB file not found: {self.evb_path}")
            self.evb_files = [Path(self.evb_path)]

        
        # Setting up output directory for intermediate h5 file generation
        self.output_dir = Path(self.config["io"]["output"])
        if not self.output_dir.exists():
            self.output_dir.mkdir(exist_ok=True)
        


    def buildRegistry(self, data):
        '''
        Input: data (np.memmap of the EVB file)
        Output: event registry dict
        Calls fetchPacketIndices to locate frame boundaries, then delegates to
        build_event_registry_parallel. Returns the populated registry used by
        jobGenerator and extractEventsParallel.

        '''
        print("Building Registry")
        start_indices, end_indices = fetchPacketIndices( 
            data,
            self.START_FRAME,
            self.END_FRAME
        )

        registry = build_event_registry_parallel(
            data,
            start_indices,
            end_indices
        )
        return registry

    
    def jobGenerator(self, registry, data):
        '''
        Input: registry (dict), data (np.memmap)
        Output: generator yielding (event_id, event_info_local, data_slice) tuples
        For each event, finds the minimal byte span covering all its packets, slices
        the memmap to that span, and adjusts packet offsets to be relative to the
        slice. Skips events with no packets.
        '''
        print("Generating Jobs")
        for event_id, event_info in registry.items():

            packet_ranges = event_info["packets"]
            if not packet_ranges:
                continue

            start = min(si for si, _ in packet_ranges)
            end   = max(ei for _, ei in packet_ranges)

            data_slice = data[start:end+1]

            adjusted_packets = [
                (si - start, ei - start)
                for si, ei in packet_ranges
            ]

            event_info_local = {
                "packets": adjusted_packets,
                "quality": event_info["quality"]
            }

            yield (event_id, event_info_local, data_slice)
    
    def batchCreator(self, job, batch_size):
        '''
        Input: job (generator), batch_size (int, default 5000)
        Output: generator yielding lists of jobs
        Accumulates jobs up to batch_size and yields each full batch. Flushes any
        remaining jobs in a partial batch at the end. Prevents unbounded memory use
        when processing large EVB files with many events.
        '''
        print("Creating Batches")
        batch = []
        for j in job:
            batch.append(j)
            if len(batch) == batch_size:
                yield batch
                batch = []
        if batch:
            yield batch

    def extractEventsParallel(self, data, registry, outfile_name, n_workers):
        '''
        Input: data (np.memmap), registry (dict), outfile_name (str), n_workers (int)
        Output: none; writes a .h5 file to self.output_dir
        Creates the output HDF5 with pre-allocated datasets for adc, cstop, skip_cell,
        roi_cell, quality, and event_id. Submits dataExtractor jobs batch by batch and
        writes results indexed by event_id as futures complete. Clips n_workers to
        cpu_count - 1 if the user requests too many.

        '''
        if n_workers is None:
            n_workers = max(1, os.cpu_count() - 1)
        if n_workers > os.cpu_count():
            print(f"WARNING: Number of specified cores exceeds cpu count. Using {max(1, os.cpu_count() -1)} cores")
            n_workers = max(1, os.cpu_count() - 1)


        ROI = self.config["camera_geometry"]["readout"]["roi_samples"]
        
        
        N_GLOBAL_CH = self.geometry.N_GLOBAL_CH

        # ---------------- Write HDF5 ----------------#

        with h5py.File(self.output_dir / f"{outfile_name}.h5", "w") as h5f:
            nevents = len(registry)
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
            d_qual = h5f.create_dataset(
                "adc/quality",
                (nevents,),
                dtype="i2"
            )

             

            with ProcessPoolExecutor(max_workers= n_workers) as executor:
                job_iterator = self.jobGenerator(registry, data)

                for batch in self.batchCreator(job_iterator, self.batch_size):
                    futures = []
                    
                    for event_id, event_info, data_slice in batch:
                        futures.append(
                            executor.submit(
                            dataExtractor,
                            event_id,
                            event_info,
                            data_slice,
                            self.geometry,
                            ROI
                            )
                        )

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
                        except Exception as e:
                            logging.error(f"Worker crashed: {e}")
            logging.info("Parallel extraction complete")
          
                       
    def run(self, n_workers = None):
        '''
        Input: n_workers (int, optional)
        Output: none; writes processed HDF5 files and appends paths to output_files.txt
        Calls setup, then loops over each EVB file in self.evb_files, builds the
        registry, runs extractEventsParallel, and records the output path. The
        output_files.txt is opened in append mode so batch runs accumulate entries.
        '''
        self.setup()
        with open(Path(self.config["io"]["output"])/ f"output_files.txt", "a") as f:  
                  
            for evb in (self.evb_files):
                logging.info(f"Processing {evb}")    
                print(f"Processing {evb}")
                data = np.memmap(evb, dtype=np.uint32, mode = 'r')
                registry = self.buildRegistry(data)
                outfile_name = Path(evb).stem + "_processed"

                self.extractEventsParallel(data, registry, outfile_name, n_workers = n_workers)
                f.write(f"{Path(self.config['io']['output'])/ f'{outfile_name}.h5'}\n")
        f.close()
        print(f"File saved: {Path(self.config['io']['output'])/ f'{outfile_name}.h5'} ")
    


def setup_logging():
    '''
        Attaches a rotating file handler (50 MB limit, 3 backups) writing to ../log/
        with a timestamped filename. A commented-out console handler can be re-enabled
        for interactive debugging. Should be called once before constructing an
        EventProcessor.
    '''

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
        config_path="config/config.yaml"
    )

    pipeline.run()

