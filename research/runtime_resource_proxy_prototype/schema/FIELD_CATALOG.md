# Canonical v1 field catalog

This is the human index for `resource_stats_v1.schema.json`. The JSON Schema and
`contract_v1.py` are normative. Every object is closed: unknown fields are rejected, JSON
`null` is never a valid substitute for missing data, and measured numeric values are canonical
decimal strings rather than JSON numbers.

## Two time scopes

The contract deliberately separates two time scopes:

| Scope | Starts | Ends | What it measures |
| --- | --- | --- | --- |
| Site job run | NVFlare begins this site's part of the job | NVFlare finishes this site's part of the job | storage, saved-result files, and F3 |
| Measurement period (`attempt`) | NVFlare records a resource observation and start time | NVFlare records the end time | CPU, memory, and GPU capacity-time |

An attempt is a measurement period. It does not imply a process, allocation, lease, or roadmap
architecture. One site report may contain several periods. Time outside recorded periods does not
contribute CPU, memory, or GPU time.

## Top-level records

| Record | Always required | Purpose |
| --- | --- | --- |
| `attempt_start` | schema_version, kind, job_id, participant_id, attempt_id, environment_key, opened_at, capacity | Resource observation and start time for one measurement period. |
| `attempt_final` | same identity, capacity | Optional final observation used to check whether capacity changed. |
| `attempt_end` | same identity, opened_at, closed_at, reason | End time and reason for one measurement period. |
| `participant_start` | schema_version, kind, job_id, participant_id, observed_at, storage | Start of one site's job run and its storage observation. |
| `participant_final` | same participant identity, observed_at, storage, retained_content, f3 | End-of-site storage, saved-result, and F3 observation. |
| `participant_summary` | schema_version, kind, job_id, participant_key, start, final, attempts | Final site report accepted by the server. |
| `resource_summary` | schema_version, kind, job_id, report_cutoff_at, finalized_at, roster, totals | Final server result. |
| `manifest` | schema_version, kind, job_id, entries | Exact path/digest inventory. |

Each record has exact `schema_version: "1.0"` and its namespaced
`nvflare.resource_stats.*` kind. This candidate has no general-purpose extension object. The standalone records are
small collection fragments. Their bodies are embedded without repeated identity in
`participant_summary`.

## Common identity and time

| Field | Type and serialized rule | Purpose |
| --- | --- | --- |
| job_id | 1–128 ASCII characters; alphanumeric first, then alphanumeric, dot, underscore, or hyphen | Authenticated job identity. |
| participant_id | 1–128 ASCII alphanumeric/underscore/hyphen characters; alphanumeric first | Authenticated display identity on standalone records. |
| attempt_id | exactly 32 lowercase hexadecimal characters | Random 128-bit identity for one measurement period. |
| environment_key | `sha256-` plus 64 lowercase hexadecimal characters | Job-scoped platform HMAC for one measurement scope; it may repeat only for non-overlapping periods. |
| participant_key | same sha256-prefixed form | Job-scoped platform HMAC used in archive paths and the expected participant list. |
| observed_at | calendar-valid UTC RFC 3339 ending in `Z`, with zero to nine fractional digits | Participant storage/terminal observation time. |
| opened_at | same timestamp form | NVFlare start time for one measurement period. |
| closed_at | same timestamp form, not earlier than opened_at | NVFlare end time for that period, using the same clock. |
| report_cutoff_at | same timestamp form | Fixed last acceptance point for participant summaries. |
| finalized_at | same timestamp form, not earlier than cutoff | Time when the server built the final result. |
| received_at | same timestamp form, not later than cutoff | Trusted server receipt time for an accepted or invalid candidate. |

Keys are keyed HMAC outputs, not plain hashes of enumerable labels. Shape validation is not
identity authentication; the server must match a report to its authenticated job context.

## Measurement-period capacity

Both `attempt_start.capacity` and `attempt_final.capacity` contain exactly `cpu`, `memory`, and
`gpu`. Storage is intentionally absent: it is measured once for the site job run rather than once
per measurement period. The embedded `start` and `final` bodies contain capacity only. Timestamps
remain on the measurement period.

Point-capacity objects use `reported`, `unavailable`, or `error`:

- `reported` requires its value/evidence and forbids `issues`;
- `unavailable` or `error` forbids numeric/evidence/model fields and requires applicable issues;
- an observed zero is explicit; omission never means zero except for an absent GPU kind inside a
  successfully reported inventory.

### CPU

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, unavailable, error | Point-capacity state. |
| visible_units | reported only | positive decimal string, maximum 1,048,576, at most 9 fractional digits | Minimum applicable selector evidence. |
| evidence.affinity_count | optional strong evidence | positive U32 integer string | Logical CPUs visible through process affinity. |
| evidence.cpuset_count | optional strong evidence | positive U32 integer string | Logical CPUs in the effective cgroup cpuset. |
| evidence.quota_units | optional strong evidence | positive decimal CPU units, same bound | Exact finite quota/period ratio, conservatively floored to nine fractional digits before persistence. |
| evidence.online_count | fallback only | positive U32 integer string | Used only when no affinity/cpuset/quota evidence is usable. |
| model | optional on reported | normalized display-safe ASCII, at most 128 characters | Emitted only for a homogeneous affinity-visible set; this feature adds no publication setting. |
| architecture | optional on reported | normalized ASCII label, 1–32 characters | Metadata; it does not affect numeric authority. |
| issues | unavailable/error only | 1–4 sorted unique values | Contextual cause; see `CODE_CATALOG.md`. |

Raw `quota_us` and `period_us` are probe inputs, not canonical fields. For example,
`150000 / 100000` is stored as `quota_units: "1.5"`, while `1 / 3` becomes
`quota_units: "0.333333333"`. Division uses exact decimal arithmetic and floors, rather than
rounding up, so normalization cannot overstate the effective quota. When strong evidence exists,
`online_count` is forbidden. A heterogeneous CPU set omits `model` without changing status.

### Memory

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, unavailable, error | Point-capacity state. |
| visible_bytes | reported only | positive U64 integer string | Minimum finite evidence value. |
| evidence.physical_bytes | optional | positive U64 integer string | Physical RAM, excluding swap. |
| evidence.cgroup_limit_bytes | optional | positive U64 integer string | Effective finite cgroup limit; unlimited is omitted. |
| issues | unavailable/error only | 1–4 sorted unique values | Contextual cause. |

Reported memory requires at least one evidence value. Physical-only evidence is the host-visible
fallback. With both values, `visible_bytes` equals their minimum.

### GPU

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, unavailable, error | `reported` means CUDA-runtime enumeration succeeded. |
| cuda_mask_present | required | boolean | Presence diagnostic only; the raw mask and its token count are forbidden. |
| groups | reported only | 0–4,096 sorted unique groups | Empty means successfully observed zero. |
| issues | unavailable/error only | 1–4 sorted unique values | Contextual cause. |

Each positive group has `kind`, positive U32 string `count`, and optional normalized `model` and
positive U64 `memory_bytes`. `memory_bytes` is runtime-reported memory per visible entity, not
aggregate group memory; all entities in a consolidated group share it, and differing values form
separate groups. `mig_profile` is optional only for
`kind: "mig_compute_instance"`; it is forbidden for `full_gpu`. Group identity is kind plus the
optional metadata. The total of group counts fits U32. NVML may enrich a CUDA-enumerated group but
cannot add groups or change count authority. A non-MIG client simply has no MIG group.

A reported empty `groups` array means CUDA-runtime enumeration succeeded and found no visible GPU.
It is a generic observation, not a required consequence of a resource release. A process that
already initialized CUDA under different visibility cannot establish a new inventory reliably.

## Site-run storage

`participant_start.storage` and `participant_final.storage` use lifecycle-status rules:

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, partial, unavailable, error | Capacity plus continuous-availability coverage. |
| capacity_bytes | reported/partial only | positive U64 integer string | `statvfs` total for the filesystem containing the existing job workspace. |
| issues | partial/unavailable/error only | 1–4 sorted unique values | Contextual cause. |

Free bytes, filesystem class, and absolute path are not retained. Storage byte-seconds use the
participant start-to-final interval exactly once. `reported` requires NVFlare to establish
continuous workspace availability over that interval. If continuity is uncertain but a numeric
proxy remains usable, storage is `partial`; otherwise it is unavailable/error. V1 deliberately has
no storage sub-windows.

## Attempt end

An embedded `end` contains `closed_at` and one reason. A standalone `attempt_end` repeats
`opened_at` so an end-only launch failure is self-contained:

| reason | Meaning |
| --- | --- |
| released | NVFlare ended the measurement period normally. |
| failed | The measurement period ended after a failure. |
| terminated | The measurement period ended after cancellation, preemption, or administration. |
| launch_failed | NVFlare knows the period bounds, but no start capacity exists; start/final are forbidden. |
| reconfigured | NVFlare ended the period after observing a capacity change. This does not imply another period. |

There is no return code because the contract measures a period, not an OS-process outcome.
`opened_at` and `closed_at` come from the same NVFlare clock, and every duration uses exactly that
interval. Failed or terminated work does not by itself make
capacity-time partial when matching start/final evidence exists. `launch_failed` still contributes
measurement time but degrades compute totals because capacity is unknown.

## Participant terminal facts

`participant_final` contains storage plus one retained-content observation and one F3 observation.
These facts are never repeated in attempt finals.

### Retained content

Reported/partial retained content has 0–4,096 sorted unique entries. Each entry requires a
normalized ASCII POSIX-relative `relative_path` of 1–512 bytes, U128 string `size_bytes`, and a
64-character lowercase hexadecimal `sha256`. Reported empty entries means exact zero. Partial
keeps a verified subset and applicable issues; unavailable/error has no entries. Total bytes are
derived from entry sizes.

### F3

Reported/partial F3 requires exactly three counter pairs. Every pair contains U128 strings
`payload_bytes` and `messages`; zero messages requires zero bytes.

| Counter | Meaning |
| --- | --- |
| remote_accepted | Remote application payload accepted before NVFlare closes the counters; the primary F3 total. |
| local_delivered | Direct/local application delivery, kept separate. |
| remote_failed_before_acceptance | Remote traffic that failed before sender acceptance. |

NVFlare closes all three counters in one operation before serializing `participant_final`.
Callbacks that finish later do not change the stored totals. Job code cannot
mark traffic as excluded. The resource-summary message is excluded inside
NVFlare and is not embedded in the summary itself.
The included classes are `task_request`, `task_response`, `task_result`, `job_application`, and
`job_stream_data`; `job_stream_control`, `bulk_envelope`, `workspace_transfer`,
`platform_control`, `log_export`, unknown classes, and summary publication are excluded.

## Participant summary

The summary requires participant `start`, participant `final`, and `attempts`. Participant final
must not precede participant start. Every attempt `opened_at` and `end.closed_at` must lie inside
this lifecycle.

`attempts` contains 0–4,096 unique entries sorted by `attempt_id`. Zero attempts authoritatively
means zero measurement periods and derives reported zero CPU, memory, and GPU time. An end-only
`launch_failed` attempt instead makes those compute totals unavailable unless another
attempt contributes a numeric value, in which case they are partial.

Each attempt always has `attempt_id`, `environment_key`, `opened_at`, and `end.closed_at/reason`.
Except for `launch_failed`, it also requires capacity-only `start`; capacity-only `final` is
optional. Resource time always uses the half-open `[opened_at,closed_at)` measurement period;
final is stability evidence only. Missing final or changed numeric capacity makes the affected
total partial. Attempts with the same environment key may be sequential but cannot overlap.
Different environment keys may overlap. `reconfigured` is descriptive only. It does not require
or imply a successor period.

## Compact totals

The same totals shape appears on every accepted participant entry and once at job level:

| Member | Required when reported/partial | Unit and grouping |
| --- | --- | --- |
| cpu | status, groups | `unit_seconds`, grouped by optional model and architecture. |
| memory | status, byte_seconds | memory byte-seconds across measurement periods. |
| storage | status, byte_seconds | participant-lifetime filesystem-capacity byte-seconds. |
| gpu | status, groups | `instance_seconds`, grouped by kind and optional metadata. |
| retained_content | status, bytes | one terminal registered-content byte count. |
| f3 | status, remote_accepted | one participant-lifetime primary counter pair. |

Totals statuses are `reported`, `partial`, or `unavailable`. Reported/partial requires the numeric
field or group array; unavailable forbids it. Totals contain no issues because status derives from
site and participant-status facts. CPU and GPU groups are consolidated, unique, and sorted. Empty reported
groups are valid zero.

## Resource summary and expected participant list

The expected participant list has 1–10,000 unique entries sorted by role, participant ID, then
participant key.
Expected members come from authenticated job deployment/selection state independently of
resource-report arrivals. At cutoff, every expected member is classified exactly once as
`accepted`, `missing`, `invalid`, or `disabled`; the final list does not change.
Every entry contains `participant_id`, `participant_key`, `role`, and `status`. Missing/disabled
entries contain only those fields. Invalid entries add trusted `received_at` and issues. Accepted
entries add:

| Field | Type/bound | Rule |
| --- | --- | --- |
| received_at | UTC timestamp | No later than `report_cutoff_at`. |
| summary_sha256 | 64 lowercase hexadecimal characters | Digest of accepted participant bytes. |
| resource_window_seconds | canonical U128 decimal seconds, at most 9 fractional digits | Sum of all measurement-period durations, including launch failures; it may exceed elapsed site-run time when periods use different scopes. |
| totals | compact totals | Recomputed from referenced lifecycle facts. |

Job totals are deterministic sums of accepted participant totals. Missing, invalid, or disabled members
make an otherwise numeric job total partial; no numeric contribution makes it unavailable. Counts,
coverage, contributors, warnings, and qualifications derive from the expected participant list and
are not stored.

## Formula and bounds

```text
attempt CPU time    = attempt-start CPU units × (closed_at - opened_at)
attempt memory time = attempt-start memory bytes × (closed_at - opened_at)
attempt GPU time    = attempt-start GPU instances × (closed_at - opened_at)
storage time        = participant-start storage bytes × (participant-final - participant-start)
```

Products round at most once to nine fractional digits using round-half-even before summation.
All U32/U64/U128 bounds are inclusive. Booleans are never integers.

| Structural item | Bound |
| --- | ---: |
| JSON nesting | 32 levels |
| Attempts per participant | 0–4,096 |
| GPU/CPU groups per applicable array | 0–4,096 |
| Expected participants | 1–10,000 |
| Retained entries | 0–4,096 |
| Issues per list | 1–4 when present |
| Hardware-model label | 128 ASCII characters |
| Relative path | 512 bytes in the safe ASCII grammar |

The 4,096-attempt bound accommodates jobs with many measurement periods while preventing an
unbounded array. It is an implementation-capacity candidate, not a promise that
4,096 maximally sized attempts fit: the independent 64 MiB participant-summary limit remains
decisive.

## Serialized record bounds

| Record kind | Maximum bytes |
| --- | ---: |
| attempt_start | 1 MiB |
| attempt_final | 1 MiB |
| attempt_end | 64 KiB |
| participant_start | 64 KiB |
| participant_final | 1 MiB |
| participant_summary | 64 MiB |
| resource_summary | 64 MiB |
| manifest | 4 MiB |

## Privacy exclusions

Allowed data is restricted to authenticated product identity, job-scoped HMAC keys, normalized
hardware display metadata, normalized registered relative paths, numeric facts, statuses, and
issues. Optional CPU/GPU model metadata may be omitted without changing numeric status. This
feature adds no model-publication setting.

Forbidden data includes environment/argument dumps, raw CUDA masks, GPU UUID/PCI identity, CPU
serials/flags/topology, host/IP/PID/container/pod/scheduler identity, absolute cgroup/workspace
paths, credentials, secrets, tokens, message payloads/topics, raw exceptions, and tracebacks.
