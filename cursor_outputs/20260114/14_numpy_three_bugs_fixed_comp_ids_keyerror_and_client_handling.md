# URGENT: NumPy Example Failures - Fixes Applied

**Date**: January 20, 2026  
**Status**: ✅ **ALL FIXES APPLIED**

---

## 🚨 What Happened

You reported errors when running:
```bash
cd ../NVFlare/examples/hello-world/hello-numpy-cross-val
python3 job.py --mode training --n_clients 2 --num_rounds 3
```

**Three bugs were identified:**

1. ❌ Wrong model locator (`PTFileModelLocator` instead of `NPModelLocator`)
2. ❌ Missing `comp_ids["persistor_id"]` in NumPy recipe
3. ❌ Client code crashes with `KeyError: 'numpy_key'` when no initial model

---

## ✅ Fixes Applied

### Fix 1: NumPy Recipe - Set comp_ids for Persistor

**File:** `nvflare/app_common/np/recipes/fedavg.py`

**What Changed:**
```python
# Added line 191
if self.initial_model is not None:
    persistor_id = job.to_server(NPModelPersistor(initial_model=self.initial_model), id="persistor")
    job.comp_ids["persistor_id"] = persistor_id  # ← NEW: Track persistor ID
```

**Why:** NumPy recipe wasn't tracking the persistor_id in `comp_ids`, causing `add_cross_site_evaluation()` to fail when looking it up. This matches PyTorch and TensorFlow patterns.

---

### Fix 2: Client Code - Handle Empty Initial Model

**Files:**
- `examples/hello-world/hello-numpy-cross-val/client.py`
- `examples/hello-world/hello-numpy/client.py`

**What Changed:**
```python
# Before (line 61):
input_np_arr = input_model.params[NPConstants.NUMPY_KEY]  # ← KeyError if no initial model!

# After:
if NPConstants.NUMPY_KEY in input_model.params:
    input_np_arr = input_model.params[NPConstants.NUMPY_KEY]
    print(f"Received weights: {input_np_arr}")
else:
    # Initialize with simple numpy array for first round
    input_np_arr = np.array([0.0] * 10)
    print(f"No initial model provided, using zero initialization: {input_np_arr}")
```

**Why:** When running FedAvg **without** an `initial_model`, the server sends empty params on the first round. The client must handle this gracefully by initializing weights locally.

---

## ⚠️ IMPORTANT: You Need to Reinstall

Your error log shows you're running from an **installed venv**:
```
/raid/zhaoyan/nvflare_workspace/nvflare_test/logs/20260120_075011/venv/lib/python3.12/site-packages/nvflare/
```

**The fixes are in the source tree, but not in your installed version!**

### To Apply Fixes:

```bash
# 1. Navigate to NVFlare source directory
cd /path/to/NVFlare/source

# 2. Reinstall in editable mode (or regular install)
pip install -e .

# OR for regular install:
# pip install .

# 3. Verify the fix
python3 -c "
from nvflare.app_common.np.recipes import NumpyFedAvgRecipe
from nvflare.job_config.script_runner import FrameworkType

recipe = NumpyFedAvgRecipe(
    name='test',
    min_clients=2,
    num_rounds=1,
    train_script='client.py',
    initial_model=[1.0, 2.0, 3.0]
)

print(f'Framework: {recipe.framework}')
print(f'Has comp_ids: {hasattr(recipe.job, \"comp_ids\")}')
print(f'persistor_id in comp_ids: {\"persistor_id\" in recipe.job.comp_ids}')
assert recipe.framework == FrameworkType.RAW, 'Framework should be RAW!'
assert 'persistor_id' in recipe.job.comp_ids, 'comp_ids should have persistor_id!'
print('✅ All checks passed!')
"

# 4. Run the example again
cd examples/hello-world/hello-numpy-cross-val
python3 job.py --mode training --n_clients 2 --num_rounds 3
```

---

## 🔍 Detailed Error Analysis

### Error 1: `ValueError: pt_persistor_id component must be PTFileModelPersistor`

**Root Cause:** This was happening because the NumPy recipe's `framework` attribute was already set to `FrameworkType.RAW` (line 160 of `fedavg.py`), but your installed version might not have had this fix yet.

**Fix Status:** ✅ Already in source (from previous PR work)

### Error 2: Missing persistor_id

**Root Cause:** When `add_cross_site_evaluation()` tried to look up the persistor_id:
```python
persistor_id = recipe.job.comp_ids.get("persistor_id", "")  # Returns ""
```

It got an empty string because NumPy recipe never set it.

**Fix Status:** ✅ Fixed now (added line 191)

### Error 3: `KeyError: 'numpy_key'`

**Root Cause:** Your example creates a recipe without `initial_model`:
```python
recipe = NumpyFedAvgRecipe(
    name="hello-numpy-train-cse",
    min_clients=n_clients,
    num_rounds=num_rounds,
    train_script="client.py",
    train_args="",  # No initial_model!
)
```

When there's no initial model, `ScatterAndGather` sends **empty params** (`{}`) to clients on the first round. But the client code blindly accessed:
```python
input_np_arr = input_model.params[NPConstants.NUMPY_KEY]  # KeyError!
```

**Fix Status:** ✅ Fixed (added defensive check in both client.py files)

---

## ✅ Testing After Reinstall

Run these tests to verify:

### Test 1: Training without initial model (what failed before)
```bash
cd examples/hello-world/hello-numpy-cross-val
python3 job.py --mode training --n_clients 2 --num_rounds 3
```

**Expected:** Should complete successfully without KeyError

### Test 2: Training with initial model
```python
from nvflare.app_common.np.recipes import NumpyFedAvgRecipe
from nvflare.recipe import SimEnv
from nvflare.recipe.utils import add_cross_site_evaluation

recipe = NumpyFedAvgRecipe(
    name="test-with-initial",
    min_clients=2,
    num_rounds=2,
    train_script="client.py",
    initial_model=[1.0, 2.0, 3.0, 4.0, 5.0],  # Provide initial model
)

add_cross_site_evaluation(recipe)

env = SimEnv(num_clients=2)
run = recipe.execute(env)
print(f"Result: {run.get_result()}")
```

**Expected:** Should create `NPModelLocator`, not `PTFileModelLocator`

### Test 3: CSE-only mode
```bash
cd examples/hello-world/hello-numpy-cross-val
python3 job.py --mode pretrained --n_clients 2
```

**Expected:** Should work if pre-trained models exist in `/tmp/nvflare/server_pretrain_models`

---

## 📊 Summary of Changes

| File | Lines Changed | Purpose |
|------|---------------|---------|
| `nvflare/app_common/np/recipes/fedavg.py` | +1 (line 191) | Track persistor_id in comp_ids |
| `examples/hello-world/hello-numpy-cross-val/client.py` | ~7 (lines 61-67) | Handle empty params gracefully |
| `examples/hello-world/hello-numpy/client.py` | ~7 (lines 61-67) | Handle empty params gracefully |

**Total Impact:** Minimal changes, high impact - fixes critical runtime failures

---

## 🎯 Root Cause: "Did You Cause This?"

**Short Answer:** Partially, but these were pre-existing issues that surfaced when testing CSE.

**Long Answer:**
1. The `framework` attribute was added in a previous PR, which was correct
2. The `comp_ids` tracking was missing in NumPy recipe (oversight during refactoring)
3. The client code issue was **pre-existing** - examples never handled the no-initial-model case

**These fixes improve robustness and are necessary for CSE support.**

---

## 🚀 Next Steps

1. ✅ **Reinstall NVFlare** from source (see command above)
2. ✅ **Test the example** with the command that failed
3. ✅ **Verify CSE works** with NumPy recipes
4. ✅ **Check CI/CD** - these changes should pass all tests

If you still see issues after reinstalling, please share:
- The full error log
- Output of `python3 -c "import nvflare; print(nvflare.__file__)"`  (to confirm you're using the right installation)
- The exact command you ran
