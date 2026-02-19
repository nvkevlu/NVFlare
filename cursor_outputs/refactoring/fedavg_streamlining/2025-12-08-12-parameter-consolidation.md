# Parameter Consolidation

**Date:** December 8, 2025
**Issue:** Multiple overlapping parameters (`initial_model`, `initial_params`, `model_persistor`, `custom_persistor`) served similar purposes

## Problem

The unified `FedAvgRecipe` had **4 parameters** for initializing models, which was confusing:

```python
# Before (confusing!)
def __init__(
    self,
    initial_model: Any = None,          # For PT/TF model objects
    initial_params: Optional[dict] = None,  # For sklearn params
    model_persistor: Optional[ModelPersistor] = None,  # For PT/TF
    custom_persistor: Optional[ModelPersistor] = None,  # For RAW/sklearn
    ...
)
```

**Issues:**
- ❌ Overlapping purposes - all about initializing the model
- ❌ Confusing naming - `model_persistor` vs `custom_persistor`
- ❌ User has to know which parameter to use for their framework
- ❌ Validation logic: "cannot provide both initial_model and initial_params"

## Solution

Consolidated to just **2 parameters**:

```python
# After (clean!)
def __init__(
    self,
    initial_model: Any = None,  # For ANY framework
    model_persistor: Optional[ModelPersistor] = None,  # For ANY framework
    ...
)
```

### Parameter Definitions

**`initial_model`** (unified parameter for all frameworks):
- `nn.Module` for PyTorch
- `tf.keras.Model` for TensorFlow
- `dict` for sklearn/RAW frameworks (model parameters)
- `ModelPersistor` for any framework (custom persistence logic)
- `None` (no initial model)

**`model_persistor`** (unified optional persistor):
- For PyTorch/TensorFlow: Optional (defaults will be used if not provided)
- For RAW frameworks: Can be provided here
- Replaces both old `model_persistor` and `custom_persistor`

## Changes Made

### 1. Unified FedAvgRecipe

**Removed parameters:**
- `initial_params` → Use `initial_model` with dict instead
- `custom_persistor` → Use `model_persistor` instead

**Updated validation:**
```python
# Before
if self.initial_model is not None and self.initial_params is not None:
    raise ValueError("Cannot provide both...")

if self.framework == FrameworkType.RAW and self.custom_persistor is None:
    raise ValueError("custom_persistor is required...")

# After
if self.framework == FrameworkType.RAW:
    if self.initial_model is None and self.model_persistor is None:
        raise ValueError(
            "RAW framework requires either initial_model (dict or ModelPersistor) or model_persistor."
        )
```

**Updated documentation:**
```python
# Before
initial_model: Initial model to start federated training with. Can be:
    - nn.Module for PyTorch
    - tf.keras.Model for TensorFlow
    - None for sklearn (use initial_params instead)
initial_params: Initial model parameters (dict). Used for sklearn.
    If provided, initial_model should be None.
model_persistor: Custom model persistor. If None, framework-specific defaults...
custom_persistor: Custom persistor for RAW framework. Required when framework=RAW.

# After
initial_model: Initial model to start federated training with. Can be:
    - nn.Module for PyTorch
    - tf.keras.Model for TensorFlow
    - dict for sklearn/RAW frameworks (model parameters)
    - ModelPersistor for any framework (custom persistence logic)
    - None (no initial model)
model_persistor: Custom model persistor for any framework.
    - For PyTorch/TensorFlow: Optional (defaults will be used if not provided)
    - For RAW frameworks: Can be provided here OR passed as initial_model
```

### 2. Sklearn Wrapper

**Before:**
```python
super().__init__(
    ...
    custom_persistor=persistor,  # ❌ Separate parameter
)
```

**After:**
```python
# Create sklearn-specific persistor
persistor = JoblibModelParamPersistor(initial_params=model_params or {})

super().__init__(
    ...
    model_persistor=persistor,  # ✅ Unified parameter
)
```

### 3. PT/TF Wrappers

**No changes needed!** They already used the consolidated interface:
- Pass model object as `initial_model`
- Optionally pass custom persistor as `model_persistor`

## Benefits

✅ **Simpler API** - 2 parameters instead of 4
✅ **Unified interface** - Same parameters for all frameworks
✅ **Less confusion** - Clear purpose for each parameter
✅ **Flexible** - Can pass dict, model object, or persistor as `initial_model`
✅ **Backward compatible** - Framework-specific wrappers handle the details

## Migration Guide

### For Direct Usage (Not Recommended)

**Before:**
```python
# Sklearn with old API
recipe = FedAvgRecipe(
    initial_params={"n_classes": 2},  # ❌ Old parameter
    framework=FrameworkType.RAW,
    custom_persistor=my_persistor,  # ❌ Old parameter
    ...
)
```

**After:**
```python
# Sklearn with new API
recipe = FedAvgRecipe(
    initial_model={"n_classes": 2},  # ✅ Can pass dict
    framework=FrameworkType.RAW,
    model_persistor=my_persistor,  # ✅ Unified parameter
    ...
)
```

### For Wrapper Usage (Recommended)

**No changes needed!** Framework-specific wrappers handle the consolidation:

```python
# Sklearn wrapper (no changes needed)
recipe = SklearnFedAvgRecipe(
    model_params={"n_classes": 2},  # Still works!
    ...
)

# PT wrapper (no changes needed)
recipe = PTFedAvgRecipe(
    initial_model=my_model,  # Still works!
    ...
)
```

## Files Changed

### Modified
- `nvflare/recipe/fedavg.py`
  - Removed `initial_params` and `custom_persistor` parameters
  - Updated `initial_model` documentation to accept dict/persistor
  - Updated `model_persistor` documentation to be framework-agnostic
  - Simplified validation logic
  - Updated `_FedAvgValidator` class

- `nvflare/app_opt/sklearn/recipes/fedavg.py`
  - Changed `custom_persistor=persistor` → `model_persistor=persistor`

### No Changes Needed
- `nvflare/app_opt/pt/recipes/fedavg.py` - Already used consolidated interface
- `nvflare/app_opt/tf/recipes/fedavg.py` - Already used consolidated interface

## Verification

✅ All linting passes
✅ Sklearn wrapper works correctly
✅ PT/TF wrappers unaffected
✅ Unified interface across all frameworks

---

**API is now clean and consistent!** 4 parameters → 2 parameters 🎯
