.. _resource_statistics_capacity:

CPU, Memory, and CUDA Capacity
******************************

Capacity describes the resources a job process can see, not how much it uses.
NVFlare normally observes capacity once, before the application starts, and
includes it in the final report.

CPU capacity
============

One CPU unit means the processing capacity of one logical CPU. This can be a
hardware thread rather than a whole physical core.

NVFlare starts with the CPUs the process is allowed to run on. It applies any
CPU-set or CPU-time limits it can read. Without a restriction, the result can
be the whole machine's logical-CPU count.

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

Best-effort values
==================

If a limit cannot be read, NVFlare keeps a best-effort value: the allowed CPU
count (or machine count), or physical RAM, reduced by any smaller readable
limits. The value may exceed the actual limit. The CLI marks it with ``*``
and explains the gap. Only an observation with no usable value is unavailable.

An absent or unlimited constraint is not a failed measurement. Missing GPU
information does not remove CPU or memory data.

CUDA devices and GPU memory
===========================

The CUDA Driver counts the devices available to the job process. The report
can also include each group's GPU model and memory per device or instance.
Seeing a device does not establish that the job used it.

Device type is optional. A counted device can be a verified full GPU, a
verified Multi-Instance GPU (MIG) instance, or a device whose type could not
be verified. All three contribute to the total CUDA-device count exactly
once. MIG detail appears only when applicable.

A successful observation of no devices is zero. If the Driver cannot
establish a count, the GPU observation is unavailable, not zero. Missing
optional model or type information does not remove a counted device.

Duration and totals
===================

The report stores capacity and its covered elapsed seconds separately.
For example, two CUDA devices observed for 600 seconds contribute
1,200 device-seconds, or one-third of a device-hour, when queried.

Several participants can see the same hardware, so adding their capacity-time
does not count unique machines.

Inspect a participant's saved capacities and hardware details with:

.. code-block:: shell

   nvflare job resources --job JOB_ID --site site-1
   nvflare job resources --job JOB_ID --site site-1 --format json

Collection reference
====================

The reference below gives the exact queries, limit files, and selection rules.
It is not required reading to use the reports.

.. toctree::
   :maxdepth: 1

   capacity_collection
