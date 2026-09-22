# Canonical v1 status and code catalog

This file lists every allowed status and code. The JSON Schema defines their
shape and `contract_v1.py` checks cross-record rules. Unlisted values are
rejected.

The contract does not store separate source, coverage, caveat, warning, or
qualification lists. The containing typed object supplies the subject. CLI
explanations are derived from stored status and coverage rather than persisted
again.

## Typed-object statuses

| Context | Allowed statuses | Meaning |
| --- | --- | --- |
| Participant `resource_time` | reported, partial, unavailable | Complete compute resource time; at least one usable numeric member with incomplete coverage; or no usable compute resource-time value. |
| Participant `workspace_filesystem` | reported, unavailable, error | One valid terminal capacity observation; no usable observation; or collection/integrity failure. |
| Participant `retained_content` and `f3` | reported, partial, unavailable, error | Complete facts; useful incomplete facts; no usable facts; or collection/integrity failure. |
| Job/study `resource_time`, `retained_content`, and `f3` totals | reported, partial, unavailable | Complete additive contributions; at least one numeric contribution with incomplete coverage; or no numeric contribution. `resource_time` retains one issue list when not reported; retained/F3 totals do not. |

`resource_time` has exactly one status for measured time, CPU, memory, and GPU.
Those nested members never carry their own statuses. This is intentional: v1
does not expose separate CPU/memory/GPU lifecycle records.

For participant observations, `reported` requires the applicable numeric facts
and forbids issues. `partial` requires numeric facts plus applicable issues.
`unavailable` and `error` contain no numeric facts and require issues. The
workspace-filesystem point observation cannot be partial.

An observed zero is explicit: a decimal string `"0"`, an empty reported GPU
group array, a reported retained-content value of `"0"`, or zeroed reported F3
counters. Missing, invalid, disabled, unbound, or nonterminal data is never
encoded as zero.

Aggregate status is derived:

- `reported`: every selected contribution is present and complete;
- `partial`: at least one numeric contribution exists and at least one source
  contribution or expected participant/job is incomplete; and
- `unavailable`: no numeric contribution exists for that typed total.

Aggregate `resource_time` keeps one derived issue list on
partial/unavailable because it uses the same closed object as a participant.
Retained-content and F3 totals do not repeat issue lists. None of the totals
stores a second warning or caveat array.

## Expected participant state

| Domain | Exact values | Rule |
| --- | --- | --- |
| role | client, server | Stored once for each expected participant; never inferred from its ID. |
| status | accepted, missing, invalid, disabled | Classification of the participant's one terminal report at cutoff. |

`accepted` requires validated bytes installed in the server run workspace.
`invalid` requires no accepted bytes plus at least one correctly bound,
pre-cutoff candidate that failed report validation; `received_at` is the first
such rejection, and its issue is `malformed_source`.
`missing` means no bytes were accepted and the remaining outcomes were only
`not_provided`, `too_late`, authentication/binding rejection, or
`server_error`. A persistence or validator fault is therefore not blamed on
the participant. `disabled` comes only from existing platform policy. Incoming
reports never create the expected-participant set.

An accepted report always wins final classification. `duplicate` keeps that
state, while `conflict` presupposes an already accepted slot.

## Study job state

Each retained job selected for an on-demand study query has one
`resource_data` value:

| Value | Meaning |
| --- | --- |
| included | The job is terminal and its archived resource summary validated; its additive totals contribute. |
| unavailable | The job is terminal, but no valid archived resource summary could be read; it contributes no numeric value and degrades coverage. |
| nonterminal | The job was not terminal when its status was read during the query's one job-store scan; it is listed for coverage and excluded from additive totals. |

`job_status` is the bounded underlying NVFlare job state at the server's query
scan. It is not inferred from `resource_data`. `included` and `unavailable`
require a status accepted by the existing job-CLI terminal predicate: a
`FINISHED:` prefix or the legacy exact value `FINISHED_OK`,
`FINISHED_EXCEPTION`, `ABORTED`, `ABANDONED`, or `FAILED`. `nonterminal`
forbids those values. Study coverage counts selected, included, unavailable,
and nonterminal jobs separately.

## Issue allowlist

| Issue | Meaning in its typed context |
| --- | --- |
| not_bound | NVFlare has no existing bounded source for this fact. |
| counter_gap | Some events may be absent; the stored counter is a lower bound. |
| observation_incomplete | Only part of the relevant time or intended bounded set was observed. |
| attribution_incomplete | Facts that could not be safely attributed were excluded. |
| unsupported | The observation is unsupported on this platform/runtime. |
| permission_denied | Ordinary-user collection was denied. |
| dependency_missing | An optional runtime/library required for the observation was absent. |
| malformed_source | A source failed parsing, range, or consistency validation. |

`issues` is a sorted, unique array of one to four values. The containing object
provides context. For example, `not_bound` on retained content means there is
no authoritative bounded result set. F3 counters are now bound at the three
trusted semantic origins; runtime coverage failures use the applicable gap or
incomplete-attribution code rather than a clean zero.

| Context/status | Allowed issues |
| --- | --- |
| Resource time partial | observation_incomplete, attribution_incomplete |
| Resource time unavailable | not_bound, observation_incomplete, attribution_incomplete, unsupported, permission_denied, dependency_missing, malformed_source |
| Workspace filesystem unavailable | observation_incomplete, attribution_incomplete, unsupported, dependency_missing |
| Workspace filesystem error | permission_denied, malformed_source |
| Retained content partial | observation_incomplete, attribution_incomplete |
| Retained content unavailable | not_bound, observation_incomplete, attribution_incomplete, unsupported, dependency_missing |
| Retained content error | permission_denied, malformed_source |
| F3 partial | counter_gap, observation_incomplete, attribution_incomplete |
| F3 unavailable | not_bound, observation_incomplete, attribution_incomplete, unsupported, dependency_missing |
| F3 error | permission_denied, malformed_source |
| Invalid participant report | malformed_source |

Reported objects never carry issues. A missing/invalid participant or an
unavailable/nonterminal job is already an explicit coverage fact, so its
effect is not copied into a separate warning list on derived totals.
`not_bound` remains legal for historical F3 records and readers, but the
current supported production bindings do not hard-code it; a runtime loss of
an expected counter is observation or attribution incompleteness.

## GPU group kind

| Kind | Meaning |
| --- | --- |
| full_gpu | Resource time from one or more runtime-visible full CUDA devices. |
| mig_compute_instance | Resource time from one or more runtime-visible MIG compute instances. |

Only positive `instance_seconds` groups are stored. Absence of a kind from a
successfully reported GPU object means accumulated zero for that kind. An
empty reported group array means authoritative total GPU resource time of
zero. `mig_profile` is legal only on a MIG group. Full-GPU and MIG time remain
separate through participant, job, and study reduction.

## F3 counter

| Field | Included fact |
| --- | --- |
| remote_accepted | Remote application payload accepted before counters close; the primary total. |

Reported/partial participant F3 contains this counter pair;
unavailable/error has no counter. Zero messages requires zero bytes. NVFlare
closes the counters once before terminal report serialization. Later callbacks
do not alter canonical totals. Platform code excludes the resource report;
job code cannot request that exclusion.

Included classes are exactly `job_application`, `task_response`, and
`task_result`. A task response counts only when it carries a real task; empty
polls, `__try_again__`, and `__end_run__` are excluded. Task requests are not
counted. Large-object `DownloadService` data retains its originating class; it
is not a separate stream class. Control, bulk-envelope, workspace-transfer,
platform-control, log-export, unknown, and resource-report traffic are
excluded. These are platform classifications, not caller labels.

`payload_bytes` is sampled after FOBS encoding and before optional end-to-end
encryption. Successfully accepted unique `DownloadService` source bytes are
folded into the originating operation without adding messages. It excludes
headers, encryption expansion, SFM/driver/TLS/network framing, transport
compression, and retransmissions. Fan-out counts one logical message per
destination. Only the trusted semantic origin counts; the process-local
context is not serialized, so relays and forwarders do not count the payload
again. A remote logical destination routed through a local first-hop relay is
still counted once at that origin. A send increments `remote_accepted` only
after local transport acceptance. Exact final delivery to an in-process
logical destination and failed send attempts do not contribute. A streamed
send remains pending until its `StreamFuture` ends successfully; asynchronous
failure or cancellation abandons it.
An unidentifiable `DownloadService` contribution or a failed, unknown, or
ambiguous transaction settlement discards the affected logical operation and
marks F3 `partial/counter_gap`; it is never published as a complete undercount.

## Participant acceptance and replay

There is no report revision. The server:

1. authenticates and validates before cutoff;
2. accepts the first valid participant report bytes;
3. treats an exact byte-for-byte retry as idempotent;
4. rejects different bytes as a conflicting replacement; and
5. does not reserve the participant slot for an invalid candidate.

There is nothing to merge within a participant: the accepted bytes are the one
terminal report.

### Completion-request outcomes are not report fields

The selected one-message completion request needs an immediate handling result:
`accepted`, `duplicate`, `invalid`, `conflict`, `too_late`, `not_provided`, or
`server_error`. These values control bounded retry and diagnostics. They are
not persisted inside `participant_summary`, are not compute statuses, and do
not add another status branch to the schema. Final expected-participant state
is still only accepted, missing, invalid, or disabled.

The outcome list and acceptance meaning are identical whether Option A extends
`REPORT_JOB_FAILURE` or Option B uses versioned `REPORT_JOB_COMPLETION` with
exact integer `protocol_version: 1`. A client/job uses only one option.

## New query error code

| Code | Meaning |
| --- | --- |
| `RESOURCE_VIEW_TOO_LARGE` | The complete generated study response would exceed 64 MiB. Return no rows or totals; do not truncate the result. |

Existing authorization, missing-job, and running-job errors remain the normal
job-command errors and are not new resource-statistics codes.

## Interpretation rules, not stored codes

Documentation may explain that:

- resource time is visible capacity multiplied by privately accumulated time,
  not utilization, ownership, reservation, cost, or billing;
- the archive does not expose start/end snapshots or a resource-change
  timeline;
- workspace-filesystem capacity is one terminal observation of only the
  filesystem containing the existing job workspace;
- workspace capacity is not usage or job-owned storage and is not aggregated;
- CPU, memory, GPU, and filesystem capacity may be shared;
- a raw CUDA visibility mask is diagnostic only and is not stored;
- full GPUs and MIG instances are not combined;
- participant and job resource-time totals may overlap physically;
- missing participants or unavailable jobs make otherwise numeric aggregates
  partial;
- F3 counts accepted application payload only at its trusted semantic origin,
  does not recount relays, and excludes the resource report; and
- site observations are self-reported until accepted and stored by the server.

These statements do not require another warning array. A duplicate caveat list
could contradict the facts from which it should be derived.
