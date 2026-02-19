# XGBoost Recipes: Reverted to per_site_config Only Pattern

**Date**: 2026-02-02  
**Status**: ✅ COMPLETE  
**Branch**: 2.7

## Summary

Reverted `histogram.py` and `vertical.py` to use **only** `per_site_config` parameter (removed the `data_loader` parameter we previously added). This simplifies the API and aligns with actual federated learning usage patterns.

## Why We Reverted

### Commenter's Feedback

The reviewer correctly pointed out that:
1. **The original design was simpler**: Only `per_site_config`, no separate `data_loader` parameter
2. **Our `data_loader` addition was unnecessary**: Common data loader for all sites doesn't match real FL use cases
3. **Better approach**: Keep only `per_site_config`, but allow it to override ANY executor parameter

### Analysis: Why per_site_config Only Makes Sense

**In Federated Learning:**
- Each site has **different data** (that's the fundamental point of FL!)
- All XGBoost examples use per-site data loaders loading different data files
- A common `data_loader` for all sites loading identical data is not a real FL scenario

**Example from all working examples:**
```python
for site_id in range(1, args.site_num + 1):
    data_loader = HIGGSDataLoader(data_split_filename=f"data_site-{site_id}.json")  # Different file per site!
    per_site_config[site_name] = {"data_loader": data_loader}
```

**Benefits of per_site_config only:**
1. **Simpler API**: One way to configure, not two mutually exclusive ways
2. **Matches real usage**: All examples already use per_site_config
3. **More extensible**: Can support overriding ANY executor parameter per-site:
   ```python
   per_site_config[site] = {
       "data_loader": my_loader,           # Required
       "per_msg_timeout": 120.0,           # Optional override
       "in_process": False,                # Optional override
   }
   ```
4. **Consistent with other recipes**: FedAvg and sklearn recipes use this pattern

## Changes Made

### 1. `nvflare/app_opt/xgboost/recipes/histogram.py`

**Removed:**
- `data_loader: Optional["XGBDataLoader"] = None` parameter from `__init__`
- `self.data_loader` instance variable
- Validation logic for mutual exclusivity of `data_loader` and `per_site_config`
- `if self.data_loader is not None:` branch (common data loader code path)

**Kept:**
- `per_site_config: Optional[dict[str, dict]] = None` parameter
- Per-site component addition pattern (the actual bug fix)
- `SimEnv(clients=list)` usage in examples

**Result:**
```python
def __init__(
    self,
    # ... other params ...
    per_site_config: Optional[dict[str, dict]] = None,  # Only this, no data_loader
):
    # Validate per_site_config is required
    if per_site_config is None:
        raise ValueError(
            "per_site_config is required for XGBHorizontalRecipe. "
            "Each site must specify a 'data_loader' in the config dictionary."
        )
    
    # Add all components per site
    for site_name, site_config in self.per_site_config.items():
        data_loader = site_config.get("data_loader")
        # ... add executor, metrics, event_to_fed, data_loader per site
```

### 2. `nvflare/app_opt/xgboost/recipes/vertical.py`

**Same changes as histogram.py:**
- Removed `data_loader` parameter
- Removed mutual exclusivity validation
- Kept only `per_site_config` branch
- Made `per_site_config` mandatory

### 3. `nvflare/app_opt/xgboost/recipes/bagging.py`

**No changes needed** - already followed the correct pattern:
- Only uses `per_site_config`
- Already supports per-site override of `lr_scale` parameter
- Shows the extensibility pattern we want

## Verification

✅ **All checks passed:**
```
✓ Imports successful
✓ histogram.py: data_loader parameter removed
✓ vertical.py: data_loader parameter removed
✓ No linter errors
```

**Parameter lists after revert:**
- **Histogram**: `['self', 'name', 'min_clients', 'num_rounds', 'early_stopping_rounds', 'use_gpus', 'secure', 'client_ranks', 'xgb_params', 'data_loader_id', 'metrics_writer_id', 'per_site_config']`
- **Vertical**: `['self', 'name', 'min_clients', 'num_rounds', 'label_owner', 'early_stopping_rounds', 'use_gpus', 'secure', 'client_ranks', 'xgb_params', 'data_loader_id', 'metrics_writer_id', 'in_process', 'model_file_name', 'per_site_config']`

## What Remains Fixed

The **real bug fix** (per-site component addition pattern) remains intact:
- ✅ All components (executor, metrics, event_to_fed, data_loader) added per-site using `job.to(site_name)`
- ✅ No mixing of `job.to_clients()` and `job.to(site_name)` patterns
- ✅ Uses `SimEnv(clients=list(per_site_config.keys()))` in examples

## Future Enhancement: Per-Site Executor Parameter Overrides

Following the `bagging.py` pattern with `lr_scale`, we can extend per_site_config to support overriding ANY executor parameter:

```python
# Example usage:
per_site_config = {
    "site-1": {
        "data_loader": loader1,
        "per_msg_timeout": 120.0,    # Override default timeout for slow site
        "in_process": False,          # Run out-of-process for this site
    },
    "site-2": {
        "data_loader": loader2,       # Uses default timeout and in_process
    }
}

# Implementation pattern (from bagging.py):
for site_name, site_config in self.per_site_config.items():
    data_loader = site_config.get("data_loader")  # Required
    per_msg_timeout = site_config.get("per_msg_timeout", self.default_timeout)  # Optional
    in_process = site_config.get("in_process", self.in_process)  # Optional
    
    executor = FedXGBHistogramExecutor(
        data_loader_id=self.data_loader_id,
        per_msg_timeout=per_msg_timeout,  # Use site-specific or default
        in_process=in_process,            # Use site-specific or default
    )
    job.to(executor, site_name, id="xgb_executor")
```

## Comparison with Other NVFlare Recipes

This aligns with how other recipes work:

**FedAvg Recipe** (`nvflare/recipe/fedavg.py`):
- Only has `per_site_config` for client customization
- No "common" parameter for all clients
- Allows per-site override of train_script, train_args, etc.

**Sklearn Recipes**:
- Use `per_site_config` for site-specific train arguments
- No common parameters

## Summary of Changes Across All Files

| File | Change | Status |
|------|--------|--------|
| `histogram.py` | Removed `data_loader` param, kept `per_site_config` only | ✅ Complete |
| `vertical.py` | Removed `data_loader` param, kept `per_site_config` only | ✅ Complete |
| `bagging.py` | No changes needed - already correct | ✅ Correct |
| Examples (`job.py`, `job_tree.py`, `job_vertical.py`) | No changes needed - already use per_site_config | ✅ Correct |
| `README.md` | No changes needed - already shows per_site_config usage | ✅ Correct |

## Related Documents

- Initial per_site_config fix: `cursor_outputs/20260202/02_xgboost_per_site_config_fixed_correct_implementation.md`
- env.run() fix: `cursor_outputs/20260201/01_xgboost_examples_fixed_env_run_to_recipe_execute_api_update.md`
- shap/matplotlib fix: `cursor_outputs/20260202/03_xgboost_shap_matplotlib_optional_import_fix.md`
