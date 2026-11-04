.. _resource_statistics_capacity:

CPU, Memory, and GPU Capacity
*****************************

Capacity describes the resources available to the job process, not how much it
uses. NVFlare captures CPU/RAM and the GPU count at startup. The GPU count
uses the same integer-index selection rules as NVFlare's GPU resource manager.
An unavailable GPU observation does not erase CPU/RAM data. Later allocation
changes are not tracked.

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

GPU count
==============

The GPU count is the number of verified integer GPU IDs selected by the
execution's ``CUDA_VISIBLE_DEVICES`` mask. With no mask, it uses the verified
``nvidia-smi`` inventory. An empty mask establishes zero without running the
command. Unsupported selectors, including GPU UUIDs, are unavailable.

The probe runs after the launcher establishes the execution's environment,
before its measurement window. Its inventory command has a two-second timeout.
Missing, malformed, empty, or failed inventory remains unavailable rather than
becoming zero. An explicit empty pool is ``"gpu": {"count": 0}``.

Reports contain only the integer count of selected inventory IDs, without model, memory, or
device-type breakdowns. GPU-seconds and GPU-hours describe this pool's capacity
over time, not GPU utilization or exclusive allocation.

See :ref:`collection details <resource_statistics_capacity_collection>` for the
probe and container-limit rules.
