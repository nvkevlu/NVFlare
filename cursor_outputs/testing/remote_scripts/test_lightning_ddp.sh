#!/bin/bash
# test_lightning_ddp.sh - Test PyTorch Lightning DDP Multi-GPU
#
# This tests the Lightning DDP example which uses:
# - PyTorch Lightning with DDP strategy
# - 2 GPUs per site
# - NVFlare Lightning integration
# - External process launch
#
# Critical Test: Will reveal if external process DXO bug affects Lightning
# (TensorFlow Multi-GPU failed with DXO bug, PyTorch DDP passed)
#
# Hardware Requirements: 2+ CUDA GPUs
# Estimated Time: 20-30 minutes
#
# Usage: ./test_lightning_ddp.sh

set -e  # Exit on error

# Configuration
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
NVFLARE_ROOT="${NVFLARE_ROOT:-$HOME/nvflare_testing/NVFlare}"
VENV_PATH="${VENV_PATH:-$HOME/nvflare_testing/nvflare_env}"
LOGS_DIR="${LOGS_DIR:-$HOME/nvflare_testing/logs}"
RESULTS_DIR="${RESULTS_DIR:-$HOME/nvflare_testing/results}"
TEST_NAME="lightning-ddp"
LOG_FILE="$LOGS_DIR/${TEST_NAME}_${TIMESTAMP}.log"
RESULT_DIR="$RESULTS_DIR/${TEST_NAME}_${TIMESTAMP}"

# Set TMPDIR to avoid /tmp space issues
export TMPDIR="$HOME/nvflare_testing/tmp"
mkdir -p "$TMPDIR"

EXAMPLE_DIR="$NVFLARE_ROOT/examples/advanced/multi-gpu/lightning"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
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

show_gpu_status() {
    if command -v nvidia-smi &> /dev/null; then
        echo "" | tee -a "$LOG_FILE"
        log_info "GPU Status:"
        nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv | tee -a "$LOG_FILE"
        echo "" | tee -a "$LOG_FILE"
    fi
}

# Header
echo "=========================================="
echo "PyTorch Lightning DDP Multi-GPU Test"
echo "=========================================="
echo ""
echo "Example: $EXAMPLE_DIR"
echo "Log: $LOG_FILE"
echo "Timestamp: $TIMESTAMP"
echo ""

# Create directories
mkdir -p "$LOGS_DIR"
mkdir -p "$RESULTS_DIR"
mkdir -p "$RESULT_DIR"

# Check example exists
if [ ! -d "$EXAMPLE_DIR" ]; then
    log_error "Example directory not found: $EXAMPLE_DIR"
    exit 1
fi

# Activate venv
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    log_error "Virtual environment not found: $VENV_PATH"
    exit 1
fi

log_info "Activating virtual environment..."
source "$VENV_PATH/bin/activate"

# Verify installations
log_info "Verifying environment..."
NVFLARE_VERSION=$(python -c "import nvflare; print(nvflare.__version__)" 2>/dev/null || echo "NOT_FOUND")
if [ "$NVFLARE_VERSION" = "NOT_FOUND" ]; then
    log_error "NVFlare not installed"
    exit 1
fi
log_success "NVFlare: $NVFLARE_VERSION"

# Check PyTorch Lightning
LIGHTNING_VERSION=$(python -c "import pytorch_lightning; print(pytorch_lightning.__version__)" 2>/dev/null || echo "NOT_FOUND")
if [ "$LIGHTNING_VERSION" = "NOT_FOUND" ]; then
    log_error "PyTorch Lightning not installed"
    log_info "Installing pytorch-lightning..."
    pip install --no-cache-dir pytorch-lightning >> "$LOG_FILE" 2>&1
    LIGHTNING_VERSION=$(python -c "import pytorch_lightning; print(pytorch_lightning.__version__)" 2>/dev/null || echo "FAILED")
    if [ "$LIGHTNING_VERSION" = "FAILED" ]; then
        log_error "Failed to install PyTorch Lightning"
        exit 1
    fi
fi
log_success "PyTorch Lightning: $LIGHTNING_VERSION"

# Check CUDA
CUDA_AVAILABLE=$(python -c "import torch; print(torch.cuda.is_available())" 2>/dev/null || echo "False")
if [ "$CUDA_AVAILABLE" != "True" ]; then
    log_error "CUDA not available"
    exit 1
fi
GPU_COUNT=$(python -c "import torch; print(torch.cuda.device_count())" 2>/dev/null || echo "0")
log_success "CUDA available with $GPU_COUNT GPU(s)"

if [ "$GPU_COUNT" -lt 2 ]; then
    log_error "Need at least 2 GPUs, found: $GPU_COUNT"
    exit 1
fi

# Show initial GPU status
show_gpu_status

# Clean up old /tmp simulation directories to free space
log_info "Cleaning up old /tmp simulation directories..."
rm -rf /tmp/nvflare/simulation/* 2>/dev/null || true
log_success "Cleanup complete"

# Change to example directory
cd "$EXAMPLE_DIR"
log_info "Working directory: $(pwd)"

# Install dependencies
if [ -f "requirements.txt" ]; then
    log_info "Installing example dependencies (using --no-cache-dir)..."
    pip install --no-cache-dir -r requirements.txt >> "$LOG_FILE" 2>&1
    log_success "Dependencies installed"
fi

# Check for dataset or prepare it
if [ ! -d "$DATASET_PATH/cifar-10-batches-py" ]; then
    log_info "Preparing CIFAR-10 dataset..."
    if [ -f "prepare_data.sh" ]; then
        bash prepare_data.sh >> "$LOG_FILE" 2>&1
        log_success "Dataset prepared"
    else
        log_info "No prepare_data.sh, dataset will be downloaded during training"
    fi
else
    log_success "CIFAR-10 dataset already available"
fi

echo ""
log_info "=========================================="
log_info "Starting Lightning DDP Test"
log_info "=========================================="
log_info "Expected duration: 20-30 minutes"
log_info "Monitor: tail -f $LOG_FILE"
log_info "GPU usage: watch -n 1 nvidia-smi"
echo ""

show_gpu_status

START_TIME=$(date +%s)
log_info "Running: python job.py --work_dir $RESULT_DIR/workspace"

# Run the test with custom workspace to avoid /tmp space issues
python job.py --work_dir "$RESULT_DIR/workspace" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
log_info "=========================================="

if [ $EXIT_CODE -eq 0 ]; then
    log_success "✅ Lightning DDP test PASSED!"
else
    log_error "❌ Lightning DDP test FAILED with exit code: $EXIT_CODE"
fi

log_info "=========================================="
log_info "Duration: ${DURATION}s ($((DURATION/60)) minutes)"
echo ""

show_gpu_status

# Analyze results
log_info "Analyzing test results..."
echo ""

# Check for DXO errors (critical!)
if grep -q "not a valid DXO" "$LOG_FILE"; then
    log_error "❌ DXO ERROR DETECTED - External process communication bug!"
    echo ""
    log_info "DXO error context:"
    grep -B 5 -A 5 "not a valid DXO" "$LOG_FILE" | head -20
    echo ""
fi

# Check for successful completion
if grep -q "Finished FedAvg" "$LOG_FILE"; then
    log_success "✅ FedAvg training completed"
else
    log_error "⚠️  FedAvg completion marker not found"
fi

# Check rounds
ROUNDS=$(grep -c "Round [0-9]* started" "$LOG_FILE" || echo "0")
log_info "Training rounds detected: $ROUNDS"

# Check for accuracy progression
log_info "Checking training progress..."
grep -E "Accuracy|Round [0-9]* started" "$LOG_FILE" | tail -15

# Check for errors
ERROR_COUNT=$(grep -i "error\|exception" "$LOG_FILE" | grep -v "ERROR - Processing frame\|Connection attempt failed" | wc -l || echo "0")
if [ "$ERROR_COUNT" -gt 0 ]; then
    log_error "Found $ERROR_COUNT error messages"
    echo ""
    log_info "Recent errors:"
    grep -i "error\|exception" "$LOG_FILE" | grep -v "ERROR - Processing frame\|Connection attempt failed" | tail -10
fi

# Save results
log_info "Saving results..."
cp "$LOG_FILE" "$RESULT_DIR/"
echo "Test: Multi-GPU Lightning DDP" > "$RESULT_DIR/summary.txt"
echo "Timestamp: $(date)" >> "$RESULT_DIR/summary.txt"
echo "Exit code: $EXIT_CODE" >> "$RESULT_DIR/summary.txt"
echo "Duration: ${DURATION}s ($((DURATION/60)) minutes)" >> "$RESULT_DIR/summary.txt"
echo "Rounds: $ROUNDS" >> "$RESULT_DIR/summary.txt"
echo "Errors: $ERROR_COUNT" >> "$RESULT_DIR/summary.txt"

# Copy simulation results from custom workspace
if [ -d "$RESULT_DIR/workspace" ]; then
    log_info "Simulation results already in: $RESULT_DIR/workspace"
else
    log_info "No simulation workspace found"
fi

echo ""
log_info "=========================================="
log_info "Test Summary"
log_info "=========================================="
log_info "Exit Code: $EXIT_CODE"
log_info "Duration: $((DURATION/60)) minutes"
log_info "Rounds: $ROUNDS"
log_info "DXO Errors: $(grep -c 'not a valid DXO' "$LOG_FILE" 2>/dev/null || echo 0)"
log_info "Log: $LOG_FILE"
log_info "Results: $RESULT_DIR"
echo ""

if [ $EXIT_CODE -eq 0 ]; then
    log_success "🎉 Test completed successfully!"
    
    # Check if DXO errors present even with exit 0
    if grep -q "not a valid DXO" "$LOG_FILE"; then
        log_error "⚠️  WARNING: Test passed but DXO errors detected"
        log_error "This indicates external process communication issues"
    fi
else
    log_error "⚠️  Test failed. Check logs for details."
fi

exit $EXIT_CODE
