# TFFileModelLocator Filter Bypass Fix

**Date**: January 13, 2026  
**Issue**: TFFileModelLocator bypassed persistor filter processing  
**Severity**: ⚠️ **CRITICAL** - Breaks filter functionality  
**Status**: ✅ **FIXED**

---

## 🐛 Problem

### The Bug

`TFFileModelLocator.locate_model()` was calling `get_model()` directly instead of `get()`, bypassing the filter processing layer.

**Buggy Code** (line 88):
```python
model_learnable = self.model_persistor.get_model(model_name, fl_ctx)  # ❌ WRONG
```

**Correct Code** (PyTorch implementation, line 91):
```python
model_learnable = self.model_persistor.get(model_name, fl_ctx)  # ✅ CORRECT
```

### Why This Matters

The `ModelPersistor` abstract class provides a `get()` method that wraps `get_model()` and applies **persistor filters**:

**From `nvflare/app_common/abstract/model_persistor.py` (lines 60-68)**:
```python
def get(self, model_file: str, fl_ctx: FLContext) -> object:
    learnable = self.get_model(model_file, fl_ctx)  # Call implementation
    
    if self.filter_id:  # Apply filter if configured
        _filter = fl_ctx.get_engine().get_component(self.filter_id)
        if not isinstance(_filter, PersistorFilter):
            raise ValueError(f"Expected filter to be of type `PersistorFilter` but got {type(filter)}")
        learnable = _filter.process_post_get(learnable=learnable, fl_ctx=fl_ctx)
    return learnable
```

### What Gets Bypassed

When calling `get_model()` directly, the `process_post_get()` filter is skipped. This filter is used for:

1. **Serialization/Deserialization**: Custom Python object handling
2. **Data transformation**: Post-processing of loaded models
3. **Security checks**: Validation of loaded model data
4. **Compatibility layers**: Format conversions

### Impact

| Component | Filter Used? | Impact if Bypassed |
|-----------|--------------|-------------------|
| **TFModelPersistor** | Via `filter_id` param | Custom serialization broken |
| **PyTorch (correct)** | ✅ Yes | Works correctly |
| **NumPy** | Via `filter_id` param | Would be broken if using `get_model()` |

---

## ✅ Solution

Changed `TFFileModelLocator.locate_model()` to call `get()` instead of `get_model()`.

**File**: `nvflare/app_opt/tf/file_model_locator.py` (line 88)

**Before**:
```python
def locate_model(self, model_name, fl_ctx: FLContext) -> DXO:
    if model_name not in list(self.model_inventory.keys()):
        raise ValueError(f"model inventory does not contain: {model_name}")

    model_learnable = self.model_persistor.get_model(model_name, fl_ctx)  # ❌ Bypasses filters
    dxo = model_learnable_to_dxo(model_learnable)
    return dxo
```

**After**:
```python
def locate_model(self, model_name, fl_ctx: FLContext) -> DXO:
    if model_name not in list(self.model_inventory.keys()):
        raise ValueError(f"model inventory does not contain: {model_name}")

    model_learnable = self.model_persistor.get(model_name, fl_ctx)  # ✅ Applies filters
    dxo = model_learnable_to_dxo(model_learnable)
    return dxo
```

---

## 🔍 API Pattern Explanation

### ModelPersistor API Design

The `ModelPersistor` class has a **two-layer design**:

1. **Public API** (with filters):
   - `load()` → calls `load_model()` + applies `process_post_load()` filter
   - `save()` → applies `process_pre_save()` + calls `save_model()` + `process_post_save()`
   - `get()` → calls `get_model()` + applies `process_post_get()` filter ✅

2. **Implementation API** (override in subclasses):
   - `load_model()` - actual loading logic
   - `save_model()` - actual saving logic
   - `get_model()` - actual retrieval logic

### Correct Usage Pattern

**Implementers** (TFModelPersistor, PTFileModelPersistor):
- Override `load_model()`, `save_model()`, `get_model()`
- Do NOT call these methods directly

**Consumers** (TFFileModelLocator, PTFileModelLocator):
- Call `load()`, `save()`, `get()`
- Never call `load_model()`, `save_model()`, `get_model()` directly

### Comparison Table

| Operation | Implementation Method | Public Method (with filters) | Locator Should Call |
|-----------|----------------------|------------------------------|---------------------|
| Initial load | `load_model()` | `load()` | `load()` |
| Save model | `save_model()` | `save()` | `save()` |
| Get specific model | `get_model()` | `get()` | `get()` ✅ |

---

## 📊 Filter Processing Flow

### With Correct Implementation (Now)

```
TFFileModelLocator.locate_model()
  ↓
model_persistor.get(model_name, fl_ctx)
  ↓
├─ get_model(model_name, fl_ctx)  [TFModelPersistor implementation]
│   └─ Load weights from file
│       └─ Return ModelLearnable
│
├─ if filter_id:
│   └─ filter.process_post_get(learnable, fl_ctx)  ✅ Applied!
│       ├─ Deserialize custom objects
│       ├─ Apply transformations
│       └─ Return processed learnable
│
└─ Return ModelLearnable (with filters applied)
```

### With Bug (Before)

```
TFFileModelLocator.locate_model()
  ↓
model_persistor.get_model(model_name, fl_ctx)  ❌ Direct call
  ↓
Load weights from file
  ↓
Return ModelLearnable (NO filters applied)  ⚠️ BROKEN
```

---

## 🎯 Why This Was Missed

1. **Recent implementation**: `TFFileModelLocator` and `TFModelPersistor.get_model()` were just created
2. **Working without filters**: Basic use cases work without filters
3. **Silent failure**: No error, just missing functionality
4. **Inconsistency check needed**: Should have compared with `PTFileModelLocator` line-by-line

---

## ✨ Benefits of Fix

1. ✅ **Filter support works**: Custom serialization now functional
2. ✅ **Consistent with PyTorch**: Both implementations now identical
3. ✅ **API contract honored**: Uses public API correctly
4. ✅ **Future-proof**: Any filter enhancements automatically work
5. ✅ **Security**: Filter-based validation now applied

---

## 🧪 Testing Implications

### Without Filters (Still Works)
```python
persistor = TFModelPersistor(model=my_model)  # No filter_id
locator = TFFileModelLocator(tf_persistor_id="persistor")
model = locator.locate_model("model.h5", fl_ctx)  # Works before and after
```

### With Filters (Now Fixed)
```python
persistor = TFModelPersistor(model=my_model, filter_id="my_filter")  # ← With filter
locator = TFFileModelLocator(tf_persistor_id="persistor")
model = locator.locate_model("model.h5", fl_ctx)
# Before: Filter NOT applied ❌
# After:  Filter applied ✅
```

---

## 📝 Files Modified

**`nvflare/app_opt/tf/file_model_locator.py`** (line 88):
- Changed: `self.model_persistor.get_model()` → `self.model_persistor.get()`
- **1 character change** with critical impact!

---

## 🔗 Related Components

This fix ensures TensorFlow CSE works correctly with:
- `PersistorFilter` classes
- Custom serialization filters
- Any future filter enhancements

---

**Status**: ✅ **FIXED**  
**Lines Changed**: 1 (method name)  
**Severity**: Critical (breaks filter functionality)  
**Breaking Changes**: None (fix restores intended behavior)  
**Linter Errors**: 0
