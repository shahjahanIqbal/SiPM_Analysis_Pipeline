import traceback
import numpy as np
from ctapipe.instrument import OpticsDescription
from ctapipe.io import HDF5TableWriter
from ctapipe.containers import DL1CameraContainer, EventIndexContainer
from ctapipe.instrument import SubarrayDescription, TelescopeDescription
from ctapipe.instrument.camera import CameraGeometry, CameraReadout
from ctapipe.instrument.camera.description import CameraDescription

from ctapipe.io import DataWriter
from ctapipe.containers import ArrayEventContainer


from geometry import CameraLayout
from astropy import units as u
from image_gen import peakFinder, adcTomV
from config_loader import load_config
import h5py
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm
from image_gen import *
import os
import matplotlib

# Forcing QT to use wayland and quit whining -_-
os.environ["QT_QPA_PLATFORM"] = "wayland"
# Force non-GUI backend
matplotlib.use("Agg")


def buildSubarray(geometry):

    size = 22.1
    pixel_count = geometry.N_PCM * geometry.N_DDB * 4 
    pix_id = np.arange(0,pixel_count,1)
    pix_type = "square"
    x_sq = (np.arange(-8,8) * size)+size/2.0
    y_sq = (np.arange(-8,8) * size)+size/2.0
    pix_x_sq, pix_y_sq = np.meshgrid(x_sq, y_sq)
    pix_x_sq = pix_x_sq.ravel()*u.mm
    pix_y_sq = pix_y_sq.ravel()*u.mm
    pix_area_sq = np.power(size/1.05,2)*u.mm**2
    geom = CameraGeometry(pix_id=pix_id, 
                          pix_x=pix_x_sq, 
                          pix_y = pix_y_sq, 
                          pix_area=pix_area_sq*np.ones([pixel_count]), 
                          pix_type=pix_type, 
                          name="SiPM Camera")
    reference_pulse_shape = np.zeros((2, 150)) # First dimension for the gain channel, second for the pulse
    
    
    
    camera_readout = CameraReadout(
        name = "SiPM",
        sampling_rate = 1 * u.GHz, 
        reference_pulse_sample_width = 1 * u.ns,
        reference_pulse_shape = reference_pulse_shape,
        n_channels = geometry.N_GLOBAL_CH,
        n_pixels = 256,
        n_samples = geometry.roi)
    
    camera = CameraDescription(
        name=geometry.camera_name,
        geometry=geom,
        readout = camera_readout)
    
    optics = OpticsDescription(
        name="Optics",
        size_type="UNKNOWN",
        n_mirrors=1,
        equivalent_focal_length=1.0 * u.m,
        effective_focal_length=1.0 * u.m,
        mirror_area=1.0 * u.m**2,
        n_mirror_tiles=1,
        reflector_shape="UNKNOWN",
    )

    tel = TelescopeDescription(
        name="Tel",
        optics=optics,
        camera=camera,
    )

    subarray = SubarrayDescription(
        name="Array",
        tel_positions={1: [0, 0, 0] * u.m},
        tel_descriptions={1: tel},
        reference_location = [0, 0, 0] * u.m
    )

    return subarray


def main():

    config = load_config("../config/config.yaml")
    geometry = CameraLayout(config)
    pixelmap_filename = geometry.camera_name
    # Load pixel map 

    pixel_map = geometry.loadPixelMap(f"../geometry/{pixelmap_filename}.h5")
    # Load offsets 
    
    #offsets = np.loadtxt("../DRS_OFFSET/offsetcal_January13012026.txt")
    drs_path = Path(config["calib"]["drsoffset"])

    if not drs_path.exists():
        raise FileNotFoundError(f"DRS offset file not found: {drs_path}")
    
    offsets = np.loadtxt(drs_path)
    
    # Precompute channel mask to ignore reference pulse 
    gch = np.arange(geometry.N_GLOBAL_CH)
    #mask = (gch % geometry.N_CH_PER_DDB != geometry.N_CH_PER_DDB - 1)
    
    output_dir = Path("../images")
    output_dir.mkdir(exist_ok=True)

    # Open event file once
    with h5py.File("/home/shahjahan/Desktop/SiPM/Analysis_Pipeline/Codes/output/s0534+2201_339_flashCAL_14122025_2_EVBdata.h5", "r") as f:

        roi_all = f["adc/roi_data"]
        cstop_all = f["adc/cstop"]
        skip_cell =f["adc/skip_cell"]

        n_events = roi_all.shape[0]
  

        with ProcessPoolExecutor(max_workers = max(1, os.cpu_count() - 1)) as executor:

            futures = []

            for i in range(1,50): #change this and total in futures to n_events for full processing
                

                roi_slice = roi_all[i]
                #print(f"roi:{roi_slice}")
                cstop_slice = cstop_all[i]
                skip_cell_slice = skip_cell[i]

                futures.append(
                    executor.submit(
                        processEvent,
                        i,
                        roi_slice,
                        cstop_slice,
                        skip_cell_slice,
                        offsets,
                        geometry,
                        pixel_map,
                        gch,
                        output_dir
                    )
                )

            subarray = buildSubarray(geometry)
            with HDF5TableWriter( filename="evts_cta_ready.h5", mode="w", subarray = subarray) as writer:
                for future in tqdm(as_completed(futures), total=50, desc = "Generating images", unit = "event"):
                    try:
                        result = future.result()
                        index = EventIndexContainer()
                        index.event_id = result["event_id"]
                        

                        dl1 = DL1CameraContainer()
                        dl1.image = result["image_LG"].flatten().astype(np.float32)
                        dl1.peak_time = np.zeros_like(dl1.image)
                        

                        writer.write(
                            table_name="dl1/event/telescope/images",
                            containers=[index, dl1],
                        )
                        #future.result()
                    except Exception as e:
                        print("Worker crashed:", e)
                        traceback.print_exc()

if __name__ == "__main__":
    main()
