#!/bin/bash
# fix_and_continue.sh - Fix the /tmp space issue and continue setup
# Usage: ./fix_and_continue.sh

set -e

echo "=========================================="
echo "Fixing /tmp Space Issue and Continuing Setup"
echo "=========================================="
echo ""

WORK_DIR="$HOME/nvflare_testing"
VENV_DIR="$WORK_DIR/nvflare_env"
REPO_DIR="$WORK_DIR/NVFlare"

# Check if venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo "❌ Virtual environment not found!"
    echo "Please run ./remote_setup.sh first"
    exit 1
fi

# Activate venv
source "$VENV_DIR/bin/activate"
cd "$REPO_DIR"

# Set TMPDIR to avoid /tmp space issues
export TMPDIR="$WORK_DIR/tmp"
mkdir -p "$TMPDIR"

echo "✅ Using temp directory: $TMPDIR (plenty of space!)"
echo "✅ Virtual environment activated"
echo ""

# Check current disk usage
echo "=== Disk Space Check ==="
df -h "$WORK_DIR"
echo ""

# Install PyTorch with CUDA support
echo "=========================================="
echo "🔥 Installing PyTorch with CUDA support..."
echo "=========================================="
echo ""
echo "Download size: ~780MB"
echo "This may take 5-10 minutes..."
echo ""

pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Verify PyTorch CUDA
echo ""
echo "🔍 Verifying PyTorch CUDA support..."
python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')"

# Install TensorFlow with GPU support
echo ""
echo "=========================================="
echo "🤖 Installing TensorFlow with GPU support..."
echo "=========================================="
echo ""

pip install --no-cache-dir tensorflow[and-cuda]

# Install optional dependencies
echo ""
echo "=========================================="
echo "📦 Installing optional dependencies..."
echo "=========================================="
echo ""
pip install --no-cache-dir tenseal pytorch-lightning

# Verify TensorFlow GPU
echo ""
echo "🔍 Verifying TensorFlow GPU support..."
python -c "import tensorflow as tf; print(f'TensorFlow version: {tf.__version__}'); gpus = tf.config.list_physical_devices('GPU'); print(f'GPU count: {len(gpus)}'); [print(f'  {gpu}') for gpu in gpus]"

# Final CUDA verification
echo ""
echo "=========================================="
echo "🔍 Final CUDA Verification"
echo "=========================================="
python << 'PYEOF'
import torch
import tensorflow as tf

print("\n=== PyTorch CUDA Status ===")
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"CUDA version (PyTorch): {torch.version.cuda}")
    print(f"GPU count: {torch.cuda.device_count()}")
    for i in range(torch.cuda.device_count()):
        print(f"  GPU {i}: {torch.cuda.get_device_name(i)} ({torch.cuda.get_device_properties(i).total_memory / 1024**3:.1f} GB)")
else:
    print("⚠️  WARNING: PyTorch cannot access CUDA!")

print("\n=== TensorFlow GPU Status ===")
print(f"TensorFlow version: {tf.__version__}")
gpus = tf.config.list_physical_devices('GPU')
print(f"GPU count: {len(gpus)}")
if gpus:
    for gpu in gpus:
        print(f"  {gpu}")
else:
    print("⚠️  WARNING: TensorFlow cannot access GPUs!")

# Overall status
print("\n=== Overall Status ===")
if torch.cuda.is_available() and len(gpus) > 0:
    print("✅ CUDA is working correctly for both PyTorch and TensorFlow!")
    print("✅ Ready to run Multi-GPU tests!")
elif torch.cuda.is_available() or len(gpus) > 0:
    print("⚠️  CUDA is partially working (check warnings above)")
else:
    print("❌ CUDA is not working! Check CUDA_INSTALLATION_GUIDE.md")
PYEOF

echo ""
echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  cd $WORK_DIR"
echo "  ./run_multi_gpu_tests.sh"
echo ""
