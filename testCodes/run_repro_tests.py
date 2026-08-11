import os
import shutil
import subprocess
import hashlib
import numpy as np
import h5py
import yaml

PIPE = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes"
PY = "/home/shahjahan/anaconda3/envs/cta/bin/python"
BASE = "/tmp/opencode/sipm_audit/repro_test"
EVB = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes/testFiles/clean6.eve"
CFG = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes/config/config.yaml"
KEYS = ['events/event_id', 'adc/roi_data', 'adc/cstop', 'adc/quality', 'adc/roi_cell', 'adc/skip_cell']

def run(label, workers):
    outdir = os.path.join(BASE, label)
    cfg = os.path.join(BASE, f"{label}.yaml")
    with open(CFG) as f:
        y = yaml.safe_load(f)
    y["io"]["output"] = outdir
    with open(cfg, "w") as f:
        yaml.safe_dump(y, f)
    r = subprocess.run([PY, "wrapper.py", "extract", "--config", cfg,
                        "--evb", EVB, "-w", str(workers)],
                       capture_output=True, text=True, cwd=PIPE,
                       env={**os.environ, "HDF5_USE_FILE_LOCKING": "FALSE"})
    h5 = os.path.join(outdir, "clean6_processed.h5")
    return h5, r.returncode

h1, rc1 = run("out1", 1)
h2, rc2 = run("out2", 4)
h3, rc3 = run("out3", 1)
print(f"  exits: {rc1} {rc2} {rc3}  sizes: {os.path.getsize(h1)} {os.path.getsize(h2)} {os.path.getsize(h3)}")

def content(p):
    with h5py.File(p, "r") as f:
        return {k: f[k][:] for k in KEYS}
A, B, C = content(h1), content(h2), content(h3)

ok = True
def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail}")

check("all runs exit 0", rc1 == rc2 == rc3 == 0)
check("identical file sizes", len({os.path.getsize(h1), os.path.getsize(h2), os.path.getsize(h3)}) == 1)
check("content identical w1 vs w4", all(np.array_equal(A[k], B[k]) for k in KEYS))
check("content identical w1 vs w1", all(np.array_equal(A[k], C[k]) for k in KEYS))
d1 = open(h1, "rb").read(); d2 = open(h2, "rb").read()
if d1 != open(h3, "rb").read():
    print("  NOTE byte-nondeterminism between runs (HDF5 chunk file-placement/order); datasets identical.")
check("content reproducibility (primary)", ok)
print("REPRODUCIBILITY:", "PASS (content-deterministic; byte-nondeterministic)" if ok else "FAIL")
