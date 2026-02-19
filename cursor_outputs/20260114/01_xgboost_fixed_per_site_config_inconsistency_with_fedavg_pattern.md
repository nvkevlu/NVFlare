# CRITICAL FIX: XGBoost Recipes Refactored to Use per_site_config

**Date:** January 14, 2026  
**Severity:** CRITICAL - Inconsistency with established pattern  
**Status:** ✅ FIXED  

---

## The Mistake

I (the AI assistant) created XGBoost recipes on January 13, 2026 using an **incorrect pattern** (`add_dataloader()` / `add_to_client()`) instead of following the **correct `per_site_config` pattern** that Yuan-Ting had established earlier that same day for sklearn recipes.

### Root Cause
- **Failed to check recent commits** for similar work before implementing
- **Did not follow established consistency patterns**
- **Created inconsistent API** across different recipe types

---

## What Was Wrong

### Incorrect Pattern (What I Did)
```python
recipe = XGBHistogramRecipe(...)
for site_id in range(1, 3):
    dataloader = CSVDataLoader(...)
    recipe.add_dataloader(dataloader, site_name=f"site-{site_id}")  # WRONG!
```

### Correct Pattern (sklearn, established by Yuan-Ting)
```python
recipe = KMeansFedAvgRecipe(
    per_site_config={
        "site-1": {"data_loader": CSVDataLoader(...)},
        "site-2": {"data_loader": CSVDataLoader(...)},
    }
)
```

---

## Files Fixed

### Recipes (3 files)
1. ✅ `nvflare/app_opt/xgboost/recipes/histogram.py`
2. ✅ `nvflare/app_opt/xgboost/recipes/vertical.py`
3. ✅ `nvflare/app_opt/xgboost/recipes/bagging.py`

### Examples (4 files)
4. ✅ `examples/advanced/xgboost/fedxgb/job.py`
5. ✅ `examples/advanced/xgboost/fedxgb/job_vertical.py`
6. ✅ `examples/advanced/xgboost/fedxgb/job_tree.py`
7. ✅ `examples/advanced/xgboost/fedxgb_secure/job.py`

### Tests (3 files)
8. ✅ `tests/integration_test/test_xgb_histogram_recipe.py`
9. ✅ `tests/integration_test/test_xgb_vertical_recipe.py`
10. ✅ `tests/integration_test/test_xgb_bagging_recipe.py`

### Documentation (2 files)
11. ✅ `examples/advanced/xgboost/fedxgb/README.md`
12. ✅ `examples/advanced/xgboost/fedxgb_secure/README.md`

**Total: 12 files refactored**

---

## Changes Made

### 1. Recipe Classes
**Added `per_site_config` parameter:**
```python
def __init__(
    self,
    ...
    per_site_config: Optional[dict[str, dict]] = None,
):
```

**Removed methods:**
- ❌ `add_dataloader(dataloader, site_name=None)`
- ❌ `add_to_client(site_name, dataloader)` 
- ❌ `add_executor_to_client(site_name, lr_scale)` (XGBBaggingRecipe)

**Added logic in `configure()`:**
```python
if self.per_site_config:
    for site_name, site_config in self.per_site_config.items():
        data_loader = site_config.get("data_loader")
        if data_loader is None:
            raise ValueError(f"per_site_config for '{site_name}' must include 'data_loader' key")
        job.to(data_loader, site_name, id=self.data_loader_id)
```

### 2. Example Job Files
**Before:**
```python
recipe = XGBHistogramRecipe(...)
for site_id in range(1, 3):
    dataloader = CSVDataLoader(...)
    recipe.add_dataloader(dataloader, site_name=f"site-{site_id}")
```

**After:**
```python
per_site_config = {}
for site_id in range(1, 3):
    dataloader = CSVDataLoader(...)
    per_site_config[f"site-{site_id}"] = {"data_loader": dataloader}

recipe = XGBHistogramRecipe(..., per_site_config=per_site_config)
```

### 3. XGBBaggingRecipe (Special Case)
Supports optional `lr_scale` in per_site_config:
```python
per_site_config = {
    "site-1": {"data_loader": CSVDataLoader(...), "lr_scale": 0.5},
    "site-2": {"data_loader": CSVDataLoader(...), "lr_scale": 0.3},
}
```

### 4. Integration Tests
**Before:**
```python
recipe = XGBHistogramRecipe(...)
for site_id in range(1, 3):
    recipe.add_dataloader(MockXGBDataLoader(), site_name=f"site-{site_id}")
```

**After:**
```python
per_site_config = {
    f"site-{site_id}": {"data_loader": MockXGBDataLoader()}
    for site_id in range(1, 3)
}
recipe.per_site_config = per_site_config
recipe.job = recipe.configure()
```

---

## Why This Matters

### Consistency is Critical
1. **User Experience**: Users expect consistent APIs across all recipes
2. **Maintainability**: One pattern is easier to maintain than multiple patterns
3. **Documentation**: Consistent patterns are easier to document and explain
4. **Learning Curve**: Users learning one recipe can apply knowledge to others

### The Correct Pattern (per_site_config)
- ✅ Matches sklearn recipes (established pattern)
- ✅ Declarative configuration (all config in one place)
- ✅ Easier to serialize/deserialize
- ✅ Cleaner separation of concerns
- ✅ Follows Python best practices (configuration over imperative calls)

### The Wrong Pattern (add_dataloader)
- ❌ Inconsistent with sklearn
- ❌ Imperative (requires method calls after construction)
- ❌ Harder to serialize
- ❌ Mixes configuration with object mutation
- ❌ Created technical debt

---

## Lessons Learned

1. **Always check recent commits** before implementing new features
2. **Consistency is a top priority** - it's not optional
3. **Follow established patterns** even if you think there's a "better" way
4. **Document design decisions** in cursor_outputs immediately
5. **When in doubt, ask** rather than assuming

---

## Verification

All changes have been:
- ✅ Implemented across all 12 files
- ✅ Linter checks passed
- ✅ Consistent with sklearn pattern
- ✅ Documented in this file

---

## Apology

I sincerely apologize for this mistake. Consistency was explicitly stated as the top priority, and I failed to ensure it. This required significant rework and wasted time. I will be more diligent about checking for established patterns before implementing new features.

---

## Additional Consistency Fix: PSI Recipe Usage

**Date:** January 14, 2026

During the per_site_config refactor, another consistency issue was identified:

### Issue
`examples/advanced/xgboost/fedxgb/job_vertical.py` was manually creating the PSI job using FedJob API instead of using the existing `DhPSIRecipe`.

### Fix
Updated `run_psi_job()` function to use `DhPSIRecipe` from `nvflare.app_common.psi.recipes.dh_psi`, consistent with the pattern used in `examples/advanced/psi/user_email_match/`.

**Changes:**
- Removed manual FedJob creation and component additions
- Replaced with `DhPSIRecipe` initialization
- Simplified imports by removing unused PSI components
- Recipe handles all controller, executor, task handler, and writer setup internally

**Files Modified:**
- `examples/advanced/xgboost/fedxgb/job_vertical.py` (imports and `run_psi_job` function)

**Result:** Consistent with established PSI recipe pattern, reduced code complexity.

---

**Fixed by:** AI Assistant
**Reviewed by:** User  
**Date Completed:** January 14, 2026
