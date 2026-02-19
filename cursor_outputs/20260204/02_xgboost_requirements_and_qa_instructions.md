# XGBoost Requirements and QA Testing Instructions

**Date**: 2026-02-04  
**Critical**: For QA to test XGBoost examples properly

---

## The Issue

### What QA Reported
```
ERROR - failed to start adaptor: RuntimeError: cannot start - my rank is not set
```

### What I Fixed
✅ Fixed the "rank not set" bug in `fed_executor.py` (adaptor caching issue)

### What Remains
The histogram-based XGBoost examples **REQUIRE** a special build of XGBoost with federated learning support.

---

## Critical Requirement: Special XGBoost Build

### Standard pip xgboost WILL NOT WORK

The examples need XGBoost 2.2.0 nightly build with federated support:

```bash
pip install "https://s3-us-west-2.amazonaws.com/xgboost-nightly-builds/federated-secure/xgboost-2.2.0.dev0%2B4601688195708f7c31fcceeb0e0ac735e7311e61-py3-none-manylinux_2_28_x86_64.whl"
```

This is specified in `examples/advanced/xgboost/requirements.txt` (lines 12-13).

### Platform Requirements

**Linux Only**: 
- The wheel is `manylinux_2_28_x86_64`
- Requires glibc 2.28+ 
- ✅ Works on modern Linux (Ubuntu 22.04+, RHEL 9+, etc.)

**Does NOT work on**:
- ❌ macOS (any version)
- ❌ Windows
- ❌ Old Linux with glibc < 2.28

---

## QA Testing Instructions

### Step 1: Verify System Requirements

```bash
# Check glibc version (must be 2.28+)
ldd --version

# Should show: ldd (GNU libc) 2.28 or higher
```

### Step 2: Set Up Environment

```bash
cd examples/advanced/xgboost
python3 -m venv xgb_test_venv
source xgb_test_venv/bin/activate

# Install from requirements.txt (includes federated xgboost)
pip install -r requirements.txt
```

### Step 3: Verify XGBoost Installation

```bash
python3 -c "import xgboost; print(xgboost.__version__)"
# Should show: 2.2.0.dev0+...
```

### Step 4: Prepare Data

```bash
cd fedxgb
bash prepare_data.sh
```

### Step 5: Run Tests

**Histogram-based (requires federated XGBoost):**
```bash
cd fedxgb
python3 job.py --site_num 2 --round_num 2 --split_method uniform
```

**Tree-based (works with any XGBoost):**
```bash
python3 job_tree.py --site_num 2 --round_num 2 --split_method uniform
```

---

## Expected Results

### With My Fix + Correct XGBoost

**Should see:**
```
INFO - got my rank: 0
INFO - successfully configured client site-1
INFO - got my rank: 1
INFO - successfully configured client site-2
INFO - successfully configured clients ['site-1', 'site-2']
INFO - starting XGBoost Server in another thread
[XGBoost training proceeds...]
```

**Should NOT see:**
```
ERROR - failed to start adaptor: RuntimeError: cannot start - my rank is not set
```

### With Standard XGBoost (Wrong Version)

**Will fail with:**
```
ERROR - Exception starting XGBoost runner: XGBoostError: XGBoost is not compiled with federated learning support
```

**Fix:** Install from requirements.txt

---

## My Testing Limitations

**Why I couldn't fully test:**
- I'm on macOS
- The federated XGBoost wheel is Linux-only
- I could only test that my fix resolved the "rank not set" error
- I could not test actual training completion

**What I verified:**
- ✅ "rank not set" bug is fixed
- ✅ Clients configure successfully
- ✅ Adaptor caching works
- ❌ Could not verify training completion (wrong platform)

---

## Documentation Status

### requirements.txt ✅
- **Status**: Correct
- **Location**: `examples/advanced/xgboost/requirements.txt`
- **Content**: Specifies federated XGBoost wheel

### README.md ⚠️
- **Status**: Mentions requirements.txt but not explicit about special XGBoost
- **Location**: `examples/advanced/xgboost/README.md`
- **Line 145**: Says `pip install -r requirements.txt`
- **Issue**: Doesn't emphasize that standard xgboost won't work

### Recommendation
Add a prominent note in README about the special XGBoost requirement:

```markdown
## ⚠️ Important: XGBoost Requirements

Histogram-based federated XGBoost requires a special build with federated learning support.

**Linux (glibc 2.28+) only:**
```bash
pip install -r requirements.txt  # Installs federated XGBoost 2.2.0
```

**macOS/Windows users**: Only tree-based examples will work with standard XGBoost.
```

---

## Summary for QA

1. ✅ **"Rank not set" bug is FIXED** - adaptor caching implemented
2. ⚠️ **Special XGBoost required** - must install from requirements.txt
3. ✅ **Requirements.txt is correct** - has the right wheel
4. ⚠️ **README could be clearer** - should emphasize special build requirement
5. ✅ **Platform requirement**: Linux with glibc 2.28+ only

**Action for QA:**
1. Confirm environment has glibc 2.28+
2. Install from `requirements.txt` (not standard xgboost)
3. Verify xgboost version shows `2.2.0.dev0`
4. Retest with my fix

**If still fails with "rank not set"**: Bug in my fix - report back
**If fails with "not compiled with federated learning"**: Wrong xgboost version installed
