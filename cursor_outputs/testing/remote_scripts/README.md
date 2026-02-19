# NVFlare Remote Testing Scripts

**Purpose:** Automated setup and testing scripts for NVFlare 2.7 Multi-GPU examples on remote machines.

**Target Machine:**
- Username: local-kevlu
- Host: ipp1-1125 (10.117.8.61)
- GPUs: 2x NVIDIA A30 (24GB VRAM each)
- OS: Ubuntu 24.04

---

## Quick Start

### Step 1: Transfer Scripts to Remote Machine

From your **local machine** (in the NVFlare repo directory):

```bash
# Navigate to scripts directory
cd cursor_outputs/testing/remote_scripts/

# Copy all scripts to remote
scp verify_env.sh remote_setup.sh run_multi_gpu_tests.sh local-kevlu@ipp1-1125:~/
```

### Step 2: SSH into Remote Machine

```bash
ssh local-kevlu@ipp1-1125
```

### Step 3: Run Scripts on Remote Machine

```bash
# Make scripts executable
chmod +x verify_env.sh remote_setup.sh run_multi_gpu_tests.sh

# 1. Verify environment (check GPUs, CUDA, etc.)
./verify_env.sh

# 2. Setup NVFlare environment (~10-15 minutes)
./remote_setup.sh

# 3. Run Multi-GPU tests (~1 hour)
./run_multi_gpu_tests.sh
```

---

## Script Descriptions

### 1. `verify_env.sh`
**Purpose:** Verify remote machine has required hardware/software  
**Runtime:** ~5 seconds  
**Checks:**
- GPU availability (nvidia-smi)
- CUDA installation
- Python version
- System RAM (32GB+ recommended)
- Disk space
- Git installation

**Example Output:**
```
=== GPU Check ===
NVIDIA A30, 24576 MiB
NVIDIA A30, 24576 MiB
✅ Found 2 GPU(s)

=== CUDA Check ===
✅ CUDA 12.1 detected

=== Python Check ===
✅ Python 3.11.8 found

=== System Resources ===
CPU Cores: 64
Total RAM: 251Gi
Available RAM: 240Gi
✅ Sufficient RAM (251Gi)
```

---

### 2. `remote_setup.sh`
**Purpose:** Complete NVFlare environment setup  
**Runtime:** ~10-15 minutes  
**Actions:**
1. Creates work directory (`~/nvflare_testing/`)
2. Clones NVFlare repository from GitHub
3. Creates Python virtual environment
4. Installs NVFlare in editable mode
5. Installs PyTorch with CUDA support
6. Installs TensorFlow with GPU support
7. Verifies installations
8. Creates logs and results directories
9. Saves environment info

**Directory Structure Created:**
```
~/nvflare_testing/
├── nvflare_env/           # Virtual environment
├── NVFlare/               # Cloned repository
├── logs/                  # Test logs
├── results/               # Test results
├── activate.sh            # Quick activation script
└── environment_info.txt   # Environment details
```

**Example Output:**
```
📦 Cloning NVFlare repository...
🐍 Detecting Python...
Using: Python 3.11.8
🔨 Creating virtual environment...
📥 Installing NVFlare (editable mode)...
🔥 Installing PyTorch with CUDA support...
🔍 Verifying PyTorch CUDA support...
PyTorch version: 2.5.1+cu121
CUDA available: True
GPU count: 2

✅ Setup Complete!
```

---

### 3. `run_multi_gpu_tests.sh`
**Purpose:** Run all Multi-GPU tests  
**Runtime:** ~1 hour total  
**Tests:**
1. **PyTorch DDP** (`examples/advanced/multi-gpu/pt/`)
   - Uses DistributedDataParallel
   - CIFAR-10 dataset
   - 5 rounds, 2 clients
   - ~20-30 minutes

2. **TensorFlow MirroredStrategy** (`examples/advanced/multi-gpu/tf/`)
   - Uses MirroredStrategy
   - CIFAR-10 dataset
   - 5 rounds, 2 clients
   - ~20-30 minutes

**Example Output:**
```
========================================
Test 1/2: PyTorch DDP Multi-GPU
========================================

📁 Working directory: .../multi-gpu/pt
📦 Installing dependencies...
📥 Preparing CIFAR-10 dataset...
🚀 Running PyTorch DDP test...

✅ PyTorch DDP test PASSED (1456s)

========================================
Test 2/2: TensorFlow MirroredStrategy
========================================

✅ TensorFlow MirroredStrategy test PASSED (1523s)

========================================
📊 Test Summary:
   Total: 2
   Passed: 2
   Failed: 0

🎉 All tests PASSED!
```

**Logs Generated:**
- `~/nvflare_testing/logs/test_run_TIMESTAMP.log` - Main log
- `~/nvflare_testing/logs/multi-gpu-pytorch-ddp_TIMESTAMP.log` - PyTorch test log
- `~/nvflare_testing/logs/multi-gpu-tensorflow_TIMESTAMP.log` - TensorFlow test log

**Results Saved:**
- `~/nvflare_testing/results/multi-gpu-pytorch-ddp_TIMESTAMP/` - PyTorch results
- `~/nvflare_testing/results/multi-gpu-tensorflow_TIMESTAMP/` - TensorFlow results
- `~/nvflare_testing/results/test_summary_TIMESTAMP.txt` - Summary report

---

### 4. `test_bionemo.sh` 🆕 RECOMMENDED
**Purpose:** Run BioNeMo federated learning test (no Jupyter needed)  
**Runtime:** ~10-30 minutes  
**Example:** `examples/advanced/bionemo/downstream/sabdab/`

**What it tests:**
- ESM2 protein model federated fine-tuning
- Antibody binding classification (SAbDab dataset)
- BioNeMo integration with NVFlare Recipe API
- External process launch with Docker

**Usage:**
```bash
./test_bionemo.sh
```

**Advantages:**
- ✅ No network/Jupyter required (runs locally in Docker)
- ✅ Fully automated with logging
- ✅ Same pattern as other test scripts

**Expected Output:**
```
[INFO] Running BioNeMo federated training...
Downloaded 8m to /root/.cache/bionemo/esm2/8m_2.0
Job Status is: FINISHED:COMPLETED
🎉 BioNeMo test PASSED! (Duration: 20 minutes)
```

**See also:** `cursor_outputs/testing/BIONEMO_SCRIPTED_TEST.md`

---

### 4b. `setup_bionemo.sh` (ALTERNATIVE - Jupyter-based, has network issues)
**Purpose:** Setup BioNeMo Jupyter environment  
**Runtime:** ~15-30 minutes  
**Example:** `examples/advanced/bionemo/`

**NOTE:** This approach requires accessing Jupyter on port 8888, which may be blocked by firewalls. **Use `test_bionemo.sh` instead** for automated testing.

**What it does:**
1. Updates NVFlare to latest 2.7 branch
2. Verifies Docker + NVIDIA Container Toolkit
3. Pulls BioNeMo Docker image (~10GB)
4. Prepares BioNeMo example directory
5. Uses existing venv (editable NVFlare install)

**Usage:**
```bash
./setup_bionemo.sh
```

**Prerequisites:**
- Docker installed with NVIDIA Container Toolkit
- NGC credentials for pulling BioNeMo image
- 16GB+ GPU VRAM recommended
- 100GB+ free disk space (for Docker image)

**Example Output:**
```
==================================================
BioNeMo Testing Setup for NVFlare 2.7
==================================================

[1/5] Updating NVFlare to latest 2.7 branch...
  📊 New commits on 2.7:
  e77f7549 [2.7] Updates to notebooks (#4066)
  1482dfa4 [2.7] Increase BioNeMo external script init timeout (#4057)
  
[2/5] Activating Python venv: nvflare_env...
  - NVFlare version: 2.7.2rc

[3/5] Checking Docker installation...
  - Docker version: 24.0.7
  ✅ NVIDIA Container Toolkit working

[4/5] Pulling BioNeMo Docker image...
  ✅ BioNeMo image ready

[5/5] Preparing BioNeMo example directory...
  - GPU Status: 2x NVIDIA A30 (24GB each)

✅ BioNeMo Setup Complete!

🚀 Next Steps:
  1. Start BioNeMo Docker container: ./start_bionemo.sh
  2. Access Jupyter at http://localhost:8888
  3. Follow notebook: protein_property_prediction_with_bionemo.ipynb
```

**Notes:**
- BioNeMo requires specialized datasets (ESM-2 protein embeddings)
- Jupyter notebook-based workflow
- Domain knowledge helpful (drug discovery, protein modeling)
- **Test complexity: HIGH** (consider simpler examples first)

---

### 5. `test_tensor_stream.sh`
**Purpose:** Test Tensor Streaming with GPT-2 LLM  
**Runtime:** ~1-2 hours  
**Example:** `examples/advanced/tensor-stream/`

**What it tests:**
- Large tensor streaming (~620MB GPT-2 model)
- LLM fine-tuning in federated setting
- Efficient tensor communication
- HuggingFace transformers + datasets integration

**Features:**
- Pre-downloads IMDB dataset (`stanfordnlp/imdb`)
- Pre-downloads GPT-2 model to avoid timeout
- Monitors GPU usage every 60 seconds
- Shows training progress in real-time
- 2-hour timeout protection

**Usage:**
```bash
./test_tensor_stream.sh
```

**Example Output:**
```
==========================================
Tensor Streaming Test with GPT-2 LLM
==========================================

[INFO] Verifying NVFlare installation...
[SUCCESS] NVFlare version: 2.7.1+87.g7dc1cfcb

[INFO] GPU Status:
index, name, utilization.gpu [%], memory.used [MiB], memory.total [MiB]
0, NVIDIA A30, 0 %, 0 MiB, 24576 MiB
1, NVIDIA A30, 0 %, 0 MiB, 24576 MiB

[INFO] Pre-downloading IMDB dataset (stanfordnlp/imdb)...
[SUCCESS] Dataset pre-loaded successfully

[INFO] Pre-downloading GPT-2 model...
[SUCCESS] GPT-2 model pre-loaded successfully

[INFO] Starting Tensor Streaming Test
[INFO] This will take approximately 1-2 hours
[INFO] Monitor progress: tail -f ~/nvflare_testing/logs/tensor-stream_TIMESTAMP.log

[INFO] Test running for 15 minutes...
[INFO] Recent activity:
                Round 1 started.
loss: 2.351
Accuracy: 52.3%

...

[SUCCESS] ✅ Tensor Streaming test PASSED!
==========================================
[INFO] Duration: 87 minutes
[INFO] Rounds: 5
🎉 Tensor Streaming test completed successfully!
```

**Logs Generated:**
- `~/nvflare_testing/logs/tensor-stream_TIMESTAMP.log` - Complete test log

**Results Saved:**
- `~/nvflare_testing/results/tensor-stream_TIMESTAMP/summary.txt` - Test summary
- `~/nvflare_testing/results/tensor-stream_TIMESTAMP/tensor_stream/` - Simulation results

---

## Using Screen/Tmux (Recommended for Long Tests)

Since tests take ~1 hour, use `screen` or `tmux` to avoid disconnection issues:

### Using Screen:

```bash
# Start a screen session
screen -S nvflare_tests

# Run tests
./run_multi_gpu_tests.sh

# Detach from screen: Press Ctrl-A, then D

# Reattach later
screen -r nvflare_tests

# View all screen sessions
screen -ls
```

### Using Tmux:

```bash
# Start a tmux session
tmux new -s nvflare_tests

# Run tests
./run_multi_gpu_tests.sh

# Detach from tmux: Press Ctrl-B, then D

# Reattach later
tmux attach -t nvflare_tests

# View all tmux sessions
tmux ls
```

---

## Monitoring Progress from Local Machine

You can monitor test progress without SSH'ing into the machine:

```bash
# Watch main log in real-time
ssh local-kevlu@ipp1-1125 "tail -f ~/nvflare_testing/logs/test_run_*.log"

# Check GPU utilization
ssh local-kevlu@ipp1-1125 "nvidia-smi"

# Check if tests are still running
ssh local-kevlu@ipp1-1125 "ps aux | grep python"
```

---

## Quick Activation (After Setup)

After initial setup, to quickly activate the environment:

```bash
source ~/nvflare_testing/activate.sh
```

This script:
- Activates the virtual environment
- Changes to NVFlare directory
- Shows Python version
- Shows current directory

---

## Troubleshooting

### Issue: GPU Not Found
```bash
# Check if GPUs are visible
nvidia-smi

# Check CUDA
nvcc --version

# Check PyTorch CUDA
source ~/nvflare_testing/nvflare_env/bin/activate
python -c "import torch; print(torch.cuda.is_available())"
```

### Issue: Out of Memory
```bash
# Check GPU memory usage
nvidia-smi

# Kill zombie processes
pkill -9 python

# Clear CUDA cache
python -c "import torch; torch.cuda.empty_cache()"
```

### Issue: Test Hangs
```bash
# Check running processes
ps aux | grep python

# Check logs for errors
tail -100 ~/nvflare_testing/logs/*.log

# Kill hung process
pkill -9 -f "job.py"
```

### Issue: Port Already in Use (PyTorch DDP)
The test scripts handle this automatically, but if needed:
```bash
# Check what's using a port
lsof -i :29500

# Kill process using port
kill -9 <PID>
```

---

## Cleaning Up After Tests

```bash
# Clean temporary files
rm -rf /tmp/nvflare/

# Clean old logs (keep last 5 runs)
cd ~/nvflare_testing/logs/
ls -t | tail -n +6 | xargs rm -f

# Clean old results (keep last 3 runs)
cd ~/nvflare_testing/results/
ls -t | tail -n +4 | xargs rm -rf
```

---

## Expected Test Results

### Success Criteria:

**PyTorch DDP:**
- ✅ 2 GPUs detected and used
- ✅ DDP processes spawn correctly
- ✅ CIFAR-10 dataset downloads
- ✅ 5 rounds complete
- ✅ Final accuracy >50%
- ✅ No NCCL errors
- ✅ Clean shutdown

**TensorFlow MirroredStrategy:**
- ✅ 2 GPUs detected and used
- ✅ MirroredStrategy initializes
- ✅ CIFAR-10 dataset downloads
- ✅ 5 rounds complete
- ✅ Final accuracy >50%
- ✅ GPU memory properly distributed
- ✅ Clean shutdown

---

## Next Steps After Multi-GPU Tests

If Multi-GPU tests pass, you can test additional examples:

1. **Tensor-Stream (LLM)** - Your A30s have enough VRAM (24GB each)
2. **LLM HuggingFace PEFT** - 24GB is sufficient for PEFT mode
3. **LLM HuggingFace SFT (Multi-GPU)** - Can use both A30s

Let me know when Multi-GPU tests complete, and I can create scripts for the next phase!

---

## Available Scripts Summary

| Script | Purpose | Runtime | Prerequisites |
|--------|---------|---------|---------------|
| `verify_env.sh` | Check GPU/CUDA/Python | ~5 seconds | None |
| `remote_setup.sh` | Full NVFlare environment setup | ~10-15 min | verify_env.sh passed |
| `run_multi_gpu_tests.sh` | PyTorch DDP + TensorFlow tests | ~1 hour | remote_setup.sh completed |
| `test_bionemo.sh` 🆕 | BioNeMo ESM2 federated learning | ~10-30 min | Docker, NGC (no Jupyter!) |
| `setup_bionemo.sh` | BioNeMo Jupyter setup (alternative) | ~15-30 min | Docker, NGC credentials |
| `test_tensor_stream.sh` | GPT-2 LLM tensor streaming | ~1-2 hours | remote_setup.sh completed |
| `test_llm_hf.sh` | HuggingFace LLM PEFT/SFT | ~2-3 hours | remote_setup.sh, Git LFS |
| `test_lightning_ddp.sh` | PyTorch Lightning DDP | ~30 min | remote_setup.sh (has known bug) |
| `test_tensorflow_multi_gpu.sh` | TensorFlow standalone test | ~30 min | setup_tf_venv.sh |

---

## Summary of Commands

### Standard Multi-GPU Testing:
```bash
# === ON LOCAL MACHINE ===
cd cursor_outputs/testing/remote_scripts/
scp *.sh local-kevlu@ipp1-1125:~/

# === ON REMOTE MACHINE ===
ssh local-kevlu@ipp1-1125

# Make executable
chmod +x *.sh

# Run tests (in screen session recommended)
screen -S nvflare_tests
./verify_env.sh
./remote_setup.sh
./run_multi_gpu_tests.sh

# Detach: Ctrl-A, D
# Reattach: screen -r nvflare_tests
```

### BioNeMo Testing (NEW - Automated):
```bash
# === ON REMOTE MACHINE ===
ssh local-kevlu@ipp1-1125

# Run BioNeMo test (fully automated, no Jupyter needed)
./test_bionemo.sh
```

### BioNeMo Testing (ALTERNATIVE - Jupyter):
```bash
# === ON REMOTE MACHINE ===
ssh local-kevlu@ipp1-1125

# Setup and start Jupyter (requires network access to port 8888)
./setup_bionemo.sh
cd ~/nvflare_testing/NVFlare/examples/advanced/bionemo
./start_bionemo.sh
# Access Jupyter at http://localhost:8888 (may be blocked by firewall)
```

**Total estimated time:**
- Standard tests: ~1.5 hours
- BioNeMo test (scripted): ~10-30 minutes
- BioNeMo Jupyter setup: ~30 minutes + manual testing time
