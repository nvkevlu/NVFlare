.. _resource_statistics_reports:

Collection, Reports, and Storage
********************************

Each participant sends one final report. The server saves the available
participant measurements together in a job summary. Job and study queries
read that summary and calculate the requested totals.

When measurements are taken
===========================

.. code-block:: text

   Prepare the job workspace
       |
   Observe CPU, memory and CUDA capacity; start elapsed/CPU counters
       |
   Run the application and count included message traffic
       |
   Finish counters; observe file-size total and filesystem capacity
       |
   Send the final participant report with the job completion notification
       |
   Server saves participant reports and the job summary
       |
   Queries read the saved reports from the normal workspace archive

Capacity is observed before application construction, after workspace
preparation. It is kept with the duration it covers. CPU work has its own
matching elapsed duration. File-size and filesystem-capacity observations
are taken at the end.

Reports are available after server finalization. They are not a live
monitoring stream. Missing statistics do not change the training job's
success or failure.

How the server combines reports
===============================

When starting a job, the server records the expected server and client
participants. The completion-request handler identifies the registered
client and passes its report to the resource-statistics coordinator.

The coordinator validates the report and keeps one accepted record for each
participant. It copies those measurements into the job summary; it does not
infer that participants own separate hardware. When queried, the CLI adds
the available measurements according to each metric's rules.

At finalization, participants without a valid report remain visible as gaps.
The server writes participant files first and the job summary last. A report
arriving after finalization does not change the saved result.

Where the reports are stored
============================

The server's normal job workspace contains:

.. code-block:: text

   resource_stats/
     resource_summary.json
     participants/
       server.json
       site-1.json

The normal workspace archive includes these files. A job or study query
needs only ``resource_summary.json``. A ``--site`` query also reads the named
participant's report, including its workspace-filesystem capacity.

The summary remains usable if an optional detail file is missing.
A requested detail file must match the job summary. Extra unrelated files
in the archive do not invalidate the report.

Failure limits
==============

Reports are best effort. The server initially holds accepted reports in
memory; a crash before final files are written can lose them. A job-process
crash can also leave no final report. These cases remain gaps rather than
being filled with zero.

The server checks sender identity and report contents, but does not
independently verify the participant's hardware measurements.

Collection reference
====================

Child process and parent
------------------------

The job process collects measurements. The existing client process that
launches it, called its parent, reads temporary report data from:

.. code-block:: text

   resource_stats/staging/terminal_handoff.json

The parent supplies the job and participant identity, assembles the report
before releasing resources, and sends it afterward. The temporary file is
removed when consumed. The server follows its corresponding runner/parent
path and also includes deployment messages sent by its parent process.

Transport and validation
------------------------

The final report is attached to the existing ``REPORT_JOB_OUTCOME`` CellNet
request. CellNet is NVFlare's process-to-process messaging layer. The
completion handler passes the report to
``ResourceStatsCoordinator.accept_resource_report``.
No separate reporting service or periodic sender is needed.

Validation checks identity, fields, numeric bounds, and uniqueness.
Compact and pretty JSON are equivalent; numeric strings such as ``"2"``
and ``"2.0"`` are normalized. Equivalent duplicate reports do not add
measurements. A conflicting replacement is rejected.

Callbacks and sends are allowed to finish within bounded shutdown waits
before their counters close. Unresolved contributions leave partial data;
statistics do not wait indefinitely for complete reports.

Record layout and units
=======================

The following synthetic participant example is downloadable as
:download:`participant_summary.json <examples/participant_summary.json>`.
It uses the same format as a live participant report.

.. list-table:: Participant fields
   :header-rows: 1
   :widths: 37 63

   * - Field
     - Meaning
   * - ``schema_version`` and ``kind``
     - Identify the current ``3.0`` record format and participant record type.
   * - ``job_id`` and ``participant_name``
     - Identify the job and readable server/site name. CLI display names for jobs come from existing job metadata.
   * - ``reported_at``
     - UTC time when the parent assembles the public report, not the start of measurement.
   * - ``resource_capacity.measured_seconds``
     - Covered monotonic seconds for raw capacity; optional intervals have their own covered seconds.
   * - ``resource_capacity.cpu.groups[].units``
     - Logical CPU capacity, possibly fractional; optional ``model`` and ``architecture`` describe a group.
   * - ``resource_capacity.memory.bytes``
     - Visible RAM capacity in bytes.
   * - ``resource_capacity.gpu.groups[]``
     - Device ``count`` and verified/unverified ``kind``; optional ``model`` and per-device ``memory_bytes``.
   * - ``cpu_consumed``
     - Recorded CPU ``seconds`` and its own elapsed ``measured_seconds``.
   * - ``workspace_filesystem.capacity_bytes``
     - Point-in-time visible capacity of the workspace filesystem; participant detail only.
   * - ``retained_content.bytes``
     - Observed logical length of regular run-directory files.
   * - ``message_traffic.sent_to[]``
     - Destination ``participant_name``, accepted ``payload_bytes``, and logical ``messages``.

Quantities are decimal strings so large byte totals are not rounded by JSON
floating-point consumers. Bytes, device counts, and message counts are
integer-valued; CPU units and seconds can be fractional, with at most nine
fractional digits. Unknown values are not ``null`` or inferred zero.

The :download:`job summary example <examples/resource_summary.json>` stores
``job_id`` and participant entries. Each accepted entry has ``participant_name``,
``role``, server ``received_at`` time, and copies of ``resource_capacity``,
``cpu_consumed``, ``retained_content``, and ``message_traffic``. Filesystem
capacity stays in participant detail. Queries derive totals from the summary.

Hardware descriptions are optional. Raw GPU UUIDs, PCI addresses, environment
values, credentials, and private transfer identifiers are not persisted.

Missing and incomplete data
==============================================

A normal participant entry and successful measurement omit ``status``.
Exceptions identify what happened without changing another measurement's value:

.. list-table:: Exception statuses
   :header-rows: 1
   :widths: 24 28 48

   * - Status
     - Applies to
     - Meaning
   * - ``partial``
     - Measurement
     - Usable values remain; the explanation describes what could not be measured or checked.
   * - ``unavailable``
     - Measurement
     - No usable value; do not substitute zero.
   * - ``missing``
     - Participant
     - No valid report was available when the job was finalized.
   * - ``invalid``
     - Participant
     - A received report could not be accepted as valid data.
   * - ``disabled``
     - Participant
     - The server knows this expected participant was not launched for the job.

The JSON ``issues`` codes have the following meanings. The CLI shows the
explanation, not the code:

.. list-table:: Issue codes
   :header-rows: 1
   :widths: 25 45 30

   * - Code
     - Concrete examples
     - How to interpret the value
   * - ``observation_incomplete``
     - A CPU/RAM limit could not be read; GPU counting failed; a file scan stopped at its limit; an earlier attempt's measurements are missing.
     - Available values remain. Capacity can be too high after fallback; file totals can be too low after a stopped scan.
   * - ``attribution_incomplete``
     - Child-process CPU time was not accounted for, or a trainer's tensor transfer could not be tied to this participant.
     - The recorded CPU work or message total may omit that contribution.
   * - ``counter_gap``
     - A transfer was unresolved at collection; an accounting callback failed; a custom download lacks stable chunk identifiers; tracking reached its limit; or one chunk identifier had conflicting byte lengths.
     - Some accepted messages or payload bytes may be missing. Downloads continue normally.
   * - ``unsupported``
     - The platform does not provide the measurement, or a multi-node launch cannot be represented by a local capacity observation.
     - No usable value is reported for that measurement. This is not zero.
   * - ``malformed_source``
     - A child hands its parent a negative byte count, invalid number, or incorrectly shaped measurement.
     - The invalid value is discarded; independent valid measurements and contributions remain usable.

The report does not identify the exact CPU/RAM limit that could not be read.

For example, a capacity block may retain CPU and RAM while omitting an
unavailable GPU observation:

.. code-block:: json

   {
     "resource_capacity": {
       "status": "partial",
       "issues": ["observation_incomplete"],
       "measured_seconds": "600",
       "cpu": {"groups": [{"units": "2"}]},
       "memory": {"bytes": "2147483648"}
     }
   }

The CLI translates gaps into readable explanations, marks incomplete numbers
with ``*``, and shows ``—`` for unavailable values.

Full participant example
========================

.. literalinclude:: examples/participant_summary.json
   :language: json

Source reference
================

The :github_nvflare_link:`collector <nvflare/private/fed/resource_stats/collector.py>`,
:github_nvflare_link:`client completion path <nvflare/private/fed/client/client_executor.py>`,
:github_nvflare_link:`server completion handler <nvflare/private/fed/server/fed_server.py>`,
:github_nvflare_link:`coordinator <nvflare/private/fed/resource_stats/coordinator.py>`,
and :github_nvflare_link:`archive reader <nvflare/private/fed/resource_stats/archive_reader.py>`
implement the flow above. The
:github_nvflare_link:`semantic contract <nvflare/private/fed/resource_stats/contract.py>`
and :github_nvflare_link:`JSON Schema <research/runtime_resource_proxy_prototype/schema/resource_stats_v3.schema.json>`
define required fields, accepted values, privacy checks, and bounds.
