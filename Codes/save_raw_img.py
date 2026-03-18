#!/usr/bin/env python3
import numpy as np
from config_loader import load_config
from image_gen import saveImageHiRes, processEvent, plotLGHGPulseWithWindow, plotReferencePulses
from geometry import CameraLayout          
from pathlib import Path
import h5py
import cmyt
from concurrent.futures import ProcessPoolExecutor, as_completed
import traceback
import os
import tqdm
config = load_config("config/config.yaml")
geometry = CameraLayout(config)
pixel_map = geometry.loadPixelMap(f"geometry/{geometry.camera_name}")
offset = np.loadtxt(Path(config["calib"]["drsoffset"]))
def main(infile_name, output_dir, event_id_start = 1, event_id_end = None, save_lg = True, save_hg = True, save_arrTime = True, save_waveform = False, save_refPulse = False):
    if not Path(infile_name).exists():
        print("H5 File not found! Please enter the correct file path")
        exit
    if (event_id_end == None) | (event_id_end == event_id_start):
        event_id_end = event_id_start + 1
    with h5py.File(infile_name, "r") as f:
        roi_all = f["adc/roi_data"]
        cstop_all = f["adc/cstop"]
        skip_cell_all =f["adc/skip_cell"]
  

        with ProcessPoolExecutor(max_workers = max(1, os.cpu_count() - 1)) as executor:
            futures = []


            for event in range(event_id_start, event_id_end + 1):
                roi_slice = roi_all[event]
                cstop = cstop_all[event]
                skip_cell = skip_cell_all[event]

                futures.append(

                    executor.submit(
                        processEvent,
                        event,
                        roi_all[event],
                        cstop_all[event],
                        skip_cell_all[event],
                        offset,
                        geometry,
                        pixel_map,
                        np.arange(geometry.N_GLOBAL_CH),
                        output_dir
                    )
                )
                '''result = processEvent(event, 
                                    roi_slice = roi_all[event], 
                                    cstop_slice = cstop_all[event], 
                                    skip_cell_slice = skip_cell_all[event], 
                                    offsets=offset, 
                                    geometry = geometry, 
                                    pixel_map = pixel_map, 
                                    gch = np.arange(geometry.N_GLOBAL_CH)
                                    ) '''
            for future in tqdm(as_completed(futures), total = event_id_end - event_id_start + 1, desc = "Generating Images", unit = "event"):
                try:
                    result = future.result()
                    evt = result["event_id"]
                    if save_lg:
                        saveImageHiRes(f"{evt}_LG", "Integrated Charge",  result["image_LG"], output_dir, pixel_map, geometry,cmap = 'cmyt.xray')
                    if save_hg:
                        saveImageHiRes(f"{evt}_HG", "Integrated Charge", result["image_HG"], output_dir, pixel_map, geometry)
                    if save_arrTime:
                        saveImageHiRes(f"{evt}_time", "Arrival Time", result["t_image_HG"], output_dir, pixel_map, geometry, cmap='plasma')
                    if save_waveform:
                        plotLGHGPulseWithWindow(roi_all[evt], cstop_all[evt], offset, skip_cell_all[evt], geometry, 2, event, output_dir)
                    if save_refPulse:
                        plotReferencePulses(event, roi_all[evt], geometry, output_dir)
                except Exception as e:
                    print("Worker crashed:", e)
                    traceback.print_exc()


if __name__ == "__main__":
    main