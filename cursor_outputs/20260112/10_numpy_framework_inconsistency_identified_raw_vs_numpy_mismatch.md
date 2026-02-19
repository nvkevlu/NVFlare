# Framework Fix and Support Analysis

**Date**: January 12, 2026  
**Issue**: Inconsistency in NumpyFedAvgRecipe framework usage

---

## 🐛 Bug Fixed

### Issue
`NumpyFedAvgRecipe` added `framework` parameter with default `FrameworkType.RAW`, but the `ScriptRunner` creation hardcoded `FrameworkType.NUMPY` instead of using `self.framework`.

**Before (nvflare/app_common/np/recipes/fedavg.py:190)**:
```python
executor = ScriptRunner(
    script=self.train_script,
    script_args=self.train_args,
    launch_external_process=self.launch_external_process,
    command=self.command,
    framework=FrameworkType.NUMPY,  # ❌ Hardcoded!
    server_expected_format=self.server_expected_format,
    params_transfer_type=self.params_transfer_type,
)
```

**After**:
```python
executor = ScriptRunner(
    script=self.train_script,
    script_args=self.train_args,
    launch_external_process=self.launch_external_process,
    command=self.command,
    framework=self.framework,  # ✅ Uses instance variable
    server_expected_format=self.server_expected_format,
    params_transfer_type=self.params_transfer_type,
)
```

**Impact**: This ensures consistency between the framework parameter and the ScriptRunner configuration.

---

## 📋 Framework Types in NVFlare

From `nvflare/job_config/script_runner.py`:

```python
class FrameworkType(str, Enum):
    RAW = "raw"
    NUMPY = "numpy"
    PYTORCH = "pytorch"
    TENSORFLOW = "tensorflow"
```

### Framework Usage Conventions

| FrameworkType | Typical Usage | Notes |
|---------------|---------------|-------|
| `RAW` | Generic/custom frameworks | Used by NumPy recipes as base type |
| `NUMPY` | NumPy-specific operations | ScriptRunner can use this |
| `PYTORCH` | PyTorch deep learning | Fully supported |
| `TENSORFLOW` | TensorFlow deep learning | Recipe exists, CSE not yet supported |

---

## ✅ Cross-Site Evaluation Framework Support

### Currently Supported for CSE

#### 1. **PyTorch** (`FrameworkType.PYTORCH`)
- ✅ Recipe: `FedAvgRecipe` (PyTorch wrapper)
- ✅ Model Locator: `PTFileModelLocator`
- ✅ Persistor: `PTModelPersistor`
- ✅ Framework field: Already exists in unified `FedAvgRecipe`
- ✅ CSE Support: **Full**

**Registry Entry**:
```python
"pytorch": {
    "locator_module": "nvflare.app_opt.pt.file_model_locator",
    "locator_class": "PTFileModelLocator",
    "persistor_param": "pt_persistor_id",
}
```

#### 2. **NumPy** (`FrameworkType.RAW`)
- ✅ Recipe: `NumpyFedAvgRecipe`
- ✅ Model Locator: `NPModelLocator`
- ✅ Persistor: `NPModelPersistor`
- ✅ Framework field: **Newly added** in this PR
- ✅ Validator: `NPValidator`
- ✅ CSE Support: **Full**

**Registry Entry**:
```python
"numpy": {
    "locator_module": "nvflare.app_common.np.np_model_locator",
    "locator_class": "NPModelLocator",
    "persistor_param": None,  # Doesn't use persistor_id
}
```

**Note**: NumPy uses `FrameworkType.RAW` as its framework type, mapped to `"numpy"` for the model locator registry.

---

### Not Yet Supported for CSE

#### 3. **TensorFlow** (`FrameworkType.TENSORFLOW`)
- ✅ Recipe: `FedAvgRecipe` (TensorFlow wrapper) - **Training works**
- ❌ Model Locator: None found
- ❌ Validator: None found
- ✅ Framework field: Already exists in unified `FedAvgRecipe`
- ❌ CSE Support: **Not implemented**

**Status**: TensorFlow has training recipes but lacks CSE infrastructure (model locator, validator).

**Error Message** (if attempted):
```
ValueError: Unsupported framework for cross-site evaluation: tensorflow. 
Currently supported: pytorch (FrameworkType.PYTORCH), raw (FrameworkType.RAW). 
TensorFlow support may be added in the future.
```

---

## 🔍 Framework Field Status Across Recipes

### Recipes WITH Framework Field

| Recipe | Framework Field | Default Value | Location |
|--------|----------------|---------------|----------|
| `FedAvgRecipe` (Unified) | ✅ Yes | `FrameworkType.PYTORCH` | `nvflare.recipe.fedavg` |
| `FedAvgRecipe` (PyTorch) | ✅ Yes (inherited) | `FrameworkType.PYTORCH` | `nvflare.app_opt.pt.recipes.fedavg` |
| `FedAvgRecipe` (TensorFlow) | ✅ Yes (inherited) | `FrameworkType.TENSORFLOW` | `nvflare.app_opt.tf.recipes.fedavg` |
| `NumpyFedAvgRecipe` | ✅ Yes | `FrameworkType.RAW` | `nvflare.app_common.np.recipes.fedavg` |
| `NumpyCrossSiteEvalRecipe` | ✅ Yes | `FrameworkType.RAW` | `nvflare.app_common.np.recipes.cross_site_eval` |

### How They Work Together

1. **Unified Base**: `nvflare.recipe.fedavg.FedAvgRecipe` is the base that stores `self.framework`
2. **PyTorch Wrapper**: Passes `framework=FrameworkType.PYTORCH` to unified base
3. **TensorFlow Wrapper**: Passes `framework=FrameworkType.TENSORFLOW` to unified base
4. **NumPy Standalone**: Defines its own `framework` field with `FrameworkType.RAW`

---

## 📝 Documentation Updates

### Updated Error Messages

**In `nvflare/recipe/utils.py`**:

Enhanced error message to be more informative:
```python
if framework not in framework_to_locator:
    supported = [f"{k.value} (FrameworkType.{k.name})" for k in framework_to_locator.keys()]
    raise ValueError(
        f"Unsupported framework for cross-site evaluation: {framework}. "
        f"Currently supported: {', '.join(supported)}. "
        f"TensorFlow support may be added in the future."
    )
```

### Updated Docstring

Added note to `add_cross_site_evaluation` docstring:
```python
Note:
    Currently supports PyTorch and NumPy frameworks. 
    TensorFlow support may be added in the future.
```

---

## 🎯 Summary of Changes

### Files Modified

1. **`nvflare/app_common/np/recipes/fedavg.py`**
   - Changed `framework=FrameworkType.NUMPY` → `framework=self.framework`
   - Ensures ScriptRunner uses the recipe's framework setting

2. **`nvflare/recipe/utils.py`**
   - Added docstring note about framework support
   - Enhanced error message with specific framework details
   - Clarified TensorFlow is not yet supported for CSE

### What This Enables

- ✅ Consistent framework usage in NumPy recipes
- ✅ Clear error messages for unsupported frameworks
- ✅ Documentation of current CSE support matrix
- ✅ Future-proofing for TensorFlow CSE support

---

## 🚀 Future Work: TensorFlow CSE Support

To add TensorFlow support for CSE, the following would be needed:

### 1. Create TensorFlow Model Locator
```python
# nvflare/app_opt/tf/file_model_locator.py (to be created)
class TFFileModelLocator(ModelLocator):
    """Model locator for TensorFlow models in CSE."""
    # Implementation similar to PTFileModelLocator
```

### 2. Create TensorFlow Validator
```python
# nvflare/app_opt/tf/tf_validator.py (to be created)
class TFValidator(Executor):
    """Validator for TensorFlow models in CSE."""
    # Implementation similar to NPValidator
```

### 3. Update Registry
```python
# In nvflare/recipe/utils.py
MODEL_LOCATOR_REGISTRY = {
    # ... existing entries ...
    "tensorflow": {
        "locator_module": "nvflare.app_opt.tf.file_model_locator",
        "locator_class": "TFFileModelLocator",
        "persistor_param": "tf_persistor_id",
    },
}
```

### 4. Update Framework Mapping
```python
# In add_cross_site_evaluation()
framework_to_locator = {
    FrameworkType.PYTORCH: "pytorch",
    FrameworkType.RAW: "numpy",
    FrameworkType.TENSORFLOW: "tensorflow",  # Add this
}
```

### 5. Auto-add TensorFlow Validator
```python
# In add_cross_site_evaluation()
# Auto-add validators
if framework == FrameworkType.RAW:
    # NumPy validator (existing)
    from nvflare.app_common.np.np_validator import NPValidator
    validator = NPValidator()
    recipe.job.to_clients(validator, tasks=[AppConstants.TASK_VALIDATION])
elif framework == FrameworkType.TENSORFLOW:
    # TensorFlow validator (to be added)
    from nvflare.app_opt.tf.tf_validator import TFValidator
    validator = TFValidator()
    recipe.job.to_clients(validator, tasks=[AppConstants.TASK_VALIDATION])
```

**Estimated Effort**: Medium (~1-2 weeks)
- Create model locator and validator classes
- Test with TensorFlow models
- Update documentation

---

## ✅ Testing

All changes pass linting:
```bash
✅ nvflare/app_common/np/recipes/fedavg.py - No linter errors
✅ nvflare/recipe/utils.py - No linter errors
```

---

## 📊 Final Status

| Framework | Training | CSE | Status |
|-----------|----------|-----|--------|
| PyTorch | ✅ | ✅ | Fully supported |
| NumPy | ✅ | ✅ | Fully supported (this PR) |
| TensorFlow | ✅ | ❌ | Training only, CSE not yet implemented |
| RAW | ✅ | ✅ | Generic type, used by NumPy |

**Key Insight**: The framework field is crucial for CSE auto-detection. All recipes that support training now have proper framework metadata, making CSE configuration seamless for PyTorch and NumPy.

