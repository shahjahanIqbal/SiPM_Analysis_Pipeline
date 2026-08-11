import os
import sys
import tempfile
import subprocess
import numpy as np
import h5py

PIPE = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes"
COMMITTED = os.path.join(PIPE, "geometry", "SiPMCamera.h5")

ok = True
def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail}")

# ---- 1 committed map integrity ----
with h5py.File(COMMITTED, "r") as f:
    pm = f["PIXEL_MAP"][:].astype(int)
check("map shape (16,16)", pm.shape == (16, 16), str(pm.shape))
check("map has 256 unique values 0..255",
      np.unique(pm).size == 256 and pm.min() == 0 and pm.max() == 255)

# ---- 2 createPixelMap regeneration from a temp cwd reproduces the map ----
with tempfile.TemporaryDirectory() as td:
    cfg_path = os.path.join(td, "c.yaml")
    with open(cfg_path, "w") as f:
        f.write("camera_geometry:\n"
                "  name: SiPMCamera\n"
                "  pcm_count: 16\n"
                "  ddb_count: 4\n"
                "  channel_count: 9\n"
                "  expected_packets_per_event: 64\n"
                "  readout:\n    roi_samples: 150\n"
                "  layout:\n    rows: 16\n    cols: 16\n"
                "data:\n  evbfilepath: /tmp/opencode/x.eve\n"
                "calib:\n  drsoffset: /tmp/opencode/y.cofsm\n"
                "io:\n  output: /tmp/opencode/z\n")
    env = dict(os.environ)
    env["PYTHONPATH"] = PIPE
    sys.path.insert(0, PIPE)
    code = ("from config_loader import load_config\n"
            "from geometry import CameraLayout\n"
            "import numpy as np, h5py\n"
            f"g = CameraLayout(load_config('{cfg_path}'))\n"
            "g.createPixelMap()\n"
            "regen = h5py.File('../geometry/SiPMCamera.h5','r')['PIXEL_MAP'][:].astype(int)\n"
            "comm = h5py.File('" + COMMITTED + "','r')['PIXEL_MAP'][:].astype(int)\n"
            "print('MATCH', np.array_equal(regen, comm))\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=td, env=env)
    match_line = [l for l in r.stdout.splitlines() if l.startswith("MATCH")]
    matched = (r.returncode == 0 and bool(match_line) and match_line[0].split()[-1] == "True")
    if not matched:
        print(f"  regen stderr: {r.stderr[-300:]}")
    check("createPixelMap regenerates identical map", matched)
    # cwd-dependence documentation: map file landed OUTSIDE the temp dir (in td/../geometry)
    outside = os.path.exists(os.path.join(td, "..", "geometry", "SiPMCamera.h5"))
    print(f"  NOTE createPixelMap writes to ../geometry relative to CWD "
          f"(cwd={os.path.relpath(td, os.getcwd())}); file outside project dir: {outside}")

# ---- 3 gch <-> local round trip for all 576 channels (in-process) ----
os.chdir(PIPE)
sys.path.insert(0, PIPE)
from config_loader import load_config
from geometry import CameraLayout
geom2 = CameraLayout(load_config("config/config.yaml"))
bad = []
for gch in range(geom2.N_GLOBAL_CH):
    lch, lddb, lpcm = geom2.local_channel_id(gch)
    if geom2.global_channel_id(lpcm, lddb, lch) != gch:
        bad.append((gch, (lch, lddb, lpcm)))
check("gch<->local round trip", len(bad) == 0, f"nbad={len(bad)} {bad[:5]}")

# ---- 4 mapToPixels: unique LG/HG gch assignment per pixel ----
sys.path.insert(0, PIPE)
os.chdir(PIPE)
from config_loader import load_config
from geometry import CameraLayout
import image_gen as IG
geom = CameraLayout(load_config("config/config.yaml"))
gch = np.arange(geom.N_GLOBAL_CH)
mask = (gch % geom.N_CH_PER_DDB) != geom.N_CH_PER_DDB - 1
nz = gch[mask]
LG_gch = nz[0::2]
HG_gch = nz[1::2]
check("LG flat gch unique", np.unique(LG_gch).size == LG_gch.size, str(LG_gch.size))
check("HG flat gch unique", np.unique(HG_gch).size == HG_gch.size, str(HG_gch.size))
check("LG/HG gch disjoint", np.intersect1d(LG_gch, HG_gch).size == 0)
# physical positions -> flat pixel index -> gch (LG and HG)
lg_gch_map = LG_gch[pm]
hg_gch_map = HG_gch[pm]
check("each physical pixel gets distinct LG gch",
      np.unique(lg_gch_map).size == 256 and lg_gch_map.min() >= 0 and lg_gch_map.max() <= 575)
check("each physical pixel gets distinct HG gch",
      np.unique(hg_gch_map).size == 256 and hg_gch_map.min() >= 0 and hg_gch_map.max() <= 575)

print("PIXELMAP:", "PASS" if ok else "FAIL")
