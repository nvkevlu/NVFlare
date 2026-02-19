#!/bin/bash
# verify_env.sh - Verify remote machine environment for NVFlare testing
# Usage: ./verify_env.sh

set -e

echo "=========================================="
echo "NVFlare Remote Testing - Environment Check"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check GPU
echo "=== GPU Check ==="
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
    GPU_COUNT=$(nvidia-smi --query-gpu=name --format=csv,noheader | wc -l)
    echo -e "${GREEN}✅ Found $GPU_COUNT GPU(s)${NC}"
else
    echo -e "${RED}❌ nvidia-smi not found!${NC}"
    exit 1
fi

echo ""

# Check CUDA
echo "=== CUDA Check ==="
if command -v nvcc &> /dev/null; then
    CUDA_VERSION=$(nvcc --version | grep "release" | awk '{print $5}' | cut -d',' -f1)
    echo -e "${GREEN}✅ CUDA ${CUDA_VERSION} detected${NC}"
else
    echo -e "${YELLOW}⚠️  nvcc not found (CUDA toolkit not installed at system level)${NC}"
    echo ""
    echo "This is OK! PyTorch and TensorFlow will install their own CUDA libraries."
    echo "You can proceed with setup. See CUDA_INSTALLATION_GUIDE.md if you need system CUDA."
fi

echo ""

# Check Python
echo "=== Python Check ==="
if command -v python3.9 &> /dev/null; then
    PYTHON_VERSION=$(python3.9 --version)
    echo -e "${GREEN}✅ ${PYTHON_VERSION} found${NC}"
elif command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo -e "${YELLOW}⚠️  ${PYTHON_VERSION} found (python3.9 preferred but will work)${NC}"
else
    echo -e "${RED}❌ Python 3 not found!${NC}"
    exit 1
fi

echo ""

# Check system resources
echo "=== System Resources ==="
TOTAL_RAM=$(free -h | grep Mem | awk '{print $2}')
AVAILABLE_RAM=$(free -h | grep Mem | awk '{print $7}')
CPU_COUNT=$(nproc)
echo "CPU Cores: $CPU_COUNT"
echo "Total RAM: $TOTAL_RAM"
echo "Available RAM: $AVAILABLE_RAM"

# Check if we have enough RAM (recommend 32GB+)
TOTAL_RAM_GB=$(free -g | grep Mem | awk '{print $2}')
if [ "$TOTAL_RAM_GB" -ge 32 ]; then
    echo -e "${GREEN}✅ Sufficient RAM ($TOTAL_RAM)${NC}"
else
    echo -e "${YELLOW}⚠️  RAM is $TOTAL_RAM (32GB+ recommended)${NC}"
fi

echo ""

# Check disk space
echo "=== Disk Space ==="
DISK_AVAILABLE=$(df -h . | tail -1 | awk '{print $4}')
echo "Available disk space: $DISK_AVAILABLE"

echo ""

# Check Git
echo "=== Git Check ==="
if command -v git &> /dev/null; then
    GIT_VERSION=$(git --version)
    echo -e "${GREEN}✅ ${GIT_VERSION}${NC}"
else
    echo -e "${RED}❌ Git not found! Please install git.${NC}"
    exit 1
fi

echo ""

# Summary
echo "=========================================="
echo "Environment Verification Complete!"
echo "=========================================="
echo ""

# Check if we should warn about CUDA
if ! command -v nvcc &> /dev/null; then
    echo -e "${YELLOW}Note: System CUDA toolkit not found, but this is OK!${NC}"
    echo "PyTorch and TensorFlow will use their bundled CUDA libraries."
    echo ""
    echo "If you prefer to install system CUDA, see: CUDA_INSTALLATION_GUIDE.md"
    echo ""
fi

echo "Ready to proceed with NVFlare setup!"
echo ""
echo "Next steps:"
echo "  1. Run: ./remote_setup.sh       (~15 minutes)"
echo "  2. Run: ./run_multi_gpu_tests.sh (~1 hour)"
echo ""
