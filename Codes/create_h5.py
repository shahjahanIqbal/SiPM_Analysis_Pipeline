#!/usr/bin/env python3
import json
import os
import argparse
import numpy as np
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from tqdm import tqdm

import h5py
from astropy import units as u
from astropy.coordinates import EarthLocation, SkyCoord
from astropy.time import Time

from ctapipe.io import EventSource, DataWriter
from ctapipe.core.provenance import Provenance
from ctapipe.instrument import (
    CameraGeometry,
    CameraReadout,
    CameraDescription,
    SubarrayDescription,
    OpticsDescription,
    TelescopeDescription,
)
from ctapipe.containers import (
    ArrayEventContainer,
    SchedulingBlockContainer,
    ObservationBlockContainer,
    ImageParametersContainer,
    CoordinateFrameType,
    ObservingMode,
    PointingMode,
)

from config_loader import load_config
from geometry import CameraLayout
from image_gen import processEvent
from ctapipe.image import brightest_island, number_of_islands, largest_island

from ctapipe.image import ImageProcessor
from ctapipe.image.cleaning import tailcuts_clean
from ctapipe.image import hillas_parameters, number_of_islands
from ctapipe.coordinates import CameraFrame

config      = load_config("config/config.yaml")
geometry    = CameraLayout(config)
N_GLOBAL_CH = geometry.N_GLOBAL_CH
n_samples   = geometry.roi
pixel_map   = geometry.loadPixelMap(f"geometry/{geometry.camera_name}.h5")
offsets     = np.loadtxt(config["calib"]["drsoffset"])
gch         = np.arange(N_GLOBAL_CH)
input_dir   = Path(config["io"]["output"])


# One reference pulse waveform per DDB (64 DDBs x 150 samples)
N_DDB_TOTAL = geometry.N_PCM * geometry.N_DDB

reference_location = EarthLocation(
    lat    = 24.6  * u.deg,
    lon    = 72.7  * u.deg,
    height = 1300  * u.m,
)

def build_subarray(geometry):
    size        = 22.1
    pixel_count = geometry.N_PCM * geometry.N_DDB * 4
    pix_id      = np.arange(pixel_count)

    x = (np.arange(-8, 8) * size) + size / 2
    y = (np.arange(-8, 8) * size) + size / 2
    pix_x, pix_y = np.meshgrid(x, y)
    pix_x    = pix_x.ravel() * u.mm
    pix_y    = pix_y.ravel() * u.mm
    pix_area = (size / 1.05) ** 2 * np.ones(pixel_count) * u.mm ** 2

    geom = CameraGeometry(
        name     = "SiPM",
        pix_id   = pix_id,
        pix_x    = pix_x,
        pix_y    = pix_y,
        pix_area = pix_area,
        pix_type = "square",
    )

    reference_pulse = np.zeros((N_DDB_TOTAL, n_samples))

    readout = CameraReadout(
        name                         = "SiPM",
        sampling_rate                = 1 * u.GHz,
        reference_pulse_shape        = reference_pulse,
        reference_pulse_sample_width = 1 * u.ns,
        n_channels                   = N_DDB_TOTAL,
        n_pixels                     = 256,
        n_samples                    = geometry.roi,
    )

    camera  = CameraDescription(name="SiPM", geometry=geom, readout=readout)

    optics  = OpticsDescription(
        name                    = "Optics",
        size_type               = "UNKNOWN",
        n_mirrors               = 1,
        equivalent_focal_length = 4 * u.m,
        effective_focal_length  = 4 * u.m,
        mirror_area             = 1 * u.m ** 2,
        n_mirror_tiles          = 34,
        reflector_shape         = "UNKNOWN",
    )

    telescope = TelescopeDescription(name="Tel", optics=optics, camera=camera)

    subarray = SubarrayDescription(
        name               = "Array",
        tel_positions      = {1: [0, 0, 0] * u.m},
        tel_descriptions   = {1: telescope},
        reference_location = reference_location,
    )
    return subarray


subarray = build_subarray(geometry)


def _parse_datetime(meta, time_key):
    """Combine Date_UTC (DD.MM.YYYY) with a HH:MM:SS time field into astropy Time."""
    d, m, y = meta["Date_UTC"].split(".")
    return Time(f"{y}-{m}-{d}T{meta[time_key]}", format="isot", scale="utc")


def build_obs_block(meta):
    obs_id = np.uint64(meta["Run_No"])

    coord = SkyCoord(
        ra    = meta["RA (J2000)"],
        dec   = meta["DEC (J2000)"],
        unit  = (u.hourangle, u.deg),
        frame = "icrs",
    )

    t_start      = _parse_datetime(meta, "StartTime_UTC")
    t_stop       = _parse_datetime(meta, "StopTime_UTC")
    duration_min = float(meta["Duration(mins)"]) * u.min

    ob = ObservationBlockContainer()
    ob.obs_id      = obs_id
    ob.sb_id       = obs_id
    ob.producer_id = meta["File_Name"]

    # Pointing: lon=RA, lat=Dec in ICRS frame
    ob.subarray_pointing_lon   = coord.ra.deg  * u.deg
    ob.subarray_pointing_lat   = coord.dec.deg * u.deg
    ob.subarray_pointing_frame = CoordinateFrameType.ICRS

    # Timing
    ob.actual_start_time    = t_start
    ob.actual_duration      = duration_min
    ob.scheduled_start_time = t_start
    ob.scheduled_duration   = duration_min

    return ob


def build_sched_block(meta):
    sb = SchedulingBlockContainer()
    sb.sb_id         = np.uint64(meta["Run_No"])
    sb.producer_id   = meta["Source_Name"]
    sb.pointing_mode = PointingMode.TRACK

    source_lower = meta["Source_Name"].lower()
    if "on" in source_lower and "off" not in source_lower:
        sb.observing_mode = ObservingMode.ON_OFF
    else:
        sb.observing_mode = ObservingMode.UNKNOWN

    return sb


def build_context(meta):
    """Fields that don't fit a ctapipe container — stored as HDF5 file-level attributes."""
    return {
        "OBSERVATION SOURCE_NAME"         : meta["Source_Name"],
        "OBSERVATION MJD"                 : meta["MJD"],
        "OBSERVATION TRANSIT_TIME"        : meta["Transit_Time"],
        "OBSERVATION RA_PRECISE"          : meta["RA (Precise)"],
        "OBSERVATION DEC_PRECISE"         : meta["DEC (Precise)"],
        "OBSERVATION HOUR_ANGLE_START"    : meta["Hour_Angle_Start"],
        "OBSERVATION HOUR_ANGLE_STOP"     : meta["Hour_Angle_Stop"],
        "OBSERVATION ZEN_ANGLE_START"     : meta["Zen_Angle_Start"],
        "OBSERVATION ZEN_ANGLE_STOP"      : meta["Zen_Angle_Stop"],
        "OBSERVATION AZ_ANGLE_START"      : meta["Az_Angle_Start"],
        "OBSERVATION AZ_ANGLE_STOP"       : meta["Az_Angle_Stop"],
        "OBSERVATION SQM_START"           : meta["SQM_Start"],
        "OBSERVATION TRIGGER_THRESHOLD_MV": str(meta["Trigger_Threshold_mV"]),
        "OBSERVATION TRIGGER_LOGIC"       : meta["Trigger_Logic"],
        "OBSERVATION TOTAL_EVENTS"        : str(meta["Total_Events"]),
        "OBSERVATION AVG_TRIGGER_RATE_HZ" : meta["Average_Trigger_Rate(Hz)"],
        "OBSERVATION DURATION_MINS"       : str(meta["Duration(mins)"]),
    }


class SyntheticSource(EventSource):
    """
    Minimal EventSource shim. DataWriter needs this to write subarray and
    observation metadata. No events are generated here — they are injected
    directly via writer() in main().
    """

    def __init__(self, subarray, ob, sb):
        super().__init__(input_url="synthetic")
        self._subarray           = subarray
        self._scheduling_blocks  = {sb.sb_id:  sb}
        self._observation_blocks = {ob.obs_id: ob}
        self._obs_ids            = [ob.obs_id]

    @staticmethod
    def is_compatible(file_path):
        return False

    @property
    def subarray(self):
        return self._subarray

    @property
    def is_simulation(self):
        return False

    @property
    def datalevels(self):
        return ("R1", "DL1")

    @property
    def scheduling_blocks(self):
        return self._scheduling_blocks

    @property
    def observation_blocks(self):
        return self._observation_blocks

    @property
    def obs_ids(self):
        return self._obs_ids

    def _generator(self):
        while False:
            yield




def jsonFinder(h5_path, json_dir):
    json_path = json_dir / f"{h5_path.stem}.json"
    if not json_path.exists():
        raise FileNotFoundError(
            f"Missing JSON for {h5_path.name}: expected {json_path}"
        )
    return json_path

def mad(data):
    return np.median(np.abs(data - np.median(data)))

def compute_hillas(event, source, cleaning_config):
    """
    Runs image cleaning and Hillas parametrization on the DL1 image.
    Fills event.dl1.tel[1].parameters in place.
    Returns False if the image is too faint to parametrize.
    """

    tel = event.dl1.tel[1]
    image = tel.image
    med_abs_dev = mad(image.flatten())
    # Tailcuts cleaning — tune picture/boundary to your camera
    camera_geom = source.subarray.tel[1].camera.geometry
    clean_mask = tailcuts_clean(
        camera_geom,
        image,
        picture_thresh   = 6 * med_abs_dev,  #cleaning_config["picture_thresh"],
        boundary_thresh  = med_abs_dev,      #cleaning_config["boundary_thresh"],
        min_number_picture_neighbors = 2,
    )

    n_islands, island_labels = number_of_islands(camera_geom, clean_mask)
    brightest_mask_sq = brightest_island(n_islands, island_labels, image)
    cleaned = image * brightest_mask_sq

    if cleaned.sum() == 0 or clean_mask.sum() < 5:
        return False   # too few pixels survive cleaning

    hillas = hillas_parameters(camera_geom, cleaned)
    tel.parameters = ImageParametersContainer()
    tel.parameters.hillas = hillas
    return True

def main(input_file, output_dir, json_path, dl2_flag):

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{input_file.stem}_cta_cont.h5"

    with open(json_path) as jf:
        meta = json.load(jf)

    obs_id  = np.uint64(meta["Run_No"])
    ob      = build_obs_block(meta)
    sb      = build_sched_block(meta)
    context = build_context(meta)

    source = SyntheticSource(subarray=subarray, ob=ob, sb=sb)

    PROV = Provenance()
    PROV.start_activity("dl1_write")

    with h5py.File(input_file, "r") as f:
        roi_slices   = f["adc/roi_data"][:]
        cstop_slices = f["adc/cstop"][:]
        skip_slices  = f["adc/skip_cell"][:]
        n_events     = roi_slices.shape[0]

    with ProcessPoolExecutor(max_workers=max(1, os.cpu_count() - 1)) as executor:

        futures = {
            executor.submit(
                processEvent,
                i,
                roi_slices[i],
                cstop_slices[i],
                skip_slices[i],
                offsets,
                geometry,
                pixel_map,
                gch,
                None,
            ): i
            for i in range(n_events)
        }

        cleaning_config = {
                            "picture_thresh" : 10,   
                            "boundary_thresh": 5,
                            "min_neighbors"  : 2,
                            }

        with DataWriter(
            event_source     = source,
            output_path      = output_file,
            overwrite        = True,
            write_dl1_images = True,
            write_dl1_parameters = dl2_flag
        ) as writer:

            for future in tqdm(as_completed(futures), total=n_events,
                               desc=f"Writing {input_file.stem}", unit = "Events"):
                try:
                    result = future.result()
                except Exception as e:
                    print(f"Worker crashed for event {futures[future]}: {e}")
                    continue

                event = ArrayEventContainer()

                event.index.obs_id   = obs_id
                event.index.event_id = np.uint64(result["event_id"])

                event.trigger.tels_with_trigger = [1]
                event.trigger.tel[1].time       = 0.0

                tel = event.dl1.tel[1]
                tel.is_valid = True

                # Use LG if any HG pixel saturated, else HG
                if np.any(result["saturation_mask"]):
                    tel.image = result["image_LG"].flatten().astype(np.float32)
                else:
                    tel.image = result["image_HG"].flatten().astype(np.float32)

                tel.peak_time  = result["time_HG"].flatten().astype(np.float32)
                tel.parameters = ImageParametersContainer()
                compute_hillas(event, source, cleaning_config)

                writer(event)

    # DataWriter does not accept context_metadata as a constructor argument in
    # this version — write the observation attributes directly to the HDF5 file
    # after the writer has closed and flushed.
    with h5py.File(output_file, "a") as f:
        grp = f.require_group("CONTEXT/OBSERVATION")
        for key, value in context.items():
            # Keys are "OBSERVATION FIELDNAME" — store just the field part
            attr_name = key.split(" ", 1)[-1]
            grp.attrs[attr_name] = value

    PROV.finish_activity("dl1_write")
    print(f"Written: {output_file}")




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert pipeline H5 to ctapipe DL1 H5")
    parser.add_argument("output_dir", type=str, default = "events_cta"
                        help="Output directory for DL1 files")
    parser.add_argument("--json_dir", type=str, default="OBS_INFO",
                        help="Directory containing per-run JSON metadata files")
    parser.add_argument("--no-dl2", action="store_false",  help = "Don't compute Hillas Parameters. Use it for processing calibration files")
    args = parser.parse_args()

    input_files = np.atleast_1d(np.loadtxt(input_dir / "output_files.txt", dtype=str))

    for file in input_files:
        h5_file = Path(file)
        try:
            json_path = jsonFinder(h5_file, json_dir=Path(args.json_dir))
        except FileNotFoundError as e:
            print(f"Skipping {h5_file.name}: {e}")
            continue

        print(f"Processing {h5_file.name}")
        main(
            input_file = h5_file,
            output_dir = Path(args.output_dir),
            json_path  = json_path,
            dl2_flag = args.dl2
        )