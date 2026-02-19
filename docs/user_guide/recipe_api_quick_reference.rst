.. _recipe_api_quick_reference:

Recipe API Quick Reference
===========================

This guide provides a quick reference for working with NVIDIA FLARE's Recipe API and understanding
the differences from traditional job structures.

Overview
--------

NVIDIA FLARE supports two approaches for defining federated learning jobs:

1. **Recipe API** (Modern, Python-based) - Define jobs in Python code
2. **Traditional Jobs** (Legacy, JSON-based) - Define jobs with JSON configuration files

Job Structure Comparison
--------------------------

Recipe API Job
^^^^^^^^^^^^^^

.. code-block:: none

    hello-numpy/
    ├── job.py              # Main job definition (Recipe API)
    ├── src/
    │   └── trainer.py      # Custom training logic
    └── requirements.txt    # Dependencies

Traditional Job
^^^^^^^^^^^^^^^

.. code-block:: none

    traditional-job/
    ├── meta.json           # Job metadata
    ├── app/
    │   ├── config/
    │   │   ├── config_fed_server.json
    │   │   └── config_fed_client.json
    │   └── custom/         # Custom Python code
    └── resources/

Execution Methods
-----------------

Understanding Recipe Execution
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A Recipe API job consists of:

1. **Recipe creation** - Define your FL job (workflow, clients, config)
2. **Environment selection** - Choose where to run (SimEnv/PocEnv/ProdEnv)
3. **Execution** - Call ``recipe.execute(env)``

All of this typically happens in your ``job.py`` file. The environment determines where the job runs:

- ``SimEnv`` - Single process, threaded simulation (fastest for testing)
- ``PocEnv`` - Multi-process on one machine (closer to production)
- ``ProdEnv`` - Full distributed deployment

Recipe API Jobs
^^^^^^^^^^^^^^^

**Simulation (recommended for development):**

.. code-block:: bash

    cd examples/hello-world/hello-numpy
    python job.py --n_clients 2

**POC Environment:**

.. code-block:: python

    # In your job.py file:
    from nvflare.recipe import PocEnv
    from nvflare.app_common.np.recipes.fedavg import NumpyFedAvgRecipe
    
    # Create your recipe
    recipe = NumpyFedAvgRecipe(
        name="my-job",
        min_clients=2,
        num_rounds=3,
        train_script="client.py",
        # ... other config
    )
    
    # Execute with PocEnv
    env = PocEnv(num_clients=2)
    run = recipe.execute(env)

**Production Environment:**

*Option 1: Execute directly (programmatic submission)*

.. code-block:: python

    from nvflare.recipe import ProdEnv
    
    # ... recipe creation code ...
    
    # Execute with ProdEnv - submits and runs job
    env = ProdEnv(startup_kit_location="/path/to/admin/startup/kit")
    run = recipe.execute(env)

*Option 2: Export for manual submission (CLI pattern)*

.. code-block:: bash

    # In your job.py, add CLI argument handling:
    # if args.export_config:
    #     recipe.export(job_dir)
    
    python job.py --export_config
    # Exports to /tmp/nvflare/jobs/job_config/
    # Then submit with: nvflare job submit /tmp/nvflare/jobs/job_config

Traditional Jobs
^^^^^^^^^^^^^^^^

**Simulator:**

.. code-block:: bash

    nvflare simulator path/to/job -w workspace -n 2 -t 2

**Submit to POC/Production:**

.. code-block:: bash

    # In FLARE Console
    submit_job path/to/job
    
    # Or with FLARE API
    sess.submit_job("path/to/job")

Key Differences
---------------

=================== ======================= =======================
Feature             Recipe API              Traditional Jobs
=================== ======================= =======================
Job Definition      Python (job.py)         JSON (meta.json, config/)
Configuration       Pythonic, type-safe     JSON dictionaries
Execution           ``python job.py``       ``nvflare simulator``
Submission          Export first            Direct submission
Environment Control SimEnv/PocEnv/ProdEnv   CLI arguments
Learning Curve      Easier for Python devs  Requires JSON knowledge
=================== ======================= =======================

Common Workflows
----------------

Running Recipe API Job in Simulation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

    cd your-recipe-job
    python job.py --n_clients 4 --num_rounds 10

Submitting Recipe API Job to POC
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Option 1: Export then submit**

.. code-block:: bash

    python job.py --export_config
    # Then in FLARE console:
    submit_job /tmp/nvflare/jobs/job_config/your-job

**Option 2: Use Recipe execute** (recommended)

.. code-block:: python

    from nvflare.recipe import PocEnv
    
    # Your recipe definition here
    env = PocEnv(num_clients=2)
    run = recipe.execute(env)

Migrating from Traditional to Recipe API
-----------------------------------------

If you have an existing traditional job and want to use Recipe API:

1. Study existing Recipe API examples (hello-numpy, hello-pt, etc.)
2. Extract your custom Python code from app/custom/
3. Rewrite JSON configurations as Python Recipe API calls
4. Test in simulation with ``python job.py``
5. Use Recipe execute methods for POC/production

Examples in the Repository
---------------------------

**Recipe API Examples:**

- ``examples/hello-world/hello-numpy`` - Basic NumPy example
- ``examples/hello-world/hello-pt`` - PyTorch example
- ``examples/hello-world/hello-tf2`` - TensorFlow example

**Traditional Job Examples:**

- Look for directories with ``meta.json`` and ``app/config/`` structure
- Older examples in version branches (2.0-2.4)

Getting Help
------------

- :ref:`programming_guide` - Core concepts
- :ref:`flare_api` - Programmatic control
- :ref:`fl_simulator` - Simulation environment details
- :ref:`hello_numpy` - Step-by-step tutorial

Best Practices
--------------

1. **Use Recipe API for new projects** - It's more maintainable and Pythonic
2. **Start with simulation** - Test with ``python job.py`` before deploying
3. **Version control your jobs** - Especially the job.py definition
4. **Use environment variables** - For configuration that changes between environments
5. **Test with small datasets first** - Verify your FL logic before scaling up

