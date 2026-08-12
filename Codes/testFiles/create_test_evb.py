#!/usr/bin/env python3
"""Generate 12 EVB replica test files under Codes/testFiles/.

Each file is derived from pristine in-memory packets read from the real 339 EVB
file and applies exactly ONE targeted mutation, so every test exercises a single
defect in isolation.

Real-file base packet layout (mirrored exactly here):
  - fixed packet size 694 words; START marker 0xFBDA and END marker 0xEDAC in the
    upper 16 bits, packet size 694 in the lower 16 bits of the start/end words
  - 64 packets per event (16 CDM x 4 DDB)
  - event id   at word +2
  - time_stamp at +3, time_elapsed at +4
  - CDM/DDB    in +5   ((>>18)&0x1F, (>>16)&0x3)
  - validCh    in +6   ((>>18)&0x1FF)
  - 9 channel headers at +7 + c*76 (roi_cell, skip_cell, cstop)
  - END at +693
"""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from registry_creator import fetchPacketIndices, build_event_registry

SRC = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "data",
        "s0534+2201_339_flashCAL_14122025_2_EVBdata.eve",
    )
)
OUT = os.path.dirname(os.path.abspath(__file__))

START = 0xFBDA
END = 0xEDAC
SIZE = 694


def load_source():
    data = np.memmap(SRC, dtype=np.uint32, mode="r")
    header = (data >> 16) & 0xFFFF
    starts = np.where(header == START)[0]
    ends = np.where(header == END)[0]
    print(f"source: {data.size:,} words | starts={starts.size:,} ends={ends.size:,}")
    end_for_start = ends[np.searchsorted(ends, starts, side="left")]
    events = {}
    for si, ei in zip(starts, end_for_start):
        ev = int(data[si + 2] & 0x7FFFFFFF)
        events.setdefault(ev, []).append((int(si), int(ei)))
    for ev, pkt in events.items():
        assert len(pkt) == 64, f"event {ev} has {len(pkt)} packets (expected 64)"
        for si, ei in pkt:
            assert ei - si + 1 == SIZE, f"packet {si}-{ei} not {SIZE} words"
    print(f"source: {len(events)} events, all {SIZE}-word packets")
    return data, events


def make_synthetic_source(n_events=10):
    """Build a self-contained source when the real data EVB is unavailable.

    Constructs n_events events (ids 1..n_events) of 64 packets each in memory,
    mirroring the real packet layout: 9 channel headers at +7 + ch*76, each with
    75 data words (two 14-bit ADC samples per word), START/END markers, and a
    Gaussian pulse on a small baseline so downstream image tests see realistic
    pulses. Returns (data_array, events) matching load_source()'s contract.
    """
    roi = 150
    n_wave = roi // 2                      # 75 ADC words per channel
    n_header = 9 * (1 + n_wave)            # 9 channels * 76 words
    t = np.arange(roi, dtype=np.float64)
    gauss = np.exp(-0.5 * ((t - 60) / 5.0) ** 2)
    packets = []
    for ev in range(1, n_events + 1):
        for cdm in range(16):
            for ddb in range(4):
                p = np.zeros(SIZE, dtype=np.uint32)
                p[0] = (START << 16) | SIZE
                p[1] = 0x04FF008F
                p[2] = np.uint32(ev)
                p[3] = np.uint32(0x123456 + ev)
                p[4] = np.uint32(0x5A5A5A5A)
                p[5] = np.uint32(0x03800000 | ((cdm & 0x1F) << 18) | ((ddb & 0x3) << 16))
                p[6] = np.uint32(0x1FF << 18)      # all 9 channels valid
                for ch in range(9):
                    h = 7 + ch * (1 + n_wave)
                    cstop = 100 + ch
                    p[h] = np.uint32((roi & 0x7FF) | ((cstop & 0x3FF) << 21))
                    amp = 9000 + 100 * ((cdm * 4 + ddb) * 9 + ch) % 4000
                    adc = np.clip(np.rint(1500 + amp * gauss), 0, 16383).astype(np.int16)
                    cid = ch if ch < 8 else 0
                    for k in range(n_wave):
                        lo = int(adc[2 * k]) & 0x3FFF
                        hi = int(adc[2 * k + 1]) & 0x3FFF
                        p[h + 1 + k] = np.uint32((cid << 28) | (hi << 14) | lo)
                p[692] = 0x947a0345
                p[693] = (END << 16) | SIZE
                packets.append(p)
    data = np.concatenate(packets).astype(np.uint32)
    events = {}
    span = 64 * SIZE
    for i, ev in enumerate(range(1, n_events + 1)):
        base = i * span
        events[ev] = [(base + j * SIZE, base + (j + 1) * SIZE - 1) for j in range(64)]
    print(f"source: SYNTHETIC ({n_events} events, {SIZE}-word packets, Gaussian pulses)")
    return data, events


def build_events(data, events, ids):
    """Return list of events; each event = list of packet arrays."""
    return [[np.array(data[si:ei + 1]) for si, ei in events[ev]] for ev in ids]


def renumber(evs, mapping):
    """Rewrite the event-id word (+2) of every packet according to mapping."""
    for ev in evs:
        for p in ev:
            old = int(p[2] & 0x7FFFFFFF)
            p[2] = np.uint32(mapping.get(old, old))


def flat(evs):
    return [p for ev in evs for p in ev]


def write(name, packets):
    arr = np.concatenate(packets).astype(np.uint32)
    path = os.path.join(OUT, name)
    arr.tofile(path)
    return path, arr.size


def verify(path, label):
    data = np.memmap(path, dtype=np.uint32, mode="r")
    starts, ends = fetchPacketIndices(data, START, END)
    reg = build_event_registry(data, starts, ends)
    ids = sorted(reg)
    qual = {e: reg[e]["quality"] for e in ids}
    n_pkt = sum(len(reg[e]["packets"]) for e in ids)
    shown = ids[:5]
    print(
        f"  {label:34s} words={data.size:>9,} starts={len(starts):>6} "
        f"ends={len(ends):>6} events={len(ids):>2} pkts={n_pkt:>4} "
        f"ids={shown}{'...' if len(ids) > 5 else ''} qual={qual}"
    )


def main():
    try:
        data, events = load_source()
    except (FileNotFoundError, ValueError):
        print(f"note: real EVB source not found at {SRC}; using synthetic data")
        data, events = make_synthetic_source()

    # ---- 0. clean6.eve : pristine events 1..6 (baseline) ----
    evs = build_events(data, events, list(range(1, 7)))
    write("clean6.eve", flat(evs))

    # ---- 1. noStartFrames.eve : upper 16 bits of every START word zeroed ----
    evs = build_events(data, events, list(range(1, 7)))
    for p in flat(evs):
        p[0] = p[0] & 0xFFFF
    write("noStartFrames.eve", flat(evs))

    # ---- 2. noEndFrames.eve : upper 16 bits of every END word zeroed ----
    evs = build_events(data, events, list(range(1, 7)))
    for p in flat(evs):
        p[-1] = p[-1] & 0xFFFF
    write("noEndFrames.eve", flat(evs))

    # ---- 3. mismatchedStartEndFrames.eve : one END frame declares size 700 ----
    evs = build_events(data, events, list(range(1, 7)))
    p = evs[0][0]  # first packet of event 1
    p[-1] = (p[-1] & 0xFFFF0000) | 700
    write("mismatchedStartEndFrames.eve", flat(evs))

    # ---- 4. multipleEndFrames.eve : extra END marker inserted mid-packet ----
    evs = build_events(data, events, list(range(1, 7)))
    p = evs[0][0]  # first packet of event 1
    p[300] = np.uint32(0xEDAC0000 | SIZE)
    write("multipleEndFrames.eve", flat(evs))

    # ---- 5. packetSizeMismatch.eve : END displaced 3 words early (691 span) ----
    evs = build_events(data, events, list(range(1, 7)))
    p = evs[0][0]  # first packet of event 1
    p[690] = np.uint32(0xEDAC0000 | 691)
    p[693] = np.uint32(0x12345678)  # remove original END marker
    write("packetSizeMismatch.eve", flat(evs))

    # ---- 6. incompleteFinalPacket.eve : last packet truncated to 100 words ----
    evs = build_events(data, events, list(range(1, 7)))
    last = evs[-1][-1][:100]
    packets = flat(evs[:-1] + [evs[-1][:-1]]) + [last]
    write("incompleteFinalPacket.eve", packets)

    # ---- 7. malformedPacketHeader.eve : CDM_ID=31 -> gch out of bounds ----
    evs = build_events(data, events, list(range(1, 7)))
    p = evs[1][0]  # first packet of event 2
    p[5] = np.uint32((int(p[5]) & ~(0x1F << 18)) | (31 << 18))
    write("malformedPacketHeader.eve", flat(evs))

    # ---- 8. duplicatedEventIDs.eve : event 4 renumbered to id 2 ----
    evs = build_events(data, events, list(range(1, 5)))
    renumber([evs[3]], {4: 2})
    write("duplicatedEventIDs.eve", flat(evs))

    # ---- 9. missingEventIDs.eve : event 3 absent (ids 1,2,4,5,6) ----
    evs = build_events(data, events, [1, 2, 4, 5, 6])
    write("missingEventIDs.eve", flat(evs))

    # ---- 10. nonContiguousEventIDs.eve : ids 1,2,3,5,7,9 ----
    evs = build_events(data, events, [1, 2, 3, 5, 7, 9])
    write("nonContiguousEventIDs.eve", flat(evs))

    # ---- 11. eventIDsNotStartingAt1.eve : ids 1..6 renumbered to 10..15 ----
    evs = build_events(data, events, list(range(1, 7)))
    renumber(evs, {i: i + 9 for i in range(1, 7)})
    write("eventIDsNotStartingAt1.eve", flat(evs))

    # ---- 12. veryLargeEventIDs.eve : ids renumbered to 100000..100005 ----
    evs = build_events(data, events, list(range(1, 7)))
    renumber(evs, {i: 100000 + i - 1 for i in range(1, 7)})
    write("veryLargeEventIDs.eve", flat(evs))

    print("\nVerification (fetchPacketIndices + build_event_registry):")
    verify(os.path.join(OUT, "clean6.eve"), "clean6.eve")
    verify(os.path.join(OUT, "noStartFrames.eve"), "noStartFrames.eve")
    verify(os.path.join(OUT, "noEndFrames.eve"), "noEndFrames.eve")
    verify(os.path.join(OUT, "mismatchedStartEndFrames.eve"), "mismatchedStartEndFrames.eve")
    verify(os.path.join(OUT, "multipleEndFrames.eve"), "multipleEndFrames.eve")
    verify(os.path.join(OUT, "packetSizeMismatch.eve"), "packetSizeMismatch.eve")
    verify(os.path.join(OUT, "incompleteFinalPacket.eve"), "incompleteFinalPacket.eve")
    verify(os.path.join(OUT, "malformedPacketHeader.eve"), "malformedPacketHeader.eve")
    verify(os.path.join(OUT, "duplicatedEventIDs.eve"), "duplicatedEventIDs.eve")
    verify(os.path.join(OUT, "missingEventIDs.eve"), "missingEventIDs.eve")
    verify(os.path.join(OUT, "nonContiguousEventIDs.eve"), "nonContiguousEventIDs.eve")
    verify(os.path.join(OUT, "eventIDsNotStartingAt1.eve"), "eventIDsNotStartingAt1.eve")
    verify(os.path.join(OUT, "veryLargeEventIDs.eve"), "veryLargeEventIDs.eve")


if __name__ == "__main__":
    main()
