#!/bin/bash
# test_tensor_stream.sh - Test Tensor Streaming with GPT-2 LLM on GPU
# 
# This script tests the tensor-stream example which demonstrates:
# - Large tensor streaming (GPT-2 model ~620MB)
# - LLM fine-tuning in federated setting
# - Efficient tensor communication
#
# Hardware Requirements:
# - 2x GPUs with 24GB+ memory
# - Good for: 2x NVIDIA A30 24GB
#
# Estimated Time: 1-2 hours
#
# Usage: ./test_tensor_stream.sh

set -e  # Exit on error

# Configuration
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NVFLARE_ROOT="${NVFLARE_ROOT:-$HOME/nvflare_testing/NVFlare}"
VENV_PATH="${VENV_PATH:-$HOME/nvflare_testing/nvflare_env}"
LOGS_DIR="${LOGS_DIR:-$HOME/nvflare_testing/logs}"
RESULTS_DIR="${RESULTS_DIR:-$HOME/nvflare_testing/results}"
TEST_NAME="tensor-stream"
LOG_FILE="$LOGS_DIR/${TEST_NAME}_${TIMESTAMP}.log"
RESULT_DIR="$RESULTS_DIR/${TEST_NAME}_${TIMESTAMP}"

# Set TMPDIR to avoid /tmp space issues
export TMPDIR="$HOME/nvflare_testing/tmp"
mkdir -p "$TMPDIR"

# Example location
EXAMPLE_DIR="$NVFLARE_ROOT/examples/advanced/tensor-stream"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

# Function to show GPU status
show_gpu_status() {
    if command -v nvidia-smi &> /dev/null; then
        echo ""
        log_info "GPU Status:"
        nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv | tee -a "$LOG_FILE"
        echo ""
    fi
}

# Function to check if process is still running
check_process_alive() {
    local pid=$1
    if kill -0 "$pid" 2>/dev/null; then
        return 0
    else
        return 1
    fi
}

# Cleanup function
cleanup() {
    log_info "Cleaning up..."
    
    # Kill any remaining Python processes for this test
    pkill -f "tensor-stream/job.py" || true
    pkill -f "tensor-stream/trainer.py" || true
    
    # Clean up temp simulation directories
    if [ -d "/tmp/nvflare/simulation/tensor_stream" ]; then
        log_info "Removing simulation directory..."
        rm -rf /tmp/nvflare/simulation/tensor_stream
    fi
}

# Trap to ensure cleanup on exit
trap cleanup EXIT

# Header
echo "=========================================="
echo "Tensor Streaming Test with GPT-2 LLM"
echo "=========================================="
echo ""
echo "Example: $EXAMPLE_DIR"
echo "Log file: $LOG_FILE"
echo "Timestamp: $TIMESTAMP"
echo ""

# Create directories
mkdir -p "$LOGS_DIR"
mkdir -p "$RESULTS_DIR"
mkdir -p "$RESULT_DIR"

# Check if example exists
if [ ! -d "$EXAMPLE_DIR" ]; then
    log_error "Example directory not found: $EXAMPLE_DIR"
    exit 1
fi

log_success "Found tensor-stream example"

# Activate virtual environment
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    log_error "Virtual environment not found: $VENV_PATH"
    exit 1
fi

log_info "Activating virtual environment..."
source "$VENV_PATH/bin/activate"

# Verify NVFlare installation
log_info "Verifying NVFlare installation..."
NVFLARE_VERSION=$(python -c "import nvflare; print(nvflare.__version__)" 2>/dev/null || echo "NOT_FOUND")
if [ "$NVFLARE_VERSION" = "NOT_FOUND" ]; then
    log_error "NVFlare not installed in virtual environment"
    exit 1
fi
log_success "NVFlare version: $NVFLARE_VERSION"

# Show initial GPU status
show_gpu_status

# Change to example directory
cd "$EXAMPLE_DIR"
log_info "Working directory: $(pwd)"

# Check for requirements.txt
if [ -f "requirements.txt" ]; then
    log_info "Installing example dependencies (using --no-cache-dir)..."
    pip install --no-cache-dir -r requirements.txt >> "$LOG_FILE" 2>&1
    if [ $? -eq 0 ]; then
        log_success "Dependencies installed"
    else
        log_error "Failed to install dependencies"
        exit 1
    fi
else
    log_warning "No requirements.txt found, assuming dependencies are satisfied"
fi

# Verify critical dependencies
log_info "Verifying dependencies..."

# Check PyTorch
TORCH_VERSION=$(python -c "import torch; print(torch.__version__)" 2>/dev/null || echo "NOT_FOUND")
if [ "$TORCH_VERSION" = "NOT_FOUND" ]; then
    log_error "PyTorch not installed"
    exit 1
fi
log_success "PyTorch version: $TORCH_VERSION"

# Check CUDA availability
CUDA_AVAILABLE=$(python -c "import torch; print(torch.cuda.is_available())" 2>/dev/null || echo "False")
if [ "$CUDA_AVAILABLE" != "True" ]; then
    log_error "CUDA not available in PyTorch"
    exit 1
fi
GPU_COUNT=$(python -c "import torch; print(torch.cuda.device_count())" 2>/dev/null || echo "0")
log_success "CUDA available with $GPU_COUNT GPU(s)"

# Check HuggingFace transformers
TRANSFORMERS_VERSION=$(python -c "import transformers; print(transformers.__version__)" 2>/dev/null || echo "NOT_FOUND")
if [ "$TRANSFORMERS_VERSION" = "NOT_FOUND" ]; then
    log_error "HuggingFace transformers not installed"
    exit 1
fi
log_success "Transformers version: $TRANSFORMERS_VERSION"

# Check datasets library
DATASETS_VERSION=$(python -c "import datasets; print(datasets.__version__)" 2>/dev/null || echo "NOT_FOUND")
if [ "$DATASETS_VERSION" = "NOT_FOUND" ]; then
    log_error "HuggingFace datasets not installed"
    exit 1
fi
log_success "Datasets version: $DATASETS_VERSION"

# Pre-download IMDB dataset to avoid timeout during test
log_info "Pre-downloading IMDB dataset (stanfordnlp/imdb)..."
python -c "
from datasets import load_dataset
print('Loading IMDB dataset...')
dataset = load_dataset('stanfordnlp/imdb')
print(f'Dataset loaded: {len(dataset[\"train\"])} train, {len(dataset[\"test\"])} test samples')
" >> "$LOG_FILE" 2>&1

if [ $? -eq 0 ]; then
    log_success "Dataset pre-loaded successfully"
else
    log_error "Failed to pre-load dataset"
    exit 1
fi

# Pre-download GPT-2 model
log_info "Pre-downloading GPT-2 model..."
python -c "
from transformers import AutoTokenizer, AutoModelForCausalLM
print('Loading GPT-2 tokenizer and model...')
tokenizer = AutoTokenizer.from_pretrained('gpt2')
model = AutoModelForCausalLM.from_pretrained('gpt2')
print('GPT-2 model loaded successfully')
print(f'Model parameters: {sum(p.numel() for p in model.parameters())/1e6:.1f}M')
" >> "$LOG_FILE" 2>&1

if [ $? -eq 0 ]; then
    log_success "GPT-2 model pre-loaded successfully"
else
    log_error "Failed to pre-load GPT-2 model"
    exit 1
fi

echo ""
log_info "=========================================="
log_info "Starting Tensor Streaming Test"
log_info "=========================================="
log_info "This will take approximately 1-2 hours"
log_info "Monitor progress: tail -f $LOG_FILE"
log_info "Monitor GPUs: watch -n 1 nvidia-smi"
echo ""

# Run the test in background and capture PID
show_gpu_status

START_TIME=$(date +%s)
log_info "Running: python job.py"

# Run with full logging
python job.py >> "$LOG_FILE" 2>&1 &
JOB_PID=$!

log_info "Job started with PID: $JOB_PID"

# Monitor progress
LAST_CHECK=0
CHECK_INTERVAL=60  # Check every 60 seconds
TIMEOUT=7200  # 2 hour timeout

while check_process_alive $JOB_PID; do
    ELAPSED=$(($(date +%s) - START_TIME))
    
    # Check for timeout
    if [ $ELAPSED -gt $TIMEOUT ]; then
        log_error "Test exceeded timeout of $TIMEOUT seconds"
        kill -9 $JOB_PID 2>/dev/null || true
        exit 1
    fi
    
    # Show progress every CHECK_INTERVAL seconds
    if [ $((ELAPSED - LAST_CHECK)) -ge $CHECK_INTERVAL ]; then
        log_info "Test running for $((ELAPSED/60)) minutes..."
        
        # Show GPU status
        show_gpu_status
        
        # Show recent log entries
        log_info "Recent activity:"
        tail -5 "$LOG_FILE" | grep -E "Round|Accuracy|loss|Finished" || true
        
        LAST_CHECK=$ELAPSED
    fi
    
    sleep 5
done

# Wait for process to fully exit
wait $JOB_PID
EXIT_CODE=$?

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
log_info "=========================================="

if [ $EXIT_CODE -eq 0 ]; then
    log_success "✅ Tensor Streaming test PASSED!"
else
    log_error "❌ Tensor Streaming test FAILED with exit code: $EXIT_CODE"
fi

log_info "=========================================="
log_info "Duration: ${DURATION}s ($((DURATION/60)) minutes)"
echo ""

# Show final GPU status
show_gpu_status

# Analyze results
log_info "Analyzing test results..."
echo ""

# Check for successful completion
if grep -q "Finished FedAvg" "$LOG_FILE"; then
    log_success "✅ FedAvg training completed"
else
    log_warning "⚠️  FedAvg completion marker not found"
fi

# Check for rounds completion
ROUNDS=$(grep -c "Round [0-9]* started" "$LOG_FILE" || echo "0")
log_info "Training rounds detected: $ROUNDS"

# Check for errors
ERROR_COUNT=$(grep -i "error\|exception\|failed" "$LOG_FILE" | grep -v "ERROR - Processing frame" | wc -l || echo "0")
if [ "$ERROR_COUNT" -gt 0 ]; then
    log_warning "Found $ERROR_COUNT error/exception messages in log"
    echo ""
    log_info "Recent errors:"
    grep -i "error\|exception\|failed" "$LOG_FILE" | grep -v "ERROR - Processing frame" | tail -10
fi

# Check for DXO errors specifically
if grep -q "not a valid DXO" "$LOG_FILE"; then
    log_error "❌ DXO errors detected (external process communication bug)"
fi

# Save results
log_info "Saving results..."
cp "$LOG_FILE" "$RESULT_DIR/"
echo "Test completed at: $(date)" > "$RESULT_DIR/summary.txt"
echo "Exit code: $EXIT_CODE" >> "$RESULT_DIR/summary.txt"
echo "Duration: ${DURATION}s ($((DURATION/60)) minutes)" >> "$RESULT_DIR/summary.txt"
echo "Rounds: $ROUNDS" >> "$RESULT_DIR/summary.txt"
echo "Errors: $ERROR_COUNT" >> "$RESULT_DIR/summary.txt"

# Copy simulation results if they exist
if [ -d "/tmp/nvflare/simulation/tensor_stream" ]; then
    log_info "Copying simulation results..."
    cp -r /tmp/nvflare/simulation/tensor_stream "$RESULT_DIR/" || true
fi

echo ""
log_info "=========================================="
log_info "Test Summary"
log_info "=========================================="
log_info "Exit Code: $EXIT_CODE"
log_info "Duration: $((DURATION/60)) minutes"
log_info "Rounds: $ROUNDS"
log_info "Errors: $ERROR_COUNT"
log_info "Log: $LOG_FILE"
log_info "Results: $RESULT_DIR"
echo ""

if [ $EXIT_CODE -eq 0 ]; then
    log_success "🎉 Tensor Streaming test completed successfully!"
else
    log_error "⚠️  Test completed with errors. Check logs for details."
fi

exit $EXIT_CODE
