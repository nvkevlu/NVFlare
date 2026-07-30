.. _timeout_troubleshooting:

#############################
Timeout Troubleshooting Guide
#############################

This guide covers the most common timeout-related job failures and how to resolve them.
For a comprehensive reference of all timeouts, see :ref:`timeouts_programming_guide`.

.. contents:: Table of Contents
   :local:
   :depth: 2

Common Job Failure Scenarios
============================

Task Fetch Timeout
------------------

**Symptom**: Client fails to receive tasks from server; logs show "timeout" during task fetch.

**Common Causes**:

- Large model weights take too long to transfer
- Network latency exceeds default timeout
- Tensor streaming timeout exceeds task fetch timeout

**Solution**: Set ``get_task_timeout`` in client config:

.. code-block:: python

   recipe.add_client_config({
       "get_task_timeout": 300,  # 5 minutes
   })


External Process Pre-Init Timeout (Client API Only)
----------------------------------------------------

**Applies to**: Client API with subprocess launcher (``ScriptRunner``, ``ClientAPILauncherExecutor``)

**Symptom**: Job fails before training starts with "external_pre_init_timeout" error.

This timeout controls how long NVFlare waits for your external training script to call ``flare.init()``.
When using Client API, NVFlare launches your script as a subprocess and waits for it to connect back.

**Common Causes**:

- Large models (LLMs) take time to load before ``flare.init()`` is called
- Heavy library imports (PyTorch, TensorFlow, transformers)
- Slow disk I/O reading model weights

**Solution**: Call ``flare.init()`` as soon as the distributed rank is known and
before model, tokenizer, dataset, or checkpoint loading. Increasing the timeout is
defense in depth, not a substitute for this ordering:

.. code-block:: python

   import os
   import nvflare.client as flare

   rank = int(os.environ.get("RANK", "0"))
   flare.init(rank=rank)

   # Heavy initialization begins only after the Client API session exists.
   model = load_model()
   tokenizer = load_tokenizer()

For a recipe-generated job, also make the pre-init budget explicit:

.. code-block:: python

   from nvflare.client.constants import EXTERNAL_PRE_INIT_TIMEOUT

   recipe.add_client_config({
       EXTERNAL_PRE_INIT_TIMEOUT: 600,
   })

For a directly configured executor, set the same budget in its constructor:

.. code-block:: python

   from nvflare.app_common.executors.client_api_launcher_executor import ClientAPILauncherExecutor

   executor = ClientAPILauncherExecutor(
       external_pre_init_timeout=600,  # 10 minutes for LLMs
       ...
   )


Heartbeat Timeout
-----------------

**Symptom**: Client marked as dead; logs show "heartbeat timeout" or "client not responding".

**Common Causes**:

- Long-running training blocks heartbeat thread
- Network issues causing missed heartbeats
- Client overwhelmed with compute

**Solution**: Adjust heartbeat settings:

.. code-block:: python

   # In executor configuration
   heartbeat_timeout = 300.0   # 5 minutes
   heartbeat_interval = 10.0   # Send every 10 seconds

**Rule**: ``heartbeat_interval`` must be less than ``heartbeat_timeout``.


Training Task Timeout
---------------------

**Symptom**: Training interrupted before completion; logs show task timeout.

**Common Causes**:

- Training round takes longer than expected
- Data loading is slow
- Hardware is slower than anticipated

**Solution**: Set appropriate task timeout in controller:

.. code-block:: python

   # ScatterAndGather controller
   controller = ScatterAndGather(
       train_timeout=7200,  # 2 hours per round
       wait_time_after_min_received=60,
   )

   # Or via ModelController
   controller = FedAvg(
       num_rounds=100,
       timeout=7200,  # 2 hours per round
   )


Result Submission Timeout
-------------------------

**Symptom**: Training completes but result submission fails.

**Common Causes**:

- Large model results take time to transfer
- Network congestion

**Solution**: Set ``submit_task_result_timeout``:

.. code-block:: python

   recipe.add_client_config({
       "submit_task_result_timeout": 300,  # 5 minutes
   })


Subprocess Large-Model Result Submission Timeout
-------------------------------------------------

**Applies to**: Subprocess-mode clients (``launch_external_process=True``) with large models

**Symptom**: Training completes in the subprocess but the job hangs or fails immediately
after, with no result acknowledgment received. With very large payloads and many
clients, logs may also show repeated ``no ref found`` messages from
``DownloadService`` after delayed retries.

**Cause**: ``submit_result_timeout`` is the time the training subprocess waits for
the client job process to acknowledge its result. ``PEER_READ_TIMEOUT`` is the
client config key for the parent client job's corresponding wait for the
subprocess to read a task. For large models (5 GB+) and many clients, either side
can exceed short defaults if streaming request timeouts are configured higher
than the pipe timeout. The subprocess also must remain alive long enough for the
server to finish pulling tensors from its ``DownloadService`` after result ACK.

**Solution**:

.. code-block:: python

   recipe.add_client_config({
       "submit_result_timeout": 1800,      # 30 min for LLM-scale results
       "download_complete_timeout": 1800,  # keep subprocess alive for server tensor download
       "last_result_transfer_timeout": 1800,  # parent waits for final result transfer
       "PEER_READ_TIMEOUT": 600,           # parent CJ read budget; match configured streaming timeout
       "tensor_min_download_timeout": 600, # PyTorch transaction lifetime/inactivity floor
       # "np_min_download_timeout": 600,   # NumPy/sklearn: same, use instead of tensor variant
       "max_resends": 3,                   # finite value; 0 disables retries, None is rejected
   })

.. note::
   ``submit_result_timeout`` is the subprocess-side wait for acknowledgment.
   It is distinct from ``submit_task_result_timeout``, which is the server-side wait
   for the client to deliver a result.  For large models, set ``submit_task_result_timeout``
   (server-side) to be at least as large as ``submit_result_timeout`` (subprocess-side)
   so the server is still listening when the subprocess finishes sending.

.. note::
   In FLARE 2.8.0, ``ClientAPILauncherExecutor`` rejects
   ``download_complete_timeout=None`` and ``max_resends=None`` at job
   initialization. Use a positive ``download_complete_timeout`` and a finite
   non-negative ``max_resends`` value. Recipe-based external-process jobs
   serialize the default ``max_resends=3`` in executor args; use
   ``recipe.add_client_config({"max_resends": N})`` only to override that
   default.

Swarm Learning P2P Transfer Timeout
------------------------------------

**Applies to**: ``SwarmLearningRecipe`` with large models

**Symptom**: Swarm Learning job fails with P2P ACK timeout during model scatter between peers.

**Cause**: ``round_timeout`` (which sets the P2P model-transfer ACK budget between peers)
defaults to 3600 s.  For very large models (7B+) on congested networks, peer-to-peer
tensor streaming can approach this limit.

**Solution**: Set ``round_timeout`` directly on the recipe:

.. code-block:: python

   recipe = SwarmLearningRecipe(
       name="swarm",
       model=MyModel(),
       min_clients=3,
       num_rounds=5,
       train_script="client.py",
       round_timeout=7200,  # 2 hours for 70B+ models
   )

Cross-Site Evaluation Timeout
-----------------------------

**Symptom**: Model evaluation fails or times out during cross-site validation.

**Solution**: Adjust evaluation timeouts:

.. code-block:: python

   from nvflare.app_common.np.recipes import NumpyCrossSiteEvalRecipe

   recipe = NumpyCrossSiteEvalRecipe(
       submit_model_timeout=900,      # 15 min for model submission
       validation_timeout=7200,       # 2 hours for validation
   )


Quick Reference Table
=====================

Most Commonly Adjusted Timeouts
-------------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 15 55

   * - Timeout
     - Default
     - When to Increase
   * - get_task_timeout
     - None
     - Large models, slow networks, tensor streaming
   * - submit_task_result_timeout
     - None
     - Large result payloads
   * - submit_result_timeout (subprocess mode only)
     - 300 s through Client API job config; 60 s in raw ``FlareAgent``
     - Large model result transfers from subprocess; set 1800 s for LLMs
   * - tensor_min_download_timeout / np_min_download_timeout (subprocess mode only)
     - Effective 600 s with the current default streaming-idle floor
     - Large streamed transactions with long activity gaps (tensor = PyTorch, np = NumPy/sklearn); this is not the F3 receiver inter-chunk read guard
   * - PEER_READ_TIMEOUT (Client API subprocess only)
     - 300 s
     - Large task payloads when streaming per-request timeout is explicitly increased
   * - download_complete_timeout (subprocess mode only)
     - 1800 s
     - Keep subprocess alive while the server downloads large tensor results
   * - last_result_transfer_timeout (Client API subprocess only)
     - 300 s
     - Large final subprocess result; coordinate with result/download operation budgets
   * - max_resends (subprocess mode only)
     - 3
     - Persistent network failures; keep finite; use 0 to disable retries
   * - round_timeout (Swarm Learning only)
     - 3600 s
     - 7B+ model P2P transfers between Swarm peers
   * - external_pre_init_timeout (Client API subprocess only)
     - 300 s
     - LLMs, heavy imports before ``flare.init()``
   * - heartbeat_timeout
     - 60-300s
     - Long training iterations, slow networks
   * - train_timeout
     - 0
     - Long training rounds
   * - validation_timeout
     - 6000s
     - Large validation datasets
   * - progress_timeout
     - 3600s
     - Complex multi-round workflows


Configuration Methods
=====================

Via Recipe API
--------------

.. code-block:: python

   # Client-side timeouts (applies to all clients)
   recipe.add_client_config({
       "get_task_timeout": 300,
       "submit_task_result_timeout": 300,
   })

   # Or for specific clients
   recipe.add_client_config({
       "get_task_timeout": 600,
   }, clients=["site-1", "site-2"])


Via Configuration Files
-----------------------

**application.conf** (job-level):

.. code-block::

   get_task_timeout = 300.0
   submit_task_result_timeout = 300.0

   # Server startup/dead-job safety flags
   strict_start_job_reply_check = false
   sync_client_jobs_require_previous_report = true

Server-side safety flags guidance (see :ref:`server_startup_dead_job_safety_flags` for full details):

- ``strict_start_job_reply_check`` (default ``false``): in non-strict mode, start-job timeouts are silently
  excluded from the active set with no ``min_sites``/``required_sites`` enforcement; set to ``true`` to make
  timeouts visible and have ``min_sites``/``required_sites`` constraints enforced at startup.
- ``sync_client_jobs_require_previous_report`` (default ``true``): keep enabled to avoid false dead-job reports
  caused by transient startup or sync races.

**comm_config.json** (system-level, in startup kit):

.. code-block:: json

   {
     "heartbeat_interval": 10,
     "streaming_ack_wait": 600,
     "streaming_ack_progress_timeout": 600,
     "streaming_read_timeout": 600,
     "streaming_send_timeout": 600
   }


Recommended Settings by Scenario
================================

Client API Large-Model Checklist
--------------------------------

Use this checklist for subprocess-mode PyTorch jobs that load or exchange large
models. The timeout values are an example envelope; choose one operation budget
that exceeds the slowest measured load or transfer, then keep dependent settings
coordinated.

**Required lifecycle order**:

1. Establish the distributed rank/process group.
2. Call ``flare.init(rank=rank)`` on every rank before heavyweight initialization.
3. Load the model, tokenizer, datasets, and checkpoints; then apply FSDP/DDP sharding.
4. Only rank zero calls ``flare.receive()`` and ``flare.send()``; all ranks participate
   in the framework collectives.

**Coordinated recipe configuration**:

.. code-block:: python

   from nvflare.client.config import ConfigKey
   from nvflare.client.constants import EXTERNAL_PRE_INIT_TIMEOUT, LAST_RESULT_TRANSFER_TIMEOUT, PEER_READ_TIMEOUT
   from nvflare.fuel.f3.streaming.transfer_progress import (
       STREAMING_IDLE_TIMEOUT,
       STREAMING_MAX_PEER_SILENCE,
   )

   operation_timeout = 1800

   recipe.add_client_config({
       EXTERNAL_PRE_INIT_TIMEOUT: operation_timeout,
       PEER_READ_TIMEOUT: operation_timeout,
       ConfigKey.HEARTBEAT_TIMEOUT: operation_timeout,
       ConfigKey.SUBMIT_RESULT_TIMEOUT: operation_timeout,
       ConfigKey.DOWNLOAD_COMPLETE_TIMEOUT: operation_timeout,
       ConfigKey.MAX_RESENDS: 3,
       LAST_RESULT_TRANSFER_TIMEOUT: operation_timeout,
       STREAMING_IDLE_TIMEOUT: operation_timeout,
       STREAMING_MAX_PEER_SILENCE: operation_timeout * 1.5,
       "get_task_timeout": operation_timeout,
       "submit_task_result_timeout": operation_timeout,
       "max_runner_sync_timeout": operation_timeout,
       "runner_sync_timeout": 5.0,
       "tensor_streaming_per_request_timeout": operation_timeout,
       "tensor_min_download_timeout": operation_timeout,
   })

   recipe.add_server_config({
       "strict_start_job_reply_check": True,
       "sync_client_jobs_require_previous_report": True,
       STREAMING_IDLE_TIMEOUT: operation_timeout,
       STREAMING_MAX_PEER_SILENCE: operation_timeout * 1.5,
       "tensor_streaming_per_request_timeout": operation_timeout,
       "tensor_min_download_timeout": operation_timeout,
   })

Keep ``max_resends`` finite. Set ``submit_task_result_timeout`` greater than or
equal to ``submit_result_timeout``, and keep ``tensor_min_download_timeout``
greater than or equal to ``tensor_streaming_per_request_timeout``.

Pin the matching low-level transport guards in ``comm_config.json`` for the
server and every client startup kit. Configuration-file values take precedence
over environment fallbacks:

.. code-block:: json

   {
     "streaming_ack_wait": 1800,
     "streaming_ack_progress_timeout": 1800,
     "streaming_read_timeout": 1800,
     "streaming_send_timeout": 1800
   }

``streaming_ack_wait`` is the absolute time a sender may remain blocked by its
flow-control window; it does not reset merely because a partial ACK advanced
within that window. ``streaming_ack_progress_timeout`` and
``streaming_read_timeout`` are no-progress/read inactivity guards.
``streaming_send_timeout`` applies to the socket-driver frame-send path; gRPC
deployments should still pin it if startup kits may later change transport.

For external-process PyTorch clients, the launcher resolves
``tensor_streaming_per_request_timeout`` and writes the effective value into
``client_api_config.json`` as ``download_req_timeout``. The subprocess installs
that value as ``FOBSContextKey.DOWNLOAD_REQ_TIMEOUT`` before it decodes the first
task. This propagation is required; otherwise the subprocess-side
``TensorDecomposer`` cannot see the parent application configuration and falls
back to 600 seconds.

The operation budget must also be greater than or equal to the external
client-readiness allowance. Calling ``flare.init()`` early establishes the
subprocess session, but the parent can already be waiting for that subprocess
to read its first task while model loading and sharding continue. In
particular, a shorter ``PEER_READ_TIMEOUT`` can undercut an apparently longer
model-readiness watchdog.

The ``tensor_`` prefix is required for PyTorch ``TensorDecomposer`` transfers.
The generic ``streaming_per_request_timeout`` key does not replace
``tensor_streaming_per_request_timeout``.

Before allocating accelerators, export the job on a CPU node and verify both
client configurations and the server configuration. Also inspect the packaged
training source—not only the source checkout—to confirm that ``flare.init()``
still precedes heavyweight initialization. A large-model run should fail
preflight if any required site, timeout, dataset, or lifecycle check is missing.

These are operation and inactivity budgets, not a recommendation to add an
application-level total-runtime deadline. Use a separate progress-aware watchdog
only if it resets on real transfer, training, aggregation, and persistence
progress.

Also size the recipe's external-process ``shutdown_timeout`` for distributed
framework teardown. This clock starts during cleanup, not during healthy
training, but a short value can terminate a large FSDP or NCCL process group
before it has released resources and returned its final status.

Some framework boundaries are intentionally lower-level than this coordinated
envelope. The server start-job request covers launching an already-deployed
client job, not loading model weights. When a byte-stream sender is blocked by
its flow-control window, F3 defaults to a 300-second ACK-wait limit and a
separate 60-second no-ACK-progress guard. The receiver read default is 300
seconds. These are lower boundaries unless the startup kits override them; ACK
wait is a blocked-window lifetime, while ACK progress and receiver read are
inactivity guards. CoreCell's ``max_timeout`` (3,600 seconds by default) is used
only when the caller supplies no request timeout; it does not clamp an
explicitly longer call. ``streaming_max_peer_silence`` is currently resolved
for compatibility but is not a Phase-1 progress-aware task-send liveness guard;
use the active streaming-idle timeout rather than treating max-peer-silence as
proof. Before a costly run, exercise the exact provisioned control plane with
all required clients and confirm that the largest individual serialized
tensor—not only the aggregate state—is below the transport's message-size
ceiling.

Standard Training
-----------------

.. code-block:: python

   recipe.add_client_config({
       "get_task_timeout": 120,
   })


Large Model Training (100M+ parameters)
---------------------------------------

.. code-block:: python

   recipe.add_client_config({
       "get_task_timeout": 600,
       "submit_task_result_timeout": 600,
       "submit_result_timeout": 600,        # subprocess mode only
       "download_complete_timeout": 1800,   # subprocess mode only
       "last_result_transfer_timeout": 600, # parent launcher final-result wait
       "tensor_streaming_per_request_timeout": 600,  # PyTorch subprocess mode
       "tensor_min_download_timeout": 600,  # use np_min_download_timeout for NumPy
       "PEER_READ_TIMEOUT": 600,            # subprocess mode only
       "max_resends": 3,                    # subprocess mode only; finite default
   })


LLM/Foundation Model Training
-----------------------------

.. code-block:: python

   recipe.add_client_config({
       "get_task_timeout": 1200,
       "submit_task_result_timeout": 1800,  # server-side; must be >= submit_result_timeout
       "submit_result_timeout": 1800,       # subprocess mode only
       "download_complete_timeout": 1800,   # subprocess mode only
       "last_result_transfer_timeout": 1800, # parent launcher final-result wait
       "tensor_streaming_per_request_timeout": 600,  # PyTorch
       "tensor_min_download_timeout": 600,  # PyTorch; use np_min_download_timeout for NumPy
       "PEER_READ_TIMEOUT": 600,            # subprocess mode only
       "max_resends": 3,                    # keep finite; increase only after measured transient failures
   })


High-Latency Networks
---------------------

.. code-block:: python

   # Longer communication timeouts
   recipe.add_client_config({
       "get_task_timeout": 600,
       "submit_task_result_timeout": 600,
   })

System-level (``comm_config.json`` in startup kit):

.. code-block:: json

   {
     "heartbeat_interval": 15,
     "streaming_ack_wait": 600,
     "streaming_ack_progress_timeout": 600,
     "streaming_read_timeout": 600,
     "streaming_send_timeout": 600
   }


Streaming Stall Guardrail (``comm_config.json``)
------------------------------------------------

For large payload/model transfers, configure F3 stream stall detection in
``comm_config.json`` (server and client startup kits).

**Runtime defaults** (if not set explicitly):

- ``streaming_ack_wait``: ``300`` seconds while the flow-control window remains blocked
- ``streaming_read_timeout``: ``300`` seconds
- ``streaming_send_timeout``: ``30.0`` seconds for the socket driver
- ``streaming_ack_progress_timeout``: ``60.0`` seconds
- ``streaming_ack_progress_check_interval``: ``5.0`` seconds
- ``sfm_send_stall_timeout``: ``45.0`` seconds
- ``sfm_close_stalled_connection``: ``false`` (warn-only)
- ``sfm_send_stall_consecutive_checks``: ``3``

**Recommended deployment guideline**:

1. Start with **warn-only** to observe behavior safely.
2. If repeated stall warnings are observed during large-model streaming, enable auto-close.
3. Keep the guard enabled with consecutive checks to reduce false alarms.

Warn-only baseline:

.. code-block:: json

   {
     "sfm_close_stalled_connection": false,
     "sfm_send_stall_timeout": 75,
     "sfm_send_stall_consecutive_checks": 3
   }

Auto-recovery mode (when needed):

.. code-block:: json

   {
     "sfm_close_stalled_connection": true,
     "sfm_send_stall_timeout": 75,
     "sfm_send_stall_consecutive_checks": 3
   }

**Timing relationship (important)**:

- ``sfm_send_stall_timeout`` is compared against the total continuous blocked-send duration.
- ``sfm_send_stall_consecutive_checks`` counts consecutive heartbeat monitor ticks (every 5 seconds),
  not multiples of ``sfm_send_stall_timeout``.

Approximate auto-close window (when ``sfm_close_stalled_connection=true``):

.. code-block:: text

   close_lower_bound ~= sfm_send_stall_timeout + (HEARTBEAT_TICK * (sfm_send_stall_consecutive_checks - 1))
   close_upper_bound ~= sfm_send_stall_timeout + (HEARTBEAT_TICK * sfm_send_stall_consecutive_checks)

With ``sfm_send_stall_timeout=75`` and ``sfm_send_stall_consecutive_checks=3``, close typically occurs
around ``85``-``90`` seconds of continuous stall (not 225 seconds).

**Outer-timeout guideline**:

Set higher-layer timeouts (for example ``communication_timeout`` or task/request timeouts that include
message transfer time) greater than ``close_upper_bound`` plus a safety margin.

Example: ``communication_timeout=300`` is safely larger than the ~``90`` second stall auto-close window.

**How to interpret logs**:

- Expected warning on real stalls:
  ``Detected stalled send on ... (N/3)``
- In healthy/normal streaming, no stall warning should be emitted.
- Intermittent stalls should not close the connection unless the threshold is reached in consecutive checks.


Large-Scale Hierarchical / HPC Deployments (Slurm, Lustre)
------------------------------------------------------------

When running 100+ FL clients in a hierarchical topology on HPC systems with shared
filesystems (Lustre, GPFS), two settings significantly improve startup reliability:

**1. Set a minimum-client tolerance in** ``config_fed_server.json``

Allow a small number of clients to be late or unavailable at startup without aborting
the job. For a 144-client job, tolerating up to ~4% stragglers is safe:

.. code-block:: json

   {
     "workflows": [{
       "id": "controller",
       "path": "nvflare.app_common.workflows.fedavg.FedAvg",
       "args": {
         "num_clients": 144,
         "min_clients": 138
       }
     }]
   }

**2. Extend the runner sync timeout in** ``config_fed_client.json``

With the default runner sync settings (a 2.0-second per-request timeout with overall
sync bounded by ``max_runner_sync_timeout``), many clients contending for Lustre I/O
at job launch can time out before finishing initialization. Increase these values to
give each client more time to start up:

.. code-block:: json

   {
     "runner_sync_timeout": 120,
     "max_runner_sync_timeout": 7200
   }

These two changes address the most common startup race conditions in large hierarchical
deployments and are compatible with the startup stability fixes in FLARE 2.7.2.


Debugging Timeout Issues
========================

1. **Check logs** for "timeout" messages to identify which timeout triggered
2. **Enable debug logging** to see detailed timing information
3. **Monitor heartbeat status** in admin console
4. **Start with longer timeouts** during development, then optimize

For timeout hierarchies, relationships, and all available timeout parameters, 
see the comprehensive :ref:`timeouts_programming_guide`.
