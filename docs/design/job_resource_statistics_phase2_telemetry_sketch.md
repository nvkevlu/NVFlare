# NVFlare Phase 2 — Publishing Finalized Resource Statistics

**Status:** Integration sketch. The Phase 1 candidate-v1 contract is ready for design review and
remains the implementation priority. Phase 2 may publish selected finalized Phase 1 values through
**JobStatsReporter**; it does not define another collector or data model.

For the full path from observation to CLI/export, start with the
[linear review guide](../../research/runtime_resource_proxy_prototype/REVIEW_GUIDE.md). The
[Phase 1 implementation plan](job_resource_statistics_implementation_plan.md) describes the
system of record, and the [schema guide](../../research/runtime_resource_proxy_prototype/schema/README.md)
defines the exact records.

## 1. Boundary between the phases

| Layer | Owns | Does not own |
| --- | --- | --- |
| Phase 1 | Logical-participant and stable-vector attempt records, trusted bootstrap/reconfigure hook, supervisor-owned durable storage, participant acceptance, derivation, server finalization, archive/manifest, RESOURCE_STATS, and CLI semantics. | Utilization, billing, or external telemetry delivery. |
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
Phase 2 receives no event for individual vector open/reconfiguration, allocation release,
checkpoint, or resume.
Those events are normalized by Phase 1 before publication.

## 2. Canonical Phase 1 input

The adapter consumes the exact **nvflare.resource_stats.resource_summary** object. It does not
read job-controlled files, lifecycle fragments, raw environment values, launcher specifications,
or resource-manager allocation results.

The resource summary contains:

- flat **job_id**, **report_cutoff_at**, and **finalized_at**;
- a fixed expected-participant roster sourced from authenticated job-selection/deployment state
  independently of report arrivals, made immutable and classified at the report cutoff, with role
  stored once per roster entry;
- for accepted entries, **received_at**, **summary_sha256**, **resource_window_seconds**, and compact
  flat totals; and
- flat job totals for CPU, memory, storage, GPU, retained content, and F3.

There is no summary revision. At the Phase 1 acceptance boundary, the first valid authenticated
participant summary received by the cutoff wins. An identical-digest retry is a no-op; a
conflicting replacement is rejected; and an invalid candidate does not reserve the slot.
Distinct stable `(resource lease, reporter environment, capacity vector)` windows remain immutable
attempt entries in the participant file. One scheduler allocation may contain several concurrent
reporter-environment attempts, and a partial resource change may split one environment into
sequential attempts. Multiple attempts therefore do not imply failure.

**resource_window_seconds** is a convenience value derived by Phase 1 from accepted attempt
intervals. It is their sum and may exceed participant wall time when environments overlap. For
CPU, memory, and GPU, each interval uses start capacity multiplied by:

~~~text
end.closed_at - opened_at
~~~

Both boundaries come from one durable lifecycle-owner clock. **opened_at** is recorded at
confirmed acquisition before bootstrap, so bootstrap time is included. Worker start/final
snapshots carry no duration timestamp. An optional final is capacity-stability evidence only. A
missing final makes the affected compute result partial, but a final is never invented after a
crash or preemption.

A GPU-only change closes the old vector as **reconfigured** and immediately opens a CPU/memory
plus zero-GPU successor when those resources remain held. Only a full-release interval with no
open environment attempt adds zero to every transient compute total. A launch failure after
acquisition still contributes its known open/close duration to `resource_window_seconds`, but its
missing capacity makes transient totals partial or unavailable.

`reconfigured` is a one-way lifecycle assertion: it requires an immediate same-environment
successor at the exact close boundary. When both capacity snapshots are comparable, they must
differ; a successor whose snapshot is unavailable is still representable and makes affected
totals partial or unavailable. A fully released lease may instead be reacquired at that same
timestamp and may expose a different vector without being relabeled as reconfiguration.

Storage-capacity time instead spans the logical participant's start and final storage
observations, including release/resume gaps, only when the supervisor guarantees that the
workspace remained continuously available; otherwise storage is partial or unavailable.
Retained content and all-job F3 counters are finalized once
at participant finalization. Phase 2 consumes these outcomes; it does not repeat either formula,
pair fragments across resumptions, or infer allocation state.

## 3. What JobStatsReporter may publish

The initial adapter should publish only compact finalized totals and bounded roster state. Exact
backend metric names are intentionally left to the integration review, but each value has one
unambiguous Phase 1 source:

| Published concept | Phase 1 field | Meaning |
| --- | --- | --- |
| CPU time | totals.cpu.groups[].unit_seconds | Attempt-start CPU units multiplied by resource-window time, grouped by optional model/architecture. |
| Memory time | totals.memory.byte_seconds | Attempt-start memory bytes multiplied by resource-window time. |
| Storage-capacity time | totals.storage.byte_seconds | Participant-start run-filesystem capacity multiplied by logical-participant time; not occupancy or retained size. |
| GPU time | totals.gpu.groups[].instance_seconds | CUDA-validated attempt-start instances multiplied by resource-window time, kept separate by kind and optional metadata. |
| Retained content | totals.retained_content.bytes | Sum of frozen platform-registered retained file sizes. |
| Primary F3 traffic | totals.f3.remote_accepted.{payload_bytes,messages} | Remote application payload accepted by transport before the participant-final counter freeze. |
| Resource-window duration | roster[].resource_window_seconds | Checked sum of stable environment-vector intervals; it may exceed logical participant wall time when environments overlap. |
| Roster state | roster[].status | One of accepted, missing, invalid, or disabled. |

Job totals should be the default publication. Per-participant series are optional and require an
explicit cardinality and authorization decision. A site selection or participant series must not
be labeled as physical capacity or as an independently measured job total.

Every compact total has status **reported**, **partial**, or **unavailable**.

- Publish a numeric value only for reported or partial.
- Never publish unavailable as numeric zero.
- Carry the bounded status as a backend attribute or companion state signal.
- Derive counts such as expected/accepted/missing from the fixed roster at publication time.
- Do not create stored warning, coverage, or contributor fields beside the total.

Roster membership must never be reconstructed from the reports that happened to arrive; doing so
would silently remove missing participants from coverage.

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

Every accepted Phase 1 participant final with numeric F3 facts has the same three factual buckets:

| Bucket | Phase 1 meaning |
| --- | --- |
| remote_accepted | Remote payload accepted by transport before the participant-final counter freeze. |
| local_delivered | Direct/local delivery, reported separately. |
| remote_failed_before_acceptance | Remote send that failed before acceptance. |

Each bucket contains canonical integer-string **payload_bytes** and **messages**. Phase 1 fixes
the included classes to `task_request`, `task_response`, `task_result`, `job_application`, and
`job_stream_data`. It excludes `job_stream_control`, `bulk_envelope`, `workspace_transfer`,
`platform_control`, `log_export`, unknown classes, and summary publication. A job cannot select
its own class or mark ordinary traffic as summary traffic.

Phase 1 counts `len(message.payload)` after payload encoding and optional end-to-end encryption,
immediately before the direct-delivery or remote-send boundary. It excludes headers, transport
framing, TLS/network overhead, compression effects, and retransmissions. Counts are per
destination and per sender hop, so fan-out and forwarding are hop traffic rather than unique
logical data. A remote bucket increments only after send acceptance; direct delivery remains
separate. Before participant-final serialization, the durable participant owner atomically freezes
all three counters; callbacks completing after the freeze are ignored for canonical totals.
Summary publication uses a platform-only exclusion path. Neither behavior is represented by a
stored counter, and counting summary publication inside the summary itself would be circular.

These counters span the logical participant, including traffic while no GPU attempt is open. The
compact resource summary intentionally publishes only **remote_accepted**. If a later
telemetry view needs the other two diagnostic buckets, it must read the already validated
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
publish no resource values. Do not fall back to resource-worker fragments, current host probes, or the
existing reporter's sampled resource fields.

## 7. Privacy, cardinality, and units

The typed location defines each unit:

- CPU uses CPU-unit seconds;
- memory and storage use byte-seconds;
- GPU uses instance-seconds;
- retained content and F3 payload use bytes;
- F3 message counts use messages; and
- resource-window duration uses seconds.

The adapter may convert base units for a human report, but machine telemetry should preserve the
canonical decimal value or use a backend representation that can do so without silent
large-integer loss. Do not parse U128-range decimal strings through an IEEE-754 number first.

Allowed dimensions should be closed and small: resource kind, total status, GPU kind, and
optionally approved normalized hardware labels. Role comes only from the fixed roster if a
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
- the main three-window result maps 480 CPU/memory window-seconds, 180 GPU-instance-seconds, and
  480 participant-storage seconds; a separate preempt/resume result preserves a true full-release
  gap and partial totals;
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
JobStatsReporter. Any accepted integration must preserve the reviewed Phase 1 schema and formulas.
