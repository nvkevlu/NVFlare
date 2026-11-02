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

CUDA devices
============

The CUDA Driver counts devices visible in the execution environment. The count
can include visible MIG compute instances; it is not a count of physical GPUs,
a fraction of a full GPU, or a measurement of GPU use. Reports contain only this
integer count, without model, memory, or device-type breakdowns.

The resident probe inherits the environment after the launcher has applied its
GPU assignment. The startup observation retains that visibility even if the
application later narrows its own CUDA mask. Task workers instead reuse an
application-initialized CUDA count when available, without initializing CUDA
for reporting. Missing observations remain unavailable.

An observed count of zero is ``"gpu": {"count": 0}``. A missing Driver or
failed count is unavailable rather than zero. Startup capacity and device-hours
describe availability, not GPU utilization or exclusive allocation.

See :ref:`collection details <resource_statistics_capacity_collection>` for the
probe and container-limit rules.
