#!/usr/bin/env python3
import yaml
from pathlib import Path
import logging

#USE PYDANTIC FOR EASIER VALIDATION

REQUIRED_STRUCTURE = {
    "camera_geometry": [
        "pcm_count",
        "ddb_count",
        "channel_count",
        "expected_packets_per_event",
        "readout",
        "layout",
    ],
    "data": ["evbfilepath"],
    "calib": ["drsoffset"],
    "io": ["output"]
}


def is_valid_config(cfg):
    '''
        Input: cfg (dict)
        Output: bool
        Checks that the top-level sections camera_geometry, data, calib, and io are
        present and are themselves dicts. Verifies that evbfilepath, drsoffset, and
        output are non-empty, and that every key listed in REQUIRED_STRUCTURE exists
        under camera_geometry. Returns False at the first missing or malformed field.

    '''
    if not isinstance(cfg, dict):
        return False

    if ("camera_geometry" not in cfg) or ("data" not in cfg) or ("calib" not in cfg) or ("io" not in cfg):
        return False

    cam = cfg.get("camera_geometry")
    dat = cfg.get("data")
    calib = cfg.get("calib")
    io = cfg.get("io")

    if not all(isinstance(x, dict) for x in [cam, dat, calib, io]):
        return False
    if not dat.get("evbfilepath"):
        return False

    if not calib.get("drsoffset"):
        return False

    if not io.get("output"):
        return False

    for key in REQUIRED_STRUCTURE["camera_geometry"]:
        if key not in cam:
            return False
    
    for key in REQUIRED_STRUCTURE["data"]:
        if key not in dat:
            return False

    for key in REQUIRED_STRUCTURE["calib"]:
        if key not in calib:
            return False

    for key in REQUIRED_STRUCTURE["io"]:
        if key not in io:
            return False 

    return True

# NEEDS COMMENTING OF DTYPES FOR EACH KEY 

def config_creator(path):
    '''
        Input: path (str or Path)
        Output: None; writes a YAML file to disk
        Builds a skeleton config dict with all required keys present and data paths
        set to None. Writes it to the given path using yaml.safe_dump. Intended to be
        called automatically when the config is missing or corrupted. The user must
        fill in evbfilepath, drsoffset, and output before running the pipeline.

    '''
    config_file = {
        "camera_geometry": {
            "name": "SiPMCamera",
            "pcm_count": 16,
            "ddb_count": 4,
            "channel_count": 9,
            "expected_packets_per_event": 64,
            "readout": {
                "roi_samples": 150,
                "adc_bits": 14,
         
                "channel_zero_dual_map": True,
            },
            "layout": {
                "rows": 16,
                "cols": 16,
                "ordering": "column-major",
                "pixel_size_mm": 22.1,
                "pixel_gap_mm": 0.05,
            },
            
        },
        "data":{
                "evbfilepath":None
        },
        "calib":{
                "drsoffset": None
        },
        "io":{
             "output": None
        }
    }
    with open(path, "w") as f:
        yaml.safe_dump(config_file, f, sort_keys=False)

def load_config(path = "../config/config.yaml"):
    '''
        Input: path (str or Path, default "../config/config.yaml")
        Output: dict
        Loads and parses the YAML config. If the file does not exist, cannot be parsed,
        or fails is_valid_config, it calls config_creator to write a fresh default and
        warns the user to populate the paths. Always returns a dict, never raises on
        a missing or corrupt file.
'''
    file_path = Path(path)

    if not file_path.exists():
        logging.warning("Config file missing. Creating default.")
        print(("Config file missing. Creating default."))
        file_path.parent.mkdir(parents=True, exist_ok=True)
        config_creator(file_path)
        return yaml.safe_load(file_path.read_text())

    try:
        with open(file_path, "r") as f:
            cfg = yaml.safe_load(f)

    except yaml.YAMLError:
        logging.error("Config file is corrupted YAML. Recreating default.")
        config_creator(file_path)
        return yaml.safe_load(file_path.read_text())

    except Exception as e:
        logging.error(f"Unexpected config load error: {e}")
        config_creator(file_path)
        return yaml.safe_load(file_path.read_text())

    if not is_valid_config(cfg):
        print("Config file is corrupt. Recreating with default values...")
        logging.error("Config file incomplete or invalid structure. Recreating default.")
        
        config_creator(file_path)
        print("WARNING: Ensure the data, output and calib paths are entered!")
        return yaml.safe_load(file_path.read_text())

    return cfg