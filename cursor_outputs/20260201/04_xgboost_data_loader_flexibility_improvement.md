# XGBoost Data Loader Flexibility Improvement

**Date:** February 2, 2026  
**Issue:** Improved data loader configuration to support both common and site-specific patterns  
**Type:** Enhancement  
**Status:** ✅ COMPLETE  

---

## The Problem

### User's Initial Report
> "the per-site config doesn't seem to be working correctly. I get data loader being None"

### Root Cause
The original design had **no validation** - recipes would silently accept missing `per_site_config` and create broken jobs where data loaders were never added.

### Initial Fix Attempt ❌
My first attempt was to make `per_site_config` **mandatory**, but the user correctly pointed out this was too restrictive:

> "should per_site_config be mandatory? are there defaults for which this system could work without it?"

### The Real Issue
Looking at the codebase, I found two conflicting patterns:

**Pattern 1: CSVDataLoader - Designed for Common Config**
```python
class CSVDataLoader(XGBDataLoader):
    def __init__(self, folder: str):
        """This data loader automatically handles site-specific data loading.
        Even though you pass the same folder path to all clients, each client
        will load its own data based on its client_id (injected at runtime).
        """
        self.folder = folder
    
    def load_data(self):
        train_path = f"{self.folder}/{self.client_id}/train.csv"  # Uses self.client_id!
```

**Pattern 2: HIGGSDataLoader - Requires Site-Specific Config**
```python
class HIGGSDataLoader(XGBDataLoader):
    def __init__(self, data_split_filename):
        """Each site needs different file path"""
        self.data_split_filename = data_split_filename  # Site-specific!
```

**The Problem:** The recipe API only supported `per_site_config`, which was:
- ✅ Perfect for HIGGSDataLoader (site-specific paths)
- ❌ Unnecessarily verbose for CSVDataLoader (same config repeated for each site)

---

## The Solution: Support Both Patterns

### New Flexible API

Add optional `data_loader` parameter alongside `per_site_config`:

```python
class XGBHorizontalRecipe:
    def __init__(
        self,
        name: str,
        min_clients: int,
        num_rounds: int,
        ...
        data_loader: Optional[XGBDataLoader] = None,          # NEW: Common config
        per_site_config: Optional[dict[str, dict]] = None,    # Existing: Site-specific
    ):
```

**Rules:**
1. Must provide EITHER `data_loader` OR `per_site_config` (not both, not neither)
2. `data_loader` → Applied to all clients (simpler for common configs)
3. `per_site_config` → Site-specific (more flexible for different configs)

---

## Usage Examples

### Pattern 1: Common Data Loader (NEW - Simpler!)

Use when all clients can share the same configuration:

```python
from nvflare.app_opt.xgboost.recipes import XGBHorizontalRecipe
from nvflare.app_opt.xgboost.histogram_based_v2.csv_data_loader import CSVDataLoader

recipe = XGBHorizontalRecipe(
    name="xgb_horizontal",
    min_clients=3,
    num_rounds=100,
    data_loader=CSVDataLoader(folder="/tmp/data"),  # ← Applied to all clients!
)

# At runtime:
# - site-1 loads: /tmp/data/site-1/train.csv
# - site-2 loads: /tmp/data/site-2/train.csv  
# - site-3 loads: /tmp/data/site-3/train.csv
```

**Before (verbose):**
```python
per_site_config={
    "site-1": {"data_loader": CSVDataLoader(folder="/tmp/data")},
    "site-2": {"data_loader": CSVDataLoader(folder="/tmp/data")},  # Repetitive!
    "site-3": {"data_loader": CSVDataLoader(folder="/tmp/data")},  # Repetitive!
},
```

**After (concise):**
```python
data_loader=CSVDataLoader(folder="/tmp/data"),  # ← Much cleaner!
```

###  Pattern 2: Site-Specific Config (Existing - Still Supported!)

Use when each client needs different configuration:

```python
from nvflare.app_opt.xgboost.recipes import XGBHorizontalRecipe
from higgs_data_loader import HIGGSDataLoader

recipe = XGBHorizontalRecipe(
    name="xgb_horizontal",
    min_clients=2,
    num_rounds=100,
    per_site_config={
        "site-1": {
            "data_loader": HIGGSDataLoader(
                data_split_filename="/tmp/data/data_site-1.json"  # Site-specific path
            )
        },
        "site-2": {
            "data_loader": HIGGSDataLoader(
                data_split_filename="/tmp/data/data_site-2.json"  # Different path
            )
        },
    },
)
```

---

## Implementation Details

### Validation Logic

```python
# In __init__:
if data_loader is not None and per_site_config is not None:
    raise ValueError(
        "Cannot specify both 'data_loader' and 'per_site_config'. "
        "Use 'data_loader' for common config across all clients, "
        "or 'per_site_config' for site-specific configs."
    )

if data_loader is None and per_site_config is None:
    raise ValueError(
        "Must provide either 'data_loader' or 'per_site_config'. "
        "Use 'data_loader=CSVDataLoader(...)' for common config, "
        "or 'per_site_config={\"site-1\": {\"data_loader\": ...}}' for site-specific configs."
    )
```

### Job Configuration

```python
# In configure():
if self.data_loader:
    # Common data loader for all clients
    job.to_clients(self.data_loader, id=self.data_loader_id)
elif self.per_site_config:
    # Site-specific data loaders
    for site_name, site_config in self.per_site_config.items():
        data_loader = site_config.get("data_loader")
        if data_loader is None:
            raise ValueError(f"per_site_config for '{site_name}' must include 'data_loader' key")
        job.to(data_loader, site_name, id=self.data_loader_id)
```

---

## Files Modified

All three XGBoost recipes were updated with the same pattern:

1. ✅ `nvflare/app_opt/xgboost/recipes/histogram.py`
   - Added `data_loader` parameter
   - Added validation logic
   - Updated `configure()` to handle both patterns

2. ✅ `nvflare/app_opt/xgboost/recipes/vertical.py`
   - Added `data_loader` parameter
   - Added validation logic
   - Updated `configure()` to handle both patterns

3. ✅ `nvflare/app_opt/xgboost/recipes/bagging.py`
   - Added `data_loader` parameter
   - Added validation logic
   - Updated `configure()` to handle both patterns
   - Also creates executors for common pattern

---

## Testing Results

### Test 1: Common Data Loader Pattern ✅
```python
recipe = XGBHorizontalRecipe(
    name='test',
    min_clients=2,
    num_rounds=3,
    data_loader=CSVDataLoader(folder='/tmp/data')
)
# ✅ PASS: Recipe created successfully
```

### Test 2: Site-Specific Pattern ✅
```python
recipe = XGBHorizontalRecipe(
    name='test',
    min_clients=2,
    num_rounds=3,
    per_site_config={
        'site-1': {'data_loader': HIGGSDataLoader('data_site-1.json')},
        'site-2': {'data_loader': HIGGSDataLoader('data_site-2.json')},
    }
)
# ✅ PASS: Recipe created successfully
```

### Test 3: Missing Both (Should Fail) ✅
```python
recipe = XGBHorizontalRecipe(name='test', min_clients=2, num_rounds=3)
# ✅ PASS: ValueError - "Must provide either 'data_loader' or 'per_site_config'"
```

### Test 4: Specifying Both (Should Fail) ✅
```python
recipe = XGBHorizontalRecipe(
    name='test',
    min_clients=2,
    num_rounds=3,
    data_loader=CSVDataLoader(folder='/tmp/data'),
    per_site_config={'site-1': {'data_loader': CSVDataLoader(folder='/tmp/data')}},
)
# ✅ PASS: ValueError - "Cannot specify both 'data_loader' and 'per_site_config'"
```

---

## Benefits

### 1. **Simpler for Common Cases**
```python
# Before: 5 lines
per_site_config={
    "site-1": {"data_loader": CSVDataLoader(folder="/tmp/data")},
    "site-2": {"data_loader": CSVDataLoader(folder="/tmp/data")},
}

# After: 1 line
data_loader=CSVDataLoader(folder="/tmp/data")
```

### 2. **Still Flexible for Complex Cases**
The existing `per_site_config` pattern still works for cases where each site needs different configuration.

### 3. **Better Error Messages**
- Before: Silent failure → confusing runtime "data loader being None" error
- After: Clear validation error at recipe creation time

### 4. **Backward Compatible**
All existing code using `per_site_config` continues to work unchanged.

---

## Migration Guide

### If You're Using CSVDataLoader (or similar)

**Before (verbose):**
```python
per_site_config={
    "site-1": {"data_loader": CSVDataLoader(folder="/tmp/data")},
    "site-2": {"data_loader": CSVDataLoader(folder="/tmp/data")},
    "site-3": {"data_loader": CSVDataLoader(folder="/tmp/data")},
}
```

**After (simpler):**
```python
data_loader=CSVDataLoader(folder="/tmp/data")
```

### If You're Using Site-Specific Config

**No change needed!** Your existing `per_site_config` code continues to work:
```python
per_site_config={
    "site-1": {"data_loader": HIGGSDataLoader("data_site-1.json")},
    "site-2": {"data_loader": HIGGSDataLoader("data_site-2.json")},
}
```

---

## Design Rationale

### Why Not Just Make per_site_config Optional with Defaults?

Considered options:
1. ❌ **Make per_site_config mandatory** - Too restrictive, verbose for common cases
2. ❌ **Allow no config, use defaults** - Can't have meaningful defaults (need file paths!)
3. ✅ **Support both patterns explicitly** - Clear, flexible, backward compatible

### Why Not Auto-Detect?

Could have tried to auto-detect if the data loader is "common" vs "site-specific", but:
- ❌ Complex: Would need to analyze data loader class properties
- ❌ Fragile: Could break with custom data loaders
- ❌ Unclear: User intent not explicit in code
- ✅ **Explicit is better**: User clearly states their intent

---

## Comparison with Other Recipes

### PyTorch/TensorFlow Recipes (FedAvgRecipe)
```python
recipe = FedAvgRecipe(
    train_script="client.py",
    train_args="--data /tmp/data",  # Same args for all clients (optional)
    per_site_config={...},           # Or site-specific (optional)
)
```
- Scripts can have default args
- per_site_config is **optional** (falls back to common config)

### XGBoost Recipes (XGBHorizontalRecipe)
```python
recipe = XGBHorizontalRecipe(
    data_loader=CSVDataLoader(...),  # Common (pick one)
    per_site_config={...},             # Or site-specific (pick one)
)
```
- Data loaders need configuration (file paths, etc.)
- One of `data_loader` or `per_site_config` is **required**

---

## Summary

### What Changed
1. ✅ Added `data_loader` parameter to all three XGBoost recipes
2. ✅ Added validation: exactly one of `data_loader` or `per_site_config` must be provided
3. ✅ Updated `configure()` to handle both patterns
4. ✅ Maintained backward compatibility with existing code

### User Experience Improvements
- **Simpler:** Common cases now require just 1 line instead of N lines (one per site)
- **Clearer:** Error messages explain what's needed
- **Flexible:** Still supports site-specific configs when needed

### Breaking Changes
**NONE!** This is a pure enhancement:
- Existing `per_site_config` code works unchanged
- New `data_loader` parameter is optional (if `per_site_config` provided)
- Only fails if you provide neither or both (which never worked anyway)

---

**Designed by:** AI Assistant (after user feedback)  
**Reported by:** User  
**Date Completed:** February 2, 2026  
**Status:** ✅ READY TO COMMIT
