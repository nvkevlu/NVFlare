.. _resource_statistics:

Resource Statistics
*******************

After a job finishes, resource statistics shows its participants' CPU, memory,
and GPU capacity, recorded CPU work, total run-directory file size, and selected
application data sent between them. Use it to inspect one job, look more closely
at a participant, or compare retained jobs in a study.

A participant is the server or a client site in the job. Reports are collected
automatically; no extra monitoring setup is needed.

Start with a command
====================

.. code-block:: shell

   # All participants in one finished job
   nvflare job resources --job JOB_ID

   # Add one participant's hardware and filesystem detail
   nvflare job resources --job JOB_ID --site site-1

   # Return the structured report
   nvflare job resources --job JOB_ID --format json

   # All accessible retained jobs in one study
   nvflare job resources --study STUDY_NAME

A job query uses the default study unless ``--study STUDY_NAME`` is also
provided. Running ``nvflare job resources`` without a selector displays help.
Use the normal administrator startup kit and permissions for your deployment;
see :ref:`CLI options and errors <job_resources_cli>`, or
:ref:`Python API access <flare_api_resource_utilization>`.

Reports become queryable after server finalization, not while training is
running. For live training statistics use ``nvflare job stats``; for system
monitoring see :ref:`monitoring`.

Read the output
===============

This example uses synthetic data to demonstrate the CLI format.

.. literalinclude:: resource_statistics/examples/job_resources.out
   :language: text
   :end-before: Notes:

``CPU VISIBLE`` is logical CPU capacity, ``MEM GiB`` is RAM capacity, and
``CUDA DEVICES`` is the number of devices available to that process for CUDA
execution. These values describe what the process could see, not how busy
those resources were.

``AVG CPU USED`` is different: it divides recorded CPU work by that counter's
own elapsed duration. In this example, site-1 used 180 CPU seconds over
600 seconds, averaging 0.3 CPUs despite having 32 logical CPU units visible.
The CLI uses ``cores`` as a short label for these logical CPU units.

The file and message table uses GiB, where 1 GiB is 1,073,741,824 bytes.
``PAYLOAD SENT TO SITE`` is calculated from the other participants' sends;
it is not a measurement of delivery at the receiving process.

Derived capacity-time totals multiply each observed capacity by its covered
duration. For example, two CUDA devices visible for ten minutes produce
one-third of a device-hour. Stored reports keep the capacities and durations
separately; the query calculates these products. Several participants or jobs
can see the same physical hardware, so their sums are not an inventory of
unique machines. Filesystem capacity is never multiplied by time or summed.

Incomplete information
======================

A number followed by ``*`` has incomplete information. For example, CPU
capacity may use a best-effort count when a container limit cannot be read.
An em dash (``—``) means no usable value. The ``Data gaps`` section explains
the limitation, and ``--format json`` provides the structured details.
Successful measurements have no status label in JSON.

A participant may send a valid report with CPU data but no GPU observation.
CPU averages can still be shown. A failed or missing report does not change the training
job's success or failure.

Measurement details
===================

Each page starts with what the value means. Collection methods and technical
details follow for readers who need them.

.. toctree::
   :maxdepth: 1

   resource_statistics/capacity
   resource_statistics/cpu_work
   resource_statistics/files
   resource_statistics/message_traffic
   resource_statistics/reports

Study results
=============

A study query includes jobs still retained by the job store and permitted by
the caller's existing per-job access policy. Running jobs and jobs without a
readable final resource summary appear as gaps and do not contribute to totals.
The view is not a permanent history of deleted jobs.

The following example shows two jobs with data, one without a usable report,
and one still running. Identical names do not merge jobs: the job ID identifies
each row.

.. literalinclude:: resource_statistics/examples/study_resources.out
   :language: text
   :end-before: Notes:

Collection and availability
===========================

These archived reports cover jobs using NVFlare's server/client job processes.
Standalone simulator execution is outside this guide's scope. Collection uses
existing process access and requires no additional service, privilege, mount,
or operator configuration.

Reports are best effort. A process or server crash can leave information
missing; missing data is not assumed to be zero. See
:ref:`resource_statistics_reports` for collection, storage, and failure details.
