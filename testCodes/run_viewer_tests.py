import os
import sys
import subprocess

PIPE = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes"
PY = "/home/shahjahan/anaconda3/envs/cta/bin/python"
DL1 = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes/dl1/clean6_processed_cta_cont.h5"

ok = True
def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail}")

env = {**os.environ, "MPLBACKEND": "Agg",
       "QT_QPA_PLATFORM": "offscreen",
       "HDF5_USE_FILE_LOCKING": "FALSE"}

# --- 1. end-to-end viewer run on a small DL1 (Agg => show() no-op) ---
r = subprocess.run([PY, "display_reco_events.py", DL1],
                   capture_output=True, text=True, cwd=PIPE, env=env, timeout=300)
check("viewer exit 0 on clean6 DL1", r.returncode == 0, f"exit={r.returncode}")
check("viewer no traceback", "Traceback" not in r.stdout + r.stderr,
      (r.stdout + r.stderr)[-600:])

# --- 2. missing file ---
r = subprocess.run([PY, "display_reco_events.py", "/tmp/opencode/NOPE.h5"],
                   capture_output=True, text=True, cwd=PIPE, env=env, timeout=120)
check("missing DL1 raises FileNotFoundError", r.returncode != 0 and "File not found" in r.stdout + r.stderr)

# --- 3. no argument -> argparse usage error ---
r = subprocess.run([PY, "display_reco_events.py"], capture_output=True, text=True, cwd=PIPE, env=env)
check("no arg -> argparse exit 2", r.returncode == 2)

# --- 4. draw_event headless over all 6 events (paging logic) ---
import matplotlib
matplotlib.use("Agg")
sys.path.insert(0, PIPE)
from ctapipe.io import EventSource
import display_reco_events as v

source = EventSource(input_url=DL1, max_events=None)
v.source = source  # __main__ defines these globals; mirror for module-level reuse
v.event_iter = iter(source)
try:
    for k in range(6):
        ev = next(v.event_iter)
        v.state = {"event": ev}
        v.draw_event(ev)
        v.fig.canvas.draw()
    v.on_next(None)  # advance a page
    v.on_skip(None)  # skip 10 (guarded, should not crash past end)
    check("draw_event over 6 events + next/skip handlers", True)
except Exception as e:
    check("draw_event over 6 events + next/skip handlers", False, repr(e))

print("VIEWER:", "PASS" if ok else "FAIL")
