# NumPy Cross-Site Evaluation Example Failures

**Date**: January 20, 2026  
**Context**: User reported failure when running `hello-numpy-cross-val` example  
**User's Environment**: Installed NVFlare venv, not source tree

---

## 🐛 Errors Reported

### Error 1: Wrong Model Locator Type
```
ValueError: pt_persistor_id component must be PTFileModelPersistor. But got: <class 'NoneType'>
File: nvflare/app_opt/pt/file_model_locator.py:49
```

**Root Cause:** `PTFileModelLocator` (PyTorch) is being created instead of `NPModelLocator` (NumPy).

**Possible Causes:**
1. Recipe's `framework` attribute is not set to `FrameworkType.RAW`
2. Framework detection in `add_cross_site_evaluation()` is failing
3. User's installed version is outdated and doesn't have the fix

**Status:** ✅ **FIXED in source** (line 160 of `nvflare/app_common/np/recipes/fedavg.py` sets `self.framework = FrameworkType.RAW`)

### Error 2: Missing Persistor ID in comp_ids
```
persistor_id = recipe.job.comp_ids.get("persistor_id", "")
# Returns "" when no initial_model provided
```

**Root Cause:** NumPy recipe doesn't set `job.comp_ids["persistor_id"]` when creating a persistor.

**Impact:** When `add_cross_site_evaluation()` tries to look up the persistor_id, it gets an empty string.

**Status:** ✅ **FIXED NOW** - Added `job.comp_ids["persistor_id"] = persistor_id` to line 191

### Error 3: Client Expects numpy_key But Receives Empty Params
```
KeyError: 'numpy_key'
File: client.py:61
Code: input_np_arr = input_model.params[NPConstants.NUMPY_KEY]
```

**Root Cause:** The example creates a recipe **without an initial_model**:

```python
recipe = NumpyFedAvgRecipe(
    name="hello-numpy-train-cse",
    min_clients=n_clients,
    num_rounds=num_rounds,
    train_script="client.py",
    train_args="",  # No initial_model!
)
```

When ScatterAndGather has `persistor_id=""` and `allow_empty_global_weights=True`, it sends an **empty params dict** to clients.

But the client code expects:
```python
input_np_arr = input_model.params[NPConstants.NUMPY_KEY]  # ← KeyError!
```

**Status:** ⚠️ **EXAMPLE BUG** - Client code incompatible with no-initial-model workflow

---

## 🔧 Fixes Applied

### Fix 1: Set comp_ids in NumPy Recipe

**File:** `nvflare/app_common/np/recipes/fedavg.py` line 191

```python
# Before:
if self.initial_model is not None:
    persistor_id = job.to_server(NPModelPersistor(initial_model=self.initial_model), id="persistor")

# After:
if self.initial_model is not None:
    persistor_id = job.to_server(NPModelPersistor(initial_model=self.initial_model), id="persistor")
    job.comp_ids["persistor_id"] = persistor_id  # ← Added
```

This matches the pattern used in PyTorch and TensorFlow recipes.

---

## 🚨 Remaining Issues

### Issue 1: Example Client Code Incompatible

**File:** `examples/hello-world/hello-numpy-cross-val/client.py` line 61

**Problem:** Client assumes `input_model.params` always has `NPConstants.NUMPY_KEY`, but this is not true when:
- No initial model is provided
- First round with empty global weights

**Recommended Fix:**

```python
# Option A: Check if key exists
if flare.is_running():
    input_model = flare.receive()
    print(f"Client {client_name}, current_round={input_model.current_round}")
    
    # Handle empty params (first round with no initial model)
    if NPConstants.NUMPY_KEY in input_model.params:
        input_np_arr = input_model.params[NPConstants.NUMPY_KEY]
        print(f"Received weights: {input_np_arr}")
    else:
        # Initialize with random/zero weights for first round
        input_np_arr = np.random.randn(10)  # or appropriate initialization
        print(f"No initial model, using random initialization")
    
    # Continue with training...
```

```python
# Option B: Require initial_model in example
recipe = NumpyFedAvgRecipe(
    name="hello-numpy-train-cse",
    min_clients=n_clients,
    num_rounds=num_rounds,
    train_script="client.py",
    train_args="",
    initial_model=[1.0, 2.0, 3.0],  # ← Add this
)
```

### Issue 2: User Running Outdated Version

**Evidence:** Error path shows installed venv:
```
/raid/zhaoyan/nvflare_workspace/nvflare_test/logs/20260120_075011/venv/lib/python3.12/site-packages/nvflare/
```

**Action Required:** User needs to reinstall NVFlare from source:
```bash
cd /path/to/NVFlare/source
pip install -e .
```

---

## ✅ Verification Steps

After fixes are applied, verify:

1. **Framework Detection:**
   ```python
   from nvflare.app_common.np.recipes import NumpyFedAvgRecipe
   recipe = NumpyFedAvgRecipe(name="test", min_clients=2, num_rounds=1, train_script="client.py")
   assert recipe.framework == FrameworkType.RAW
   ```

2. **comp_ids Tracking:**
   ```python
   recipe = NumpyFedAvgRecipe(
       name="test",
       min_clients=2,
       num_rounds=1,
       train_script="client.py",
       initial_model=[1, 2, 3]
   )
   assert "persistor_id" in recipe.job.comp_ids
   ```

3. **CSE Locator Selection:**
   ```python
   from nvflare.recipe.utils import add_cross_site_evaluation
   recipe = NumpyFedAvgRecipe(
       name="test",
       min_clients=2,
       num_rounds=1,
       train_script="client.py",
       initial_model=[1, 2, 3]
   )
   add_cross_site_evaluation(recipe)
   # Should create NPModelLocator, not PTFileModelLocator
   ```

---

## 📝 Summary

| Issue | Type | Status | Action |
|-------|------|--------|--------|
| Wrong locator (PT vs NP) | Framework detection | ✅ Fixed | Already in source |
| Missing comp_ids["persistor_id"] | NumPy recipe bug | ✅ Fixed now | Just applied |
| KeyError: 'numpy_key' | Example bug | ⚠️ Needs fix | Update client.py |
| User on old version | Environment | ⚠️ User action | Reinstall from source |

**Next Steps:**
1. ✅ comp_ids fix applied
2. ⚠️ Update `examples/hello-world/hello-numpy-cross-val/client.py` to handle empty params
3. ⚠️ User needs to reinstall NVFlare from source
4. ✅ Test the example end-to-end
