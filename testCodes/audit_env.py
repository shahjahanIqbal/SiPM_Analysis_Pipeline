#!/usr/bin/env python3
"""Portable paths and input provisioning for the audit test harnesses.

Every harness in this directory derives its paths from here instead of
hardcoding machine-specific locations, so the same code runs on any system:

    REPO   - repository root (two levels above this file)
    CODES  - production pipeline directory (repo/Codes)
    TF     - generated test EVB files (repo/Codes/testFiles)
    WORK   - all harness outputs, under the system temp dir (never the repo)
    PY     - python used to run the pipeline (default: interpreter running the
             harness; override with the SIPM_PYTHON env var)

Provisioning helpers create the gitignored runtime inputs a fresh checkout
lacks (config.yaml, DRS offset file, camera pixel map, clean6.eve + replicas,
and the cross-harness intermediate products), so the suite runs end to end on
a clean clone. Real files are never overwritten.
"""
import os
import sys
import subprocess
import tempfile

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TEST_DIR)
CODES = os.path.join(REPO, "Codes")
TF = os.path.join(CODES, "testFiles")

# All harness outputs live under the system temp dir; sections never pollute
# the repository. Override with SIPM_AUDIT_WORK to redirect elsewhere.
WORK = os.environ.get("SIPM_AUDIT_WORK", os.path.join(tempfile.gettempdir(), "sipm_audit"))

# Python used to invoke the pipeline (wrapper.py / create_test_evb.py / ...).
# Defaults to the interpreter running the harness so no hardcoded env path is
# needed; set SIPM_PYTHON to force a specific environment (e.g. a conda env).
PY = os.environ.get("SIPM_PYTHON", sys.executable)

CONFIG = os.path.join(CODES, "config", "config.yaml")
GEOM_H5 = os.path.join(CODES, "geometry", "SiPMCamera.h5")
DRS_REAL = os.path.join(CODES, "DRS_OFFSET", "all_cdm_ddb_drsoffsets_fro_09112024_1.cofsm")
DRS_STUB = os.path.join(WORK, "drs_zero_stub.cofsm")

CLEAN6 = os.path.join(TF, "clean6.eve")
PARALLEL_H5 = os.path.join(WORK, "parallel_test", "w1", "clean6_processed.h5")
DL1 = os.path.join(CODES, "dl1", "clean6_processed_cta_cont.h5")

_CAMERA = {
    "name": "SiPMCamera",
    "pcm_count": 16,
    "ddb_count": 4,
    "channel_count": 9,
    "expected_packets_per_event": 64,
    "readout": {"roi_samples": 150, "adc_bits": 14, "channel_zero_dual_map": True},
    "layout": {"rows": 16, "cols": 16, "ordering": "column-major",
               "pixel_size_mm": 22.1, "pixel_gap_mm": 0.05},
}


def _run(argv, cwd=CODES, **kw):
    env = dict(os.environ)
    env["HDF5_USE_FILE_LOCKING"] = "FALSE"
    env.setdefault("MPLBACKEND", "Agg")
    return subprocess.run([PY, *argv], cwd=cwd, env=env, **kw)


def ensure_drs():
    """Return a usable DRS offset file path.

    Uses the real file when present; otherwise generates a zero-offset stub of
    the expected shape (65536 lines x 10 columns) under WORK.
    """
    if os.path.exists(DRS_REAL):
        return DRS_REAL
    os.makedirs(WORK, exist_ok=True)
    if not os.path.exists(DRS_STUB):
        with open(DRS_STUB, "w") as f:
            for _ in range(65536):
                f.write(" ".join(["0.0"] * 10) + "\n")
    return DRS_STUB


def ensure_config():
    """Ensure a valid Codes/config/config.yaml exists (never overwrites).

    A fresh checkout has no config (it is gitignored); the harnesses and the
    pipeline's module-level loads need one, so a working template is written
    pointing at the generated test EVB and the resolved DRS file.
    """
    if os.path.exists(CONFIG):
        return CONFIG
    cfg = {
        "camera_geometry": dict(_CAMERA),
        "data": {"evbfilepath": ensure_evb()},
        "calib": {"drsoffset": ensure_drs()},
        "io": {"output": os.path.join(CODES, "output0308")},
    }
    import yaml
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    return CONFIG


def ensure_pixelmap():
    """Ensure Codes/geometry/SiPMCamera.h5 exists (regenerates if missing).

    createPixelMap writes to ``../geometry`` relative to the CWD, so it is run
    from a Codes/ subdirectory to land the map in Codes/geometry (the location
    the pipeline resolves via ``geometry/{camera_name}.h5`` from Codes/).
    """
    if os.path.exists(GEOM_H5):
        return GEOM_H5
    ensure_config()
    sub = os.path.join(CODES, "audit_provision")
    os.makedirs(sub, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = CODES + os.pathsep + env.get("PYTHONPATH", "")
    env["HDF5_USE_FILE_LOCKING"] = "FALSE"
    code = ("from config_loader import load_config; "
            "from geometry import CameraLayout; "
            f"CameraLayout(load_config('{CONFIG}')).createPixelMap()")
    subprocess.run([PY, "-c", code], cwd=sub, env=env, capture_output=True, text=True,
                   check=True)
    return GEOM_H5


def ensure_evb():
    """Ensure clean6.eve and its 12 replicas exist under Codes/testFiles.

    Regenerates them via create_test_evb.py (which builds synthetic packets
    when the real data EVB is not available) if clean6.eve is missing.
    """
    if os.path.exists(CLEAN6):
        return CLEAN6
    os.makedirs(TF, exist_ok=True)
    _run([os.path.join(TF, "create_test_evb.py")], cwd=CODES,
         capture_output=True, text=True, check=True)
    return CLEAN6


def ensure_parallel_h5():
    """Ensure the extract-H5 used by later sections exists (WORK/parallel_test)."""
    if os.path.exists(PARALLEL_H5):
        return PARALLEL_H5
    ensure_evb()
    ensure_drs()
    _run([os.path.join(TEST_DIR, "run_parallel_tests.py")], cwd=CODES,
         capture_output=True, text=True, check=True)
    return PARALLEL_H5


def ensure_dl1():
    """Ensure the clean6 DL1 used by viewer/validation sections exists."""
    if os.path.exists(DL1):
        return DL1
    ensure_config()
    ensure_pixelmap()
    ensure_parallel_h5()
    _run(["wrapper.py", "createh5", os.path.dirname(DL1),
          "--config", "config/config.yaml"], cwd=CODES,
         capture_output=True, text=True, check=True)
    return DL1
