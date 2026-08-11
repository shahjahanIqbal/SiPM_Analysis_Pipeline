# SiPM Analysis Pipeline — Production-Readiness Audit (Final Report)

Audit date: 2026-08-11 · Repo HEAD: `1748c1e` · Environment: anaconda env `cta`, ctapipe 0.28
Scope: `wrapper.py, event_proc_parallel.py, registry_creator.py, data_extractor.py, geometry.py,
image_gen.py, create_h5.py, save_raw_img.py, display_reco_events.py, config_loader.py, setup.sh`.
`config/config.yaml` unmodified (verified via `git diff`). No production code changed during this audit.

Test harnesses: `/tmp/opencode/sipm_audit/run_{config,evb,registry,extract,parallel,image_gen,
pixelmap,createh5,hillas,obsmeta,batch,saveimg,viewer,repro}_tests.py`, `h5_audit.py`,
`run_output_validation.py`, `run_dl1_validation.py`, `run_resources.py`.

## Verdict: NOT READY

Core extraction is scientifically correct on well-formed input (bit-exact round-trip), but the
pipeline silently fabricates data on malformed/edge-case EVBs, and several of those failures
propagate all the way into DL1 products. These are correctness bugs, not polish items.

---

## A. Run-level metadata
- Real-data run (run_339, 444 MB, 2500 events, w4): extraction OK in ~30 s (~84 ev/s, gzip 0.80),
  `ids 1..2500 contiguous`, `quality {3:2500}`, 0 zero rows, 209.6 M nonzero samples.
  sha256 `95965d6c…` (345 MB). Clean6 sha256 `bce79179…`.
- createh5 requires the run JSON present in `OBS_INFO/<stem>.json` (or `--json-dir`); without it the
  run is skipped with a warning and **exit 0** → the batch "succeeds" but produces no DL1.
- `evt.txt` still lists stale Desktop paths (points nowhere).

## B. Event-content checks
- EVB → extract-H5 round-trip is **bit-exact** (maxdiff = 0) for events 1, 2, 6 of clean6, re-derived
  independently from registry packet offsets (verified `data_extractor.py` framing: 64 packets/event,
  694 words/packet, stride `1 + roi//2`, cid-8 workaround, `gch = cdm*(N_DDB*9)+ddb*9+ch`).
- H5 → DL1 matches `imageGen`/`mapToPixels` to float32 precision (max rel err ~1e-7) **after applying
  the vertical flip** (`create_h5.py:463` `[::-1]`). The DL1 stores the flipped orientation; saveimg
  PNGs store the unflipped one — a user comparing them sees a vertical mirror.
- Registry: serial ≡ parallel (workers 1/2/4/None), clean6 = 384 unique packets, 64/event, no dup/missing.
- Real data: quality all 3, zero rows 0.

## C. Phantom events (CRITICAL, verified at every layer)
Datasets are sized `max(event_id)` and filled at `event_id - 1` (`event_proc_parallel.py`):
`nevents = max(registry)`, `idx = event_id - 1`. Any deviation from contiguous 1-based IDs silently
produces zero-filled phantom events (quality 0, ADC 0) or silent data loss:

| Input | Registry quality | Rows written | Phantom rows |
|---|---|---|---|
| clean6 | {3} | 6 | 0 |
| noEndFrames | {0} | 6 | 6 |
| malformedPacketHeader | {1} | 6 | 1 |
| missingEventIDs | {1} | 6 | 1 |
| nonContiguousEventIDs | {1} | 6 | 3 |
| eventIDsNotStartingAt1 | {1} | 15 | 9 |
| veryLargeEventIDs | {1} | 100 005 | 99 999 (347 MB sparse) |
| duplicatedEventIDs | {3} | 3 | — (2 events silently merged/lost) |

Phantoms propagate into DL1: `noEndFrames` → all 6 events `event_id=0`, image sum 21.6 (a **non-zero**
fake signal), Hillas NaN. Clean6/missingEventIDs DL1s are NaN-free; noEndFrames DL1 carries
**36 NaN Hillas fields** (6 ev × 6 params) that are written to the DL1 and never filtered.

## D. Duplicate/missing packet semantics
- Duplicated event IDs: only 3 rows; packets are merged into one registry entry, duplicates silently
  discarded → data loss without any error/warning (quality still 3 — the checker does not flag it).
- Missing event IDs / non-contiguous / not-starting-at-1 / very large IDs: all silently "handled" as
  phantom rows. No warning is raised at extraction time.

## E. DL1 / Hillas
- compute_hillas returns False (all-zero, uniform, 1-pixel, all-negative, all-NaN) without crashing;
  but the `ImageParametersContainer.hillas` is left all-NaN and still written to the DL1.
- ctapipe 0.28 fields differ between fresh containers (`fov_lon/fov_lat`) and reopened tables
  (`x/y`, plain floats) — code must handle both; the viewer does not guard against NaN Hillas.

## F. Config handling
- `config_loader.load_config` auto-creates a default config and **silently overwrites** the existing
  file on any load failure (9/17 malformed/empty/missing-section cases → overwrite=True). A user config
  can be destroyed by a typo. `Codes/config/config.yaml` itself is unchanged (this audit never invoked
  `load_config` against it; every test used temp configs).
- DRS-offset path and `roi`/`layout` types are not validated at config load (`roi: "149"` and
  `layout: "CAMEL"` both exit 0, fail later inside image_gen / h5py).

## G. Known defects (HIGH/MEDIUM)
1. **Saturation flag never fires** (HIGH): `adcTomV` checks `pulse_mV > 1000` **before** adding offsets,
   on raw 14-bit ADC whose max = 999.94 mV → flag can never be True (verified: +600 mV offset, full-scale).
2. **Phantom-row machinery** (HIGH): see C. Core fix: size by `len(registry)`, write rows by registry
   order, and store a row↔event map.
3. **Duplicated event IDs silently merged** (HIGH): registry must warn/flag duplicate packet IDs.
4. **Odd ROI** (MEDIUM): ROI=149 writes 148 samples, last stays 0.
5. **CWD-dependent imports** (MEDIUM): `image_gen.py` runs `load_config("config/config.yaml")` at
   import + module-level DRS/pixel-map loads → running wrapper from anywhere but `Codes/` recreates a
   default config in CWD and fails (`expected str... not NoneType`). `createPixelMap` writes to
   `../geometry` relative to CWD. Batch `process` writes DL1 to CWD-relative `dl1/`.
6. **Byte-nondeterminism** (LOW/MEDIUM): repeated runs are content-identical but byte-different (HDF5
   chunk placement order) → checksum-based QA fails; validate at dataset level or h5repack.
7. **Viewer** (LOW): state lives in module globals (`source`, `event_iter`, `state`), CLI-only; no NaN
   guard; `event_id=0`/phantom events render as blank.
8. **createh5 missing-JSON skips exit 0** (MEDIUM): silent no-DL1 success.
9. **Batch missing EVB** warns + continues (exit 0) — arguably OK, but the aggregate exit status is 0.

## H. Recommendations (priority order)
1. Rebuild extraction sizing/indexing on registry order (not `event_id`); write a row→event_id array;
   reject or warn on non-contiguous/duplicate/missing IDs (registry is already 90% of the machinery).
2. Fix `adcTomV` saturation check to run after offset application; add a unit test with a saturated pulse.
3. Make `createh5` fail (nonzero exit) when all runs were skipped for missing JSON.
4. Remove cwd-dependent module-level loads in `image_gen.py` (lazy init or explicit config passing);
   make `createPixelMap` and batch `dl1/` output path-safe.
5. Guard Hillas writing: skip/flag NaN-parameter events instead of persisting NaN; drop phantom rows
   upstream so they never reach DL1.
6. Registry: raise quality and log a WARNING on duplicated packet IDs.
7. Add a checksum/integrity pass over extract H5 at creation (content-level), and document the
   byte-nondeterminism so future checksum tests don't false-fail.
8. Add a smoke CI: run 1 wrapper extract + 1 createh5 on a small synthetic EVB, assert row count ==
   event count and no phantom rows.

## Test-pass summary
Static: PASS(module compile/import; pyflakes warnings) · Config: 17 cases (9 overwrite bug) ·
EVB 13 replicas: PASS (defects documented as expected FAILs) · Registry: PASS · Extraction: PASS
(truncated-channel IndexError noted) · Parallelism: PASS · H5 audit: PASS · image_gen: 21 PASS + 1
BUG (saturation) · Pixel map: PASS · create_h5/DL1: PASS · Hillas edge cases: PASS (NaN caveat) ·
Calibration/obs metadata: PASS · Batch: PASS · saveimg: PASS · Output validation: PASS (bit-exact;
DL1 flip documented) · Viewer: PASS (CLI-only caveat) · Resources: PASS (63 MB RSS extract /
375 MB RSS createh5, 30 s real-339) · Reproducibility: PASS content-deterministic · Integrity:
PASS (git clean of audit, config untouched, NaN scan = 0 except phantom-DL1 Hillas NaN).
