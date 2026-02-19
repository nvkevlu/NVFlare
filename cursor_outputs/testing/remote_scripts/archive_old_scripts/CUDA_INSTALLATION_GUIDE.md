# CUDA Installation Guide for Remote Testing

**Situation:** Your remote machine has NVIDIA A30 GPUs with drivers installed (nvidia-smi works), but the CUDA toolkit (nvcc) is not installed.

**Good News:** You have 3 options, with **Option 2** being the fastest and easiest!

---

## Option 1: Skip System CUDA (Recommended - Fastest!)

**Why this works:**
- PyTorch and TensorFlow bundle their own CUDA libraries
- You don't need system-wide CUDA toolkit for testing
- No sudo required
- No reboot required

**Steps:**

```bash
# Just run the setup script as-is!
./remote_setup.sh
```

The script will install PyTorch and TensorFlow with bundled CUDA support. This is sufficient for NVFlare testing.

**Pros:**
- ✅ Fastest (no additional installation)
- ✅ No sudo required
- ✅ No reboot required
- ✅ Works for 99% of use cases

**Cons:**
- ⚠️ `nvcc` command won't be available (but not needed for testing)
- ⚠️ Can't compile CUDA code (but we're not doing that)

---

## Option 2: Install CUDA via Conda (Recommended if Option 1 fails)

**Best for:** No sudo access, want complete CUDA toolkit

**Steps:**

1. **Transfer the new script:**
   ```bash
   # On local machine:
   cd cursor_outputs/testing/remote_scripts/
   scp install_cuda_conda.sh local-kevlu@ipp1-1125:~/
   ```

2. **On remote machine:**
   ```bash
   chmod +x install_cuda_conda.sh
   ./install_cuda_conda.sh
   ```

3. **After installation, modify setup process:**
   ```bash
   # Instead of using the venv approach, use conda
   conda activate nvflare_cuda
   
   # Then manually install NVFlare:
   cd ~/nvflare_testing/NVFlare
   pip install -e .
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
   pip install tensorflow[and-cuda]
   ```

**Pros:**
- ✅ No sudo required
- ✅ Complete CUDA toolkit (nvcc available)
- ✅ Isolated environment
- ✅ No system modifications

**Cons:**
- ⚠️ Requires ~5-10 minutes to install
- ⚠️ Uses conda instead of venv (different workflow)

---

## Option 3: System-Wide CUDA Installation (If you have sudo)

**Only use if:** You have sudo access and want system-wide CUDA

**Steps:**

1. **Transfer the script:**
   ```bash
   # On local machine:
   cd cursor_outputs/testing/remote_scripts/
   scp install_cuda.sh local-kevlu@ipp1-1125:~/
   ```

2. **On remote machine:**
   ```bash
   chmod +x install_cuda.sh
   sudo ./install_cuda.sh
   ```

3. **Reboot (required):**
   ```bash
   sudo reboot
   ```

4. **After reboot, verify:**
   ```bash
   nvidia-smi
   nvcc --version
   ```

5. **Continue with setup:**
   ```bash
   ./verify_env.sh
   ./remote_setup.sh
   ./run_multi_gpu_tests.sh
   ```

**Pros:**
- ✅ System-wide CUDA toolkit
- ✅ Works for all users
- ✅ `nvcc` available

**Cons:**
- ⚠️ Requires sudo access
- ⚠️ Requires reboot
- ⚠️ Takes 15-20 minutes
- ⚠️ Modifies system packages

---

## My Recommendation

### Try Option 1 First (Just run setup!)

```bash
# Skip CUDA installation, just run:
./remote_setup.sh
```

The script will automatically install PyTorch and TensorFlow with CUDA support. This should work fine!

### If PyTorch/TensorFlow can't find CUDA:

If you see errors like `CUDA not available` after setup, then use **Option 2** (Conda CUDA).

---

## Quick Decision Guide

**Do you have sudo access?**
- ❌ No → Use **Option 1** (skip) or **Option 2** (conda)
- ✅ Yes → Use **Option 1** first, then **Option 3** if needed

**Can you reboot the machine?**
- ❌ No → Use **Option 1** or **Option 2** (no reboot needed)
- ✅ Yes → Any option works

**How fast do you want to start testing?**
- 🚀 ASAP → Use **Option 1** (skip CUDA, use bundled)
- 🐢 OK to wait → Use **Option 3** (system CUDA)

---

## Testing the Installation

After any option, verify CUDA works with PyTorch/TensorFlow:

```bash
# Activate your environment (venv or conda)
source ~/nvflare_testing/nvflare_env/bin/activate
# OR
conda activate nvflare_cuda

# Test PyTorch CUDA
python -c "import torch; print(f'PyTorch CUDA: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')"

# Test TensorFlow GPU
python -c "import tensorflow as tf; print(f'TF GPUs: {len(tf.config.list_physical_devices(\"GPU\"))}')"
```

**Expected output:**
```
PyTorch CUDA: True
GPU count: 2
TF GPUs: 2
```

If you see this, you're good to go! 🎉

---

## Summary

**Fastest path to testing:**

```bash
# On remote machine:
./verify_env.sh       # Will show CUDA warning (ignore it)
./remote_setup.sh     # Installs PyTorch/TF with bundled CUDA
./run_multi_gpu_tests.sh  # Should work!
```

If tests fail with CUDA errors, come back and use Option 2 or 3.

---

## What Actually Happens in remote_setup.sh

The setup script installs:
```bash
# PyTorch with CUDA 12.1 support (includes CUDA libraries)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# TensorFlow with GPU support (includes CUDA libraries)
pip install tensorflow[and-cuda]
```

These packages include:
- ✅ CUDA runtime libraries
- ✅ cuDNN (deep learning primitives)
- ✅ NCCL (multi-GPU communication)
- ❌ CUDA compiler (nvcc) - not needed for testing

**This is sufficient for running NVFlare Multi-GPU tests!**
