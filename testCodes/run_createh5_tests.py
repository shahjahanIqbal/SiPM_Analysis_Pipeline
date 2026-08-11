import os
import sys
import json
import shutil
import numpy as np

PIPE = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes"
os.chdir(PIPE)
sys.path.insert(0, PIPE)
os.environ.setdefault("MPLBACKEND", "Agg")
os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"

from config_loader import load_config
import create_h5
from pathlib import Path

BASE = "/tmp/opencode/sipm_audit/createh5_test"
INPUT = "/tmp/opencode/sipm_audit/parallel_test/w1/clean6_processed.h5"
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(BASE, exist_ok=True)

cfg = load_config("config/config.yaml")

ok = True
def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail}")

# ---- build subarray sanity ----
sub = create_h5.build_subarray(create_h5.CameraLayout(cfg))
tel = sub.tel[1]
check("subarray 1 tel", len(sub.tel) == 1)
check("camera 256 pixels", tel.camera.geometry.n_pixels == 256)
check("roi samples 150", tel.camera.readout.n_samples == 150)
print(f"  NOTE camera frame: {tel.camera.geometry.frame}")

# ---- calibration mode (--no-dl2) ----
out_cal = os.path.join(BASE, "cal")
create_h5.main(input_file=Path(INPUT), output_dir=Path(out_cal), json_path=None,
               config=cfg, dl2_flag=False)
cal_file = os.path.join(out_cal, "clean6_processed_cta_cont.h5")
check("calibration DL1 written", os.path.exists(cal_file))

# ---- observation mode (dl2) ----
json_path = os.path.join(BASE, "clean6.json")
meta = {
    "Run_No": 419, "Source_Name": "crab_on", "File_Name": "s0534+2201_419",
    "Date_UTC": "15.01.2026", "MJD": "61055", "RA (Precise)": "05:36:06",
    "DEC (Precise)": "22:01:50", "RA (J2000)": "05:36:06", "DEC (J2000)": "22:01:50",
    "Transit_Time": "22:34", "StartTime_UTC": "17:25:02", "Hour_Angle_Start": "0.34",
    "Zen_Angle_Start": "5.40", "Az_Angle_Start": "62.31", "SQM_Start": "20.83",
    "StopTime_UTC": "18:34:57", "Hour_Angle_Stop": "1.51", "Zen_Angle_Stop": "20.97",
    "Az_Angle_Stop": "87.53", "Trigger_Threshold_mV": 150, "Trigger_Logic": "3NN",
    "Total_Events": 47013, "Average_Trigger_Rate(Hz)": "11.2", "Duration(mins)": 69,
}
with open(json_path, "w") as f:
    json.dump(meta, f)

out_obs = os.path.join(BASE, "obs")
create_h5.main(input_file=Path(INPUT), output_dir=Path(out_obs), json_path=Path(json_path),
               config=cfg, dl2_flag=True)
obs_file = os.path.join(out_obs, "clean6_processed_cta_cont.h5")
check("observation DL1 written", os.path.exists(obs_file))

# ---- reopen with ctapipe EventSource ----
from ctapipe.io import EventSource
for tag, f, want_dl2 in [("cal", cal_file, False), ("obs", obs_file, True)]:
    try:
        src = EventSource(f)
        nevents = sum(1 for _ in src)
        check(f"{tag} EventSource reopens, {nevents} events", nevents == 6, f"n={nevents}")
    except Exception as e:
        check(f"{tag} EventSource reopens", False, str(e)[:200])
        nevents = 0

# ---- DL1 structure via ctapipe containers ----
from ctapipe.io import EventSource
with EventSource(obs_file) as src:
    check("obs obs_ids=[419]", list(src.obs_ids) == [419], str(list(src.obs_ids)))
    ev = next(iter(src))
    img = ev.dl1.tel[1].image
    check("obs image length 256", img.shape == (256,), str(img.shape))
    hp = ev.dl1.tel[1].parameters.hillas
    check("obs Hillas params finite", all(np.isfinite(x) for x in
          [hp.x, hp.y, hp.length, hp.width, hp.psi, hp.phi,
           hp.intensity, hp.skewness, hp.kurtosis]))
    print(f"  NOTE obs event1 Hillas: x={hp.x:.1f} y={hp.y:.1f} length={hp.length:.1f} "
          f"width={hp.width:.1f} intensity={hp.intensity:.0f} n_pix_survive")
    check("obs event_index=419? obs_id", ev.index.obs_id == 419, str(ev.index.obs_id))
    check("obs event_id from registry", ev.index.event_id == 1, str(ev.index.event_id))
    check("obs has peak_time", ev.dl1.tel[1].peak_time.shape == (256,))

with EventSource(cal_file) as src:
    check("cal obs_ids=[0]", list(src.obs_ids) == [0], str(list(src.obs_ids)))
    ev = next(iter(src))
    check("cal image length 256", ev.dl1.tel[1].image.shape == (256,), str(ev.dl1.tel[1].image.shape))
    check("cal no Hillas params", ev.dl1.tel[1].parameters is None,
          f"params={ev.dl1.tel[1].parameters}")

print("CREATEH5:", "PASS" if ok else "FAIL")
