#!/usr/bin/env python3
"""Event extraction tests: build synthetic EVB packets with known ADC values and
verify every output field of dataExtractor against independent expectations."""
import sys, os
import numpy as np
import audit_env
sys.path.insert(0, audit_env.CODES)
from geometry import CameraLayout
from data_extractor import dataExtractor

SIZE = 694
NCH = 9
ROI = 150

cfg = {"camera_geometry": {"name": "SiPMCamera", "pcm_count": 16, "ddb_count": 4,
                            "channel_count": 9, "expected_packets_per_event": 64,
                            "readout": {"roi_samples": ROI},
                            "layout": {"rows": 16, "cols": 16}}}
geom = CameraLayout(cfg)

def make_packet(event_id, cdm, ddb, valid_ch, roi_cells, skips, cstops,
                adc_values, channel_ids, end_at=693):
    """Build one 694-word packet (or shorter if end_at < 693)."""
    p = np.zeros(SIZE, dtype=np.uint32)
    p[0] = (0xFBDA << 16) | SIZE
    p[1] = 0x04FF008F
    p[2] = np.uint32(event_id)
    p[3] = np.uint32(0x123456)          # time_stamp (24 bits)
    p[4] = np.uint32(0x7FFFFFFF & 0x5A5A5A5A)  # time_elapsed
    p[5] = np.uint32(0x03800000 | ((cdm & 0x1F) << 18) | ((ddb & 0x3) << 16))
    p[6] = np.uint32((valid_ch & 0x1FF) << 18)
    h = 7
    for ch in range(NCH):
        roi = roi_cells[ch]
        skip = skips[ch]
        cstop = cstops[ch]
        p[h] = np.uint32((roi & 0x7FF) | ((skip & 0x3FF) << 11) | ((cstop & 0x3FF) << 21))
        vals = adc_values[ch]
        cid = channel_ids[ch]
        for k in range(roi // 2):
            lo = int(vals[2 * k]) & 0x3FFF
            hi = int(vals[2 * k + 1]) & 0x3FFF
            word = (int(cid) << 28) | (hi << 14) | lo
            p[h + 1 + k] = np.uint32(word)
        h += 1 + roi // 2
    p[692] = 0x947a0345
    p[693] = (0xEDAC << 16) | SIZE
    return p[:end_at + 1]

def expect_equal(name, got, want):
    ok = np.array_equal(np.asarray(got), np.asarray(want))
    if not ok:
        print(f"  FAIL {name}: got {got!r} want {want!r}")
    return ok

ok = True

# ---- Test 1: all channels valid, known ADC ----
vals = np.zeros((NCH, ROI), dtype=np.int16)
cstops = np.array([100 + ch for ch in range(NCH)])
skips = np.array([0] * NCH)
for ch in range(NCH):
    vals[ch] = (np.arange(ROI) + ch * 1000) % 15000  # all < 16384
pkt = make_packet(event_id=7, cdm=2, ddb=3, valid_ch=0x1FF,
                  roi_cells=[150] * NCH, skips=skips, cstops=cstops,
                  adc_values=vals, channel_ids=list(range(8)) + [0])
data = np.concatenate([pkt])  # single packet file
res = dataExtractor(7, {"packets": [(0, 693)], "quality": 3}, data, geom, ROI)
ok &= expect_equal("event_id", res["event_id"], 7)
ok &= expect_equal("event_number", res["event_number"], 7)
ok &= expect_equal("adc shape", res["adc"].shape, (576, ROI))
ok &= expect_equal("adc dtype", res["adc"].dtype, np.int16)
for ch in range(NCH):
    g = 2 * (4 * 9) + 3 * 9 + ch  # cdm*36 + ddb*9 + ch = 99 + ch
    ok &= expect_equal(f"adc ch{ch} @gch{g}", res["adc"][g], vals[ch])
    ok &= expect_equal(f"valid ch{ch}", res["valid_mask"][g], True)
    ok &= expect_equal(f"cstop ch{ch}", res["cstop"][g], cstops[ch])
    ok &= expect_equal(f"skip ch{ch}", res["skip_cell"][g], skips[ch])
    ok &= expect_equal(f"roi_cell ch{ch}", res["roi_cell"][g], 150)
ok &= expect_equal("valid_mask others false", res["valid_mask"].sum(), NCH)
ok &= expect_equal("time_stamp", res["time_stamp"], 0x123456)
ok &= expect_equal("time_elapsed", res["time_elapsed"], 0x5A5A5A5A)
ok &= expect_equal("quality", res["quality"], 3)

# ---- Test 2: no channels valid ----
pkt = make_packet(7, 2, 3, 0x000, [150] * NCH, [0] * NCH, cstops, vals,
                  list(range(8)) + [0])
res = dataExtractor(7, {"packets": [(0, 693)], "quality": 3}, pkt, geom, ROI)
ok &= expect_equal("novalid mask sum", res["valid_mask"].sum(), 0)
ok &= expect_equal("novalid adc allzero", res["adc"].sum(), 0)

# ---- Test 3: one valid channel (ch 4 only) ----
pkt = make_packet(7, 2, 3, 0x010, [150] * NCH, [0] * NCH, cstops, vals,
                  list(range(8)) + [0])
res = dataExtractor(7, {"packets": [(0, 693)], "quality": 3}, pkt, geom, ROI)
g4 = 99 + 4
ok &= expect_equal("one-valid mask", res["valid_mask"].sum(), 1)
ok &= expect_equal("one-valid ch4", res["valid_mask"][g4], True)
ok &= expect_equal("one-valid ch4 adc", res["adc"][g4], vals[4])

# ---- Test 4: channel 8 special mapping (cid 0 -> ch 8) ----
vals8 = np.full((NCH, ROI), 5000, dtype=np.int16)
pkt = make_packet(7, 2, 3, 0x1FF, [150] * NCH, [0] * NCH, cstops, vals8,
                  list(range(8)) + [0])
res = dataExtractor(7, {"packets": [(0, 693)], "quality": 3}, pkt, geom, ROI)
ok &= expect_equal("ch8 fix mask", res["valid_mask"][99 + 8], True)
ok &= expect_equal("ch8 fix adc", res["adc"][99 + 8], vals8[8])

# ---- Test 5: saturated 14-bit ADC (16383) ----
sat = np.full((NCH, ROI), 16383, dtype=np.int16)
pkt = make_packet(7, 2, 3, 0x1FF, [150] * NCH, [0] * NCH, cstops, sat,
                  list(range(8)) + [0])
res = dataExtractor(7, {"packets": [(0, 693)], "quality": 3}, pkt, geom, ROI)
ok &= expect_equal("sat adc max", res["adc"][99 + 1].max(), 16383)

# ---- Test 6: zero ADC ----
zero = np.zeros((NCH, ROI), dtype=np.int16)
pkt = make_packet(7, 2, 3, 0x1FF, [150] * NCH, [0] * NCH, cstops, zero,
                  list(range(8)) + [0])
res = dataExtractor(7, {"packets": [(0, 693)], "quality": 3}, pkt, geom, ROI)
ok &= expect_equal("zero adc sum", res["adc"].sum(), 0)

# ---- Test 7: odd ROI length (149) ----
odd_vals = np.arange(ROI, dtype=np.int16).reshape(1, -1).repeat(NCH, axis=0)
pkt = make_packet(7, 2, 3, 0x1FF, [149] * NCH, [0] * NCH, cstops, odd_vals,
                  list(range(8)) + [0])
res = dataExtractor(7, {"packets": [(0, 693)], "quality": 3}, pkt, geom, ROI)
ok &= expect_equal("odd roi len", res["roi_cell"][99 + 0], 149)
# data_write length ROI_Cell; only 2*(149//2)=148 samples written; last stays 0
ok &= expect_equal("odd roi sample 148", res["adc"][99 + 0, 148], 0)
ok &= expect_equal("odd roi sample 0", res["adc"][99 + 0, 0], odd_vals[0, 0])

# ---- Test 8: truncated channel data (packet ends mid-channel) ----
pkt = make_packet(7, 2, 3, 0x1FF, [150] * NCH, [0] * NCH, cstops, vals,
                  list(range(8)) + [0], end_at=7 + 2 * 76 + 20)  # end inside ch2 data
try:
    res = dataExtractor(7, {"packets": [(0, 7 + 2 * 76 + 20)], "quality": 3}, pkt, geom, ROI)
    print("  FAIL truncated: no exception raised")
    ok = False
except IndexError as e:
    print(f"  NOTE truncated channel data -> dataExtractor raises {type(e).__name__}: {e} "
          f"(relies on worker-level try/except to avoid killing the batch)")

# ---- Test 9: wrong channel id in payload word ----
# put channel_id=5 in a ch0 data word -> data written to gch(2,3,5) not gch(2,3,0)
evil = vals.copy()
pkt = make_packet(7, 2, 3, 0x1FF, [150] * NCH, [0] * NCH, cstops, evil,
                  channel_ids=[5] + list(range(1, 8)) + [0])
res = dataExtractor(7, {"packets": [(0, 693)], "quality": 3}, pkt, geom, ROI)
print("  NOTE payload-cid test: ch0 adc landed at gch5=", np.all(res["adc"][104] == evil[0]),
      "(payload channel id, not loop index, determines row)")

print("\nEXTRACTION TESTS PASSED" if ok else "\nEXTRACTION TESTS FAILED")
sys.exit(0 if ok else 1)
