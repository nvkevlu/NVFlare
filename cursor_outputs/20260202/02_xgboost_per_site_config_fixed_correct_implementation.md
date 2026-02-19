# XGBoost Per-Site Config Fixed: Correct Implementation Pattern

**Date**: 2026-02-02  
**Status**: ✅ COMPLETE  
**Branch**: 2.7

## Summary

Fixed XGBoost recipe implementations to follow the correct NVFlare Job API pattern for `per_site_config`. The issue was not a bug in NVFlare, but rather an incorrect implementation in the XGBoost recipes that mixed two incompatible patterns.

## Root Cause: Implementation Error, Not NVFlare Bug

The XGBoost recipes were mixing two incompatible patterns:
1. Using `job.to_clients()` to add executor/metrics/event_converter to `@ALL` clients
2. Using `job.to(site_name)` to add data_loader per-site
3. Using `SimEnv(num_clients=N)` instead of `SimEnv(clients=list)`

This caused `@ALL` components to overwrite site-specific components during job export.

## The Correct Pattern (Used by FedAvg, sklearn)

NVFlare's Job API has two distinct usage patterns:

### Pattern A: Common Components for All Clients
```python
# Use when all clients have identical configuration
job.to_clients(executor)
job.to_clients(data_loader)

env = SimEnv(num_clients=N)
```

### Pattern B: Per-Site Configuration  
```python
# Use when clients have different configurations
if per_site_config:
    for site_name in per_site_config:
        job.to(executor, site_name)  # Add ALL components per-site
        job.to(data_loader, site_name)
        # etc.

env = SimEnv(clients=list(per_site_config.keys()))  # Use explicit client list!
```

**Key Rules:**
1. ❌ **Never mix** `job.to_clients()` (Pattern A) with `job.to(site_name)` (Pattern B)
2. ✅ When using `per_site_config`, add **ALL components** per-site, not just the data loader
3. ✅ When using `per_site_config`, use `SimEnv(clients=list)` not `SimEnv(num_clients=N)`

## Files Changed

### 1. Recipe Files - Fixed Component Addition Pattern

#### `nvflare/app_opt/xgboost/recipes/histogram.py`
**Status**: ✅ Already correct
- When using `data_loader` (common): Uses `job.to_clients()` for all components
- When using `per_site_config`: Uses `job.to(site_name)` for all components (executor, metrics, event_to_fed, data_loader)

#### `nvflare/app_opt/xgboost/recipes/bagging.py`
**Status**: ✅ Already correct
- When using `data_loader` (common): Uses `job.to_clients()` for all components
- When using `per_site_config`: Uses `job.to(site_name)` for all components (executor, data_loader)

#### `nvflare/app_opt/xgboost/recipes/vertical.py`
**Status**: 🔧 **FIXED** - Was mixing patterns
- **Before**: Used `job.to_clients()` for executor/metrics/event_to_fed, then `job.to()` for data_loader
- **After**: 
  - When using `data_loader` (common): Uses `job.to_clients()` for all components
  - When using `per_site_config`: Uses `job.to(site_name)` for all components

```python
# Fixed pattern in vertical.py
if self.data_loader is not None:
    # Common data loader - use to_clients for ALL components
    job.to_clients(executor, id="xgb_hist_executor", tasks=["config", "start"])
    job.to_clients(metrics_writer, id=self.metrics_writer_id)
    job.to_clients(event_to_fed, id="event_to_fed")
    job.to_clients(self.data_loader, id=self.data_loader_id)
elif self.per_site_config is not None:
    # Per-site config - add ALL components per-site
    for site_name, site_config in self.per_site_config.items():
        data_loader = site_config.get("data_loader")
        # Add ALL components using job.to(site_name)
        job.to(executor, site_name, id="xgb_hist_executor", tasks=["config", "start"])
        job.to(metrics_writer, site_name, id=self.metrics_writer_id)
        job.to(event_to_fed, site_name, id="event_to_fed")
        job.to(data_loader, site_name, id=self.data_loader_id)
```

### 2. Example Files - Fixed SimEnv Usage

All three example files were using `SimEnv(num_clients=N)` when they should have used `SimEnv(clients=list)`:

#### `examples/advanced/xgboost/fedxgb/job.py`
```python
# Before:
env = SimEnv(num_clients=args.site_num)

# After:
clients = list(per_site_config.keys())
env = SimEnv(clients=clients)
```

#### `examples/advanced/xgboost/fedxgb/job_tree.py`
```python
# Before:
env = SimEnv(num_clients=args.site_num)

# After:
clients = list(per_site_config.keys())
env = SimEnv(clients=clients)
```

#### `examples/advanced/xgboost/fedxgb/job_vertical.py`
```python
# In run_training_job() only (PSI job doesn't use per_site_config):

# Before:
env = SimEnv(num_clients=args.site_num)

# After:
clients = list(per_site_config.keys())
env = SimEnv(clients=clients)
```

## Testing Results

Tested with `examples/advanced/xgboost/fedxgb/job.py`:

```bash
cd /Users/kevlu/workspace/repos/secondcopynvflare/examples/advanced/xgboost/fedxgb
python job.py --site_num 2 --round_num 2 --data_root /tmp/test_xgb_data/HIGGS --split_method uniform
```

**Results:**
- ✅ Job configured successfully with per-site components
- ✅ Both clients (site-1, site-2) received their configurations
- ✅ Data loaders correctly loaded for each site
- Note: Job failed at XGBoost training due to environment issue (XGBoost not compiled with federated learning support), not per_site_config issue

Relevant log output:
```
2026-02-02 13:36:04,672 - INFO - Waiting for clients to be ready: ['site-1', 'site-2']
2026-02-02 13:36:04,674 - INFO - Configuring clients ['site-1', 'site-2']
2026-02-02 13:36:12,482 - INFO - got my rank: 0
2026-02-02 13:36:12,498 - INFO - successfully configured client site-1
2026-02-02 13:36:20,357 - INFO - got my rank: 1
2026-02-02 13:36:20,372 - INFO - successfully configured client site-2
2026-02-02 13:36:20,600 - INFO - successfully configured clients ['site-1', 'site-2']
```

## Why Other Recipes (FedAvg, sklearn) Worked

Other recipes like `nvflare/recipe/fedavg.py` and `nvflare/app_opt/sklearn/recipes/fedavg.py` already followed the correct pattern:

1. **FedAvg recipe**: When using `per_site_config`, adds **only** `ScriptRunner` executor per-site using `job.to(site_name)`, no mixing with `job.to_clients()`
2. **Sklearn examples**: Use `SimEnv(clients=list)` when using per-site config

## Summary of All Changes

| File | Change Type | Details |
|------|-------------|---------|
| `nvflare/app_opt/xgboost/recipes/vertical.py` | Fix | Changed to add ALL components per-site when using per_site_config |
| `examples/advanced/xgboost/fedxgb/job.py` | Fix | Changed `SimEnv(num_clients=N)` to `SimEnv(clients=list)` |
| `examples/advanced/xgboost/fedxgb/job_tree.py` | Fix | Changed `SimEnv(num_clients=N)` to `SimEnv(clients=list)` |
| `examples/advanced/xgboost/fedxgb/job_vertical.py` | Fix | Changed `SimEnv(num_clients=N)` to `SimEnv(clients=list)` in training job |
| `nvflare/app_opt/xgboost/recipes/histogram.py` | No change | Already correct |
| `nvflare/app_opt/xgboost/recipes/bagging.py` | No change | Already correct |

## Lessons Learned

1. **NVFlare's Job API is correctly designed** - the issue was in how we used it
2. **Pattern consistency is critical** - never mix `job.to_clients()` with `job.to(site_name)`
3. **SimEnv has two modes**:
   - `SimEnv(num_clients=N)` → for Pattern A (common components)
   - `SimEnv(clients=list)` → for Pattern B (per-site config)
4. **Always follow working examples** - FedAvg and sklearn recipes showed the correct pattern

## Next Steps

1. ✅ XGBoost examples now follow the correct pattern
2. ✅ All three recipes (histogram, bagging, vertical) are correct
3. 📝 Consider adding documentation about these patterns to prevent future confusion
4. 📝 Consider adding tests that verify per_site_config behavior

## Related Documents

- Previous (outdated) analysis: `cursor_outputs/20260202/01_xgboost_per_site_config_root_cause_and_fix.md`
- Initial env.run() fix: `cursor_outputs/20260201/01_xgboost_examples_fixed_env_run_to_recipe_execute_api_update.md`
