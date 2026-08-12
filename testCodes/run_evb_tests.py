#!/usr/bin/env python3
"""EVB input tests: run wrapper.py extract on every malformed/edge-case EVB and
inspect the resulting intermediate H5 for rows, quality, event IDs, zero rows."""
import os
import subprocess
import sys
import numpy as np
import h5py

import audit_env

CODES = audit_env.CODES
WORK = os.path.join(audit_env.WORK, "evb_test")
CFGS = os.path.join(WORK, "cfgs")
OUT = os.path.join(WORK, "out")
PY = audit_env.PY
TF = audit_env.TF
DRS = audit_env.ensure_drs()
audit_env.ensure_evb()

def make_cfg(name):
    os.makedirs(CFGS, exist_ok=True)
    outdir = os.path.join(OUT, name)
    os.makedirs(outdir, exist_ok=True)
    text = f"""camera_geometry:
  name: SiPMCamera
  pcm_count: 16
  ddb_count: 4
  channel_count: 9
  expected_packets_per_event: 64
  readout:
    roi_samples: 150
    adc_bits: 14
    channel_zero_dual_map: true
  layout:
    rows: 16
    cols: 16
    ordering: column-major
    pixel_size_mm: 22.1
    pixel_gap_mm: 0.05
data:
  evbfilepath: {os.path.join(TF, name + '.eve')}
calib:
  drsoffset: {DRS}
io:
  output: {outdir}
"""
    p = os.path.join(CFGS, f"{name}.yaml")
    with open(p, "w") as f:
        f.write(text)
    return p, outdir

def extract(name, evb=None, timeout=180):
    p, outdir = make_cfg(name)
    if evb is not None:
        # overwrite evb path in config
        text = open(p).read()
        start = text.index("evbfilepath:")
        end = text.index("calib:")
        new = text[:start] + f"evbfilepath: {evb}\n" + text[end:]
        with open(p, "w") as f:
            f.write(new)
    env = dict(os.environ); env["MPLBACKEND"] = "Agg"
    proc = subprocess.run([PY, "wrapper.py", "extract", "--config", p],
                          cwd=CODES, env=env, capture_output=True, text=True, timeout=timeout)
    return proc

def inspect_h5(outdir):
    files = [f for f in os.listdir(outdir) if f.endswith(".h5")]
    if not files:
        return None
    h5 = os.path.join(outdir, files[0])
    with h5py.File(h5, "r") as f:
        ev = f["events/event_id"][:]
        qual = f["adc/quality"][:]
        adc = f["adc/roi_data"]
        nevents, nch, roi = adc.shape
        if nevents > 20000:
            return dict(h5=h5, rows=nevents, roi=roi, nch=nch,
                        ids=ev[:20].tolist() + ["..."], qual=qual[:20].tolist(),
                        zero_rows="skipped(huge)", nonzero_rows="skipped(huge)")
        zero_rows = int(np.sum(np.all(adc[...] == 0, axis=(1, 2))))
        return dict(h5=h5, rows=nevents, roi=roi, nch=nch,
                    ids=ev.tolist(), qual=qual.tolist(), zero_rows=zero_rows,
                    nonzero_rows=nevents - zero_rows)

def main():
    cases = [
        ("clean6", None),
        ("noStartFrames", None),
        ("noEndFrames", None),
        ("mismatchedStartEndFrames", None),
        ("multipleEndFrames", None),
        ("packetSizeMismatch", None),
        ("incompleteFinalPacket", None),
        ("malformedPacketHeader", None),
        ("duplicatedEventIDs", None),
        ("missingEventIDs", None),
        ("nonContiguousEventIDs", None),
        ("eventIDsNotStartingAt1", None),
        ("veryLargeEventIDs", None),
    ]
    for name, evb in cases:
        proc = extract(name, evb)
        info = inspect_h5(os.path.join(OUT, name))
        if info is None:
            print(f"{name:32s} exit={proc.returncode} NO-H5")
            err = [l for l in proc.stdout.splitlines() if "ERROR" in l or "Error" in l]
            print(f"    {err[:2]}")
        else:
            print(f"{name:32s} exit={proc.returncode} rows={info['rows']} "
                  f"ids={info['ids'][:8]}{'...' if info['rows']>8 else ''} "
                  f"qual={set(info['qual'])} zero_rows={info['zero_rows']} "
                  f"nonzero={info['nonzero_rows']} nch={info['nch']} roi={info['roi']}")

    # empty EVB
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "empty.eve"), "wb") as f:
        pass
    proc = extract("empty", os.path.join(OUT, "empty.eve"))
    print(f"{'empty':32s} exit={proc.returncode} " +
          f"h5={'yes' if inspect_h5(os.path.join(OUT,'empty')) else 'no'}")

    # truncated EVB (half of clean6)
    d = np.memmap(f"{TF}/clean6.eve", dtype=np.uint32, mode="r")
    d[: len(d) // 2].tofile(os.path.join(OUT, "truncated.eve"))
    proc = extract("truncated", os.path.join(OUT, "truncated.eve"))
    info = inspect_h5(os.path.join(OUT, "truncated"))
    print(f"{'truncated':32s} exit={proc.returncode} info={info}")

    # missing EVB in batch list (one valid + one missing)
    batch1 = os.path.join(OUT, "batch1.txt")
    with open(batch1, "w") as f:
        f.write(f"{TF}/clean6.eve\n{os.path.join(audit_env.WORK, 'MISSING.eve')}\n")
    proc = extract("batch1", batch1)
    info = inspect_h5(os.path.join(OUT, "batch1"))
    print(f"{'batch1(mix)':32s} exit={proc.returncode} rows={info and info['rows']}")
    outl = [l for l in proc.stdout.splitlines() if "Skipping missing" in l]
    print(f"    warnings={outl[:2]}")

    # all EVBs missing
    batch2 = os.path.join(OUT, "batch2.txt")
    with open(batch2, "w") as f:
        f.write(f"{os.path.join(audit_env.WORK, 'MISSING1.eve')}\n"
                f"{os.path.join(audit_env.WORK, 'MISSING2.eve')}\n")
    proc = extract("batch2", batch2)
    print(f"{'batch2(all missing)':32s} exit={proc.returncode}")
    err = [l for l in proc.stdout.splitlines() if "Error" in l or "ERROR" in l]
    print(f"    {err[:3]}")

    # nonexistent EVB direct
    proc = extract("nonexistent", os.path.join(audit_env.WORK, "MISSING.eve"))
    print(f"{'nonexistent-evb':32s} exit={proc.returncode}")
    err = [l for l in proc.stdout.splitlines() if "Error" in l or "ERROR" in l]
    print(f"    {err[:2]}")

if __name__ == "__main__":
    main()
