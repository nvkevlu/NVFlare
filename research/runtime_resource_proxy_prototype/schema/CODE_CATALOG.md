# Canonical v1 status and issue catalog

This is the human projection of the closed vocabularies in
`resource_stats_v1.schema.json`. `contract_v1.py` enforces contextual combinations and
cross-record consequences. Unknown statuses, issues, roles, end reasons, group kinds, and record
kinds are rejected.

The contract has no persisted source, coverage, caveat, warning, or qualification codes. Typed
field location and schema version already determine source semantics, units, and display text. A
renderer may show derived notices, but those notices are not canonical facts.

## Resource statuses

| Context | Allowed statuses | Meaning |
| --- | --- | --- |
| Point-in-time CPU/memory/GPU | reported, unavailable, error | Complete numeric observation; no usable observation; or collection/integrity failure. |
| Participant-lifetime storage | reported, partial, unavailable, error | Numeric capacity with complete/uncertain continuous availability, no usable value, or failure. |
| Participant-terminal retained content and F3 | reported, partial, unavailable, error | Complete facts; usable incomplete facts; no usable observation; or failure. |
| Participant/job totals | reported, partial, unavailable | Complete contributions; numeric contributions with a gap/uncertainty; or no usable contribution. |

`reported` requires the applicable numeric facts and forbids issues. `partial` requires numeric
facts plus applicable issues. `unavailable` and `error` contain no numeric result and require
issues. Point-in-time capacity cannot be partial: a source either produced a valid selected value
or it did not.

An observed zero is explicit: the string `"0"`, an empty reported GPU group array, an empty
reported retained-entry array, or a completed participant summary with no transient attempts.
Missing, failed, disabled, or unbound collection is never encoded as zero. In particular, a
`launch_failed` capacity is unavailable rather than a reported zero, although its supervisor-owned
opened-to-closed duration remains part of `resource_window_seconds`.

Aggregate status has no stored issue list. It is derived deterministically:

- `reported`: every expected enabled contribution used by that total is complete;
- `partial`: at least one numeric contribution exists and a lifecycle fact is incomplete/changed
  or a roster member is missing, invalid, or disabled; and
- `unavailable`: no numeric contribution exists for that total.

Workload failure or termination alone does not make resource time partial. Matching start/final
capacity plus a trusted end completely describes the capacity window regardless of task outcome.

## Roster state

| Domain | Exact values | Rule |
| --- | --- | --- |
| roster role | client, server | Stored once per fixed expected-participant roster entry; never inferred from participant ID. |
| roster status | accepted, missing, invalid, disabled | Partitions the expected participants at server finalization. |

Expected members come from authenticated job deployment/selection state, independently of report
arrivals. At cutoff, every expected member is classified exactly once and the roster is immutable:
`accepted` means a valid authenticated participant summary arrived by cutoff; `missing` means none
did; `invalid` adds trusted receipt time and issues because a candidate arrived but failed
validation; and `disabled` means policy disabled collection for that member. Counts, coverage, and
warnings derive from these entries.

## Issue allowlist

| Issue | Meaning in its typed context |
| --- | --- |
| not_bound | The required platform counter or registry was not connected. |
| counter_gap | Some events may be absent; the stored counter is a lower bound. |
| observation_incomplete | Only part of the relevant interval or registered set was observed. |
| attribution_incomplete | Facts that could not be safely attributed were excluded. |
| unsupported | The observation is unsupported on this platform/runtime. |
| permission_denied | Ordinary-user collection was denied. |
| dependency_missing | An optional runtime/library required for the observation was absent. |
| malformed_source | A source failed parsing, range, or consistency validation. |

`issues` is a unique, sorted array of one to four values. The containing typed object supplies the
subject: for example, `not_bound` on F3 means an unbound transport counter, while the same code on
retained content means an unbound artifact registry.

| Context/status | Exact allowed issues |
| --- | --- |
| Capacity unavailable | observation_incomplete, attribution_incomplete, unsupported, dependency_missing |
| Capacity error | permission_denied, malformed_source |
| Storage partial | observation_incomplete, attribution_incomplete |
| Retained partial | observation_incomplete, attribution_incomplete |
| Retained unavailable | not_bound, observation_incomplete, attribution_incomplete, unsupported, dependency_missing |
| Retained error | permission_denied, malformed_source |
| F3 partial | counter_gap, observation_incomplete, attribution_incomplete |
| F3 unavailable | not_bound, observation_incomplete, attribution_incomplete, unsupported, dependency_missing |
| F3 error | permission_denied, malformed_source |
| Invalid roster entry | malformed_source, permission_denied |

Reported objects never carry issues. Missing/changed attempt final capacity, launch failure,
disabled collection, and roster gaps are already visible lifecycle/roster facts, so their derived
effects are not duplicated as issue codes.

## Attempt-end reason

`reason` is stored beside `closed_at` in embedded `end`. Standalone `attempt_end` also repeats the
supervisor-owned `opened_at`, making its duration self-contained:

| Reason | Meaning and shape |
| --- | --- |
| released | Ordinary closure/release of a transient resource lease; requires an attempt start. |
| failed | Closure following a failure after a trusted start capacity snapshot; requires start. |
| terminated | Closure due to cancellation, preemption, or administration; requires an attempt start. |
| launch_failed | The resource lease opened but no accepted capacity snapshot exists; forbids start/final. |
| reconfigured | Trusted lifecycle authority observed an in-place stable capacity-vector transition; requires a same-environment successor at the exact boundary, and equal vectors are rejected when both snapshots are comparable. |

There is no process return code. `opened_at` and `closed_at` come from the same durable-supervisor
clock; `closed_at` means confirmed lease closure, not a worker snapshot or OS-process exit. The same
process may have sequential attempts as resources are released, reacquired, or reconfigured.
A full release and reacquisition can use `released` even if timestamp resolution makes the two
windows touch.

## GPU group kind

| Kind | Meaning |
| --- | --- |
| full_gpu | One or more runtime-visible full CUDA devices. |
| mig_compute_instance | One or more runtime-visible MIG compute instances. |

Only positive-count groups are stored. Absence of a kind in a successfully reported inventory
means observed zero; unavailable/error inventories contain no groups. `mig_profile` is legal only
for `mig_compute_instance`. Full-GPU and MIG-instance time stay separate through aggregation.

## F3 factual buckets

| Field | Included fact |
| --- | --- |
| remote_accepted | Remote application payload accepted by transport before the atomic freeze; the primary total. |
| local_delivered | Direct/local application delivery, kept separately. |
| remote_failed_before_acceptance | Remote traffic that failed before transport acceptance. |

F3 is a participant-lifetime terminal fact, not an attempt fact. Reported/partial F3 contains all
three counter pairs; unavailable/error contains no counters. Zero messages requires zero bytes.
The lifecycle supervisor atomically freezes the three counters before participant-final
serialization. Callback completions after the freeze never enter canonical counters, and no
ordinal is exposed. Summary publication bypasses accounting through a platform-owned
non-spoofable path; neither circular diagnostic is stored in the immutable terminal fact.

The normative included traffic classes are `task_request`, `task_response`, `task_result`,
`job_application`, and `job_stream_data`. The integration excludes `job_stream_control`,
`bulk_envelope`, `workspace_transfer`, `platform_control`, `log_export`, unknown classes, and
summary publication. These are platform-defined classifications, not caller-supplied labels.

`payload_bytes` is `len(message.payload)` after `encode_payload` and optional end-to-end
`encrypt_payload`, sampled immediately before direct delivery or `Communicator.send`. It excludes
headers, SFM/driver/TLS/network framing, transport compression, and retransmissions. One message
is counted per destination, so fan-out counts each destination and a forwarding participant
counts its sender hop again. These are participant-hop counters, not unique-logical-data counters.
Direct delivery increments `local_delivered`; a remote message increments `remote_accepted` only
after `Communicator.send` returns successfully, or `remote_failed_before_acceptance` if it fails
before acceptance.

## Participant acceptance and replay

There is no summary revision. The server:

1. validates and authenticates before the fixed cutoff;
2. accepts the first valid participant digest;
3. treats an identical digest retry as idempotent;
4. rejects a different digest as a conflicting replacement; and
5. does not reserve the slot for an invalid candidate.

This does not collapse resource windows. Distinct attempt IDs stay separate inside the one
accepted participant summary, including sequential windows that reuse an environment key.

## Derived notices, not stored codes

A v1 renderer can derive that:

- runtime-visible values are not utilization, ownership, total physical capacity, or billing;
- transient CPU/memory/GPU time is integrated per stable vector, so GPU may be zero while CPU and
  memory continue in a successor window;
- persistent storage spans the participant lifecycle, not every transient attempt;
- CPU, memory, storage, and GPU visibility may be shared;
- a raw CUDA mask was diagnostic only when `cuda_mask_present` is true;
- full GPUs and MIG instances are not combined;
- participant-visible totals may overlap, including intentionally across jobs;
- roster gaps make an otherwise numeric aggregate partial;
- F3 includes remote-accepted application payload only in its primary total, ignores callback
  completions after its atomic freeze, and excludes summary publication behaviorally; and
- attempt capacity snapshots are worker self-reports preserved by supervisor-owned durable
  storage, while attempt bounds and participant lifecycle facts are supervisor-observed.

Persisting a second warning/caveat list would create possible contradiction without adding
evidence.
