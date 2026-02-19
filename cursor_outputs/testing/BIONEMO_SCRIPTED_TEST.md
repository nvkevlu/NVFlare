# BioNeMo Scripted Test (No Jupyter Required)

**Date:** January 30, 2026  
**Purpose:** Run BioNeMo federated learning tests as a standalone script without Jupyter notebooks

---

## Quick Start

### Transfer Script to Remote:
```bash
# On local machine
cd /Users/kevlu/workspace/repos/secondcopynvflare/cursor_outputs/testing/remote_scripts/
scp test_bionemo.sh local-kevlu@ipp1-1125:~/
```

### Run Test on Remote:
```bash
# SSH to remote
ssh local-kevlu@ipp1-1125

# Make executable
chmod +x test_bionemo.sh

# Run test
./test_bionemo.sh
```

---

## What This Script Does

Unlike `setup_bionemo.sh` which starts Jupyter, this script:

1. ✅ **Runs BioNeMo job directly** inside Docker container
2. ✅ **No Jupyter needed** - executes `job.py` directly
3. ✅ **No network access needed** - all runs locally
4. ✅ **Follows same pattern** as other test scripts (test_tensor_stream.sh, test_llm_hf.sh)
5. ✅ **Produces logs** - saves output to `~/nvflare_testing/logs/`
6. ✅ **Reports results** - shows pass/fail status

---

## Test Configuration

**Default Settings:**
- **Task:** SAbDab (antibody binding classification)
- **Model:** ESM2-8m (smallest, fastest)
- **Clients:** 2
- **Rounds:** 3
- **Local steps:** 10 per round
- **Expected runtime:** 10-30 minutes

**Why SAbDab/8m:**
- Smallest dataset (fastest to download)
- Smallest model (lowest memory)
- Binary classification (simplest task)
- Good for smoke testing BioNeMo integration

---

## What Gets Tested

This script verifies:
1. ✅ BioNeMo Docker container launches
2. ✅ GPUs accessible inside container
3. ✅ ESM2 model downloads successfully
4. ✅ NVFlare Recipe API works with BioNeMo
5. ✅ Federated training completes all rounds
6. ✅ Custom filters (BioNeMoParamsFilter, BioNeMoStateDictFilter) work
7. ✅ External process launch works
8. ✅ Results saved correctly

---

## Expected Output

```bash
==========================================
BioNeMo Federated Learning Test
==========================================

[INFO] Test started: Thu Jan 30 18:00:00 UTC 2026
[INFO] Configuration:
  - Task: sabdab (SAbDab antibody binding)
  - Model: ESM2-8m
  - Clients: 2
  - Rounds: 3
  - Local steps: 10
  - Docker image: nvcr.io/nvidia/clara/bionemo-framework:2.5

[INFO] Step 1/5: Verifying prerequisites...
[INFO] GPU Status:
index, name, memory.total [MiB]
0, NVIDIA A30, 24576
1, NVIDIA A30, 24576

[INFO] Step 2/5: Preparing BioNeMo example...
[INFO] Task directory: .../bionemo/downstream/sabdab
[INFO] Job script: .../bionemo/downstream/sabdab/job.py

[INFO] Step 3/5: Running BioNeMo federated training...
[INFO] This will take approximately 10-30 minutes depending on GPU
[INFO] Starting Docker container...

Downloaded 8m to /root/.cache/bionemo/esm2/8m_2.0
...
Job Status is: FINISHED:COMPLETED
Result can be found in : /tmp/nvflare/bionemo/sabdab/...

[INFO] Docker container finished (exit code: 0)
[INFO] Duration: 1234s (20 minutes)

[INFO] Step 4/5: Checking results...
[INFO] Job Status is: FINISHED:COMPLETED

[INFO] Step 5/5: Test Summary

==========================================
📊 BioNeMo Test Results
==========================================

✅ Test completed in 1234s (20 minutes)

Configuration:
  - Task: sabdab (antibody binding classification)
  - Model: ESM2-8m
  - Clients: 2
  - Rounds: 3
  - Steps per round: 10

Logs:
  - Test log: ~/nvflare_testing/logs/bionemo_20260130_180000.log
  - NVFlare results: /tmp/nvflare/bionemo/sabdab/

==========================================
🎉 BioNeMo test PASSED!
==========================================
```

---

## Customization

Edit the script to test different configurations:

```bash
nano test_bionemo.sh

# Change these variables (around line 15):
TASK="sabdab"      # Options: sabdab, tap, scl
MODEL="8m"         # Options: 8m, 650m, 3b
NUM_CLIENTS=2
NUM_ROUNDS=3
LOCAL_STEPS=10
```

### Available Tasks:

| Task | Description | Dataset | Classes |
|------|-------------|---------|---------|
| **sabdab** | Antibody binding | Binary | pos/neg |
| **tap** | Thermostability | Regression | Multiple endpoints |
| **scl** | Subcellular location | Multi-class | 10 classes |

### Available Models:

| Model | Parameters | VRAM | Speed |
|-------|-----------|------|-------|
| **8m** | 8 million | ~2GB | Fast |
| **650m** | 650 million | ~8GB | Medium |
| **3b** | 3 billion | ~16GB | Slow |

---

## Comparison: Jupyter vs Script

### Original Jupyter Approach:
```bash
./setup_bionemo.sh         # My setup script
./start_bionemo.sh         # Starts Jupyter
# Access http://localhost:8888
# Run notebook interactively
```

**Problems:**
- ❌ Requires network access to Jupyter
- ❌ Firewall blocks port 8888
- ❌ SSH port forwarding disabled
- ❌ Interactive, can't automate

### New Script Approach:
```bash
./test_bionemo.sh          # Single script
# Runs to completion
# Logs all output
# Reports pass/fail
```

**Benefits:**
- ✅ No network access needed
- ✅ No Jupyter required
- ✅ Fully automated
- ✅ Follows same pattern as other tests
- ✅ Easy to integrate into CI/CD

---

## Troubleshooting

### Issue: Docker image not found
**Solution:** Script will auto-pull, but you can pre-pull:
```bash
docker pull nvcr.io/nvidia/clara/bionemo-framework:2.5
```

### Issue: GPU not accessible
**Solution:** Check NVIDIA Container Toolkit:
```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

### Issue: Out of memory
**Solution:** Use smaller model or fewer clients:
```bash
# Edit test_bionemo.sh:
MODEL="8m"         # Not 650m or 3b
NUM_CLIENTS=1      # Not 2
```

### Issue: Download timeout
**Solution:** ESM2 model downloads from HuggingFace. If slow:
```bash
# Pre-download inside container:
docker run --rm -it --gpus all \
  -v ~/.cache:/root/.cache \
  nvcr.io/nvidia/clara/bionemo-framework:2.5 \
  python3 -c "from bionemo.core.data.load import load; load('esm2/8m:2.0')"
```

### Issue: Test hangs
**Solution:** Check logs for details:
```bash
tail -f ~/nvflare_testing/logs/bionemo_*.log
```

---

## Files Generated

| File | Location | Purpose |
|------|----------|---------|
| **test_bionemo.sh** | `~/test_bionemo.sh` | Main test script |
| **Test log** | `~/nvflare_testing/logs/bionemo_TIMESTAMP.log` | Complete output |
| **NVFlare results** | `/tmp/nvflare/bionemo/sabdab/` | Simulation workspace |
| **Model cache** | `~/.cache/bionemo/` | Downloaded ESM2 models |

---

## Integration with Other Tests

This script follows the same pattern as:
- `test_tensor_stream.sh`
- `test_llm_hf.sh`
- `test_lightning_ddp.sh`
- `test_tensorflow_multi_gpu.sh`

You can run them all sequentially:
```bash
./test_tensor_stream.sh
./test_llm_hf.sh
./test_bionemo.sh
# etc.
```

---

## Advantages Over Jupyter

| Aspect | Jupyter | Script |
|--------|---------|--------|
| **Network** | Required | Not required |
| **Automation** | Manual | Fully automated |
| **Logging** | Manual save | Auto-logged |
| **CI/CD** | Difficult | Easy |
| **Monitoring** | Interactive | Log files |
| **Reproducibility** | Low | High |

---

## Summary

✅ **Script created:** `test_bionemo.sh`  
✅ **No Jupyter needed:** Runs `job.py` directly in Docker  
✅ **No network access needed:** All local execution  
✅ **Automated:** Run and check results  
✅ **Logged:** Complete output saved  

**Usage:**
```bash
scp test_bionemo.sh local-kevlu@ipp1-1125:~/
ssh local-kevlu@ipp1-1125
chmod +x test_bionemo.sh
./test_bionemo.sh
```

**Expected runtime:** 10-30 minutes  
**Expected result:** BioNeMo federated learning completes successfully
