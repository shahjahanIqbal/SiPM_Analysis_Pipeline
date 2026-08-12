#!/usr/bin/env python3
"""Registry validation: serial vs parallel builders on identical synthetic EVB,
with 1, 2, 4, and default workers. Checks IDs, packets, quality equivalence."""
import sys, os, numpy as np
import audit_env
sys.path.insert(0, audit_env.CODES)
from registry_creator import fetchPacketIndices, build_event_registry, build_event_registry_parallel

TF = audit_env.TF
audit_env.ensure_evb()
FILES = ["clean6.eve", "nonContiguousEventIDs.eve", "eventIDsNotStartingAt1.eve",
         "multipleEndFrames.eve", "duplicatedEventIDs.eve", "noEndFrames.eve", "veryLargeEventIDs.eve"]

def norm(reg):
    return {e: (tuple(sorted(reg[e]["packets"])), reg[e]["quality"]) for e in reg}

for fn in FILES:
    path = os.path.join(TF, fn)
    data = np.memmap(path, dtype=np.uint32, mode="r")
    s, e = fetchPacketIndices(data, 0xFBDA, 0xEDAC)
    ser = norm(build_event_registry(data, s, e))
    results = {}
    ok = True
    for w in (1, 2, 4, None):
        par = norm(build_event_registry_parallel(data, s, e, n_workers=w))
        results[w] = par
        if par != ser:
            ok = False
            print(f"  MISMATCH {fn} workers={w}: serial_keys={set(ser)} par_keys={set(par)}")
    print(f"{fn:32s} serial_vs_parallel_consistent={ok}  events={len(ser)} "
          f"total_packets={sum(len(v[0]) for v in ser.values())} "
          f"qualities={sorted(set(v[1] for v in ser.values()))}")

# Explicit checks on clean6: no dup/missing/wrong-event packets
path = os.path.join(TF, "clean6.eve")
data = np.memmap(path, dtype=np.uint32, mode="r")
s, e = fetchPacketIndices(data, 0xFBDA, 0xEDAC)
reg = build_event_registry(data, s, e)
allpkts = [p for v in reg.values() for p in v["packets"]]
print("\nExplicit clean6 checks:")
print("  unique packets:", len(set(allpkts)) == len(allpkts), f"({len(allpkts)} packets, {len(set(allpkts))} unique)")
print("  per-event counts:", {k: len(v['packets']) for k, v in reg.items()})
