.. _resources_cli:

**********************
Resources
**********************

``nvflare resources`` reads saved resource reports after a job has
finished and the server has finalized them. It shows observed capacity,
recorded CPU work, total run-directory file size, and message payload sent
and received. For the collection methods and interpretation, start with
:ref:`resource_statistics`.

Commands
=========

.. code-block:: shell

   # One job in the default study
   nvflare resources --job JOB_ID

   # One job in a named study
   nvflare resources --job JOB_ID --study STUDY_NAME

   # Add one participant's startup capacity and workspace-filesystem detail
   nvflare resources --job JOB_ID --site site-1

   # Structured job or participant output
   nvflare resources --job JOB_ID --site site-1 --format json

   # Accessible retained jobs in a study
   nvflare resources --study STUDY_NAME

Arguments
==========

- ``--job``: job ID to inspect, in the default study unless ``--study`` is given.
- ``--study``: select the study containing ``--job``, or query the study when
  ``--job`` is omitted.
- ``--site``: include one participant's report, startup capacity and visible
  workspace-filesystem capacity. Requires ``--job``.
- ``--format json``: return structured output for automation.
- ``--schema``: print the command schema without connecting to a server.

Bare ``nvflare resources`` displays help; in JSON mode, a missing selector
returns an ``INVALID_ARGUMENT`` error envelope. Use the standard startup-kit
selection described in :ref:`job_cli`; no feature-specific setup is required.
A job name comes from existing job metadata and does not replace its ID.

Human and automation modes
==========================

Use the same command for people and agents: default text for reading,
``--format json`` for the standard JSON envelope, and ``--schema`` for argument
and behavior discovery. No separate ``nvflare agent resources`` command is
needed. JSON retains the report's native numbers and precision; display
rounding applies only to text. This command does not stream JSON Lines.

Read the result
================

The capacity table shows observed CPU, memory, and CUDA-device capacity.
A separate utilization table groups average CPU use, retained file bytes, and
message payload. Job and study totals keep the same separation.
CUDA-device counts are integers. CPU capacity and average CPU use may
be fractional; device-hours may also be fractional. Text uses
at most two decimal places without trailing zeros; positive values below
0.01 display as ``<0.01`` rather than zero.
``AVG CPU USED`` divides ``resource_utilization.cpu_consumed.cpu_seconds`` by the shared participant
``duration_seconds``. Totals are calculated at query time. ``*`` marks incomplete values;
``—`` means no usable value. See the output examples in
:ref:`resource_statistics` and the detailed explanations:

- :ref:`resource_statistics_capacity`
- :ref:`resource_statistics_cpu_work`
- :ref:`resource_statistics_files`
- :ref:`resource_statistics_message_traffic`
- :ref:`resource_statistics_reports`

Study queries check each job's normal resource-read permission before archive
access, rows, totals, or coverage counts. Nonterminal jobs and jobs without a
readable final summary do not contribute to numeric totals. The view covers
only jobs still retained in the job store.

Resource queries use a five-minute default command wait because they read
workspace archives. A query returns as soon as its result is ready; a timeout
does not cancel the server's archive read. Other commands retain their existing
timeouts.

Structured output and errors
============================

For a job, the JSON envelope contains ``data.selection`` and ``data.summary``,
plus ``data.participant`` when ``--site`` is requested. A study envelope contains
``data.selection`` and ``data.summary`` with its job rows and computed totals. Reports and archive
readers support only the current schema ``1.0``. The format and example files
are described in :ref:`resource_statistics_reports`.

An unknown job returns ``JOB_NOT_FOUND``. A job not yet finalized returns
``JOB_NOT_FINALIZED``; retry after completion. ``--site`` without ``--job``
returns ``INVALID_ARGUMENT``. A requested participant-detail file must exist
and agree with the job summary. Missing detail does not invalidate a summary-only
job or study query. Archive metadata limits still apply; see
:ref:`resource_statistics_reports`.

For live system resource information, use ``nvflare system resources``.
For running-job training statistics, use ``nvflare job stats``. The same saved
resource reports are available through :ref:`flare_api_resource_utilization`.
