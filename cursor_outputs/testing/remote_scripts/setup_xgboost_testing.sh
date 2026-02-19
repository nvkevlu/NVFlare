#!/bin/bash
# XGBoost Federated Learning Test Environment Setup
# For Linux machines with CUDA-capable GPU
# Branch: fix_xgboost_27
# Date: 2026-02-04

set -e  # Exit on any error

# ============================================
# CONFIGURATION - Set your NVFlare repo path here
# ============================================
REPO_DIR="/localhome/local-kevlu/nvflare_testing/NVFlare"
BRANCH_NAME="fix_xgboost_adaptor"  # Branch with all XGBoost fixes
# ============================================

# Optional: pass --clean to remove existing venv and reinstall everything (slow)
FORCE_CLEAN=0
for arg in "$@"; do
    if [ "$arg" = "--clean" ]; then
        FORCE_CLEAN=1
        break
    fi
done

echo "=========================================="
echo "XGBoost FL Test Environment Setup"
echo "=========================================="
[ "$FORCE_CLEAN" -eq 1 ] && echo "Mode: --clean (recreate venv and reinstall)"
echo ""

# Check system requirements
echo "Step 1: Verifying system requirements..."
echo ""

# Check if bc is installed (needed for version comparison)
if ! command -v bc &> /dev/null; then
    echo "ERROR: 'bc' command not found. Install with: sudo apt install bc"
    exit 1
fi

# Check glibc version (must be 2.28+)
GLIBC_VERSION=$(ldd --version | head -n1 | grep -oP '\d+\.\d+' | head -n1)
echo "✓ glibc version: $GLIBC_VERSION"
if (( $(echo "$GLIBC_VERSION < 2.28" | bc -l) )); then
    echo "ERROR: glibc $GLIBC_VERSION is too old. Need 2.28+"
    echo "Federated XGBoost requires manylinux_2_28"
    exit 1
fi

# Check Python
PYTHON_VERSION=$(python3 --version)
echo "✓ Python version: $PYTHON_VERSION"

# Check GPU (optional but available)
if command -v nvidia-smi &> /dev/null; then
    echo "✓ GPU detected:"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
    GPU_AVAILABLE=1
else
    echo "⚠ No GPU detected (CPU-only mode)"
    GPU_AVAILABLE=0
fi

echo ""
echo "Step 2: Verifying repository and fix..."
echo ""

echo "Using NVFlare repository at: $REPO_DIR"

# Verify we found the right place by checking for nvflare directory
NVFLARE_DIR="$REPO_DIR/nvflare"
if [ ! -d "$NVFLARE_DIR" ]; then
    echo "ERROR: Could not find NVFlare repository structure!"
    echo "Expected nvflare directory at: $NVFLARE_DIR"
    echo ""
    echo "Debug info:"
    echo "  Script path: $SCRIPT_PATH"
    echo "  Script dir: $SCRIPT_DIR"
    echo "  Calculated repo: $REPO_DIR"
    echo "  Looking for: $NVFLARE_DIR"
    echo ""
    ls -la "$REPO_DIR" || echo "Cannot list $REPO_DIR"
    exit 1
fi

echo "✓ Found nvflare directory at: $NVFLARE_DIR"

# Change to repo directory
cd "$REPO_DIR" || {
    echo "ERROR: Could not cd to $REPO_DIR"
    exit 1
}
echo "✓ Changed to: $(pwd)"

# Check if we have the fix (most important check)
FIX_FILE="$REPO_DIR/nvflare/app_opt/xgboost/histogram_based_v2/fed_executor.py"
if [ ! -f "$FIX_FILE" ]; then
    echo "ERROR: File not found: $FIX_FILE"
    exit 1
fi

if ! grep -q "_cached_adaptor" "$FIX_FILE"; then
    echo "ERROR: Adaptor caching fix not found in fed_executor.py"
    echo "Checked file: $FIX_FILE"
    echo "The 'rank not set' bug fix is missing!"
    echo ""
    echo "Make sure you're on branch '$BRANCH_NAME' with latest changes:"
    echo "  cd $REPO_DIR"
    echo "  git checkout $BRANCH_NAME"
    echo "  git pull"
    exit 1
fi
echo "✓ Adaptor caching fix verified in: $FIX_FILE"
echo "✓ Using branch: $BRANCH_NAME"

echo ""
VENV_DIR="$REPO_DIR/xgb_test_venv"

if [ -d "$VENV_DIR" ] && [ "$FORCE_CLEAN" -eq 0 ]; then
    echo "Step 3: Using existing virtual environment..."
    echo ""
    source "$VENV_DIR/bin/activate"
    echo "✓ Reusing venv: $VENV_DIR"
    echo "  (Use --clean to remove and reinstall from scratch)"
else
    if [ -d "$VENV_DIR" ]; then
        echo "Step 3: Removing existing venv (--clean)..."
        rm -rf "$VENV_DIR"
    else
        echo "Step 3: Creating Python virtual environment..."
    fi
    echo ""

    python3 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"

    echo "✓ Virtual environment created: $VENV_DIR"

    echo ""
    echo "Step 4: Installing dependencies..."
    echo ""

    pip install --upgrade pip

    echo "Installing NVFlare from local source..."
    cd "$REPO_DIR" || {
        echo "ERROR: Could not cd to $REPO_DIR"
        exit 1
    }
    pip install -e .

    XGBOOST_DIR="$REPO_DIR/examples/advanced/xgboost"
    echo "Installing XGBoost example dependencies from: $XGBOOST_DIR"
    cd "$XGBOOST_DIR" || {
        echo "ERROR: Could not cd to $XGBOOST_DIR"
        exit 1
    }
    grep -v "^nvflare" requirements.txt | pip install -r /dev/stdin
fi

echo ""
echo "Step 5: Verifying XGBoost installation..."
echo ""

# Check xgboost version
XGBOOST_VERSION=$(python3 -c "import xgboost; print(xgboost.__version__)")
echo "✓ XGBoost version: $XGBOOST_VERSION"

# Test if federated support is actually available
echo "Testing for federated learning support..."
if python3 -c "import xgboost.federated" 2>/dev/null; then
    echo "✓ Federated XGBoost module found"
else
    echo "ERROR: XGBoost federated module not found!"
    echo "XGBoost version $XGBOOST_VERSION does not have federated learning support."
    echo ""
    echo "This usually means standard pip xgboost was installed instead of the federated build."
    exit 1
fi

echo "✓ Federated XGBoost confirmed and working"

echo ""

# Where to look for HIGGS dataset
DATASET_DIR="$REPO_DIR/xgboost_test_data"
HIGGS_CSV="$DATASET_DIR/HIGGS.csv"

if [ ! -f "$HIGGS_CSV" ]; then
    echo "=========================================="
    echo "HIGGS Dataset Not Found"
    echo "=========================================="
    echo ""
    echo "Please place HIGGS.csv at:"
    echo "  $HIGGS_CSV"
    echo ""
    echo "Steps:"
    echo "  1. Download HIGGS.csv.gz from UCI ML Repository"
    echo "  2. Uncompress: gunzip HIGGS.csv.gz"
    echo "  3. Place at: $HIGGS_CSV"
    echo ""
    echo "Or if you already have it elsewhere, create a symlink:"
    echo "  mkdir -p $DATASET_DIR"
    echo "  ln -s /path/to/your/HIGGS.csv $HIGGS_CSV"
    echo ""
    exit 1
fi

echo "✓ HIGGS dataset found at: $HIGGS_CSV"

# If HIGGS.csv is actually gzip-compressed (e.g. renamed .gz file), decompress it
# so pandas in prepare_data_vertical.py can read it (avoids UnicodeDecodeError).
if [ -f "$HIGGS_CSV" ] && [ "$(xxd -l 2 -p "$HIGGS_CSV" 2>/dev/null)" = "1f8b" ]; then
    echo "Detected gzip-compressed HIGGS.csv; decompressing..."
    mv "$HIGGS_CSV" "${HIGGS_CSV}.gz"
    gunzip "${HIGGS_CSV}.gz"
    echo "✓ Decompressed to: $HIGGS_CSV"
fi

echo ""
echo "Step 7: Preparing test data splits..."
echo ""

FEDXGB_DIR="$REPO_DIR/examples/advanced/xgboost/fedxgb"
cd "$FEDXGB_DIR" || {
    echo "ERROR: Could not cd to $FEDXGB_DIR"
    exit 1
}

# Use persistent data directory
DATA_SPLITS_DIR="$DATASET_DIR/splits"
mkdir -p "$DATA_SPLITS_DIR"

echo "Generating horizontal data splits..."
OUTPUT_PATH="$DATA_SPLITS_DIR/horizontal"
for site_num in 2 5 20; do
    for split_mode in uniform exponential square; do
        python3 utils/prepare_data_horizontal.py \
            --data_path "$HIGGS_CSV" \
            --site_num $site_num \
            --size_total 11000000 \
            --size_valid 1000000 \
            --split_method $split_mode \
            --out_path "${OUTPUT_PATH}/${site_num}_${split_mode}"
    done
done
echo "✓ Horizontal data splits generated in: $OUTPUT_PATH"

echo "Generating vertical data splits..."
OUTPUT_PATH="$DATA_SPLITS_DIR/vertical"
python3 utils/prepare_data_vertical.py \
    --data_path "$HIGGS_CSV" \
    --site_num 2 \
    --rows_total_percentage 0.02 \
    --rows_overlap_percentage 0.25 \
    --out_path "$OUTPUT_PATH" \
    --out_file "higgs.data.csv"
echo "✓ Vertical data splits generated in: $OUTPUT_PATH"

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Environment details:"
echo "  - Repository: $REPO_DIR"
echo "  - Virtual environment: $VENV_DIR"
echo "  - XGBoost version: $XGBOOST_VERSION"
echo "  - GPU available: $([ $GPU_AVAILABLE -eq 1 ] && echo 'Yes (RTX A4000)' || echo 'No (CPU only)')"
echo "  - Dataset: $HIGGS_CSV"
echo "  - Data splits: $DATA_SPLITS_DIR"
echo "  - Test directory: $FEDXGB_DIR"
echo ""
echo "To activate environment:"
echo "  source $VENV_DIR/bin/activate"
echo ""
echo "To run tests (from $FEDXGB_DIR):"
echo ""
echo "  cd $FEDXGB_DIR"
echo ""
echo "  # CPU test (2-3 minutes):"
echo "  python3 job.py --site_num 2 --round_num 2 --split_method uniform --data_root $DATA_SPLITS_DIR/horizontal"
echo ""
if [ $GPU_AVAILABLE -eq 1 ]; then
echo "  # GPU test (faster, ~1 minute):"
echo "  python3 job.py --site_num 2 --round_num 2 --split_method uniform --data_root $DATA_SPLITS_DIR/horizontal --use_gpus"
echo ""
fi
echo "Expected success indicators:"
echo "  ✓ 'got my rank: 0'"
echo "  ✓ 'successfully configured client site-1'"
echo "  ✓ 'got my rank: 1'"
echo "  ✓ 'successfully configured client site-2'"
echo "  ✓ NO 'rank not set' error"
echo "  ✓ Training completes with rounds updating"
echo ""
echo "If you see 'XGBoost is not compiled with federated learning support':"
echo "  - Wrong XGBoost version installed"
echo "  - Run this script again"
echo ""
