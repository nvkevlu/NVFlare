.. _resource_statistics_capacity:

CPU, Memory, and CUDA Capacity
******************************

Capacity describes the resources a job process can see, not how much it uses.
NVFlare captures CPU/RAM at startup. Resident jobs discover CUDA capacity
alongside application setup and execution; finalization can wait up to two
seconds for the count, followed by bounded helper cleanup. Task workers reuse
CUDA initialization performed by the application and never start a discovery
helper. An unavailable GPU count does not erase CPU/RAM observations. Later
allocation changes are not tracked.

CPU capacity
============

One CPU unit means the processing capacity of one logical CPU. This can be a
hardware thread rather than a whole physical core.

NVFlare starts with the CPUs the process is allowed to run on and applies any
smaller readable CPU-time quota. Without a restriction, the result can be the
whole machine's logical-CPU count.

For example, a process may see sixteen logical CPUs while its Docker container
has a two-CPU limit. NVFlare reports **2**. This is a shared CPU-time budget,
not a restriction to two particular CPU IDs.

A fractional limit works the same way: **0.5** means half of one logical CPU's
processing time. See :ref:`CPU quota examples <resource_statistics_cpu_quota>`
for the arithmetic.

Why read container limits?
--------------------------

Docker's ``--cpus`` option sets a CPU-time limit, which a logical-CPU count
alone can miss. Kubernetes CPU limits work similarly. Linux exposes these
limits through cgroups: groups of processes with shared resource limits.
NVFlare reads those existing limits; users do not need to configure anything
for collection.

A normal process can also inherit limits from a scheduler or system service,
so the same rule applies in every launch mode.

Memory capacity
===============

Memory capacity is the machine's physical RAM, reduced by any smaller memory
limit NVFlare can read for the process's group. A container with a readable
2 GiB memory limit on a 128 GiB machine reports **2 GiB**.

This is not currently free RAM, the process's memory use, or its peak use.
A host-memory command alone can miss a container's memory limit.

Both CPU and memory values describe visible bounds. A container can hide a
parent limit; collection does not request host access to discover it.

Best-effort values
==================

If a limit cannot be read, NVFlare keeps a best-effort value: the allowed CPU
count (or machine count), or physical RAM, reduced by any smaller readable
limits. The value may exceed the actual limit. The CLI marks it with ``*``
and explains the gap. Only an observation with no usable value is unavailable.

An absent controller or unlimited limit is not a failed measurement. Missing GPU
information does not remove CPU or memory data.

CUDA devices and GPU memory
===========================

The CUDA Driver counts the devices available to the job process. The report
can also include each group's GPU model and memory per device or instance.
Seeing a device does not establish that the job used it.

Device type is optional. A counted device can be a verified full GPU, a
verified Multi-Instance GPU (MIG) instance, or a device whose type could not
be verified. All three contribute to the total CUDA-device count exactly
once. Counts are integers, including MIG-instance counts; the report does not
convert a MIG instance into a fraction of a full GPU. GPU-hours can be
fractional: one visible GPU for half an hour contributes 0.5 GPU-hours.
MIG detail appears only when applicable.

A successful Driver count is authoritative, including zero. When CUDA is not
initialized, an exactly empty ``CUDA_VISIBLE_DEVICES`` also establishes zero
once the Driver library loads. Other mask strings are left to the Driver;
collection never interprets them as counts. A missing Driver or failed count
leaves GPU capacity unavailable, not zero. Missing optional model or type
information does not remove or delay a verified count.

Duration and totals
===================

The report stores the job-process startup capacity and accumulated
``resource_time``. Each execution multiplies capacity by its own duration;
the participant report combines those products once.
For example, two CUDA devices observed for 600 seconds contribute
1,200 device-seconds, or one-third of a device-hour. A task worker visible for
ten seconds contributes ten seconds of its capacity, not the coordinator's
whole lifetime. Queries add the recorded products.

Several participants can see the same hardware, so adding their capacity-time
does not count unique machines.

Inspect a participant's saved capacities and hardware details with:

.. code-block:: shell

   nvflare resources --job JOB_ID --site site-1
   nvflare resources --job JOB_ID --site site-1 --format json

Collection reference
====================

The reference below gives the exact queries, limit files, and selection rules.
It is not required reading to use the reports.

.. toctree::
   :maxdepth: 1

   capacity_collection
