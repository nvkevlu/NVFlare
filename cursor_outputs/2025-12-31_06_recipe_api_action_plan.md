# Documentation Update Action Plan for Recipe API Migration

## Current Status

✅ **Completed (But Partially Incorrect)**:
- Simple path replacements from `hello-numpy-sag` → `hello-numpy` in 42 locations
- Removed `/jobs/hello-numpy-sag` path segments
- Updated test directories and configuration files

❌ **Issues Created**:
- Many examples now show workflows that won't work
- Missing information about Recipe export requirements
- Obsolete references to non-existent config files
- Confusion between Recipe API vs traditional job approaches

## Prioritized Fix Plan

### 🔴 CRITICAL - Fix Breaking User Workflows (Do First)

These files contain instructions that will **actively break** for users trying to follow them:

#### 1. `examples/tutorials/flare_api.ipynb`
**Current Problem**:
```python
# Cell 7: Copies Recipe directory
! cp -r  ../hello-world/hello-numpy /tmp/nvflare/poc/.../transfer/.

# Cell 10: Tries to submit Recipe directory directly
path_to_example_job = "hello-numpy"
job_id = sess.submit_job(path_to_example_job)  # ❌ WILL FAIL
```

**Fix Required**:
```python
# Option A: Use Recipe execute with PocEnv (RECOMMENDED)
import sys
sys.path.append("../hello-world/hello-numpy")
from job import create_recipe  # Or inline recipe creation

recipe = create_recipe()  # Create the Recipe
from nvflare.recipe import PocEnv
env = PocEnv(num_clients=2)
run = recipe.execute(env)
job_id = run.job_id
print(f"{job_id} was submitted")

# Option B: Export then submit
recipe.export("/tmp/nvflare/exported_job")
job_id = sess.submit_job("/tmp/nvflare/exported_job/hello-numpy")
```

**Additional Changes**:
- Add explanation cell about Recipe API
- Add note about export requirement
- Show both execute() and export() approaches

---

#### 2. `examples/tutorials/flare_simulator.ipynb`
**Current Problem**:
```bash
# Cell 4: Tries to simulate Recipe directory directly
!nvflare simulator -w hello-numpy-workspace -n 2 -t 2 -gpu 0 ../hello-world/hello-numpy
# ❌ WILL FAIL - expects traditional job structure
```

**Fix Required**:
```bash
# Option A: Use Recipe's built-in execution (RECOMMENDED)
!cd ../hello-world/hello-numpy && python job.py

# Option B: Export first, then simulate
# In Python cell:
import sys
sys.path.append("../hello-world/hello-numpy")
from job import create_recipe
recipe = create_recipe()
recipe.export("/tmp/hello-numpy-job")

# Then in shell:
!nvflare simulator -w hello-numpy-workspace -n 2 -t 2 /tmp/hello-numpy-job/hello-numpy
```

**Additional Changes**:
- Add introduction about Recipe API examples
- Explain simulator requirements
- Show recommended `python job.py` approach

---

#### 3. `examples/tutorials/logging.ipynb`
**Current Problem**:
```bash
# Cells with simulator commands
!nvflare simulator -w hello-numpy-workspace -n 2 -t 2 -l full ../hello-world/hello-numpy
```

**Fix Required**:
Same as flare_simulator.ipynb - either use `python job.py` approach or export first

---

#### 4. `docs/user_guide/nvflare_cli/poc_command.rst`
**Current Problem**:
```bash
# Lines 383, 400, 411 show:
submit_job hello-world/hello-numpy
job_id = sess.submit_job("hello-world/hello-numpy")
nvflare job submit -j NVFlare/examples/hello-world/hello-numpy
# ❌ WILL FAIL
```

**Fix Required**:
```rst
.. note::
   The hello-numpy example uses the Recipe API. You have two options:

   **Option 1: Use Recipe with PocEnv (Recommended)**

   .. code-block:: python

       from hello_numpy.job import create_recipe  # Or define inline
       from nvflare.recipe import PocEnv

       recipe = create_recipe()
       env = PocEnv(num_clients=2)
       run = recipe.execute(env)

   **Option 2: Export Recipe, then submit**

   .. code-block:: python

       recipe.export("/tmp/exported_job")
       job_id = sess.submit_job("/tmp/exported_job/hello-numpy")
```

---

### 🟡 HIGH PRIORITY - Fix Misleading Documentation

#### 5. `docs/examples/hello_scatter_and_gather.rst`
**Current Problem**:
- References config files that don't exist (config_fed_server.json, config_fed_client.json)
- Shows traditional job workflow
- Replaced literalinclude with generic note

**Fix Required**:
- **Complete rewrite** for Recipe API approach
- Show actual hello-numpy structure
- Explain Recipe parameters replace JSON configs
- Link to Recipe API documentation
- Keep as "conceptual" guide rather than step-by-step

**Suggested Structure**:
```rst
Hello Federated Learning with NumPy
===================================

This tutorial demonstrates federated learning concepts using the hello-numpy
example, which uses NVIDIA FLARE's Recipe API.

.. note::
   This example uses the **Recipe API**, which provides a simplified way to
   define federated learning jobs programmatically, without needing JSON
   configuration files.

Understanding the Recipe API Approach
--------------------------------------

Instead of traditional job configurations with JSON files, the Recipe API
allows you to define jobs in Python:

.. code-block:: python

   from nvflare.app_common.np.recipes.fedavg import NumpyFedAvgRecipe

   recipe = NumpyFedAvgRecipe(
       name="hello-numpy",
       min_clients=2,
       num_rounds=3,
       initial_model=[[1, 2, 3], [4, 5, 6], [7, 8, 9]],
       train_script="client.py",
   )

[Continue with FedAvg concepts, workflow explanation, etc.]

Running the Example
-------------------

The hello-numpy example includes a job.py file that creates and executes the recipe:

.. code-block:: bash

   cd examples/hello-world/hello-numpy
   python job.py

[Explain what happens, how to view results, etc.]
```

---

#### 6. `docs/user_guide/nvflare_cli/fl_simulator.rst`
**Current Problem**:
- Examples show simulating Recipe directories directly

**Fix Required**:
- Add section explaining simulator requirements
- Clarify: works with traditional job folders OR exported Recipe jobs
- Show Recipe example with export step
- Recommend `python job.py` for Recipe-based examples

---

### 🟢 MEDIUM PRIORITY - Improve Clarity

#### 7. Create New Documentation: `docs/user_guide/recipe_vs_traditional.rst`

**Content Outline**:
```rst
Recipe API vs Traditional Jobs
===============================

When to Use Each Approach
-------------------------

Recipe API (Recommended for Getting Started)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
✅ You're new to NVIDIA FLARE
✅ Using standard algorithms (FedAvg, Cyclic, etc.)
✅ Want to focus on ML, not FL infrastructure
✅ Rapid prototyping

Traditional Job API (For Advanced Use Cases)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
✅ Need fine-grained control
✅ Custom workflows/controllers
✅ Complex multi-app deployments
✅ Existing job configurations to maintain

Comparison Table
----------------

| Aspect | Recipe API | Traditional Job |
|--------|-----------|----------------|
| Configuration | Python code | JSON files |
| Learning Curve | Low | Medium-High |
| Flexibility | High-level params | Full control |
| Job Structure | job.py, client.py | jobs/app/config/ |
| Submission | execute(env) or export | Direct folder submit |

Working with Recipe API Jobs
-----------------------------

Running Locally (Simulation)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
[Show python job.py approach]

Running in POC
^^^^^^^^^^^^^^
[Show execute(PocEnv) approach]

Running in Production
^^^^^^^^^^^^^^^^^^^^^
[Show execute(ProdEnv) approach]

Exporting Recipe to Traditional Format
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
[Show export() method]
[When/why you'd want to do this]

Converting Traditional to Recipe
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
[Brief guide with examples]
```

---

#### 8. Update `docs/user_guide/data_scientist_guide/job_recipe.rst`

**Add Section**:
```rst
Common Pitfalls and Solutions
------------------------------

"Why can't I submit my Recipe directory?"
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Recipe directories are not traditional job folders. Use one of these approaches:

1. Use execute() with appropriate environment (recommended)
2. Export to traditional format first, then submit

"nvflare simulator fails on my Recipe directory"
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The simulator command expects traditional job structure. Options:

1. Run: python job.py (if using SimEnv internally)
2. Export first: recipe.export(), then simulate exported folder
3. Use recipe.execute(SimEnv) directly

[More common issues...]
```

---

### 🔵 LOW PRIORITY - Polish & Consistency

#### 9. Add Badges/Labels to Examples
- Label examples as "Recipe API" or "Traditional Job"
- Update README files with clear indicators
- Create consistent naming convention

#### 10. Update Integration Tests
- Verify tests work with renamed directories
- Add Recipe-specific test patterns
- Ensure tests actually validate what docs claim

#### 11. Create Troubleshooting Guide
- Common errors with Recipe API
- Debugging export issues
- Environment-specific problems

---

## Implementation Sequence

### Week 1: Critical Fixes
1. Fix flare_api.ipynb
2. Fix flare_simulator.ipynb
3. Fix logging.ipynb
4. Fix poc_command.rst
5. Add warning boxes to recently updated docs

### Week 2: High Priority Documentation
6. Rewrite hello_scatter_and_gather.rst
7. Create recipe_vs_traditional.rst
8. Update fl_simulator.rst with clarifications
9. Add pitfalls section to job_recipe.rst

### Week 3: Polish & Validation
10. Add example labels/badges
11. Test all documented workflows
12. Update integration tests
13. Create troubleshooting guide
14. Final review and consistency check

---

## Testing Checklist

For each updated tutorial/doc, verify:

- [ ] Commands actually work when executed
- [ ] Paths exist and are correct
- [ ] Output matches expectations
- [ ] Error messages (if any) are explained
- [ ] Alternative approaches are shown when applicable
- [ ] Links to related documentation work

---

## Documentation Standards Going Forward

### For Recipe API Examples:
```rst
.. admonition:: Recipe API Example
   :class: note

   This example uses the Recipe API. Run with: `python job.py`

   To submit to POC/Production, use `recipe.execute(PocEnv/ProdEnv)`
   or export first with `recipe.export()`.
```

### For Traditional Job Examples:
```rst
.. admonition:: Traditional Job Structure
   :class: note

   This example uses traditional job structure with JSON configurations.
   Submit directly with: `nvflare job submit -j path/to/job`
```

---

## Key Messages for Documentation

1. **Recipe API is the recommended approach** for new users
2. **Different submission methods** required for Recipe vs Traditional
3. **Export is available** when traditional format is needed
4. **Both approaches are valid** - use what fits your needs
5. **hello-numpy is a Recipe API example** - not a traditional job

---

## Success Metrics

- ✅ Users can follow tutorials without errors
- ✅ Clear distinction between Recipe and Traditional approaches
- ✅ All examples are labeled appropriately
- ✅ Troubleshooting guide addresses common issues
- ✅ Migration guide helps users understand differences

---

## Notes for Reviewers

- The current updates are a good first step but incomplete
- Recipe API is newer, better, simpler - but requires different workflows
- Documentation must be explicit about requirements
- Users coming from older versions may be confused
- We need both approaches documented until traditional is deprecated (if ever)
