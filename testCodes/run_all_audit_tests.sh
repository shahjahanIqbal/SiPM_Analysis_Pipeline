#!/usr/bin/env bash
# Run every audit harness. Exit 0 only if ALL harnesses report PASS.
# The interpreter defaults to python3; override with SIPM_PYTHON or PY.
set -u
PIPE="$(cd "$(dirname "${BASH_SOURCE[0]}")/Codes" && pwd)"
PY="${PY:-${SIPM_PYTHON:-python3}}"
LOG_DIR="$(dirname "${BASH_SOURCE[0]}")/logs"
mkdir -p "$LOG_DIR"
export HDF5_USE_FILE_LOCKING=FALSE

HARNESSES=(
  run_config_tests.py
  run_evb_tests.py
  run_registry_tests.py
  run_extract_tests.py
  run_parallel_tests.py
  h5_audit.py
  run_image_gen_tests.py
  run_pixelmap_tests.py
  run_createh5_tests.py
  run_hillas_tests.py
  run_obsmeta_tests.py
  run_batch_tests.py
  run_saveimg_tests.py
  run_output_validation.py
  run_dl1_validation.py
  run_viewer_tests.py
  run_repro_tests.py
)

fail=0
for h in "${HARNESSES[@]}"; do
  log="$LOG_DIR/${h%.py}.log"
  echo "==> $h"
  if ! "$PY" "$(dirname "${BASH_SOURCE[0]}")/$h" >"$log" 2>&1; then
    fail=1
  fi
  tail -1 "$log"
done

echo
if [ "$fail" -eq 0 ]; then
  echo "ALL AUDIT HARNESSES: PASS"
else
  echo "ALL AUDIT HARNESSES: FAIL (see $LOG_DIR/)"
fi
exit $fail
