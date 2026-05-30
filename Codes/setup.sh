#!/usr/bin/env bash
# setup.sh — SiPM Pipeline environment and project scaffolding
# Run from the repository root: bash setup.sh

set -euo pipefail

ENV_NAME="scicam"
PYTHON_VERSION="3.11"
MINICONDA_INSTALLER="Miniconda3-latest-Linux-x86_64.sh"
MINICONDA_URL="https://repo.anaconda.com/miniconda/${MINICONDA_INSTALLER}"
MINICONDA_DEFAULT_PATH="${HOME}/miniconda3"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

print_step() {
    echo ""
    echo ">>> $*"
}

command_exists() {
    command -v "$1" &>/dev/null
}

# ---------------------------------------------------------------------------
# Step 1 — Locate or install conda
# ---------------------------------------------------------------------------

print_step "Checking for conda installation..."

CONDA_CMD=""

if command_exists conda; then
    CONDA_CMD="conda"
    echo "    Found conda at: $(command -v conda)"
elif [ -f "${HOME}/miniconda3/bin/conda" ]; then
    CONDA_CMD="${HOME}/miniconda3/bin/conda"
    echo "    Found conda at: ${CONDA_CMD}"
elif [ -f "${HOME}/anaconda3/bin/conda" ]; then
    CONDA_CMD="${HOME}/anaconda3/bin/conda"
    echo "    Found conda at: ${CONDA_CMD}"
elif [ -f "/opt/conda/bin/conda" ]; then
    CONDA_CMD="/opt/conda/bin/conda"
    echo "    Found conda at: ${CONDA_CMD}"
else
    print_step "conda not found. Installing Miniconda3 to ${MINICONDA_DEFAULT_PATH}..."

    if command_exists curl; then
        curl -fsSL "${MINICONDA_URL}" -o "/tmp/${MINICONDA_INSTALLER}"
    elif command_exists wget; then
        wget -q "${MINICONDA_URL}" -O "/tmp/${MINICONDA_INSTALLER}"
    else
        echo "ERROR: Neither curl nor wget is available. Install one and re-run."
        exit 1
    fi

    bash "/tmp/${MINICONDA_INSTALLER}" -b -p "${MINICONDA_DEFAULT_PATH}"
    rm -f "/tmp/${MINICONDA_INSTALLER}"

    CONDA_CMD="${MINICONDA_DEFAULT_PATH}/bin/conda"
    echo "    Miniconda installed at: ${MINICONDA_DEFAULT_PATH}"

    # Initialise conda for the current shell session
    eval "$("${CONDA_CMD}" shell.bash hook)"

    print_step "Adding conda initialisation to ~/.bashrc..."
    "${CONDA_CMD}" init bash
    echo "    Done. Run 'source ~/.bashrc' after this script completes."
fi

# Ensure conda is available in this shell session
eval "$("${CONDA_CMD}" shell.bash hook)" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Step 2 — Create the conda environment
# ---------------------------------------------------------------------------

print_step "Setting up conda environment '${ENV_NAME}'..."

if conda env list | grep -qE "^${ENV_NAME}[[:space:]]"; then
    echo "    Environment '${ENV_NAME}' already exists. Skipping creation."
    echo "    To rebuild from scratch: conda env remove -n ${ENV_NAME}"
else
    echo "    Creating environment with Python ${PYTHON_VERSION}..."
    conda create -n "${ENV_NAME}" python="${PYTHON_VERSION}" -y
    echo "    Environment created."
fi

# ---------------------------------------------------------------------------
# Step 3 — Install Python dependencies
# ---------------------------------------------------------------------------

print_step "Installing Python dependencies into '${ENV_NAME}'..."

# Activate the environment for pip installs
CONDA_ENV_PREFIX="$(conda info --base)/envs/${ENV_NAME}"
PIP="${CONDA_ENV_PREFIX}/bin/pip"

if [ ! -f "${PIP}" ]; then
    # Fallback for older conda layouts
    PIP="${MINICONDA_DEFAULT_PATH:-${HOME}/miniconda3}/envs/${ENV_NAME}/bin/pip"
fi

if [ ! -f "${PIP}" ]; then
    echo "ERROR: Could not locate pip inside the '${ENV_NAME}' environment."
    echo "       Activate the environment manually and run:"
    echo "       pip install numpy h5py scipy matplotlib tqdm tifffile pyyaml click astropy ctapipe joblib pandas"
    exit 1
fi

echo "    Using pip at: ${PIP}"

"${PIP}" install --upgrade pip --quiet

"${PIP}" install \
    "numpy>=1.24" \
    "h5py>=3.8" \
    "scipy>=1.11" \
    "matplotlib>=3.7" \
    "tqdm>=4.65" \
    "tifffile>=2023.1" \
    "pyyaml>=6.0" \
    "click>=8.1" \
    "astropy>=5.3" \
    "ctapipe>=0.19" \
    "joblib>=1.3" \
    "pandas>=2.0"

echo "    All packages installed."

# ---------------------------------------------------------------------------
# Step 4 — Create project directory structure
# ---------------------------------------------------------------------------

print_step "Creating project directories..."

for DIR in config geometry log output OBS_INFO model_parameters plots; do
    if [ ! -d "${DIR}" ]; then
        mkdir -p "${DIR}"
        echo "    Created: ${DIR}/"
    else
        echo "    Already exists: ${DIR}/"
    fi
done

# ---------------------------------------------------------------------------
# Step 5 — Write default config/config.yaml
# ---------------------------------------------------------------------------

CONFIG_PATH="config/config.yaml"

if [ -f "${CONFIG_PATH}" ]; then
    echo ""
    echo "    config/config.yaml already exists — leaving it unchanged."
else
    print_step "Writing default config/config.yaml..."

    cat > "${CONFIG_PATH}" << 'EOF'
# SiPM Pipeline Configuration
# ----------------------------
# Fill in the three path fields (evbfilepath, drsoffset, output) before running.
# All other values match the default camera layout.

camera_geometry:
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
  # Path to a single .evb file or a .txt file listing multiple .evb paths (one per line)
  evbfilepath: null

calib:
  # Path to the DRS offset correction file (downloaded separately)
  drsoffset: null

io:
  # Directory where intermediate and final HDF5 files will be written
  output: output/
EOF

    echo "    Written: ${CONFIG_PATH}"
    echo ""
    echo "    ACTION REQUIRED: Edit ${CONFIG_PATH} and set:"
    echo "      data.evbfilepath  — path to your EVB data file"
    echo "      calib.drsoffset   — path to your DRS offset file"
    echo "      io.output         — output directory (default: output/)"
fi

# ---------------------------------------------------------------------------
# Step 6 — Write a .gitignore if none exists
# ---------------------------------------------------------------------------

if [ ! -f ".gitignore" ]; then
    print_step "Writing .gitignore..."
    cat > ".gitignore" << 'EOF'
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.eggs/

# Pipeline outputs
output/
log/
plots/

# Geometry (auto-generated)
geometry/

# Data files
*.evb
*.h5
*.hdf5

# Conda
.conda/

# Editor
.vscode/
.idea/
*.swp
EOF
    echo "    Written: .gitignore"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo ""
echo "============================================================"
echo " Setup complete."
echo "============================================================"
echo ""
echo " Activate the environment before running the pipeline:"
echo ""
echo "     conda activate ${ENV_NAME}"
echo ""
echo " Then edit config/config.yaml with your file paths."
echo ""
echo " Quick start:"
echo "     python wrapper.py --help"
echo "     python wrapper.py              # launches interactive REPL"
echo ""
