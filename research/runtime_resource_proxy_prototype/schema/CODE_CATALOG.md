# Canonical v1 status and issue catalog

This file lists every allowed status and code. `resource_stats_v1.schema.json` defines their JSON
shape. `contract_v1.py` checks relationships between records. Any value not listed here is
rejected.

The contract does not store separate source, coverage, caveat, warning, or qualification codes.
The typed field already identifies the resource and unit. The CLI may explain a result, but those
display notices are not stored data.

## Resource statuses

| Context | Allowed statuses | Meaning |
| --- | --- | --- |
| Point-in-time CPU/memory/GPU | reported, unavailable, error | Complete numeric observation; no usable observation; or collection/integrity failure. |
| Participant-lifetime storage | reported, partial, unavailable, error | Numeric capacity with complete/uncertain continuous availability, no usable value, or failure. |
| Participant-terminal retained content and F3 | reported, partial, unavailable, error | Complete facts; usable incomplete facts; no usable observation; or failure. |
| Participant/job totals | reported, partial, unavailable | Complete contributions; numeric contributions with a gap/uncertainty; or no usable contribution. |

For resource observations, `reported` requires the applicable numeric facts and forbids issues.
`partial` requires numeric facts plus applicable issues. `unavailable` and `error` contain no
numeric result and require issues. Point-in-time capacity cannot be partial: a source either
produced a valid selected value or it did not. Derived totals never store issues.

An observed zero is explicit: the string `"0"`, an empty reported GPU group array, retained
content with `bytes: "0"`, or a completed participant summary with no measurement periods.
Missing, failed, disabled, or unbound collection is never encoded as zero. In particular, a
`launch_failed` capacity is unavailable rather than a reported zero, although its known
opened-to-closed duration remains part of `resource_window_seconds`.

Aggregate status has no stored issue list. It is derived deterministically:

- `reported`: every expected participant is accepted and every contribution used by that total is complete;
- `partial`: at least one numeric contribution exists and a measurement is incomplete or changed,
  or an expected participant is missing, invalid, or disabled; and
- `unavailable`: no numeric contribution exists for that total.

Workload failure or termination alone does not make resource time partial. Matching start/final
capacity plus a known end completely describes the measurement period regardless of task outcome.

## Expected participant status

| Domain | Exact values | Rule |
| --- | --- | --- |
| role | client, server | Stored once for each expected participant; never inferred from its ID. |
| status | accepted, missing, invalid, disabled | Tells what happened to that participant's report. |

The server already knows which participants the job expects. It does not build this list from
resource reports. At the cutoff, each participant is accepted, missing, invalid, or disabled.
Counts and CLI notices come from these entries.

## Issue allowlist

| Issue | Meaning in its typed context |
| --- | --- |
| not_bound | NVFlare has no existing bounded source for this fact. |
| counter_gap | Some events may be absent; the stored counter is a lower bound. |
| observation_incomplete | Only part of the relevant interval or intended bounded set was observed. |
| attribution_incomplete | Facts that could not be safely attributed were excluded. |
| unsupported | The observation is unsupported on this platform/runtime. |
| permission_denied | Ordinary-user collection was denied. |
| dependency_missing | An optional runtime/library required for the observation was absent. |
| malformed_source | A source failed parsing, range, or consistency validation. |

`issues` is a unique, sorted array of one to four values. The containing typed object supplies the
subject: for example, `not_bound` on F3 means no existing job counter is available, while the same
code on retained content means NVFlare has no existing bounded result set.

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
| Invalid participant report | malformed_source, permission_denied |

Reported objects never carry issues. Missing or changed final capacity, launch failure, disabled
collection, and missing participant reports are already visible facts, so their effects are not
duplicated as issue codes.

## Measurement-period end reason

`reason` is stored beside `closed_at` in embedded `end`. Standalone `attempt_end` also repeats
`opened_at`, making its duration self-contained:

| Reason | Meaning and shape |
| --- | --- |
| released | NVFlare ended the measurement period normally; requires an attempt start. |
| failed | The period ended after a failure; requires an attempt start. |
| terminated | The period ended after cancellation, preemption, or administration; requires an attempt start. |
| launch_failed | NVFlare knows the period bounds but no capacity snapshot exists; forbids start/final. |
| reconfigured | NVFlare ended the period after observing a capacity change; does not imply another period. |

There is no process return code. `opened_at` and `closed_at` come from the same NVFlare clock.
The schema does not choose which component supplies that clock or what process event ends a period.

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
| remote_accepted | Remote application payload accepted before NVFlare closes the counters; the primary total. |
| local_delivered | Direct/local application delivery, kept separately. |
| remote_failed_before_acceptance | Remote traffic that failed before transport acceptance. |

F3 is a participant-lifetime terminal fact, not an attempt fact. Reported/partial F3 contains all
three counter pairs; unavailable/error contains no counters. Zero messages requires zero bytes.
NVFlare closes the three counters in one operation before writing participant_final. Callbacks
that finish later do not change the stored totals. Platform code excludes resource-summary
publication; job code cannot request that exclusion.

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

This does not merge measurement periods. Distinct attempt IDs stay separate inside the one
accepted site report, including sequential periods that reuse an environment key.

## Interpretation rules, not stored codes

Documentation may explain that:

- runtime-visible values are not utilization, ownership, total physical capacity, or billing;
- CPU/memory/GPU time is calculated for each recorded measurement period;
- storage spans the site job run, not every measurement period;
- CPU, memory, storage, and GPU visibility may be shared;
- a raw CUDA mask was diagnostic only when `cuda_mask_present` is true;
- full GPUs and MIG instances are not combined;
- participant-visible totals may overlap, including intentionally across jobs;
- missing expected participant reports make an otherwise numeric aggregate partial;
- F3 includes remote-accepted application payload only in its primary total, ignores callbacks
  that finish after NVFlare closes the counters, and excludes the summary message; and
- site observations are self-reported until the server receives and stores the final report.

These facts do not require another stored warning list or mandatory CLI
disclaimer. Persisting a second warning/caveat list would create possible
contradiction without adding evidence.
