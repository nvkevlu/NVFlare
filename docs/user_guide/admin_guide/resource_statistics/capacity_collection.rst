.. _resource_statistics_capacity_collection:

Capacity Collection Reference
*****************************

This reference explains the OS queries behind the capacities shown in
:ref:`resource_statistics_capacity`. Collection uses the job process's
existing access; no additional privileges, mounts, packages, or settings
are required.

CPU selection
=============

NVFlare takes the smallest positive CPU bound it can read:

* Allowed logical CPUs from ``os.sched_getaffinity(0)``.
* A readable CPU-set restriction.
* A finite CPU-time quota divided by its period.

If affinity is unavailable, the base count is
``os.sysconf("SC_NPROCESSORS_ONLN")``, with ``os.cpu_count()`` as a fallback.
This can be the machine-wide logical-CPU count rather than a process-specific
limit.

An unreadable or invalid bound does not erase the other values. NVFlare
keeps the smallest usable value and marks the capacity observation partial
with ``observation_incomplete`` when a restriction could not be checked.
The same applies when only the machine-wide count is available in place of
affinity. A missing or explicitly unlimited constraint is not a failed read.
If no positive value is available, CPU capacity is unavailable.

For example, if affinity allows sixteen CPUs but a configured quota cannot
be read, the report retains sixteen as a best-effort value. It does not claim
that sixteen is the actual container limit. A second readable bound of four
would reduce that value to four.

.. _resource_statistics_cpu_quota:

How a quota becomes CPU units
-----------------------------

A quota is a CPU-time budget shared by the process group during each
scheduling period:

.. code-block:: text

   CPU units = quota / period

For a 100-millisecond period:

.. list-table::
   :header-rows: 1
   :widths: 30 30 40

   * - CPU-time budget
     - Raw quota / period
     - CPU units
   * - 50 milliseconds
     - 50,000 / 100,000 microseconds
     - 0.5
   * - 200 milliseconds
     - 200,000 / 100,000 microseconds
     - 2

The second case is possible because CPU time adds across logical CPUs:
two CPUs each working for 100 milliseconds consume 200 milliseconds of
CPU time. The scheduler may spread that work across more CPUs for shorter
bursts. A quota is not a mapping to particular CPU IDs or a guarantee of
exclusive CPU access.

CPU weights or shares are not converted into a fixed CPU capacity.

Linux limit files
=================

Docker and Kubernetes use Linux cgroups to enforce resource limits. A cgroup
is a group of processes subject to shared limits. Different Linux systems
expose those limits in v1 or v2 file formats; NVFlare reads the format already
in use.

.. list-table::
   :header-rows: 1
   :widths: 20 38 42

   * - Limit
     - Cgroup v2
     - Cgroup v1
   * - Allowed CPUs
     - ``cpuset.cpus.effective``
     - ``cpuset.effective_cpus``, or ``cpuset.cpus``
   * - CPU-time budget
     - Quota and period in ``cpu.max``
     - ``cpu.cfs_quota_us`` and ``cpu.cfs_period_us``
   * - Memory
     - ``memory.max``
     - ``memory.limit_in_bytes``

The process's membership and mount locations come from
``/proc/self/cgroup`` and ``/proc/self/mountinfo``. CPU and memory controls
can be in different directories. Readable parent limits also apply: a
container's own directory can say unlimited while its parent limits the
whole group.

For an optional inspection from a shell in the same environment:

.. code-block:: shell

   cat /proc/self/cgroup
   cat /proc/self/mountinfo

The limit files above are read from the controller directories identified
by those records, not an assumed fixed directory. These shell commands show
the shell's environment, which need not match a worker launched elsewhere.

NVFlare does not search outside the process's visible mounts for hidden
host limits. Failure to read an applicable limit leaves a best-effort value,
not a requirement for additional host access.

Memory selection
================

Physical RAM comes from:

.. code-block:: python

   os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")

The reported bytes are the smallest usable value among physical RAM and
finite readable memory limits. An unlimited value is not a cap. A failed
limit read retains physical RAM or a smaller readable bound and marks the
capacity observation partial. If no positive byte value is available, memory
capacity is unavailable.

CPU and RAM use these Linux interfaces. An unsupported platform leaves the
affected observation unavailable rather than substituting an unrelated
measurement.

CUDA count and optional descriptions
====================================

On Linux, Python's ``ctypes`` loads the system ``libcuda.so.1`` and calls:

.. code-block:: text

   cuInit(0)
   cuDeviceGetCount(&count)

A successful count is the numeric authority. Successful zero and an explicit
``CUDA_ERROR_NO_DEVICE`` mean zero. A missing Driver, missing required symbol,
or other initialization/count error means unavailable. Unlike CPU/RAM, a
host inventory count is not a fallback for the process's CUDA-device count.

``cuDeviceGet`` obtains each counted device handle.
``cuDeviceGetName`` and ``cuDeviceTotalMem_v2`` supply optional model and
total CUDA memory per device or instance, not memory in use or the group's
combined memory. Failed metadata queries leave the numeric count intact.

The optional NVIDIA Management Library (NVML) classifies counted devices.
NVFlare obtains a private ``cuDeviceGetUuid_v2`` identity, matches an NVML
handle by UUID, then calls ``nvmlDeviceIsMigDeviceHandle``:

* Verified non-MIG: ``full_gpu``.
* Verified Multi-Instance GPU (MIG) instance: ``mig_compute_instance``.
* No reliable classification: ``cuda_device_unclassified``.

NVML does not add devices or set the count. Missing NVML or identity leaves
counted devices unclassified; it does not make the numeric observation fail.

``nvidia-smi`` lists management inventory and can differ from the devices
selected for the process. ``CUDA_VISIBLE_DEVICES`` is not parsed for a count.
Collection requires neither CUDA Runtime nor a training framework.

Hardware models
===============

CPU models come from ``/proc/cpuinfo`` for the affinity-selected CPUs, with
architecture from ``platform.machine()``. Different known models can form
separate groups. If a quota spans different models, NVFlare keeps the numeric
capacity without guessing how to divide it between models. Missing
descriptions do not remove a usable count.

Duration
========

``resource_capacity.measured_seconds`` uses a monotonic clock from the end of
the capacity observation until final collection closes it. It includes waiting
during the job and final callback/send completion within that window. Workspace
preparation, the initial probe, later file scanning, and report writing are
outside the window.

A normal report has one observation. If NVFlare is given updated capacity
during execution, each interval has its own capacity and seconds. Queries add the
interval products; the CLI shows ``varies`` when capacities differ. Collection
does not independently detect resource release or poll for changes.

An observation describes its reporting process, not every node in a
multi-node job.

Further reading
===============

* `Docker resource constraints <https://docs.docker.com/engine/containers/resource_constraints/>`_
  describes CPU and memory limits.
* `Linux CPU bandwidth control <https://docs.kernel.org/scheduler/sched-bwc.html>`_
  explains quota and period.
* The :github_nvflare_link:`CPU/RAM collector <nvflare/private/fed/resource_stats/probes/cgroup_linux.py>`,
  :github_nvflare_link:`CUDA collector <nvflare/private/fed/resource_stats/probes/gpu_nvidia.py>`,
  and :github_nvflare_link:`capacity recorder <nvflare/private/fed/resource_stats/accumulator.py>`
  contain the collection logic.
