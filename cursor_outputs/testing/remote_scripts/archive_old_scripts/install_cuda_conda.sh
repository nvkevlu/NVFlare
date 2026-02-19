#!/bin/bash
# install_cuda_conda.sh - Install CUDA toolkit via Conda (no sudo required)
# This is faster and safer than system-wide installation
# Usage: ./install_cuda_conda.sh

set -e

echo "=========================================="
echo "CUDA Installation via Conda (No Sudo Required)"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

WORK_DIR="$HOME/nvflare_testing"
CONDA_DIR="$HOME/miniforge3"

# Check if miniforge/conda is already installed
if [ -d "$CONDA_DIR" ]; then
    echo -e "${YELLOW}⚠️  Miniforge already installed at $CONDA_DIR${NC}"
    source "$CONDA_DIR/etc/profile.d/conda.sh"
else
    echo "📥 Downloading Miniforge installer..."
    wget -q https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O miniforge.sh
    
    echo "📦 Installing Miniforge..."
    bash miniforge.sh -b -p "$CONDA_DIR"
    rm miniforge.sh
    
    # Initialize conda
    source "$CONDA_DIR/etc/profile.d/conda.sh"
    conda init bash
    echo -e "${GREEN}✅ Miniforge installed${NC}"
fi

echo ""
echo "🔨 Creating conda environment with CUDA..."

# Remove old environment if exists
if conda env list | grep -q "nvflare_cuda"; then
    echo "Removing old nvflare_cuda environment..."
    conda env remove -n nvflare_cuda -y
fi

# Create new environment with CUDA toolkit
echo "Creating new environment (this may take 5-10 minutes)..."
conda create -n nvflare_cuda python=3.9 -y

# Activate environment
conda activate nvflare_cuda

# Install CUDA toolkit via conda
echo ""
echo "📥 Installing CUDA toolkit 12.1 via conda..."
conda install -c nvidia cuda-toolkit=12.1 -y

# Verify CUDA installation
echo ""
echo "🔍 Verifying CUDA installation..."
nvcc --version

echo ""
echo "=========================================="
echo -e "${GREEN}✅ CUDA Installation Complete (Conda)${NC}"
echo "=========================================="
echo ""
echo "To use this environment:"
echo "  conda activate nvflare_cuda"
echo ""
echo "Next steps:"
echo "  1. Close and reopen your terminal (to reload bash profile)"
echo "  2. conda activate nvflare_cuda"
echo "  3. Continue with NVFlare setup"
echo ""
