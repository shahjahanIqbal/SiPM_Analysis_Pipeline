import os
import sys
import json
import shutil
import subprocess

PIPE = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes"
PY = "/home/shahjahan/anaconda3/envs/cta/bin/python"
BASE = "/tmp/opencode/sipm_audit/batch_test"
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(BASE, exist_ok=True)

ok = True
def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail}")

TESTS = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes/testFiles"
evb_list = os.path.join(BASE, "evbs.txt")
with open(evb_list, "w") as f:
    f.write(f"{TESTS}/clean6.eve\n")
    f.write(f"{TESTS}/missingEventIDs.eve\n")
    f.write("/tmp/opencode/DOESNOTEXIST.eve\n")   # missing file in batch

conf = os.path.join(BASE, "conf.yaml")
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
  evbfilepath: {evb_list}
calib:
  drsoffset: /home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes/DRS_OFFSET/all_cdm_ddb_drsoffsets_fro_09112024_1.cofsm
io:
  output: {BASE}
""")
json_dir = os.path.join(BASE, "json")
os.makedirs(json_dir, exist_ok=True)
META = {"Run_No": 419, "Source_Name": "crab_on", "File_Name": "s0534+2201_419",
 "Date_UTC": "15.01.2026", "MJD": "61055", "RA (Precise)": "05:36:06",
 "DEC (Precise)": "22:01:50", "RA (J2000)": "05:36:06", "DEC (J2000)": "22:01:50",
 "Transit_Time": "22:34", "StartTime_UTC": "17:25:02", "Hour_Angle_Start": "0.34",
 "Zen_Angle_Start": "5.40", "Az_Angle_Start": "62.31", "SQM_Start": "20.83",
 "StopTime_UTC": "18:34:57", "Hour_Angle_Stop": "1.51", "Zen_Angle_Stop": "20.97",
 "Az_Angle_Stop": "87.53", "Trigger_Threshold_mV": 150, "Trigger_Logic": "3NN",
 "Total_Events": 47013, "Average_Trigger_Rate(Hz)": "11.2", "Duration(mins)": 69}
for stem in ["clean6", "missingEventIDs"]:
    with open(os.path.join(json_dir, f"{stem}.json"), "w") as f:
        json.dump(META, f)

r = subprocess.run([PY, os.path.join(PIPE, "wrapper.py"), "process", "dl1",
                    "--config", conf, "--json-dir", json_dir],
                   capture_output=True, text=True, cwd=PIPE,
                   env={**os.environ, "HDF5_USE_FILE_LOCKING": "FALSE"})
out = r.stdout + r.stderr
print(f"  process exit={r.returncode}")
print("  [logs] " + "; ".join(l for l in out.splitlines()
      if "Skipping" in l or "No valid" in l or "File saved" in l or "Failed" in l
      or "Processed" in l or "Pipeline execution" in l)[:600])

for fname in ["clean6_processed.h5", "missingEventIDs_processed.h5"]:
    check(f"extract h5 {fname}", os.path.exists(os.path.join(BASE, fname)))
check("missing EVB produces no h5", not os.path.exists(os.path.join(BASE, "DOESNOTEXIST_processed.h5")))
check("output_files.txt lists 2 files",
      os.path.exists(os.path.join(BASE, "output_files.txt")) and
      len(open(os.path.join(BASE, "output_files.txt")).read().splitlines()) == 2,
      "ok" if os.path.exists(os.path.join(BASE, "output_files.txt")) else "missing")
for fname in ["clean6_processed_cta_cont.h5", "missingEventIDs_processed_cta_cont.h5"]:
    check(f"DL1 {fname}", os.path.exists(os.path.join(PIPE, "dl1", fname)))

# clean6 DL1 sanity
import h5py
h5 = os.path.join(BASE, "clean6_processed.h5")
with h5py.File(h5, "r") as f:
    n = f["events/event_id"].shape[0]
    z = int((f["adc/roi_data"][:] == 0).all(axis=(1, 2)).sum())
    check("clean6 6 events", n == 6, str(n))
    check("clean6 no phantom rows", z == 0, str(z))
h5m = os.path.join(BASE, "missingEventIDs_processed.h5")
with h5py.File(h5m, "r") as f:
    ids = list(f["events/event_id"][:])
    z = int((f["adc/roi_data"][:] == 0).all(axis=(1, 2)).sum())
    print(f"  NOTE missingEventIDs in batch: ids={ids} phantom_zero_rows={z}")
    check("missingEventIDs phantom row present (documents bug)", z == 1)

print("BATCH:", "PASS" if ok else "FAIL")
