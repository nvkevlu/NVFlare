# Canonical v1 status and issue catalog

This is the human projection of the closed vocabularies in
resource_stats_v1.schema.json. contract_v1.py enforces contextual combinations and cross-record
consequences. Unknown statuses, issues, roles, exit outcomes, group kinds, and record kinds are
rejected.

The accepted contract has no persisted source, coverage, caveat, warning, or qualification
codes. Typed field location and schema_version already determine source semantics, units, and
display text. A renderer may expose derived notices, but those notices are not canonical facts.

## Resource statuses

| Context | Allowed statuses | Meaning |
| --- | --- | --- |
| Point-in-time CPU/memory/storage/GPU | reported, unavailable, error | Complete numeric observation; no usable observation; or collection/integrity failure. |
| Retained content and F3 | reported, partial, unavailable, error | Complete facts; usable incomplete facts; no usable observation; or failure. |
| Participant/job totals | reported, partial, unavailable | Complete contributions; numeric contributions with a gap/uncertainty; or no usable contribution. |

reported requires the applicable numeric facts and forbids issues. partial requires numeric facts
plus one or more applicable issues. unavailable and error contain no numeric result and require
one or more applicable issues. Point-in-time capacity cannot be partial: a source either produced
a valid selected value or it did not.

An observed zero is explicit—the string \"0\", an empty reported GPU group array, or an empty
reported retained-entry array. Missing, failed, disabled, or unbound collection is never encoded
as zero.

Aggregate status has no stored issue list. It is derived deterministically from participant facts:

- reported: every expected enabled contribution used by that total is complete;
- partial: at least one numeric contribution exists and a contributing attempt is partial or a
  roster member is missing, invalid, or disabled; and
- unavailable: no numeric contribution exists for that total.

## Collection and roster state

| Domain | Exact values | Rule |
| --- | --- | --- |
| collection_state | enabled, disabled | Stored once on attempt start; disabled forbids capacity and a child final. |
| roster role | client, server | Stored once per frozen roster entry; never inferred from its participant ID. |
| roster status | accepted, missing, invalid, disabled | The one frozen roster partitions expected participants. |

An accepted roster member has a valid authenticated participant file received no later than the
cutoff. Missing means none arrived. Invalid adds trusted receipt time and issues because a
candidate arrived but failed authentication, shape, semantic, or digest validation. Disabled
means collection policy was disabled for that participant. Counts, coverage, and warnings derive
from these entries and are not parallel stored fields.

## Issue allowlist

| Issue | Meaning in its typed context |
| --- | --- |
| not_bound | The platform counter or registry required by that object was not connected. |
| counter_gap | Some events may be absent; the stored numeric counter is a lower bound. |
| observation_incomplete | Only part of the relevant interval or registered set was observed. |
| attribution_incomplete | Some facts could not be safely attributed to this job/attempt and were excluded. |
| unsupported | The required observation is unsupported on this platform/runtime. |
| permission_denied | Ordinary-user collection was denied. |
| dependency_missing | An optional runtime/library required for this observation was absent. |
| malformed_source | A source returned data that failed parsing, range, or consistency checks. |

issues is a unique, canonically sorted array of one to four values. The same compact word is safe
because the containing object supplies the missing noun—for example, not_bound on F3 is an
unbound CellNet counter, while not_bound on retained content is an unbound artifact registry.

### Contextual issue matrix

| Context/status | Exact allowed issues |
| --- | --- |
| Capacity unavailable | observation_incomplete, attribution_incomplete, unsupported, dependency_missing |
| Capacity error | permission_denied, malformed_source |
| Retained partial | observation_incomplete, attribution_incomplete |
| Retained unavailable | not_bound, observation_incomplete, attribution_incomplete, unsupported, dependency_missing |
| Retained error | permission_denied, malformed_source |
| F3 partial | counter_gap, observation_incomplete, attribution_incomplete |
| F3 unavailable | not_bound, observation_incomplete, attribution_incomplete, unsupported, dependency_missing |
| F3 error | permission_denied, malformed_source |
| Invalid roster entry | malformed_source, permission_denied |

Reported objects never carry issues. Capacity change, missing final, and early termination are
already observable by comparing lifecycle records, so resource-time partiality derives from those
facts rather than another persisted reason code. Disabled collection and roster gaps similarly
remain states rather than duplicated issues.

## Process-exit outcome

outcome is stored directly beside observed_at (and return_code when applicable), both in the
standalone parent-exit record and the nested participant attempt. There is no extra exit wrapper.

| Outcome | Return-code rule | Meaning |
| --- | --- | --- |
| finished_ok | required and exactly 0 | Child completed successfully. |
| finished_error | required and nonzero | Child exited with a failure code. |
| terminated | required and nonzero | Parent observed termination rather than normal completion. |
| launch_failed | omitted | No child return code exists; launch itself failed. |

The return code is a signed 32-bit JSON integer. Parent exit is required even when collection was
disabled or the child final is missing. Final presence is established by the accepted bundle, not
by a separate child_final_state label.

## GPU group kind

| Kind | Meaning |
| --- | --- |
| full_gpu | One or more runtime-visible full CUDA devices. |
| mig_compute_instance | One or more runtime-visible MIG compute instances. |

Only positive-count groups are stored. Absence of a kind in a successfully reported GPU inventory
means observed zero; an unavailable/error inventory carries no groups. mig_profile is legal only
for mig_compute_instance. Full-GPU and MIG-instance time remain separate through aggregation.

## F3 factual buckets

| Field | Included fact |
| --- | --- |
| remote_accepted | Remote application payload accepted by transport before the cutoff; the primary F3 total. |
| local_delivered | Direct/local application delivery, kept separately. |
| remote_failed_before_acceptance | Remote traffic that failed before transport acceptance. |
| late_after_cutoff | Events after the fixed cutoff, excluded from the primary total. |
| summary_excluded | Summary-publication traffic excluded via a platform-owned non-spoofable path. |

Reported/partial F3 contains all five pairs and cutoff_sequence; unavailable/error contains no
counter facts. Each pair has payload_bytes and messages. Zero messages requires zero bytes;
zero-byte messages with a positive message count are allowed. If the cutoff is zero, each
pre-cutoff bucket is zero. A positive pre-cutoff message count requires a positive cutoff.

The traffic-class allowlist and sender/exclusion mechanism are fixed by v1 integration. They are
not user-controlled labels and are not serialized as codes. Remote-failed bytes are recorded only
when the post-serialization size is known; failures before that point make observation coverage
partial rather than inventing a size.

## Participant acceptance and replay

There is no summary_revision state. Participant acceptance has these exact outcomes:

1. validate/authenticate before the fixed cutoff;
2. accept the first valid participant digest;
3. accept an identical digest retry as an idempotent no-op;
4. reject a different digest as a conflicting replacement; and
5. do not reserve the participant slot for an invalid candidate.

This does not collapse execution attempts. Multiple attempts retain unique attempt IDs and remain
separate entries inside the one accepted participant summary.

## Derived notices, not stored codes

A schema-v1 renderer can deterministically explain that:

- runtime-visible values are not allocations, reservations, ownership, total physical capacity,
  or billing;
- CPU, memory, filesystem, and GPU visibility may be shared;
- a raw CUDA mask was diagnostic only when cuda_mask_present is true;
- full GPUs and MIG instances are not combined;
- participant-visible totals may overlap, including intentionally across jobs;
- missing/invalid/disabled roster members make a numeric aggregate partial;
- F3 includes remote-accepted application payload only and excludes local, failed, late, and
  summary-publication buckets from its primary total; and
- start/final facts are child self-reports preserved by parent-owned storage.

Because each notice follows from stored typed facts, persisting a second caveat/warning list would
create possible contradiction without adding evidence.
