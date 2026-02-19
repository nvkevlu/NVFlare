#!/bin/bash
# setup_tf_venv.sh - Create clean TensorFlow-only venv
#
# This creates a SEPARATE venv for TensorFlow to avoid conflicts with PyTorch
#
# Usage: ./setup_tf_venv.sh

set -e

# Configuration
WORK_DIR="$HOME/nvflare_testing"
TF_VENV_DIR="$WORK_DIR/nvflare_tf_env"
REPO_DIR="$WORK_DIR/NVFlare"
TMPDIR="$WORK_DIR/tmp"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "TensorFlow-Only Virtual Environment Setup"
echo "=========================================="
echo ""

# Remove old TF venv if exists
if [ -d "$TF_VENV_DIR" ]; then
    echo -e "${YELLOW}⚠️  Removing old TensorFlow venv...${NC}"
    rm -rf "$TF_VENV_DIR"
fi

# Create new venv
echo -e "${BLUE}🔨 Creating TensorFlow virtual environment...${NC}"
python3 -m venv "$TF_VENV_DIR"

# Activate
echo -e "${BLUE}✨ Activating virtual environment...${NC}"
source "$TF_VENV_DIR/bin/activate"

# Set TMPDIR
export TMPDIR="$TMPDIR"
mkdir -p "$TMPDIR"

# Upgrade pip
echo -e "${BLUE}📦 Upgrading pip...${NC}"
pip install --upgrade pip setuptools wheel

# Install NVFlare
echo -e "${BLUE}📥 Installing NVFlare...${NC}"
cd "$REPO_DIR"
pip install -e .

# Install TensorFlow ONLY (no PyTorch!)
echo -e "${BLUE}🤖 Installing TensorFlow with GPU support...${NC}"
pip install --no-cache-dir tensorflow[and-cuda]

# Verify
echo ""
echo "=========================================="
echo "🔍 Verification"
echo "=========================================="
python << 'PYEOF'
import nvflare
import tensorflow as tf

print(f"\n✅ NVFlare: {nvflare.__version__}")
print(f"✅ TensorFlow: {tf.__version__}")

gpus = tf.config.list_physical_devices('GPU')
print(f"✅ GPU count: {len(gpus)}")
for gpu in gpus:
    print(f"   {gpu}")

# Check that PyTorch is NOT installed
try:
    import torch
    print("\n⚠️  WARNING: PyTorch is installed! (should not be)")
except ImportError:
    print("\n✅ PyTorch NOT installed (good!)")
PYEOF

echo ""
echo "=========================================="
echo -e "${GREEN}✅ TensorFlow venv ready!${NC}"
echo "=========================================="
echo ""
echo "Location: $TF_VENV_DIR"
echo ""
echo "To activate later:"
echo "  source $TF_VENV_DIR/bin/activate"
echo ""
