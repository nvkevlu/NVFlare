# Final Cleanup: Removed All data_loader Parameter References

**Date**: 2026-02-02  
**Status**: ✅ COMPLETE  
**Branch**: 2.7

## Issue

After reverting to per_site_config only, docstrings still contained references to the removed `data_loader` parameter, including:
- Parameter documentation for `data_loader (XGBDataLoader, optional)`
- Mutual exclusivity warnings ("Cannot be used together with per_site_config")
- Either/or notes ("Either data_loader OR per_site_config must be provided")
- Old SimEnv pattern (`SimEnv(num_clients=2)` instead of `SimEnv(clients=list)`)

## Changes Made

### 1. `nvflare/app_opt/xgboost/recipes/histogram.py`

**Removed from docstring:**
```python
# BEFORE:
data_loader (XGBDataLoader, optional): Default data loader applied to all clients.
    Use this when all clients can share the same data loader configuration.
    Cannot be used together with per_site_config.
per_site_config (dict, optional): Per-site configuration mapping site names to config dicts.
    Each config dict must contain 'data_loader' key with XGBDataLoader instance.
    Use this when each client needs different data loader configuration.
    Cannot be used together with data_loader.
    Example: {"site-1": {"data_loader": CSVDataLoader(...)}, "site-2": {...}}

Note:
    Either data_loader OR per_site_config must be provided (but not both)
```

**Changed to:**
```python
# AFTER:
per_site_config (dict): Per-site configuration mapping site names to config dicts.
    Each config dict must contain 'data_loader' key with XGBDataLoader instance.
    Example: {"site-1": {"data_loader": CSVDataLoader(...)}, "site-2": {...}}
```

**Updated example docstring:**
```python
# BEFORE:
recipe = XGBHorizontalRecipe(
    name="xgb_higgs_horizontal",
    min_clients=2,
    num_rounds=100,
    xgb_params={...},
    per_site_config={
        "site-1": {"data_loader": CSVDataLoader(...)},
        "site-2": {"data_loader": CSVDataLoader(...)}
    }
)

env = SimEnv(num_clients=2)
run = recipe.execute(env)
```

**Changed to:**
```python
# AFTER:
# Build per-site configuration with data loaders
per_site_config = {
    "site-1": {"data_loader": CSVDataLoader(...)},
    "site-2": {"data_loader": CSVDataLoader(...)},
}

# Create recipe
recipe = XGBHorizontalRecipe(
    name="xgb_higgs_horizontal",
    min_clients=2,
    num_rounds=100,
    xgb_params={...},
    per_site_config=per_site_config,
)

# Run simulation with explicit client list
clients = list(per_site_config.keys())
env = SimEnv(clients=clients)
run = recipe.execute(env)
```

### 2. `nvflare/app_opt/xgboost/recipes/vertical.py`

**Updated example docstring:**
```python
# BEFORE:
env = SimEnv(num_clients=2)
run = recipe.execute(env)
```

**Changed to:**
```python
# AFTER:
# Step 3: Run with explicit client list
clients = list(per_site_config.keys())
env = SimEnv(clients=clients)
run = recipe.execute(env)
```

## Verification

✅ **All checks passed:**
```bash
✓ All docstring references cleaned up
✓ No linter errors
✓ Imports work correctly
✓ Parameters correctly removed
```

**Git diff now only shows:**
- ✅ Import statements moved to top (TBAnalyticsReceiver, TBWriter, ConvertToFedEvent, etc.)
- ✅ Component addition changed from `job.to_clients()` to per-site `job.to(site_name)`
- ✅ SimEnv usage changed from `num_clients=N` to `clients=list`
- ✅ Example docstrings updated to show complete per_site_config pattern
- ✅ Validation changed to require per_site_config

**No problematic references remaining:**
- ❌ No `data_loader (XGBDataLoader, optional)` parameter docs
- ❌ No "Cannot be used together with" warnings
- ❌ No "Either/or" notes
- ❌ No `SimEnv(num_clients=N)` in docstrings

## Summary

The revert is now **complete and clean**:
1. ✅ `data_loader` parameter removed from `__init__` signatures
2. ✅ `data_loader` parameter removed from docstrings
3. ✅ Mutual exclusivity logic removed
4. ✅ Only `per_site_config` remains (mandatory)
5. ✅ Examples show correct `SimEnv(clients=list)` pattern
6. ✅ All components added per-site (the real bug fix)

## Related Documents

- Summary: `00_SUMMARY_all_xgboost_fixes.md`
- Revert rationale: `04_xgboost_recipes_reverted_to_per_site_config_only.md`
