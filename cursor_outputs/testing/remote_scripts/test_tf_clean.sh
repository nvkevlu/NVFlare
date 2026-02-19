#!/bin/bash
# test_tf_clean.sh - Test TensorFlow Multi-GPU in CLEAN environment
#
# Uses TensorFlow-only venv (no PyTorch conflicts)
#
# Usage: ./test_tf_clean.sh

set -e

# Configuration
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
NVFLARE_ROOT="$HOME/nvflare_testing/NVFlare"
TF_VENV_PATH="$HOME/nvflare_testing/nvflare_tf_env"
LOGS_DIR="$HOME/nvflare_testing/logs"
RESULTS_DIR="$HOME/nvflare_testing/results"
TEST_NAME="tensorflow-clean"
LOG_FILE="$LOGS_DIR/${TEST_NAME}_${TIMESTAMP}.log"
RESULT_DIR="$RESULTS_DIR/${TEST_NAME}_${TIMESTAMP}"

export TMPDIR="$HOME/nvflare_testing/tmp"
mkdir -p "$TMPDIR"

EXAMPLE_DIR="$NVFLARE_ROOT/examples/advanced/multi-gpu/tf"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

echo "=========================================="
echo "TensorFlow Multi-GPU Test (Clean Env)"
echo "=========================================="
echo ""

mkdir -p "$LOGS_DIR" "$RESULTS_DIR" "$RESULT_DIR"

# Check TF venv exists
if [ ! -f "$TF_VENV_PATH/bin/activate" ]; then
    log_error "TensorFlow venv not found: $TF_VENV_PATH"
    log_info "Run setup_tf_venv.sh first!"
    exit 1
fi

log_info "Activating TensorFlow-only virtual environment..."
source "$TF_VENV_PATH/bin/activate"

# Verify environment
log_info "Verifying clean environment..."
NVFLARE_VERSION=$(python -c "import nvflare; print(nvflare.__version__)" 2>/dev/null || echo "NOT_FOUND")
TF_VERSION=$(python -c "import tensorflow; print(tensorflow.__version__)" 2>/dev/null || echo "NOT_FOUND")
HAS_TORCH=$(python -c "import torch; print('YES')" 2>/dev/null || echo "NO")

if [ "$NVFLARE_VERSION" = "NOT_FOUND" ]; then
    log_error "NVFlare not installed"
    exit 1
fi
log_success "NVFlare: $NVFLARE_VERSION"

if [ "$TF_VERSION" = "NOT_FOUND" ]; then
    log_error "TensorFlow not installed"
    exit 1
fi
log_success "TensorFlow: $TF_VERSION"

if [ "$HAS_TORCH" = "YES" ]; then
    log_error "⚠️  PyTorch is installed! This venv is contaminated!"
    log_error "Run setup_tf_venv.sh to recreate clean environment"
    exit 1
fi
log_success "PyTorch NOT installed (clean environment ✓)"

# Check CUDA
GPU_COUNT=$(python -c "import tensorflow as tf; print(len(tf.config.list_physical_devices('GPU')))" 2>/dev/null || echo "0")
log_success "GPU count: $GPU_COUNT"

if [ "$GPU_COUNT" -lt 2 ]; then
    log_error "Need at least 2 GPUs, found: $GPU_COUNT"
    exit 1
fi

cd "$EXAMPLE_DIR"
log_info "Working directory: $(pwd)"

# Cleanup
log_info "Cleaning up old simulation directories..."
rm -rf /tmp/nvflare/simulation/* 2>/dev/null || true

# Install dependencies
if [ -f "requirements.txt" ]; then
    log_info "Installing dependencies..."
    pip install --no-cache-dir -r requirements.txt >> "$LOG_FILE" 2>&1
    log_success "Dependencies installed"
fi

log_info "Preparing CIFAR-10 dataset..."
if [ -f "prepare_data.sh" ]; then
    bash prepare_data.sh >> "$LOG_FILE" 2>&1
fi
log_success "Dataset ready"

echo ""
log_info "=========================================="
log_info "Starting TensorFlow Test (Clean Env)"
log_info "=========================================="
echo ""

START_TIME=$(date +%s)
log_info "Running: python job.py --work_dir $RESULT_DIR/workspace"

python job.py --work_dir "$RESULT_DIR/workspace" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
log_info "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    log_success "✅ Test PASSED!"
else
    log_error "❌ Test FAILED (exit code: $EXIT_CODE)"
fi
log_info "Duration: ${DURATION}s ($((DURATION/60)) minutes)"
log_info "=========================================="
echo ""

# Analyze
log_info "Analyzing results..."

if grep -q "not a valid DXO" "$LOG_FILE"; then
    DXO_COUNT=$(grep -c "not a valid DXO" "$LOG_FILE")
    log_error "❌ DXO errors: $DXO_COUNT"
else
    log_success "✅ No DXO errors!"
fi

if grep -q "Finished FedAvg" "$LOG_FILE"; then
    log_success "✅ FedAvg completed"
else
    log_error "⚠️  FedAvg not completed"
fi

ROUNDS=$(grep -c "Round [0-9]* started" "$LOG_FILE" || echo "0")
log_info "Rounds: $ROUNDS"

# Check for models
MODEL_COUNT=$(find "$RESULT_DIR/workspace" -name "*.h5" 2>/dev/null | wc -l)
log_info "Model files saved: $MODEL_COUNT"

# Save results
cp "$LOG_FILE" "$RESULT_DIR/"
echo "Test: TensorFlow Multi-GPU (Clean Env)" > "$RESULT_DIR/summary.txt"
echo "Timestamp: $(date)" >> "$RESULT_DIR/summary.txt"
echo "Exit code: $EXIT_CODE" >> "$RESULT_DIR/summary.txt"
echo "Duration: ${DURATION}s" >> "$RESULT_DIR/summary.txt"
echo "Rounds: $ROUNDS" >> "$RESULT_DIR/summary.txt"
echo "Models: $MODEL_COUNT" >> "$RESULT_DIR/summary.txt"

echo ""
log_info "Log: $LOG_FILE"
log_info "Results: $RESULT_DIR"
echo ""

exit $EXIT_CODE
