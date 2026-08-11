import os
import glob
import numpy as np
import h5py

BASE = "/tmp/opencode/sipm_audit/evb_test/out"

def audit(name, h5):
    with h5py.File(h5, "r") as h:
        adc = h["adc/roi_data"]
        shape, dtype, comp = adc.shape, adc.dtype.str, adc.compression
        n = shape[0]
        ids = h["events/event_id"][()]
        qual = h["adc/quality"][()]
        roi = h["adc/roi_cell"][()]
        skip = h["adc/skip_cell"][()]
        cstop = h["adc/cstop"][()]
        a = adc[()] if n <= 4000 else None
        zero_rows = int(np.all(a == 0, axis=(1, 2)).sum()) if a is not None else "n/a"
        nonzero_events = int(np.any(a != 0, axis=(1, 2)).sum()) if a is not None else "n/a"
        q = sorted(set(int(x) for x in qual))
        ch_nonzero = int((a.sum(axis=2) != 0).sum()) if a is not None else "n/a"
        contiguous = bool(np.array_equal(ids, np.arange(1, n + 1)))
        mx = int(a.max()) if a is not None else "n/a"
        print(f"{name:28s} n={n:6d} zero_rows={zero_rows} nz_events={nonzero_events} "
              f"ids_first={list(ids[:6])} qual={q} contig_ids={contiguous} "
              f"roi_uniq={sorted(set(np.unique(roi)))} comp={comp} max_adc={mx}")
        return {"n": n, "ids": ids, "qual": q, "zero_rows": zero_rows}

for d in sorted(os.listdir(BASE)):
    h5 = os.path.join(BASE, d, "*.h5")
    files = glob.glob(h5)
    if not files:
        continue
    audit(d, files[0])
