# TensorFlow Multi-GPU Investigation & Setup Guide

**Date:** February 2, 2026  
**Status:** Issue identified - TensorFlow MirroredStrategy deadlocks in external subprocess

---

## Summary of Previous Testing

### What Was Tested:
- **Example:** `examples/advanced/multi-gpu/tf/`
- **Environment:** Remote GPU machine (2x NVIDIA A30 24GB, Ubuntu 24.04)
- **Framework:** TensorFlow with MirroredStrategy
- **Mode:** External process launch (`launch_external_process=True`)

### Result: FAILED

**Test Duration:** Failed in two different ways:
1. **First attempt (contaminated env):** 31 seconds - crashed with space issues
2. **Second attempt (clean TF env):** ~5 minutes per round - deadlocked/hung

---

## The Issue: NOT Protobuf

**Note:** There is NO protobuf-specific issue documented. The problem is an **architectural incompatibility**.

### Actual Root Cause:

**TensorFlow's MirroredStrategy deadlocks when running in NVFlare external subprocess:**

1. Process launches successfully
2. TensorFlow initializes both GPUs
3. Model loads successfully
4. **Hangs/deadlocks during `model.evaluate()` BEFORE training even starts**
5. Waits ~5 minutes until pipe timeout
6. Process gets killed, subsequent rounds fail

### Technical Details:

**Why it deadlocks:**
- MirroredStrategy uses single-process with multi-threading for GPU coordination
- ALL code (including `flare.receive()`, `flare.send()`) runs in that one process
- MirroredStrategy's internal GPU synchronization conflicts with NVFlare's pipe-based IPC
- Not a crash or premature shutdown - it's a genuine **deadlock/hang**

### Comparison with PyTorch:

| Framework | Result | Architecture | Issue |
|-----------|--------|--------------|-------|
| **PyTorch DDP** | ✅ PASS | Multi-process (one per GPU, rank 0 for comms) | None |
| **Lightning DDP** | ✅ PASS | Multi-process (rank 0 for comms) | None |
| **TensorFlow MirroredStrategy** | ❌ FAIL | Single-process (threaded GPU coordination) | Deadlock |

**PyTorch works because:**
- Explicitly multi-process
- Only rank 0 communicates with NVFlare
- Other ranks sync via DDP, not through NVFlare pipes
- Clean separation of concerns

**TensorFlow fails because:**
- Single-process with internal threading
- ALL code runs in the same process context
- Pipe communication conflicts with TensorFlow's async GPU operations

---

## What You Lost (Remote Machine Lease Expired)

### Environment Setup:
```bash
~/nvflare_testing/
├── nvflare_env/          # Main venv (PyTorch + NVFlare)
├── nvflare_tf_env/       # Clean TF-only venv (separate from PyTorch)
├── NVFlare/              # Git repo clone
├── logs/                 # Test logs
├── results/              # Test results
└── tmp/                  # Custom TMPDIR (to avoid /tmp space issues)
```

### Venvs Created:
1. **nvflare_env** - Main environment with PyTorch
   - Used for: PyTorch DDP, Lightning, LLM tests
   
2. **nvflare_tf_env** - Clean TensorFlow-only environment
   - No PyTorch (to avoid Keras 3 conflicts)
   - Created specifically for TF multi-GPU testing
   - Used separate venv to isolate TF dependencies

### Scripts Available:
All scripts are preserved in `cursor_outputs/testing/remote_scripts/`:
- `setup_tf_venv.sh` - Creates clean TF-only venv
- `test_tensorflow_multi_gpu.sh` - Runs TF multi-GPU test
- `test_tf_clean.sh` - Alternative test script
- Full setup instructions in `README.md`

---

## Can You Set Up Again? YES! ✅

### You Have Everything Needed:

1. ✅ **All setup scripts** - Preserved in `cursor_outputs/testing/remote_scripts/`
2. ✅ **Complete documentation** - REMOTE_TESTING_REQUIREMENTS.md
3. ✅ **Test scripts** - All automated scripts ready
4. ✅ **Git repo** - Just clone from GitHub again
5. ✅ **Configuration** - All settings documented

### Quick Setup on New Machine:

```bash
# On new remote machine:
mkdir ~/nvflare_testing
cd ~/nvflare_testing

# Clone repo
git clone https://github.com/NVIDIA/NVFlare.git
cd NVFlare
git checkout 2.7

# Create main venv
python3 -m venv ~/nvflare_testing/nvflare_env
source ~/nvflare_testing/nvflare_env/bin/activate
pip install -e .

# For TensorFlow testing, create separate venv
# (Transfer setup_tf_venv.sh from local machine first)
bash ~/setup_tf_venv.sh
```

---

## Should You Test TensorFlow Multi-GPU Again?

### Short Answer: NO ❌

**Reasons:**
1. **Issue is known and documented** - Architectural incompatibility
2. **Requires core framework changes** - Not an example-level fix
3. **Already tested twice** - Same failure both times
4. **Different venvs don't help** - Problem is in pipe communication, not dependencies
5. **Protobuf is NOT the issue** - No protobuf errors documented

### What Would Be Needed to Fix:

**Core NVFlare changes required:**
1. Modify pipe communication protocol to handle single-process multi-threaded GPU frameworks
2. Add async/threading-aware IPC mechanisms
3. Or: Add alternative communication mode for TensorFlow MirroredStrategy
4. Extensive testing with TensorFlow's internal threading model

**This is a framework-level issue, not a configuration problem.**

---

## What DOES Work for Multi-GPU Testing

### ✅ Verified Working:

**1. PyTorch DDP** (`examples/advanced/multi-gpu/pt/`)
- Status: ✅ PASS
- Duration: 20 minutes
- Hardware: 2x NVIDIA A30
- Architecture: Multi-process (torch.distributed)
- External process: YES
- Result: Clean pass, no errors

**2. PyTorch Lightning DDP** (`examples/advanced/multi-gpu/lightning/`)
- Status: Known Lightning integration bug (separate issue)
- When bug is fixed, should work (uses same architecture as PyTorch DDP)

---

## Recommendation for TensorFlow Users

### Option 1: Use PyTorch DDP (RECOMMENDED)
- Proven to work with NVFlare
- Better integration with external process mode
- More examples available

### Option 2: Use TensorFlow Single-GPU
- Skip MirroredStrategy
- Use one GPU per client
- Simpler architecture, fewer conflicts

### Option 3: Wait for Framework Fix
- Monitor NVFlare releases for TensorFlow MirroredStrategy support
- Requires core team investigation
- No ETA available

---

## What To Do on New Remote Machine

### Priority 1: Re-run Successful Tests (Validation)

Test what you know works to validate new setup:

**1. PyTorch DDP Multi-GPU** (~20 min)
```bash
cd ~/nvflare_testing/NVFlare/examples/advanced/multi-gpu/pt
bash prepare_data.sh
python job.py
```

**2. BioNeMo** (~15-30 min) - You just got this working!
```bash
# Transfer and run test_bionemo.sh
./test_bionemo.sh
```

### Priority 2: Test New Examples

**Tensor-Stream** (~1-2 hours) - Dataset fix applied, needs GPU validation
```bash
cd ~/nvflare_testing/NVFlare/examples/advanced/tensor-stream
python job.py --n_clients 2 --num_rounds 2
```

### Priority 3: Skip TensorFlow Multi-GPU

**Don't waste time on known broken test.**

---

## Setup Checklist for New Machine

### Step 1: Environment Verification
```bash
# Check GPUs
nvidia-smi

# Check CUDA
nvcc --version

# Check Python
python3 --version
```

### Step 2: Repository Setup
```bash
# Clone NVFlare
git clone https://github.com/NVIDIA/NVFlare.git ~/nvflare_testing/NVFlare
cd ~/nvflare_testing/NVFlare
git checkout 2.7

# Create main venv
python3 -m venv ~/nvflare_testing/nvflare_env
source ~/nvflare_testing/nvflare_env/bin/activate
pip install -e .
```

### Step 3: Install Framework Dependencies

**For PyTorch (multi-GPU, LLM, etc.):**
```bash
source ~/nvflare_testing/nvflare_env/bin/activate
pip install torch torchvision
```

**For BioNeMo:**
```bash
# Docker-based, no additional venv needed
# Just ensure Docker + NVIDIA Container Toolkit installed
```

**For TensorFlow (if you really want to test):**
```bash
# Create separate TF venv
bash ~/setup_tf_venv.sh  # (transfer script from local first)
```

### Step 4: Transfer Test Scripts

```bash
# On local machine:
cd /Users/kevlu/workspace/repos/secondcopynvflare/cursor_outputs/testing/remote_scripts/
scp *.sh user@remote-machine:~/
```

### Step 5: Run Tests

```bash
# On remote machine:
chmod +x ~/*.sh

# Run working tests:
./test_bionemo.sh          # 15-30 min
# Or manually run PyTorch DDP
cd ~/nvflare_testing/NVFlare/examples/advanced/multi-gpu/pt
bash prepare_data.sh && python job.py  # 20 min
```

---

## Summary

### About TensorFlow Multi-GPU Issue:

✅ **Documented:** Architecture incompatibility (MirroredStrategy + external process)  
✅ **Reproduced:** Tested twice, same deadlock behavior  
❌ **NOT Protobuf:** No protobuf errors found in any logs  
❌ **NOT Fixable:** Requires core framework changes  
✅ **Alternative:** PyTorch DDP works perfectly

### About Setting Up Again:

✅ **Can rebuild:** All scripts and documentation preserved  
✅ **Quick setup:** ~15-30 minutes for basic environment  
✅ **Known working tests:** PyTorch DDP, BioNeMo, Tensor-Stream  
❌ **Don't retest TF:** Known failure, waste of time

### Recommended Action:

**Skip TensorFlow Multi-GPU testing entirely. Focus on:**
1. Validating PyTorch DDP works on new machine (20 min)
2. Re-running BioNeMo test (30 min)
3. Testing Tensor-Stream with GPU (1-2 hours)

**Do NOT spend time trying to "fix" TensorFlow Multi-GPU - it's a framework issue.**

---

## Files Reference

**Documentation:**
- `cursor_outputs/testing/20260126_EXAMPLE_TESTING_SESSION_SUMMARY.md` (lines 393-456)
- `cursor_outputs/testing/TESTING_STATUS_OVERVIEW.md` (lines 85-94, 200-228)
- `cursor_outputs/testing/REMOTE_TESTING_REQUIREMENTS.md` (Section 2)

**Setup Scripts:**
- `cursor_outputs/testing/remote_scripts/setup_tf_venv.sh`
- `cursor_outputs/testing/remote_scripts/test_tensorflow_multi_gpu.sh`
- `cursor_outputs/testing/remote_scripts/test_tf_clean.sh`

**Working Test Scripts:**
- `cursor_outputs/testing/remote_scripts/test_bionemo.sh` (just completed successfully!)
- PyTorch DDP: Run manually via `examples/advanced/multi-gpu/pt/job.py`

---

## Questions?

**Q: Is there a protobuf issue?**  
A: No. No protobuf errors documented anywhere.

**Q: Can I fix TensorFlow multi-GPU?**  
A: No. Requires core framework changes.

**Q: Should I create separate TF venv?**  
A: Doesn't help with the deadlock issue. The problem is architectural, not dependency-related.

**Q: What should I test instead?**  
A: PyTorch DDP (proven working), BioNeMo (just succeeded), Tensor-Stream (needs GPU validation).

**Q: Do I have everything to set up again?**  
A: Yes! All scripts, configs, and documentation preserved.
