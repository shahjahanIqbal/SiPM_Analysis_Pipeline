import os
import sys
import numpy as np

import audit_env

PIPE = audit_env.CODES
os.chdir(PIPE)
sys.path.insert(0, PIPE)
os.environ.setdefault("MPLBACKEND", "Agg")

audit_env.ensure_config()
audit_env.ensure_pixelmap()
from config_loader import load_config
from geometry import CameraLayout
import image_gen as IG

cfg = load_config("config/config.yaml")
geom = CameraLayout(cfg)
print(f"geometry: N_CH_PER_DDB={geom.N_CH_PER_DDB} N_DDB={geom.N_DDB} "
      f"N_PCM={geom.N_PCM} N_GLOBAL_CH={geom.N_GLOBAL_CH} roi={geom.roi}")

ok = True
def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail}")

# ---- 1 gaussianFunction ----
x = IG.gaussianFunction(np.arange(-35, 36))
check("gaussian sum=1", abs(x.sum() - 1) < 1e-12, f"sum={x.sum()}")
check("gaussian peak at 0", abs(x[35] - x.max()) < 1e-15)

# ---- 2 peakFinder on known Gaussian pulse ----
ROI = 150
t = np.arange(ROI)
amp = 8000
center = 60
sig = 4
adc = amp * np.exp(-0.5 * ((t - center) / sig) ** 2).astype(np.int16)
peak = IG.peakFinder(adc)
check("peakFinder locates peak", abs(peak - center) <= 2, f"peak={peak} expected~{center}")

# ---- 3 adcTomV: flat no pulse -> ~0 after baseline ----
flat = np.full(ROI, 10000, dtype=np.int16)
mv, rx, at, start, end, sat = IG.adcTomV(flat, cstop=0, skip_cell=0, offsets=None)
check("adcTomV flat -> 0 after baseline", np.abs(mv).max() < 1e-6, f"max={np.abs(mv).max():.2e}")
check("adcTomV window within ROI", 0 <= start <= end <= ROI, f"{start}..{end}")

# ---- 4 adcTomV with pulse: peak mV scale ----
mv, rx, at, start, end, sat = IG.adcTomV(adc, cstop=0, skip_cell=0, offsets=None)
expect_peak = (1000 / 16384) * amp
check("adcTomV peak ~ expected mV", abs(mv[peak] - expect_peak) < 1.0,
      f"got {mv[peak]:.3f} expected {expect_peak:.3f}")
check("adcTomV sat False", not sat)
check("adcTomV arrival_time=peak", at == peak, f"at={at}")

# ---- 5 saturation flag: DOCUMENTED BUG (check happens pre-offset on raw ADC) ----
# With 14-bit max ADC=16383, raw pulse_mV max = (1000/16384)*16383 = 999.94 < 1000,
# and the >1000 test runs BEFORE offsets are added -> flag can never be True.
offsets_high = np.zeros(1024)
offsets_high[:] = 600.0  # +600 mV everywhere
sat_amp = np.full(ROI, 16383, dtype=np.int16)  # 14-bit full scale ~1000 mV
mv, _, _, _, _, sat = IG.adcTomV(sat_amp, cstop=0, skip_cell=0, offsets=offsets_high)
print(f"  NOTE saturation flag with full-scale+600mV offset = {sat} "
      f"(max raw mV={(1000/16384)*16383:.2f} -> pre-offset check can never exceed 1000; BUG)")
check("adcTomV sat True with large offset", sat)  # documents the bug (expected FAIL)

# ---- 6 adcTomV offset cycling uses (roi_x + cstop) % 1024 ----
off = np.zeros(1024)
off[0] = 7.0  # applied when (x + cstop) % 1024 == 0
mv, _, _, _, _, _ = IG.adcTomV(flat, cstop=1024 - 10, skip_cell=0, offsets=off)
check("offset applied at x=10", abs(mv[10] - 7.0) < 1e-9, f"mv[10]={mv[10]}")
check("offset not applied at x=11", abs(mv[11]) < 1e-9, f"mv[11]={mv[11]}")

# ---- 7 chargePerPixel: rectangular pulse on top of baseline ----
V_ADC = 900
rect = np.zeros(ROI, dtype=np.int16)
rect[40:100] = V_ADC  # pulse plateau in the middle, baseline elsewhere
mv, rx, _, s, e, _ = IG.adcTomV(rect, cstop=0, skip_cell=0, offsets=None)
q = IG.chargePerPixel(rx, mv, s, e)
expected_q = (V_ADC * 1000 / 16384) * (e - s) / 50.0
check("chargePerPixel rectangular ~ V*(end-start)/50", abs(q - expected_q) / expected_q < 0.10,
      f"got {q:.3f} expected {expected_q:.3f} (window {s}..{e})")

# ---- 8 edgeDetector on Gaussian ----
edge = IG.edgeDetector(adc.astype(np.float64), peak)
check("edgeDetector returns index near rising edge", 40 <= edge <= peak,
      f"edge={edge} peak={peak}")

# ---- 9 imageGen + mapToPixels end-to-end ----
block = geom.N_CH_PER_DDB  # 9
NBLK = geom.N_GLOBAL_CH // block  # 64
roi_data = np.zeros((geom.N_GLOBAL_CH, ROI), dtype=np.int16)
cstop_arr = np.zeros(geom.N_GLOBAL_CH, dtype=np.int16)
skip_arr = np.zeros(geom.N_GLOBAL_CH, dtype=np.int16)
A_LG, A_HG, A_REF = 5000, 9000, 11000
for b in range(NBLK):
    g = b * block
    roi_data[g + 8] = (A_REF * np.exp(-0.5 * ((t - 60) / 4) ** 2)).astype(np.int16)  # ref
    for lg, hg in [(0, 1), (2, 3), (4, 5), (6, 7)]:
        roi_data[g + lg] = (A_LG * np.exp(-0.5 * ((t - 60) / 4) ** 2)).astype(np.int16)
        roi_data[g + hg] = (A_HG * np.exp(-0.5 * ((t - 60) / 4) ** 2)).astype(np.int16)
offsets = np.zeros((NBLK * 1024, geom.N_CH_PER_DDB + 1))  # (65536,10)

ch_img, t_img, sat_mask = IG.imageGen(roi_data, cstop_arr, skip_arr, offsets, geom)
check("imageGen HG charge positive", ch_img[0 + 1] > 0, f"HG={ch_img[1]:.3f}")
check("imageGen LG charge positive", ch_img[0 + 0] > 0, f"LG={ch_img[0]:.3f}")
check("imageGen HG>LG (higher amp)", ch_img[1] > ch_img[0],
      f"HG={ch_img[1]:.3f} LG={ch_img[0]:.3f}")
check("imageGen ref channel zero", abs(ch_img[0 + 8]) < 1e-9, f"ch_img[8]={ch_img[8]}")
check("imageGen sat mask False", not sat_mask.any())
check("imageGen time non-negative", (t_img >= 0).all())

# pixel map
import h5py
pixel_map = geom.loadPixelMap(f"geometry/{geom.camera_name}.h5")
check("pixel_map 16x16", pixel_map.shape == (16, 16), str(pixel_map.shape))
gch = np.arange(geom.N_GLOBAL_CH)
imLG, imHG = IG.mapToPixels(geom, ch_img, pixel_map, gch)
check("mapToPixels LG shape", imLG.shape == (16, 16), str(imLG.shape))
check("mapToPixels HG shape", imHG.shape == (16, 16), str(imHG.shape))
# charge conserved: sum of non-ref HG + LG across camera
tot_mapped = imLG.sum() + imHG.sum()
tot_charge = ch_img[~((gch % 9) == 8)].sum()
check("mapToPixels charge conserved", abs(tot_mapped - tot_charge) < 1e-6,
      f"{tot_mapped:.3f} vs {tot_charge:.3f}")

print("IMAGE_GEN:", "PASS" if ok else "FAIL")
