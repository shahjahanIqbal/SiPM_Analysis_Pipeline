# Audit Test Harnesses

Production-readiness audit harnesses for the SiPM analysis pipeline. They run on any
system with no machine-specific configuration: all paths are derived at runtime from
`testCodes/audit_env.py` (repository-relative) or the system temp dir, and the
gitignored inputs a fresh clone lacks (test EVBs, DRS offset file, camera pixel map,
`config/config.yaml`, and the cross-section intermediate products) are generated on
demand.

## Requirements

- Python 3 with `numpy`, `scipy`, `h5py`, `tables`, `yaml`, `tqdm`, `matplotlib`
- `ctapipe` (>= 0.20) for the DL1 sections
- A copy of the repository, e.g. cloned from GitHub

No hardcoded user/environment paths are needed. The interpreter used to run the
pipeline defaults to the one executing the harness; set `SIPM_PYTHON` to force a
different environment (e.g. a conda env):

```bash
export SIPM_PYTHON=/path/to/your/python
```

## How to run

Run one section from anywhere:

```bash
python testCodes/run_<section>_tests.py
```

or run everything (in dependency order, results in `testCodes/logs/`):

```bash
bash testCodes/run_all_audit_tests.sh
```

Exit status is non-zero if any harness fails.

## What gets generated

The first run provisions the following under a clean clone (never overwriting
existing files):

| Input | Where | When missing |
|---|---|---|
| `Codes/testFiles/*.eve` (clean6 + 12 replicas) | repo | `create_test_evb.py` builds synthetic packets (Gaussian pulses) when the real EVB is absent |
| `Codes/config/config.yaml` | repo (gitignored) | a working template pointing at the generated EVB/DRS |
| DRS offset file | repo (gitignored) or stub | a zero-offset stub of the expected shape under the temp dir |
| `Codes/geometry/SiPMCamera.h5` | repo (gitignored) | regenerated via `createPixelMap()` |
| extract H5, DL1 (clean6) | temp dir / `Codes/dl1/` | re-run by the harness that needs them |

Harnesses write outputs under `<tempdir>/sipm_audit/<section>_test/` (override with
`SIPM_AUDIT_WORK`) and never touch a real `config.yaml`. The optional real-data
resource section (`run_resources.py`) only runs when a real EVB is available; point
`SIPM_REAL_EVB` at one to enable it.

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
- Extract H5s are read with h5py; DL1s must be read via ctapipe `EventSource` (blosc2-compressed).
