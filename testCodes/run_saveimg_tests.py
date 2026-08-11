import os
import sys
import shutil
import subprocess
import glob

PIPE = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes"
PY = "/home/shahjahan/anaconda3/envs/cta/bin/python"
H5 = "/tmp/opencode/sipm_audit/parallel_test/w1/clean6_processed.h5"
BASE = "/tmp/opencode/sipm_audit/saveimg_test"
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(BASE, exist_ok=True)

ok = True
def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail}")

env = {**os.environ, "HDF5_USE_FILE_LOCKING": "FALSE"}

# ---- all outputs on, events 1..3 ----
out1 = os.path.join(BASE, "all")
r = subprocess.run([PY, os.path.join(PIPE, "wrapper.py"), "saveimg", H5, out1,
                    "--start", "1", "--end", "3", "--waveform", "--refpulse",
                    "--cdist-lg", "--cdist-hg", "--tdist"],
                   capture_output=True, text=True, cwd=PIPE, env=env)
print(f"  saveimg all exit={r.returncode}")
check("saveimg all exit 0", r.returncode == 0)
root = os.path.join(out1, "clean6_processed")
lg = sorted(glob.glob(os.path.join(root, "Integrated_Charge", "*_LG.png")))
hg = sorted(glob.glob(os.path.join(root, "Integrated_Charge", "*_HG.png")))
tm = sorted(glob.glob(os.path.join(root, "Arrival_Time", "*_Time.png")))
check("LG images for [1,3)", len(lg) == 2, str(len(lg)))
check("HG images for [1,3)", len(hg) == 2, str(len(hg)))
check("Time images for [1,3)", len(tm) == 2, str(len(tm)))
wf = sorted(glob.glob(os.path.join(root, "Event_*", "*.png")))
check("waveform plots written", len(wf) >= 512, str(len(wf)))
rf = sorted(glob.glob(os.path.join(root, "ref_pulses", "Event_*", "*.png")))
check("ref pulses written", len(rf) == 64 * 2, str(len(rf)))
cd = sorted(glob.glob(os.path.join(root, "Dist", "*.png")))
check("charge/time dists written", len(cd) >= 6, str(len(cd)))

# ---- flag toggles: no-lg, no-hg, no-time ----
out2 = os.path.join(BASE, "toggles")
r = subprocess.run([PY, os.path.join(PIPE, "wrapper.py"), "saveimg", H5, out2,
                    "--start", "1", "--end", "2", "--no-lg", "--no-time"],
                   capture_output=True, text=True, cwd=PIPE, env=env)
root2 = os.path.join(out2, "clean6_processed")
lg2 = glob.glob(os.path.join(root2, "Integrated_Charge", "*_LG.png"))
hg2 = glob.glob(os.path.join(root2, "Integrated_Charge", "*_HG.png"))
tm2 = glob.glob(os.path.join(root2, "Arrival_Time", "*_Time.png"))
check("no-lg suppresses LG", len(lg2) == 0 and len(hg2) == 1, f"LG={len(lg2)} HG={len(hg2)}")
check("no-time suppresses Time", len(tm2) == 0)

# ---- error handling ----
r = subprocess.run([PY, os.path.join(PIPE, "wrapper.py"), "saveimg", H5, os.path.join(BASE, "bad"),
                    "--start", "5", "--end", "2"],
                   capture_output=True, text=True, cwd=PIPE, env=env)
check("start>end rejected", r.returncode != 0 and "start index 5 > end index 2" in (r.stdout + r.stderr),
      f"exit={r.returncode}")
r = subprocess.run([PY, os.path.join(PIPE, "wrapper.py"), "saveimg", H5, os.path.join(BASE, "bad2"),
                    "--start", "1", "--end", "99"],
                   capture_output=True, text=True, cwd=PIPE, env=env)
check("end beyond rows rejected", r.returncode != 0 and "maps to row" in (r.stdout + r.stderr),
      f"exit={r.returncode}")

# ---- nonexistent H5 ----
r = subprocess.run([PY, os.path.join(PIPE, "wrapper.py"), "saveimg", "/tmp/opencode/NOPE.h5",
                    os.path.join(BASE, "bad3")],
                   capture_output=True, text=True, cwd=PIPE, env=env)
check("missing H5 rejected", r.returncode != 0 and "H5 file not found" in (r.stdout + r.stderr),
      f"exit={r.returncode}")

print("SAVEIMG:", "PASS" if ok else "FAIL")
