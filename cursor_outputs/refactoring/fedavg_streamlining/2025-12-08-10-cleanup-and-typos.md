# Cleanup and Typo Fixes

**Date:** December 8, 2025
**Issues:** Redundant parameters, typos in docstrings, and unnecessary variable storage

## Issues Fixed

### 1. Redundant Parameter in Unified FedAvgRecipe

**File:** `nvflare/recipe/fedavg.py`

**Issue:**
`train_task_name="train"` was explicitly set in the `ScatterAndGather` controller, but this is the default value.

**Before:**
```python
controller = ScatterAndGather(
    min_clients=self.min_clients,
    num_rounds=self.num_rounds,
    wait_time_after_min_received=0,
    aggregator_id=aggregator_id,
    persistor_id=persistor_id,
    shareable_generator_id=shareable_generator_id,
    train_task_name="train",  # ❌ Redundant - this is the default
)
```

**After:**
```python
controller = ScatterAndGather(
    min_clients=self.min_clients,
    num_rounds=self.num_rounds,
    wait_time_after_min_received=0,
    aggregator_id=aggregator_id,
    persistor_id=persistor_id,
    shareable_generator_id=shareable_generator_id,
    # train_task_name defaults to AppConstants.TASK_TRAIN ("train")
)
```

**Why this is correct:**
- `ScatterAndGather`'s default is `train_task_name=AppConstants.TASK_TRAIN`
- `AppConstants.TASK_TRAIN = "train"`
- Explicitly setting a parameter to its default value is redundant
- After unification, there's only ONE controller for all frameworks (no separate branches)

### 2. Docstring Typos in PT and TF BaseFedJob Wrappers

**Files:**
- `nvflare/app_opt/pt/job_config/base_fed_job.py`
- `nvflare/app_opt/tf/job_config/base_fed_job.py`

**Typos fixed:**

| Line | Before | After |
|------|--------|-------|
| ~53-54 | "covert certain events" | "convert certain events" |
| ~55 | "AnlyticsReceiver" | "AnalyticsReceiver" |
| ~57-58 | "how to persistor the model" | "how to persist the model" |

```python
# Before (incorrect)
convert_to_fed_event: A component to covert certain events to fed events.
analytics_receiver (AnlyticsReceiver, optional): Receive analytics.
model_persistor: how to persistor the model.

# After (correct)
convert_to_fed_event: A component to convert certain events to fed events.
analytics_receiver (AnalyticsReceiver, optional): Receive analytics.
model_persistor: how to persist the model.
```

### 3. Redundant Variable Storage in PT BaseFedJob

**File:** `nvflare/app_opt/pt/job_config/base_fed_job.py`

**Issue:**
`model_locator` was being stored as an instance variable on line 81, but only used immediately after on line 98. The storage was unnecessary since the parameter is passed directly to the setup method.

**Before:**
```python
# Line 80-81 (redundant storage)
self.model_locator = model_locator

# Line 98 (direct usage)
self._setup_pytorch_model(initial_model, model_persistor, model_locator)
```

**After:**
```python
# Line 98 (direct usage, no storage needed)
self._setup_pytorch_model(initial_model, model_persistor, model_locator)
```

**Why this is correct:**
- `model_locator` is only used once during initialization
- Storing it as `self.model_locator` creates a misleading API (suggests it might be used later)
- Passing it directly is cleaner and more explicit
- TF wrapper doesn't store `model_persistor` either (consistent pattern)

## Note on `comp_ids`

**Question raised:** Is `self.comp_ids = {}` in unified `BaseFedJob` used?

**Answer:** ✅ **YES, intentionally!** This is a template/infrastructure pattern:

1. **Base class initializes:**
   ```python
   # nvflare/job_config/base_fed_job.py
   self.comp_ids = {}
   ```

2. **Child classes populate:**
   ```python
   # PT wrapper
   self.comp_ids.update(self.to_server(pt_model))

   # TF wrapper
   self.comp_ids["persistor_id"] = self.to_server(tf_model)
   ```

3. **Existing jobs use it:**
   ```python
   # nvflare/app_opt/pt/job_config/fed_avg.py
   controller = FedAvg(
       persistor_id=self.comp_ids["persistor_id"],  # ← Uses it!
   )
   ```

**Do NOT remove `comp_ids`** - it's part of the public API that existing code depends on!

## Verification

✅ All linting passes (except expected torch/tensorflow import warnings)
✅ No functional changes
✅ Improved code clarity
✅ Fixed documentation accuracy

## Files Changed

### Modified
- `nvflare/recipe/fedavg.py`
  - Removed redundant `train_task_name="train"` parameter from ScatterAndGather

- `nvflare/app_opt/pt/job_config/base_fed_job.py`
  - Fixed 3 docstring typos
  - Removed redundant `self.model_locator` storage

- `nvflare/app_opt/tf/job_config/base_fed_job.py`
  - Fixed 3 docstring typos

---

**Code hygiene improved!** 🧹
