#!/bin/bash
# remote_setup.sh - Setup NVFlare testing environment on remote machine
# Usage: ./remote_setup.sh

set -e

echo "=========================================="
echo "NVFlare Remote Testing - Setup"
echo "=========================================="
echo ""

# Configuration
NVFLARE_BRANCH="main"  # Change to "2.7" if you want specific branch
WORK_DIR="$HOME/nvflare_testing"
VENV_DIR="$WORK_DIR/nvflare_env"
REPO_DIR="$WORK_DIR/NVFlare"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Create work directory
echo "📁 Creating work directory..."
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

# Clone NVFlare repository
echo ""
echo "📦 Cloning NVFlare repository..."
if [ -d "$REPO_DIR" ]; then
    echo -e "${YELLOW}⚠️  NVFlare directory exists, pulling latest changes...${NC}"
    cd "$REPO_DIR"
    git pull
else
    git clone https://github.com/NVIDIA/NVFlare.git "$REPO_DIR"
    cd "$REPO_DIR"
    git checkout "$NVFLARE_BRANCH"
fi

echo ""
echo "Current branch: $(git branch --show-current)"
echo "Latest commit: $(git log -1 --oneline)"

# Detect Python version
echo ""
echo "🐍 Detecting Python..."
if command -v python3.9 &> /dev/null; then
    PYTHON_CMD="python3.9"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    echo "❌ Python 3 not found!"
    exit 1
fi

PYTHON_VERSION=$($PYTHON_CMD --version)
echo "Using: $PYTHON_VERSION"

# Create virtual environment
echo ""
echo "🔨 Creating virtual environment..."
if [ -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment exists, removing old one...${NC}"
    rm -rf "$VENV_DIR"
fi

$PYTHON_CMD -m venv "$VENV_DIR"

# Activate virtual environment
echo ""
echo "✨ Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Set temporary directory to avoid /tmp space issues
export TMPDIR="$WORK_DIR/tmp"
mkdir -p "$TMPDIR"
echo "Using temp directory: $TMPDIR"

# Upgrade pip
echo ""
echo "📦 Upgrading pip..."
pip install --upgrade pip setuptools wheel

# Install NVFlare in editable mode
echo ""
echo "📥 Installing NVFlare (editable mode)..."
cd "$REPO_DIR"
pip install -e .

# Install optional dependencies needed for examples
echo ""
echo "📦 Installing optional dependencies..."
echo "   - tenseal (for homomorphic encryption examples)"
echo "   - pytorch-lightning (for Lightning examples)"
pip install --no-cache-dir tenseal pytorch-lightning

# Verify NVFlare installation
echo ""
echo "🔍 Verifying NVFlare installation..."
python -c "import nvflare; print(f'NVFlare version: {nvflare.__version__}')"

# Install PyTorch with CUDA support
echo ""
echo "🔥 Installing PyTorch with CUDA support (large download, ~780MB)..."
echo "This may take 5-10 minutes..."
pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Verify PyTorch CUDA
echo ""
echo "🔍 Verifying PyTorch CUDA support..."
python -c "import torch; print(f'PyTorch version: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')"

# Install TensorFlow with GPU support
echo ""
echo "🤖 Installing TensorFlow with GPU support..."
pip install --no-cache-dir tensorflow[and-cuda]

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

# Create logs directory
echo ""
echo "📝 Creating logs directory..."
mkdir -p "$WORK_DIR/logs"

# Create results directory
echo ""
echo "📊 Creating results directory..."
mkdir -p "$WORK_DIR/results"

# Save environment info
echo ""
echo "💾 Saving environment info..."
cat > "$WORK_DIR/environment_info.txt" << EOF
Setup Date: $(date)
Hostname: $(hostname)
OS: $(lsb_release -d | cut -f2)
Kernel: $(uname -r)

Python: $($PYTHON_CMD --version)
Pip: $(pip --version)

NVFlare: $(python -c "import nvflare; print(nvflare.__version__)")
PyTorch: $(python -c "import torch; print(torch.__version__)")
TensorFlow: $(python -c "import tensorflow as tf; print(tf.__version__)")

GPUs:
$(nvidia-smi --query-gpu=name,memory.total,driver_version,cuda_version --format=csv)

NVFlare Branch: $NVFLARE_BRANCH
NVFlare Repo: $REPO_DIR
Virtual Env: $VENV_DIR
Work Dir: $WORK_DIR
EOF

cat "$WORK_DIR/environment_info.txt"

# Create activation helper script
echo ""
echo "📝 Creating activation helper script..."
cat > "$WORK_DIR/activate.sh" << 'EOF'
#!/bin/bash
# Quick activation script
source ~/nvflare_testing/nvflare_env/bin/activate
cd ~/nvflare_testing/NVFlare
echo "✅ NVFlare environment activated"
echo "📁 Current directory: $(pwd)"
echo "🐍 Python: $(python --version)"
echo ""
echo "To run tests: cd ~/nvflare_testing && ./run_multi_gpu_tests.sh"
EOF
chmod +x "$WORK_DIR/activate.sh"

echo ""
echo "=========================================="
echo -e "${GREEN}✅ Setup Complete!${NC}"
echo "=========================================="
echo ""
echo "Environment details saved to: $WORK_DIR/environment_info.txt"
echo ""
echo "To activate environment later:"
echo "  source $WORK_DIR/activate.sh"
echo ""
echo "Next steps:"
echo "  cd $WORK_DIR"
echo "  ./run_multi_gpu_tests.sh"
echo ""
