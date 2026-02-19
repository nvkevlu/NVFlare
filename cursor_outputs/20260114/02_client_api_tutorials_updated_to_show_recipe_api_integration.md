# Client API Tutorial Updates - January 14, 2026

## Summary

Updated the Client API tutorial documentation to reflect the modern Recipe API approach for defining and running federated learning jobs. The updates show how Client API (for training scripts) works together with Job Recipe API (for job definitions).

## Files Updated

### 1. `/docs/user_guide/data_scientist_guide/client_api_usage.rst`
**User Guide version - for data scientists**

**Changes:**
- ✅ Replaced reference to `job_cli` with `job_recipe`
- ✅ Added new section: "Combining Client API with Job Recipe"
- ✅ Added complete working example showing `job.py` + `client.py` pattern
- ✅ Added "Framework-Specific Examples" section with PyTorch example
- ✅ Updated "Additional Resources" section with modern references
- ✅ Added links to hello-world examples (hello-pt, hello-numpy, hello-lightning, hello-tf)

**Key Additions:**
```rst
Combining Client API with Job Recipe
=====================================

The Client API handles the **client-side training code** (what each client does with the model),
while the Job Recipe handles the **job definition** (how the FL workflow is configured and executed).
```

Complete example showing:
- File structure (job.py, client.py, requirements.txt)
- client.py using Client API (flare.init(), receive(), send())
- job.py using Recipe API (NumpyFedAvgRecipe, SimEnv)
- How to run: `python job.py`

### 2. `/docs/programming_guide/execution_api_type/client_api.rst`
**Programming Guide version - for developers**

**Changes:**
- ✅ Added comprehensive section: "Understanding the Client API and Job Recipe Relationship"
- ✅ Added "Complete Working Example" with 3-step tutorial
- ✅ Added "Key Benefits of This Approach" section
- ✅ Added "When to Use Client API" guidance section
- ✅ Updated "Examples" section with categorized links (Hello World, Advanced, Step-by-Step)
- ✅ Added "Additional Resources" with organized links to API docs and guides
- ✅ Enhanced cross-references to related documentation

**Key Additions:**

1. **Clear separation of concerns:**
   - Client API → training script (client.py)
   - Job Recipe API → job definition (job.py)

2. **Complete PyTorch example** showing:
   - Step 1: Training script with Client API
   - Step 2: Job definition with Recipe API
   - Step 3: Running the job with different environments

3. **Environment flexibility:**
   ```python
   # Simulation
   env = SimEnv(num_clients=2)
   
   # POC
   env = PocEnv(num_clients=2)
   
   # Production
   env = ProdEnv(startup_kit_location="/path/to/admin/startup")
   ```

4. **When to Use guidance:**
   - Recommended for most users
   - When to consider alternatives (ModelLearner, Executor, 3rd-Party Integration)

## What's Covered

### Recipe Conversions Referenced
Based on the recipe conversion work documented in `cursor_outputs/recipe_conversions/`:

1. **Hello World Examples** (100% converted)
   - hello-numpy, hello-pt, hello-lightning, hello-tf, hello-flower
   - All use Recipe API with Client API

2. **Experiment Tracking** (100% converted)
   - Shows `add_experiment_tracking()` utility
   - TensorBoard, MLflow, Weights & Biases examples

3. **XGBoost Examples** (100% converted - Jan 13, 2026)
   - XGBHistogramRecipe, XGBVerticalRecipe
   - Shows advanced Recipe usage

4. **Sklearn Examples** (100% converted)
   - SklearnFedAvgRecipe, KMeansFedAvgRecipe, SVMFedAvgRecipe
   - Shows custom recipe patterns

### Key Concepts Explained

1. **Client API Purpose:**
   - Minimal code changes to convert centralized → federated
   - Used in training scripts (client.py)
   - Core methods: init(), receive(), send()

2. **Job Recipe Purpose:**
   - Define FL workflow and parameters
   - Used in job definitions (job.py)
   - Supports multiple environments (SimEnv, PocEnv, ProdEnv)

3. **How They Work Together:**
   - Client API: "What each client does with the model"
   - Job Recipe: "How the FL workflow is configured"
   - Separation of concerns enables flexibility

4. **Benefits:**
   - Minimal code changes (5 lines for Client API)
   - Environment flexibility (same code, different envs)
   - Easy experimentation (change params without changing training code)
   - Built-in features (tracking, cross-site eval, etc.)

## Examples Added

### User Guide Examples:
1. **Basic NumPy Example** - Shows simplest case
2. **PyTorch Example** - Shows framework-specific usage

### Programming Guide Examples:
1. **Complete PyTorch Example** - Full tutorial with 3 steps
2. **Environment Switching** - How to use different environments
3. **Command-line Arguments** - How to parameterize jobs

## Cross-References Verified

All cross-references are valid and working:

✅ `:ref:`job_recipe`` → `docs/user_guide/data_scientist_guide/job_recipe.rst`
✅ `:ref:`client_api`` → `docs/programming_guide/execution_api_type/client_api.rst`
✅ `:ref:`client_api_usage`` → `docs/user_guide/data_scientist_guide/client_api_usage.rst`
✅ `:ref:`execution_api_type`` → `docs/programming_guide/execution_api_type.rst`
✅ `:ref:`fl_simulator`` → `docs/user_guide/nvflare_cli/fl_simulator.rst`
✅ `:ref:`hello_pt`` → `docs/hello-world/hello-pt/index.rst`
✅ `:ref:`hello_lightning`` → `docs/hello-world/hello-lightning/index.rst`
✅ `:ref:`hello_tf`` → `docs/hello-world/hello-tf/index.rst`

## Links to Examples

### GitHub Links (using `:github_nvflare_link:` directive):
- `hello-pt <examples/hello-world/hello-pt>`
- `hello-numpy <examples/hello-world/hello-numpy>`
- `hello-lightning <examples/hello-world/hello-lightning>`
- `hello-tf <examples/hello-world/hello-tf>`
- `hello-flower <examples/hello-world/hello-flower>`
- `llm_hf <examples/llm_hf>`
- `xgboost examples <examples/advanced/xgboost>`
- `sklearn examples <examples/advanced/sklearn-*>`
- `step-by-step series <examples/hello-world/step-by-step>`

## Migration Path

The updated documentation now shows the modern path:

**Old Way (deprecated):**
```
Client API → Job Templates → Job CLI → Simulator
```

**New Way (recommended):**
```
Client API → Job Recipe → SimEnv/PocEnv/ProdEnv
```

## Impact

### For New Users:
- Clear path from centralized code to federated learning
- Complete working examples to copy and modify
- Understand how Client API and Recipe API work together

### For Existing Users:
- See how to migrate from job_cli to Recipe API
- Understand the benefits of the new approach
- Find examples for their specific framework

### For Documentation:
- Consistent with recipe conversion work (79% of examples converted)
- Aligned with modern FLARE 2.7+ approach
- Clear separation between user guide and programming guide

## Related Work

This update is based on:

1. **Recipe Conversions** (cursor_outputs/recipe_conversions/)
   - 31/39 examples converted to Recipe API (79%)
   - XGBoost, Sklearn, Hello World all 100% complete
   - Comprehensive status tracking and documentation

2. **Recent Fixes** (cursor_outputs/20260114/)
   - NumpyFedAvgRecipe experiment tracking fix
   - XGBoost secure split updates
   - Inventory corrections

3. **Job Recipe Tutorial** (docs/user_guide/data_scientist_guide/job_recipe.rst)
   - Existing comprehensive guide
   - Referenced from Client API docs

## Testing

No code changes were made - only documentation updates.

**Verification:**
- ✅ All cross-references validated
- ✅ All :ref: links point to existing targets
- ✅ All :github_nvflare_link: directives use correct paths
- ✅ RST syntax validated (no linter errors)

## Next Steps

The Client API tutorial is now fully updated. Users can:

1. Read the tutorial to understand Client API + Recipe API
2. Follow complete working examples
3. Explore framework-specific examples (PyTorch, NumPy, TensorFlow, etc.)
4. Learn when to use Client API vs alternatives
5. Find links to all relevant examples and documentation

## Files Changed

```
docs/user_guide/data_scientist_guide/client_api_usage.rst
docs/programming_guide/execution_api_type/client_api.rst
```

**Lines Added:**
- User Guide: ~140 new lines
- Programming Guide: ~180 new lines

**Total Impact:** ~320 lines of new documentation showing modern Recipe API approach

---

**Created:** January 14, 2026
**Status:** ✅ Complete
**Linter Errors:** None
**Cross-References:** All verified
