# XGBoost Recipe Naming Consistency Analysis

## Date: 2026-01-15
## Status: Proposal for Review

---

## Current State (Inconsistent)

```python
# Current naming:
from nvflare.app_opt.xgboost.recipes import (
    XGBHistogramRecipe,    # Histogram-based, HORIZONTAL split
    XGBVerticalRecipe,     # Histogram-based, VERTICAL split
    XGBBaggingRecipe,      # Tree-based, bagging/cyclic modes
)
```

**Problem:** Naming doesn't clearly communicate the data split mode at first glance.
- `XGBHistogramRecipe` → Not obvious it's horizontal
- `XGBVerticalRecipe` → Clear it's vertical, but no mention of algorithm
- `XGBBaggingRecipe` → Different algorithm family, but "bagging" is just one mode

---

## Key Differences Analysis

### XGBHistogramRecipe (Horizontal) vs XGBVerticalRecipe
**Similarities:**
- Both use histogram-based algorithm (histogram_based_v2)
- Both use same controller/executor family
- Both support secure training (HE)
- Both use per_site_config for data loaders
- Very similar structure

**Differences:**
| Feature | Horizontal | Vertical |
|---------|-----------|----------|
| `data_split_mode` | 0 | 1 |
| `label_owner` | Not used | **Required** parameter |
| `model_file_name` | Not used | Optional parameter |
| `in_process` | Optional (False default) | Optional (True default) |
| Data split | Different samples, same features | Same samples, different features |
| PSI required | No | **Yes** (must run first) |

**Could they be merged?**
- Technically yes, with a `split_mode` parameter
- BUT: Different use cases, different documentation needs
- label_owner is required for vertical, not applicable for horizontal
- Better UX to keep separate with clear names

**Recommendation:** Keep separate classes with consistent naming.

---

## Proposed Options

### Option 1: Longer, More Explicit Names
```python
from nvflare.app_opt.xgboost.recipes import (
    XGBHorizontalHistogramRecipe,  # Histogram-based, horizontal split
    XGBVerticalHistogramRecipe,    # Histogram-based, vertical split
    XGBTreeBasedRecipe,            # Tree-based (rename from Bagging)
)
```

**Pros:**
- Very explicit about both algorithm and split mode
- No ambiguity

**Cons:**
- Longer class names
- "Histogram" is implementation detail users don't need to know

### Option 2: Shorter, User-Focused Names ✅ RECOMMENDED
```python
from nvflare.app_opt.xgboost.recipes import (
    XGBHorizontalRecipe,   # Horizontal split (histogram-based)
    XGBVerticalRecipe,     # Vertical split (histogram-based)
    XGBTreeBasedRecipe,    # Tree-based (bagging/cyclic)
)
```

**Pros:**
- Clean, concise names
- Split mode is the primary user concern (not algorithm)
- Users care about "horizontal vs vertical", not "histogram vs tree"
- Consistent prefix pattern
- "Histogram" is implementation detail (already removed V1)

**Cons:**
- Slightly less explicit about algorithm
- But algorithm can be in docstring

---

## Recommendation: Option 2

### Why Option 2 is Better

1. **User Mental Model**
   - Users think: "Do I have horizontal or vertical data split?"
   - Users don't think: "Do I want histogram-based or tree-based algorithm?"
   - Algorithm is secondary to data split mode

2. **Consistency**
   - All follow pattern: `XGB{SplitMode}Recipe`
   - Or: `XGB{AlgorithmType}Recipe` for tree-based
   - Clean and predictable

3. **Simpler Names**
   - Shorter is better for common use
   - "Histogram" is implementation detail
   - Docstrings explain the algorithm

4. **Future-Proof**
   - If we later have other algorithms for horizontal/vertical, naming still makes sense
   - e.g., could add `XGBHorizontalTreeBasedRecipe` later if needed

---

## Implementation Plan

### Renaming Changes Required

#### 1. Recipe Classes
```python
# nvflare/app_opt/xgboost/recipes/histogram.py
- class XGBHistogramRecipe(Recipe):
+ class XGBHorizontalRecipe(Recipe):
    """XGBoost Horizontal Federated Learning Recipe (histogram-based)."""

# nvflare/app_opt/xgboost/recipes/vertical.py
# Already named XGBVerticalRecipe - NO CHANGE NEEDED! ✅

# nvflare/app_opt/xgboost/recipes/bagging.py
- class XGBBaggingRecipe(Recipe):
+ class XGBTreeBasedRecipe(Recipe):
    """XGBoost Tree-Based Recipe (supports Bagging and Cyclic modes)."""
```

#### 2. File Renaming (Optional, for consistency)
```bash
# Could rename files to match class names:
nvflare/app_opt/xgboost/recipes/histogram.py → horizontal.py
nvflare/app_opt/xgboost/recipes/bagging.py → tree_based.py
# vertical.py stays as-is
```

#### 3. __init__.py Exports
```python
# nvflare/app_opt/xgboost/recipes/__init__.py
from .horizontal import XGBHorizontalRecipe
from .vertical import XGBVerticalRecipe
from .tree_based import XGBTreeBasedRecipe

# Backward compatibility (optional, for deprecation period):
XGBHistogramRecipe = XGBHorizontalRecipe  # Deprecated alias
XGBBaggingRecipe = XGBTreeBasedRecipe      # Deprecated alias
```

#### 4. Update Examples
**Files to update:**
- `examples/advanced/xgboost/fedxgb/job.py`
- `examples/advanced/xgboost/fedxgb/job_vertical.py`
- `examples/advanced/xgboost/fedxgb/job_tree.py`
- `examples/advanced/xgboost/fedxgb_secure/job.py`
- `examples/advanced/xgboost/fedxgb_secure/job_vertical.py`
- All READMEs

**Change:**
```python
# Before:
from nvflare.app_opt.xgboost.recipes import XGBHistogramRecipe
recipe = XGBHistogramRecipe(...)

# After:
from nvflare.app_opt.xgboost.recipes import XGBHorizontalRecipe
recipe = XGBHorizontalRecipe(...)
```

#### 5. Update Tests
**Files to update:**
- `tests/integration_test/test_xgb_histogram_recipe.py` → `test_xgb_horizontal_recipe.py`
- `tests/integration_test/test_xgb_vertical_recipe.py` (no change to class, just imports)
- `tests/integration_test/test_xgb_bagging_recipe.py` → `test_xgb_tree_based_recipe.py`

#### 6. Update Documentation
- Update all docstrings
- Update README files
- Update any tutorial notebooks
- Update API reference docs

---

## Migration Strategy

### Approach 1: Hard Break (Recommended for pre-1.0 or major version)
- Rename classes immediately
- Update all examples and tests
- No backward compatibility
- Clear release notes

### Approach 2: Deprecation Period
- Keep old names as aliases with deprecation warnings
- Give users 1-2 releases to migrate
- Remove in version 2.9.0

**Recommendation:** Hard break if this is still pre-stable, otherwise deprecation period.

---

## Summary Table

| Current Name | New Name | Reason |
|-------------|----------|--------|
| `XGBHistogramRecipe` | `XGBHorizontalRecipe` | Clearer split mode indication |
| `XGBVerticalRecipe` | `XGBVerticalRecipe` | ✅ Already good! No change |
| `XGBBaggingRecipe` | `XGBTreeBasedRecipe` | More accurate (supports bagging + cyclic) |

---

## Validation Checklist (After Implementation)

- [ ] All recipe classes renamed
- [ ] Files renamed (optional)
- [ ] __init__.py updated with exports
- [ ] All examples updated (6+ files)
- [ ] All tests updated and renamed
- [ ] All READMEs updated
- [ ] Docstrings updated
- [ ] No import errors
- [ ] All tests pass
- [ ] Release notes prepared

---

## User-Facing Result

**Before (Inconsistent):**
```python
from nvflare.app_opt.xgboost.recipes import (
    XGBHistogramRecipe,  # Wait, is this horizontal or vertical?
    XGBVerticalRecipe,   # Ah, vertical!
    XGBBaggingRecipe,    # What if I want cyclic mode?
)
```

**After (Clean & Consistent):**
```python
from nvflare.app_opt.xgboost.recipes import (
    XGBHorizontalRecipe,  # Clear: horizontal data split
    XGBVerticalRecipe,    # Clear: vertical data split
    XGBTreeBasedRecipe,   # Clear: tree-based algorithm (both modes)
)

# Usage is obvious:
if my_data_is_horizontally_split:
    recipe = XGBHorizontalRecipe(...)
elif my_data_is_vertically_split:
    recipe = XGBVerticalRecipe(...)
else:  # Tree-based approach
    recipe = XGBTreeBasedRecipe(training_mode="bagging")  # or "cyclic"
```

**Much better user experience!** 🎉
