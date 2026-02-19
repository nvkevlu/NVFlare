# BioNeMo Testing Setup Guide

**Date:** January 26, 2026  
**NVFlare Branch:** 2.7 (latest)  
**Status:** READY TO TEST

---

## Quick Links

### 1. Setup Script
**Location:** [`cursor_outputs/testing/remote_scripts/setup_bionemo.sh`](remote_scripts/setup_bionemo.sh)

**What it does:**
- ✅ Updates NVFlare to latest 2.7 branch (includes BioNeMo timeout fix #4057)
- ✅ Verifies Docker + NVIDIA Container Toolkit
- ✅ Pulls BioNeMo Docker image (nvcr.io/nvidia/clara/bionemo-framework:2.5)
- ✅ Uses existing `nvflare_env` venv (editable install, created by remote_setup.sh)
- ✅ Prepares example directory

---

### 2. All Remote Scripts & Documentation
**Location:** [`cursor_outputs/testing/remote_scripts/README.md`](remote_scripts/README.md)

**Contains:**
- Complete script inventory
- Usage instructions
- Troubleshooting guide
- Expected outputs

---

### 3. Hardware Requirements
**Location:** [`cursor_outputs/testing/REMOTE_TESTING_REQUIREMENTS.md`](REMOTE_TESTING_REQUIREMENTS.md)

**BioNeMo Requirements (Section 6):**
- GPU: 1+ NVIDIA GPU with 16GB+ VRAM
- RAM: 32GB+ system memory
- Storage: 100GB+ (for Docker images)
- Special: Docker + NGC credentials

---

## Usage on Remote Machine

### Step 1: Transfer Script
```bash
# On local machine
cd /Users/kevlu/workspace/repos/secondcopynvflare/cursor_outputs/testing/remote_scripts/
scp setup_bionemo.sh local-kevlu@ipp1-1125:~/
```

### Step 2: Run Setup
```bash
# SSH to remote
ssh local-kevlu@ipp1-1125

# Make executable
chmod +x setup_bionemo.sh

# Run setup (interactive, ~15-30 minutes)
./setup_bionemo.sh
```

**What happens:**
1. Shows new commits on 2.7 branch
2. Prompts to merge latest changes
3. Activates existing venv
4. Checks Docker installation
5. Pulls BioNeMo image (~10GB download)
6. Verifies GPU availability

### Step 3: Start BioNeMo Container
```bash
cd ~/nvflare_testing/NVFlare/examples/advanced/bionemo
./start_bionemo.sh
```

**Result:**
- Jupyter Lab starts on http://localhost:8888
- All GPUs available inside container
- NVFlare code mounted at `/bionemo_nvflare_examples`

### Step 4: Run Notebook
Inside Jupyter:
- Open: `protein_property_prediction_with_bionemo.ipynb`
- Follow notebook instructions
- Test federated protein property prediction

---

## What's Different from Other Tests

### Advantages of This Approach:
1. **Uses existing venv** - No need to recreate environment (uses `nvflare_env` from remote_setup.sh)
2. **Editable NVFlare install** - Automatically uses updated code after 2.7 merge
3. **Docker-based** - Isolated BioNeMo environment
4. **Interactive** - Prompts for confirmation before merging 2.7 changes

### What's NOT Automated:
- **Datasets** - BioNeMo requires specialized datasets (ESM-2 protein embeddings)
- **Testing** - Jupyter notebook-based, requires manual execution
- **Domain knowledge** - Drug discovery context helpful

---

## Latest 2.7 Updates Included

The setup script will fetch these recent commits:
```
e77f7549 [2.7] Updates to notebooks (#4066)
e3e923d5 Fix the rest of the examples (#4039)
9044d44c [2.7] Update info logging of Cacheable (#4062)
528a3de4 [2.7] update GNN readme (#4065)
db54d078 [2.7] Update Edge for Android (#4064)
1482dfa4 [2.7] Increase BioNeMo external script init timeout (#4057) ⭐
a3b0aefe [2.7] increase link check timout (#4060)
fbc06b45 Fixed keycloak docker tag (#4058)
b82ed627 [2.7] Update custom authentication example (#4055)
ef72c8f9 [2.7] Move monai examples under advanced (#4053)
```

**Key fix for BioNeMo:** #4057 increases initialization timeout

---

## Venv Strategy: Same vs New

### Using SAME venv (nvflare_env) ✅ RECOMMENDED
**Pros:**
- Already has all dependencies installed
- NVFlare is editable install (`pip install -e .`)
- After updating 2.7 branch, code changes are immediately active
- No reinstallation needed

**Cons:**
- None (this is the correct approach for editable installs)

### Creating NEW venv ❌ NOT NEEDED
**Pros:**
- Clean slate

**Cons:**
- Must reinstall everything (~15 minutes)
- Wastes time
- Same result (since dependencies unchanged)

**Verdict:** Use existing venv, as the setup script does.

---

## Expected Output from setup_bionemo.sh

```bash
==================================================
BioNeMo Testing Setup for NVFlare 2.7
==================================================

[1/5] Updating NVFlare to latest 2.7 branch...
  - Fetching from origin (NVIDIA/NVFlare)...
  
  📊 New commits on 2.7:
  e77f7549 [2.7] Updates to notebooks (#4066)
  e3e923d5 Fix the rest of the examples (#4039)
  1482dfa4 [2.7] Increase BioNeMo external script init timeout (#4057)
  ...
  
  Merge latest 2.7 changes? (y/n): y
  ✅ Updated to latest 2.7
  
  📍 Current commit:
  e77f7549 [2.7] Updates to notebooks (#4066)

[2/5] Activating Python venv: nvflare_env...
  - NVFlare version:
    2.7.2rc+10.ge77f7549

[3/5] Checking Docker installation...
  - Docker version:
Docker version 24.0.7, build afdd53b
  
  - Checking NVIDIA Container Toolkit...
    ✅ NVIDIA Container Toolkit working

[4/5] Pulling BioNeMo Docker image: nvcr.io/nvidia/clara/bionemo-framework:2.5...
  (This may take 10-20 minutes for first download, ~10GB image)

2.5: Pulling from nvidia/clara/bionemo-framework
...
Status: Downloaded newer image for nvcr.io/nvidia/clara/bionemo-framework:2.5
  ✅ BioNeMo image ready

[5/5] Preparing BioNeMo example directory...
  - BioNeMo directory: ~/nvflare_testing/NVFlare/examples/advanced/bionemo
  - Files:
-rwxr-xr-x 1 user user 421 Jan 26 10:00 start_bionemo.sh
  
  - GPU Status:
index, name, memory.total [MiB]
0, NVIDIA A30, 24576
1, NVIDIA A30, 24576

==================================================
✅ BioNeMo Setup Complete!
==================================================

📋 Summary:
  - NVFlare Branch: 2.7 (latest)
  - Venv: nvflare_env
  - Docker Image: nvcr.io/nvidia/clara/bionemo-framework:2.5
  - Working Directory: ~/nvflare_testing/NVFlare/examples/advanced/bionemo

🚀 Next Steps:

  1. Review BioNeMo example requirements:
     cat ~/nvflare_testing/NVFlare/examples/advanced/bionemo/README.md

  2. Start BioNeMo Docker container:
     cd ~/nvflare_testing/NVFlare/examples/advanced/bionemo
     ./start_bionemo.sh

  3. Inside container, run Jupyter notebook:
     - Notebook will be at: http://localhost:8888
     - Follow protein_property_prediction_with_bionemo.ipynb

  4. For automated testing, prepare datasets first:
     - ESM-2 protein embeddings
     - Domain-specific protein data

==================================================

⚠️  BioNeMo Notes:
  - Requires specialized datasets (not included)
  - Jupyter notebook-based workflow
  - Domain expertise helpful (drug discovery)
  - Test complexity: HIGH

💡 Alternative: Test simpler examples first
   (multi-gpu, tensor-stream, llm_hf)
```

---

## Troubleshooting

### Issue: Docker pull fails
**Solution:** Check NGC credentials
```bash
docker login nvcr.io
# Username: $oauthtoken
# Password: <Your NGC API Key>
```

### Issue: NVIDIA Container Toolkit not working
**Solution:** Install toolkit
```bash
# Ubuntu
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

### Issue: Port 8888 already in use
**Solution:** Change Jupyter port in start_bionemo.sh
```bash
# Edit start_bionemo.sh, add port mapping:
docker run ... -p 8889:8888 ...
# Then access: http://localhost:8889
```

---

## What's Next After BioNeMo Setup?

Once setup is complete:

1. **Manual Testing** (Jupyter notebook):
   - Follow protein_property_prediction_with_bionemo.ipynb
   - Test federated drug discovery workflow
   - Document results

2. **Alternative Simpler Tests** (if BioNeMo too complex):
   - Run `test_tensor_stream.sh` (GPT-2 LLM, ~1-2 hours)
   - Run `test_llm_hf.sh` (HuggingFace PEFT, ~2-3 hours)
   - These don't require specialized datasets

3. **Report Findings:**
   - Does BioNeMo container start correctly?
   - Are GPUs visible inside container?
   - Does notebook load without errors?
   - Any timeout issues? (should be fixed by #4057)

---

## Files Created

| File | Purpose | Location |
|------|---------|----------|
| **setup_bionemo.sh** | Main setup script | `cursor_outputs/testing/remote_scripts/` |
| **README.md** (updated) | Script documentation | `cursor_outputs/testing/remote_scripts/` |
| **BIONEMO_SETUP_GUIDE.md** | This guide | `cursor_outputs/testing/` |

---

## Summary

✅ **Ready to use:** Transfer `setup_bionemo.sh` to remote and run  
✅ **Includes 2.7 update:** Latest branch with BioNeMo timeout fix  
✅ **Uses existing venv:** No reinstallation needed  
✅ **Docker-based:** Clean BioNeMo environment  
✅ **Well-documented:** Clear instructions and troubleshooting  

**Estimated time:** 15-30 minutes for setup + manual testing time

**Priority:** LOW (consider simpler examples first)
