#!/bin/bash
# run_multi_gpu_tests.sh - Run Multi-GPU tests for NVFlare
# Usage: ./run_multi_gpu_tests.sh

set -e

echo "=========================================="
echo "NVFlare Multi-GPU Testing"
echo "=========================================="
echo ""

# Configuration
WORK_DIR="$HOME/nvflare_testing"
VENV_DIR="$WORK_DIR/nvflare_env"
REPO_DIR="$WORK_DIR/NVFlare"
LOG_DIR="$WORK_DIR/logs"
RESULTS_DIR="$WORK_DIR/results"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Check if environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${RED}❌ Virtual environment not found!${NC}"
    echo "Please run ./remote_setup.sh first"
    exit 1
fi

# Activate virtual environment
echo "✨ Activating virtual environment..."
source "$VENV_DIR/bin/activate"
cd "$REPO_DIR"

# Set TMPDIR to avoid /tmp space issues
export TMPDIR="$WORK_DIR/tmp"
mkdir -p "$TMPDIR"
echo "📁 Using temp directory: $TMPDIR (avoids /tmp space issues)"

# Create timestamp for this test run
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RUN_LOG="$LOG_DIR/test_run_${TIMESTAMP}.log"

echo "📝 Logging to: $RUN_LOG"
echo ""

# Start logging
exec > >(tee -a "$RUN_LOG") 2>&1

echo "=========================================="
echo "Test Run Started: $(date)"
echo "=========================================="
echo ""

# Display GPU info
echo "=== GPU Information ==="
nvidia-smi
echo ""

# Display environment info
echo "=== Environment Information ==="
python -c "
import sys
import torch
import tensorflow as tf
import nvflare

print(f'Python: {sys.version}')
print(f'NVFlare: {nvflare.__version__}')
print(f'PyTorch: {torch.__version__}')
print(f'  CUDA available: {torch.cuda.is_available()}')
print(f'  GPU count: {torch.cuda.device_count()}')
if torch.cuda.is_available():
    for i in range(torch.cuda.device_count()):
        print(f'  GPU {i}: {torch.cuda.get_device_name(i)}')
print(f'TensorFlow: {tf.__version__}')
gpus = tf.config.list_physical_devices('GPU')
print(f'  GPU count: {len(gpus)}')
for gpu in gpus:
    print(f'  {gpu}')
"
echo ""

# Test counter
TOTAL_TESTS=2
PASSED_TESTS=0
FAILED_TESTS=0

# Array to track results
declare -a TEST_RESULTS

###########################################
# Test 1: PyTorch DDP Multi-GPU
###########################################

echo ""
echo "=========================================="
echo "Test 1/2: PyTorch DDP Multi-GPU"
echo "=========================================="
echo ""

TEST_NAME="multi-gpu-pytorch-ddp"
TEST_DIR="examples/advanced/multi-gpu/pt"
TEST_LOG="$LOG_DIR/${TEST_NAME}_${TIMESTAMP}.log"

cd "$REPO_DIR/$TEST_DIR"

echo "📁 Working directory: $(pwd)"
echo "📝 Test log: $TEST_LOG"
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
pip install --no-cache-dir -r requirements.txt > "$TEST_LOG" 2>&1

# Prepare data
echo "📥 Preparing CIFAR-10 dataset..."
if [ -f "prepare_data.sh" ]; then
    bash prepare_data.sh >> "$TEST_LOG" 2>&1
    echo "✅ Dataset prepared"
else
    echo "⚠️  prepare_data.sh not found, will download during training"
fi

echo ""
echo "🚀 Running PyTorch DDP test (this may take 20-30 minutes)..."
echo "   Progress can be monitored at: $TEST_LOG"
echo ""

# Run the test
START_TIME=$(date +%s)

if python job.py >> "$TEST_LOG" 2>&1; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo -e "${GREEN}✅ PyTorch DDP test PASSED${NC} (${DURATION}s)"
    TEST_RESULTS+=("✅ PyTorch DDP: PASSED (${DURATION}s)")
    PASSED_TESTS=$((PASSED_TESTS + 1))
    
    # Save results
    RESULT_DIR="$RESULTS_DIR/${TEST_NAME}_${TIMESTAMP}"
    mkdir -p "$RESULT_DIR"
    if [ -d "/tmp/nvflare/jobs/workdir" ]; then
        cp -r /tmp/nvflare/jobs/workdir/* "$RESULT_DIR/" 2>/dev/null || true
        echo "   Results saved to: $RESULT_DIR"
    fi
else
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo -e "${RED}❌ PyTorch DDP test FAILED${NC} (${DURATION}s)"
    echo "   Check log: $TEST_LOG"
    TEST_RESULTS+=("❌ PyTorch DDP: FAILED (${DURATION}s)")
    FAILED_TESTS=$((FAILED_TESTS + 1))
    
    # Show last 50 lines of log
    echo ""
    echo "Last 50 lines of error log:"
    tail -n 50 "$TEST_LOG"
fi

# Check GPU utilization
echo ""
echo "GPU status after test:"
nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv

###########################################
# Test 2: TensorFlow MirroredStrategy
###########################################

echo ""
echo "=========================================="
echo "Test 2/2: TensorFlow MirroredStrategy"
echo "=========================================="
echo ""

TEST_NAME="multi-gpu-tensorflow"
TEST_DIR="examples/advanced/multi-gpu/tf"
TEST_LOG="$LOG_DIR/${TEST_NAME}_${TIMESTAMP}.log"

cd "$REPO_DIR/$TEST_DIR"

echo "📁 Working directory: $(pwd)"
echo "📝 Test log: $TEST_LOG"
echo ""

# Install dependencies
echo "📦 Installing dependencies..."
pip install --no-cache-dir -r requirements.txt > "$TEST_LOG" 2>&1

# Prepare data
echo "📥 Preparing CIFAR-10 dataset..."
if [ -f "prepare_data.sh" ]; then
    bash prepare_data.sh >> "$TEST_LOG" 2>&1
    echo "✅ Dataset prepared"
else
    echo "⚠️  prepare_data.sh not found, will download during training"
fi

echo ""
echo "🚀 Running TensorFlow MirroredStrategy test (this may take 20-30 minutes)..."
echo "   Progress can be monitored at: $TEST_LOG"
echo ""

# Run the test
START_TIME=$(date +%s)

if python job.py >> "$TEST_LOG" 2>&1; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo -e "${GREEN}✅ TensorFlow MirroredStrategy test PASSED${NC} (${DURATION}s)"
    TEST_RESULTS+=("✅ TensorFlow: PASSED (${DURATION}s)")
    PASSED_TESTS=$((PASSED_TESTS + 1))
    
    # Save results
    RESULT_DIR="$RESULTS_DIR/${TEST_NAME}_${TIMESTAMP}"
    mkdir -p "$RESULT_DIR"
    if [ -d "/tmp/nvflare/jobs/workdir" ]; then
        cp -r /tmp/nvflare/jobs/workdir/* "$RESULT_DIR/" 2>/dev/null || true
        echo "   Results saved to: $RESULT_DIR"
    fi
else
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo -e "${RED}❌ TensorFlow MirroredStrategy test FAILED${NC} (${DURATION}s)"
    echo "   Check log: $TEST_LOG"
    TEST_RESULTS+=("❌ TensorFlow: FAILED (${DURATION}s)")
    FAILED_TESTS=$((FAILED_TESTS + 1))
    
    # Show last 50 lines of log
    echo ""
    echo "Last 50 lines of error log:"
    tail -n 50 "$TEST_LOG"
fi

# Check GPU utilization
echo ""
echo "GPU status after test:"
nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv

###########################################
# Final Summary
###########################################

echo ""
echo "=========================================="
echo "Test Run Complete: $(date)"
echo "=========================================="
echo ""

echo "📊 Test Summary:"
echo "   Total: $TOTAL_TESTS"
echo "   Passed: $PASSED_TESTS"
echo "   Failed: $FAILED_TESTS"
echo ""

echo "📝 Detailed Results:"
for result in "${TEST_RESULTS[@]}"; do
    echo "   $result"
done

echo ""
echo "📂 Test Artifacts:"
echo "   Main log: $RUN_LOG"
echo "   Individual logs: $LOG_DIR/*_${TIMESTAMP}.log"
echo "   Results: $RESULTS_DIR/*_${TIMESTAMP}/"
echo ""

# Create summary file
SUMMARY_FILE="$RESULTS_DIR/test_summary_${TIMESTAMP}.txt"
cat > "$SUMMARY_FILE" << EOF
========================================
NVFlare Multi-GPU Test Summary
========================================

Test Date: $(date)
Hostname: $(hostname)

Environment:
$(cat $WORK_DIR/environment_info.txt)

Test Results:
Total: $TOTAL_TESTS
Passed: $PASSED_TESTS
Failed: $FAILED_TESTS

Detailed Results:
$(printf '%s\n' "${TEST_RESULTS[@]}")

Logs:
Main log: $RUN_LOG
Individual logs: $LOG_DIR/*_${TIMESTAMP}.log
Results: $RESULTS_DIR/*_${TIMESTAMP}/

GPU Info:
$(nvidia-smi)
EOF

echo "📋 Summary saved to: $SUMMARY_FILE"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}🎉 All tests PASSED!${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠️  Some tests FAILED. Check logs for details.${NC}"
    exit 1
fi
