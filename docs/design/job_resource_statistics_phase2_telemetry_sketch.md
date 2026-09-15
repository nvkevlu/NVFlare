# NVFlare Phase 2 resource telemetry — JobStatsReporter sketch

Status: draft for review.

Phase 2 may publish selected facts from the finalized Phase 1 result through
JobStatsReporter. It does not collect or recalculate Phase 1 data.

## 1. Boundary between the phases

| Phase | Responsibility |
| --- | --- |
| Phase 1 | Observe runtime-visible resources, build site reports, validate them, calculate job totals, and store the final RESOURCE_STATS record. |
| Phase 2 | Read that finalized record and optionally publish an approved subset. |

Phase 2 reads the exact server-side RESOURCE_STATS component through the narrow
Phase 1 read API. Phase 1 has already validated the participant archive,
manifest, and query copy before making that record available. Phase 2 does not
read the manifest or participant files independently, nor does it read current
host values, job code, launcher data, or in-progress reports.

If RESOURCE_STATS is missing, invalid, or not final, Phase 2 publishes nothing.
A Phase 2 failure never changes the Phase 1 result or the job outcome.

## 2. Why JobStatsReporter is relevant

JobStatsReporter already publishes operational job statistics. Today it samples
process CPU, RSS, GPU utilization, and GPU memory. Those are utilization
measurements.

Phase 1 values have a different meaning:

- visible CPU, memory, and GPU capacity;
- capacity multiplied by measured time;
- one saved-result byte total; and
- F3 payload counters.

Phase 2 may use JobStatsReporter to publish Phase 1 facts, but it must
keep the two kinds of data separate. Utilization samples must never fill a
Phase 1 capacity field.

## 3. Input requirements

The adapter accepts a record only when all of these are true:

- the component name is exactly RESOURCE_STATS;
- the record kind is nvflare.resource_stats.resource_summary;
- the schema version is supported;
- the server has finalized the expected participant list;
- the Phase 1 API returns it as a finalized, validated record; and
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
| CPU-unit-seconds | totals.cpu groups |
| Memory byte-seconds | totals.memory |
| Full-GPU instance-seconds | totals.gpu full_gpu groups |
| MIG instance-seconds | totals.gpu MIG groups, only when present |
| Storage byte-seconds | totals.storage |
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
resource_proxy.cpu_unit_seconds
resource_proxy.memory_byte_seconds
resource_proxy.full_gpu_instance_seconds
resource_proxy.storage_byte_seconds
resource_proxy.saved_result_bytes
resource_proxy.f3_remote_payload_bytes
resource_proxy.quality
~~~

These names are proposed, not final.

Do not use names such as CPU used, GPU used, allocated GPU, reserved memory, or
cost. Phase 1 does not establish those meanings.

## 6. Timing

Publish only after Phase 1 has written the final RESOURCE_STATS record.

A simple sequence is:

1. Phase 1 finalizes the expected participant list.
2. Phase 1 validates received reports and calculates totals.
3. Phase 1 writes the participant records, summary, and manifest.
4. Phase 1 writes the exact RESOURCE_STATS query copy.
5. Phase 2 reads that validated copy through the narrow Phase 1 API.
6. JobStatsReporter publishes the approved fields.

No extra wait is added to job completion. If publication is asynchronous, the
adapter may retry without changing Phase 1 data.

## 7. Retry behavior

Use a stable event ID based on:

- job ID;
- Phase 1 schema version; and
- the SHA-256 digest of the exact RESOURCE_STATS bytes.

A repeated publication with the same event ID is a retry, not a new
measurement.

If the reporter cannot provide idempotent delivery, duplicate publication must
be documented. The stored Phase 1 record remains the source of truth.

## 8. Status handling

Phase 2 preserves Phase 1 status.

- reported stays reported;
- partial stays partial;
- unavailable stays unavailable; and
- missing or invalid participant reports remain visible in counts.

Do not convert unavailable to zero. Do not remove the partial label because
some numeric values are present.

## 9. Privacy and security

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

## 10. Relationship to existing JobStatsReporter output

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

## 11. Failure behavior

Phase 2 is best effort.

| Failure | Result |
| --- | --- |
| Phase 1 is not final | Publish nothing yet. |
| RESOURCE_STATS is absent | Publish nothing; record one short diagnostic. |
| Schema version is unsupported | Publish nothing; identify the version. |
| Phase 1 validation fails | Publish nothing; report invalid input. |
| JobStatsReporter is not already active | Phase 1 remains available through storage and CLI; this feature does not add an enablement setting. |
| Reporter publication fails | Keep the Phase 1 result; retry only within the normal reporter policy. |

No failure in this table may fail the federated job.

## 12. Process-model independence

Phase 2 does not need to know whether CP runs tasks directly, a parent starts
children, or another process model is chosen.

It sees one finalized server record. Any process-model work belongs to Phase 1
integration and remains outside the JobStatsReporter adapter.

## 13. Tests

Tests should cover:

- refusal before Phase 1 finalization;
- refusal for a missing or invalid RESOURCE_STATS component;
- exact field mapping;
- preservation of partial and unavailable status;
- omission of absent MIG groups;
- privacy-field rejection;
- stable retry IDs;
- duplicate retry behavior;
- publication failure without job failure;
- coexistence with existing utilization output; and
- no change to Phase 1 bytes before or after publication.

## 14. Open decisions

The team still needs to choose:

1. The final resource_proxy field names.
2. Whether Phase 2 publishes only job totals or selected per-site facts.
3. Whether hardware models are ever allowed.
4. The JobStatsReporter event type and size limit.
5. Retry duration and duplicate-delivery expectations.
6. Whether every active JobStatsReporter publishes the Phase 1 subset. This
   must be an implementation decision, not a new user or operator setting.

None of these decisions changes the Phase 1 schema or permits a new privilege,
configuration field, launch option, or deployment step.

These Phase 2 items are also recorded in the authoritative
[GAPS.md](../../research/runtime_resource_proxy_prototype/GAPS.md) list.
