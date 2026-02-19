# NumPy Framework Type Mismatch - Critical Fix Needed

**Date**: January 12, 2026  
**Issue**: Inconsistency between FrameworkType.RAW and FrameworkType.NUMPY causing parameter exchange mismatch  
**Status**: ⚠️ **IDENTIFIED - REQUIRES DECISION**

---

## 🐛 Problem

### Issue 1: Framework/ExchangeFormat Mismatch

In `NumpyFedAvgRecipe`:
```python
# Line 121
framework: FrameworkType = FrameworkType.RAW  # Default parameter

# Line 122  
server_expected_format: ExchangeFormat = ExchangeFormat.NUMPY  # Explicit

# Line 194 - Passes to ScriptRunner
executor = ScriptRunner(
    framework=self.framework,  # FrameworkType.RAW
    server_expected_format=self.server_expected_format,  # ExchangeFormat.NUMPY
    ...
)
```

In `ScriptRunner.__init__()` (lines 139-142):
```python
elif self._framework == FrameworkType.NUMPY:
    self._params_exchange_format = ExchangeFormat.NUMPY
elif self._framework == FrameworkType.RAW:
    self._params_exchange_format = ExchangeFormat.RAW  # ← This gets set!
```

**The Mismatch**:
- Recipe has `framework=FrameworkType.RAW`
- ScriptRunner sets `params_exchange_format=ExchangeFormat.RAW` based on framework
- But `server_expected_format=ExchangeFormat.NUMPY` is explicitly passed
- **Result**: Internal exchange format (RAW) ≠ Server expected format (NUMPY)

### Issue 2: Public API Exposure

The `framework` parameter is exposed as a public API parameter but:
- Users should NOT change it from `FrameworkType.RAW` for NumPy recipes
- If user sets `framework=FrameworkType.PYTORCH`, `add_cross_site_evaluation()` would select PyTorch model locator → Wrong!
- No validation prevents mismatched framework types

---

## ⚠️ Why This Matters

### Potential Bugs

1. **Parameter Exchange Confusion**:
   - ScriptRunner internally uses RAW format
   - Server expects NUMPY format
   - Could cause subtle serialization/deserialization issues

2. **CSE Auto-Detection Breakage**:
   ```python
   recipe = NumpyFedAvgRecipe(framework=FrameworkType.PYTORCH, ...)  # User mistake!
   add_cross_site_evaluation(recipe)  # Selects PTFileModelLocator → Wrong!
   ```

3. **Type Safety**:
   - No validation prevents framework type mismatch
   - Silent failures possible

---

## 🤔 Root Cause Analysis

### The "Dual Personality" Problem

FrameworkType serves TWO distinct purposes:

1. **Internal Purpose** (ScriptRunner):
   - Determines `params_exchange_format`
   - Should be `FrameworkType.NUMPY` for proper NumPy param exchange

2. **External Purpose** (Recipe API):
   - Used by utilities like `add_cross_site_evaluation()`
   - Should be `FrameworkType.RAW` for CSE auto-detection

The documentation even acknowledges this split (line 78-82):
> "This is distinct from the internal FrameworkType.NUMPY used by ScriptRunner, and is exposed here so that helper APIs such as add_cross_site_evaluation() can correctly auto-detect the framework for this recipe."

**This is a design smell** - one parameter serving two purposes.

---

## 💡 Proposed Solutions

### Option A: Separate Internal/External Framework (Recommended)

**Keep framework parameter internal, use FrameworkType.NUMPY for ScriptRunner**:

```python
class NumpyFedAvgRecipe(Recipe):
    def __init__(
        self,
        *,
        # ... other params ...
        # Remove framework from public API
    ):
        # Internal: Use NUMPY for ScriptRunner
        self._internal_framework = FrameworkType.NUMPY
        
        # External: Use RAW for recipe API (CSE, etc.)
        self.framework = FrameworkType.RAW
        
        executor = ScriptRunner(
            framework=self._internal_framework,  # FrameworkType.NUMPY
            server_expected_format=ExchangeFormat.NUMPY,  # Consistent!
            ...
        )
```

**Benefits**:
- ✅ Fixes mismatch: NUMPY ↔ NUMPY
- ✅ Prevents user errors (no public framework param)
- ✅ Clear separation of concerns
- ✅ CSE auto-detection still works (uses `self.framework`)

**Drawbacks**:
- ⚠️ Breaking change (removes public parameter)
- ⚠️ Need to update examples/docs

---

### Option B: Add Validation (Safer, Non-Breaking)

**Keep framework parameter but validate it**:

```python
class NumpyFedAvgRecipe(Recipe):
    def __init__(
        self,
        *,
        framework: FrameworkType = FrameworkType.RAW,
        # ... other params ...
    ):
        # Validate framework is appropriate for NumPy recipe
        if framework not in [FrameworkType.RAW, FrameworkType.NUMPY]:
            raise ValueError(
                f"NumpyFedAvgRecipe only supports FrameworkType.RAW or FrameworkType.NUMPY, "
                f"but got {framework}. "
                f"Use FrameworkType.RAW (recommended) for CSE auto-detection, "
                f"or FrameworkType.NUMPY for explicit NumPy parameter exchange."
            )
        
        self.framework = framework
        
        # Always use NUMPY for ScriptRunner to ensure correct param exchange
        internal_framework = FrameworkType.NUMPY
        
        executor = ScriptRunner(
            framework=internal_framework,  # Always NUMPY
            server_expected_format=ExchangeFormat.NUMPY,
            ...
        )
```

**Benefits**:
- ✅ No breaking changes
- ✅ Prevents wrong framework types
- ✅ Clear error messages
- ✅ Fixes mismatch internally

**Drawbacks**:
- ⚠️ Still allows users to set framework (confusing API)
- ⚠️ Doesn't fully solve "dual personality" problem

---

### Option C: Document and Warn (Minimal, Not Recommended)

**Add clear documentation and runtime warning**:

```python
class NumpyFedAvgRecipe(Recipe):
    def __init__(
        self,
        *,
        framework: FrameworkType = FrameworkType.RAW,
        # ... other params ...
    ):
        """
        ...
        Args:
            framework: **INTERNAL USE ONLY**. Do not modify unless you know what you're doing.
                      Defaults to FrameworkType.RAW for proper CSE auto-detection.
                      Changing this may break cross-site evaluation and parameter exchange.
        """
        if framework != FrameworkType.RAW:
            import warnings
            warnings.warn(
                f"NumpyFedAvgRecipe framework parameter set to {framework} instead of RAW. "
                f"This may cause issues with CSE auto-detection and parameter exchange.",
                UserWarning
            )
        
        self.framework = framework
        
        # Use NUMPY internally
        executor = ScriptRunner(
            framework=FrameworkType.NUMPY,  # Hard-coded
            ...
        )
```

**Benefits**:
- ✅ No breaking changes
- ✅ Minimal code changes

**Drawbacks**:
- ❌ Doesn't prevent errors, just warns
- ❌ Confusing API remains
- ❌ Users might ignore warnings

---

## 📊 Comparison

| Aspect | Option A | Option B | Option C |
|--------|----------|----------|----------|
| **Fixes Mismatch** | ✅ Yes | ✅ Yes | ✅ Yes |
| **Prevents User Errors** | ✅ Yes (no param) | ⚠️ Partial (validation) | ❌ No (just warns) |
| **Breaking Changes** | ⚠️ Yes | ✅ No | ✅ No |
| **API Clarity** | ✅ Clear | ⚠️ Acceptable | ❌ Confusing |
| **Maintenance** | ✅ Clean | ⚠️ OK | ❌ Fragile |

---

## 🎯 Recommendation

**Option B (Validation)** for this PR because:
1. **No breaking changes** - existing code continues to work
2. **Fixes the mismatch** - ScriptRunner uses NUMPY internally
3. **Prevents errors** - Validation catches wrong framework types
4. **Good error messages** - Users understand what went wrong

**Option A** should be considered for a future major version (NVFlare 3.0) as the proper long-term solution.

---

## 🔧 Implementation (Option B)

```python
# In NumpyFedAvgRecipe.__init__()

# Validate framework parameter
if framework not in [FrameworkType.RAW, FrameworkType.NUMPY]:
    raise ValueError(
        f"NumpyFedAvgRecipe only supports FrameworkType.RAW or FrameworkType.NUMPY, "
        f"but got {framework}. "
        f"For NumPy-based recipes, use FrameworkType.RAW (recommended for CSE compatibility)."
    )

# Store for external use (CSE, etc.)
self.framework = framework

# Always use NUMPY internally for correct parameter exchange
_internal_framework = FrameworkType.NUMPY

executor = ScriptRunner(
    script=self.train_script,
    script_args=self.train_args,
    launch_external_process=self.launch_external_process,
    command=self.command,
    framework=_internal_framework,  # ← Changed from self.framework
    server_expected_format=self.server_expected_format,
    params_transfer_type=self.params_transfer_type,
)
```

---

## 📝 Documentation Updates

Update docstring to clarify:

```python
framework: Framework type for the recipe. Defaults to FrameworkType.RAW, which is the
    recommended value for NumPy-based recipes. This parameter is used by utilities
    like add_cross_site_evaluation() for framework auto-detection. Valid values are
    FrameworkType.RAW or FrameworkType.NUMPY. **Do not set to PYTORCH or TENSORFLOW
    for NumPy recipes** - this will cause CSE and parameter exchange to fail.
```

---

## ⚠️ Impact Assessment

### Who Is Affected?

1. **Users passing framework parameter explicitly**:
   ```python
   recipe = NumpyFedAvgRecipe(framework=FrameworkType.PYTORCH, ...)  
   # ❌ Will now raise ValueError
   ```
   - **Impact**: Positive - prevents bugs

2. **Users using default**:
   ```python
   recipe = NumpyFedAvgRecipe(...)  # framework=RAW (default)
   ```
   - **Impact**: None - works as before

3. **Internal ScriptRunner**:
   - **Impact**: Positive - now uses correct NUMPY format

### Testing

Need to verify:
- ✅ Default case still works
- ✅ framework=RAW works
- ✅ framework=NUMPY works
- ✅ framework=PYTORCH raises ValueError
- ✅ CSE auto-detection uses recipe.framework (external)
- ✅ ScriptRunner uses NUMPY internally
- ✅ Parameter exchange works correctly

---

## 🔗 Related Issues

This is related to the framework fix mentioned in the previous session that got "hopelessly stuck". The original attempt to fix framework parameter handling introduced this inconsistency.

---

**Status**: ✅ **IMPLEMENTED - Option A**  
**Decision**: Since framework parameter was just added today (not released), removed it from public API  
**Implementation**: Clean separation - RAW for external APIs, NUMPY for ScriptRunner
