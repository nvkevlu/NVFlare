# Recipe API Migration - Final Guide
**Date**: December 31, 2025
**Status**: Path changes complete, workflow documentation needs updates

---

## TL;DR - What You Need to Know

✅ **Path changes** from `hello-numpy-sag` → `hello-numpy` are **CORRECT**
⚠️ **Workflow examples** need updates because Recipe API works differently
✨ **Your intuition was RIGHT**: For simulation, just use `python job.py`!

---

## Background: What Happened

### The Original Task
You asked me to fix an invalid path in tutorials: `hello-numpy-sag` didn't exist anymore, it should be `hello-numpy`.

### What I Did (Simple Find-Replace)
I updated 42+ files, replacing:
- `hello-world/hello-numpy-sag/jobs/hello-numpy-sag` → `hello-world/hello-numpy`
- Various references to the old path structure
- Test directories and configuration files

### What I Missed (The Architecture Change!)
The path change wasn't just a rename - it represented a **fundamental shift** in how NVFlare jobs work:

**`hello-numpy-sag`** = Traditional job with JSON configs
**`hello-numpy`** = New Recipe API with Python configs

These have **different workflows** - you can't just change the path and expect the same commands to work!

### The Problem I Created
My simple find-replace left examples showing workflows like:
```bash
nvflare simulator ... hello-numpy  # ❌ Won't work
sess.submit_job("hello-numpy")      # ❌ Won't work
```

These commands expect traditional job structure (meta.json, app/config/), but Recipe API directories don't have that.

### Your Insight
You correctly questioned: "Can't we just use `python job.py`?"

**YES!** That's exactly right for simulation. I was overcomplicating it. The fix is much simpler than I initially thought.

---

## What's a Recipe API?

**Recipe API** = High-level Python API that replaces JSON configuration files

**Before (Traditional)**:
```
hello-numpy-sag/jobs/hello-numpy-sag/
├── meta.json                    # Job metadata
└── app/
    └── config/
        ├── config_fed_server.json  # Server config
        └── config_fed_client.json  # Client config
```

**Now (Recipe API)**:
```
hello-numpy/
├── job.py          # Creates recipe and runs it
├── client.py       # Training script
└── requirements.txt
```

**Key Difference**: Configuration is now in Python code, not JSON files.

### Why This Matters for Documentation

**Traditional jobs**: Submit the job folder directly
- `sess.submit_job("path/to/job")` looks for meta.json
- `nvflare simulator job_path` expects app/config/

**Recipe API**: Need to execute or export first
- Recipe directories don't have meta.json or app/config/
- Can't submit directly - must use recipe.execute() OR export first
- For simulation, `python job.py` is simplest

This is why my simple path replacement broke workflows!

---

## The Impact: What Breaks

### For Users Following Tutorials:
If someone follows my updated tutorials as-is:

❌ **Simulator command fails**: `nvflare simulator ... hello-numpy`
- Error: "Cannot find meta.json" or similar
- User confused why documented command doesn't work

❌ **Job submission fails**: `sess.submit_job("hello-numpy")`
- Error: "Invalid job definition"
- User doesn't know Recipe needs export first

❌ **Wrong result paths**: Looking in `hello-numpy-workspace/`
- Files are actually in `/tmp/nvflare/simulation/hello-numpy/`
- User can't find their results

### The Fix

Simply update workflow examples to match Recipe API patterns. Not a massive rewrite - just 7 files!

---

## The Simple Fix: Simulation Examples

For **simulation/tutorial examples**, the fix is simple:

### ❌ OLD (Won't Work):
```bash
nvflare simulator -w workspace -n 2 ../hello-world/hello-numpy
```

### ✅ NEW (Works!):
```bash
cd ../hello-world/hello-numpy
python job.py --n_clients 2
```

**Why**: The `job.py` already has SimEnv inside it, so just run it directly!

---

## The Context Fix: POC/Production Submission

For **POC/Production**, you can't submit Recipe directories directly:

### ❌ WON'T WORK:
```python
sess.submit_job("hello-numpy")  # Recipe dir has no meta.json
```

### ✅ OPTION A - Export First (Traditional Feel):
```python
# 1. Export the recipe to traditional job format
cd hello-numpy
python job.py --export_config
# Creates: /tmp/nvflare/jobs/job_config/hello-numpy

# 2. Then submit normally
sess.submit_job("/tmp/nvflare/jobs/job_config/hello-numpy")
```

### ✅ OPTION B - Use Recipe Execute (Recommended):
```python
from hello_numpy.job import recipe  # or recreate it
from nvflare.recipe import PocEnv, ProdEnv

# For POC
env = PocEnv(num_clients=2)
run = recipe.execute(env)  # Handles export + submit automatically

# For Production
env = ProdEnv(
    startup_kit_location="/path/to/admin",
    username="admin@nvidia.com"
)
run = recipe.execute(env)
```

---

## Files That Need Updates (Only 7!)

### 🔴 CRITICAL - Tutorial Notebooks (Users Follow These):

#### 1. `examples/tutorials/flare_simulator.ipynb`
**Change Cell 4** from:
```bash
!nvflare simulator -w hello-numpy-workspace -n 2 ../hello-world/hello-numpy
```
**To**:
```bash
!cd ../hello-world/hello-numpy && python job.py --n_clients 2
```

**Add explanation**:
```markdown
> **Note**: hello-numpy uses Recipe API. The job.py file includes execution
> logic, so we run it directly rather than using the simulator command.
```

---

#### 2. `examples/tutorials/logging.ipynb`
**Change Cell 2 & 20** - Same as above (use `python job.py`)

**Update result paths** in Cells 4, 6, 9, 11, 13, 15, 18:
- FROM: `hello-numpy-workspace/`
- TO: `/tmp/nvflare/simulation/hello-numpy/`

---

#### 3. `examples/tutorials/flare_api.ipynb`
**Update Cell 6** - Add explanation:
```markdown
### 3. Prepare Example

The hello-numpy example uses Recipe API. To submit it, we first export
to traditional job format:
```

**Replace Cell 7** with:
```python
# Export hello-numpy Recipe to traditional job format
import os
export_cmd = """
cd ../hello-world/hello-numpy && python job.py --export_config
"""
os.system(export_cmd)

# Copy exported job to transfer directory
transfer_dir = "/tmp/nvflare/poc/example_project/prod_00/admin@nvidia.com/transfer/"
os.system(f"cp -r /tmp/nvflare/jobs/job_config/hello-numpy {transfer_dir}")
```

**Keep Cell 10** as-is (it's now correct):
```python
path_to_example_job = "hello-numpy"
job_id = sess.submit_job(path_to_example_job)
```

**Add new cell** after Cell 10:
```markdown
> **Alternative**: You can also use Recipe.execute(PocEnv) directly:
> ```python
> from nvflare.recipe import PocEnv
> env = PocEnv(num_clients=2)
> run = recipe.execute(env)
> ```
```

---

### 🟡 IMPORTANT - Reference Documentation:

#### 4. `docs/user_guide/nvflare_cli/fl_simulator.rst`
**Update lines 56-60**:
```rst
For Recipe API examples like hello-numpy, run the job.py directly:

.. code-block:: bash

    cd NVFlare/examples/hello-world/hello-numpy
    python job.py --n_clients 8

For traditional job structures, use the nvflare simulator command:

.. code-block:: bash

    nvflare simulator traditional-job-path -w workspace -n 8 -t 1
```

**Update lines 756, 771** similarly.

---

#### 5. `docs/user_guide/nvflare_cli/poc_command.rst`
**Replace lines 383-411**:
```rst
Submitting Recipe API Jobs
---------------------------

For Recipe API examples (like hello-numpy), you have two options:

**Option 1: Export then submit** (traditional workflow)

.. code-block:: bash

    cd hello-world/hello-numpy
    python job.py --export_config
    # Then submit: submit_job /tmp/nvflare/jobs/job_config/hello-numpy

**Option 2: Use Recipe execute** (recommended)

.. code-block:: python

    from nvflare.recipe import PocEnv
    env = PocEnv(num_clients=2)
    run = recipe.execute(env)

For traditional jobs, submit directly:

.. code-block:: bash

    submit_job path/to/traditional/job
```

---

### 🟢 POLISH - Documentation Improvements:

#### 6. `docs/examples/hello_scatter_and_gather.rst`
**Simplify to conceptual overview** (full rewrite):

```rst
Hello Federated Learning with NumPy
====================================

Introduction to federated learning concepts using hello-numpy.

Concept
-------
* Server distributes model to clients
* Clients train locally, send updates
* Server aggregates using FedAvg
* Process repeats for multiple rounds

Running
-------
.. code-block:: bash

    cd examples/hello-world/hello-numpy
    python job.py

Results saved to: ``/tmp/nvflare/simulation/hello-numpy/``

Code
----
See: :github_nvflare_link:`hello-numpy <examples/hello-world/hello-numpy>`

* ``job.py`` - Creates Recipe and executes
* ``client.py`` - Training logic
```

---

#### 7. `docs/user_guide/recipe_api_quick_ref.rst` (NEW FILE)
**Create quick reference**:

```rst
Recipe API Quick Reference
==========================

Running Locally (Simulation)
-----------------------------

.. code-block:: bash

    cd examples/hello-world/hello-numpy
    python job.py

Submitting to POC/Production
-----------------------------

**Method 1: Export first**

.. code-block:: bash

    python job.py --export_config
    nvflare job submit -j /tmp/nvflare/jobs/job_config/hello-numpy

**Method 2: Use execute() (Recommended)**

.. code-block:: python

    from nvflare.recipe import PocEnv, ProdEnv
    env = PocEnv(num_clients=2)  # or ProdEnv(...)
    run = recipe.execute(env)

When to Use What
----------------

* **Simulation**: Run ``python job.py``
* **POC/Prod**: Export OR execute()
* **Traditional jobs**: Submit directly
```

---

## Quick Decision Tree

```
Are you running hello-numpy?
│
├─ YES → Is it for simulation/testing?
│   │
│   ├─ YES → Just run: cd hello-numpy && python job.py ✅
│   │
│   └─ NO (POC/Prod) → Choose:
│       ├─ Export first, then submit ✅
│       └─ OR use recipe.execute(PocEnv/ProdEnv) ✅
│
└─ NO (other example) → Check if Recipe API or Traditional
    │
    ├─ Recipe API → Same as hello-numpy above
    └─ Traditional → Submit directly ✅
```

---

## What's Already Fixed (Keep These)

✅ All path changes from `hello-numpy-sag` → `hello-numpy`
✅ Test directory rename
✅ meta.json name field updates
✅ Setup script paths
✅ Most documentation path references

**These are all correct!** Just need the workflow updates above.

---

## Testing Checklist

After making updates, test:

- [ ] `cd hello-numpy && python job.py` works
- [ ] Tutorial notebooks run without errors
- [ ] Export approach works for POC submission
- [ ] Recipe.execute(PocEnv) works
- [ ] Documentation examples are copy-pasteable

---

## Summary & Next Steps

### What We Learned

**The Journey**:
1. Started with simple path fix: `hello-numpy-sag` → `hello-numpy` ✅
2. Realized it's not just a path - it's an architectural change ⚠️
3. Initially thought massive rewrite needed 😰
4. You questioned: "Can't we just use `python job.py`?" 💡
5. **YES!** That's the simple answer for most cases! 🎉

**The Fix is Simple**:
1. **Simulation examples** → Change to `python job.py`
2. **POC/Prod examples** → Show export OR execute approach
3. **Everything else** → Already correct from your path updates!

**Only 7 files need updates**, not the massive rewrite I initially suggested.

### Why This Document Exists

This consolidates my analysis after realizing:
- Simple find-replace isn't enough (different workflows)
- But also isn't as complicated as I first thought (your `python job.py` insight)
- Just need to update workflow examples, not rewrite everything

### Action Plan Priority

**Week 1** (Critical - breaks user workflows):
- Fix 3 tutorial notebooks (flare_simulator, logging, flare_api)
- Add Recipe API explanation notes

**Week 2** (Important - documentation accuracy):
- Update 2 CLI reference docs (fl_simulator.rst, poc_command.rst)
- Simplify hello_scatter_and_gather.rst
- Create recipe_api_quick_ref.rst

**Week 3** (Polish):
- Test all examples end-to-end
- Verify all paths and commands work
- Add troubleshooting section if needed

**Your intuition was right** - for most cases, the `python job.py` approach is the simple answer!

---

## Related Files (For Reference)

This document consolidates everything. Other documents in cursor_outputs/:

**Supporting Documents** (in reading order):
- `2025-12-31_02_recipe_api_SIMPLIFIED.md` - High-level overview
- `2025-12-31_03_recipe_api_QUICK_FIX.md` - Detailed code changes for each file

**Original Analysis** (for deep dive):
- `2025-12-31_04_recipe_api_summary.md` - Original executive summary
- `2025-12-31_05_recipe_api_analysis.md` - Technical deep dive into differences
- `2025-12-31_06_recipe_api_action_plan.md` - Comprehensive original plan

**This file** (`2025-12-31_01_recipe_api_FINAL_GUIDE.md`) is the consolidated guide with:
- Background on what happened and why
- Context on Recipe API vs Traditional
- Clear explanation of the problem and impact
- Concrete fixes for all 7 files
- Action plan with priorities
- Everything needed to understand and fix the issue
