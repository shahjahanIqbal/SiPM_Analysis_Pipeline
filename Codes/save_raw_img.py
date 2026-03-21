#!/usr/bin/env python3
import numpy as np
from config_loader import load_config
from image_gen import * 
from geometry import CameraLayout          
from pathlib import Path
import h5py
import cmyt
from concurrent.futures import ProcessPoolExecutor, as_completed
import traceback
import os
from tqdm import tqdm
import argparse

import matplotlib
matplotlib.use('Agg')

# Forcing QT to use wayland and quit whining -_-
os.environ["QT_QPA_PLATFORM"] = "wayland"

config = load_config("config/config.yaml")
geometry = CameraLayout(config)
pixel_map = geometry.loadPixelMap(f"geometry/{geometry.camera_name}.h5")
offset = np.loadtxt(Path(config["calib"]["drsoffset"]))
def main(infile_name, output_dir, event_id_start = 1, event_id_end = None, save_lg = True, save_hg = True, save_arrTime = True, save_waveform = False, save_refPulse = False, save_charge_dist_LG = False, save_charge_dist_HG = False, save_time_dist = False):
    if not Path(infile_name).exists():
        print("H5 File not found! Please enter the correct file path")
        exit
    if (event_id_end == None) | (event_id_end == event_id_start):
        event_id_end = event_id_start + 1

    if event_id_start > event_id_end:
        try:
            raise RuntimeError("Event start index > end index. Bruh (-_-)")
        except RuntimeError as e:
            print(f"RuntimeError: {e}")
    output_dir = output_dir / f"{infile_name.split('/')[-1].split('.')[0]}"
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    with h5py.File(infile_name, "r") as f:
        roi_all = f["adc/roi_data"]
        cstop_all = f["adc/cstop"]
        skip_cell_all =f["adc/skip_cell"]
  

        with ProcessPoolExecutor(max_workers = max(1, os.cpu_count() - 1)) as executor:
            futures = []


            for event in range(event_id_start, event_id_end):
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

            for future in tqdm(as_completed(futures), total = event_id_end - event_id_start , desc = "Generating Images", unit = "event"):
                try:
                    result = future.result()
                    evt = result["event_id"]
                    if save_lg:
                        #print("Generating Charge Image")
                        saveImageHiRes(f"{evt}_LG", "Integrated Charge",  result["image_LG"], output_dir, pixel_map, geometry,cmap = 'cmyt.xray')
                    if save_hg:
                        #print("Generating Charge Image")
                        saveImageHiRes(f"{evt}_HG", "Integrated Charge", result["image_HG"], output_dir, pixel_map, geometry)
                    if save_arrTime:
                        #print("Generating Arrival Time Image")
                        saveImageHiRes(f"{evt}_time", "Arrival Time", result["time_HG"], output_dir, pixel_map, geometry, cmap='plasma')
                    if save_charge_dist_LG:
                        #print("Generating Charge Distribution")
                        chargeDist(evt, result["image_LG"], "Charge Distribution LG", "Charge [pC]", output_dir, charge_flag = True)
                    if save_charge_dist_HG:
                        #print("Generating Charge Distribution")
                        chargeDist(evt, result["image_HG"], "Charge Distribution HG", "Charge [pC]", output_dir, charge_flag = True )
                    if save_time_dist:
                        #print("Generating Arrival Time Distribution")
                        chargeDist(evt, result["time_HG"], "Arrival Time Distribution", "Time [ns]", output_dir )
                    if save_waveform:
                        #print("Generating Waveforms")
                        plotAllPulses(roi_all[evt], cstop_all[evt], offset, skip_cell_all[evt], geometry, evt, output_dir)
                    if save_refPulse:
                        #print("Generating Reference Pulses")
                        plotReferencePulses(evt, roi_all[evt], geometry, output_dir)
                    
                except Exception as e:
                    print("Worker crashed:", e)
                    traceback.print_exc()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate event images and pulse profiles")

    parser.add_argument("infile", type = str, help="H5 file path")
    parser.add_argument("output_dir", type= str, default = "plots", help = "Output Directory")
    parser.add_argument("--start", type = int, default = 1, help = "Start Event ID")
    parser.add_argument("--end", type = int, default = None, help = "End Event ID")
    parser.add_argument("--no-lg", action="store_true", help="Disable LG image saving")
    parser.add_argument("--no-hg", action="store_true", help="Disable HG image saving")
    parser.add_argument("--no-time", action="store_true", help="Disable arrival time images")
    parser.add_argument("--waveform", action="store_true", help="Save waveform plots")
    parser.add_argument("--refpulse", action="store_true", help="Save reference pulses")
    parser.add_argument("--cdist-lg", action="store_true", help="Save LG charge distribution")
    parser.add_argument("--cdist-hg", action="store_true", help="Save HG charge distribution")
    parser.add_argument("--tdist", action="store_true", help="Save Arrival time distribution")

    args = parser.parse_args()
    
    main(
        infile_name = args.infile,
        output_dir = Path(args.output_dir),
        event_id_start = args.start,
        event_id_end = args.end,
        save_lg = not args.no_lg,
        save_hg = not args.no_hg,
        save_arrTime = not args.no_time,
        save_waveform = args.waveform,
        save_refPulse = args.refpulse,  
        save_charge_dist_LG= args.cdist_lg,
        save_charge_dist_HG= args.cdist_hg,
        save_time_dist= args.tdist
    )