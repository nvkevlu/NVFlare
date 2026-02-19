# XGBoost V1/V2 Cleanup Plan

## Date: 2026-01-15
## Status: Planning - For Future PR (Target: 2.8.0)

---

## Management Directive

From leadership comments:
> "We only have one algorithm. @YuanTingHsieh is going to remove the old V1 version and rename the v2 to histogram."

> "What are the options for the user to select? Histogram-based vs. tree-based? We might need a XGBoost algorithm type?"

---

## Current State

### Directory Structure
```
nvflare/app_opt/xgboost/
├── histogram_based/          # V1 (OLD - TO BE REMOVED)
│   ├── __init__.py
│   ├── constants.py
│   ├── controller.py
│   └── executor.py
│
├── histogram_based_v2/       # V2 (CURRENT - TO BE RENAMED)
│   ├── controller.py
│   ├── fed_controller.py
│   ├── executor.py
│   ├── fed_executor.py
│   ├── csv_data_loader.py
│   ├── adaptors/
│   ├── runners/
│   ├── sec/               # Secure/HE components
│   └── ...
│
└── tree_based/              # Tree-based algorithms (KEEP)
    ├── executor.py
    ├── bagging_aggregator.py
    └── ...
```

### Algorithm Options (Current)
In `XGBHistogramRecipe`, users can specify:
- `algorithm="histogram"` → Uses V1 (old)
- `algorithm="histogram_v2"` → Uses V2 (current, recommended)

**Problem:** This creates confusion and maintains legacy code.

---

## Cleanup Plan

### Phase 1: Add Deprecation Warnings (Immediate)

1. **Add deprecation warning to V1 imports**
   - File: `nvflare/app_opt/xgboost/histogram_based/__init__.py`
   - Action: Add `DeprecationWarning` when module is imported
   
   ```python
   import warnings
   
   warnings.warn(
       "The 'histogram_based' module (V1) is deprecated and will be removed in version 2.8.0. "
       "Please use 'histogram_based_v2' instead, or set algorithm='histogram_v2' in recipes.",
       DeprecationWarning,
       stacklevel=2
   )
   ```

2. **Add deprecation warning in recipe**
   - File: `nvflare/app_opt/xgboost/recipes/histogram.py`
   - Line: 187-190 (when `algorithm == "histogram"`)
   - Action: Add runtime warning
   
   ```python
   if self.algorithm == "histogram":
       warnings.warn(
           "algorithm='histogram' (V1) is deprecated and will be removed in version 2.8.0. "
           "Please use algorithm='histogram_v2' instead.",
           DeprecationWarning,
           stacklevel=2
       )
       # Original histogram-based implementation
       from nvflare.app_opt.xgboost.histogram_based.controller import XGBFedController
       from nvflare.app_opt.xgboost.histogram_based.executor import FedXGBHistogramExecutor
       # ...
   ```

3. **Update documentation**
   - Mark V1 as deprecated in all READMEs and docstrings
   - Recommend V2 as the default

### Phase 2: Remove V1 and Rename V2 (Version 2.8.0)

#### Step 1: Remove V1 Code
**Files to DELETE:**
```
nvflare/app_opt/xgboost/histogram_based/
├── __init__.py
├── constants.py
├── controller.py
└── executor.py
```

#### Step 2: Rename V2 Directory
**Rename:**
```bash
nvflare/app_opt/xgboost/histogram_based_v2/ 
→ 
nvflare/app_opt/xgboost/histogram_based/
```

**OR** (cleaner option):
```bash
nvflare/app_opt/xgboost/histogram_based_v2/
→
nvflare/app_opt/xgboost/histogram/
```

#### Step 3: Simplify Recipe Algorithm Parameter

**Before:**
```python
class XGBHistogramRecipe(Recipe):
    def __init__(
        self,
        algorithm: str = "histogram_v2",  # Options: "histogram" or "histogram_v2"
        ...
    ):
```

**After:**
```python
class XGBHistogramRecipe(Recipe):
    def __init__(
        self,
        # algorithm parameter REMOVED - only one implementation now
        ...
    ):
```

#### Step 4: Update Recipe Implementation

**File:** `nvflare/app_opt/xgboost/recipes/histogram.py`

**Lines to REMOVE:** 187-205 (entire V1 block)

**Lines to SIMPLIFY:** 206-236 (remove the `elif` check, make it the default)

**Before:**
```python
def configure(self):
    job = FedJob(name=self.name, min_clients=self.min_clients)
    
    # Configure controller and executor based on algorithm
    if self.algorithm == "histogram":
        # V1 code (lines 187-204)
        from nvflare.app_opt.xgboost.histogram_based.controller import XGBFedController
        from nvflare.app_opt.xgboost.histogram_based.executor import FedXGBHistogramExecutor
        # ...
    
    elif self.algorithm == "histogram_v2":
        # V2 code (lines 206-236)
        from nvflare.app_opt.xgboost.histogram_based_v2.fed_controller import XGBFedController
        from nvflare.app_opt.xgboost.histogram_based_v2.fed_executor import FedXGBHistogramExecutor
        # ...
```

**After:**
```python
def configure(self):
    job = FedJob(name=self.name, min_clients=self.min_clients)
    
    # Configure controller and executor (histogram-based)
    from nvflare.app_opt.xgboost.histogram.fed_controller import XGBFedController
    from nvflare.app_opt.xgboost.histogram.fed_executor import FedXGBHistogramExecutor
    
    controller_kwargs = {
        "num_rounds": self.num_rounds,
        "data_split_mode": 0,  # 0 = horizontal
        "secure_training": self.secure,
        "xgb_options": {"early_stopping_rounds": self.early_stopping_rounds, "use_gpus": self.use_gpus},
        "xgb_params": self.xgb_params,
    }
    # ... rest of simplified V2 code
```

#### Step 5: Update All Imports Across Codebase

**Files to Update (33 files found):**
```
nvflare/app_opt/xgboost/recipes/vertical.py
nvflare/app_opt/xgboost/recipes/histogram.py
nvflare/app_opt/xgboost/recipes/bagging.py
nvflare/app_opt/xgboost/histogram_based_v2/runners/xgb_eval_runner.py
nvflare/app_opt/xgboost/histogram_based_v2/fed_eval_executor.py
# ... (all 33 files that reference histogram_based_v2)
```

**Search/Replace:**
```python
# Old:
from nvflare.app_opt.xgboost.histogram_based_v2

# New:
from nvflare.app_opt.xgboost.histogram
```

#### Step 6: Update Examples

**Example files to update:**
- `examples/advanced/xgboost/fedxgb/job.py`
- `examples/advanced/xgboost/fedxgb/job_vertical.py`
- `examples/advanced/xgboost/fedxgb_secure/job.py`
- `examples/advanced/xgboost/fedxgb_secure/job_vertical.py`

**Change:**
```python
# Remove algorithm parameter
recipe = XGBHistogramRecipe(
    name="xgboost_horizontal",
    min_clients=args.site_num,
    num_rounds=args.num_rounds,
    # algorithm="histogram_v2",  # REMOVE THIS
    xgb_params=xgb_params,
    per_site_config=per_site_config,
)
```

#### Step 7: Update Tests

**Test files to update:**
- `tests/integration_test/test_xgb_histogram_recipe.py`
- `tests/integration_test/test_xgb_vertical_recipe.py`
- `tests/integration_test/test_xgb_secure_recipe.py`

**Actions:**
- Remove `algorithm` parameter from recipe instantiations
- Remove tests for V1 algorithm variant
- Update imports if needed

---

## User-Facing Algorithm Types

After cleanup, users will choose between **two main XGBoost training modes:**

### 1. Histogram-Based (Horizontal & Vertical)
**Recipes:**
- `XGBHistogramRecipe` - Horizontal federated learning
- `XGBVerticalRecipe` - Vertical federated learning

**Characteristics:**
- Uses histogram-based gradient boosting
- Supports secure training (Homomorphic Encryption)
- Efficient for large datasets
- Supports both horizontal and vertical data partitioning

**Usage:**
```python
from nvflare.app_opt.xgboost.recipes import XGBHistogramRecipe

recipe = XGBHistogramRecipe(
    name="my_job",
    min_clients=3,
    num_rounds=10,
    secure=True,  # Optional: Enable HE
    xgb_params={...},
    per_site_config={...},
)
```

### 2. Tree-Based (Bagging & Cyclic)
**Recipes:**
- `XGBBaggingRecipe` - Supports both bagging and cyclic modes

**Characteristics:**
- Uses tree-based gradient boosting
- Supports bagging (ensemble) and cyclic (sequential) training modes
- Different aggregation strategy than histogram-based

**Usage:**
```python
from nvflare.app_opt.xgboost.recipes import XGBBaggingRecipe

recipe = XGBBaggingRecipe(
    name="my_job",
    min_clients=3,
    training_mode="bagging",  # or "cyclic"
    num_rounds=5,
    per_site_config={...},
)
```

---

## Validation Checklist for 2.8.0 Release

- [ ] V1 directory removed (`histogram_based/`)
- [ ] V2 directory renamed to `histogram/` or remains `histogram_based/`
- [ ] All imports updated across codebase (33+ files)
- [ ] Recipe simplified (no `algorithm` parameter)
- [ ] Examples updated (4 job files)
- [ ] Tests updated (3+ test files)
- [ ] Documentation updated (READMEs, docstrings)
- [ ] No deprecation warnings in test runs
- [ ] All integration tests pass
- [ ] Backward compatibility guide written for users migrating from V1

---

## Migration Guide for Users (Draft for 2.8.0 Release Notes)

### Breaking Change: XGBoost V1 Removed

**What Changed:**
- The old histogram-based implementation (V1) has been removed
- The `algorithm` parameter in `XGBHistogramRecipe` has been removed
- V2 is now the only histogram implementation

**Before (2.7.x):**
```python
recipe = XGBHistogramRecipe(
    algorithm="histogram_v2",  # Had to specify
    ...
)
```

**After (2.8.0+):**
```python
recipe = XGBHistogramRecipe(
    # No algorithm parameter needed
    ...
)
```

**Action Required:**
- Remove `algorithm="histogram_v2"` from your code
- If using `algorithm="histogram"` (V1), update to V2 before upgrading
- Update any direct imports from `nvflare.app_opt.xgboost.histogram_based_v2`

---

## References

**Key Files:**
- Recipe: `nvflare/app_opt/xgboost/recipes/histogram.py:187-236`
- V1 Imports: Line 189-190
- V2 Imports: Line 208-209

**Related Issues:**
- Management comment: "Remove old V1 version and rename v2 to histogram"
- User confusion about algorithm selection
- Code duplication and maintenance burden

**Assigned To:** @YuanTingHsieh

---

## Notes

1. **Why This Cleanup?**
   - Reduces confusion for users
   - Eliminates legacy code maintenance
   - Simplifies documentation
   - Aligns with "one recommended way" philosophy

2. **Risk Assessment:**
   - **Low Risk:** V2 has been recommended for a while
   - **Migration Path:** Clear deprecation warnings in current version
   - **Documentation:** Will provide migration guide

3. **Timeline:**
   - **Now:** Add deprecation warnings
   - **2.8.0:** Remove V1, rename V2

4. **Communication:**
   - Release notes must clearly state breaking change
   - Migration guide must be included
   - Update "What's New" section
