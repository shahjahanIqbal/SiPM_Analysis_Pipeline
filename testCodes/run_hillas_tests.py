import os
import sys
import numpy as np

PIPE = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes"
os.chdir(PIPE)
sys.path.insert(0, PIPE)
os.environ.setdefault("MPLBACKEND", "Agg")

from config_loader import load_config
import create_h5 as CH
from ctapipe.containers import ArrayEventContainer

cfg = load_config("config/config.yaml")
geom = CH.CameraLayout(cfg)
source = CH.SyntheticSource(subarray=CH.build_subarray(geom),
                            ob=CH.build_obs_block({
                                "Run_No": 1, "File_Name": "x", "Source_Name": "on",
                                "Date_UTC": "01.01.2026", "StartTime_UTC": "00:00:00",
                                "StopTime_UTC": "00:01:00", "Duration(mins)": 1,
                                "RA (J2000)": "05:00:00", "DEC (J2000)": "22:00:00"}),
                            sb=CH.build_sched_block({
                                "Run_No": 1, "Source_Name": "on"}))
cam = source.subarray.tel[1].camera.geometry

ok = True
def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail}")

def run(image, label):
    ev = ArrayEventContainer()
    ev.dl1.tel[1].image = image
    ev.dl1.tel[1].parameters = CH.ImageParametersContainer()
    try:
        r = CH.compute_hillas(ev, source)
        p = ev.dl1.tel[1].parameters.hillas
        if p is not None and "fov_lon" in p.fields:
            summary = (f"ret={r} intensity={p.intensity} fov_lon={p.fov_lon} "
                       f"len={p.length} width={p.width}")
        else:
            summary = f"ret={r} params={p}"
    except Exception as e:
        r = None
        summary = f"EXC {type(e).__name__}: {str(e)[:120]}"
    print(f"    {label}: {summary}")
    return r

# 1 all-zero (phantom-event image) -> MAD=0 -> no params
r = run(np.zeros(256, dtype=np.float32), "all-zero (phantom)")
check("zero image returns False (no params)", r is False)

# 2 uniform constant -> MAD=0
r = run(np.full(256, 500.0, dtype=np.float32), "uniform 500")
check("uniform image returns False", r is False)

# 3 single bright pixel -> <3 pixels survive
img = np.zeros(256, dtype=np.float32); img[100] = 1e6
r = run(img, "single bright pixel")
check("1-pixel image returns False", r is False)

# 4 two bright pixels
img = np.zeros(256, dtype=np.float32); img[[100, 101]] = 1e6
r = run(img, "two bright pixels")
check("2-pixel image returns False", r is False)

# 5 3+ pixel Gaussian blob -> params
y, x = np.mgrid[0:16, 0:16]
blob = 2000 * np.exp(-0.5 * ((x - 8) ** 2 + (y - 8) ** 2) / 4).ravel().astype(np.float32)
r = run(blob, "Gaussian blob")
check("Gaussian blob returns True", r is True)

# 6 NaN image
img = np.full(256, np.nan, dtype=np.float32)
r = run(img, "all-NaN image")
check("NaN image does not crash", r is not None, f"r={r}")

# 7 negative image
img = np.full(256, -100.0, dtype=np.float32)
r = run(img, "all-negative -100")
check("all-negative image returns False", r is False)

# 8 mixed negative/positive -> cleaning handles negative baseline
y, x = np.mgrid[0:16, 0:16]
img = (2000 * np.exp(-0.5 * ((x - 8) ** 2 + (y - 8) ** 2) / 4)).ravel().astype(np.float32)
img[::7] -= 800.0
r = run(img, "blob with negative pixels")
check("mixed-sign blob returns True", r is True)

print("HILLAS:", "PASS" if ok else "FAIL")
