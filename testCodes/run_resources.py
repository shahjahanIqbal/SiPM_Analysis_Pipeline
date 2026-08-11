import os
import shutil
import subprocess
import time
import yaml

PIPE = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes"
PY = "/home/shahjahan/anaconda3/envs/cta/bin/python"
BASE = "/tmp/opencode/sipm_audit/resources_test"
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(BASE, exist_ok=True)
os.makedirs(os.path.join(BASE, "obs"), exist_ok=True)

EVB = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes/testFiles/clean6.eve"
with open("/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes/config/config.yaml") as f:
    y = yaml.safe_load(f)
y["io"]["output"] = BASE
CFG = os.path.join(BASE, "config.yaml")
with open(CFG, "w") as f:
    yaml.safe_dump(y, f)

import shutil as _sh
_sh.copy("/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes/OBS_INFO/s0534+2201_419_NOR_15012026_1_EVBdata.json",
         os.path.join(BASE, "obs", "clean6.json"))

env = {**os.environ, "HDF5_USE_FILE_LOCKING": "FALSE"}

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

# /usr/bin/time peak RSS for the two heavy steps
for label, argv in [("extract w1 peak-rss", ["extract", "--config", CFG, "--evb", EVB, "-w", "1"]),
                    ("extract w4 peak-rss", ["extract", "--config", CFG, "--evb", EVB, "-w", "4"]),
                    ("createh5 peak-rss", ["createh5", os.path.join(BASE, "dl1"),
                                           "--json-dir", os.path.join(BASE, "obs"), "--config", CFG])]:
    rr = subprocess.run(["/usr/bin/time", "-v", PY, "wrapper.py", *argv],
                        capture_output=True, text=True, cwd=PIPE, env=env)
    mem = [l for l in rr.stderr.splitlines() if "Maximum resident" in l]
    print(f"  {label}: exit={rr.returncode} {mem[0].strip() if mem else 'no-time'}")

# sparse-H5 disk behavior
big = "/tmp/opencode/sipm_audit/evb_test/veryLargeEventIDs/veryLargeEventIDs_processed.h5"
if os.path.exists(big):
    import h5py
    print(f"  sparse H5 (100005 rows): disk_mb={os.path.getsize(big)/1e6:.2f}")
    with h5py.File(big, "r") as f:
        d = f["adc/roi_data"]
        print(f"    dataset shape={d.shape} chunks={d.chunks} compression={d.compression} fillvalue={d.fillvalue}")

# real-EVB registry timing (memory-only)
real = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/EVB_data/20240109_sv/run_339.sv0b.eve"
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
