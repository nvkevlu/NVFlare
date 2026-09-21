# NVFlare Phase 2 resource telemetry — JobStatsReporter sketch

Status: draft for review.

This document first describes a Phase 2 adapter that may publish selected facts
from the finalized Phase 1 result through JobStatsReporter. That adapter does
not collect or recalculate Phase 1 data. A separate, deferred Phase 2 extension
may later keep periodic capacity snapshots; Section 11.1 records that future
direction without changing the Phase 1 v1 schema.

## 1. Boundary between the phases

| Phase | Responsibility |
| --- | --- |
| Phase 1 | Accumulate resource time, build one terminal report per participant, validate the reports, calculate job totals, and archive the final files in the existing server `WORKSPACE`. |
| Phase 2 finalized-summary publication | Read the finalized summary, or receive it directly from the Phase 1 finalizer, and optionally publish an approved subset. |
| Deferred Phase 2 capacity history | Periodically observe selected capacity and keep a bounded, timestamped history under a separate future contract. |

There is no `RESOURCE_STATS` job-store component. For an immediate publication,
the preferred adapter receives the already validated `resource_summary.json`
bytes directly from the root-server Phase 1 finalizer. For a later publication
or retry, it uses the same safe reader as the CLI to validate the published
`resource_stats/resource_summary.json` bundle in the existing archived
`WORKSPACE` component.

The ZIP reader checks the CRC of each member it reads, which can detect
accidental corruption of that member. Neither Phase 1 nor Phase 2 treats this
as cryptographic integrity or a signature.

The finalized-summary publication adapter does not read participant files
independently, current host values, job code, launcher data, or in-progress
reports. If the summary is missing, invalid, or not final, it publishes
nothing. A publication failure never changes the Phase 1 result or the job
outcome.

## 2. Why JobStatsReporter is relevant

JobStatsReporter already publishes operational job statistics. Today it samples
process CPU, RSS, GPU utilization, and GPU memory. Those are utilization
measurements.

Phase 1 values have a different meaning:

- accumulated CPU, memory, and GPU resource time;
- one terminal visible workspace-filesystem capacity observation in each
  participant report;
- one saved-result byte total; and
- F3 payload counters.

Phase 2 may use JobStatsReporter to publish Phase 1 facts, but it must
keep the two kinds of data separate. Utilization samples must never fill a
Phase 1 resource-time field.

## 3. Input requirements

The adapter accepts a record only when all of these are true:

- the record kind is nvflare.resource_stats.resource_summary;
- the schema version is supported;
- the server has finalized the expected participant list;
- the Phase 1 finalizer supplies validated canonical bytes, or the shared
  archive reader validates the summary publication marker, the exact derived
  participant namespace, and cross-record identities and values; and
- the job ID matches the requested job.

The adapter does not repair a bad record. It logs one short diagnostic and
publishes nothing.

## 4. Proposed publication

The first version should publish a small job-level summary:

| Published value | Phase 1 source |
| --- | --- |
| Schema version | resource summary schema_version |
| Job ID | resource summary job_id |
| Finalization time | finalized_at |
| Expected participants | number of entries in `participants` |
| Accepted reports | `participants` entries with status `accepted` |
| Missing reports | `participants` entries with status `missing` |
| Invalid reports | `participants` entries with status `invalid` |
| Disabled reports | `participants` entries with status `disabled` |
| Compute status | totals.resource_time.status |
| Measured seconds | totals.resource_time.measured_seconds, when present |
| CPU-unit-seconds | totals.resource_time.cpu groups |
| Memory byte-seconds | totals.resource_time.memory |
| Full-GPU instance-seconds | totals.resource_time.gpu full_gpu groups |
| MIG instance-seconds | totals.resource_time.gpu MIG groups, only when present |
| Saved-result bytes | totals.retained_content |
| Accepted remote F3 payload bytes/messages | totals.f3.remote_accepted |
| Overall quality | derived from the stored statuses |

The first version does not publish participant-level hardware models. Model
metadata may identify infrastructure. Adding it later requires a separate
design review; this feature adds no privacy setting or configuration switch.

## 5. Naming

Published names need a clear prefix so they cannot be confused with existing
JobStatsReporter utilization values.

Example names:

~~~text
resource_proxy.schema_version
resource_proxy.expected_reports
resource_proxy.accepted_reports
resource_proxy.compute_status
resource_proxy.measured_seconds
resource_proxy.cpu_unit_seconds
resource_proxy.memory_byte_seconds
resource_proxy.full_gpu_instance_seconds
resource_proxy.saved_result_bytes
resource_proxy.f3_remote_payload_bytes
resource_proxy.quality
~~~

These names are proposed, not final.

There is no job-level storage-capacity or storage-time field. Each participant's
single terminal visible workspace-filesystem observation remains in its
archived report. It is intentionally absent from job totals, so the proposed
job-level Phase 2 publication does not include it.

Do not use names such as CPU used, GPU used, allocated GPU, reserved memory, or
cost. Phase 1 does not establish those meanings.

## 6. Timing and current-code integration

Publish only after Phase 1 has finalized the summary.

The current JobStatsReporter lives inside the client/server job application and
writes `job_stats_run_summary.*` during server `END_RUN`. The root server has
not yet received all client terminal reports or built the Phase 1 summary at
that point. The in-job reporter therefore cannot simply open the final summary.

The preferred sequence is:

1. The root-server Phase 1 finalizer validates received reports and calculates
   totals at the existing terminal-outcome cutoff.
2. It writes and fsyncs accepted participant files.
3. It atomically writes and fsyncs `resource_summary.json` last in the
   parent-owned local construction directory as the publication marker. This
   does not constrain member ordering in the later `WORKSPACE` ZIP.
4. It passes the exact validated summary bytes to one parent-side telemetry
   adapter.
5. The adapter maps only approved fields and asks JobStatsReporter's telemetry
   sink to publish them.
6. Phase 1 continues with the existing `WORKSPACE` archival regardless of the
   publication result.

This requires a parent-side adapter or a small reusable publication interface;
it does not require an active reporter in every job process. If publication
must happen after archival, the adapter uses the same fixed-namespace
`WORKSPACE` reader as the CLI and performs the same checks.

No extra wait is added to job completion. An asynchronous retry uses the
archived workspace and never changes Phase 1 bytes.

## 7. Retry behavior

Use a stable event ID based on:

- job ID;
- Phase 1 schema version; and
- the summary's `finalized_at` value.

A repeated publication with the same event ID is a retry, not a new
measurement.

If the reporter cannot provide idempotent delivery, duplicate publication must
be documented. The stored Phase 1 record remains the source of truth.

## 8. Status handling

Phase 2 preserves Phase 1 status.

- the one `resource_time.status` stays reported, partial, or unavailable;
- retained-content and F3 statuses remain separate; and
- missing or invalid participant reports remain visible in counts.

Do not convert unavailable to zero. Do not remove the partial label because
some numeric values are present. Do not manufacture separate CPU, memory, and
GPU statuses: v1 deliberately has one compute status for the resource-time
object.

## 9. Relationship to the study CLI

The finalized-summary publication adapter publishes one finalized job fact
set. It does not create or persist a study summary.

The separate Phase 1 command:

~~~text
nvflare job resources --study NAME
~~~

builds an on-demand view from matching jobs still retained by the normal job
store. It adds resource time, saved-result bytes, and the primary F3
accepted-remote counter, but never workspace-filesystem capacity. Jobs already
removed by retention are not in that view. Sending job facts through
JobStatsReporter does not turn the CLI view into permanent history or a
billing ledger.

## 10. Privacy and security

Phase 2 reads only approved fields from the finalized summary.

It must not publish:

- host names or addresses;
- process IDs;
- GPU UUIDs or PCI addresses;
- raw CUDA visibility values;
- raw cpuinfo, CPU flags, or topology;
- workspace paths;
- raw probe errors;
- individual F3 messages; or
- job custom configuration.

The adapter uses the permissions JobStatsReporter and NVFlare already have. It
does not require root, new mounts, launcher settings, Kubernetes permissions,
cloud credentials, or Slurm administrator access.

It also adds no JobStatsReporter option. The integration is an NVFlare code
change, not a user or operator configuration task.

## 11. Relationship to existing JobStatsReporter output

Keep the current operational report for compatibility.

When JobStatsReporter publishes both forms, present them as separate sections:

~~~text
job_stats_run_summary.*       sampled utilization
resource_proxy.*              finalized Phase 1 facts
~~~

Do not add or average them together. For example, GPU utilization percentage
cannot be combined with GPU instance-seconds.

The existing StatsPool transport histograms are also separate. They do not
replace the exact per-job F3 counters.

### 11.1 Deferred periodic capacity snapshots

Phase 1 deliberately keeps accumulated resource-time, not the CPU-unit,
memory-byte, or GPU-count observation behind each private interval. A later
Phase 2 extension may record a bounded series of periodic or change-triggered
capacity snapshots using the same selection and privacy rules.

That series would be separate from both JobStatsReporter utilization samples
and the finalized Phase 1 resource-time totals. It would not replace,
recalculate, or modify the Phase 1 record. Sparse snapshots also must not be
multiplied or interpolated into authoritative resource-time unless the future
contract defines how cadence and missing intervals are handled.

Before implementation, the extension must define:

- periodic versus change-triggered collection and its cadence;
- snapshot timestamps and ordering;
- size and retention bounds;
- missing-sample and process-restart semantics; and
- which existing platform component owns the series across the chosen
  execution model.

## 12. Failure behavior

Phase 2 is best effort.

| Failure | Result |
| --- | --- |
| Phase 1 is not final | Publish nothing yet. |
| Final summary is absent from archived `WORKSPACE` | Publish nothing; record one short diagnostic. |
| Schema version is unsupported | Publish nothing; identify the version. |
| Phase 1 validation fails | Publish nothing; report invalid input. |
| JobStatsReporter is not already active | Phase 1 remains available through the job store and CLI; this feature does not add an enablement setting. |
| Reporter publication fails | Keep the Phase 1 result; retry only within the normal reporter policy. |

No failure in this table may fail the federated job.

## 13. Process-model independence

The finalized-summary publication adapter does not need to know whether CP
runs tasks directly, a parent starts children, or another process model is
chosen.

It sees one finalized server record. Phase 1 may accumulate today's
process-lifetime capacity or receive future platform-owned acquire/release
events. Those internal details remain outside the terminal schema and the
publication adapter. A future periodic-capacity extension must choose its own
platform-owned observation boundary; this document does not assume the future
process model.

## 14. Tests

Tests should cover:

- refusal before Phase 1 finalization;
- refusal for a missing or invalid publication marker, an unexpected resource
  namespace, or inconsistent participant records;
- exact field mapping;
- preservation of the single compute status and the separate saved-result and
  F3 statuses;
- omission of absent MIG groups;
- privacy-field rejection;
- stable retry IDs;
- duplicate retry behavior;
- publication failure without job failure;
- coexistence with existing utilization output;
- no change to Phase 1 bytes before or after publication;
- no persistent study rollup; and
- no workspace-filesystem capacity in additive job or study facts.

## 15. Open decisions

The team still needs to choose:

1. The final resource_proxy field names.
2. Whether Phase 2 publishes only job totals or selected per-site facts.
3. Whether hardware models are ever allowed.
4. The JobStatsReporter event type and size limit.
5. Retry duration and duplicate-delivery expectations.
6. Which reusable publication interface exposes the existing telemetry sink to
   the one root-parent adapter.
7. Whether the deferred capacity history is periodic, change-triggered, or
   both, together with its cadence, bounds, ownership, and gap semantics.

None of these decisions changes the Phase 1 schema or permits a new privilege,
configuration field, launch option, or deployment step.

These Phase 2 items are also recorded in the authoritative
[GAPS.md](../../research/runtime_resource_proxy_prototype/GAPS.md) list.
