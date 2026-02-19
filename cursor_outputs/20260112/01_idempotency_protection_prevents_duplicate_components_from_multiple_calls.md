# Idempotency Protection for add_cross_site_evaluation()

**Date**: January 12, 2026  
**Issue**: Multiple calls to `add_cross_site_evaluation()` would add duplicate components  
**Status**: ✅ Fixed

---

## 🐛 Problem

The `add_cross_site_evaluation()` function had no protection against being called multiple times on the same recipe, causing:

1. **Duplicate model locators** (line 191)
2. **Duplicate ValidationJsonGenerator instances** (line 194)
3. **Duplicate CrossSiteModelEval controllers** (line 202)
4. **Duplicate NPValidator instances** for NumPy recipes (line 218)

**Impact**: Resource waste, runtime conflicts, unexpected behavior

---

## ✅ Solution

Added simple flag-based idempotency check:

### 1. Check Before Proceeding

```python
# Idempotency check: prevent multiple calls on the same recipe
if hasattr(recipe, "_cse_added") and recipe._cse_added:
    raise RuntimeError(
        f"Cross-site evaluation has already been added to recipe '{recipe.name}'. "
        "Calling add_cross_site_evaluation() multiple times would create duplicate "
        "model locators, validators, and controllers, which can cause unexpected behavior. "
        "Please call this function only once per recipe instance."
    )
```

**Location**: Lines 136-143 in `nvflare/recipe/utils.py`

### 2. Set Flag After Success

```python
# Mark that CSE has been added to prevent duplicate calls
recipe._cse_added = True
```

**Location**: Line 221 in `nvflare/recipe/utils.py`

### 3. Updated Documentation

Added to function docstring:

```python
**WARNING**: Do not call this function multiple times on the same recipe instance.
This function is idempotent and will raise a RuntimeError if called more than once
on the same recipe to prevent duplicate component registration.

Raises:
    ValueError: If the recipe doesn't have a framework attribute or uses an unsupported framework.
    RuntimeError: If cross-site evaluation has already been added to this recipe.
```

---

## 🎯 Design Decision

**Why a simple flag?**

Considered alternatives:
- ❌ **Component inspection**: Too fragile, depends on internal structure
- ❌ **Global registry**: Overkill, potential memory leaks
- ✅ **Simple flag**: Clear, effective, minimal overhead

**Why raise instead of silent no-op?**
- Fail fast to surface bugs immediately
- Multiple calls likely indicate programming error
- Clear error message guides users to fix

---

## 📝 Testing

```python
from nvflare.app_common.np.recipes import NumpyFedAvgRecipe
from nvflare.recipe.utils import add_cross_site_evaluation

recipe = NumpyFedAvgRecipe(
    name="my-job", min_clients=2, num_rounds=3, train_script="client.py"
)

# First call: ✓ succeeds
add_cross_site_evaluation(recipe)

# Second call: ✓ raises RuntimeError
try:
    add_cross_site_evaluation(recipe)
except RuntimeError as e:
    print(f"Expected: {e}")
```

**Expected Output**:
```
Expected: Cross-site evaluation has already been added to recipe 'my-job'. 
Calling add_cross_site_evaluation() multiple times would create duplicate 
model locators, validators, and controllers, which can cause unexpected behavior. 
Please call this function only once per recipe instance.
```

---

## ✨ Benefits

- ✅ Prevents resource waste and runtime conflicts
- ✅ Clear, actionable error messages
- ✅ Minimal overhead (~10 lines of code)
- ✅ No breaking changes
- ✅ Flag only set after successful configuration (allows retry on error)

---

**Files Modified**:
- `nvflare/recipe/utils.py`: Lines 99-101, 121-123, 136-143, 221
