# Cleanup: Removed Unused Storage from BaseFedJob

## Issue

User identified that `self.framework` was stored in `BaseFedJob` but never actually read. Investigation revealed multiple other similar issues.

## What Was Removed

### ❌ Removed from BaseFedJob (Never Read):

```python
# Before:
self.initial_model = initial_model      # ❌ Stored but never read
self.initial_params = initial_params    # ❌ Stored but never read
self.framework = framework              # ❌ Stored but never read
self.model_persistor = model_persistor  # ❌ Stored but never read

# After:
# All removed! ✅
```

### ✅ Kept in BaseFedJob (Actually Used):

```python
self.comp_ids = {}                      # ✅ Used to track component IDs
self.convert_to_fed_event = ...         # ✅ Used in set_up_client() method
```

## Why These Were Unnecessary

### 1. `self.framework`
- **Stored:** Line 100 in BaseFedJob
- **Read:** NEVER in BaseFedJob or child classes
- **Used:** Only in recipes (FedAvgRecipe, CyclicRecipe) as their own instance variable
- **Passed:** As a parameter to constructors, not read from parent

### 2. `self.initial_model`
- **Stored:** Line 98 in BaseFedJob
- **Read:** NEVER in BaseFedJob or child classes
- **Used:** Only in FedAvgRecipe as its own instance variable
- **Pattern:** Child classes receive it as constructor parameter and pass directly to setup methods

### 3. `self.initial_params`
- **Stored:** Line 99 in BaseFedJob
- **Read:** NEVER in BaseFedJob or child classes
- **Used:** Only by `JoblibModelParamPersistor` (which receives it in its own constructor)
- **Pattern:** Passed through recipe wrapper, not through parent storage

### 4. `self.model_persistor`
- **Stored:** Line 139 in BaseFedJob with comment "Store these for child classes to use"
- **Read:** NEVER by child classes!
- **Pattern:** Child classes receive it as constructor parameter and pass directly to model setup methods
- **Example (PT wrapper):**
  ```python
  def __init__(self, ..., model_persistor=None):
      super().__init__(..., model_persistor=model_persistor)  # Stored (unnecessary)
      if initial_model:
          self._setup_pytorch_model(initial_model, model_persistor, ...)  # Used directly!
  ```

## Verification

### Grep Results:

**BaseFedJob reads:**
```bash
$ grep "self\.(framework|initial_model|initial_params|model_persistor)" nvflare/job_config/base_fed_job.py
# Only WRITE operations found, no READ operations
```

**Child classes read:**
```bash
$ grep "self\.(framework|initial_model|initial_params|model_persistor)" nvflare/app_opt/pt/job_config/base_fed_job.py
# No matches (PT wrapper doesn't read them)

$ grep "self\.(framework|initial_model|initial_params|model_persistor)" nvflare/app_opt/tf/job_config/base_fed_job.py
# No matches (TF wrapper doesn't read them)
```

**External code reads:**
```bash
$ grep "job\.(framework|initial_model|initial_params|model_persistor)" nvflare/
# No matches (no external code accesses these)
```

## Where These ARE Used

### `framework`
- ✅ `FedAvgRecipe` - stores and uses extensively for logic branching
- ✅ `CyclicRecipe` - stores and uses for ScriptRunner configuration
- ✅ Passed as constructor parameters, not inherited from parent

### `initial_model`
- ✅ `FedAvgRecipe` - stores and uses for validation and model setup
- ✅ PT/TF wrappers - receive as parameter and pass to setup methods
- ✅ Model components (PTModel, TFModel) - receive in constructor

### `initial_params`
- ✅ `FedAvgRecipe` - stores for validation
- ✅ `JoblibModelParamPersistor` - receives in constructor, uses in load_model()
- ✅ Sklearn wrapper - passes directly to persistor

### `model_persistor`
- ✅ PT/TF wrappers - receive as parameter and pass to model setup methods
- ✅ Model components (PTModel, TFModel) - receive in constructor

## The Pattern

All these follow the same pattern:
1. **Recipes** (FedAvgRecipe, etc.) store and use them as their own instance variables
2. **Wrappers** receive them as constructor parameters
3. **Wrappers** pass them directly to child methods or components
4. **BaseFedJob** receives them but NEVER reads them

**Conclusion:** BaseFedJob was acting as a "storage pass-through" but nothing was reading from storage!

## Benefits of Cleanup

✅ **Clearer code** - Only store what you actually use
✅ **Less memory** - Don't store redundant copies
✅ **Better understanding** - Makes data flow explicit
✅ **Easier maintenance** - No confusion about "where is this stored?"

## After Cleanup

### BaseFedJob Now Only Stores:
```python
class BaseFedJob(FedJob):
    def __init__(self, ...):
        super().__init__(...)

        self.comp_ids = {}                      # ✅ Used: tracking component IDs
        self.convert_to_fed_event = ...         # ✅ Used: in set_up_client()

        # Everything else is just parameters received and passed to methods
        # No unnecessary storage!
```

### Data Flow Now Clear:
```
Recipe (FedAvgRecipe)
  ↓ stores: framework, initial_model, etc.
  ↓ creates: BaseFedJob(framework=..., initial_model=...)
  ↓
BaseFedJob
  ↓ receives parameters
  ↓ passes to: ValidationJsonGenerator, IntimeModelSelector, etc.
  ↓ does NOT store them (not needed!)
```

---

**All changes verified with linting - no errors!** ✅
