# Cross-Site Evaluation API: Before & After Examples

**Purpose**: Concrete code examples showing the impact of proposed simplifications

---

## Example 1: NumPy Cross-Site Evaluation (Training + CSE)

### ❌ Current API (Complex)

```python
# File: job.py
from nvflare.app_common.np.recipes import NumpyFedAvgRecipe
from nvflare.recipe.utils import add_cross_site_evaluation
from nvflare.app_common.np.np_validator import NPValidator
from nvflare.app_common.app_constant import AppConstants
from nvflare.recipe import SimEnv

# User needs to understand 5+ imports just for CSE

# Create recipe for training
recipe = NumpyFedAvgRecipe(
    num_clients=2,
    num_rounds=5,
    train_task_name="train"
)

# Add validator MANUALLY (easy to forget!)
recipe.job.to_clients(
    NPValidator(validate_task_name=AppConstants.TASK_VALIDATION),
    tasks=[AppConstants.TASK_VALIDATION]
)

# Add CSE with confusing parameters
add_cross_site_evaluation(
    recipe=recipe,
    model_locator_type="numpy",  # Redundant with recipe type
    model_locator_config={       # Why nested dict?
        "model_dir": "server_models",
        "model_name": {"server": "server.npy"}  # Why dict for one model?
    },
    persistor_id=None  # What is this? Do I need it?
)

SimEnv(recipe).execute()
```

**Problems**:
- 5 imports needed just for CSE
- Must manually add validator (runtime failure if forgotten)
- `model_locator_config` is nested dict with unclear structure
- `model_name` dict is confusing for single model
- `model_locator_type` is redundant (recipe already knows it's NumPy)
- `persistor_id` is mysterious

---

### ✅ Proposed API (Simple)

```python
# File: job.py
from nvflare.app_common.np.recipes import NumpyFedAvgRecipe
from nvflare.recipe import SimEnv

# Only 2 imports needed!

# Create recipe for training
recipe = NumpyFedAvgRecipe(
    num_clients=2,
    num_rounds=5,
    train_task_name="train"
)

# Add CSE - that's it!
recipe.add_cross_site_evaluation(
    model_dir="server_models"  # Simple!
)

SimEnv(recipe).execute()
```

**Improvements**:
- 60% fewer imports (5 → 2)
- No manual validator addition (auto-added)
- Single clear parameter (`model_dir`)
- Framework auto-detected from recipe type
- No mysterious IDs or nested dicts

**Lines of Code**: 20 → 11 (45% reduction)

---

## Example 2: Standalone CSE (Pre-trained Models Only)

### ❌ Current API (Two Different Approaches!)

**Approach A: Using Recipe**
```python
from nvflare.app_common.np.recipes import NumpyCrossSiteEvalRecipe
from nvflare.recipe import SimEnv

recipe = NumpyCrossSiteEvalRecipe(
    model_dir="server_models",
    model_name={"server": "server.npy"}  # Still confusing dict
)

SimEnv(recipe).execute()
```

**Approach B: Using utility function**
```python
from nvflare.job_config.api import FedJob
from nvflare.recipe.utils import add_cross_site_evaluation
from nvflare.recipe.spec import Recipe
from nvflare.recipe import SimEnv

job = FedJob(name="my_cse", min_clients=2)
recipe = Recipe(job)

add_cross_site_evaluation(
    recipe=recipe,
    model_locator_type="numpy",
    model_locator_config={
        "model_dir": "server_models",
        "model_name": {"server": "server.npy"}
    }
)

SimEnv(recipe).execute()
```

**Problems**:
- Two different ways to do the same thing (confusion!)
- Approach A: Recipe name is long and not discoverable
- Approach B: Exposes FedJob (low-level API)
- Both still use confusing `model_name` dict

---

### ✅ Proposed API (Unified & Simple)

```python
from nvflare.recipe import CrossSiteEvalRecipe, SimEnv

# One obvious way to do CSE
recipe = CrossSiteEvalRecipe(
    framework="numpy",  # Or auto-detect from model file extension
    model_dir="server_models"
)

SimEnv(recipe).execute()
```

**OR even simpler with auto-detection:**

```python
from nvflare.recipe import CrossSiteEvalRecipe, SimEnv

# Framework auto-detected from .npy file extension
recipe = CrossSiteEvalRecipe(model_dir="server_models")

SimEnv(recipe).execute()
```

**Improvements**:
- Single obvious approach (Zen of Python: "one way to do it")
- Short, clear recipe name
- Framework auto-detected or explicitly specified
- No low-level FedJob exposure
- No confusing dicts

---

## Example 3: PyTorch CSE with Training

### ❌ Current API

```python
from nvflare.app_opt.pt.recipes.fedavg import FedAvgRecipe
from nvflare.recipe.utils import add_cross_site_evaluation
from nvflare.app_common.widgets.validation_json_generator import ValidationJsonGenerator
from nvflare.recipe import SimEnv

# User needs to know about ValidationJsonGenerator? Why?

recipe = FedAvgRecipe(
    num_clients=2,
    num_rounds=5,
    train_task_name="train",
    evaluate_task_name="evaluate"
)

# Do I need to add validator manually? (Actually no, but unclear)

add_cross_site_evaluation(
    recipe=recipe,
    model_locator_type="pytorch",  # Again, redundant!
    # Need to figure out persistor_id from recipe internals
    persistor_id=recipe.job.comp_ids.get("persistor_id", ""),
    # Model locator config for PyTorch is DIFFERENT from NumPy
    model_locator_config={
        "model_dir": "models",
        "model_name": "best_model.pt"  # Wait, string not dict now?
    }
)

SimEnv(recipe).execute()
```

**Problems**:
- Inconsistent `model_name` type (dict for NumPy, string for PyTorch?)
- Must access `recipe.job.comp_ids` (internal API!)
- Unclear if validator needed
- ValidationJsonGenerator import needed? (Actually added automatically, but not obvious)

---

### ✅ Proposed API

```python
from nvflare.app_opt.pt.recipes.fedavg import FedAvgRecipe
from nvflare.recipe import SimEnv

recipe = FedAvgRecipe(
    num_clients=2,
    num_rounds=5,
    train_task_name="train",
    evaluate_task_name="evaluate"
)

# Just add CSE - everything else automatic!
recipe.add_cross_site_evaluation(
    model_dir="models"
)

SimEnv(recipe).execute()
```

**Improvements**:
- Consistent API across frameworks
- No internal API access needed
- Everything configured automatically
- Clear and obvious

---

## Example 4: Advanced Use Case - Multiple Models

### ❌ Current API

```python
from nvflare.app_common.np.recipes import NumpyFedAvgRecipe
from nvflare.recipe.utils import add_cross_site_evaluation
from nvflare.app_common.np.np_validator import NPValidator
from nvflare.app_common.app_constant import AppConstants

recipe = NumpyFedAvgRecipe(num_clients=2, num_rounds=5)

recipe.job.to_clients(
    NPValidator(validate_task_name=AppConstants.TASK_VALIDATION),
    tasks=[AppConstants.TASK_VALIDATION]
)

# How do I evaluate multiple models?
# Need to read documentation...
add_cross_site_evaluation(
    recipe=recipe,
    model_locator_type="numpy",
    model_locator_config={
        "model_dir": "server_models",
        "model_name": {  # Ah, this is how!
            "baseline": "baseline_model.npy",
            "optimized": "optimized_model.npy",
            "best": "best_accuracy_model.npy"
        }
    }
)
```

---

### ✅ Proposed API

```python
from nvflare.app_common.np.recipes import NumpyFedAvgRecipe

recipe = NumpyFedAvgRecipe(num_clients=2, num_rounds=5)

# Clear distinction: multiple models use 'models' parameter
recipe.add_cross_site_evaluation(
    model_dir="server_models",
    models={
        "baseline": "baseline_model.npy",
        "optimized": "optimized_model.npy",
        "best": "best_accuracy_model.npy"
    }
)
```

**OR automatic pattern matching:**

```python
# Evaluate ALL .npy files in directory
recipe.add_cross_site_evaluation(
    model_dir="server_models",
    model_pattern="*.npy"  # Evaluate all models
)
```

**Improvements**:
- Clear parameter names (`models` for multiple, `model_file` for single)
- Pattern matching option for "evaluate everything"
- Consistent with command-line glob patterns
- No manual validator setup

---

## Example 5: Custom Storage (Advanced)

### ❌ Current API (Forces persistor abstraction on everyone)

```python
from nvflare.app_common.np.recipes import NumpyFedAvgRecipe
from nvflare.app_common.np.np_model_persistor import NPModelPersistor
from nvflare.recipe.utils import add_cross_site_evaluation
from nvflare.app_common.np.np_validator import NPValidator
from nvflare.app_common.app_constant import AppConstants

# Even for simple file loading, must understand persistor!
recipe = NumpyFedAvgRecipe(num_clients=2, num_rounds=5)

# Must manually add persistor to recipe
persistor_id = recipe.job.to_server(NPModelPersistor(model_dir="models"))

recipe.job.to_clients(
    NPValidator(validate_task_name=AppConstants.TASK_VALIDATION),
    tasks=[AppConstants.TASK_VALIDATION]
)

add_cross_site_evaluation(
    recipe=recipe,
    model_locator_type="numpy",
    persistor_id=persistor_id,  # Connect the dots manually
    model_locator_config={"model_name": {"server": "server.npy"}}
)
```

---

### ✅ Proposed API (Simple default, advanced option available)

**90% Case - Simple file loading:**
```python
from nvflare.app_common.np.recipes import NumpyFedAvgRecipe

recipe = NumpyFedAvgRecipe(num_clients=2, num_rounds=5)

# File loading handled automatically, no persistor concept needed
recipe.add_cross_site_evaluation(model_dir="models")
```

**10% Case - Custom storage (S3, database, etc.):**
```python
from nvflare.app_common.np.recipes import NumpyFedAvgRecipe
from my_company.storage import S3ModelLoader

recipe = NumpyFedAvgRecipe(num_clients=2, num_rounds=5)

# Advanced users can provide custom loader
recipe.add_cross_site_evaluation(
    model_loader=S3ModelLoader(
        bucket="my-models",
        region="us-west-2"
    )
)
```

**Improvements**:
- 90% case requires zero understanding of storage abstractions
- 10% case uses simple `ModelLoader` interface (not complex persistor)
- Clear separation: `model_dir` for files, `model_loader` for custom
- Can't accidentally misconfigure (type safety)

---

## Example 6: Error Handling

### ❌ Current API (Cryptic errors)

```python
# User forgets to add validator
recipe = NumpyFedAvgRecipe(num_clients=2, num_rounds=5)

add_cross_site_evaluation(
    recipe=recipe,
    model_locator_type="numpy",
    model_locator_config={"model_dir": "models"}
)

# Runtime error (after job starts):
# "No handler for task 'validate'"
# User has no idea what went wrong!
```

---

### ✅ Proposed API (Clear errors)

```python
recipe = NumpyFedAvgRecipe(num_clients=2, num_rounds=5)

# Auto-adds validator, no error!
recipe.add_cross_site_evaluation(model_dir="models")

# If model_dir doesn't exist:
# ValueError: model_dir 'models' not found. 
# Did you mean 'server_models'? (auto-suggest similar names)

# If no models in directory:
# ValueError: No .npy files found in 'models'.
# Ensure your models are saved with .npy extension.
```

**Improvements**:
- Errors at API call time, not runtime
- Helpful error messages with suggestions
- Auto-configuration prevents common errors

---

## Summary: Cognitive Load Reduction

| Aspect | Current API | Proposed API | Improvement |
|--------|-------------|--------------|-------------|
| **Imports for basic CSE** | 5-6 | 2 | 60-70% reduction |
| **Parameters to understand** | 7+ (model_locator_type, model_locator_config, persistor_id, model_name dict, validator, task names) | 1 (model_dir) | 85% reduction |
| **Lines of code** | 20-30 | 8-12 | 50-60% reduction |
| **Concepts to learn** | 8-10 (locator, persistor, validator, config dict, task names, component IDs) | 1-2 (model directory, optionally framework) | 80-90% reduction |
| **Time to working example** | 15-20 minutes | 2-5 minutes | 70-80% reduction |
| **Common errors** | 5+ (missing validator, wrong config structure, wrong persistor_id, wrong task name, wrong model_name format) | 0-1 (wrong path) | 90%+ reduction |

---

## User Journey Comparison

### ❌ Current Experience

1. User reads CSE documentation
2. Learns about CrossSiteModelEval controller
3. Learns about model locators (what are they?)
4. Learns about model persistors (why?)
5. Learns about model_locator_config structure
6. Learns about model_name dict format
7. Learns about ValidationJsonGenerator
8. Learns about NPValidator (or PTValidator)
9. Learns about task names and constants
10. Tries example, gets "No handler for task" error
11. Debugs, realizes forgot validator
12. Adds validator, finally works
13. **Total time: 30-60 minutes**

---

### ✅ Proposed Experience

1. User reads CSE documentation
2. Sees: `recipe.add_cross_site_evaluation(model_dir="path")`
3. Tries it, works immediately
4. **Total time: 2-5 minutes**

---

## Backward Compatibility Strategy

### Option: Wrapper Approach (No Breaking Changes)

```python
# In nvflare/recipe/utils.py

def add_cross_site_evaluation(
    recipe,
    model_dir: Optional[str] = None,
    model_file: Optional[str] = None,
    models: Optional[dict] = None,
    # Legacy parameters (deprecated)
    model_locator_type: Optional[str] = None,
    model_locator_config: Optional[dict] = None,
    persistor_id: Optional[str] = None,
    **kwargs
):
    """Add cross-site evaluation to a recipe.
    
    Simple usage (recommended):
        recipe.add_cross_site_evaluation(model_dir="models")
    
    Legacy usage (deprecated):
        add_cross_site_evaluation(
            recipe, 
            model_locator_type="numpy",
            model_locator_config={...}
        )
    """
    
    # Detect API style
    if model_locator_type is not None or model_locator_config is not None:
        warnings.warn(
            "model_locator_type and model_locator_config are deprecated. "
            "Use model_dir='path' instead.",
            DeprecationWarning
        )
        # Use legacy path
        return _add_cross_site_evaluation_legacy(...)
    
    # Use new simplified path
    return _add_cross_site_evaluation_simple(recipe, model_dir, model_file, models, **kwargs)
```

This allows:
- Existing code continues working (with deprecation warning)
- New code uses simple API
- Smooth migration path
- Can remove legacy path in next major version

---

## Next Steps

1. **Get feedback on these examples**: Do they resonate? Are there missing use cases?
2. **Prototype the simplified API**: Implement in feature branch
3. **User testing**: Have 2-3 external users try both APIs, measure time and frustration
4. **Iterate based on feedback**: Refine before committing to API
5. **Document migration path**: Clear guide for existing users

The goal: **Make simple things simple, complex things possible**.
