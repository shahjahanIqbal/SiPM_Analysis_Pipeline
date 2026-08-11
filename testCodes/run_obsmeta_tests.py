import os
import sys
import json
import shutil
import subprocess
import numpy as np

PIPE = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes"
PY = "/home/shahjahan/anaconda3/envs/cta/bin/python"
BASE = "/tmp/opencode/sipm_audit/obsmeta_test"
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(BASE, exist_ok=True)

ok = True
def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail}")

META = {"Run_No": 419, "Source_Name": "crab_on", "File_Name": "s0534+2201_419",
 "Date_UTC": "15.01.2026", "MJD": "61055", "RA (Precise)": "05:36:06",
 "DEC (Precise)": "22:01:50", "RA (J2000)": "05:36:06", "DEC (J2000)": "22:01:50",
 "Transit_Time": "22:34", "StartTime_UTC": "17:25:02", "Hour_Angle_Start": "0.34",
 "Zen_Angle_Start": "5.40", "Az_Angle_Start": "62.31", "SQM_Start": "20.83",
 "StopTime_UTC": "18:34:57", "Hour_Angle_Stop": "1.51", "Zen_Angle_Stop": "20.97",
 "Az_Angle_Stop": "87.53", "Trigger_Threshold_mV": 150, "Trigger_Logic": "3NN",
 "Total_Events": 47013, "Average_Trigger_Rate(Hz)": "11.2", "Duration(mins)": 69}

# ---- build blocks from a real-format JSON ----
sys.path.insert(0, PIPE)
os.chdir(PIPE)
from config_loader import load_config
import create_h5 as CH
ob = CH.build_obs_block(META)
sb = CH.build_sched_block(META)
ctx = CH.build_context(META)
check("obs_id from Run_No", ob.obs_id == 419)
check("RA pointed correctly", abs(ob.subarray_pointing_lon.to_value("deg") - 84.025) < 0.001,
      f"ra={ob.subarray_pointing_lon}")
check("DEC pointed correctly", abs(ob.subarray_pointing_lat.to_value("deg") - 22.0306) < 0.001,
      f"dec={ob.subarray_pointing_lat}")
check("start time parsed", ob.actual_start_time.isot == "2026-01-15T17:25:02.000",
      ob.actual_start_time.isot)
check("duration 69 min", ob.actual_duration.to_value("min") == 69.0,
      ob.actual_duration)
check("crab_on -> ON_OFF mode", sb.observing_mode.name == "ON_OFF",
      str(sb.observing_mode))
check("sched pointing TRACK", sb.pointing_mode.name == "TRACK")
check("context has 17 keys", len(ctx) == 17, str(len(ctx)))
check("context has SQM", "OBSERVATION SQM_START" in ctx)
check("context MJD", ctx["OBSERVATION MJD"] == "61055")

# ---- wrapper createh5 CLI (observation mode) end-to-end ----
outd = os.path.join(BASE, "dl1")
json_dir = os.path.join(BASE, "json")
os.makedirs(json_dir, exist_ok=True)
with open(os.path.join(json_dir, "clean6.json"), "w") as f:
    json.dump(META, f)
with open(os.path.join(json_dir, "clean6.json"), "w") as f:
    json.dump(META, f)
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
  evbfilepath: /tmp/opencode/x.eve
calib:
  drsoffset: /home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes/DRS_OFFSET/all_cdm_ddb_drsoffsets_fro_09112024_1.cofsm
io:
  output: {BASE}
""")
outfiles = os.path.join(BASE, "output_files.txt")
with open(outfiles, "w") as f:
    f.write("/tmp/opencode/sipm_audit/parallel_test/w1/clean6_processed.h5\n")
r = subprocess.run([PY, os.path.join(PIPE, "wrapper.py"), "createh5", outd,
                    "--json-dir", json_dir, "--config", conf],
                   capture_output=True, text=True, cwd=PIPE,
                   env={**os.environ, "HDF5_USE_FILE_LOCKING": "FALSE"})
print(f"  CLI exit={r.returncode}")
if r.returncode != 0:
    print(f"  CLI stderr: {r.stderr[-600:]}")
dl1 = os.path.join(outd, "clean6_processed_cta_cont.h5")
check("CLI createh5 produced DL1", os.path.exists(dl1))

if os.path.exists(dl1):
    from ctapipe.io import EventSource
    with EventSource(dl1) as src:
        check("CLI obs_id 419", list(src.obs_ids) == [419], str(list(src.obs_ids)))
        ev = next(iter(src))
        check("CLI event image len", ev.dl1.tel[1].image.shape == (256,))
        check("CLI Hillas present", ev.dl1.tel[1].parameters is not None)
    import tables
    with tables.open_file(dl1) as t:
        check("CONTEXT attrs written", "/CONTEXT/OBSERVATION" in t.root,
              str([n for n in t.root.CONTEXT._f_iter_nodes()]))
        grp = t.root.CONTEXT.OBSERVATION._v_attrs
        keys = sorted(grp._f_list())
        print(f"  NOTE CONTEXT attrs: {keys}")
        check("context attr SOURCE_NAME", "SOURCE_NAME" in keys)
        check("context attr value", grp.SOURCE_NAME == "crab_on", str(grp.SOURCE_NAME))

print("OBSMETA:", "PASS" if ok else "FAIL")
