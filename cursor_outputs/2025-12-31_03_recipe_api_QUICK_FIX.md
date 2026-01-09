# Quick Fix Guide - Recipe API Updates
Date: 2025-01-05

## The Simple Truth

**YES, you're right!** For hello-numpy simulation, we can just use `python job.py`. Here's what actually needs changing:

---

## 7 Files to Update (That's It!)

### 🔴 File 1: `examples/tutorials/flare_simulator.ipynb`

**Cell 3 - Change the markdown:**
```markdown
The two key arguments here are `-w WORKSPACE` and the `job_folder` argument.
For this example, we'll use the hello-numpy Recipe API example, which includes
its own execution logic.
```

**Cell 4 - Replace the shell commands:**
```bash
# OLD (what I updated to, won't work):
!mkdir -p hello-numpy-workspace
!nvflare simulator -w hello-numpy-workspace -n 2 -t 2 -gpu 0 ../hello-world/hello-numpy

# NEW (simple!):
!cd ../hello-world/hello-numpy && python job.py --n_clients 2
```

**Add new cell after Cell 4:**
```markdown
> **Note**: The hello-numpy example uses the Recipe API, which includes its own
> SimEnv execution environment. Running `python job.py` handles everything
> automatically. The older `nvflare simulator` command works with traditional
> job structures or exported Recipe jobs.
```

---

### 🔴 File 2: `examples/tutorials/logging.ipynb`

**Cell 2 - Replace shell commands:**
```bash
# OLD:
!mkdir -p hello-numpy-workspace
!nvflare simulator -w hello-numpy-workspace -n 2 -t 2 -l full ../hello-world/hello-numpy

# NEW:
!cd ../hello-world/hello-numpy && python job.py --n_clients 2
```

**Cell 4 - Update workspace path:**
```bash
# OLD:
!tree hello-numpy-workspace

# NEW:
!tree /tmp/nvflare/simulation/hello-numpy
```

**Cell 20 - Replace shell commands:**
```bash
# OLD:
!nvflare simulator -w hello-numpy-workspace -n 2 -t 2 -l custom_log_config.json ../hello-world/hello-numpy

# NEW:
# Copy log config to hello-numpy directory
!cp custom_log_config.json ../hello-world/hello-numpy/
!cd ../hello-world/hello-numpy && python job.py --n_clients 2
# Note: To use custom log config with Recipe, modify job.py to pass log_config to SimEnv
```

**Update all other cells (6, 9, 11, 13, 15, 18)** to use `/tmp/nvflare/simulation/hello-numpy` instead of workspace

---

### 🔴 File 3: `examples/tutorials/flare_api.ipynb`

**Keep Cells 1-5 as-is** (POC setup is fine)

**Cell 6 - Update markdown:**
```markdown
### 3. Prepare Example

For this tutorial, we'll use the hello-numpy example. Since it uses the Recipe API,
we have two options for submission:

**Option A**: Export the Recipe to traditional job format (shown below)
**Option B**: Use Recipe's execute() method with PocEnv (see Recipe API docs)

For this tutorial, we'll use Option A to demonstrate traditional job submission:
```

**Cell 7 - Replace with export approach:**
```python
# Export the hello-numpy Recipe to a job folder
import sys
sys.path.append("../hello-world/hello-numpy")
import os

# Run the export
export_cmd = """
cd ../hello-world/hello-numpy
python -c "
from job import define_parser
args = define_parser()
args.export_config = True
from job import main
main()
"
"""
os.system(export_cmd)

# Copy exported job to transfer directory
os.system("cp -r /tmp/nvflare/jobs/job_config/hello-numpy /tmp/nvflare/poc/example_project/prod_00/admin@nvidia.com/transfer/")
```

**Cell 10 - Update to:**
```python
path_to_example_job = "hello-numpy"  # Now points to exported job
job_id = sess.submit_job(path_to_example_job)
print(job_id + " was submitted")
```

**Add new cell after 10:**
```markdown
> **Alternative Method**: You can also use Recipe's execute() method directly:
> ```python
> from hello_numpy.job import recipe
> from nvflare.recipe import PocEnv
> env = PocEnv(num_clients=2)
> run = recipe.execute(env)
> job_id = run.job_id
> ```
```

---

### 🟡 File 4: `docs/user_guide/nvflare_cli/fl_simulator.rst`

**Line 56-60 - Update example:**
```rst
This command shows how to run the hello-numpy example, which uses the Recipe API:

.. code-block:: bash

    cd NVFlare/examples/hello-world/hello-numpy
    python job.py --n_clients 8

For traditional job structures, you can use the nvflare simulator command:

.. code-block:: bash

    nvflare simulator NVFlare/examples/traditional-job -w /tmp/workspace -n 8 -t 1 -l full
```

**Lines 756, 771 - Update or note:**
```rst
.. note::
   The hello-numpy example uses Recipe API. For traditional job structures,
   use the nvflare simulator command as shown above.
```

---

### 🟡 File 5: `docs/user_guide/nvflare_cli/poc_command.rst`

**Lines 383-411 - Replace section:**
```rst
Login and submit a job:

.. note::
   For Recipe API examples like hello-numpy, you have two options:

**Option 1: Export then submit** (traditional workflow)

.. code-block:: python

    # Export the recipe first
    cd hello-world/hello-numpy
    python job.py --export_config

    # Then submit the exported job
    submit_job /tmp/nvflare/jobs/job_config/hello-numpy

**Option 2: Use Recipe execute** (recommended)

.. code-block:: python

    from hello_numpy.job import recipe  # Or recreate it
    from nvflare.recipe import PocEnv

    env = PocEnv(num_clients=2)
    run = recipe.execute(env)
```

---

### 🟢 File 6: `docs/examples/hello_scatter_and_gather.rst`

**Simplify the entire file to be conceptual:**

```rst
Hello Federated Learning with NumPy
====================================

This tutorial introduces federated learning concepts using NVIDIA FLARE's
hello-numpy example, which demonstrates FedAvg (Federated Averaging) with
simple NumPy arrays.

Concept Overview
----------------

The example simulates federated learning where:

* **Server** starts with initial weights: ``[[1, 2, 3], [4, 5, 6], [7, 8, 9]]``
* **Clients** receive the model, train locally (add delta), send updates back
* **Server** aggregates client updates using FedAvg
* **Process** repeats for multiple rounds

Running the Example
-------------------

The hello-numpy example uses the Recipe API for simplicity:

.. code-block:: bash

    cd examples/hello-world/hello-numpy
    python job.py

This will:

1. Create a FedAvg recipe with the initial model
2. Start a simulation environment with 2 clients
3. Run 3 rounds of federated training
4. Save results to ``/tmp/nvflare/simulation/hello-numpy``

Code Structure
--------------

The example consists of:

* ``job.py`` - Creates and executes the Recipe
* ``client.py`` - Client training logic
* ``requirements.txt`` - Dependencies

For detailed code, see: :github_nvflare_link:`hello-numpy <examples/hello-world/hello-numpy>`

Understanding the Results
-------------------------

After running, check the server logs to see how weights evolve:

.. code-block:: bash

    cat /tmp/nvflare/simulation/hello-numpy/server/simulate_job/log.txt

You'll see the weights increase by 1 each round as clients add their deltas.

Next Steps
----------

* Try modifying the delta in ``client.py``
* Change number of rounds in ``job.py``
* Explore other hello-world examples: hello-pt, hello-tf, hello-lightning

Related Examples
----------------

For traditional job structure examples, see the step-by-step tutorials:
:github_nvflare_link:`Step-by-step Examples <examples/hello-world/step-by-step>`

Previous Versions
-----------------

   - `hello-numpy-sag for 2.0-2.4 <...>`_ (Traditional job structure)
```

---

### 🟢 File 7: `docs/user_guide/recipe_api_quick_ref.rst` (NEW)

Create new file:

```rst
.. _recipe_api_quick_ref:

Recipe API Quick Reference
==========================

Running Recipe API Examples Locally
-----------------------------------

Most hello-world examples use Recipe API. Simply run:

.. code-block:: bash

    cd examples/hello-world/hello-numpy  # or hello-pt, hello-tf, etc.
    python job.py

This runs in simulation mode with default settings.

Customizing Execution
---------------------

Modify parameters via command line:

.. code-block:: bash

    python job.py --n_clients 4 --num_rounds 5

Or edit the job.py file directly.

Submitting to POC/Production
-----------------------------

Recipe directories cannot be submitted directly. Two options:

**Option 1: Export to traditional format**

.. code-block:: bash

    cd examples/hello-world/hello-numpy
    python job.py --export_config
    # Job exported to /tmp/nvflare/jobs/job_config/hello-numpy

    # Then submit normally
    nvflare job submit -j /tmp/nvflare/jobs/job_config/hello-numpy

**Option 2: Use Recipe execute() (Recommended)**

.. code-block:: python

    from hello_numpy.job import recipe
    from nvflare.recipe import PocEnv, ProdEnv

    # For POC
    env = PocEnv(num_clients=2)
    run = recipe.execute(env)

    # For Production
    env = ProdEnv(
        startup_kit_location="/path/to/admin",
        username="admin@nvidia.com"
    )
    run = recipe.execute(env)

When to Export vs Execute
--------------------------

**Use Export when:**

* You need traditional job folder for workflow tools
* Submitting via admin console commands
* Want to inspect/modify job config files

**Use Execute when:**

* Running programmatically
* Want unified workflow (dev to prod)
* Prefer Python over config files

See Also
--------

* :ref:`job_recipe` - Full Recipe API tutorial
* :ref:`fed_job_api` - Traditional Job API
* :github_nvflare_link:`Hello World Examples <examples/hello-world>`
```

---

## Summary: What Actually Needs Changing

### Pattern 1: Simulation Examples
**BEFORE**: `nvflare simulator ... hello-numpy`
**AFTER**: `cd hello-numpy && python job.py`

### Pattern 2: POC/Production Submission
**BEFORE**: `sess.submit_job("hello-numpy")`
**AFTER**: Export first OR use Recipe.execute()

### Pattern 3: Results Location
**BEFORE**: `hello-numpy-workspace/`
**AFTER**: `/tmp/nvflare/simulation/hello-numpy/`

---

## That's It!

Just update these 7 files (6 existing + 1 new quick ref), and the documentation will be accurate and helpful. Much simpler than my original 40+ file plan! 🎉
