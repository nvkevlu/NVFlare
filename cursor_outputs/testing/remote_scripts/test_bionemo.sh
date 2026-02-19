#!/bin/bash
# test_bionemo.sh - Run BioNeMo federated learning test inside Docker
# Purpose: Test BioNeMo ESM2 downstream task with NVFlare (no Jupyter needed)
# Usage: ./test_bionemo.sh

set -e

# ============================================
# Configuration
# ============================================
WORK_DIR="$HOME/nvflare_testing"
REPO_DIR="$WORK_DIR/NVFlare"
BIONEMO_DIR="$REPO_DIR/examples/advanced/bionemo"
DOCKER_IMAGE="nvcr.io/nvidia/clara/bionemo-framework:2.5"
LOG_DIR="$WORK_DIR/logs"
RESULTS_DIR="$WORK_DIR/results"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/bionemo_${TIMESTAMP}.log"

# BioNeMo test configuration
TASK="sabdab"  # Antibody binding classification (fastest to test)
MODEL="8m"     # Smallest ESM2 model (fastest)
NUM_CLIENTS=2
NUM_ROUNDS=3
LOCAL_STEPS=10

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ============================================
# Helper Functions
# ============================================
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

# ============================================
# Main Test
# ============================================
echo "=========================================="
echo "BioNeMo Federated Learning Test"
echo "=========================================="
echo ""

mkdir -p "$LOG_DIR"
mkdir -p "$RESULTS_DIR"

log_info "Test started: $(date)"
log_info "Configuration:"
log_info "  - Task: $TASK (SAbDab antibody binding)"
log_info "  - Model: ESM2-$MODEL"
log_info "  - Clients: $NUM_CLIENTS"
log_info "  - Rounds: $NUM_ROUNDS"
log_info "  - Local steps: $LOCAL_STEPS"
log_info "  - Docker image: $DOCKER_IMAGE"
echo ""

# ============================================
# Step 1: Verify Prerequisites
# ============================================
log_info "Step 1/5: Verifying prerequisites..."

# Check if repo exists
if [ ! -d "$REPO_DIR" ]; then
    log_error "NVFlare repository not found: $REPO_DIR"
    log_error "Run remote_setup.sh first!"
    exit 1
fi

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    log_error "Docker not found!"
    exit 1
fi

# Check if Docker image exists
if ! docker images | grep -q "bionemo-framework.*2.5"; then
    log_warning "BioNeMo image not found locally, will pull (~10GB download)"
    log_info "Pulling $DOCKER_IMAGE..."
    docker pull "$DOCKER_IMAGE" >> "$LOG_FILE" 2>&1
fi

# Check GPU availability
log_info "GPU Status:"
nvidia-smi --query-gpu=index,name,memory.total --format=csv | tee -a "$LOG_FILE"
echo ""

# ============================================
# Step 2: Prepare BioNeMo Example
# ============================================
log_info "Step 2/5: Preparing BioNeMo example..."

cd "$BIONEMO_DIR"

# Check if downstream task exists
TASK_DIR="$BIONEMO_DIR/downstream/$TASK"
if [ ! -d "$TASK_DIR" ]; then
    log_error "Task directory not found: $TASK_DIR"
    exit 1
fi

if [ ! -f "$TASK_DIR/job.py" ]; then
    log_error "job.py not found in $TASK_DIR"
    exit 1
fi

log_info "Task directory: $TASK_DIR"
log_info "Job script: $TASK_DIR/job.py"
echo ""

# ============================================
# Step 3: Prepare Dataset (if needed)
# ============================================
log_info "Step 3/6: Checking for SAbDab dataset..."

DATA_DIR="/tmp/data/sabdab_chen"
if [ -d "$DATA_DIR" ] && [ -f "$DATA_DIR/train/sabdab_chen_site-1_train.csv" ]; then
    log_info "Dataset already exists, skipping preparation"
else
    log_info "Preparing SAbDab dataset (first run only)..."
    log_info "This will download ~10-20MB and take 2-5 minutes"
    
    # Run data prep script inside Docker
    docker run \
        --rm \
        -v "$BIONEMO_DIR:/workspace/bionemo" \
        -v "/tmp/data:/tmp/data" \
        "$DOCKER_IMAGE" \
        bash -c "
            echo 'Installing PyTDC for dataset download...' && \
            pip install -q PyTDC && \
            echo 'Downloading and preparing SAbDab dataset...' && \
            python3 /workspace/bionemo/downstream/sabdab/prepare_sabdab_data.py
        " 2>&1 | tee -a "$LOG_FILE"
    
    DATA_PREP_EXIT=$?
    if [ $DATA_PREP_EXIT -ne 0 ]; then
        log_error "Data preparation failed!"
        exit 1
    fi
    
    log_info "Dataset prepared successfully"
    log_info "Data location: $DATA_DIR"
    ls -lh "$DATA_DIR/train/" | tee -a "$LOG_FILE"
fi
echo ""

# ============================================
# Step 4: Run BioNeMo Job Inside Docker
# ============================================
log_info "Step 4/6: Running BioNeMo federated training..."
log_info "This will take approximately 10-30 minutes depending on GPU"
log_info "Progress logged to: $LOG_FILE"
echo ""

# Run Docker container with job.py (non-interactive)
log_info "Starting Docker container..."
START_TIME=$(date +%s)

# Install NVFlare in container and run job
docker run \
    --gpus all \
    --network=host \
    --ipc=host \
    --rm \
    --shm-size=1g \
    --ulimit memlock=-1 \
    --ulimit stack=67108864 \
    -v "$BIONEMO_DIR:/workspace/bionemo" \
    -v "$REPO_DIR:/workspace/nvflare_src" \
    -v "/tmp/data:/tmp/data" \
    -w "/workspace/bionemo/downstream/$TASK" \
    "$DOCKER_IMAGE" \
    bash -c "
        echo 'Installing NVFlare in container...' && \
        pip install -q -e /workspace/nvflare_src && \
        echo 'Running BioNeMo job...' && \
        python3 job.py \
            --num_clients $NUM_CLIENTS \
            --num_rounds $NUM_ROUNDS \
            --local_steps $LOCAL_STEPS \
            --model $MODEL \
            --exp_name fedavg \
            --sim_gpus 0
    " 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}
END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
log_info "Docker container finished (exit code: $EXIT_CODE)"
log_info "Duration: ${DURATION}s ($(($DURATION / 60)) minutes)"
echo ""

# ============================================
# Step 5: Check Results
# ============================================
log_info "Step 5/6: Checking results..."

# Look for NVFlare simulation results
NVFLARE_RESULT_DIR="/tmp/nvflare/bionemo/$TASK"
if docker run --rm -v "$NVFLARE_RESULT_DIR:$NVFLARE_RESULT_DIR" "$DOCKER_IMAGE" test -d "$NVFLARE_RESULT_DIR"; then
    log_info "NVFlare simulation results found in $NVFLARE_RESULT_DIR"
else
    log_warning "Simulation results directory not found (may have been cleaned up)"
fi

# Check for success indicators in log
if grep -q "Job Status is:" "$LOG_FILE"; then
    JOB_STATUS=$(grep "Job Status is:" "$LOG_FILE" | tail -1)
    log_info "$JOB_STATUS"
fi

if grep -q "Result can be found in" "$LOG_FILE"; then
    RESULT_PATH=$(grep "Result can be found in" "$LOG_FILE" | tail -1)
    log_info "$RESULT_PATH"
fi

# Check for errors
if [ $EXIT_CODE -ne 0 ]; then
    log_error "Test FAILED with exit code $EXIT_CODE"
    log_error "Check log for details: $LOG_FILE"
    
    # Show last 50 lines of log for diagnosis
    echo ""
    log_error "Last 50 lines of log:"
    tail -50 "$LOG_FILE"
    
    exit 1
fi

# Check for common success patterns
if grep -q "successfully" "$LOG_FILE" || grep -q "completed" "$LOG_FILE"; then
    log_info "Test appears successful"
else
    log_warning "Could not confirm test success, check logs manually"
fi

echo ""

# ============================================
# Step 6: Summary
# ============================================
log_info "Step 6/6: Test Summary"
echo ""
echo "=========================================="
echo "📊 BioNeMo Test Results"
echo "=========================================="
echo ""
echo "✅ Test completed in ${DURATION}s ($(($DURATION / 60)) minutes)"
echo ""
echo "Configuration:"
echo "  - Task: $TASK (antibody binding classification)"
echo "  - Model: ESM2-$MODEL"
echo "  - Clients: $NUM_CLIENTS"
echo "  - Rounds: $NUM_ROUNDS"
echo "  - Steps per round: $LOCAL_STEPS"
echo ""
echo "Logs:"
echo "  - Test log: $LOG_FILE"
echo "  - NVFlare results: /tmp/nvflare/bionemo/$TASK/"
echo ""
echo "GPU Utilization:"
nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv
echo ""
echo "=========================================="

if [ $EXIT_CODE -eq 0 ]; then
    echo "🎉 BioNeMo test PASSED!"
    echo "=========================================="
    exit 0
else
    echo "❌ BioNeMo test FAILED"
    echo "=========================================="
    exit 1
fi
