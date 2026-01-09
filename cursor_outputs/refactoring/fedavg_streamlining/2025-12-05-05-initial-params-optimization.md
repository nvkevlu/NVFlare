# Final Optimization: Removed Unnecessary initial_params Passing

## Issue Identified

User spotted that `initial_params` was being passed through multiple layers unnecessarily:

```python
# Before (unnecessary passing):
sklearn wrapper → unified recipe → BaseFedJob
                ↓
            persistor (already has it!)
```

## Root Cause Analysis

**Who actually USES `initial_params`:**
- ✅ `JoblibModelParamPersistor.load_model()` (line 60-61)
  ```python
  self.logger.info(f"Initialization, sending global settings: {self.initial_params}")
  model = self.initial_params  # <-- ONLY REAL USER
  ```

**Who just STORES it (never reads):**
- ❌ `BaseFedJob.__init__` (line 99) - `self.initial_params = initial_params` (never used)
- ❌ `FedAvgRecipe.__init__` (line 214) - `self.initial_params = v.initial_params` (just passes through)

## The Fix

### Before:
```python
# sklearn wrapper
persistor = JoblibModelParamPersistor(initial_params=model_params or {})

super().__init__(
    ...
    initial_params=model_params,  # ❌ Unnecessary - persistor already has it!
    custom_persistor=persistor,
)
```

### After:
```python
# sklearn wrapper
persistor = JoblibModelParamPersistor(initial_params=model_params or {})

super().__init__(
    ...
    # ✅ Removed: initial_params (persistor already has it)
    custom_persistor=persistor,  # This is all we need!
)
```

## Why This Works

1. **The persistor has the params** - Created with `JoblibModelParamPersistor(initial_params=model_params)`
2. **The persistor is passed separately** - Via `custom_persistor=persistor`
3. **The persistor is the only user** - It's the component that actually loads/saves the model state
4. **BaseFedJob doesn't use it** - It just stores `initial_params` but never reads it

## Benefits

✅ **Cleaner code** - No redundant data passing
✅ **Single source of truth** - Persistor owns the initial params
✅ **Less confusion** - Clearer that persistor manages state
✅ **Same functionality** - Nothing broke because nothing used it!

## Verification

Checked all usages of `self.initial_params`:
```bash
$ grep -r "self.initial_params" nvflare/

# Results:
- JoblibModelParamPersistor: USES it (line 60-61) ✅
- BaseFedJob: stores but never reads ❌
- FedAvgRecipe: stores but just passes through ❌
```

**Conclusion:** Only the persistor actually needs `initial_params`, so only the persistor should have it!

## Related Code

The same pattern works for PT/TF:
- PT: `PTModel` gets `initial_model` (via model parameter)
- TF: `TFModel` gets `initial_model` (via model parameter)
- Sklearn: `JoblibModelParamPersistor` gets `initial_params` (via constructor)

All frameworks: **The component that manages model state owns the initial state.** ✅

---

**Great catch by the user!** This simplification makes the code cleaner and more maintainable.
