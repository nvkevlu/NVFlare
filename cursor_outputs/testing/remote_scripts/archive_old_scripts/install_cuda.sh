#!/bin/bash
# install_cuda.sh - Install CUDA toolkit on Ubuntu 24.04
# Usage: ./install_cuda.sh

set -e

echo "=========================================="
echo "CUDA Toolkit Installation for Ubuntu 24.04"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run with sudo:${NC}"
    echo "  sudo ./install_cuda.sh"
    exit 1
fi

echo "🔍 Checking current system..."
echo ""

# Check Ubuntu version
UBUNTU_VERSION=$(lsb_release -rs)
echo "Ubuntu version: $UBUNTU_VERSION"

# Check if CUDA is already installed
if command -v nvcc &> /dev/null; then
    EXISTING_CUDA=$(nvcc --version | grep "release" | awk '{print $5}' | cut -d',' -f1)
    echo -e "${YELLOW}⚠️  CUDA ${EXISTING_CUDA} is already installed${NC}"
    echo ""
    read -p "Do you want to reinstall/upgrade? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi
fi

echo ""
echo "📦 Installing CUDA Toolkit 12.1 (recommended for PyTorch 2.x)..."
echo ""

# Remove old CUDA/NVIDIA packages if they exist
echo "🧹 Cleaning up old installations..."
apt-get remove --purge -y '^nvidia-.*' '^libnvidia-.*' '^cuda-.*' 2>/dev/null || true
apt-get autoremove -y
apt-get autoclean

# Update package list
echo ""
echo "📥 Updating package lists..."
apt-get update

# Install prerequisites
echo ""
echo "📦 Installing prerequisites..."
apt-get install -y \
    build-essential \
    dkms \
    linux-headers-$(uname -r) \
    wget \
    software-properties-common

# Add NVIDIA package repository
echo ""
echo "📦 Adding NVIDIA package repository..."
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
dpkg -i cuda-keyring_1.1-1_all.deb
rm cuda-keyring_1.1-1_all.deb

# Update package list with NVIDIA repo
apt-get update

# Install CUDA Toolkit 12.1
echo ""
echo "📥 Installing CUDA Toolkit 12.1 (this may take 10-15 minutes)..."
apt-get install -y cuda-toolkit-12-1

# Install NVIDIA drivers (if not already installed)
echo ""
echo "📥 Installing NVIDIA drivers..."
apt-get install -y nvidia-driver-545

# Set up environment variables
echo ""
echo "🔧 Setting up environment variables..."

# Add to /etc/environment for system-wide access
if ! grep -q "CUDA_HOME" /etc/environment; then
    echo 'CUDA_HOME=/usr/local/cuda-12.1' >> /etc/environment
fi

# Create profile script for PATH
cat > /etc/profile.d/cuda.sh << 'EOF'
export CUDA_HOME=/usr/local/cuda-12.1
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
EOF

chmod +x /etc/profile.d/cuda.sh

# Create symbolic link
if [ ! -L /usr/local/cuda ]; then
    ln -sf /usr/local/cuda-12.1 /usr/local/cuda
fi

echo ""
echo "=========================================="
echo -e "${GREEN}✅ CUDA Installation Complete!${NC}"
echo "=========================================="
echo ""
echo "⚠️  IMPORTANT: You MUST reboot the system for driver changes to take effect!"
echo ""
echo "After reboot, verify installation with:"
echo "  nvidia-smi"
echo "  nvcc --version"
echo ""
echo "To reboot now:"
echo "  sudo reboot"
echo ""
