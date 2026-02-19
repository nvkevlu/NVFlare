# Fixed: Made shap and matplotlib Optional Imports in XGBoost Runner

**Date**: 2026-02-02  
**Status**: ✅ COMPLETE  
**Branch**: 2.7

## Issue

CI tests were failing with:
```
ModuleNotFoundError: No module named 'shap'
```

When importing `nvflare.app_opt.xgboost` modules, the import chain triggered:
```
nvflare.app_opt.xgboost
  → recipes.histogram
    → histogram_based_v2.fed_executor
      → histogram_based_v2.runners.xgb_client_runner
        → import shap  # FAILED
        → import matplotlib.pyplot  # Would also fail
```

## Root Cause

`shap` and `matplotlib` were imported at module level in `xgb_client_runner.py` but:
1. Not listed in `setup.cfg` dependencies
2. Only used for explainability features (SHAP plots)
3. Only needed in horizontal mode (`data_split_mode == 0`)

This broke tests that import XGBoost modules without having these packages installed.

## Solution

Made `shap` and `matplotlib` imports **lazy** - only import when actually needed for explainability plots.

### Changes to `nvflare/app_opt/xgboost/histogram_based_v2/runners/xgb_client_runner.py`

**Before:**
```python
import matplotlib.pyplot as plt
import shap
import xgboost as xgb

# ... later in code ...
if self._data_split_mode == 0:
    explainer = shap.TreeExplainer(bst)
    explanation = explainer(val_data)
    shap.plots.beeswarm(explanation, show=False)
    img = plt.gcf()
    # ...
```

**After:**
```python
import xgboost as xgb
# Removed top-level imports of shap and matplotlib

# ... later in code ...
if self._data_split_mode == 0:
    try:
        import matplotlib.pyplot as plt
        import shap

        explainer = shap.TreeExplainer(bst)
        explanation = explainer(val_data)
        shap.plots.beeswarm(explanation, show=False)
        img = plt.gcf()
        # ...
    except ImportError:
        xgb.collective.communicator_print(
            "Warning: shap and/or matplotlib not installed. Skipping explainability plots.\n"
        )
```

## Benefits

1. ✅ **Tests pass**: XGBoost modules can be imported without `shap`/`matplotlib`
2. ✅ **Graceful degradation**: If packages are missing, training still works, just skips explainability plots
3. ✅ **Clear messaging**: Users see a warning if explainability features are skipped
4. ✅ **Follows NVFlare patterns**: Same try/except ImportError pattern used elsewhere (e.g., `quantile_stats.py`)

## Testing

Verified that:
- ✅ Module imports successfully without `shap`/`matplotlib`
- ✅ No syntax or linter errors
- ✅ Warning message appears if explainability features are unavailable

## Alternative Solutions Considered

1. **Add to setup.cfg**: Would force all users to install `shap`/`matplotlib` even if they don't need explainability
2. **Create separate extras_require**: More complex, and these are truly optional features
3. **Remove explainability code**: Would lose useful feature

## Notes

- Explainability plots are only generated in **horizontal** XGBoost mode (`data_split_mode == 0`)
- Vertical mode and tree-based modes are unaffected
- Users who want SHAP plots should install: `pip install shap matplotlib`

## Related

- This issue surfaced because recipe imports were restructured during the per_site_config fix
- See: `cursor_outputs/20260202/02_xgboost_per_site_config_fixed_correct_implementation.md`
