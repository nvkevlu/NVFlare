# XGBoost Recipe Rename: XGBHistogramRecipe → XGBHorizontalRecipe

## Date: 2026-01-15
## Status: ✅ COMPLETE

---

## Summary

Successfully renamed `XGBHistogramRecipe` to `XGBHorizontalRecipe` to achieve naming consistency with `XGBVerticalRecipe`, as requested in PR feedback.

---

## PR Feedback Addressed

**Original Comment:**
> "If differ by just a Boolean I don't think should be 2 classes.  
> But if more yeah it becomes subjective.  
> If so can you rename them to be consistent:  
> XGBHorizontalHistogramRecipe and XGBVerticalHistogramRecipe  
> **OR**  
> XGBHorizontalRecipe and XGBVerticalRecipe"

**Decision:** Option 2 (shorter names)
- ✅ `XGBHorizontalRecipe` (renamed from `XGBHistogramRecipe`)
- ✅ `XGBVerticalRecipe` (already correct)
- ✅ `XGBBaggingRecipe` (unchanged - different algorithm family)

---

## Files Modified

### 1. Recipe Implementation (2 files)

**`nvflare/app_opt/xgboost/recipes/histogram.py`**
- ✅ Renamed class: `XGBHistogramRecipe` → `XGBHorizontalRecipe`
- ✅ Updated docstring title
- ✅ Updated example code in docstring
- ✅ Changed example job name: `xgb_higgs_histogram` → `xgb_higgs_horizontal`

**`nvflare/app_opt/xgboost/recipes/__init__.py`**
- ✅ Updated import: `from .histogram import XGBHorizontalRecipe`
- ✅ Updated `__all__` export list

### 2. Examples (4 files)

**`examples/advanced/xgboost/fedxgb/job.py`**
- ✅ Updated import statement
- ✅ Updated recipe instantiation

**`examples/advanced/xgboost/fedxgb_secure/job.py`**
- ✅ Updated import statement
- ✅ Updated recipe instantiation

**`examples/advanced/xgboost/fedxgb/README.md`**
- ✅ Updated text: "use the `XGBHorizontalRecipe`"
- ✅ Updated import statement in code example
- ✅ Updated recipe instantiation in code example
- ✅ Updated job name in example

**`examples/advanced/xgboost/fedxgb_secure/README.md`**
- ✅ Updated feature list text
- ✅ Updated import statement (2 places)
- ✅ Updated recipe instantiation
- ✅ Updated inline code reference

### 3. Tests (1 file)

**`tests/integration_test/test_xgb_histogram_recipe.py`**
- ✅ Updated import statement
- ✅ Updated module docstring (2 places)
- ✅ Renamed test class: `TestXGBHistogramRecipe` → `TestXGBHorizontalRecipe`
- ✅ Updated all recipe instantiations (4 places)

---

## Result: Consistent Naming

### Before (Inconsistent):
```python
from nvflare.app_opt.xgboost.recipes import (
    XGBHistogramRecipe,  # Algorithm-focused name
    XGBVerticalRecipe,   # Split-mode-focused name
    XGBBaggingRecipe,    # Different algorithm
)
```

### After (Consistent):
```python
from nvflare.app_opt.xgboost.recipes import (
    XGBHorizontalRecipe,  # ✅ Split-mode-focused, consistent
    XGBVerticalRecipe,    # ✅ Already good
    XGBBaggingRecipe,     # ✅ Different algorithm family
)
```

---

## Why Keep Separate Classes?

The PR comment asked: "If differ by just a Boolean I don't think should be 2 classes."

**Analysis:** Horizontal and Vertical differ by **more than a boolean**:

| Feature | Horizontal | Vertical |
|---------|-----------|----------|
| `data_split_mode` | 0 | 1 |
| `label_owner` | ❌ Not used | ✅ **Required parameter** |
| PSI preprocessing | ❌ Not needed | ✅ **Required** |
| Use case | Different samples, same features | Same samples, different features |
| Workflow | Direct training | PSI → Training |

**Conclusion:** Different enough to warrant separate classes with clear names.

---

## User Experience

### Clear Intent:
```python
# Horizontal data split (different samples per client)
recipe = XGBHorizontalRecipe(
    name="my_horizontal_job",
    min_clients=3,
    num_rounds=10,
    xgb_params={...},
    per_site_config={...},
)

# Vertical data split (different features per client)
recipe = XGBVerticalRecipe(
    name="my_vertical_job",
    min_clients=3,
    num_rounds=10,
    label_owner="site-1",  # Required for vertical
    xgb_params={...},
    per_site_config={...},
)
```

**Users immediately understand which to use based on their data split!**

---

## Validation

### Linter Check:
✅ No errors (only expected xgboost import warning in test file)

### Files Updated:
- ✅ 2 recipe files
- ✅ 2 example job.py files
- ✅ 2 README files
- ✅ 1 test file
- ✅ Total: 7 files

### Remaining References:
- Only in documentation/cursor_outputs (historical records)
- No functional code uses old name

---

## Migration Notes (If Needed)

If users have existing code using `XGBHistogramRecipe`:

**Before:**
```python
from nvflare.app_opt.xgboost.recipes import XGBHistogramRecipe
recipe = XGBHistogramRecipe(...)
```

**After:**
```python
from nvflare.app_opt.xgboost.recipes import XGBHorizontalRecipe
recipe = XGBHorizontalRecipe(...)
```

Simple find-and-replace: `XGBHistogramRecipe` → `XGBHorizontalRecipe`

---

## Summary

✅ **Renamed:** `XGBHistogramRecipe` → `XGBHorizontalRecipe`  
✅ **Consistent naming** with `XGBVerticalRecipe`  
✅ **All examples updated**  
✅ **All tests updated**  
✅ **All documentation updated**  
✅ **No linter errors**  
✅ **PR feedback addressed**

The naming now clearly communicates the data split mode (horizontal vs vertical) rather than the algorithm implementation detail (histogram), making it more intuitive for users.
