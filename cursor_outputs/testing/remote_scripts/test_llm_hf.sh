#!/bin/bash
# test_llm_hf.sh - Test LLM HuggingFace federated fine-tuning
#
# Tests GPT-Neo-1.3B federated fine-tuning with 3 clients
# Hardware: 2x NVIDIA A30 24GB GPUs
# Duration: ~1-2 hours for full test (or use --num_rounds 1 for quick test)
#
# Usage: ./test_llm_hf.sh [--quick]

set -e

# Parse arguments
QUICK_TEST=false
if [ "$1" = "--quick" ]; then
    QUICK_TEST=true
fi

# Configuration
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
NVFLARE_ROOT="${NVFLARE_ROOT:-$HOME/nvflare_testing/NVFlare}"
VENV_PATH="${VENV_PATH:-$HOME/nvflare_testing/nvflare_env}"
LOGS_DIR="${LOGS_DIR:-$HOME/nvflare_testing/logs}"
RESULTS_DIR="${RESULTS_DIR:-$HOME/nvflare_testing/results}"
TEST_NAME="llm-hf"
LOG_FILE="$LOGS_DIR/${TEST_NAME}_${TIMESTAMP}.log"
RESULT_DIR="$RESULTS_DIR/${TEST_NAME}_${TIMESTAMP}"

export TMPDIR="$HOME/nvflare_testing/tmp"
mkdir -p "$TMPDIR"

EXAMPLE_DIR="$NVFLARE_ROOT/examples/advanced/llm_hf"

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
echo "LLM HuggingFace Federated Fine-Tuning Test"
echo "=========================================="
echo ""
if [ "$QUICK_TEST" = true ]; then
    echo "Mode: QUICK TEST (1 round)"
else
    echo "Mode: FULL TEST (3 rounds)"
fi
echo "Example: $EXAMPLE_DIR"
echo "Log: $LOG_FILE"
echo "Timestamp: $TIMESTAMP"
echo ""

# Create directories
mkdir -p "$LOGS_DIR" "$RESULTS_DIR" "$RESULT_DIR"

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

# Verify NVFlare
NVFLARE_VERSION=$(python -c "import nvflare; print(nvflare.__version__)" 2>/dev/null || echo "NOT_FOUND")
if [ "$NVFLARE_VERSION" = "NOT_FOUND" ]; then
    log_error "NVFlare not installed"
    exit 1
fi
log_success "NVFlare: $NVFLARE_VERSION"

# Check CUDA
GPU_COUNT=$(python -c "import torch; print(torch.cuda.device_count())" 2>/dev/null || echo "0")
if [ "$GPU_COUNT" -lt 1 ]; then
    log_error "No GPUs available"
    exit 1
fi
log_success "CUDA available with $GPU_COUNT GPU(s)"

show_gpu_status

# Set HuggingFace cache to avoid filling /tmp
export HF_HOME="$HOME/nvflare_testing/hf_cache"
export TRANSFORMERS_CACHE="$HF_HOME/transformers"
mkdir -p "$HF_HOME"
log_info "HuggingFace cache: $HF_HOME"

# Change to example directory
cd "$EXAMPLE_DIR"
log_info "Working directory: $(pwd)"

# Check datasets exist
log_info "Checking datasets..."
if [ ! -f "dataset/dolly/training.jsonl" ] || [ ! -f "dataset/alpaca/training.jsonl" ] || [ ! -f "dataset/oasst1/training.jsonl" ]; then
    log_error "Datasets not found! Run setup_llm_hf_data.sh first"
    log_info "Expected files:"
    log_info "  - dataset/dolly/training.jsonl"
    log_info "  - dataset/alpaca/training.jsonl"
    log_info "  - dataset/oasst1/training.jsonl"
    exit 1
fi
log_success "Datasets verified"

# Install dependencies
log_info "Installing dependencies (this may take several minutes)..."
# Note: requirements.txt has nvflare~=2.7rc but we already have it installed
# Skip nvflare to avoid conflicts
grep -v "^nvflare" requirements.txt > /tmp/requirements_no_nvflare.txt || true
if [ -s /tmp/requirements_no_nvflare.txt ]; then
    pip install --no-cache-dir -r /tmp/requirements_no_nvflare.txt >> "$LOG_FILE" 2>&1
    rm /tmp/requirements_no_nvflare.txt
fi
log_success "Dependencies installed"

# Verify key dependencies
log_info "Verifying LLM dependencies..."
python -c "import transformers, peft, trl; print(f'transformers: {transformers.__version__}, peft: {peft.__version__}, trl: {trl.__version__}')" | tee -a "$LOG_FILE"

echo ""
log_info "=========================================="
log_info "Starting LLM HuggingFace Test"
log_info "=========================================="
log_info "Model: GPT-Neo-1.3B (~6GB model weights)"
log_info "Note: First run will download model from HuggingFace (~6GB, may take 10-15 minutes)"
log_info "Clients: 2 (dolly, alpaca) - one per GPU"
log_info "GPUs: 0, 1"
if [ "$QUICK_TEST" = true ]; then
    log_info "Rounds: 1 (quick smoke test)"
    log_info "Expected duration: 15-30 minutes"
else
    log_info "Rounds: 3 (full test)"
    log_info "Expected duration: 1-2 hours"
fi
log_info "Monitor: tail -f $LOG_FILE"
echo ""

show_gpu_status

START_TIME=$(date +%s)

# Run test
# Note: llm_hf requires one GPU and one port per client, plus data_path
# We have 2 GPUs, so use 2 clients with 2 ports
DATA_PATH="$EXAMPLE_DIR/dataset"
if [ "$QUICK_TEST" = true ]; then
    log_info "Running: python job.py --client_ids dolly alpaca --num_rounds 1 --gpu \"0,1\" --ports 7777 7778 --data_path $DATA_PATH --workspace_dir $RESULT_DIR/workspace"
    python job.py \
        --client_ids dolly alpaca \
        --num_rounds 1 \
        --gpu "0,1" \
        --ports 7777 7778 \
        --data_path "$DATA_PATH" \
        --workspace_dir "$RESULT_DIR/workspace" \
        >> "$LOG_FILE" 2>&1
else
    log_info "Running: python job.py --client_ids dolly alpaca --num_rounds 3 --gpu \"0,1\" --ports 7777 7778 --data_path $DATA_PATH --workspace_dir $RESULT_DIR/workspace"
    python job.py \
        --client_ids dolly alpaca \
        --num_rounds 3 \
        --gpu "0,1" \
        --ports 7777 7778 \
        --data_path "$DATA_PATH" \
        --workspace_dir "$RESULT_DIR/workspace" \
        >> "$LOG_FILE" 2>&1
fi

EXIT_CODE=$?

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
log_info "=========================================="
if [ $EXIT_CODE -eq 0 ]; then
    log_success "✅ LLM HuggingFace test PASSED!"
else
    log_error "❌ LLM HuggingFace test FAILED (exit code: $EXIT_CODE)"
fi
log_info "=========================================="
log_info "Duration: ${DURATION}s ($((DURATION/60)) minutes)"
echo ""

show_gpu_status

# Analyze results
log_info "Analyzing results..."
echo ""

if grep -q "Finished FedAvg" "$LOG_FILE"; then
    log_success "✅ FedAvg training completed"
else
    log_error "⚠️  FedAvg completion marker not found"
fi

if [ "$QUICK_TEST" = true ]; then
    EXPECTED_ROUNDS=1
else
    EXPECTED_ROUNDS=3
fi

ROUNDS=$(grep -c "Round [0-9]* started" "$LOG_FILE" || echo "0")
log_info "Training rounds completed: $ROUNDS / $EXPECTED_ROUNDS"

# Check for model files
MODEL_COUNT=$(find "$RESULT_DIR/workspace" -name "*.pt" -o -name "*.pth" -o -name "pytorch_model.bin" 2>/dev/null | wc -l)
log_info "Model files saved: $MODEL_COUNT"

# Check for errors
ERROR_COUNT=$(grep -i "error\|exception" "$LOG_FILE" | grep -v "Error processing frame\|UserWarning" | wc -l || echo "0")
if [ "$ERROR_COUNT" -gt 0 ]; then
    log_error "Found $ERROR_COUNT error messages"
    echo ""
    log_info "Recent errors:"
    grep -i "error\|exception" "$LOG_FILE" | grep -v "Error processing frame\|UserWarning" | tail -5
fi

# Save results
log_info "Saving results..."
cp "$LOG_FILE" "$RESULT_DIR/"
echo "Test: LLM HuggingFace Federated Fine-Tuning" > "$RESULT_DIR/summary.txt"
echo "Timestamp: $(date)" >> "$RESULT_DIR/summary.txt"
echo "Mode: $([ "$QUICK_TEST" = true ] && echo "Quick (1 round)" || echo "Full (3 rounds)")" >> "$RESULT_DIR/summary.txt"
echo "Exit code: $EXIT_CODE" >> "$RESULT_DIR/summary.txt"
echo "Duration: ${DURATION}s ($((DURATION/60)) minutes)" >> "$RESULT_DIR/summary.txt"
echo "Rounds: $ROUNDS / $EXPECTED_ROUNDS" >> "$RESULT_DIR/summary.txt"
echo "Models: $MODEL_COUNT" >> "$RESULT_DIR/summary.txt"
echo "Errors: $ERROR_COUNT" >> "$RESULT_DIR/summary.txt"

echo ""
log_info "=========================================="
log_info "Test Summary"
log_info "=========================================="
log_info "Exit Code: $EXIT_CODE"
log_info "Duration: $((DURATION/60)) minutes"
log_info "Rounds: $ROUNDS / $EXPECTED_ROUNDS"
log_info "Models: $MODEL_COUNT"
log_info "Log: $LOG_FILE"
log_info "Results: $RESULT_DIR"
echo ""

if [ $EXIT_CODE -eq 0 ] && [ "$ROUNDS" -eq "$EXPECTED_ROUNDS" ]; then
    log_success "🎉 Test completed successfully!"
else
    log_error "⚠️  Test had issues. Check logs for details."
fi

exit $EXIT_CODE
