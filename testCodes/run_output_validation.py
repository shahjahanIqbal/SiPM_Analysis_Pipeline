import os
import sys
import numpy as np
import h5py

PIPE = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes"
sys.path.insert(0, PIPE)
os.chdir(PIPE)
os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"

from config_loader import load_config
from geometry import CameraLayout

cfg = load_config("config/config.yaml")
geom = CameraLayout(cfg)

ok = True
def check(name, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  {'PASS' if cond else 'FAIL'} {name} {detail}")

EVB = "/home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes/testFiles/clean6.eve"
H5 = "/tmp/opencode/sipm_audit/parallel_test/w1/clean6_processed.h5"
ROI = 150

# independent re-implementation of unpacking (from the EVB layout)
data = np.fromfile(EVB, dtype=np.uint32, offset=0)
n_words = int(data[0] & 0xFFFF)
NCH = geom.N_CH_PER_DDB

# use the registry's own (si, ei) packet spans to re-derive ADC independently
sys.path.insert(0, PIPE)
from registry_creator import fetchPacketIndices, build_event_registry
starts, ends = fetchPacketIndices(data, 0xFBDA, 0xEDAC)
reg = build_event_registry(data, starts, ends)
packets_by_event = {eid: [p for p in reg[eid]["packets"]] for eid in reg}

def unpack_event(eid):
    adc = np.zeros((geom.N_GLOBAL_CH, ROI), dtype=np.int16)
    for si, ei in packets_by_event[eid]:
        pkt = data[si : ei]
        cdm = (pkt[5] >> 18) & 0x1F
        ddb = (pkt[5] >> 16) & 0x3
        valid = (pkt[6] >> 18) & 0x1FF
        hdr = 7
        for ch in range(NCH):
            if hdr >= ei:
                break
            roi_cell = pkt[hdr] & 0x7FF
            cid = (pkt[hdr + 1] >> 28) & 0x7
            if ch == 8 and cid == 0:
                cid = 8
            if (valid >> ch) & 1:
                g = geom.global_channel_id(cdm, ddb, cid)
                for k in range(roi_cell // 2):
                    adc[g, 2 * k] = pkt[hdr + 1 + k] & 0x3FFF
                    adc[g, 2 * k + 1] = (pkt[hdr + 1 + k] >> 14) & 0x3FFF
            hdr += 1 + roi_cell // 2
    return adc

with h5py.File(H5, "r") as f:
    h5_adc = f["adc/roi_data"][:]
    h5_ids = f["events/event_id"][:]

print(f"  H5 ids={list(h5_ids)}")
# clean6 ids 1..6, rows aligned event_id-1
for eid in [1, 2, 6]:
    ref = unpack_event(eid)
    got = h5_adc[eid - 1]
    diff = np.abs(ref.astype(int) - got.astype(int))
    check(f"event {eid}: ADC round-trip exact", diff.max() == 0,
          f"maxdiff={diff.max()} ref_nz={int((ref!=0).sum())}")
    check(f"event {eid}: nonzero entries present", int((ref != 0).sum()) > 40000,
          f"nz_entries={int((ref!=0).sum())}")

# sample-level spot check on a specific gch for event 1
ref = unpack_event(1)
g = geom.global_channel_id(0, 0, 0)
print(f"  NOTE event1 gch(0,0,0) first 8 samples: {list(ref[g,:8])}")
print("  NOTE H5 event1 gch(0,0,0) first 8 samples:", list(h5_adc[0, g, :8]))
print("OUTPUT_VALIDATION:", "PASS" if ok else "FAIL")
