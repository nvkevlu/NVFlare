# RAW Framework Documentation Clarification

**Date:** December 8, 2025
**Issue:** Documentation incorrectly suggested that `FrameworkType.RAW` is only for sklearn

## Problem

The documentation in the unified `FedAvgRecipe` incorrectly implied that `FrameworkType.RAW` was specific to sklearn:

```python
# Before (incorrect)
framework: The framework type. One of:
    - FrameworkType.PYTORCH (default)
    - FrameworkType.TENSORFLOW
    - FrameworkType.RAW (for sklearn)  # ❌ Too restrictive!

custom_persistor: Custom persistor for RAW framework (sklearn).  # ❌ Too restrictive!
```

**Issue:** This is misleading because `FrameworkType.RAW` is a general-purpose framework type that can be used for **any** custom framework, not just sklearn.

## What is FrameworkType.RAW?

`FrameworkType.RAW` is a generic framework type for custom Python frameworks that:
- Don't have built-in NVFlare model wrappers (like PT/TF do)
- Need custom serialization/persistence logic
- Use raw Python objects for model parameters

**Examples of frameworks that can use RAW:**
- ✅ Scikit-learn
- ✅ XGBoost
- ✅ LightGBM
- ✅ CatBoost
- ✅ Custom ML frameworks
- ✅ Any framework without dedicated NVFlare support

## Solution

Updated all documentation to be framework-agnostic:

### 1. Framework Type Documentation

**Before:**
```python
framework: The framework type. One of:
    - FrameworkType.RAW (for sklearn)
```

**After:**
```python
framework: The framework type. One of:
    - FrameworkType.RAW (for custom frameworks, e.g., sklearn, XGBoost)
```

### 2. Custom Persistor Documentation

**Before:**
```python
custom_persistor: Custom persistor for RAW framework (sklearn). Required when framework=RAW.
    This allows framework-specific wrappers to provide their own persistor...
```

**After:**
```python
custom_persistor: Custom persistor for RAW framework. Required when framework=RAW.
    This allows custom frameworks (e.g., sklearn, XGBoost) to provide their own persistor
    without the unified recipe depending on framework-specific components.
```

### 3. Error Message

**Before:**
```python
raise ValueError(
    "custom_persistor is required when framework=FrameworkType.RAW. "
    "Use framework-specific wrappers (e.g., SklearnFedAvgRecipe) or provide a custom persistor."
)
```

**After:**
```python
raise ValueError(
    "custom_persistor is required when framework=FrameworkType.RAW. "
    "Either use a framework-specific wrapper (e.g., SklearnFedAvgRecipe for sklearn) "
    "or provide a custom persistor for your framework."
)
```

## What Didn't Change

**Sklearn wrapper comments are still fine** because they're in the sklearn-specific file:

```python
# nvflare/app_opt/sklearn/recipes/fedavg.py, line 116
framework=FrameworkType.RAW,  # sklearn uses RAW framework
```

This comment says "sklearn uses RAW", not "RAW is only for sklearn" - it's accurate in this context.

## Key Takeaway

✅ **RAW is framework-agnostic** - it's for ANY custom framework
✅ **Sklearn is just one example** - XGBoost, LightGBM, etc. can also use RAW
✅ **Documentation now reflects this** - uses "e.g., sklearn, XGBoost" to show it's not exclusive

## Files Changed

### Modified
- `nvflare/recipe/fedavg.py`
  - Updated framework type documentation (line ~90)
  - Updated custom_persistor documentation (line ~96-98)
  - Updated error message (line ~239-241)

---

**Documentation is now accurate and inclusive!** 📚
