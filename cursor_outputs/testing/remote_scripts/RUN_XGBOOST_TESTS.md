# XGBoost Federated Learning Test Guide

**Date**: 2026-02-04  
**Branch**: fix_xgboost_27  
**Machine**: Linux with RTX A4000

---

## Fast check: self-paced tutorial (notebook 10.1_fed_xgboost)

This mirrors the flow in `examples/tutorials/self-paced-training/.../chapter-10_federated_XGBoost/10.1_fed_xgboost/fed_xgboost.ipynb`: Credit Card data, 3 sites, `xgb_fl_job.py`.

**1. Go to tutorial dir and activate venv**
```bash
cd /localhome/local-kevlu/nvflare_testing/NVFlare
source xgb_test_venv/bin/activate
cd examples/tutorials/self-paced-training/part-4_advanced_federated_learning/chapter-10_federated_XGBoost/10.1_fed_xgboost
```

**2. One-time data setup (notebook does this in “Data Preparation”)**
- Download Credit Card dataset (e.g. via notebook cells or):
  ```bash
  pip install kagglehub
  python3 -c "import kagglehub; path=kagglehub.dataset_download('mlg-ulb/creditcardfraud'); print(path)"
  mkdir -p /tmp/nvflare/dataset
  cp <path_from_above>/creditcard.csv /tmp/nvflare/dataset/
  ```
- Generate splits (same as `! bash prepare_data.sh` in notebook):
  ```bash
  bash prepare_data.sh
  ```
  Output goes to `/tmp/nvflare/dataset/xgb_dataset/` (base_xgb_data, horizontal_xgb_data, vertical_xgb_data).

**3. Run the tutorial jobs (same as notebook “Experiments”)**
```bash
# Horizontal histogram (main one to verify first)
python3 xgb_fl_job.py --training_algo histogram --data_split_mode horizontal

# Optional: cyclic, bagging, vertical (as in notebook)
python3 xgb_fl_job.py --training_algo cyclic --data_split_mode horizontal
python3 xgb_fl_job.py --training_algo bagging --data_split_mode horizontal
python3 xgb_fl_job.py --training_algo histogram --data_split_mode vertical
```

**4. Pass =**
- No `rank not set` / `failed to start adaptor`
- You see clients configured (e.g. site-1, site-2, site-3) and training runs; results under `/tmp/nvflare/workspace/fedxgb/`

**Fail (rank not set)** → use the class-level adaptor cache fix in `nvflare/app_opt/xgboost/histogram_based_v2/fed_executor.py` (and scp to this machine if needed).

---

## Fast check: advanced example (fedxgb/job.py, HIGGS, 2 sites)

For the **advanced** example (HIGGS, 2 sites, recipe API), not the notebook tutorial:

```bash
cd /localhome/local-kevlu/nvflare_testing/NVFlare
source xgb_test_venv/bin/activate
cd examples/advanced/xgboost/fedxgb
python3 job.py --site_num 2 --round_num 2 --split_method uniform --data_root /localhome/local-kevlu/nvflare_testing/NVFlare/xgboost_test_data/splits/horizontal
```

Pass = `got my rank: 0/1`, `successfully configured clients`, no `rank not set`. (If repo path differs, set `--data_root` to `$REPO_DIR/xgboost_test_data/splits/horizontal`.)

---

## Quick Start

```bash
# On remote Linux machine (NVFlare repo already there)

# 1. Checkout fix branch
cd /path/to/secondcopynvflare
git checkout fix_xgboost_27
git pull

# 2. Run setup script
cd cursor_outputs/testing/remote_scripts
bash setup_xgboost_testing.sh

# 3. Run tests (venv is already activated by setup script)
cd ../../examples/advanced/xgboost/fedxgb

# CPU test
python3 job.py --site_num 2 --round_num 2 --split_method uniform

# GPU test (with RTX A4000)
python3 job.py --site_num 2 --round_num 2 --split_method uniform --use_gpus
```

---

## Check XGBoost version (for management)

We use the **federated** XGBoost build (not the standard PyPI package). To report versions:

```bash
source /path/to/xgb_test_venv/bin/activate

# Version string (expect 2.2.0.dev0+...)
python3 -c "import xgboost; print('xgboost', xgboost.__version__)"

# Confirm federated build (must succeed)
python3 -c "import xgboost.federated; print('federated build: OK')"

# Full package origin
pip show xgboost
```

- **Version**: `2.2.0.dev0+<git_hash>` from the federated-secure nightly wheel (see `examples/advanced/xgboost/requirements.txt`).
- **Source**: `https://s3-us-west-2.amazonaws.com/xgboost-nightly-builds/federated-secure/...manylinux_2_28_x86_64.whl`
- Standard `pip install xgboost` does **not** include federated support; the setup script installs the wheel from requirements.txt.

---

## What the Setup Script Does

1. ✅ **Verifies glibc 2.28+** (required for federated XGBoost)
2. ✅ **Checks GPU availability** (RTX A4000)
3. ✅ **Verifies branch** (fix_xgboost_27)
4. ✅ **Checks adaptor caching fix** (the "rank not set" bug fix)
5. ✅ **Creates clean venv** (xgb_test_venv)
6. ✅ **Installs federated XGBoost** (2.2.0.dev0 from requirements.txt)
7. ✅ **Verifies correct version** (not standard pip xgboost)
8. ✅ **Prepares HIGGS dataset** (downloads and splits data)

---

## Expected Test Results

### ✅ Success (What You Should See)

```
INFO - Waiting for clients to be ready: ['site-1', 'site-2']
INFO - Configuring clients ['site-1', 'site-2']
INFO - sending task config to clients ['site-1', 'site-2']
INFO - got my rank: 0
INFO - successfully configured client site-1
INFO - got my rank: 1
INFO - successfully configured client site-2
INFO - successfully configured clients ['site-1', 'site-2']
INFO - starting XGBoost Server in another thread
[XGBoost training proceeds with round updates...]
INFO - Training completed
```

### ❌ Failure Scenarios

**1. "rank not set" error (THE BUG WE FIXED)**
```
ERROR - failed to start adaptor: RuntimeError: cannot start - my rank is not set
```
**Meaning**: The adaptor caching fix is not present  
**Action**: Verify you're on fix_xgboost_27 branch with latest commits

**2. "XGBoost is not compiled with federated learning support"**
```
ERROR - Exception starting XGBoost runner: XGBoostError: XGBoost is not compiled with federated learning support
```
**Meaning**: Wrong XGBoost version (standard pip instead of federated build)  
**Action**: Run setup script again, it will reinstall correct version

**3. "not a supported wheel on this platform"**
```
ERROR: xgboost-2.2.0.dev0+...-manylinux_2_28_x86_64.whl is not a supported wheel
```
**Meaning**: glibc version too old  
**Action**: Need newer Linux distro (Ubuntu 22.04+, not 20.04)

---

## Test Variations

### Basic Tests (2-3 minutes each)

```bash
# Histogram-based (default)
python3 job.py --site_num 2 --round_num 2 --split_method uniform

# Tree-based bagging
python3 job_tree.py --site_num 2 --round_num 2 --split_method uniform

# Vertical (requires PSI first)
python3 job_vertical.py --site_num 2 --round_num 2 --split_method uniform
```

### GPU Accelerated Tests (~1 minute each)

```bash
# With GPU (RTX A4000)
python3 job.py --site_num 2 --round_num 2 --split_method uniform --use_gpus
```

### Extended Tests (5-10 minutes)

```bash
# More rounds
python3 job.py --site_num 2 --round_num 10 --split_method uniform

# More clients
python3 job.py --site_num 5 --round_num 5 --split_method uniform
```

---

## Manual Verification Steps

### 1. Verify Adaptor Fix is Present

```bash
grep -A 2 "_cached_adaptor" nvflare/app_opt/xgboost/histogram_based_v2/fed_executor.py
```

**Should see:**
```python
self._cached_adaptor = None  # Cache adaptor to prevent recreation

def get_adaptor(self, fl_ctx: FLContext):
    # Return cached adaptor if it exists to prevent losing configuration
    if self._cached_adaptor is not None:
        return self._cached_adaptor
```

### 2. Check XGBoost Version

```bash
source xgb_test_venv/bin/activate
python3 -c "import xgboost; print(xgboost.__version__)"
```

**Must show**: `2.2.0.dev0+...` (NOT `2.1.4` or other stable versions)

### 3. Check GPU

```bash
nvidia-smi
```

**Should show**: RTX A4000 with available memory

---

## Troubleshooting

### Setup Script Fails at glibc Check

**Problem**: glibc < 2.28  
**Solution**: Use Ubuntu 22.04+, RHEL 9+, or Debian 11+  
**Check**: `ldd --version`

### Setup Script Fails at Fix Verification

**Problem**: Adaptor caching code not found  
**Solution**: Make sure you're on fix_xgboost_27 with latest changes:
```bash
git checkout fix_xgboost_27
git pull
```

### Wrong XGBoost Version Installed

**Problem**: Shows 2.1.4 instead of 2.2.0.dev0  
**Solution**: 
```bash
rm -rf xgb_test_venv
bash cursor_outputs/testing/remote_scripts/setup_xgboost_testing.sh
```

### Job Fails with "No module named 'nvflare'"

**Problem**: venv not activated  
**Solution**: `source xgb_test_venv/bin/activate`

---

## What to Report Back

After running tests, report:

1. ✅/❌ Setup script completed successfully
2. ✅/❌ XGBoost version is 2.2.0.dev0
3. ✅/❌ Clients configured (saw "got my rank" messages)
4. ✅/❌ NO "rank not set" error appeared
5. ✅/❌ Training completed successfully
6. Any error messages (full error, not just last line)
7. GPU usage (if --use_gpus was used)

---

## Quick Diagnosis Commands

```bash
# Check everything is correct
cd /path/to/secondcopynvflare

# 1. Fix present?
grep "_cached_adaptor" nvflare/app_opt/xgboost/histogram_based_v2/fed_executor.py

# 2. Right XGBoost?
source xgb_test_venv/bin/activate
python3 -c "import xgboost; print(xgboost.__version__)"

# 3. GPU available?
nvidia-smi --query-gpu=name --format=csv,noheader

# All checks pass? Run test:
cd examples/advanced/xgboost/fedxgb
python3 job.py --site_num 2 --round_num 2 --split_method uniform
```

---

## Expected Timeline

- Setup: 5-10 minutes (one-time)
- CPU test: 2-3 minutes per run
- GPU test: ~1 minute per run

**Total for full validation: ~15 minutes**
