# Analytics Receiver Made Opt-In (2025-12-12)

## Issue

After the refactoring, both `BaseFedJob` and `FedAvgRecipe` for PyTorch and TensorFlow were **defaulting to `TBAnalyticsReceiver`**, which caused a critical problem:

**Users importing TensorFlow recipe would get `ModuleNotFoundError: No module named 'torch'`** because `TBAnalyticsReceiver` imports `torch.utils.tensorboard` at module level.

### Original Error

```python
from nvflare.app_opt.tf.recipes.fedavg import FedAvgRecipe

# Error: ModuleNotFoundError: No module named 'torch'
# Because TBAnalyticsReceiver imports torch.utils.tensorboard
```

## Root Causes

### Issue 1: Module-Level Imports in BaseFedJob (FIXED, then regression)
PT/TF `BaseFedJob` wrappers had module-level import of `TBAnalyticsReceiver`, causing torch to be loaded even when just importing the module.

### Issue 2: Recipe Calling _get_analytics_receiver() (MAIN ISSUE)
The unified `FedAvgRecipe` was calling `self._get_analytics_receiver()` in `__init__`, which forced the lazy import to execute even when users didn't want tracking:

```python
# ❌ WRONG: Always calls _get_analytics_receiver(), forcing torch import
job = BaseFedJob(
    name=self.name,
    min_clients=self.min_clients,
    analytics_receiver=self._get_analytics_receiver(),  # ← Always called!
)
```

## Solution

Made experiment tracking **fully opt-in** at all levels:

### 1. BaseFedJob: No Default Analytics Receiver
```python
# ✅ CORRECT: Just pass through analytics_receiver (may be None)
super().__init__(
    ...
    analytics_receiver=analytics_receiver,  # No default!
)
```

### 2. Recipes: Add analytics_receiver Parameter
Added `analytics_receiver` parameter to all recipes with lazy default:

```python
def __init__(
    self,
    *,
    ...
    analytics_receiver: Optional[AnalyticsReceiver] = None,
):
    # Default to TBAnalyticsReceiver if not provided (lazy import)
    if analytics_receiver is None:
        from nvflare.app_opt.tracking.tb.tb_receiver import TBAnalyticsReceiver
        analytics_receiver = TBAnalyticsReceiver()
    
    super().__init__(..., analytics_receiver=analytics_receiver)
```

**Key difference**: The lazy import only happens if `analytics_receiver` is `None` **AND** the user actually instantiates the recipe. Just importing the module doesn't trigger torch import.

### 3. Unified Recipe: Accept and Pass Through
Removed `_get_analytics_receiver()` method from unified recipe and added parameter:

```python
def __init__(
    self,
    *,
    ...
    analytics_receiver: Optional[AnalyticsReceiver] = None,
):
    ...
    job = BaseFedJob(
        name=self.name,
        min_clients=self.min_clients,
        analytics_receiver=self.analytics_receiver,  # ✅ Pass through, don't call method
    )
```

## Behavior After Fix

**ALL LEVELS ARE NOW FULLY OPT-IN** ✅

1. **`BaseFedJob` (PT/TF)**: NO default experiment tracking ✅
   - Must explicitly pass `analytics_receiver` to enable tracking
   - No framework dependency unless explicitly requested
   - Fully opt-in

2. **`FedAvgRecipe` (unified)**: NO default experiment tracking ✅
   - Must explicitly pass `analytics_receiver` to enable tracking
   - Framework-agnostic
   - Fully opt-in

3. **`FedAvgRecipe` (PT/TF wrappers)**: NO default experiment tracking ✅
   - Must explicitly pass `analytics_receiver` to enable tracking
   - No torch/tensorflow import unless tracking is explicitly enabled
   - Fully opt-in

## Files Modified

1. **`nvflare/app_opt/pt/job_config/base_fed_job.py`**
   - Removed module-level `TBAnalyticsReceiver` import
   - Removed default `TBAnalyticsReceiver` instantiation
   - Updated docstring to clarify opt-in behavior

2. **`nvflare/app_opt/tf/job_config/base_fed_job.py`**
   - Removed module-level `TBAnalyticsReceiver` import
   - Removed default `TBAnalyticsReceiver` instantiation
   - Updated docstring to clarify opt-in behavior

3. **`nvflare/recipe/fedavg.py`**
   - Added `analytics_receiver` parameter
   - Removed `_get_analytics_receiver()` method
   - Updated to pass through `analytics_receiver` instead of calling method

4. **`nvflare/app_opt/pt/recipes/fedavg.py`**
   - Added `analytics_receiver` parameter
   - Removed `_get_analytics_receiver()` method override
   - Removed default `TBAnalyticsReceiver` instantiation (fully opt-in)
   - Added comprehensive documentation with examples

5. **`nvflare/app_opt/tf/recipes/fedavg.py`**
   - Added `analytics_receiver` parameter
   - Removed `_get_analytics_receiver()` method override
   - Removed default `TBAnalyticsReceiver` instantiation (fully opt-in)
   - Added comprehensive documentation with examples

## Key Principles

- **BaseFedJob**: Low-level, flexible, minimal defaults, fully opt-in
- **Unified Recipe**: Framework-agnostic, opt-in by default
- **Framework Recipes**: Convenient defaults via lazy imports (opt-out available)
- **Dependencies**: Framework dependencies only loaded when actually needed

## Testing Scenarios

✅ **Import without instantiation** (no torch needed):
```python
from nvflare.app_opt.tf.recipes.fedavg import FedAvgRecipe
# ✅ Works - no torch imported
```

✅ **Instantiate without tracking** (no torch needed):
```python
recipe = FedAvgRecipe(
    name="cifar10_tf_fedavg",
    min_clients=2,
    num_rounds=2,
    initial_model=TFNet(),
    train_script="client.py",
)
# ✅ No torch imported, no TBAnalyticsReceiver created
```

✅ **Enable tracking explicitly** (torch needed only here):
```python
from nvflare.app_opt.tracking.tb.tb_receiver import TBAnalyticsReceiver

recipe = FedAvgRecipe(
    name="cifar10_tf_fedavg",
    min_clients=2,
    num_rounds=2,
    initial_model=TFNet(),
    train_script="client.py",
    analytics_receiver=TBAnalyticsReceiver()  # ✅ torch imported here
)
```

✅ **Add tracking after creation** (torch needed only here):
```python
from nvflare.recipe.utils import add_experiment_tracking

recipe = FedAvgRecipe(...)  # ✅ No torch yet
add_experiment_tracking(recipe, "tensorboard")  # ✅ torch imported here
```

✅ **Use BaseFedJob** (fully opt-in):
```python
from nvflare.app_opt.pt.job_config.base_fed_job import BaseFedJob
job = BaseFedJob(...)  # ✅ No TBAnalyticsReceiver, fully opt-in
```

## How to Enable Experiment Tracking

Users have two options to enable experiment tracking:

### Option 1: Pass Explicitly During Creation
```python
from nvflare.app_opt.tracking.tb.tb_receiver import TBAnalyticsReceiver

recipe = FedAvgRecipe(
    ...,
    analytics_receiver=TBAnalyticsReceiver()
)
```

### Option 2: Add After Creation
```python
from nvflare.recipe.utils import add_experiment_tracking

recipe = FedAvgRecipe(...)
add_experiment_tracking(recipe, "tensorboard")  # or "mlflow" or "wandb"
```

