#!/usr/bin/env python3
"""Config tests for the SiPM pipeline. Runs wrapper.py extract with mutated configs
and checks: exit code, config-overwrite behavior, error clarity."""
import hashlib
import os
import subprocess
import sys
import yaml

import audit_env

CODES = audit_env.CODES
WORK = os.path.join(audit_env.WORK, "config_test")
CFGS = os.path.join(WORK, "cfgs")
PY = audit_env.PY
DRS = audit_env.ensure_drs()
audit_env.ensure_evb()

BASE = {
    "camera_geometry": {
        "name": "SiPMCamera",
        "pcm_count": 16,
        "ddb_count": 4,
        "channel_count": 9,
        "expected_packets_per_event": 64,
        "readout": {"roi_samples": 150, "adc_bits": 14, "channel_zero_dual_map": True},
        "layout": {"rows": 16, "cols": 16, "ordering": "column-major",
                   "pixel_size_mm": 22.1, "pixel_gap_mm": 0.05},
    },
    "data": {"evbfilepath": audit_env.CLEAN6},
    "calib": {"drsoffset": DRS},
    "io": {"output": os.path.join(WORK, "out_valid")},
}

def h(path):
    if not os.path.exists(path):
        return None
    return hashlib.md5(open(path, "rb").read()).hexdigest()

def run_case(name, cfg_text, timeout=90):
    os.makedirs(CFGS, exist_ok=True)
    path = os.path.join(CFGS, f"{name}.yaml")
    with open(path, "w") as f:
        f.write(cfg_text)
    before = h(path)
    env = dict(os.environ)
    env["MPLBACKEND"] = "Agg"
    proc = subprocess.run(
        [PY, "wrapper.py", "extract", "--config", path],
        cwd=CODES, env=env, capture_output=True, text=True, timeout=timeout,
    )
    after = h(path)
    out = (proc.stdout + proc.stderr).strip()
    first_err = next((l for l in out.splitlines() if "rror" in l or "ERROR" in l), "")
    print(f"== {name} ==")
    print(f"   exit={proc.returncode} overwritten={before != after}")
    print(f"   errline={first_err[:120]!r}")
    return proc.returncode, before != after

def write(path, d):
    with open(path, "w") as f:
        yaml.safe_dump(d, f, sort_keys=False)

def main():
    os.makedirs(WORK, exist_ok=True)
    valid = yaml.safe_dump(BASE, sort_keys=False)
    res = {}

    # 1 valid
    r = run_case("1_valid", valid); res["1_valid"] = r
    # 2 missing config (nonexistent path)
    r = run_case("2_missing", "garbage")
    # manually point at a nonexistent path
    p = os.path.join(CFGS, "2_missing.yaml")
    os.remove(p)
    before = None
    subprocess.run([PY, "wrapper.py", "extract", "--config", p],
                   cwd=CODES, capture_output=True, text=True, timeout=90)
    print("== 2_missing (nonexistent path) =="); print("   config created:", os.path.exists(p))
    # 3 malformed YAML
    r = run_case("3_malformed", "camera_geometry: [unclosed\n  data: {")
    # 4 empty config
    r = run_case("4_empty", "")
    # 5 missing camera_geometry
    d = dict(BASE); del d["camera_geometry"]
    r = run_case("5_no_camera_geometry", yaml.safe_dump(d, sort_keys=False))
    # 6 missing data
    d = dict(BASE); del d["data"]
    r = run_case("6_no_data", yaml.safe_dump(d, sort_keys=False))
    # 7 missing calib
    d = dict(BASE); del d["calib"]
    r = run_case("7_no_calib", yaml.safe_dump(d, sort_keys=False))
    # 8 missing io
    d = dict(BASE); del d["io"]
    r = run_case("8_no_io", yaml.safe_dump(d, sort_keys=False))
    # 9 missing EVB path
    d = dict(BASE); d["data"] = {"evbfilepath": None}
    r = run_case("9_missing_evb_path", yaml.safe_dump(d, sort_keys=False))
    # 10 missing DRS offset
    d = dict(BASE); d["calib"] = {"drsoffset": None}
    r = run_case("10_missing_drs_path", yaml.safe_dump(d, sort_keys=False))
    # 11 missing output path
    d = dict(BASE); d["io"] = {"output": None}
    r = run_case("11_missing_output", yaml.safe_dump(d, sort_keys=False))
    # 12 nonexistent EVB file (path present)
    d = dict(BASE); d["data"] = {"evbfilepath": os.path.join(audit_env.WORK, "NONEXISTENT.eve")}
    r = run_case("12_nonexistent_evb", yaml.safe_dump(d, sort_keys=False))
    # 13 nonexistent DRS offset file (path present)
    d = dict(BASE); d["calib"] = {"drsoffset": os.path.join(audit_env.WORK, "NONEXISTENT.cofsm")}
    r = run_case("13_nonexistent_drs", yaml.safe_dump(d, sort_keys=False))
    # 14 malformed nested camera config
    d = dict(BASE); d["camera_geometry"]["layout"] = "not-a-dict"
    r = run_case("14_bad_layout", yaml.safe_dump(d, sort_keys=False))
    # 15 incorrect ROI (non-int)
    d = dict(BASE); d["camera_geometry"]["readout"]["roi_samples"] = "abc"
    r = run_case("15_bad_roi_str", yaml.safe_dump(d, sort_keys=False))
    # 16 incorrect channel count
    d = dict(BASE); d["camera_geometry"]["channel_count"] = 8
    r = run_case("16_channel_count_8", yaml.safe_dump(d, sort_keys=False))
    # 17 incorrect PCM/DDB counts
    d = dict(BASE); d["camera_geometry"]["pcm_count"] = 8; d["camera_geometry"]["ddb_count"] = 2
    r = run_case("17_bad_pcm_ddb", yaml.safe_dump(d, sort_keys=False))

if __name__ == "__main__":
    main()
