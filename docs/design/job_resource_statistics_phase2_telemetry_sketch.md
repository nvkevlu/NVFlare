# NVFlare Phase 2 — Publishing Finalized Resource Statistics

**Status:** Integration sketch. Phase 1 owns the approved candidate-v1 contract and remains the
implementation priority. Phase 2 may publish selected finalized Phase 1 values through
**JobStatsReporter**; it does not define another collector or data model.

For the full path from observation to CLI/export, start with the
[linear review guide](../../research/runtime_resource_proxy_prototype/REVIEW_GUIDE.md). The
[Phase 1 implementation plan](job_resource_statistics_implementation_plan.md) describes the
system of record, and the [schema guide](../../research/runtime_resource_proxy_prototype/schema/README.md)
defines the exact records.

## 1. Boundary between the phases

| Layer | Owns | Does not own |
| --- | --- | --- |
| Phase 1 | Trusted bootstrap, typed lifecycle records, parent-owned durable storage, participant acceptance, derivation, server finalization, archive/manifest, RESOURCE_STATS, and CLI semantics. | Utilization, allocation, billing, or external telemetry delivery. |
| Phase 2 | A bounded adapter that reads the validated, finalized Phase 1 result and publishes selected facts through JobStatsReporter. | Collection authority, formulas, participant acceptance, retry replacement, F3 classification, or durable evidence. |
| Existing JobStatsReporter diagnostics | Current job/round/task reports and compatibility behavior. | Canonical Phase 1 evidence. |

This split is important. The existing reporter can observe events, sample task-time process
activity, accept filterable client headers, and write useful human/JSON diagnostics. Those values
have different boundaries from Phase 1 and must not be used to reconstruct or correct resource
statistics.

Phase 2 starts only after the server has:

1. closed the fixed participant-report cutoff;
2. accepted at most one immutable participant summary per roster slot;
3. derived accepted-participant and job totals;
4. validated exact archive membership and path/digest pairs;
5. materialized **resource_summary.json**; and
6. saved those exact bytes behind the narrow **RESOURCE_STATS** component API.

Publication failure is non-fatal and never changes the finalized job or its stored statistics.

## 2. Canonical Phase 1 input

The adapter consumes the exact **nvflare.resource_stats.resource_summary** object. It does not
read job-controlled files, lifecycle fragments, raw environment values, launcher specifications,
or resource-manager allocation results.

The resource summary contains:

- flat **job_id**, **report_cutoff_at**, and **finalized_at**;
- a frozen roster, with role stored once per roster entry;
- for accepted entries, **received_at**, **summary_sha256**, **observation_seconds**, and compact
  flat totals; and
- flat job totals for CPU, memory, storage, GPU, retained content, and F3.

There is no summary revision. At the Phase 1 acceptance boundary, the first valid authenticated
participant summary received by the cutoff wins. An identical-digest retry is a no-op; a
conflicting replacement is rejected; and an invalid candidate does not reserve the slot.
Distinct executions remain immutable attempt entries in the participant file.

**observation_seconds** is a convenience value derived by Phase 1 from enabled attempt
intervals. For each interval, Phase 1 uses startup capacity multiplied by:

~~~text
final observed_at - start observed_at
~~~

or, when no valid final was received:

~~~text
parent-exit observed_at - start observed_at
~~~

The latter result is partial. A valid final retains its complete capacity snapshot plus retained
content and F3 facts. A final is never invented after a crash. Phase 2 consumes these outcomes; it
does not repeat the duration or resource-time calculation.

## 3. What JobStatsReporter may publish

The initial adapter should publish only compact finalized totals and bounded roster state. Exact
backend metric names are intentionally left to the integration review, but each value has one
unambiguous Phase 1 source:

| Published concept | Phase 1 field | Meaning |
| --- | --- | --- |
| CPU time | totals.cpu.groups[].unit_seconds | Startup-visible CPU units multiplied by observed time, grouped by optional model/architecture. |
| Memory time | totals.memory.byte_seconds | Startup-visible memory bytes multiplied by observed time. |
| Storage-capacity time | totals.storage.byte_seconds | Run-filesystem capacity bytes multiplied by observed time; not occupancy or retained size. |
| GPU time | totals.gpu.groups[].instance_seconds | CUDA-validated visible instances multiplied by observed time, kept separate by kind and optional metadata. |
| Retained content | totals.retained_content.bytes | Sum of frozen platform-registered retained file sizes. |
| Primary F3 traffic | totals.f3.remote_accepted.{payload_bytes,messages} | Remote application payload accepted by transport before the fixed cutoff. |
| Participant duration | roster[].observation_seconds | Checked sum of accepted enabled attempt intervals. |
| Roster state | roster[].status | One of accepted, missing, invalid, or disabled. |

Job totals should be the default publication. Per-participant series are optional and require an
explicit cardinality and authorization decision. A site selection or participant series must not
be labeled as physical capacity or as an independently measured job total.

Every compact total has status **reported**, **partial**, or **unavailable**.

- Publish a numeric value only for reported or partial.
- Never publish unavailable as numeric zero.
- Carry the bounded status as a backend attribute or companion state signal.
- Derive counts such as expected/accepted/missing from the frozen roster at publication time.
- Do not create stored warning, coverage, or contributor fields beside the total.

Source-level issues stay in detailed Phase 1 records. Compact totals intentionally have no issue
array. The exporter should not turn arbitrary source detail into high-cardinality labels.

## 4. Hardware labels and adaptive GPU presentation

CPU **model** and **architecture**, and GPU **model**, **memory_bytes**, and **mig_profile**, are
optional. They are infrastructure fingerprints, so the default exporter should omit them unless
deployment policy explicitly enables a reviewed allowlist.

When model labels are enabled:

- copy only the normalized value already present in a finalized typed group;
- never recover missing labels from the host, CUDA, NVML, or raw probe evidence;
- omit CPU model when the visible processors were heterogeneous rather than emitting a synthetic
  heterogeneous value;
- preserve separate GPU **kind** values **full_gpu** and **mig_compute_instance**; and
- omit MIG series, columns, and explanatory text when no selected total contains positive MIG
  instance-time.

This matches the Phase 1 CLI: common clients see the simpler full-GPU view, while applicable MIG
data remains available without mixing it into a generic GPU count.

## 5. F3 authority remains in Phase 1

Every accepted Phase 1 final with numeric F3 facts has the same five factual buckets:

| Bucket | Phase 1 meaning |
| --- | --- |
| remote_accepted | Remote payload accepted by transport before cutoff. |
| local_delivered | Direct/local delivery, reported separately. |
| remote_failed_before_acceptance | Remote send that failed before acceptance. |
| late_after_cutoff | Post-cutoff traffic excluded from the frozen primary total. |
| summary_excluded | Resource-summary publication traffic excluded through a platform-owned, non-spoofable path. |

Each bucket contains canonical integer-string **payload_bytes** and **messages**. Phase 1 fixes
the included traffic classes, sender-acceptance point, cutoff, and exclusion path. A job cannot
select its own class or mark ordinary traffic as summary traffic.

The compact resource summary intentionally publishes only **remote_accepted**. If a later
telemetry view needs the other four diagnostic buckets, it must read the already validated
participant bundle under a separately reviewed bounded mapping. It must not estimate the values
from JobStatsReporter task payload sizes, communication time, receiver counts, or process-wide
statistics.

## 6. Adapter lifecycle and idempotency

Recommended server flow:

~~~text
Phase 1 finalizes and validates the archive
  -> exact resource_summary.json bytes are saved as RESOURCE_STATS
  -> a post-finalization event gives JobStatsReporter the validated object or narrow lookup key
  -> the adapter maps approved fields to bounded telemetry
  -> the backend accepts, retries, or rejects the publication independently of job completion
~~~

The adapter should use an internal method equivalent to:

~~~text
get_resource_stats(job_id)
~~~

That method selects the exact component internally. The adapter must not request a generic
component prefix, accept RESOURCE_STATS_*, or construct a job-store path from user input.

At-least-once telemetry delivery is acceptable if the backend supports idempotency. A stable
publication key can be derived from job ID, schema version, and the SHA-256 of the exact
resource-summary bytes. This is transport deduplication, not a mutable summary revision. A retry
publishes the same values; Phase 2 never replaces the Phase 1 record.

If validation or the narrow lookup fails, emit an exporter error through normal observability and
publish no resource values. Do not fall back to child fragments, current host probes, or the
existing reporter's sampled resource fields.

## 7. Privacy, cardinality, and units

The typed location defines each unit:

- CPU uses CPU-unit seconds;
- memory and storage use byte-seconds;
- GPU uses instance-seconds;
- retained content and F3 payload use bytes;
- F3 message counts use messages; and
- observation duration uses seconds.

The adapter may convert base units for a human report, but machine telemetry should preserve the
canonical decimal value or use a backend representation that can do so without silent
large-integer loss. Do not parse U128-range decimal strings through an IEEE-754 number first.

Allowed dimensions should be closed and small: resource kind, total status, GPU kind, and
optionally approved normalized hardware labels. Role comes only from the frozen roster if a
participant view is enabled. Do not export raw participant IDs/keys, attempt IDs, environment
keys, paths, hashes, host/container/pod identity, GPU UUID/PCI identity, or issue text as default
labels.

Retention, access control, and external destination remain deployment policy. Enabling
publication does not broaden who may query the canonical Phase 1 artifact.

## 8. Relationship to current reporter output

JobStatsReporter can retain its current job, workflow, round, task, and compatibility reports.
Its sampled client CPU/GPU/memory data, logical task-payload estimates, and derived
communication/wait time remain diagnostics with their existing meaning. They are not alternate
values for the Phase 1 fields above.

The clean integration is a small finalized-resource adapter within or alongside the reporter:

- receive one post-finalization notification on the server;
- obtain only the validated typed summary;
- map an explicit subset to the configured telemetry sink or report section;
- keep existing client task headers and samplers out of this path; and
- make failures non-fatal and independently observable.

If NVFlare later wants sampled workload-utilization telemetry as a product feature, that needs a
separate versioned contract and privacy review. It should not be folded into this Phase 2
publication task or into Phase 1 resource-time totals.

## 9. Implementation sequence

| Slice | Deliverable | Exit criterion |
| --- | --- | --- |
| P2-00 | Freeze backend, exact metric names, allowed dimensions, model-label policy, enablement, and retention. | The mapping is bounded and every value points to one typed Phase 1 field. |
| P2-01 | Add the post-finalization event and narrow RESOURCE_STATS reader adapter. | Reporter code cannot access unvalidated lifecycle fragments or generic components. |
| P2-02 | Implement job-total publication, closed status handling, adaptive GPU groups, and large-decimal conversion. | Reported/partial/unavailable and no-MIG/model-suppressed goldens map correctly. |
| P2-03 | Add idempotent retry, authorization, exporter failure handling, and optional participant view. | Retries cannot duplicate values and exporter failure cannot affect job completion. |

## 10. Required tests and open integration choices

Required tests:

- exact byte/object handoff after Phase 1 finalization and refusal before finalization;
- reported, partial, and unavailable mapping without invented zeros;
- roster-derived accepted/missing/invalid/disabled counts;
- full-GPU, MIG, no-MIG, suppressed model, and heterogeneous-CPU cases;
- values beyond JavaScript's safe-integer range;
- idempotent retry and conflicting/noncanonical input rejection;
- generic component-prefix and unvalidated-fragment access rejection;
- no leakage of participant keys, paths, hashes, raw hardware identity, or source issues; and
- exporter outage without any change to job result, archive, CLI, or query copy.

The remaining choices are intentionally integration-specific: telemetry backend, final metric
names, whether per-participant series are useful, hardware-model label policy, enablement
default, retry/retention limits, authorization, and compatibility placement in
JobStatsReporter. None of these choices may change the approved Phase 1 schema or formulas.
