# TFModelPersistor CSE Methods - Fix

**Date**: January 12, 2026  
**Issue**: TFModelPersistor missing methods required for cross-site evaluation  
**Status**: ✅ **FIXED**

---

## 🐛 Problem

When implementing TensorFlow CSE support, `TFFileModelLocator` was created to call methods on `TFModelPersistor` that didn't exist:

### Missing Methods

1. **`get_model(model_file, fl_ctx)`**:
   - Called by: `TFFileModelLocator.locate_model()` line 73
   - Error: `AttributeError: 'TFModelPersistor' object has no attribute 'get_model'`

2. **`get_model_inventory(fl_ctx)`**:
   - Called by: `TFFileModelLocator.get_model_names()` line 63
   - Error: `AttributeError: 'TFModelPersistor' object has no attribute 'get_model_inventory'`

### What TFModelPersistor Had

```python
class TFModelPersistor(ModelPersistor):
    def load_model(self, fl_ctx) -> ModelLearnable:  # Load from fixed path
    def save_model(self, model_learnable, fl_ctx):  # Save to fixed path
    # ❌ No get_model() method
    # ❌ No get_model_inventory() method
```

### What PTFileModelPersistor Has (Correct Pattern)

```python
class PTFileModelPersistor(ModelPersistor):
    def load_model(self, fl_ctx) -> ModelLearnable:
    def save_model(self, model_learnable, fl_ctx):
    def get_model(self, model_file, fl_ctx) -> ModelLearnable:  # ✅ Exists
    def get_model_inventory(self, fl_ctx) -> Dict[str, ModelDescriptor]:  # ✅ Exists
```

---

## ✅ Solution

Added the missing methods to `TFModelPersistor` following the `PTFileModelPersistor` pattern.

### 1. Added `get_model()` Method

**File**: `nvflare/app_opt/tf/model_persistor.py` (lines 85-104)

```python
def get_model(self, model_file: str, fl_ctx: FLContext) -> ModelLearnable:
    """Get a specific model by file name for cross-site evaluation.

    Args:
        model_file: Name/path of the model file to load
        fl_ctx: FLContext

    Returns:
        ModelLearnable object or None if model not found
    """
    inventory = self.get_model_inventory(fl_ctx)
    if not inventory:
        return None

    desc = inventory.get(model_file)
    if not desc:
        return None

    location = desc.location
    return self._get_model_from_location(location, fl_ctx)
```

### 2. Added `_get_model_from_location()` Helper

**File**: `nvflare/app_opt/tf/model_persistor.py` (lines 106-139)

```python
def _get_model_from_location(self, location: str, fl_ctx: FLContext) -> ModelLearnable:
    """Load model from a specific file location.

    Args:
        location: Full path to model file
        fl_ctx: FLContext

    Returns:
        ModelLearnable object or None if loading fails
    """
    try:
        if os.path.exists(location):
            self.logger.info(f"Loading TensorFlow model from {location}")
            self.model.load_weights(location)

            # build model if not built yet
            if not self.model.built:
                if hasattr(self.model, "_input_shape"):
                    self.model.build(input_shape=self.model._input_shape)
                else:
                    raise AttributeError("To use delayed model build, you need to set model._input_shape")

            # get flat model parameters
            layer_weights_dict = {layer.name: layer.get_weights() for layer in self.model.layers}
            result = flat_layer_weights_dict(layer_weights_dict)

            model_learnable = make_model_learnable(result, dict())
            return model_learnable
        else:
            self.logger.error(f"Model file not found: {location}")
            return None
    except Exception as e:
        self.log_exception(fl_ctx, f"Error loading TensorFlow model from {location}: {e}")
        return None
```

### 3. Added `get_model_inventory()` Method

**File**: `nvflare/app_opt/tf/model_persistor.py` (lines 141-165)

```python
def get_model_inventory(self, fl_ctx: FLContext) -> Dict[str, ModelDescriptor]:
    """Get inventory of available models for cross-site evaluation.

    Args:
        fl_ctx: FLContext

    Returns:
        Dictionary mapping model names to ModelDescriptor objects
    """
    model_inventory = {}

    # Check for the main saved model
    if hasattr(self, "_model_save_path") and os.path.exists(self._model_save_path):
        _, tail = os.path.split(self.save_name)
        model_inventory[tail] = ModelDescriptor(
            name=self.save_name,
            location=self._model_save_path,
            model_format="TensorFlow",
            props={},
        )

    return model_inventory
```

### 4. Updated `_initialize()` to Store `log_dir`

**File**: `nvflare/app_opt/tf/model_persistor.py` (line 38)

```python
def _initialize(self, fl_ctx: FLContext):
    workspace = fl_ctx.get_engine().get_workspace()
    app_root = workspace.get_app_dir(fl_ctx.get_job_id())
    self._model_save_path = os.path.join(app_root, self.save_name)
    self.log_dir = app_root  # ← Added for inventory management
```

### 5. Fixed `TFFileModelLocator` Method Call

**File**: `nvflare/app_opt/tf/file_model_locator.py` (line 73)

**Before**:
```python
model_learnable = self.model_persistor.get(model_name, fl_ctx)  # ❌ Wrong method name
```

**After**:
```python
model_learnable = self.model_persistor.get_model(model_name, fl_ctx)  # ✅ Correct
```

### 6. Added Required Import

**File**: `nvflare/app_opt/tf/model_persistor.py` (line 7)

```python
from nvflare.app_common.abstract.model import ModelDescriptor, ModelLearnable, ModelLearnableKey, make_model_learnable
```

---

## 📊 Method Comparison

| Method | PTFileModelPersistor | TFModelPersistor (Before) | TFModelPersistor (After) |
|--------|---------------------|---------------------------|-------------------------|
| `load_model()` | ✅ Yes | ✅ Yes | ✅ Yes |
| `save_model()` | ✅ Yes | ✅ Yes | ✅ Yes |
| `get_model()` | ✅ Yes | ❌ No | ✅ Yes |
| `get_model_inventory()` | ✅ Yes | ❌ No | ✅ Yes |
| `_get_model_from_location()` | ✅ Yes | ❌ No | ✅ Yes |

Now all three have **API parity** for CSE support!

---

## 🎯 How It Works

### CSE Workflow

1. **Controller asks for inventory**:
   ```python
   locator.get_model_names(fl_ctx)
   └─> persistor.get_model_inventory(fl_ctx)
       └─> Returns: {"tf_model.weights.h5": ModelDescriptor(...)}
   ```

2. **Controller requests specific model**:
   ```python
   locator.locate_model("tf_model.weights.h5", fl_ctx)
   └─> persistor.get_model("tf_model.weights.h5", fl_ctx)
       └─> persistor._get_model_from_location("/path/to/tf_model.weights.h5", fl_ctx)
           └─> Returns: ModelLearnable with weights as DXO
   ```

3. **Model sent to clients** for validation

---

## ✨ Benefits

1. ✅ **Fixes AttributeError**: Methods now exist
2. ✅ **CSE functional**: TensorFlow CSE now actually works
3. ✅ **Consistent API**: Matches PyTorch persistor pattern
4. ✅ **Error handling**: Proper logging and exception handling
5. ✅ **Model building**: Handles delayed model building
6. ✅ **Future-proof**: Can extend to support multiple saved models

---

## 🧪 Testing

### What Works Now

1. **Get inventory**:
   ```python
   inventory = persistor.get_model_inventory(fl_ctx)
   # Returns: {"tf_model.weights.h5": ModelDescriptor(...)}
   ```

2. **Load specific model**:
   ```python
   model_learnable = persistor.get_model("tf_model.weights.h5", fl_ctx)
   # Returns: ModelLearnable with TensorFlow weights
   ```

3. **Full CSE workflow**:
   ```python
   recipe = TFRecipe(...)
   add_cross_site_evaluation(recipe)
   # ✅ Works! No AttributeError
   ```

---

## 📝 Files Modified

1. **`nvflare/app_opt/tf/model_persistor.py`**:
   - Line 1: Added `Dict` import
   - Line 7: Added `ModelDescriptor` import
   - Line 38: Added `self.log_dir` in `_initialize()`
   - Lines 85-165: Added three new methods (~80 lines)

2. **`nvflare/app_opt/tf/file_model_locator.py`**:
   - Line 73: Changed `get()` to `get_model()`

---

## 🔍 Future Enhancements

The current implementation supports the main saved model. Future enhancements could include:

1. **Multiple models**: Track best model, checkpoint models, etc.
2. **Model metadata**: Store training metrics, timestamps
3. **SavedModel format**: Support full SavedModel directories
4. **Versioning**: Track model versions

But for now, basic CSE functionality is complete!

---

**Status**: ✅ **FIXED AND FUNCTIONAL**  
**Lines Added**: ~85  
**Breaking Changes**: None (new methods only)  
**Linter Errors**: 0
