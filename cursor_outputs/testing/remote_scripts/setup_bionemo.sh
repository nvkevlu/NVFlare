#!/bin/bash
# BioNeMo Remote Testing Setup Script
# Purpose: Update 2.7 branch, setup Docker, and prepare BioNeMo testing environment
# Date: January 26, 2026

set -e  # Exit on error

echo "=================================================="
echo "BioNeMo Testing Setup for NVFlare 2.7"
echo "=================================================="
echo ""

# Configuration
REPO_DIR=~/nvflare_testing/NVFlare
VENV_NAME=nvflare_env  # Use existing venv created by remote_setup.sh
DOCKER_IMAGE="nvcr.io/nvidia/clara/bionemo-framework:2.5"

# ======================
# Step 1: Update 2.7 Branch
# ======================
echo "[1/5] Updating NVFlare to latest 2.7 branch..."
cd $REPO_DIR

# Fetch latest changes
echo "  - Fetching from origin (NVIDIA/NVFlare)..."
git fetch origin 2.7

# Check if we're on 2.7 branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "2.7" ]; then
    echo "  ⚠️  Currently on branch: $CURRENT_BRANCH"
    echo "  - Switching to 2.7..."
    git checkout 2.7
fi

# Show what's new
echo ""
echo "  📊 New commits on 2.7:"
git log --oneline HEAD..origin/2.7 | head -10
echo ""

# Merge or pull latest
read -p "  Merge latest 2.7 changes? (y/n): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    git merge origin/2.7 --no-edit
    echo "  ✅ Updated to latest 2.7"
else
    echo "  ⏭️  Skipping merge (using current commit)"
fi

# Show current commit
echo ""
echo "  📍 Current commit:"
git log -1 --oneline
echo ""

# ======================
# Step 2: Activate Venv
# ======================
echo "[2/5] Activating Python venv: $VENV_NAME..."
source ~/nvflare_testing/$VENV_NAME/bin/activate

# Verify NVFlare installation (editable install should pick up latest code)
echo "  - NVFlare version:"
python -c "import nvflare; print(f'    {nvflare.__version__}')"
echo ""

# ======================
# Step 3: Check Docker
# ======================
echo "[3/5] Checking Docker installation..."
if ! command -v docker &> /dev/null; then
    echo "  ❌ Docker not found! Please install Docker first:"
    echo "     https://docs.docker.com/engine/install/"
    exit 1
fi

echo "  - Docker version:"
docker --version
echo ""

# Check NVIDIA Container Toolkit
echo "  - Checking NVIDIA Container Toolkit..."
if docker run --rm --gpus all nvidia/cuda:11.8.0-base-ubuntu22.04 nvidia-smi &> /dev/null; then
    echo "    ✅ NVIDIA Container Toolkit working"
else
    echo "    ⚠️  NVIDIA Container Toolkit may not be configured"
    echo "    Install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
fi
echo ""

# ======================
# Step 4: Pull BioNeMo Docker Image
# ======================
echo "[4/5] Pulling BioNeMo Docker image: $DOCKER_IMAGE..."
echo "  (This may take 10-20 minutes for first download, ~10GB image)"
echo ""

docker pull $DOCKER_IMAGE
if [ $? -eq 0 ]; then
    echo "  ✅ BioNeMo image ready"
else
    echo "  ❌ Failed to pull BioNeMo image"
    echo "  Check NGC credentials: https://ngc.nvidia.com/setup"
    exit 1
fi
echo ""

# ======================
# Step 5: Prepare BioNeMo Example Directory
# ======================
echo "[5/5] Preparing BioNeMo example directory..."
BIONEMO_DIR=$REPO_DIR/examples/advanced/bionemo
cd $BIONEMO_DIR

echo "  - BioNeMo directory: $BIONEMO_DIR"
echo "  - Files:"
ls -lh start_bionemo.sh
echo ""

# Check GPU availability
echo "  - GPU Status:"
nvidia-smi --query-gpu=index,name,memory.total --format=csv
echo ""

# ======================
# Summary
# ======================
echo "=================================================="
echo "✅ BioNeMo Setup Complete!"
echo "=================================================="
echo ""
echo "📋 Summary:"
echo "  - NVFlare Branch: 2.7 (latest)"
echo "  - Venv: $VENV_NAME"
echo "  - Docker Image: $DOCKER_IMAGE"
echo "  - Working Directory: $BIONEMO_DIR"
echo ""
echo "🚀 Next Steps:"
echo ""
echo "  1. Review BioNeMo example requirements:"
echo "     cat $BIONEMO_DIR/README.md"
echo ""
echo "  2. Start BioNeMo Docker container:"
echo "     cd $BIONEMO_DIR"
echo "     ./start_bionemo.sh"
echo ""
echo "  3. Inside container, run Jupyter notebook:"
echo "     - Notebook will be at: http://localhost:8888"
echo "     - Follow protein_property_prediction_with_bionemo.ipynb"
echo ""
echo "  4. For automated testing, prepare datasets first:"
echo "     - ESM-2 protein embeddings"
echo "     - Domain-specific protein data"
echo ""
echo "=================================================="
echo ""
echo "⚠️  BioNeMo Notes:"
echo "  - Requires specialized datasets (not included)"
echo "  - Jupyter notebook-based workflow"
echo "  - Domain expertise helpful (drug discovery)"
echo "  - Test complexity: HIGH"
echo ""
echo "💡 Alternative: Test simpler examples first"
echo "   (multi-gpu, tensor-stream, llm_hf)"
echo ""
