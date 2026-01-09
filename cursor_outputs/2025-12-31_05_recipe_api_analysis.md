# Recipe API Migration Analysis & Documentation Update Plan

## Executive Summary

The migration from `hello-numpy-sag` to `hello-numpy` is NOT just a simple path change. It represents a **fundamental architectural shift** from traditional job configuration to the **Recipe API** approach. My initial find-and-replace updates are **incomplete and potentially misleading**.

## Critical Findings

### 1. **Architectural Differences**

#### Old Approach (`hello-numpy-sag`):
```
hello-numpy-sag/
└── jobs/
    └── hello-numpy-sag/
        ├── meta.json
        └── app/
            └── config/
                ├── config_fed_server.json
                ├── config_fed_client.json
```
- **Manual configuration** via JSON files
- **Traditional job structure** with deploy_map, controllers, executors
- **Submitted as a job folder** to POC/Production

#### New Approach (`hello-numpy`):
```
hello-numpy/
├── job.py           # Creates Recipe and executes
├── client.py        # Training script
├── requirements.txt
```
- **Programmatic configuration** via Python Recipe API
- **High-level abstraction** - no JSON configs needed
- **Can run directly** with `python job.py` OR export to traditional format

### 2. **Job Submission Methods - INCOMPATIBLE**

#### What I Updated (WRONG):
```python
# In docs, I changed:
sess.submit_job("hello-world/hello-numpy-sag/jobs/hello-numpy-sag")
# To:
sess.submit_job("hello-world/hello-numpy")
```

#### Why This is WRONG:
- `sess.submit_job()` expects a **traditional job folder** with `meta.json` and `app/` directories
- Recipe API directories CANNOT be directly submitted
- They must be **exported first** OR use the Recipe's `execute()` method

#### Correct Approaches:

**Option 1: Export Recipe, Then Submit**
```python
from nvflare.app_common.np.recipes.fedavg import NumpyFedAvgRecipe

recipe = NumpyFedAvgRecipe(
    name="hello-numpy",
    min_clients=2,
    num_rounds=3,
    initial_model=[[1, 2, 3], [4, 5, 6], [7, 8, 9]],
    train_script="client.py",
)
# Export to traditional job format
recipe.export("/tmp/nvflare/jobs/hello-numpy-job")
# NOW can submit
sess.submit_job("/tmp/nvflare/jobs/hello-numpy-job/hello-numpy")
```

**Option 2: Use Recipe's Execute Method (Recommended)**
```python
from nvflare.recipe import PocEnv, ProdEnv

# For POC
env = PocEnv(num_clients=2)
run = recipe.execute(env)  # Automatically handles export & submission

# For Production
env = ProdEnv(
    startup_kit_location="/path/to/admin/startup",
    username="admin@nvidia.com"
)
run = recipe.execute(env)
```

**Option 3: Run Directly (Simulation Only)**
```bash
# The hello-numpy example's job.py does this:
cd hello-numpy
python job.py  # Uses SimEnv internally
```

### 3. **Simulator Usage - BROKEN**

#### What I Updated (WRONG):
```bash
# I changed:
nvflare simulator -w workspace -n 2 ../hello-world/hello-numpy-sag/jobs/hello-numpy-sag
# To:
nvflare simulator -w workspace -n 2 ../hello-world/hello-numpy
```

#### Why This is WRONG:
- `nvflare simulator` command expects a **traditional job folder structure**
- It will fail on Recipe API directories that lack `meta.json` and `app/config/`

#### Correct Approaches:

**Option 1: Use Recipe's Built-in Execution**
```python
# Inside job.py (already done in hello-numpy):
from nvflare.recipe import SimEnv

env = SimEnv(num_clients=2)
run = recipe.execute(env)
```
```bash
# Then run:
python job.py
```

**Option 2: Export First, Then Simulate**
```python
recipe.export("/tmp/nvflare/jobs/hello-numpy-job")
```
```bash
nvflare simulator -w workspace -n 2 /tmp/nvflare/jobs/hello-numpy-job/hello-numpy
```

**Option 3: Use Job API's simulator_run()**
```python
# If using FedJob directly (not Recipe):
job.simulator_run(workspace="/tmp/workspace", n_clients=2)
```

### 4. **Configuration File References - OBSOLETE**

Many documents I updated reference configuration files that **NO LONGER EXIST** in Recipe API examples:

#### Obsolete References:
- `app/config/config_fed_server.json` ❌
- `app/config/config_fed_client.json` ❌
- `meta.json` (at job root) ❌
- `deploy_map` configurations ❌

#### What Exists Instead:
- **Programmatic configuration** in `job.py`
- **Recipe parameters** (min_clients, num_rounds, etc.)
- **Optional export** to traditional format

## Files Updated with INCORRECT Guidance

### High Priority (Active User Workflows):

1. **examples/tutorials/flare_api.ipynb**
   - ❌ Shows `submit_job("hello-numpy")` - won't work
   - ✅ Should: Show Recipe export + submit OR Recipe execute(PocEnv)

2. **examples/tutorials/flare_simulator.ipynb**
   - ❌ Shows `nvflare simulator ... hello-numpy` - won't work
   - ✅ Should: Show `python job.py` approach OR export first

3. **docs/user_guide/nvflare_cli/poc_command.rst**
   - ❌ Shows `submit_job hello-world/hello-numpy` - won't work
   - ✅ Should: Show Recipe approach OR export

4. **docs/examples/hello_scatter_and_gather.rst**
   - ❌ References config files that don't exist
   - ❌ Shows workflow that doesn't match Recipe API
   - ✅ Needs: Complete rewrite for Recipe API

### Medium Priority (Documentation/Reference):

5. **docs/programming_guide/migrating_to_flare_api.rst**
   - Updated paths but concepts still apply (job submission works for exported jobs)

6. **docs/user_guide/nvflare_cli/fl_simulator.rst**
   - Examples won't work with Recipe dirs

7. **docs/user_guide/core_concepts/job.rst**
   - Deploy map examples updated but don't reflect Recipe API

### Low Priority (Advanced/Legacy):

8. **examples/advanced/** scripts
   - Setup scripts copying Recipe dirs as job folders
   - May work if examples export first, needs verification

9. **tests/integration_test/**
   - Test renamed but may need Recipe export logic

## What Recipe API Makes Obsolete

### Concepts No Longer Needed for Basic Usage:
- ❌ Manual JSON configuration files
- ❌ Understanding Controllers vs Executors
- ❌ Workflow definitions
- ❌ Deploy map syntax
- ❌ Job folder structure details

### What Users Need to Know Instead:
- ✅ Recipe classes (FedAvgRecipe, etc.)
- ✅ Execution environments (SimEnv, PocEnv, ProdEnv)
- ✅ Recipe parameters (min_clients, num_rounds, train_script)
- ✅ When/how to export (if needed)

## Recommended Documentation Updates

### Phase 1: Fix Immediate Breakage (Critical)

1. **Update Tutorial Notebooks**
   - `flare_api.ipynb`: Change to show Recipe execute(PocEnv) pattern
   - `flare_simulator.ipynb`: Change to show `python job.py` approach
   - `logging.ipynb`: Update simulator commands

2. **Update CLI Documentation**
   - `poc_command.rst`: Show Recipe-based job submission
   - `fl_simulator.rst`: Clarify simulator works with exported jobs OR use Recipe

3. **Add Warning Boxes**
   ```rst
   .. warning::
      The hello-numpy example uses the Recipe API. To submit it to POC/Production,
      you must either use Recipe's execute() method with PocEnv/ProdEnv, or export
      it first using recipe.export().
   ```

### Phase 2: Comprehensive Recipe API Documentation

4. **Create Recipe API Migration Guide**
   - Side-by-side comparison: Traditional vs Recipe
   - When to use each approach
   - How to convert between them

5. **Update Hello World Example Docs**
   - `hello_scatter_and_gather.rst`: Complete rewrite for Recipe API
   - Add section: "Understanding Recipe API Structure"
   - Add section: "Running Recipe API Jobs"

6. **Update Programming Guide**
   - Clarify job submission methods
   - Document Recipe export() and execute() clearly
   - Show environment-specific patterns

### Phase 3: Consistency & Cleanup

7. **Audit All Examples**
   - Verify which use Recipe API vs Traditional
   - Ensure docs match actual structure
   - Add clear labels/badges

8. **Update Integration Tests**
   - Ensure tests use correct submission methods
   - Add Recipe API specific tests

9. **Create Troubleshooting Guide**
   - "Why does submit_job fail with Recipe directory?"
   - "When do I need to export?"
   - "Simulator vs Recipe execute() - which to use?"

## Key Questions to Resolve

1. **Can `nvflare job submit` command handle Recipe directories?**
   - Need to check if Job CLI has Recipe detection/auto-export
   - If not, docs should clarify

2. **Should hello-numpy-sag example be kept?**
   - As "traditional job" reference example?
   - Or fully deprecated in favor of Recipe API?

3. **What about step-by-step examples?**
   - Do they use Recipe API or traditional?
   - Need consistency

4. **Testing strategy?**
   - Test my updated paths actually work
   - Some may fail without export step

## Action Items Summary

### Immediate (Breaking User Workflows):
- [ ] Fix flare_api.ipynb job submission
- [ ] Fix flare_simulator.ipynb simulator usage
- [ ] Fix poc_command.rst submission examples
- [ ] Add warning boxes to updated docs

### Short-term (Documentation Accuracy):
- [ ] Rewrite hello_scatter_and_gather.rst
- [ ] Create Recipe API quick reference
- [ ] Update all simulator command examples
- [ ] Audit and fix configuration file references

### Long-term (Comprehensive):
- [ ] Create Recipe API migration guide
- [ ] Establish Recipe vs Traditional naming convention
- [ ] Add Recipe API troubleshooting guide
- [ ] Update all programming guide examples

## Conclusion

My initial "simple" path replacements have created **incorrect documentation** that will **break user workflows**. The Recipe API is a fundamentally different approach that requires:

1. **Different submission methods** - can't just change paths
2. **Different execution patterns** - direct execution vs export-then-submit
3. **Different mental model** - programmatic vs configuration-based

**Recommendation**: Before merging these changes, we need to:
1. Revert misleading updates (especially tutorials)
2. Create comprehensive Recipe API documentation
3. Update examples with correct patterns
4. Test that all documented workflows actually work

The Recipe API is powerful and simpler for users, but the documentation must accurately reflect this new paradigm, not just do find-and-replace on paths.
