import os, sys
import numpy as np
import h5py

import audit_env

PIPE = audit_env.CODES
os.chdir(PIPE)
sys.path.insert(0, PIPE)
os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"

from config_loader import load_config
from geometry import CameraLayout
from image_gen import imageGen, mapToPixels, processEvent

from ctapipe.io import EventSource
from ctapipe.containers import DL1CameraContainer

audit_env.ensure_config()
audit_env.ensure_pixelmap()
cfg = load_config("config/config.yaml")
geom = CameraLayout(cfg)
pixel_map = geom.loadPixelMap(f"geometry/{geom.camera_name}.h5")
offset = np.loadtxt(cfg["calib"]["drsoffset"])

ok = True
def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail}")

H5 = audit_env.ensure_parallel_h5()
DL1 = audit_env.ensure_dl1()

# recompute images in-process from extract H5
with h5py.File(H5, "r") as f:
    roi = f["adc/roi_data"][:]
    cstop = f["adc/cstop"][:]
source = EventSource(DL1)
dl1_rows = []
for ev in source:
    dl1_rows.append(ev.dl1.tel[1].image)
dl1_img = np.stack(dl1_rows)
print(f"  read {len(dl1_rows)} events via ctapipe")

imgs = []
gch = np.arange(geom.N_GLOBAL_CH)
for row in range(6):
    out = processEvent(row, roi[row], cstop[row], np.zeros(geom.N_GLOBAL_CH, dtype=np.int64),
                        offset, geom, pixel_map, gch, None)
    imgs.append(out["image_HG"].astype(float)[::-1].reshape(-1))

print(f"  DL1 img shape {dl1_img.shape} dtype {dl1_img.dtype}")
for row in range(6):
    a = imgs[row]; b = dl1_img[row]
    scale = float(b.sum() / a.sum()) if a.sum() else 1.0
    check(f"DL1 event row {row}: image matches imageGen (float32)",
          np.allclose(a * scale, b, rtol=2e-5, atol=1e-2),
          f"sum_ref={a.sum():.4f} sum_dl1={b.sum():.4f} maxrel={np.max(np.abs(a*scale-b)/np.maximum(np.abs(b),1e-9)):.2e}")

print("DL1_OUTPUT_VALIDATION:", "PASS" if ok else "FAIL")
