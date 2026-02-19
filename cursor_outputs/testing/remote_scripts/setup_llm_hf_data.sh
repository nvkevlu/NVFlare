#!/bin/bash
# setup_llm_hf_data.sh - Download and preprocess LLM HuggingFace datasets
#
# This downloads 3 instruction-tuning datasets and preprocesses them
# Requirements: Git LFS, ~5-10GB disk space
#
# Usage: ./setup_llm_hf_data.sh

set -e

# Configuration
NVFLARE_ROOT="${NVFLARE_ROOT:-$HOME/nvflare_testing/NVFlare}"
EXAMPLE_DIR="$NVFLARE_ROOT/examples/advanced/llm_hf"
DATASET_DIR="$EXAMPLE_DIR/dataset"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo "=========================================="
echo "LLM HuggingFace Data Setup"
echo "=========================================="
echo ""

# Activate virtual environment
VENV_PATH="${VENV_PATH:-$HOME/nvflare_testing/nvflare_env}"
if [ ! -f "$VENV_PATH/bin/activate" ]; then
    echo -e "${RED}❌ Virtual environment not found: $VENV_PATH${NC}"
    exit 1
fi
echo -e "${BLUE}Activating virtual environment...${NC}"
source "$VENV_PATH/bin/activate"
echo -e "${GREEN}✓${NC} Virtual environment activated"
echo ""

# Install preprocessing dependencies (datasets lib for parquet files, pyarrow)
echo -e "${BLUE}Installing preprocessing dependencies...${NC}"
pip install --no-cache-dir numpy pandas datasets pyarrow > /dev/null 2>&1
echo -e "${GREEN}✓${NC} Dependencies installed"
echo ""

# Check Git LFS
if ! command -v git-lfs &> /dev/null; then
    echo -e "${RED}❌ Git LFS not installed!${NC}"
    echo ""
    echo "Installing Git LFS..."
    sudo apt-get update
    sudo apt-get install -y git-lfs
    git lfs install
fi
echo -e "${GREEN}✓${NC} Git LFS installed"

# Change to example directory
cd "$EXAMPLE_DIR"
echo -e "${BLUE}Working directory:${NC} $(pwd)"
echo ""

# Create dataset directory
mkdir -p "$DATASET_DIR"
cd "$DATASET_DIR"

# Download datasets
echo -e "${BLUE}[1/3]${NC} Downloading Dolly dataset..."
if [ ! -d "databricks-dolly-15k" ]; then
    git clone https://huggingface.co/datasets/databricks/databricks-dolly-15k
    echo -e "${GREEN}✓${NC} Dolly downloaded"
else
    echo -e "${YELLOW}⚠${NC} Dolly already exists"
fi

echo ""
echo -e "${BLUE}[2/3]${NC} Downloading Alpaca dataset..."
if [ ! -d "alpaca" ]; then
    git clone https://huggingface.co/datasets/tatsu-lab/alpaca
    echo -e "${GREEN}✓${NC} Alpaca downloaded"
else
    echo -e "${YELLOW}⚠${NC} Alpaca already exists"
fi

echo ""
echo -e "${BLUE}[3/3]${NC} Downloading OASST1 dataset..."
if [ ! -d "oasst1" ]; then
    git clone https://huggingface.co/datasets/OpenAssistant/oasst1
    echo -e "${GREEN}✓${NC} OASST1 downloaded"
else
    echo -e "${YELLOW}⚠${NC} OASST1 already exists"
fi

cd "$EXAMPLE_DIR"

# Preprocess datasets
echo ""
echo "=========================================="
echo "Preprocessing Datasets"
echo "=========================================="
echo ""

echo -e "${BLUE}[1/3]${NC} Preprocessing Dolly..."
mkdir -p dataset/dolly
python ./utils/preprocess_dolly.py \
    --training_file dataset/databricks-dolly-15k/databricks-dolly-15k.jsonl \
    --output_dir dataset/dolly
echo -e "${GREEN}✓${NC} Dolly preprocessed"

echo ""
echo -e "${BLUE}[2/3]${NC} Preprocessing Alpaca..."
mkdir -p dataset/alpaca
python ./utils/preprocess_alpaca.py \
    --training_file dataset/alpaca/data/train-00000-of-00001-a09b74b3ef9c3b56.parquet \
    --output_dir dataset/alpaca
echo -e "${GREEN}✓${NC} Alpaca preprocessed"

echo ""
echo -e "${BLUE}[3/3]${NC} Preprocessing OASST1..."
mkdir -p dataset/oasst1
python ./utils/preprocess_oasst1.py \
    --training_file dataset/oasst1/data/train-00000-of-00001-b42a775f407cee45.parquet \
    --validation_file dataset/oasst1/data/validation-00000-of-00001-134b8fd0c89408b6.parquet \
    --output_dir dataset/oasst1
echo -e "${GREEN}✓${NC} OASST1 preprocessed"

echo ""
echo "=========================================="
echo -e "${GREEN}✓ Data Setup Complete!${NC}"
echo "=========================================="
echo ""
echo "Datasets ready at: $DATASET_DIR"
echo ""
ls -lh "$DATASET_DIR"
echo ""
