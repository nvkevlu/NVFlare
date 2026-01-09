# Model Setup Delegated to Child Classes

**Date:** December 8, 2025
**Issue:** Framework-specific model setup logic was in the unified `FedAvgRecipe`

## Problem

The unified `FedAvgRecipe` contained framework-specific logic for setting up PyTorch and TensorFlow models:

```python
# In unified FedAvgRecipe (lines 257-267)
if self.framework == FrameworkType.RAW:
    persistor_id = job.to_server(self.custom_persistor, id="persistor")
elif self.initial_model is not None:
    if self.framework == FrameworkType.PYTORCH:
        self._setup_pytorch_model(job, self.initial_model, self.model_persistor, model_locator=None)
    elif self.framework == FrameworkType.TENSORFLOW:
        self._setup_tensorflow_model(job, self.initial_model, self.model_persistor)
    persistor_id = job.comp_ids.get("persistor_id", "")
```

**Issues:**
- ❌ Unified recipe has PT/TF-specific imports (lazy but still there)
- ❌ Framework branching logic in base class
- ❌ Violates separation of concerns

## Solution

Introduced a new method `_setup_model_and_persistor(job) -> str` that child classes override:

### Unified FedAvgRecipe (Base)
```python
def _setup_model_and_persistor(self, job: BaseFedJob) -> str:
    """Setup framework-specific model components and persistor.

    Returns:
        str: The persistor_id to be used by the controller.

    Note:
        - RAW framework (sklearn): Handled in base implementation
        - PT/TF frameworks: Must be overridden by child classes
    """
    if self.framework == FrameworkType.RAW:
        # Sklearn: Add custom persistor
        return job.to_server(self.custom_persistor, id="persistor")
    elif self.initial_model is not None:
        # PT/TF: Should be overridden by child classes
        raise NotImplementedError(
            f"Model setup for framework {self.framework} must be implemented by child class. "
            f"Use framework-specific wrappers (e.g., PT FedAvgRecipe, TF FedAvgRecipe)."
        )
    return ""
```

### PyTorch FedAvgRecipe (Child)
```python
def _setup_model_and_persistor(self, job) -> str:
    """Override to handle PyTorch-specific model setup."""
    if self.initial_model is not None:
        from nvflare.app_opt.pt.job_config.model import PTModel

        pt_model = PTModel(
            model=self.initial_model,
            persistor=self.model_persistor,
            locator=self._pt_model_locator  # PT-specific!
        )
        job.comp_ids.update(job.to_server(pt_model))
        return job.comp_ids.get("persistor_id", "")
    return ""
```

### TensorFlow FedAvgRecipe (Child)
```python
def _setup_model_and_persistor(self, job) -> str:
    """Override to handle TensorFlow-specific model setup."""
    if self.initial_model is not None:
        from nvflare.app_opt.tf.job_config.model import TFModel

        tf_model = TFModel(model=self.initial_model, persistor=self.model_persistor)
        job.comp_ids["persistor_id"] = job.to_server(tf_model)
        return job.comp_ids.get("persistor_id", "")
    return ""
```

## Benefits

✅ **Unified recipe is cleaner** - Only handles sklearn (RAW) framework
✅ **No PT/TF branching** - Framework-specific logic in framework-specific classes
✅ **Better separation of concerns** - Each class handles its own framework
✅ **Consistent pattern** - Matches how `BaseFedJob` wrappers work
✅ **Clear error messages** - NotImplementedError if used incorrectly

## Pattern Consistency

This completes the pattern we established earlier:

| Component | Unified Base | PT Wrapper | TF Wrapper | Sklearn Wrapper |
|-----------|--------------|------------|------------|-----------------|
| **BaseFedJob** | Common widgets | + PT model setup | + TF model setup | N/A |
| **FedAvgRecipe** | Sklearn only | + PT model setup | + TF model setup | + Persistor |

**Both now follow the same principle:**
✅ Base class handles common/generic logic
✅ Child classes handle framework-specific logic

## Files Changed

### Modified
- `nvflare/recipe/fedavg.py`
  - Removed `_setup_pytorch_model()` and `_setup_tensorflow_model()` methods
  - Added `_setup_model_and_persistor(job) -> str` method
  - Simplified main flow to call single delegation method

- `nvflare/app_opt/pt/recipes/fedavg.py`
  - Replaced `_setup_pytorch_model()` override
  - Added `_setup_model_and_persistor()` override with PT-specific logic

- `nvflare/app_opt/tf/recipes/fedavg.py`
  - Added `_setup_model_and_persistor()` override with TF-specific logic

### No Changes Needed
- `nvflare/app_opt/sklearn/recipes/fedavg.py` - Already delegates to base (RAW handling)

## Verification

✅ All linting passes
✅ No circular dependencies
✅ Clean separation of concerns
✅ Consistent with `BaseFedJob` pattern

## Before vs After

### Before: Framework Branching in Base
```python
# Unified recipe had framework-specific knowledge
if self.framework == FrameworkType.PYTORCH:
    self._setup_pytorch_model(...)  # PT logic in base
elif self.framework == FrameworkType.TENSORFLOW:
    self._setup_tensorflow_model(...)  # TF logic in base
```

### After: Delegation to Child Classes
```python
# Unified recipe delegates to child classes
persistor_id = self._setup_model_and_persistor(job)  # Child handles specifics
```

---

**Architecture is now clean!** Framework-specific logic lives in framework-specific classes. 🎯
