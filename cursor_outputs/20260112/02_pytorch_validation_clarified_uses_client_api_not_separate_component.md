# PyTorch Cross-Site Evaluation - Validation Handling Clarification

**Date**: January 12, 2026  
**Issue**: Misleading documentation about PyTorch validators for CSE  
**Status**: ✅ Clarified

---

## 🐛 Problem

The docstring for `add_cross_site_evaluation()` stated:
> "For PyTorch recipes, client-side validators are typically already configured in the recipe."

This was **misleading and inaccurate** because:
1. PyTorch recipes (like `FedAvgRecipe`) do NOT pre-configure validators
2. PyTorch CSE works differently than NumPy CSE
3. Users might expect CSE to work automatically without understanding the requirement

---

## ✅ How PyTorch CSE Actually Works

### Key Insight: Client Script Handles Validation

PyTorch CSE uses the **Client API pattern** where the training script itself handles validation:

```python
# In client.py (PyTorch training script)
while flare.is_running():
    input_model = flare.receive()
    model.load_state_dict(input_model.params)
    
    # Evaluate model (always done)
    metrics = evaluate(model, test_loader)
    
    # CSE validation task handling
    if flare.is_evaluate():  # ← This detects validation-only tasks
        output_model = flare.FLModel(metrics=metrics)
        flare.send(output_model)
        continue  # Skip training for validation tasks
    
    # Normal training code continues here...
    train(model, train_loader)
    output_model = flare.FLModel(params=model.state_dict(), metrics=metrics)
    flare.send(output_model)
```

**How it works**:
1. `CrossSiteModelEval` controller sends `TASK_VALIDATION` to clients
2. `ScriptRunner` executes the client script with the validation task
3. `flare.is_evaluate()` returns `True` for validation tasks
4. Client script evaluates model and returns metrics without training

---

## 📊 NumPy vs PyTorch Comparison

| Aspect | NumPy | PyTorch |
|--------|-------|---------|
| **Validation Handler** | Separate `NPValidator` component | Client script via `flare.is_evaluate()` |
| **Auto-added?** | ✅ Yes, by `add_cross_site_evaluation()` | ❌ No component needed |
| **User Requirement** | None (automatic) | Must implement validation branch in client script |
| **Why Different?** | No ScriptRunner, needs separate executor | ScriptRunner handles task routing |

---

## 🔧 Documentation Fixes Applied

### 1. Added Prominent Warning

```python
**IMPORTANT for PyTorch**: Your client training script must handle validation tasks by
checking `flare.is_evaluate()` and returning metrics without training. Example pattern:
    [... code example ...]
```

**Location**: Lines 103-122 in docstring

### 2. Updated Note Section

**Before** (misleading):
```python
- For PyTorch recipes, client-side validators are typically already configured in the recipe.
```

**After** (accurate):
```python
- **PyTorch recipes**: No separate validator component is needed. The client training script
  handles validation tasks through the Client API's `flare.is_evaluate()` check. See the
  hello-pt example for implementation pattern.
```

**Location**: Lines 165-167

### 3. Added Framework-Specific Examples

**NumPy example** (fully automatic):
```python
recipe = NumpyFedAvgRecipe(...)
add_cross_site_evaluation(recipe)  # Validator auto-added
```

**PyTorch example** (with note):
```python
recipe = FedAvgRecipe(...)
# Note: client.py must handle flare.is_evaluate() for validation
add_cross_site_evaluation(recipe)
```

**Location**: Lines 124-149

---

## 📝 What Users Need to Know

### For NumPy Users
✅ **Nothing to do** - validation is fully automatic:
```python
recipe = NumpyFedAvgRecipe(...)
add_cross_site_evaluation(recipe)  # Done!
```

### For PyTorch Users
⚠️ **Client script must handle validation**:

1. **Add validation branch** to your training script:
   ```python
   if flare.is_evaluate():
       output_model = flare.FLModel(metrics=evaluate(model, test_data))
       flare.send(output_model)
       continue
   ```

2. **See working example**: `examples/hello-world/hello-pt/client.py` (lines 98-103)

3. **Why?** PyTorch CSE reuses your training script for validation via the Client API

---

## 🎯 Why the Confusion?

The original documentation implied PyTorch recipes had validators "already configured", which could mean:

1. ❌ **What users might think**: There's a validator component already added → just call `add_cross_site_evaluation()`
2. ✅ **What was meant**: The ScriptRunner + Client API pattern already handles validation tasks

The updated documentation now explicitly explains:
- **What** handles validation (client script, not a separate component)
- **How** to implement it (`flare.is_evaluate()` check)
- **Where** to see an example (hello-pt)

---

## ✨ Benefits of Clarification

1. ✅ **Clear expectations**: Users know PyTorch CSE requires client script changes
2. ✅ **Working examples**: Both NumPy and PyTorch examples in docstring
3. ✅ **Architecture understanding**: Explains why NumPy and PyTorch differ
4. ✅ **Prevents confusion**: No more "why isn't CSE working?" for PyTorch users
5. ✅ **Points to reference**: Links to hello-pt example

---

## 🔍 Reference

**Working PyTorch CSE Example**: `examples/hello-world/hello-pt/`
- `job.py` line 56: Adds CSE with `add_cross_site_evaluation(recipe)`
- `client.py` lines 98-103: Handles validation with `flare.is_evaluate()`

**Files Modified**:
- `nvflare/recipe/utils.py`: Lines 103-122 (warning), 124-149 (examples), 160-167 (note)

---

**Status**: ✅ **Documentation Clarified**  
**No Code Logic Changes**: PyTorch CSE worked correctly, only docs were misleading
