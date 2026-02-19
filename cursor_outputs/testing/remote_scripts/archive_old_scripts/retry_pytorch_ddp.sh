#!/bin/bash
# retry_pytorch_ddp.sh - Retry PyTorch DDP test after installing tenseal
# This script reuses existing CIFAR-10 dataset to avoid re-downloading
# Usage: ./retry_pytorch_ddp.sh

set -e

echo "=========================================="
echo "Retry PyTorch DDP Test (with tenseal)"
echo "=========================================="
echo ""

WORK_DIR="$HOME/nvflare_testing"
VENV_DIR="$WORK_DIR/nvflare_env"
REPO_DIR="$WORK_DIR/NVFlare"
LOG_DIR="$WORK_DIR/logs"
RESULTS_DIR="$WORK_DIR/results"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Activate venv
source "$VENV_DIR/bin/activate"

# Set TMPDIR to avoid /tmp issues
export TMPDIR="$WORK_DIR/tmp"
mkdir -p "$TMPDIR"
echo "✅ Using temp directory: $TMPDIR"
echo ""

# Install tenseal if missing
echo "🔍 Checking for tenseal..."
if ! python -c "import tenseal" 2>/dev/null; then
    echo "📦 Installing tenseal (required for HE module imports)..."
    pip install --no-cache-dir tenseal
    echo -e "${GREEN}✅ tenseal installed${NC}"
else
    echo -e "${GREEN}✅ tenseal already installed${NC}"
fi
echo ""

# Verify NVFlare can import properly
echo "🔍 Verifying NVFlare imports..."
if python -c "from nvflare.app_opt.pt.recipes.fedavg import FedAvgRecipe; print('✅ Import successful')" 2>/dev/null; then
    echo -e "${GREEN}✅ NVFlare imports working${NC}"
else
    echo -e "${RED}❌ NVFlare import failed! Check installation.${NC}"
    exit 1
fi
echo ""

###########################################
# Test: PyTorch DDP Multi-GPU (Retry)
###########################################

echo "=========================================="
echo "PyTorch DDP Multi-GPU Test (Retry)"
echo "=========================================="
echo ""

TEST_NAME="multi-gpu-pytorch-ddp"
TEST_DIR="examples/advanced/multi-gpu/pt"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TEST_LOG="$LOG_DIR/${TEST_NAME}_retry_${TIMESTAMP}.log"
RUN_LOG="$LOG_DIR/test_run_retry_${TIMESTAMP}.log"

cd "$REPO_DIR/$TEST_DIR"

echo "📁 Working directory: $(pwd)"
echo "📝 Test log: $TEST_LOG"
echo ""

# Start logging to both console and file
exec > >(tee -a "$RUN_LOG") 2>&1

# Check if dependencies already installed
echo "🔍 Checking dependencies..."
if python -c "import torch; import torchvision" 2>/dev/null; then
    echo -e "${GREEN}✅ PyTorch dependencies already installed${NC}"
else
    echo "📦 Installing dependencies..."
    pip install --no-cache-dir -r requirements.txt > "$TEST_LOG" 2>&1
    echo -e "${GREEN}✅ Dependencies installed${NC}"
fi

# Check if CIFAR-10 dataset exists
echo ""
echo "🔍 Checking for CIFAR-10 dataset..."
CIFAR_PATH="/tmp/nvflare/data/cifar10"
if [ -d "$CIFAR_PATH" ] && [ "$(ls -A $CIFAR_PATH)" ]; then
    echo -e "${GREEN}✅ CIFAR-10 dataset found (reusing existing data)${NC}"
    echo "   Location: $CIFAR_PATH"
else
    echo "📥 Preparing CIFAR-10 dataset..."
    if [ -f "prepare_data.sh" ]; then
        bash prepare_data.sh >> "$TEST_LOG" 2>&1
        echo -e "${GREEN}✅ Dataset prepared${NC}"
    else
        echo "⚠️  prepare_data.sh not found, dataset will download during training"
    fi
fi

echo ""
echo "🚀 Running PyTorch DDP test..."
echo "   This may take 20-30 minutes with 2 GPUs"
echo "   Log: $TEST_LOG"
echo ""
echo "Monitor GPU usage with: watch -n 1 nvidia-smi"
echo ""

# Run the test
START_TIME=$(date +%s)

if python job.py >> "$TEST_LOG" 2>&1; then
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo ""
    echo -e "${GREEN}=========================================="
    echo "✅ PyTorch DDP test PASSED!"
    echo "==========================================${NC}"
    echo ""
    echo "Duration: ${DURATION}s ($(($DURATION / 60)) minutes)"
    
    # Save results
    RESULT_DIR="$RESULTS_DIR/${TEST_NAME}_retry_${TIMESTAMP}"
    mkdir -p "$RESULT_DIR"
    if [ -d "/tmp/nvflare/jobs/workdir" ]; then
        cp -r /tmp/nvflare/jobs/workdir/* "$RESULT_DIR/" 2>/dev/null || true
        echo "Results saved to: $RESULT_DIR"
    fi
    
    # Show GPU status
    echo ""
    echo "Final GPU status:"
    nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv
    
    exit 0
else
    END_TIME=$(date +%s)
    DURATION=$((END_TIME - START_TIME))
    echo ""
    echo -e "${RED}=========================================="
    echo "❌ PyTorch DDP test FAILED"
    echo "==========================================${NC}"
    echo ""
    echo "Duration: ${DURATION}s"
    echo ""
    echo "Last 100 lines of error log:"
    tail -n 100 "$TEST_LOG"
    
    exit 1
fi
