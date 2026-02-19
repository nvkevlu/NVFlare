# Cross-Site Evaluation Branch Comparison Analysis

**Date:** December 30, 2024
**Branches Analyzed:**
- Branch A: `localholgerroth_fedavg_crosssiteeval` (Holger Roth's implementation)
- Branch B: `hello_cross_site_eval_recipe` (AI Assistant's implementation)

---

## Executive Summary

Both branches implement cross-site evaluation (CSE) functionality for NVFlare, but they take fundamentally different architectural approaches:

- **Branch A (Holger's)**: Adds CSE as an **optional feature** to existing recipes via parameter flags and utility functions. Focuses on PyTorch with NumPy support added later.
- **Branch B (AI's)**: Creates **dedicated CSE recipes** as separate, composable components. Focuses on NumPy with comprehensive standalone and combined workflows.

**Recommendation:** Branch A is more appropriate to continue from, but should incorporate specific improvements from Branch B (detailed in Section 6).

---

## 1. Commit History & Timeline

### Branch A: `localholgerroth_fedavg_crosssiteeval`
```
* d6a9e97a - Merge branch 'main' into fedavg_crosssiteeval
* 6e05c390 - enable numpy model locator
* c2cb9ad9 - formatting
* ae04c0c5 - move to utils
* adf56d4d - Merge branch 'fedavg_crosssiteeval' of github.com:holgerroth/NVFlare
* 201bd00f - formatting
* 5147d221 - Merge branch 'main' into fedavg_crosssiteeval
* aa9e21e7 - add cross site eval to fed avg recipe
```

**Key commits:**
- `aa9e21e7`: Initial implementation - adds `cross_site_eval` boolean parameter to `FedAvgRecipe`
- `ae04c0c5`: Refactors CSE logic into `add_cross_site_evaluation()` utility function
- `6e05c390`: Extends support to NumPy models via `MODEL_LOCATOR_REGISTRY`

### Branch B: `hello_cross_site_eval_recipe`
```
* df2af099 - add missing new file
* c32389c0 - update and address PR comments
* ce982143 - update and fix PR comments
* 8a36c752 - Merge branch 'main' into hello_cross_site_eval_recipe
* 2d17ba05 - Merge branch 'main' into hello_cross_site_eval_recipe
* 900e83ee - address PR comments
* 24bca6f1 - add recipe for hello cross site eval
```

**Key commits:**
- `24bca6f1`: Creates `NumpyCrossSiteEvalRecipe` and `FedAvgWithCrossSiteEvalRecipe`
- `900e83ee`, `ce982143`, `c32389c0`: Iterative improvements based on PR feedback
- `df2af099`: Adds missing `fedavg_with_cse.py` file

---

## 2. Architectural Approach

### Branch A: Utility Function Pattern (Composition)

**Philosophy:** CSE is a **cross-cutting concern** that can be added to any recipe.

**Implementation:**
1. **Core utility function** in `nvflare/recipe/utils.py`:
   ```python
   def add_cross_site_evaluation(
       recipe: Recipe,
       model_locator_type: str = "pytorch",
       persistor_id: str = None,
       submit_model_timeout: int = 600,
       validation_timeout: int = 6000,
   ):
       """Enable cross-site model evaluation."""
       # Creates CrossSiteModelEval controller
       # Adds to recipe.job.to_server()
   ```

2. **Optional parameter** in `FedAvgRecipe`:
   ```python
   class FedAvgRecipe(Recipe):
       def __init__(self, ..., cross_site_eval: bool = False):
           # Setup FedAvg workflow
           if self.cross_site_eval:
               # Inline CSE setup (older approach)
   ```

3. **Model locator registry** for framework extensibility:
   ```python
   MODEL_LOCATOR_REGISTRY = {
       "pytorch": {
           "locator_module": "nvflare.app_opt.pt.file_model_locator",
           "locator_class": "PTFileModelLocator",
           "persistor_param": "pt_persistor_id",
       },
       "numpy": {
           "locator_module": "nvflare.app_common.np.np_model_locator",
           "locator_class": "NPModelLocator",
           "persistor_param": None,
       },
   }
   ```

**Usage pattern:**
```python
# Option 1: Built into recipe
recipe = FedAvgRecipe(..., cross_site_eval=True)

# Option 2: Add via utility (newer, recommended)
recipe = FedAvgRecipe(...)
add_cross_site_evaluation(recipe, model_locator_type="pytorch")
```

**Files modified:**
- `nvflare/app_opt/pt/recipes/fedavg.py` (added `cross_site_eval` parameter)
- `nvflare/recipe/utils.py` (added `add_cross_site_evaluation()` function)
- `examples/hello-world/hello-pt/job.py` (added CLI flag `--cross_site_eval`)
- `examples/hello-world/hello-pt/README.md` (updated documentation)

---

### Branch B: Dedicated Recipe Pattern (Inheritance)

**Philosophy:** CSE workflows are **first-class recipes** deserving their own implementations.

**Implementation:**
1. **Standalone CSE recipe** (`NumpyCrossSiteEvalRecipe`):
   ```python
   class NumpyCrossSiteEvalRecipe(Recipe):
       """Cross-site evaluation only, no training."""
       def __init__(
           self,
           name: str,
           min_clients: int,
           model_locator_config: dict,
           client_model_dir: str,
           ...
       ):
           # Creates FedJob with CrossSiteModelEval workflow
           # No ScatterAndGather controller
   ```

2. **Combined training+CSE recipe** (`FedAvgWithCrossSiteEvalRecipe`):
   ```python
   class FedAvgWithCrossSiteEvalRecipe(Recipe):
       """FedAvg training followed by cross-site evaluation."""
       def __init__(
           self,
           name: str,
           min_clients: int,
           num_rounds: int,
           train_script: str,
           ...
       ):
           # Creates FedJob with:
           # 1. ScatterAndGather (training)
           # 2. CrossSiteModelEval (evaluation)
   ```

3. **Mode-based job script**:
   ```python
   # job.py supports two modes
   if args.mode == "pretrained":
       recipe = NumpyCrossSiteEvalRecipe(...)
   elif args.mode == "training":
       recipe = FedAvgWithCrossSiteEvalRecipe(...)
   ```

**Usage pattern:**
```python
# Standalone CSE (pre-trained models)
recipe = NumpyCrossSiteEvalRecipe(
    name="hello-numpy-cse",
    min_clients=2,
    model_locator_config={...},
    client_model_dir="/path/to/models",
)

# Training + CSE
recipe = FedAvgWithCrossSiteEvalRecipe(
    name="hello-numpy-train-cse",
    min_clients=2,
    num_rounds=2,
    train_script="client.py",
)
```

**Files created/modified:**
- `nvflare/app_common/np/recipes/cross_site_eval.py` (new file)
- `nvflare/app_common/np/recipes/fedavg_with_cse.py` (new file)
- `nvflare/app_common/np/recipes/__init__.py` (added exports)
- `examples/hello-world/hello-numpy-cross-val/job.py` (replaces `job_cse.py` and `job_train_and_cse.py`)
- `examples/hello-world/hello-numpy-cross-val/client.py` (new training script)
- `examples/hello-world/hello-numpy-cross-val/README.md` (comprehensive rewrite)

---

## 3. Detailed Feature Comparison

| Feature | Branch A (Holger's) | Branch B (AI's) |
|---------|---------------------|-----------------|
| **Primary Focus** | PyTorch workflows | NumPy workflows |
| **CSE Integration** | Optional parameter + utility function | Dedicated recipes |
| **Extensibility** | High - works with any recipe via `add_cross_site_evaluation()` | Medium - requires new recipe classes per framework |
| **Code Reusability** | Excellent - single utility for all frameworks | Moderate - code duplication across recipes |
| **Discoverability** | Lower - CSE is "hidden" as optional flag | Higher - explicit recipe names in documentation |
| **Example Complexity** | Simple - single flag or function call | Medium - mode-based script with two recipes |
| **Standalone CSE** | ❌ Not demonstrated | ✅ `NumpyCrossSiteEvalRecipe` |
| **Training + CSE** | ✅ Via `cross_site_eval=True` | ✅ `FedAvgWithCrossSiteEvalRecipe` |
| **NumPy Support** | ✅ Via `model_locator_type="numpy"` | ✅ Native, comprehensive |
| **PyTorch Support** | ✅ Native, comprehensive | ❌ Not implemented |
| **Model Locator Registry** | ✅ Extensible registry pattern | ❌ Hardcoded per recipe |
| **Legacy Consolidation** | ❌ Doesn't address `job_cse.py`/`job_train_and_cse.py` | ✅ Replaces legacy files with unified `job.py` |
| **Documentation Quality** | Moderate - brief README updates | Excellent - detailed README with examples |
| **API Consistency** | High - follows existing pattern (`add_experiment_tracking`) | Medium - new pattern for CSE |
| **Testing** | Unknown (not visible in commits) | ✅ Integration tests in `test_experiment_tracking_recipes.py` |

---

## 4. Similarities

Both approaches:
1. **Use the same underlying components:**
   - `CrossSiteModelEval` controller workflow
   - `NPModelLocator` / `PTFileModelLocator` for model discovery
   - `ValidationJsonGenerator` for result output
   - `NPValidator` / PyTorch validators for client-side evaluation

2. **Support the same workflow:**
   - Training followed by cross-site evaluation
   - All-to-all model evaluation matrix

3. **Maintain Recipe API consistency:**
   - Both return `Recipe` objects
   - Both work with `SimEnv`, `PocEnv`, `ProdEnv`

4. **Follow NVFlare patterns:**
   - Use `job.to_server()` and `job.to_clients()`
   - Leverage existing aggregators and persistors

---

## 5. Differences

### 5.1 API Design Philosophy

**Branch A: Composition over inheritance**
- CSE is a **capability** that can be added to any recipe
- Similar to `add_experiment_tracking()` pattern
- Promotes code reuse and consistency

**Branch B: Explicit recipes**
- CSE workflows are **distinct operations** with unique parameters
- More intuitive for users who want CSE-specific functionality
- Better documentation and examples

### 5.2 Framework Support

**Branch A:**
- Started with PyTorch, added NumPy support via registry
- Registry pattern makes it easy to add TensorFlow, JAX, etc.
- No NumPy-specific examples yet

**Branch B:**
- NumPy-first design with comprehensive examples
- `hello-numpy-cross-val` example is well-documented
- No PyTorch support

### 5.3 Code Location

**Branch A:**
- CSE logic in `nvflare/recipe/utils.py` (cross-cutting utilities)
- Parameter in `nvflare/app_opt/pt/recipes/fedavg.py`
- Centralized approach

**Branch B:**
- CSE recipes in `nvflare/app_common/np/recipes/`
- Separate files: `cross_site_eval.py`, `fedavg_with_cse.py`
- Decentralized, framework-specific approach

### 5.4 User Experience

**Branch A Example:**
```python
# Simple and concise
recipe = FedAvgRecipe(
    name="hello-pt",
    min_clients=2,
    num_rounds=2,
    initial_model=SimpleNetwork(),
    train_script="client.py",
)
add_cross_site_evaluation(recipe, model_locator_type="pytorch")
env = SimEnv(num_clients=2)
run = recipe.execute(env)
```

**Branch B Example:**
```python
# More explicit about the workflow
recipe = FedAvgWithCrossSiteEvalRecipe(
    name="hello-numpy-train-cse",
    min_clients=2,
    num_rounds=2,
    train_script="client.py",
)
env = SimEnv(num_clients=2)
run = recipe.execute(env)
```

### 5.5 Legacy Code Handling

**Branch A:**
- Does not address existing `job_cse.py` and `job_train_and_cse.py` files
- These legacy FedJob API files remain in the codebase

**Branch B:**
- Consolidates `job_cse.py` and `job_train_and_cse.py` into single `job.py`
- Deletes legacy files
- Provides migration path to Recipe API

---

## 6. Which Approach is Better?

### Winner: **Branch A (Holger's)** with improvements from Branch B

**Reasons:**

1. **Better API Design:**
   - The utility function pattern (`add_cross_site_evaluation()`) is more flexible and extensible
   - Consistent with existing `add_experiment_tracking()` pattern
   - Works with ANY recipe, not just FedAvg

2. **More Maintainable:**
   - Single source of truth for CSE logic in `utils.py`
   - Registry pattern makes adding new frameworks trivial
   - Reduces code duplication

3. **Framework Agnostic:**
   - Already supports PyTorch and NumPy
   - Easy to extend to TensorFlow, JAX, etc.
   - Branch B would require creating new recipes for each framework

4. **Cleaner User Experience:**
   - One-line addition: `add_cross_site_evaluation(recipe)`
   - No need to learn new recipe classes
   - Less cognitive overhead

5. **Better Alignment with NVFlare Philosophy:**
   - Recipes should be composable
   - Cross-cutting concerns should be utilities
   - Similar to how experiment tracking is implemented

**However, Branch A needs improvements from Branch B:**

### Critical Missing Pieces from Branch B to Integrate:

1. **Standalone CSE Recipe/Example:**
   - Branch A doesn't demonstrate standalone CSE (evaluation of pre-trained models)
   - Need a NumPy example showing CSE without training
   - Could be implemented as:
     ```python
     # Option 1: Use add_cross_site_evaluation() with empty recipe
     job = FedJob(name="cse-only", min_clients=2)
     # Add model locator, validators, etc.
     recipe = Recipe(job)
     add_cross_site_evaluation(recipe, model_locator_type="numpy")

     # Option 2: Add a flag to skip training in existing recipes
     recipe = NumpyFedAvgRecipe(..., num_rounds=0)  # Skip training
     add_cross_site_evaluation(recipe)
     ```

2. **NumPy Example Documentation:**
   - Branch B's `hello-numpy-cross-val/README.md` is excellent
   - Explains use cases, modes, and expected output clearly
   - Should be adapted for Branch A's approach

3. **Legacy File Consolidation:**
   - `job_cse.py` and `job_train_and_cse.py` should be replaced
   - Create unified `job.py` that uses `add_cross_site_evaluation()`
   - Keep the mode-based approach but with utility function

4. **Integration Tests:**
   - Branch B created tests in `test_experiment_tracking_recipes.py`
   - Need similar tests for CSE functionality

5. **Client Script for Training:**
   - Branch B created `client.py` for NumPy training
   - Needed for training+CSE mode

6. **Pre-trained Model Generator:**
   - Branch B's `generate_pretrain_models.py` is useful
   - Should be retained for standalone CSE examples

---

## 7. Recommended Integration Plan

### Phase 1: Immediate Fixes (Branch A is base)

1. **Keep all of Branch A's code:**
   - ✅ `nvflare/recipe/utils.py` with `add_cross_site_evaluation()`
   - ✅ `MODEL_LOCATOR_REGISTRY` for extensibility
   - ✅ `examples/hello-world/hello-pt/job.py` with CSE example

2. **Add from Branch B:**
   - ✅ `examples/hello-world/hello-numpy-cross-val/client.py` (training script)
   - ✅ `examples/hello-world/hello-numpy-cross-val/generate_pretrain_models.py`

3. **Create new unified `job.py`** for NumPy example:
   ```python
   # examples/hello-world/hello-numpy-cross-val/job.py
   import argparse
   from nvflare.app_common.np.recipes import NumpyFedAvgRecipe
   from nvflare.recipe import SimEnv
   from nvflare.recipe.utils import add_cross_site_evaluation

   def define_parser():
       parser = argparse.ArgumentParser()
       parser.add_argument("--n_clients", type=int, default=2)
       parser.add_argument("--mode", type=str, default="pretrained",
                         choices=["pretrained", "training"])
       parser.add_argument("--num_rounds", type=int, default=1)
       return parser.parse_args()

   def run_pretrained_cse(n_clients: int):
       """Standalone CSE with pre-trained models."""
       # Create minimal job for CSE only
       from nvflare import FedJob
       from nvflare.app_common.np.np_model_locator import NPModelLocator
       from nvflare.app_common.np.np_validator import NPValidator
       from nvflare.app_common.widgets.validation_json_generator import ValidationJsonGenerator
       from nvflare.app_common.workflows.cross_site_model_eval import CrossSiteModelEval
       from nvflare.recipe.spec import Recipe

       job = FedJob(name="hello-numpy-cse", min_clients=n_clients)

       # Setup CSE components
       model_locator_id = job.to_server(NPModelLocator(
           model_dir="/tmp/nvflare/server_pretrain_models",
           model_name={"server_model_1": "server_1.npy", "server_model_2": "server_2.npy"},
       ))
       job.to_server(ValidationJsonGenerator())
       job.to_server(CrossSiteModelEval(model_locator_id=model_locator_id))

       # Add validators to clients
       validator = NPValidator(validate_task_name="validate")
       job.to_clients(validator, tasks=["validate"])

       recipe = Recipe(job)
       env = SimEnv(num_clients=n_clients)
       run = recipe.execute(env)
       print(f"Results: {run.get_result()}")

   def run_training_and_cse(n_clients: int, num_rounds: int):
       """FedAvg training + CSE."""
       recipe = NumpyFedAvgRecipe(
           name="hello-numpy-train-cse",
           min_clients=n_clients,
           num_rounds=num_rounds,
           train_script="client.py",
       )
       add_cross_site_evaluation(recipe, model_locator_type="numpy")

       env = SimEnv(num_clients=n_clients)
       run = recipe.execute(env)
       print(f"Results: {run.get_result()}")

   def main():
       args = define_parser()
       if args.mode == "pretrained":
           run_pretrained_cse(args.n_clients)
       elif args.mode == "training":
           run_training_and_cse(args.n_clients, args.num_rounds)

   if __name__ == "__main__":
       main()
   ```

4. **Update README** using Branch B's structure but emphasizing utility function:
   - Explain both modes (standalone CSE, training+CSE)
   - Show how `add_cross_site_evaluation()` works
   - Include expected output

5. **Delete legacy files:**
   - `examples/hello-world/hello-numpy-cross-val/job_cse.py`
   - `examples/hello-world/hello-numpy-cross-val/job_train_and_cse.py`

### Phase 2: Documentation & Testing

1. **Add integration tests:**
   - Test standalone CSE mode with pre-trained models
   - Test training+CSE mode
   - Both NumPy and PyTorch

2. **Update documentation:**
   - Add CSE section to Recipe API docs
   - Document `add_cross_site_evaluation()` utility
   - Add examples to tutorials

3. **Create migration guide:**
   - How to convert FedJob CSE to Recipe API
   - Example showing before/after

### Phase 3: Optional Enhancements

1. **Consider adding standalone CSE recipe:**
   - If users frequently need CSE-only workflows
   - Could be `CrossSiteEvalRecipe(model_locator_config, ...)`
   - But keep `add_cross_site_evaluation()` as primary API

2. **Add more framework support:**
   - TensorFlow model locator in registry
   - JAX model locator
   - scikit-learn model locator

3. **Enhanced validation options:**
   - Custom validation metrics
   - Validation script runners (not just validators)

---

## 8. Files to Keep, Merge, or Delete

### From Branch A (Keep All)
✅ **Keep:**
- `nvflare/app_opt/pt/recipes/fedavg.py` (with `cross_site_eval` parameter)
- `nvflare/recipe/utils.py` (with `add_cross_site_evaluation()` and registry)
- `examples/hello-world/hello-pt/job.py` (CSE example)
- `examples/hello-world/hello-pt/README.md` (updated docs)

### From Branch B (Selective)
✅ **Keep (adapt for Branch A approach):**
- `examples/hello-world/hello-numpy-cross-val/client.py` (training script)
- `examples/hello-world/hello-numpy-cross-val/generate_pretrain_models.py` (useful utility)
- Documentation structure from Branch B's README
- Test concepts from `test_experiment_tracking_recipes.py`

❌ **Do NOT keep:**
- `nvflare/app_common/np/recipes/cross_site_eval.py` (redundant with utility function)
- `nvflare/app_common/np/recipes/fedavg_with_cse.py` (redundant with utility function)
- Branch B's `job.py` exactly as-is (needs refactoring to use utility)

### Existing Files (Clean Up)
🗑️ **Delete:**
- `examples/hello-world/hello-numpy-cross-val/job_cse.py` (legacy FedJob API)
- `examples/hello-world/hello-numpy-cross-val/job_train_and_cse.py` (legacy FedJob API)

📝 **Create/Replace:**
- `examples/hello-world/hello-numpy-cross-val/job.py` (new unified script using utility)
- `examples/hello-world/hello-numpy-cross-val/README.md` (rewrite to explain utility approach)

---

## 9. Technical Considerations

### 9.1 Validation JsonGenerator

**Branch A:** Uses `ValidationJsonGenerator` inline in utility function - ❌ **Issue**
```python
# Missing in current implementation
def add_cross_site_evaluation(...):
    # ... model locator setup ...
    eval_controller = CrossSiteModelEval(...)
    recipe.job.to_server(eval_controller)
    # Missing: ValidationJsonGenerator
```

**Branch B:** Explicitly includes `ValidationJsonGenerator` - ✅ **Correct**
```python
job.to_server(ValidationJsonGenerator())
```

**Fix needed:** Add to utility function:
```python
def add_cross_site_evaluation(...):
    from nvflare.app_common.widgets.validation_json_generator import ValidationJsonGenerator
    # ... existing code ...
    recipe.job.to_server(ValidationJsonGenerator())
    recipe.job.to_server(eval_controller)
```

### 9.2 Client-Side Components

**Branch A:** Assumes client-side validators already exist - ❌ **Incomplete**
- Only adds server-side components
- Doesn't configure client executors for validation task

**Branch B:** Explicitly adds validators to clients - ✅ **Complete**
```python
validator = NPValidator(validate_task_name=AppConstants.TASK_VALIDATION)
job.to_clients(validator, tasks=[AppConstants.TASK_VALIDATION])
```

**Fix needed:** Document requirement in utility function docstring:
```python
def add_cross_site_evaluation(...):
    """Enable cross-site model evaluation.

    Note: Client-side validators must be configured separately.
    For NumPy: add NPValidator
    For PyTorch: validation handled by ScriptRunner with validation logic in script
    """
```

### 9.3 Model Locator Configuration

**Branch A:** Simple configuration via `model_locator_type` - ✅ **Good**
```python
add_cross_site_evaluation(recipe, model_locator_type="pytorch")
```

**Branch B:** Detailed configuration dict - ✅ **More flexible**
```python
model_locator_config={
    "model_dir": "/path/to/models",
    "model_name": {"model1": "file1.npy", "model2": "file2.npy"},
}
```

**Improvement:** Add optional `model_locator_config` parameter to utility:
```python
def add_cross_site_evaluation(
    recipe: Recipe,
    model_locator_type: str = "pytorch",
    model_locator_config: dict = None,  # NEW
    persistor_id: str = None,
    ...
):
    # ... existing code ...
    if model_locator_config:
        locator_kwargs.update(model_locator_config)
```

---

## 10. Summary & Action Items

### Key Takeaways

1. **Branch A has the right architecture** - utility function pattern is more flexible and maintainable
2. **Branch B has better examples and documentation** - especially for NumPy workflows
3. **Both are incomplete on their own** - need elements from each

### Immediate Action Items

1. ✅ Use Branch A as the base
2. ✅ Add `ValidationJsonGenerator` to `add_cross_site_evaluation()`
3. ✅ Port NumPy example files from Branch B (`client.py`, `generate_pretrain_models.py`)
4. ✅ Create unified `job.py` using utility function approach
5. ✅ Update README with comprehensive documentation
6. ✅ Delete legacy `job_cse.py` and `job_train_and_cse.py`
7. ✅ Add integration tests
8. ❌ Do NOT port the dedicated recipe classes (`NumpyCrossSiteEvalRecipe`, `FedAvgWithCrossSiteEvalRecipe`)

### Long-term Considerations

- Monitor if users request dedicated CSE recipes (may indicate utility function isn't discoverable enough)
- Consider adding convenience parameters to existing recipes (like Branch A's `cross_site_eval=True`)
- Ensure documentation clearly shows both patterns:
  1. Parameter in recipe: `FedAvgRecipe(..., cross_site_eval=True)`
  2. Utility function: `add_cross_site_evaluation(recipe)`

---

## Appendix: Code Snippets

### A. Current State of add_cross_site_evaluation() (Branch A)

```python
def add_cross_site_evaluation(
    recipe: Recipe,
    model_locator_type: str = "pytorch",
    persistor_id: str = None,
    submit_model_timeout: int = 600,
    validation_timeout: int = 6000,
):
    """Enable cross-site model evaluation.

    Args:
        recipe: Recipe object to add cross-site evaluation to
        model_locator_type: The type of model locator to use ("pytorch" or "numpy")
        persistor_id: The persistor ID to use for model location. If None, uses the default persistor_id from job.comp_ids
        submit_model_timeout: Timeout for model submission in seconds
        validation_timeout: Timeout for validation in seconds
    """
    from nvflare.app_common.workflows.cross_site_model_eval import CrossSiteModelEval

    if model_locator_type not in MODEL_LOCATOR_REGISTRY:
        raise ValueError(
            f"Invalid model locator type: {model_locator_type}. Available types: {list(MODEL_LOCATOR_REGISTRY.keys())}"
        )

    # Use provided persistor_id or default from job.comp_ids
    if persistor_id is None:
        persistor_id = recipe.job.comp_ids["persistor_id"]

    # Get model locator configuration from registry
    locator_config = MODEL_LOCATOR_REGISTRY[model_locator_type]

    # Import and create model locator
    module = importlib.import_module(locator_config["locator_module"])
    locator_class = getattr(module, locator_config["locator_class"])

    # Create model locator with appropriate parameters
    if locator_config["persistor_param"] is not None:
        # For PyTorch locator, use persistor_id
        locator_kwargs = {locator_config["persistor_param"]: persistor_id}
        model_locator = locator_class(**locator_kwargs)
    else:
        # For Numpy locator, use default parameters (no persistor_id needed)
        model_locator = locator_class()

    model_locator_id = recipe.job.to_server(model_locator)

    # Create and add cross-site evaluation controller
    eval_controller = CrossSiteModelEval(
        model_locator_id=model_locator_id,
        submit_model_timeout=submit_model_timeout,
        validation_timeout=validation_timeout,
    )
    recipe.job.to_server(eval_controller)
```

### B. Recommended Improvements

```python
def add_cross_site_evaluation(
    recipe: Recipe,
    model_locator_type: str = "pytorch",
    model_locator_config: dict = None,  # NEW
    persistor_id: str = None,
    submit_model_timeout: int = 600,
    validation_timeout: int = 6000,
):
    """Enable cross-site model evaluation.

    Args:
        recipe: Recipe object to add cross-site evaluation to
        model_locator_type: The type of model locator to use ("pytorch" or "numpy")
        model_locator_config: Optional config dict to pass to model locator (e.g., model_dir, model_name)
        persistor_id: The persistor ID to use for model location. If None, uses the default persistor_id from job.comp_ids
        submit_model_timeout: Timeout for model submission in seconds
        validation_timeout: Timeout for validation in seconds

    Note:
        Client-side validators must be configured separately:
        - For NumPy: Add NPValidator to handle validation tasks
        - For PyTorch: Validation logic should be in the training script
    """
    from nvflare.app_common.widgets.validation_json_generator import ValidationJsonGenerator
    from nvflare.app_common.workflows.cross_site_model_eval import CrossSiteModelEval

    if model_locator_type not in MODEL_LOCATOR_REGISTRY:
        raise ValueError(
            f"Invalid model locator type: {model_locator_type}. Available types: {list(MODEL_LOCATOR_REGISTRY.keys())}"
        )

    # Use provided persistor_id or default from job.comp_ids
    if persistor_id is None:
        persistor_id = recipe.job.comp_ids.get("persistor_id", "")

    # Get model locator configuration from registry
    locator_config = MODEL_LOCATOR_REGISTRY[model_locator_type]

    # Import and create model locator
    module = importlib.import_module(locator_config["locator_module"])
    locator_class = getattr(module, locator_config["locator_class"])

    # Create model locator with appropriate parameters
    locator_kwargs = {}
    if locator_config["persistor_param"] is not None:
        locator_kwargs[locator_config["persistor_param"]] = persistor_id

    # Merge in custom config if provided
    if model_locator_config:
        locator_kwargs.update(model_locator_config)

    model_locator = locator_class(**locator_kwargs)
    model_locator_id = recipe.job.to_server(model_locator)

    # Add validation JSON generator (NEW - was missing)
    recipe.job.to_server(ValidationJsonGenerator())

    # Create and add cross-site evaluation controller
    eval_controller = CrossSiteModelEval(
        model_locator_id=model_locator_id,
        submit_model_timeout=submit_model_timeout,
        validation_timeout=validation_timeout,
    )
    recipe.job.to_server(eval_controller)
```

---

**End of Report**
