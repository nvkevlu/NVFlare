# Remote Testing Machine Requirements

**Purpose:** This document specifies hardware and software requirements for testing NVFlare 2.7 examples that cannot be tested on macOS without GPU/CUDA support.

**Date:** January 27, 2026  
**NVFlare Branch:** 2.7 (latest)

---

## Summary Table

| Example Category | Min GPUs | Min VRAM/GPU | Min System RAM | CUDA Required | Est. Test Time | Priority |
|-----------------|----------|--------------|----------------|---------------|----------------|----------|
| **Multi-GPU (PyTorch)** | 2 | 8GB | 16GB | ✅ Yes | ~30 min | HIGH |
| **Multi-GPU (TensorFlow)** | 2 | 8GB | 16GB | ✅ Yes | ~30 min | HIGH |
| **Multi-GPU (Lightning)** | 2 | 8GB | 16GB | ✅ Yes | ~30 min | DEFERRED* |
| **Tensor-Stream (LLM)** | 1 | 16GB | 32GB | ⚠️ Recommended | ~2 hours | MEDIUM |
| **LLM HuggingFace** | 1-2 | 24GB+ | 32GB | ✅ Yes | ~3 hours | MEDIUM |
| **BioNeMo** | 1+ | 16GB+ | 32GB+ | ✅ Yes | Variable | LOW |

\* *Lightning integration has a known bug being worked on by another team member*

---

## Recommended Remote Machine Configurations

### Option 1: Standard GPU Testing (Multi-GPU Examples)
**Best for:** PyTorch DDP, TensorFlow MirroredStrategy  
**Configuration:**
- **GPUs:** 2x NVIDIA RTX 3090 (24GB VRAM each) or 2x RTX 4090 (24GB VRAM each)
- **CPU:** 8+ cores
- **RAM:** 32GB system memory
- **Storage:** 100GB SSD
- **OS:** Ubuntu 20.04/22.04 LTS
- **CUDA:** 11.8+ or 12.x
- **Estimated Cost:** ~$1-2/hour on cloud providers

**Can Test:**
- ✅ `examples/advanced/multi-gpu/pt/` (PyTorch DDP)
- ✅ `examples/advanced/multi-gpu/tf/` (TensorFlow MirroredStrategy)
- ✅ `examples/advanced/tensor-stream/` (with GPUs for faster LLM training)

---

### Option 2: High-End LLM Testing
**Best for:** LLM examples, large models  
**Configuration:**
- **GPUs:** 2x NVIDIA RTX 6000 Ada (48GB VRAM each) or 2x A100 (40GB VRAM each)
- **CPU:** 16+ cores
- **RAM:** 64GB system memory
- **Storage:** 200GB SSD
- **OS:** Ubuntu 20.04/22.04 LTS
- **CUDA:** 12.x
- **Estimated Cost:** ~$3-5/hour on cloud providers

**Can Test:**
- ✅ All Multi-GPU examples
- ✅ `examples/advanced/llm_hf/` (GPT-Neo-1.3B with multi-GPU)
- ✅ `examples/advanced/tensor-stream/` (GPT-2 LLM fine-tuning)
- ✅ `examples/advanced/bionemo/` (if Docker + datasets available)

---

### Option 3: Budget CPU-Only Testing (Limited)
**Best for:** Verifying code changes only, not full training  
**Configuration:**
- **GPUs:** None
- **CPU:** 16+ cores
- **RAM:** 32GB system memory
- **Storage:** 100GB SSD
- **OS:** Ubuntu 20.04/22.04 LTS

**Can Test (with caveats):**
- ⚠️ `examples/advanced/tensor-stream/` - Will be VERY slow (~8+ hours), may hang
- ❌ Multi-GPU examples - Cannot test without GPUs
- ❌ LLM HuggingFace - Too slow for practical testing

---

## Detailed Example Requirements

### 1. Multi-GPU PyTorch DDP (`examples/advanced/multi-gpu/pt/`)

**Status:** NOT TESTED (no GPUs on macOS)  
**Purpose:** Test PyTorch Distributed Data Parallel with NVFlare

**Hardware Requirements:**
- **Minimum:** 2 CUDA-capable GPUs
- **Recommended:** 2x RTX 3090 (24GB) or better
- **VRAM per GPU:** 8GB minimum, 16GB+ recommended
- **System RAM:** 16GB minimum, 32GB recommended
- **NCCL:** Required (for multi-GPU communication)

**Software Requirements:**
```bash
# From requirements.txt
torch>=2.0.0 (with CUDA support)
torchvision
nvflare~=2.7.2rc
```

**CUDA/Driver:**
- CUDA 11.8+ or 12.x
- NVIDIA Driver: 520+ (for CUDA 11.8) or 525+ (for CUDA 12.x)

**Test Commands:**
```bash
cd examples/advanced/multi-gpu/pt/
bash prepare_data.sh
python job.py
```

**Expected Runtime:** ~20-30 minutes (CIFAR-10, 5 rounds, 2 clients)

**Success Criteria:**
- ✅ Job completes without errors
- ✅ Both clients use DDP across 2 GPUs
- ✅ Model converges (accuracy >50% on CIFAR-10)
- ✅ Different master ports work for multiple clients

---

### 2. Multi-GPU TensorFlow (`examples/advanced/multi-gpu/tf/`)

**Status:** NOT TESTED (no GPUs on macOS)  
**Purpose:** Test TensorFlow MirroredStrategy with NVFlare

**Hardware Requirements:**
- **Minimum:** 2 CUDA-capable GPUs
- **Recommended:** 2x RTX 3090 (24GB) or better
- **VRAM per GPU:** 8GB minimum, 16GB+ recommended
- **System RAM:** 16GB minimum, 32GB recommended

**Software Requirements:**
```bash
# From requirements.txt
tensorflow>=2.12.0 (with GPU support)
nvflare~=2.7.2rc
```

**CUDA/Driver:**
- CUDA 11.8+ (TensorFlow 2.12+)
- cuDNN 8.6+
- NVIDIA Driver: 520+

**Test Commands:**
```bash
cd examples/advanced/multi-gpu/tf/
bash prepare_data.sh
python job.py
```

**Expected Runtime:** ~20-30 minutes (CIFAR-10, 5 rounds, 2 clients)

**Success Criteria:**
- ✅ Job completes without errors
- ✅ Both clients use MirroredStrategy across 2 GPUs
- ✅ Model converges (accuracy >50% on CIFAR-10)
- ✅ GPU memory properly distributed

---

### 3. Multi-GPU PyTorch Lightning (`examples/advanced/multi-gpu/lightning/`)

**Status:** DEFERRED (Lightning integration bug, someone else working on it)  
**Purpose:** Test PyTorch Lightning DDP with NVFlare

**Hardware Requirements:**
- **Minimum:** 2 CUDA-capable GPUs
- **Recommended:** 2x RTX 3090 (24GB) or better
- **VRAM per GPU:** 8GB minimum, 16GB+ recommended
- **System RAM:** 16GB minimum, 32GB recommended

**Software Requirements:**
```bash
# From requirements.txt
torch>=2.0.0 (with CUDA support)
torchvision
pytorch-lightning>=2.0.0
nvflare~=2.7.2rc
```

**KNOWN ISSUE:**
```
ValueError: the shareable is not a valid DXO - expect content_type DXO but got None
```
This is a core Lightning integration bug affecting ALL Lightning examples. Another team member is working on this. **DO NOT spend time debugging this issue.**

**Action:** Skip this example until Lightning integration is fixed.

---

### 4. Tensor Stream LLM (`examples/advanced/tensor-stream/`)

**Status:** PARTIALLY TESTED (dataset fix applied, but hung on CPU-only macOS)  
**Purpose:** Test NVFlare tensor streaming with GPT-2 LLM fine-tuning

**Hardware Requirements:**
- **Minimum (CPU-only):** 16 cores, 32GB RAM (VERY slow, may hang)
- **Recommended (GPU):** 1x RTX 3090 (24GB VRAM), 16 cores, 32GB RAM
- **Optimal (Multi-GPU):** 2x RTX 3090 (24GB VRAM), 16 cores, 64GB RAM

**Why GPU is Critical:**
- **Model Size:** GPT-2 base model = ~1.5GB, generates ~621MB tensors
- **CPU Training:** EXTREMELY slow (8+ hours per round, may hit OS buffer limits)
- **GPU Training:** ~30 minutes per round (practical)

**Software Requirements:**
```bash
# From requirements.txt
torch (CUDA support highly recommended)
transformers>=4.30.0
datasets
peft
trl
bitsandbytes
nvflare~=2.7.2rc
```

**CUDA/Driver (if using GPU):**
- CUDA 11.8+ or 12.x
- NVIDIA Driver: 520+

**Issues Fixed:**
✅ Dataset migration: Changed `load_dataset("imdb")` → `load_dataset("stanfordnlp/imdb")`

**Test Commands:**
```bash
cd examples/advanced/tensor-stream/
pip install -r requirements.txt
python job.py --n_clients 2 --num_rounds 2
```

**Expected Runtime:**
- **With GPU:** ~1-2 hours (2 clients, 2 rounds)
- **Without GPU:** 8+ hours (not recommended, may hang)

**Success Criteria:**
- ✅ IMDB dataset loads successfully
- ✅ GPT-2 model loads and streams (621MB tensors)
- ✅ Training completes 2 rounds
- ✅ Model perplexity improves
- ✅ No "OSError: No buffer space available" (macOS-specific issue)

---

### 5. LLM HuggingFace (`examples/advanced/llm_hf/`)

**Status:** CODE REVIEW ONLY (confirmed 2.7 API compliance, not tested)  
**Purpose:** Test federated LLM fine-tuning with SFT/PEFT (LoRA)

**Hardware Requirements:**

**Option A: Single GPU (PEFT only)**
- **GPU:** 1x RTX 3090 (24GB VRAM) or better
- **CPU:** 8+ cores
- **RAM:** 32GB system memory
- **Storage:** 50GB (for datasets + model checkpoints)

**Option B: Multi-GPU (SFT + PEFT)**
- **GPU:** 2x RTX 6000 Ada (48GB VRAM) or 2x A100 (40GB VRAM)
- **CPU:** 16+ cores
- **RAM:** 64GB system memory
- **Storage:** 100GB (for datasets + model checkpoints)

**Why High VRAM:**
- **GPT-Neo-1.3B (SFT):** ~5-6GB model (float32) + gradients = 20GB+ VRAM
- **PEFT (LoRA):** Only fine-tunes small adapters, requires less VRAM (~8-12GB)

**Software Requirements:**
```bash
# From requirements.txt
torch>=2.7.0 (with CUDA)
transformers>=4.56.0
peft>=0.17.0
trl>=0.22.0
bitsandbytes
datasets
tensorboard
wandb
nvflare~=2.7.2rc
```

**CUDA/Driver:**
- CUDA 12.x recommended (for torch 2.7+)
- NVIDIA Driver: 525+

**Special Requirements:**
- **Git LFS:** Required for dataset downloads
- **HuggingFace Cache:** ~20GB for model downloads

**Test Commands:**

```bash
cd examples/advanced/llm_hf/

# Prepare datasets (requires Git LFS)
mkdir dataset
cd dataset
git clone https://huggingface.co/datasets/tatsu-lab/alpaca
git clone https://huggingface.co/datasets/databricks/databricks-dolly-15k
git clone https://huggingface.co/datasets/OpenAssistant/oasst1
cd ..

# Preprocess datasets
mkdir dataset/dolly
python ./utils/preprocess_dolly.py --training_file dataset/databricks-dolly-15k/databricks-dolly-15k.jsonl --output_dir dataset/dolly
python ./utils/preprocess_alpaca.py --training_file dataset/alpaca/data/train-00000-of-00001-a09b74b3ef9c3b56.parquet --output_dir dataset/alpaca
python ./utils/preprocess_oasst1.py --training_file dataset/oasst1/data/train-00000-of-00001-134b8fd0c89408b6.parquet --validation_file dataset/oasst1/data/validation-00000-of-00001-134b8fd0c89408b6.parquet --output_dir dataset/oasst1

# Test PEFT (Single GPU, lower VRAM)
python job.py \
    --dataset_name dolly \
    --sft_model hf_peft_model \
    --num_rounds 3 \
    --clients dolly \
    --workspace_dir ./workspace/dolly_fl_peft \
    --job_dir ./workspace/jobs/dolly_fl_peft

# Test SFT with Multi-GPU (if available)
python job.py \
    --dataset_name dolly,oasst1 \
    --sft_model hf_sft_model \
    --num_rounds 3 \
    --clients dolly,oasst1 \
    --gpu "[0,1],[2,3]" \
    --workspace_dir ./workspace/dolly_oasst1_fl_multi_gpu \
    --job_dir ./workspace/jobs/dolly_oasst1_fl_multi_gpu
```

**Expected Runtime:**
- **PEFT (Single GPU):** ~2-3 hours (3 rounds, 1 dataset)
- **SFT (Multi-GPU):** ~3-4 hours (3 rounds, 2 datasets)

**Success Criteria:**
- ✅ Datasets download and preprocess successfully
- ✅ GPT-Neo-1.3B model loads
- ✅ PEFT training completes with LoRA adapters
- ✅ Model streaming works (>2GB model size)
- ✅ Multi-GPU training works (if testing SFT)
- ✅ Final model shows improved loss/perplexity

---

### 6. BioNeMo (`examples/advanced/bionemo/`)

**Status:** NOT TESTED (too complex for current scope)  
**Purpose:** Test NVIDIA BioNeMo framework for drug discovery in federated setting

**Hardware Requirements:**
- **GPU:** 1+ NVIDIA GPU with 16GB+ VRAM
- **CPU:** 16+ cores
- **RAM:** 32GB+ system memory
- **Storage:** 100GB+ (for Docker images, models, datasets)

**Special Requirements:**
- **Docker:** Required (BioNeMo runs in Docker container)
- **BioNeMo Docker Image:** `nvcr.io/nvidia/clara/bionemo-framework:2.5`
- **Jupyter Lab:** Runs on port 8888
- **Specialized Datasets:** ESM-2 protein embeddings, domain-specific data

**Software Requirements:**
- Docker with NVIDIA Container Toolkit
- NGC CLI (for pulling BioNeMo container)
- BioNeMo Framework 2.5

**Why Complex:**
1. Requires Docker setup with GPU passthrough
2. Specialized biomedical datasets (not general-purpose)
3. ESM-2 pre-trained model expertise needed
4. Jupyter notebook-based workflow
5. Domain knowledge (protein embeddings, drug discovery)

**Recommendation:**
- **Priority:** LOW
- **Action:** Skip for general NVFlare 2.7 testing
- **Reason:** Highly specialized, requires domain expertise and custom datasets
- **Alternative:** If needed, work with BioNeMo specialists

---

## Cloud Provider Options

### AWS EC2 Instances

| Instance Type | GPUs | VRAM | vCPUs | RAM | Cost/Hour | Best For |
|--------------|------|------|-------|-----|-----------|----------|
| **g4dn.xlarge** | 1x T4 | 16GB | 4 | 16GB | ~$0.50 | Budget testing |
| **g5.2xlarge** | 1x A10G | 24GB | 8 | 32GB | ~$1.20 | Standard testing |
| **g5.12xlarge** | 4x A10G | 96GB | 48 | 192GB | ~$5.60 | Multi-GPU testing |
| **p3.2xlarge** | 1x V100 | 16GB | 8 | 61GB | ~$3.00 | LLM testing |
| **p4d.24xlarge** | 8x A100 | 320GB | 96 | 1.2TB | ~$32.00 | High-end LLM |

**Recommended for NVFlare Testing:** `g5.12xlarge` (4x A10G GPUs, can test all examples)

---

### Google Cloud Platform (GCP)

| Machine Type | GPUs | VRAM | vCPUs | RAM | Cost/Hour | Best For |
|-------------|------|------|-------|-----|-----------|----------|
| **n1-standard-8 + T4** | 1x T4 | 16GB | 8 | 30GB | ~$0.65 | Budget testing |
| **n1-standard-16 + 2xT4** | 2x T4 | 32GB | 16 | 60GB | ~$1.10 | Multi-GPU testing |
| **a2-highgpu-1g** | 1x A100 | 40GB | 12 | 85GB | ~$3.70 | LLM testing |
| **a2-highgpu-2g** | 2x A100 | 80GB | 24 | 170GB | ~$7.40 | High-end LLM |

**Recommended for NVFlare Testing:** `n1-standard-16 + 2xT4` (good balance)

---

### Azure

| VM Size | GPUs | VRAM | vCPUs | RAM | Cost/Hour | Best For |
|---------|------|------|-------|-----|-----------|----------|
| **NC6s_v3** | 1x V100 | 16GB | 6 | 112GB | ~$3.00 | Standard testing |
| **NC12s_v3** | 2x V100 | 32GB | 12 | 224GB | ~$6.00 | Multi-GPU testing |
| **NC24ads_A100_v4** | 1x A100 | 80GB | 24 | 220GB | ~$4.00 | LLM testing |
| **ND96asr_v4** | 8x A100 | 320GB | 96 | 900GB | ~$27.00 | High-end LLM |

**Recommended for NVFlare Testing:** `NC12s_v3` (2x V100, covers most examples)

---

## Testing Priority & Timeline

### Phase 1: High Priority (Do First)
**Goal:** Validate multi-GPU functionality  
**Examples:**
1. ✅ `multi-gpu/pt/` - PyTorch DDP
2. ✅ `multi-gpu/tf/` - TensorFlow MirroredStrategy

**Machine:** Option 1 (Standard GPU Testing)  
**Estimated Time:** 1-2 hours  
**Cost:** ~$2-4

---

### Phase 2: Medium Priority (Do Next)
**Goal:** Validate LLM capabilities  
**Examples:**
1. ✅ `tensor-stream/` - GPT-2 tensor streaming
2. ✅ `llm_hf/` - GPT-Neo-1.3B with PEFT

**Machine:** Option 2 (High-End LLM Testing) or Option 1 with PEFT only  
**Estimated Time:** 4-6 hours  
**Cost:** ~$15-30

---

### Phase 3: Low Priority (Skip or Defer)
**Examples:**
1. ⏸️ `multi-gpu/lightning/` - Wait for Lightning bug fix
2. ⏸️ `bionemo/` - Too specialized, skip

**Machine:** N/A  
**Estimated Time:** N/A

---

## Pre-Testing Checklist

Before leasing a remote machine, ensure:

### Software Setup
- [ ] Ubuntu 20.04 or 22.04 LTS
- [ ] CUDA toolkit installed (11.8+ or 12.x)
- [ ] NVIDIA driver (520+ or 525+)
- [ ] Docker + NVIDIA Container Toolkit (if testing BioNeMo)
- [ ] Python 3.9+
- [ ] Git + Git LFS

### Validation Commands
```bash
# Check GPU availability
nvidia-smi

# Check CUDA version
nvcc --version

# Check PyTorch GPU support
python -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA Available: {torch.cuda.is_available()}'); print(f'GPU Count: {torch.cuda.device_count()}')"

# Check TensorFlow GPU support
python -c "import tensorflow as tf; print(f'TensorFlow: {tf.__version__}'); print(f'GPU Devices: {tf.config.list_physical_devices(\"GPU\")}')"
```

### NVFlare Setup
```bash
# Clone repo (if not already)
git clone https://github.com/NVIDIA/NVFlare.git
cd NVFlare
git checkout 2.7  # or appropriate branch

# Create venv
python3.9 -m venv nvflare_2.7_test_env
source nvflare_2.7_test_env/bin/activate

# Install NVFlare (editable)
pip install -e .

# Verify installation
python -c "import nvflare; print(f'NVFlare: {nvflare.__version__}')"
```

---

## Post-Testing Deliverables

After completing tests, document:

1. **Test Results Summary:**
   - Example name
   - Pass/Fail status
   - Execution time
   - GPU utilization (from `nvidia-smi`)
   - Any errors encountered

2. **Performance Metrics:**
   - Training loss curves
   - Model accuracy/perplexity
   - Communication overhead
   - GPU memory usage

3. **Issues Found:**
   - Bug descriptions
   - Steps to reproduce
   - Proposed fixes (if any)

4. **Screenshots/Logs:**
   - Terminal output for each test
   - `nvidia-smi` output during training
   - Any error tracebacks

---

## Quick Reference Commands

```bash
# Check GPU status
nvidia-smi -l 1  # Refresh every second

# Monitor GPU during training
watch -n 1 nvidia-smi

# Check CUDA version
nvcc --version

# Test PyTorch multi-GPU
python -c "import torch; print(f'GPUs: {torch.cuda.device_count()}'); [print(f'GPU {i}: {torch.cuda.get_device_name(i)}') for i in range(torch.cuda.device_count())]"

# Test TensorFlow multi-GPU
python -c "import tensorflow as tf; gpus = tf.config.list_physical_devices('GPU'); print(f'GPUs: {len(gpus)}'); [print(gpu) for gpu in gpus]"

# Kill zombie processes
pkill -9 python

# Clean GPU memory
sudo fuser -v /dev/nvidia* | awk '{for(i=1;i<=NF;i++)print $i}' | xargs -n1 kill -9
```

---

## Summary

**Minimum Viable Machine for Most Testing:**
- 2x RTX 3090 (24GB VRAM each)
- 16 cores CPU
- 32GB RAM
- Ubuntu 22.04 + CUDA 12.x
- Estimated cost: $1-2/hour on cloud

**This configuration can test:**
- ✅ Multi-GPU PyTorch DDP
- ✅ Multi-GPU TensorFlow
- ✅ Tensor-Stream (with GPU acceleration)
- ⚠️ LLM HuggingFace PEFT (single GPU mode only)

**For full LLM testing (SFT + multi-GPU):**
- Upgrade to 2x RTX 6000 Ada (48GB) or 2x A100 (40GB)
- Estimated cost: $3-5/hour on cloud

**Total estimated testing time:** 6-8 hours  
**Total estimated cost:** $12-40 (depending on machine choice)
