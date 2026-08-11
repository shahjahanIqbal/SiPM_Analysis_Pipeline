# Audit Test Harnesses

Production-readiness audit harnesses for the SiPM analysis pipeline (run 2026-08-11, repo HEAD
`1748c1e`). See `FINAL_REPORT.md` for the results (verdict: NOT READY) and the A–H findings.

## How to run

All harnesses assume the repo lives at `/home/shahjahan/Projects/SiPM_Analysis_Pipeline` and the
Python env is `/home/shahjahan/anaconda3/envs/cta/bin/python` (needs tqdm; ctapipe 0.28). If the
repo moves, update the `PIPE` / `EVB` / `PY` constants at the top of each file.

```bash
cd /home/shahjahan/Projects/SiPM_Analysis_Pipeline/Codes
PY=/home/shahjahan/anaconda3/envs/cta/bin/python
$PY ../testCodes/run_<section>_tests.py
```

or run everything:

```bash
bash ../testCodes/run_all_audit_tests.sh
```

## Harness inventory

| Harness | Section | What it verifies |
|---|---|---|
| `run_config_tests.py` | 2 | Config loading: valid/missing/malformed/empty sections, EVB & DRS paths, roi/layout types (documents silent config overwrite) |
| `run_evb_tests.py` | 3 | 13 EVB replicas + empty/truncated/bad batch (documents phantom rows) |
| `run_registry_tests.py` | 4 | Serial == parallel registry equality; per-event packet counts |
| `run_extract_tests.py` | 5 | data_extractor unit cases: ROI sizes, valid-ch word, payload cid collisions |
| `run_parallel_tests.py` | 6 | wrapper `extract` determinism across workers 1/2/4/default |
| `h5_audit.py` | 7 | Intermediate H5 schema/shape/ids/quality across all 10 EVB outputs |
| `run_image_gen_tests.py` | 8 | adcTomV, peakFinder, gaussian, baseline, offsets, chargePerPixel, mapToPixels, imageGen (documents saturation-flag bug) |
| `run_pixelmap_tests.py` | 9 | PIXEL_MAP 16x16 unique; createPixelMap round-trip; LG/HG channel sets |
| `run_createh5_tests.py` | 10 | create_h5 DL1 (subarray, images, Hillas) + ctapipe reopen |
| `run_hillas_tests.py` | 11 | compute_hillas edge cases (all-zero/uniform/1px/all-negative/all-NaN) |
| `run_obsmeta_tests.py` | 12/13 | calibration mode; RA/DEC, times, CONTEXT attrs |
| `run_batch_tests.py` | 14 | batch `process` (text-file EVB list, missing-file skip, DL1 outputs) |
| `run_saveimg_tests.py` | 15 | saveimg CLI matrix + flag toggles + error handling |
| `run_output_validation.py` | 16 | Bit-exact EVB → extract-H5 round-trip (independent re-derivation via registry) |
| `run_dl1_validation.py` | 16 | DL1 image == imageGen/mapToPixels (float32, with `[::-1]` flip) |
| `run_viewer_tests.py` | 17 | display_reco_events CLI smoke + draw_event paging (headless Agg) |
| `run_resources.py` | 18 | Wall time + peak RSS (extract w1/w4, createh5), sparse-H5 disk behavior |
| `run_repro_tests.py` | 19 | Content-level reproducibility (identical datasets; byte-nondeterminism noted) |
| `data_extractor_dbg.py` | 5 | Trace copy of `data_extractor.py` (debug only) |

## Notes

- `data_extractor_dbg.py` is a debug copy of the production `data_extractor.py`; it is NOT the
  production module and may drift.
- Harnesses write outputs under `/tmp/opencode/sipm_audit/<section>_test/` and never touch
  `Codes/config/config.yaml` (each uses per-case temp configs).
- `run_all_audit_tests.sh` sets `HDF5_USE_FILE_LOCKING=FALSE` and routes stdout/stderr to
  `testCodes/logs/`.
- Extract H5s are read with h5py; DL1s must be read via ctapipe `EventSource` (blosc2-compressed).
