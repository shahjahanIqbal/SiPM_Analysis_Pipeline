#!/usr/bin/env python3
import json
import os
import logging
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
from ctapipe.image import brightest_island, number_of_islands

from ctapipe.image import concentration_parameters
from ctapipe.image.cleaning import tailcuts_clean
from ctapipe.image import hillas_parameters, number_of_islands




reference_location = EarthLocation(
    lat    = 24.6  * u.deg,
    lon    = 72.7  * u.deg,
    height = 1300  * u.m,
)

def build_subarray(geometry):
    '''
        Input: geometry (CameraLayout)
        Output: ctapipe SubarrayDescription
        Builds the full camera description including a CameraReadout with reference
        pulse shape, CameraGeometry with physical pixel positions in mm, and an
        OpticsDescription. The telescope is placed at a fixed reference location
        (24.6 N, 72.7 E, 1300 m). This is the production version used by main().
    '''
    size        = 22.1
    pixel_count = geometry.N_PCM * geometry.N_DDB * 4
    pix_id      = np.arange(pixel_count)

    x = (np.arange(-8, 8) * size) + size / 2
    y = (np.arange(-8, 8) * size) + size / 2
    pix_x, pix_y = np.meshgrid(x, y)
    pix_x    = pix_x.ravel() * u.mm
    pix_y    = pix_y.ravel() * u.mm
    pix_area = (size / 1.05) ** 2 * np.ones(pixel_count) * u.mm ** 2
    reference_pulse = np.zeros((geometry.N_PCM * geometry.N_DDB, geometry.roi)) #(Total No. of DDB, No. of samples)
    geom = CameraGeometry(
        name     = "SiPM",
        pix_id   = pix_id,
        pix_x    = pix_x,
        pix_y    = pix_y,
        pix_area = pix_area,
        pix_type = "square",
    )

    

    readout = CameraReadout(
        name                         = "SiPM",
        sampling_rate                = 1 * u.GHz,
        reference_pulse_shape        = reference_pulse,
        reference_pulse_sample_width = 1 * u.ns,
        n_channels                   = geometry.N_PCM * geometry.N_DDB,
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





def _parse_datetime(meta, time_key):
    """
        Input: meta (dict from JSON), time_key (str, e.g. "StartTime_UTC")
        Output: astropy Time in UTC isot format
        Splits the Date_UTC field (DD.MM.YYYY) and recombines it with the HH:MM:SS
        value at time_key into an ISO-8601 string. Used to populate the ctapipe
        ObservationBlockContainer timing fields.
    """
    d, m, y = meta["Date_UTC"].split(".")
    return Time(f"{y}-{m}-{d}T{meta[time_key]}", format="isot", scale="utc")


def build_obs_block(meta):
    '''
        Input: meta (dict from JSON run metadata)
        Output: ctapipe ObservationBlockContainer
        Populates obs_id, sb_id, pointing coordinates (RA/Dec in ICRS), start time,
        and both actual and scheduled durations from the run JSON. RA is parsed as
        hour angles; Dec is in degrees.
    '''
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
    '''
        Input: meta (dict from JSON run metadata)
        Output: ctapipe SchedulingBlockContainer
        Sets sb_id, producer_id (source name), and pointing mode (always TRACK).
        Infers observing mode as ON_OFF if "on" appears in the source name without
        "off"; otherwise defaults to UNKNOWN.
    '''
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
    '''
        Input: meta (dict from JSON run metadata)
        Output: dict mapping string keys to string values
        Extracts observatory-specific fields (hour angle, zenith angle, azimuth, SQM,
        trigger parameters, event count, trigger rate). The returned dict is written as 
        HDF5 group attributes under CONTEXT/OBSERVATION.
        Fields that don't fit a ctapipe container — stored as HDF5 file-level attributes.
    '''
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
        Inherits from ctapipe EventSource. Accepts a SubarrayDescription,
        ObservationBlockContainer, and SchedulingBlockContainer at construction.
        Exposes them through the properties required by DataWriter without reading
        any real file. The _generator method yields nothing; events are injected
        directly by calling the writer in main().
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
    '''
        Input: h5_path (Path), json_dir (Path)
        Output: Path to the corresponding JSON file
        Replaces the "_processed" suffix in the H5 stem with nothing and appends
        .json, then checks for the file in json_dir. Raises FileNotFoundError with
        a descriptive message if absent. Called once per input file in the main loop.

    '''
    json_path = json_dir / f"{h5_path.stem.replace('_processed', '')}.json"
    if not json_path.exists():
        raise FileNotFoundError(
            f"Missing JSON for {h5_path.name}: expected {json_path}"
        )
    return json_path

def mad(data):
    '''
        Input: data (array of any shape)
        Output: float, median absolute deviation
        Computes median absolute deviation over the flattened array. Used in
        compute_hillas to set adaptive cleaning thresholds relative to the noise
        level of the image.

    '''
    return np.median(np.abs(data - np.median(data)))

def compute_hillas(event, source):
    """
        Input: event (ArrayEventContainer), source (SyntheticSource)
        Output: bool — True if parametrization succeeded, False otherwise
        Runs tailcuts_clean with picture/boundary thresholds of 6*MAD and 1*MAD.
        Identifies the brightest connected island and skips the event if fewer than
        3 pixels survive. Computes Hillas and concentration parameters and writes
        them to event.dl1.tel[1].parameters in place.
    """

    tel = event.dl1.tel[1]
    image = tel.image
    med_abs_dev = mad(image.flatten())

    if med_abs_dev == 0:
        return False
    # Tailcuts cleaning — tune picture/boundary to your camera
    camera_geom = source.subarray.tel[1].camera.geometry
    clean_mask = tailcuts_clean(
        camera_geom,
        image,
        picture_thresh   = 6 * med_abs_dev,  
        boundary_thresh  = med_abs_dev,      
        min_number_picture_neighbors = 2,
    )

    n_islands, island_labels = number_of_islands(camera_geom, clean_mask)
    brightest_mask_sq = brightest_island(n_islands, island_labels, image)
    cleaned = image * brightest_mask_sq

    if cleaned.sum() == 0 or brightest_mask_sq.sum() < 3:
        return False   # too few pixels survive cleaning

    hillas = hillas_parameters(camera_geom, cleaned)
    conc = concentration_parameters(camera_geom, image, hillas)

    tel.parameters = ImageParametersContainer()
    tel.parameters.hillas = hillas
    tel.parameters.concentration  = conc
    return True

def main(input_file, output_dir, json_path, config, dl2_flag):
    '''
        Input: input_file (Path), output_dir (Path), json_path (Path or None),
               config (dict), dl2_flag (bool)
        Output: none; writes a ctapipe-format DL1 HDF5 to output_dir
        Reads the preprocessed HDF5, submits processEvent for all events in parallel,
        and writes results through DataWriter. For observation runs (dl2_flag=True) it
        populates scheduling/observation blocks and writes Hillas parameters. For
        calibration runs (dl2_flag=False) dummy metadata blocks are used. Context
        attributes are appended after the DataWriter session closes.
    '''

    drs_path = Path(config["calib"]["drsoffset"])
    if not drs_path.exists():
        raise FileNotFoundError(f"DRS offset file not found: {drs_path}")
    offsets = np.loadtxt(drs_path)

    geometry    = CameraLayout(config)
    N_GLOBAL_CH = geometry.N_GLOBAL_CH
    pixel_map   = geometry.loadPixelMap(f"geometry/{geometry.camera_name}.h5")
    gch         = np.arange(N_GLOBAL_CH)


    # One reference pulse waveform per DDB (64 DDBs x 150 samples)
    #N_DDB_TOTAL = geometry.N_PCM * geometry.N_DDB


    subarray = build_subarray(geometry)


    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{input_file.stem}_cta_cont.h5"
    obs_id  = np.uint64(0)   # default for calibration files
    context = {}
    if dl2_flag:
        if json_path is None:
            raise ValueError(
                "json_path is required. "
                "Pass --json-dir or use --no-dl2 for calibration files."
            )
        with open(json_path) as jf:
            meta = json.load(jf)

        obs_id  = np.uint64(meta["Run_No"])
        ob      = build_obs_block(meta)
        sb      = build_sched_block(meta)
        context = build_context(meta)
        source = SyntheticSource(subarray=subarray, ob=ob, sb=sb)
    else:
        dummy_sb = SchedulingBlockContainer()
        dummy_sb.sb_id = np.uint64(0)
        dummy_ob = ObservationBlockContainer()
        dummy_ob.obs_id = np.uint64(0)
        dummy_ob.sb_id  = np.uint64(0)
        source = SyntheticSource(subarray=subarray, ob=dummy_ob, sb=dummy_sb)

    PROV = Provenance()
    PROV.start_activity("dl1_write")

    with h5py.File(input_file, "r") as f:
        roi_slices   = f["adc/roi_data"][:]
        cstop_slices = f["adc/cstop"][:]
        skip_slices  = f["adc/skip_cell"][:]
        event_ids    = f["events/event_id"][:]
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


        with DataWriter(
            event_source     = source,
            output_path      = output_file,
            overwrite        = True,
            write_dl1_images = True,
            write_dl1_parameters = dl2_flag
        ) as writer:

            for future in tqdm(as_completed(futures), total=n_events,
                               desc=f"Writing", unit = "Events"):
                try:
                    result = future.result()
                except Exception as e:
                    logging.error(f"Worker crashed for event {futures[future]}: {e}")
                    continue

                event = ArrayEventContainer()

                event.index.obs_id   = obs_id
                event.index.event_id = np.uint64(event_ids[futures[future]])

                event.trigger.tels_with_trigger = [1]
                event.trigger.tel[1].time       = 0.0

                tel = event.dl1.tel[1]
                tel.is_valid = True

                # Use LG if any HG pixel saturated, else HG
                '''By default ctapipe seems to flip the image along the horizontal axis and store them
                   Maybe it generates the flattened image from bottom to top
                   The indexing of the flattened array is reversed as a workaround
                   '''
                if np.any(result["saturation_mask"]):
                    tel.image = result["image_LG"][::-1].flatten().astype(np.float32) 
                else:
                    tel.image = result["image_HG"][::-1].flatten().astype(np.float32)

                tel.peak_time  = result["time_HG"][::-1].flatten().astype(np.float32)
                tel.parameters = ImageParametersContainer()
                if dl2_flag:
                    compute_hillas(event, source)

                writer(event)

    with h5py.File(output_file, "a") as f:
        grp = f.require_group("CONTEXT/OBSERVATION")
        for key, value in context.items():
            
            attr_name = key.split(" ", 1)[-1]
            grp.attrs[attr_name] = value

    PROV.finish_activity("dl1_write")
    print(f"Written: {output_file}")




if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert pipeline H5 to ctapipe DL1 H5")
    parser.add_argument("output_dir", type=str, default = "events_cta", help="Output directory for DL1 files")
    parser.add_argument("--json-dir", type=str, default="OBS_INFO", help="Directory containing per-run JSON metadata files")
    parser.add_argument("--no-dl2", action="store_true",  help = "Skip Hillas parameter computation. Use it for processing calibration files")
    parser.add_argument("--config", type = str, default = 'config/config.yaml', help = "Path to the config file. Default: config/config.yaml")

    args = parser.parse_args()
    config      = load_config(args.config)
    input_dir   = Path(config["io"]["output"])

    input_files = np.atleast_1d(np.loadtxt(input_dir / "output_files.txt", dtype=str))
    #dl2 = args.no_dl2
    for file in input_files:
        h5_file = Path(file)
        json_path = None
        if not args.no_dl2: #Skip importing json if dl2 write is not enabled (for calib files)
            try:
                json_path = jsonFinder(h5_file, json_dir=Path(args.json_dir))
            except FileNotFoundError as e:
                print(f"ERROR: {e} \nSkipping file")
                continue
        else:
            print(f"Calibration mode: skipping JSON and Hillas for {h5_file.name}")
        print(f"Processing {h5_file.name}")
        main(
            input_file = h5_file,
            output_dir = Path(args.output_dir),
            json_path  = json_path,
            config = config,
            dl2_flag = not args.no_dl2
        )