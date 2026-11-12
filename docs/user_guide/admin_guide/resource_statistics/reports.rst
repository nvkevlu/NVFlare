.. _resource_statistics_reports:

Reports, quality and queries
***************************

Collection and ownership
========================

Resource statistics starts after workspace preparation and before application
construction. Each execution observes startup capacity before starting CPU and
monotonic-duration counters. At completion, it freezes the counters and sends
its measurements through the existing job outcome path. Reporting failures do
not replace the application outcome.

In task mode, the coordinator counts its own CPU and adds settled workers' CPU,
capacity-time and traffic once. Saved-result retransmission does not add compute.
Unsettled workers leave coverage gaps and omit the participant duration when a
containing observation window cannot be established. The runtime owns launch,
cancellation, results and settlement; statistics does not change those rules.

When a job process restarts, the parent reads only the terminal launch's private
handoff and checks its launch-generation token. It never substitutes a surviving
report from an earlier launch. Missing earlier observations mark the available
subtotal partial. Scheduling retries without execution do not create a gap.

Aborted or server-failed jobs allow up to 20 seconds after server exit for
expected clients to report, ending early when all reports arrive. A shorter
configured client outcome timeout still applies. Cancellation starts immediately
and other jobs continue processing. Final status, archive availability and release
of that job's scheduler slot follow report closure.

Stored reports
==============

The server accepts reports only from the expected participants of the job and
writes the accepted measurements into the normal workspace archive:

.. code-block:: text

   resource_stats/
     participants/server.json
     participants/site-1.json
     resource_summary.json

The summary contains participant measurements and missing-report entries. Job
and study queries derive totals from these recorded values. A site query also
reads the selected participant detail. The ZIP reader opens only requested
members, bounds metadata and decoded report sizes, and does not extract files.
A missing detail file does not prevent reading the job summary.

Statistics are self-reported. Job code can alter observations in memory or on
disk. Server checks enforce attribution, bounded input and usable numeric
structure, not measurement authenticity. Local producers do not repeat those
measurement checks. File operations retain path and size protections, and local
handoffs retain stale-launch protection.

Queries use existing job access controls. A study query checks authorization for
each job before reading it. Each server admits one archive-backed query at a
time; concurrent requests receive ``resource query busy; retry later``. A remote
job store may download the entire workspace archive to answer a small query, so
query time and temporary disk use can depend on archive size. A client timeout
does not cancel ongoing server storage I/O.

JSON fields
===========

Public reports use schema version ``1.0`` and native JSON numbers. Counts and
bytes are integers; CPU capacity, seconds and capacity-time may be fractional.

.. list-table:: Measurements
   :header-rows: 1
   :widths: 40 60

   * - Field
     - Meaning
   * - ``resource_capacity``
     - Startup CPU ``units``, RAM ``bytes`` and selected GPU ``count``.
   * - ``resource_time``
     - Accumulated CPU ``unit_seconds``, RAM ``byte_seconds`` and GPU ``instance_seconds``.
   * - ``duration_seconds``
     - Participant containing duration; omitted when unavailable. Worker durations are internal.
   * - ``resource_utilization.cpu_consumed.cpu_seconds``
     - CPU work across disjoint observed execution scopes.
   * - ``resource_utilization.message_traffic``
     - Separate integer ``sent_bytes`` and ``received_bytes`` payload totals.
   * - ``issues``
     - One ordered, deduplicated list of affected metrics and issue codes for the scope.

A complete measurement omits ``status``. A partial measurement keeps usable
values and explicitly sets ``status: "partial"``. An unavailable measurement
contains ``status: "unavailable"`` without an invented zero. For example:

.. code-block:: json

   {
     "resource_utilization": {
       "cpu_consumed": {"status": "partial", "cpu_seconds": 12.5}
     },
     "issues": [{"metric": "cpu_consumed", "code": "attribution_incomplete"}]
   }

Partial CPU work does not make independently complete traffic incomplete.
An unavailable GPU dimension leaves known CPU/RAM capacity usable. Zero GPU
capacity, zero byte counters and zero RAM limits remain observed zeros.

Issue codes are ``observation_incomplete``, ``attribution_incomplete``,
``unsupported`` and ``malformed_source``. They describe missing observations,
incomplete ownership coverage, unavailable platform support or unusable input.
Derived totals describe their own coverage gaps without repeating every source
diagnostic. Job summaries keep source issues on participant rows; study responses
keep them on totals, without duplicate root-level issue lists.

Duplicate participant reports do not add measurements. A changed replacement is
rejected after a report is accepted. Missing, invalid and disabled participant
reports remain explicit gaps. A server crash before publication can lose the
in-memory reports; this is not a durable delivery or billing system.

Schema and examples
===================

The :download:`JSON Schema <../../../schemas/resource_stats.schema.json>`
describes participant, job and study reports. These examples use synthetic data:

.. literalinclude:: examples/participant_summary.json
   :language: json

.. literalinclude:: examples/resource_summary.json
   :language: json
