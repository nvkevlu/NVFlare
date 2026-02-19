# Documentation Improvements: XGBoost Data Loader Clarity

**Date:** January 13, 2026  
**Issue:** Critical data loading behavior was poorly documented  
**Status:** ✅ RESOLVED

---

## Problem Statement

Users were confused about how `CSVDataLoader` handles client-specific data loading when the same folder path is passed to all clients. The key insight—that the framework automatically injects `client_id` at runtime—was not documented anywhere.

### Specific Confusion Points

1. **Horizontal splitting**: "Each client gets the same CSVDataLoader with identical folder path - how does this work?"
2. **Vertical splitting**: "Same data loader for all clients - how does it differentiate feature columns?"
3. **Runtime behavior**: No documentation explaining that `initialize()` is called automatically by the framework

---

## Root Cause

### Missing Documentation

1. **`XGBDataLoader.initialize()`** - No docstring explaining:
   - When/how it's called (automatically by framework)
   - What the parameters mean
   - That it enables client-specific loading despite same configuration

2. **`CSVDataLoader.__init__()`** - Incomplete docstring:
   - No folder structure example
   - No explanation of `{folder}/{client_id}/` pattern
   - No mention of runtime `client_id` injection

3. **Job scripts** - Vague comments:
   - "CSVDataLoader is used here for the secure example's data format"
   - No explanation of how client-specific loading works

4. **README** - Missing folder structure:
   - Data split process explained
   - But no visual of expected directory layout
   - No connection between folder structure and data loader behavior

---

## Solution Implemented

### 1. Enhanced `XGBDataLoader.initialize()` Docstring

**File:** `nvflare/app_opt/xgboost/data_loader.py`

**Added comprehensive docstring:**

```python
def initialize(
    self, client_id: str, rank: int, data_split_mode: xgb.core.DataSplitMode = xgb.core.DataSplitMode.ROW
):
    """Initialize the data loader with client-specific parameters.

    This method is automatically called by the NVFlare framework at runtime for each client.
    You do not need to call this method manually. The framework will inject the appropriate
    client_id, rank, and data_split_mode for each client site.

    Args:
        client_id: Unique identifier for the client (e.g., 'site-1', 'site-2').
            This is set automatically by the framework based on which client is running.
        rank: Client's rank in the federation (0-indexed). In vertical mode, rank 0
            is typically the label owner.
        data_split_mode: XGBoost data split mode (ROW for horizontal, COLUMN for vertical).
            This is set automatically based on the recipe configuration.

    Note:
        Even though you create the same data loader instance for all clients in your job script,
        each client will receive different values for these parameters at runtime, enabling
        client-specific data loading.
    """
```

**Key Points Explained:**
- ✅ Automatic framework invocation
- ✅ Parameter meanings and sources
- ✅ Client-specific behavior despite same configuration

---

### 2. Comprehensive `CSVDataLoader` Docstring

**File:** `nvflare/app_opt/xgboost/histogram_based_v2/csv_data_loader.py`

**Added detailed docstring with:**

1. **Clear explanation of automatic behavior**
2. **Visual folder structure example**
3. **Horizontal vs. vertical mode differences**
4. **Code example showing usage**

```python
def __init__(self, folder: str):
    """Reads CSV dataset and returns XGB data matrix with automatic client-specific loading.

    This data loader automatically handles site-specific data loading. Even though you pass
    the same folder path to all clients, each client will load its own data based on its
    client_id (which is injected by the framework at runtime).

    Expected folder structure:
        {folder}/
        ├── site-1/
        │   ├── train.csv
        │   └── valid.csv
        ├── site-2/
        │   ├── train.csv
        │   └── valid.csv
        └── site-3/
            ├── train.csv
            └── valid.csv

    For horizontal mode (row split):
        - Each site's CSV contains all features + labels
        - Each site has different rows (samples)

    For vertical mode (column split):
        - site-1 (rank 0) contains subset of features + labels
        - Other sites contain different features, no labels
        - All sites have the same rows (samples)

    Args:
        folder: Base folder path containing client-specific subdirectories.
            Each client will automatically load from {folder}/{client_id}/

    Example:
        .. code-block:: python

            # In your job script - same data loader for all clients
            for i in range(1, 4):
                dataloader = CSVDataLoader(folder="/tmp/data/horizontal")
                recipe.add_to_client(f"site-{i}", dataloader)

            # At runtime:
            # site-1 loads: /tmp/data/horizontal/site-1/train.csv
            # site-2 loads: /tmp/data/horizontal/site-2/train.csv
            # site-3 loads: /tmp/data/horizontal/site-3/train.csv

    Note:
        In vertical mode, the label owner is always rank 0 (typically site-1).
    """
```

**Key Improvements:**
- ✅ Folder structure visualization
- ✅ Horizontal vs. vertical differences
- ✅ Concrete code example
- ✅ Runtime behavior explanation

---

### 3. Improved Job Script Comments

**File:** `examples/advanced/xgboost/fedxgb_secure/job.py`

**Before (Horizontal):**
```python
# Add data loaders to each client
for i in range(1, args.site_num + 1):
    dataloader = CSVDataLoader(folder=dataset_path)
    recipe.add_to_client(f"site-{i}", dataloader)
```

**After (Horizontal):**
```python
# Add data loaders to each client
# Note: CSVDataLoader automatically handles client-specific data loading.
# Even though we pass the same folder path, each client will load its own data
# from {dataset_path}/{client_id}/ at runtime (e.g., site-1 loads from site-1/ subdirectory)
for i in range(1, args.site_num + 1):
    dataloader = CSVDataLoader(folder=dataset_path)
    recipe.add_to_client(f"site-{i}", dataloader)
```

**Before (Vertical):**
```python
# Add data loaders to each client
# Note: CSVDataLoader is used here for the secure example's data format
for i in range(1, args.site_num + 1):
    dataloader = CSVDataLoader(folder=dataset_path)
    # For vertical XGBoost, each client gets its own split of columns
    recipe.add_to_client(f"site-{i}", dataloader)
```

**After (Vertical):**
```python
# Add data loaders to each client
# Note: CSVDataLoader automatically handles client-specific data loading.
# For vertical mode, each client loads different feature columns from its subdirectory:
# - site-1 (rank 0): loads features + labels from {dataset_path}/site-1/
# - site-2, site-3: load different features (no labels) from their respective subdirectories
for i in range(1, args.site_num + 1):
    dataloader = CSVDataLoader(folder=dataset_path)
    recipe.add_to_client(f"site-{i}", dataloader)
```

**Also Updated:**
- `examples/advanced/xgboost/fedxgb/job_vertical.py` - Added similar comments

---

### 4. README Folder Structure Section

**File:** `examples/advanced/xgboost/fedxgb_secure/README.md`

**Added new section after data preparation:**

```markdown
### Expected Folder Structure

After running `prepare_data.sh`, your data will be organized as follows:

```
/tmp/nvflare/dataset/xgb_dataset/
├── horizontal_xgb_data/
│   ├── site-1/
│   │   ├── train.csv  (all features + labels, subset of rows)
│   │   └── valid.csv
│   ├── site-2/
│   │   ├── train.csv  (all features + labels, different rows)
│   │   └── valid.csv
│   └── site-3/
│       ├── train.csv  (all features + labels, different rows)
│       └── valid.csv
└── vertical_xgb_data/
    ├── site-1/
    │   ├── train.csv  (subset of features + labels, all rows)
    │   └── valid.csv
    ├── site-2/
    │   ├── train.csv  (different features, no labels, all rows)
    │   └── valid.csv
    └── site-3/
        ├── train.csv  (different features, no labels, all rows)
        └── valid.csv
```

**Important:** When using `CSVDataLoader` in your job script, you only need to specify the base folder 
(e.g., `/tmp/nvflare/dataset/xgb_dataset/horizontal_xgb_data`). The framework automatically loads 
client-specific data from the corresponding subdirectory (e.g., `site-1/`, `site-2/`) at runtime.
```

**Key Addition:**
- ✅ Visual folder structure
- ✅ Annotations showing data differences
- ✅ Important note about automatic loading

---

## Files Modified

### Core Framework Files (2)
1. `nvflare/app_opt/xgboost/data_loader.py` - Added `initialize()` docstring
2. `nvflare/app_opt/xgboost/histogram_based_v2/csv_data_loader.py` - Enhanced `CSVDataLoader` docstring

### Example Files (2)
3. `examples/advanced/xgboost/fedxgb_secure/job.py` - Improved comments for both modes
4. `examples/advanced/xgboost/fedxgb/job_vertical.py` - Added explanatory comments

### Documentation Files (1)
5. `examples/advanced/xgboost/fedxgb_secure/README.md` - Added folder structure section

---

## Impact

### Before
❌ Users confused about how same folder path works for all clients  
❌ No documentation of framework's automatic `initialize()` call  
❌ No visual of expected folder structure  
❌ Vague comments that didn't explain the mechanism  

### After
✅ Clear explanation of automatic client-specific loading  
✅ Documented framework behavior with `initialize()`  
✅ Visual folder structure with annotations  
✅ Concrete code examples showing runtime behavior  
✅ Detailed comments explaining the mechanism  

---

## Verification

### Linter Check
```bash
# All modified files pass linting
✅ nvflare/app_opt/xgboost/data_loader.py - No errors
✅ nvflare/app_opt/xgboost/histogram_based_v2/csv_data_loader.py - No errors
✅ examples/advanced/xgboost/fedxgb_secure/job.py - No errors
✅ examples/advanced/xgboost/fedxgb/job_vertical.py - No errors
✅ examples/advanced/xgboost/fedxgb_secure/README.md - No errors
```

### Documentation Quality
- ✅ Comprehensive docstrings with examples
- ✅ Clear visual aids (folder structure)
- ✅ Concrete code examples
- ✅ Explains both "what" and "how"
- ✅ Covers both horizontal and vertical modes

---

## Related Issues Resolved

1. **Original Question**: "Each client gets the same CSVDataLoader with identical folder path - how does this work?"
   - **Answer**: Framework calls `initialize(client_id, ...)` at runtime, enabling `{folder}/{client_id}/` loading

2. **Original Question**: "How does CSVDataLoader differentiate between vertical splits?"
   - **Answer**: Same mechanism + `data_split_mode` parameter controls label loading (rank 0 gets labels)

3. **Original Question**: "Is this well documented?"
   - **Answer**: No, but now it is!

---

## Lessons Learned

### Documentation Best Practices

1. **Explain Framework Magic**: When the framework does something automatically (like calling `initialize()`), document it explicitly
2. **Visual Aids**: Folder structures, diagrams, and examples are crucial for understanding
3. **Code Examples**: Show both the user's code and what happens at runtime
4. **Anticipate Confusion**: If something seems "too simple" (same config for all clients), explain why it works

### Common Pitfall
Assuming users understand framework internals. What's obvious to framework developers is often mysterious to users.

---

## Recommendations for Future Work

1. **Add to Other Data Loaders**: Apply similar documentation improvements to:
   - `HIGGSDataLoader`
   - `VerticalDataLoader`
   - Other custom data loaders

2. **Tutorial/Guide**: Consider creating a dedicated guide on "How NVFlare Data Loaders Work"

3. **Diagram**: Add a sequence diagram showing:
   ```
   User Code → Recipe → Framework → initialize() → load_data()
   ```

4. **FAQ Section**: Add to README:
   - Q: Why pass same folder to all clients?
   - A: Framework injects client_id at runtime...

---

## Conclusion

Successfully improved documentation to clarify a critical but poorly-explained behavior. The enhancements provide:

- **Comprehensive docstrings** explaining automatic framework behavior
- **Visual folder structures** showing expected layout
- **Concrete examples** demonstrating runtime behavior
- **Clear comments** in job scripts explaining the mechanism

**Status:** ✅ Complete and verified  
**Impact:** High - resolves major source of user confusion
