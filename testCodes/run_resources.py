import os
import json
import shutil
import subprocess
import time
import yaml

import audit_env

PIPE = audit_env.CODES
PY = audit_env.PY
BASE = os.path.join(audit_env.WORK, "resources_test")
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(BASE, exist_ok=True)
os.makedirs(os.path.join(BASE, "obs"), exist_ok=True)

EVB = audit_env.ensure_evb()
CFG = audit_env.ensure_config()
with open(CFG) as f:
    y = yaml.safe_load(f)
y["io"]["output"] = BASE
CFG = os.path.join(BASE, "config.yaml")
with open(CFG, "w") as f:
    yaml.safe_dump(y, f)

# observation metadata for createh5: reuse the repo OBS_INFO json when present,
# otherwise synthesize the same structure inline so the section runs anywhere.
obs_json = os.path.join(PIPE, "OBS_INFO", "s0534+2201_419_NOR_15012026_1_EVBdata.json")
META = {"Run_No": 419, "Source_Name": "crab_on", "File_Name": "s0534+2201_419",
        "Date_UTC": "15.01.2026", "MJD": "61055", "RA (Precise)": "05:36:06",
        "DEC (Precise)": "22:01:50", "RA (J2000)": "05:36:06", "DEC (J2000)": "22:01:50",
        "Transit_Time": "22:34", "StartTime_UTC": "17:25:02", "Hour_Angle_Start": "0.34",
        "Zen_Angle_Start": "5.40", "Az_Angle_Start": "62.31", "SQM_Start": "20.83",
        "StopTime_UTC": "18:34:57", "Hour_Angle_Stop": "1.51", "Zen_Angle_Stop": "20.97",
        "Az_Angle_Stop": "87.53", "Trigger_Threshold_mV": 150, "Trigger_Logic": "3NN",
        "Total_Events": 47013, "Average_Trigger_Rate(Hz)": "11.2", "Duration(mins)": 69}
meta = META
if os.path.exists(obs_json):
    with open(obs_json) as f:
        meta = json.load(f)
with open(os.path.join(BASE, "obs", "clean6.json"), "w") as f:
    json.dump(meta, f)

env = {**os.environ, "HDF5_USE_FILE_LOCKING": "FALSE"}

TIME_BIN = shutil.which("/usr/bin/time") or shutil.which("time")

def timed(label, argv, expect_file):
    t0 = time.time()
    r = subprocess.run([PY, "wrapper.py", *argv], capture_output=True, text=True,
                       cwd=PIPE, env=env)
    dt = time.time() - t0
    mb = os.path.getsize(expect_file) / 1e6 if os.path.exists(expect_file) else None
    print(f"  {label}: exit={r.returncode} wall={dt:.2f}s out_mb={mb:.2f}" if mb else
          f"  {label}: exit={r.returncode} wall={dt:.2f}s (no output)")
    return r, dt

r1, dt1 = timed("extract w1", ["extract", "--config", CFG, "--evb", EVB, "-w", "1"],
                os.path.join(BASE, "clean6_processed.h5"))
r4, dt4 = timed("extract w4", ["extract", "--config", CFG, "--evb", EVB, "-w", "4"],
                os.path.join(BASE, "clean6_processed.h5"))
print(f"  speedup w1->w4 = {dt1/dt4:.2f}x")

t0 = time.time()
r = timed("createh5(6 ev)", ["createh5", os.path.join(BASE, "dl1"),
                             "--json-dir", os.path.join(BASE, "obs"),
                             "--config", CFG],
          os.path.join(BASE, "dl1", "clean6_processed_cta_cont.h5"))

# /usr/bin/time peak RSS for the two heavy steps (skipped if `time` is absent)
for label, argv in [("extract w1 peak-rss", ["extract", "--config", CFG, "--evb", EVB, "-w", "1"]),
                    ("extract w4 peak-rss", ["extract", "--config", CFG, "--evb", EVB, "-w", "4"]),
                    ("createh5 peak-rss", ["createh5", os.path.join(BASE, "dl1"),
                                           "--json-dir", os.path.join(BASE, "obs"), "--config", CFG])]:
    if TIME_BIN is None:
        print(f"  {label}: skipped (no /usr/bin/time)")
        continue
    rr = subprocess.run([TIME_BIN, "-v", PY, "wrapper.py", *argv],
                        capture_output=True, text=True, cwd=PIPE, env=env)
    mem = [l for l in rr.stderr.splitlines() if "Maximum resident" in l]
    print(f"  {label}: exit={rr.returncode} {mem[0].strip() if mem else 'no-time'}")

# sparse-H5 disk behavior
big = os.path.join(audit_env.WORK, "evb_test", "veryLargeEventIDs", "veryLargeEventIDs_processed.h5")
if os.path.exists(big):
    import h5py
    print(f"  sparse H5 (100005 rows): disk_mb={os.path.getsize(big)/1e6:.2f}")
    with h5py.File(big, "r") as f:
        d = f["adc/roi_data"]
        print(f"    dataset shape={d.shape} chunks={d.chunks} compression={d.compression} fillvalue={d.fillvalue}")

# real-EVB registry timing (memory-only; requires the optional data file, which
# is gitignored and machine-specific -- set SIPM_REAL_EVB to enable on another box)
real = os.environ.get("SIPM_REAL_EVB", os.path.join(audit_env.REPO, "EVB_data", "20240109_sv", "run_339.sv0b.eve"))
if os.path.exists(real):
    import numpy as np
    from registry_creator import fetchPacketIndices, build_event_registry_parallel
    t0 = time.time()
    data = np.fromfile(real, dtype=np.uint32, count=111040000)
    print(f"  real EVB: loaded {data.nbytes/1e9:.2f} GB in {time.time()-t0:.2f}s")
    t0 = time.time()
    s, e = fetchPacketIndices(data, 0xFBDA, 0xEDAC)
    t1 = time.time()
    reg = build_event_registry_parallel(data, s, e)
    t2 = time.time()
    print(f"  real EVB registry: fetch={t1-t0:.2f}s build={t2-t1:.2f}s events={len(reg)}")
