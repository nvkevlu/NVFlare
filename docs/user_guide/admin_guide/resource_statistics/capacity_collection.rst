.. _resource_statistics_capacity_collection:

Capacity Collection Reference
*****************************

This reference explains the OS queries behind the capacities shown in
:ref:`resource_statistics_capacity`. Collection uses the job process's
existing access; no additional privileges, mounts, packages, or settings
are required.

CPU selection
=============

NVFlare takes the smaller of:

* Allowed logical CPUs from ``os.sched_getaffinity(0)``.
* Finite readable CPU-time quotas divided by their periods, including visible
  parent limits.

Affinity already includes CPU-set restrictions. A successful affinity query
does not require separate CPU-set file reads.

If affinity is unavailable, NVFlare uses
``os.sysconf("SC_NPROCESSORS_ONLN")``, falling back to ``os.cpu_count()``,
and applies any smaller readable CPU-set or quota bounds. This best-effort
count can still exceed the actual process limit.

An unreadable or invalid bound does not erase the other values. NVFlare
keeps the smallest usable value and marks the capacity observation partial
with ``observation_incomplete`` when a restriction could not be checked.
The same applies when only the machine-wide count is available in place of
affinity. An absent controller or explicitly unlimited limit is not a failed read.
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
   * - CPU-set fallback when affinity is unavailable
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
whole group. For v1 memory, a parent's limit applies only while its
``memory.use_hierarchy`` is ``1``; ``0`` ends that chain.

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

A fully readable visible hierarchy can still omit a hidden host parent.
The reported value is not a guarantee of the complete host-enforced ceiling.

Memory selection
================

Physical RAM comes from:

.. code-block:: python

   os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")

The reported bytes are the smallest usable value among physical RAM and
finite readable memory limits. An unlimited value is not a cap. A failed
limit read retains physical RAM or a smaller readable bound and marks the
capacity observation partial. Zero is a valid hard memory limit. If no usable
byte value is available, memory capacity is unavailable.

CPU and RAM use these Linux interfaces. An unsupported platform leaves the
affected observation unavailable rather than substituting an unrelated
measurement.

GPU count
==============

The statistics probe and ``GPUResourceManager`` share
``gpu_utils.get_visible_gpu_ids``. The pool uses ``nvidia-smi`` integer GPU IDs,
with ``CUDA_VISIBLE_DEVICES`` selecting which IDs are available in the reporting
environment. Integer selectors preserve order, remove duplicates, and stop at the
first negative or absent host index. With no mask, the verified host inventory
is used. An empty mask establishes zero without running the command.

A noninteger selector reached before selection stops makes the statistics
observation unavailable. The host-backed resource manager retains its fallback
to host inventory for unsupported masks. Externally managed pools retain their
``ignore_host`` behavior.

The statistics inventory query uses ``get_host_gpu_ids(timeout=2.0)``. A missing
command, command failure, timeout, malformed output, or empty inventory makes the
GPU observation unavailable. These failures preserve independent CPU/RAM values.
Collection uses the execution's existing permissions and does not initialize
application CUDA, retain a CUDA context, import a framework, or change assignments.

The count is an integer. ``gpu.instance_seconds`` records the pool count times
execution seconds, expressed as GPU-seconds; it does not measure GPU utilization.

Duration
========

The participant-level ``duration_seconds`` uses one monotonic clock for the
execution window, shared by CPU work and the startup capacity snapshot. It
includes waiting and final callback/send completion within that window.
Workspace preparation, capacity probing, later file scanning, and report
writing are outside the window. Capacity is observed once; collection does
not poll for changes or track resource releases.

An observation describes its reporting process, not every node in a
multi-node job.

Further reading
===============

* `Docker resource constraints <https://docs.docker.com/engine/containers/resource_constraints/>`_
  describes CPU and memory limits.
* `Linux CPU bandwidth control <https://docs.kernel.org/scheduler/sched-bwc.html>`_
  explains quota and period.
* The :github_nvflare_link:`CPU/RAM collector <nvflare/private/fed/resource_stats/probes/cgroup_linux.py>`,
  :github_nvflare_link:`GPU collector <nvflare/private/fed/resource_stats/probes/gpu_nvidia.py>`,
  and :github_nvflare_link:`capacity recorder <nvflare/private/fed/resource_stats/accumulator.py>`
  contain the collection logic.
