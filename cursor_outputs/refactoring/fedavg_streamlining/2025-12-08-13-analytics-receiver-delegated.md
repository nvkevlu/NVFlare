# Analytics Receiver Delegated to Child Classes

**Date:** December 8, 2025
**Issue:** Framework-specific `TBAnalyticsReceiver` logic was in the unified `FedAvgRecipe`

## Problem

The unified `FedAvgRecipe` contained PyTorch/TensorFlow-specific logic for providing default analytics receivers:

```python
# Before (in unified recipe)
analytics_receiver = None
if self.framework in (FrameworkType.PYTORCH, FrameworkType.TENSORFLOW):
    from nvflare.app_opt.tracking.tb.tb_receiver import TBAnalyticsReceiver
    analytics_receiver = TBAnalyticsReceiver()

job = BaseFedJob(
    name=self.name,
    min_clients=self.min_clients,
    analytics_receiver=analytics_receiver,
)
```

**Issues:**
- ❌ Framework-specific import in unified recipe
- ❌ Framework branching logic (`if self.framework in ...`)
- ❌ Violates the principle of keeping unified code framework-agnostic
- ❌ Similar to the model setup issue we already fixed

## Solution

Introduced a new overridable method `_get_analytics_receiver()` that child classes can override:

### Unified FedAvgRecipe (Base)

**Removed framework-specific logic:**
```python
# After (unified recipe - framework-agnostic!)
job = BaseFedJob(
    name=self.name,
    min_clients=self.min_clients,
    analytics_receiver=self._get_analytics_receiver(),  # Delegates to child classes
)
```

**Added overridable method:**
```python
def _get_analytics_receiver(self):
    """Get the analytics receiver for this recipe.

    Returns:
        AnalyticsReceiver or None: The analytics receiver to use, or None for no analytics.

    Note:
        Child classes (PT/TF wrappers) can override this to provide framework-specific defaults.
    """
    return None  # Base implementation: no analytics
```

### PyTorch FedAvgRecipe (Child)

```python
def _get_analytics_receiver(self):
    """Override to provide PyTorch-specific default TBAnalyticsReceiver."""
    from nvflare.app_opt.tracking.tb.tb_receiver import TBAnalyticsReceiver

    return TBAnalyticsReceiver()
```

### TensorFlow FedAvgRecipe (Child)

```python
def _get_analytics_receiver(self):
    """Override to provide TensorFlow-specific default TBAnalyticsReceiver."""
    from nvflare.app_opt.tracking.tb.tb_receiver import TBAnalyticsReceiver

    return TBAnalyticsReceiver()
```

### Sklearn FedAvgRecipe (Child)

**No override needed!** Inherits base implementation that returns `None` (sklearn doesn't use TensorBoard analytics by default).

## Benefits

✅ **Unified recipe is truly framework-agnostic** - No PT/TF imports or branching
✅ **Consistent architecture** - Matches the model setup delegation pattern
✅ **Clean separation** - Framework-specific defaults in framework-specific classes
✅ **Lazy imports in right place** - Only loaded by frameworks that need them
✅ **Extensible** - Easy for custom frameworks to provide their own analytics

## Pattern Consistency

This completes the delegation pattern we established:

| Concern | Unified Base | PT Wrapper | TF Wrapper | Sklearn Wrapper |
|---------|--------------|------------|------------|-----------------|
| **Analytics Receiver** | None (base) | TBAnalyticsReceiver | TBAnalyticsReceiver | None (inherited) |
| **Model Setup** | Delegates | PT-specific | TF-specific | Persistor creation |
| **Model Locator** | N/A | Stores & uses | N/A | N/A |

**All framework-specific logic now lives in framework-specific classes!** 🎯

## Before vs After

### Before: Framework Branching in Unified Recipe

```python
# Unified recipe had framework-specific knowledge
analytics_receiver = None
if self.framework in (FrameworkType.PYTORCH, FrameworkType.TENSORFLOW):
    from nvflare.app_opt.tracking.tb.tb_receiver import TBAnalyticsReceiver  # ❌ PT/TF import
    analytics_receiver = TBAnalyticsReceiver()
```

### After: Clean Delegation Pattern

```python
# Unified recipe delegates to child classes
job = BaseFedJob(
    analytics_receiver=self._get_analytics_receiver(),  # ✅ Child handles specifics
)

# Base implementation (returns None)
def _get_analytics_receiver(self):
    return None

# PT/TF override (returns TBAnalyticsReceiver)
def _get_analytics_receiver(self):
    from nvflare.app_opt.tracking.tb.tb_receiver import TBAnalyticsReceiver
    return TBAnalyticsReceiver()
```

## Why This Matters

**Lazy imports are useful BUT:**
- ✅ They should be in framework-specific code, not unified code
- ✅ Unified code should be completely framework-agnostic
- ✅ No conditional imports based on framework type in base classes

**The delegation pattern ensures:**
- Framework-specific logic stays in framework-specific files
- Unified recipe has zero knowledge of PT/TF/sklearn specifics
- Easy to add new frameworks without touching unified code

## Files Changed

### Modified
- `nvflare/recipe/fedavg.py`
  - Removed `if self.framework in (FrameworkType.PYTORCH, FrameworkType.TENSORFLOW)` logic
  - Removed `TBAnalyticsReceiver` import
  - Added `_get_analytics_receiver()` method (returns `None`)
  - Changed `BaseFedJob` to call `self._get_analytics_receiver()`

- `nvflare/app_opt/pt/recipes/fedavg.py`
  - Added `_get_analytics_receiver()` override returning `TBAnalyticsReceiver()`

- `nvflare/app_opt/tf/recipes/fedavg.py`
  - Added `_get_analytics_receiver()` override returning `TBAnalyticsReceiver()`

### No Changes Needed
- `nvflare/app_opt/sklearn/recipes/fedavg.py` - Inherits base (returns `None`)

## Verification

✅ All linting passes
✅ No framework-specific imports in unified recipe
✅ No framework branching in unified recipe
✅ PT/TF still get TBAnalyticsReceiver by default
✅ Sklearn gets no analytics by default
✅ Consistent with model setup delegation pattern

---

**Unified recipe is now completely framework-agnostic!** No more PT/TF-specific code. 🌟
