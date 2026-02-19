# TFValidator Usage Clarification

**Date**: January 13, 2026  
**Issue**: Unclear when to use TFValidator vs Client API pattern for TensorFlow CSE  
**Status**: ✅ **DOCUMENTED**

---

## 🤔 Problem

When implementing TensorFlow CSE support, we created `TFValidator` but the documentation in `nvflare/recipe/utils.py` stated:

> "TensorFlow and PyTorch use Client API pattern (flare.is_evaluate()). Validators are not auto-added for these frameworks."

This created confusion:
1. **Why does `TFValidator` exist** if TensorFlow uses Client API pattern?
2. **When should users use `TFValidator`** vs `flare.is_evaluate()`?
3. **Is `TFValidator` the recommended approach** or just for backward compatibility?
4. **How do users actually use `TFValidator`** if it's not auto-added?

Without clear guidance, users might:
- Not know `TFValidator` exists
- Use the wrong pattern for their use case
- Be confused about TensorFlow having two validation approaches

---

## ✅ Solution

Clarified that TensorFlow supports **two validation patterns**, with clear guidance on when to use each.

### Two Validation Patterns for TensorFlow

| Pattern | When to Use | Auto-added? | Example |
|---------|-------------|-------------|---------|
| **Client API** (recommended) | Default for most cases, tightly coupled training/validation | ❌ No | `flare.is_evaluate()` in script |
| **Component-based** (TFValidator) | Separate validation logic, CSE-only recipes, reusable validators | ❌ No (manual) | `recipe.job.to_clients(validator)` |

---

## 📝 Documentation Updates

### 1. Enhanced `TFValidator` Docstring

**File**: `nvflare/app_opt/tf/tf_validator.py` (lines 29-96)

**Added**:
- Clear explanation of when to use TFValidator vs Client API
- Decision matrix for choosing the right pattern
- Two complete usage examples (component-based and Client API)
- Explicit recommendation: "Use Client API pattern for consistency and simplicity"
- Purpose statement: "TFValidator is provided for flexibility and backward compatibility"

**Key Section**:
```python
"""Component-based TensorFlow Validator for cross-site evaluation.

This validator provides an alternative to the Client API pattern (flare.is_evaluate()) for
TensorFlow cross-site evaluation. Use this when you prefer a component-based approach or when
your validation logic is separate from your training script.

**When to use TFValidator vs Client API pattern:**

Use TFValidator (component-based) when:
- You prefer explicit validation components separate from training logic
- Your validation code is reusable across multiple projects
- You want validation to work without modifying your training script
- Your recipe is CSE-only (no training, only validation)

Use Client API pattern (flare.is_evaluate()) when:
- Your validation logic is tightly coupled with training (e.g., same preprocessing)
- You want a single script that handles both training and validation
- You're already using Client API for training (recommended for most cases)

**Default recommendation**: Use Client API pattern (like PyTorch) for consistency and simplicity.
TFValidator is provided for flexibility and backward compatibility with NumPy-style workflows.
```

### 2. Added TensorFlow Component-Based Example

**File**: `nvflare/recipe/utils.py` (lines 169-184)

**Added new example** showing how to manually use `TFValidator`:

```python
Example (TensorFlow - Component-based alternative):
    ```python
    from nvflare.app_opt.tf.recipes import FedAvgRecipe
    from nvflare.app_opt.tf.tf_validator import TFValidator
    from nvflare.recipe.utils import add_cross_site_evaluation

    recipe = FedAvgRecipe(
        name="my-job", min_clients=2, num_rounds=3,
        initial_model=MyTFModel(), train_script="client.py"
    )

    add_cross_site_evaluation(recipe)

    # Optional: manually add TFValidator for component-based validation
    validator = TFValidator(model=my_model, data_loader=test_loader)
    recipe.job.to_clients(validator, tasks=["validate"])
    ```
```

### 3. Updated Implementation Note

**File**: `nvflare/recipe/utils.py` (lines 299-303)

**Before**:
```python
# Note: TensorFlow and PyTorch use Client API pattern (flare.is_evaluate())
# Validators are not auto-added for these frameworks as they handle validation
# in the training script itself
```

**After**:
```python
# Note: TensorFlow and PyTorch use Client API pattern (flare.is_evaluate()) by default.
# Validators are not auto-added for these frameworks as they typically handle validation
# in the training script itself. However, TFValidator is available for users who prefer
# a component-based approach (similar to NumPy's NPValidator) - it must be manually added
# to the job using recipe.job.to_clients(validator, tasks=["validate"])
```

---

## 🎯 Decision Guide for Users

### Choose Client API Pattern When:

✅ **Most common case** - training and validation in same script  
✅ **Consistency** - already using Client API for training  
✅ **Simplicity** - single script handles everything  
✅ **Tight coupling** - validation uses same preprocessing as training

**Example use case**: Standard federated learning with periodic validation

```python
# client.py
while flare.is_running():
    input_model = flare.receive()
    
    metrics = evaluate(model, test_loader)
    
    if flare.is_evaluate():  # CSE validation
        flare.send(flare.FLModel(metrics=metrics))
        continue
    
    # Training code...
```

### Choose TFValidator (Component) When:

✅ **Separation** - validation logic separate from training  
✅ **Reusability** - same validator across multiple projects  
✅ **CSE-only** - no training, only cross-site evaluation  
✅ **No script modification** - validation without changing training script

**Example use case**: CSE-only recipe for model comparison

```python
from nvflare.app_opt.tf.recipes import CrossSiteEvalRecipe
from nvflare.app_opt.tf.tf_validator import TFValidator

recipe = CrossSiteEvalRecipe(name="cse-only", initial_model=model)

validator = TFValidator(
    model=model,
    data_loader=test_loader,
    metric_fn=custom_metrics
)
recipe.job.to_clients(validator, tasks=["validate"])
```

---

## 📊 Framework Comparison

| Framework | Primary Pattern | Alternative Pattern | Auto-added? |
|-----------|----------------|---------------------|-------------|
| **NumPy** | Component (NPValidator) | N/A | ✅ Yes |
| **PyTorch** | Client API (`flare.is_evaluate()`) | N/A | ❌ No |
| **TensorFlow** | Client API (`flare.is_evaluate()`) | Component (TFValidator) | ❌ No |

**Why TensorFlow has both**:
- **Primary**: Client API for consistency with PyTorch
- **Alternative**: TFValidator for users migrating from NumPy or preferring component-based approach

---

## 🔍 Why TFValidator Exists

### Design Rationale

1. **Flexibility**: Some users prefer component-based validation (like NumPy)
2. **Migration path**: Easier for NumPy users to move to TensorFlow
3. **CSE-only recipes**: Component approach works better for validation-only workflows
4. **Reusability**: Validators can be packaged and reused across projects
5. **Backward compatibility**: Aligns with existing NVFlare patterns

### Not a Mistake

`TFValidator` is **intentionally provided** as an alternative, not a legacy component. It serves legitimate use cases where component-based validation is preferred.

---

## ✨ Benefits of Clarification

1. ✅ **Clear decision criteria**: Users know when to use each pattern
2. ✅ **Explicit recommendation**: Client API is default, TFValidator is alternative
3. ✅ **Complete examples**: Both patterns fully documented
4. ✅ **No confusion**: Purpose of TFValidator clearly stated
5. ✅ **Flexibility preserved**: Users can choose the pattern that fits their needs

---

## 📝 Files Modified

1. **`nvflare/app_opt/tf/tf_validator.py`** (lines 36-96):
   - Expanded docstring from 7 lines to 60+ lines
   - Added decision matrix
   - Added two complete usage examples
   - Clarified purpose and recommendation

2. **`nvflare/recipe/utils.py`** (lines 156-184, 299-303):
   - Renamed TensorFlow example to "Client API pattern, recommended"
   - Added new "Component-based alternative" example
   - Updated implementation note to mention TFValidator availability

---

## 🎓 Key Takeaways

1. **Default**: Use Client API pattern (`flare.is_evaluate()`) for TensorFlow CSE
2. **Alternative**: Use `TFValidator` when you need component-based validation
3. **Not auto-added**: Both patterns require explicit setup (unlike NumPy)
4. **Intentional design**: TFValidator provides flexibility, not legacy support
5. **Clear docs**: Users now have complete guidance on choosing the right pattern

---

**Status**: ✅ **DOCUMENTED AND CLARIFIED**  
**Lines Added**: ~80 (documentation)  
**Breaking Changes**: None (clarification only)  
**User Impact**: Eliminates confusion, provides clear guidance
