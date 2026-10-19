.. _resource_statistics_cpu_work:

CPU Work and Average CPU Used
*****************************

CPU work is processing time recorded for the job process and completed child
processes. It is different from :ref:`CPU capacity <resource_statistics_capacity>`.

Read the values
===============

One second of work on each of two CPUs consumes about two CPU seconds.
Waiting for data adds elapsed time but little CPU work.

The report stores CPU seconds and their matching elapsed seconds:

.. code-block:: json

   {
     "cpu_consumed": {
       "seconds": "180",
       "measured_seconds": "600"
     }
   }

The CLI calculates:

.. code-block:: text

   AVG CPU USED = CPU seconds / matching elapsed seconds
                = 180 / 600
                = 0.3 CPUs

This is not 30 percent of the whole host. It is an average of 0.3 logical CPUs,
regardless of the job's visible CPU capacity. An average can exceed one when
work uses several CPUs.

Inspect a participant with:

.. code-block:: shell

   nvflare job resources --job JOB_ID --site site-1
   nvflare job resources --job JOB_ID --site site-1 --format json

What is covered
===============

The counter covers the job process and its threads, plus completed child
processes whose CPU time has been collected after waiting for them to exit.
Custom or still-running subprocesses are not guaranteed to be included.

Known missing work makes the value partial, shown as ``*``. An unavailable
counter is shown as ``—``, not zero. A missing GPU observation does not hide
a usable CPU average.

Collection details
==================

On Unix, NVFlare reads ``resource.getrusage(resource.RUSAGE_SELF)`` and
``resource.getrusage(resource.RUSAGE_CHILDREN)`` before and after execution.
Each provides user and system CPU seconds:

.. code-block:: text

   CPU work = change in self user + system time
            + change in waited-child user + system time

A monotonic clock measures the matching elapsed duration. The CPU-work
duration is measured alongside this counter; it is not borrowed from the
capacity observation. A missing or zero matching duration prevents calculation
of an average.

``RUSAGE_CHILDREN`` includes terminated children after they have been waited
for. Grandchildren depend on the intervening processes waiting for their
children. A child whose lifetime crosses the measurement boundary may not
align exactly with the elapsed window.

Collection does not isolate the job into a new process group or discover
every custom subprocess. Known live workers, incomplete descendant accounting,
or lost earlier-attempt measurements leave the surviving subtotal partial.

For an optional view of the OS counters in a new diagnostic process:

.. code-block:: shell

   python3 - <<'PY'
   import resource
   for name, who in (('self', resource.RUSAGE_SELF),
                     ('waited_children', resource.RUSAGE_CHILDREN)):
       usage = resource.getrusage(who)
       print(name, usage.ru_utime + usage.ru_stime)
   PY

These are cumulative counters for the diagnostic process, not measurements
of another running job. NVFlare records the difference between its own reads.

:github_nvflare_link:`CpuConsumedAccountant <nvflare/private/fed/resource_stats/cpu_consumed.py>`
implements the counter and duration calculation.
