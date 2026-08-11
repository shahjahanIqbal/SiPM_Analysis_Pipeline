import os
import sys
import subprocess
import glob
import numpy as np
import h5py

PIPE = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes"
PY = "/home/shahjahan/anaconda3/envs/cta/bin/python"
BASE = "/tmp/opencode/sipm_audit/parallel_test"
EVB = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes/testFiles/clean6.eve"

os.makedirs(BASE, exist_ok=True)
def make_conf(tag):
    outd = os.path.join(BASE, tag)
    os.makedirs(outd, exist_ok=True)
    conf = os.path.join(BASE, f"{tag}_conf.yaml")
    with open(conf, "w") as f:
        f.write(f"""
camera_geometry:
  name: SiPMCamera
  pcm_count: 16
  ddb_count: 4
  channel_count: 9
  expected_packets_per_event: 64
  readout:
    roi_samples: 150
  layout:
    rows: 16
    cols: 16
data:
  evbfilepath: {EVB}
calib:
  drsoffset: /home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes/DRS_OFFSET/all_cdm_ddb_drsoffsets_fro_09112024_1.cofsm
io:
  output: {outd}
""")
    return conf

def run_extract(workers, tag):
    outd = os.path.join(BASE, tag)
    conf = make_conf(tag)
    h5 = os.path.join(outd, "clean6_processed.h5")
    cmd = [PY, os.path.join(PIPE, "wrapper.py"), "extract", "--config", conf]
    if workers is not None:
        cmd += ["--workers", str(workers)]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=outd)
    if not os.path.exists(h5):
        print(f"  {tag}: exit={p.returncode} NO H5; stderr tail: {p.stderr[-400:]}")
        return None
    return h5

def read_summary(h5):
    with h5py.File(h5, "r") as h:
        adc = h["adc/roi_data"]
        n = adc.shape[0]
        qual = h["adc/quality"][()]
        ids = h["events/event_id"][()]
        roi = h["adc/roi_cell"][()]
        skip = h["adc/skip_cell"][()]
        cstop = h["adc/cstop"][()]
        return {
            "n": n, "shape": adc.shape, "dtype": adc.dtype.str,
            "comp": adc.compression,
            "ids": ids, "qual": qual,
            "roi": int(roi.sum()), "skip": int(skip.sum()), "cstop": int(cstop.sum()),
            "adc_sum": int(adc[()].sum()), "adc_min": int(adc[()].min()), "adc_max": int(adc[()].max()),
            "zero_rows": int(np.all(adc[()] == 0, axis=(1, 2)).sum()),
        }

results = {}
for tag, w in [("w1", 1), ("w2", 2), ("w4", 4), ("wdef", None)]:
    h5 = run_extract(w, tag)
    results[tag] = read_summary(h5) if h5 else None
    if results[tag]:
        s = results[tag]
        print(f"  {tag}: n={s['n']} shape={s['shape']} dtype={s['dtype']} comp={s['comp']} "
              f"zero_rows={s['zero_rows']} ids={list(s['ids'])} qual={set(int(q) for q in s['qual'])} "
              f"adc sum={s['adc_sum']} min={s['adc_min']} max={s['adc_max']}")

ok = True
base = results["w1"]
for tag in ["w2", "w4", "wdef"]:
    r = results[tag]
    if r is None:
        ok = False
        continue
    for key in ["n", "shape", "dtype", "comp", "adc_sum", "adc_min", "adc_max", "zero_rows"]:
        if base is not None and base[key] != r[key]:
            print(f"  MISMATCH {tag}.{key}: {base[key]} vs {r[key]}")
            ok = False
    if base is not None and not np.array_equal(base["ids"], r["ids"]):
        print(f"  MISMATCH {tag}.ids"); ok = False
    if base is not None and not np.array_equal(base["qual"], r["qual"]):
        print(f"  MISMATCH {tag}.qual"); ok = False
print("PARALLELISM:", "PASS" if ok else "FAIL")
