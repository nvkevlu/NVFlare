# Canonical v1 field catalog

This is the human index for resource_stats_v1.schema.json. The JSON Schema and contract_v1.py are
normative; this file makes required fields, conditional presence, units, bounds, and privacy
rules easier to review. Every object rejects unknown fields, and no measured numeric fact uses
JSON null or a JSON number.

## Top-level records

| Record | Always required | Conditional fields |
| --- | --- | --- |
| attempt_start | schema_version, kind, job_id, participant_id, attempt_id, environment_key, observed_at, collection_state | capacity is required when enabled and forbidden when disabled. |
| attempt_final | schema_version, kind, job_id, participant_id, attempt_id, environment_key, observed_at, capacity, retained_content, f3 | None. A reconstructed attempt accepts it only with a valid enabled start. |
| attempt_parent_exit | schema_version, kind, job_id, participant_id, attempt_id, environment_key, observed_at, outcome | return_code depends on outcome. |
| participant_summary | schema_version, kind, job_id, participant_key, attempts | Each attempt has optional start/final and required exit; terminal content is inside final. |
| resource_summary | schema_version, kind, job_id, report_cutoff_at, finalized_at, roster, totals | Accepted entries add receipt/digest/duration/totals; invalid entries add receipt/issues. |
| manifest | schema_version, kind, job_id, entries | None. |

Each record has exact schema_version \"1.0\" and its namespaced
nvflare.resource_stats.* kind. This candidate has no optional extension bag; unknown fields,
kinds, and versions are rejected.

## Common identity and time

| Field | Type and serialized rule | Purpose |
| --- | --- | --- |
| job_id | 1–128 ASCII characters; alphanumeric first, then alphanumeric, dot, underscore, or hyphen | Authenticated job identity. |
| participant_id | 1–128 ASCII alphanumeric/underscore/hyphen characters; alphanumeric first | Roster/display identity; absent from participant-summary records because their job-scoped key is the archive identity. |
| attempt_id | exactly 32 lowercase hexadecimal characters | Parent-minted random 128-bit attempt identity. |
| environment_key | \"sha256-\" plus 64 lowercase hexadecimal characters | Job-scoped platform HMAC for the execution environment; prevents same-environment duplicate rank reports. |
| participant_key | same sha256-prefixed form | Job-scoped platform HMAC used in the participant archive path and roster. |
| observed_at | calendar-valid UTC RFC 3339 ending in Z, with zero to nine fractional digits | The one observation time on each lifecycle fact. |
| report_cutoff_at | same timestamp form | Fixed last acceptance point for participant summaries. |
| finalized_at | same timestamp form, not earlier than the cutoff | Time the server froze/materialized the job summary. |
| received_at | same timestamp form, not later than the cutoff | Trusted server receipt time for an accepted or invalid participant candidate. |

Keys are HMAC outputs, not plain hashes of enumerable labels. Identity text in JSON is still
checked against authenticated launcher/roster context; shape validation alone is not identity
authentication.

## Attempt start and typed capacity

collection_state is exactly enabled or disabled. Enabled requires capacity with exactly cpu,
memory, storage, and gpu. Disabled forbids capacity and a child final, avoiding repeated disabled
objects.

Point-capacity objects use status reported, unavailable, or error:

- reported requires its value/evidence fields and forbids issues;
- unavailable or error forbids numeric/evidence/model fields and requires applicable issues; and
- an observed zero is explicit; omission never means zero except for a GPU kind inside a
  successfully reported inventory.

### CPU

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, unavailable, error | Point-capacity state. |
| visible_units | reported only, required | positive canonical decimal string, maximum 1,048,576, at most 9 fractional digits | Minimum applicable selector evidence. |
| evidence | reported only, required | closed object | Contains strong selector fields or the one fallback field. |
| evidence.affinity_count | optional strong evidence | positive U32 integer string | Logical CPUs visible through process affinity. |
| evidence.cpuset_count | optional strong evidence | positive U32 integer string | Logical CPUs in the effective cgroup cpuset. |
| evidence.quota_units | optional strong evidence | positive canonical CPU-unit decimal, same bound as visible_units | Finite effective quota divided by period before persistence. |
| evidence.online_count | fallback only | positive U32 integer string | Required only when no affinity/cpuset/quota evidence is usable; cannot coexist with those fields. |
| model | optional on reported | normalized display-safe ASCII, at most 128 characters | Present only when all affinity-visible processors normalize to one model and site policy permits disclosure. |
| architecture | optional on reported | normalized ASCII label, 1–32 characters | Optional metadata; it does not affect visible units. |
| issues | unavailable/error only, required | 1–4 unique sorted issue values | Contextual cause; see CODE_CATALOG.md. |

Raw quota_us and period_us are internal observations, not canonical fields. For example,
150000/100000 is stored as quota_units \"1.5\". A heterogeneous visible processor set omits
model without changing status.

### Memory

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, unavailable, error | Point-capacity state. |
| visible_bytes | reported only, required | positive U64 integer string | Minimum finite evidence value. |
| evidence.physical_bytes | optional reported evidence | positive U64 integer string | Physical RAM, excluding swap. |
| evidence.cgroup_limit_bytes | optional reported evidence | positive U64 integer string | Effective finite cgroup limit; unlimited is omitted. |
| issues | unavailable/error only, required | 1–4 unique sorted issues | Contextual cause. |

Reported memory requires at least one evidence value. Physical-only evidence is a host-visible
fallback; with both values, visible_bytes equals their minimum.

### Storage

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, unavailable, error | Point-capacity state. |
| capacity_bytes | reported only, required | positive U64 integer string | statvfs total for the filesystem containing the job-run directory. |
| issues | unavailable/error only, required | 1–4 unique sorted issues | Contextual cause. |

Free/available bytes, filesystem class, and observed absolute path are not retained.

### GPU

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, unavailable, error | reported means CUDA-runtime enumeration succeeded. |
| cuda_mask_present | required | boolean | Presence diagnostic only; raw mask and token count are forbidden. |
| groups | reported only, required | 0–4,096 sorted unique GPU groups | Empty is a successfully observed zero. |
| issues | unavailable/error only, required | 1–4 unique sorted issues | Contextual cause. |

GPU group fields:

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| kind | required | full_gpu or mig_compute_instance | Defines the entity and the unit of count/time. |
| count | required | positive U32 integer string | No stored zero group; absence in a reported inventory is zero for that kind. |
| model | optional | normalized display-safe ASCII, at most 128 characters | From a CUDA-enumerated device; optional NVML refinement. |
| memory_bytes | optional | positive U64 integer string | Bytes per entity in the group. |
| mig_profile | MIG group only, optional | normalized ASCII profile, at most 32 bytes | Forbidden on full_gpu. |

Group identity is kind plus optional model, memory, and MIG profile. Duplicates are forbidden and
groups are deterministically sorted. The sum of all group counts must also fit U32. NVML metadata
cannot add a group or change count authority.
Site suppression merges otherwise-identical unlabeled groups. Full GPU and MIG counts are never
combined.

## Attempt final

attempt_final repeats the common identity, has one final observed_at, and requires a full capacity
object under the same typed rules as startup. Its retained_content and f3 facts share that terminal
cutoff. It contains no start timestamp, duration, provisional rollup, trust object, warning, or
revision.

### Retained content

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, partial, unavailable, error | partial keeps a verified subset; unavailable/error has no entries. |
| entries | reported/partial only, required | 0–4,096 sorted unique entries | Empty reported entries means exact zero retained bytes. |
| issues | partial/unavailable/error only, required | 1–4 unique sorted issues | Contextual source/coverage cause. |

Each entry requires:

| Field | Type/bound | Rule |
| --- | --- | --- |
| relative_path | normalized safe ASCII POSIX-relative path, 1–512 bytes | No absolute path, traversal, dot/empty segment, or trailing slash; unique and sorted. |
| size_bytes | U128 integer string | Exact descriptor size of the frozen regular registered file. |
| sha256 | exactly 64 lowercase hexadecimal characters | Digest of the accepted file bytes. |

There is no artifact ID or stored retained-byte total. The total derives exactly from size_bytes.

### F3

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, partial, unavailable, error | One terminal status for the F3 observation. |
| cutoff_sequence | reported/partial only, required | U128 integer string | Last accepted-event sequence included by the fixed cutoff. |
| remote_accepted | reported/partial only, required counter pair | U128 payload_bytes and messages | The only primary F3 total. |
| local_delivered | reported/partial only, required counter pair | same | Direct delivery remains separate. |
| remote_failed_before_acceptance | reported/partial only, required counter pair | same | Failure before sender acceptance. |
| late_after_cutoff | reported/partial only, required counter pair | same | Excluded post-cutoff events. |
| summary_excluded | reported/partial only, required counter pair | same | Publication traffic excluded through a platform-owned mechanism. |
| issues | partial/unavailable/error only, required | 1–4 unique sorted issues | Counter/coverage/source cause. |

Every counter pair contains payload_bytes and messages. Zero messages requires zero bytes.
cutoff_sequence zero requires all pre-cutoff buckets to be zero; any positive pre-cutoff message
count requires a positive cutoff. Fixed traffic classes and exclusion mechanisms are contract
rules, not stored fields.

## Parent exit

The standalone parent-exit record keeps outcome beside observed_at; the nested attempt exit uses
the same flattened fields:

| outcome | return_code |
| --- | --- |
| finished_ok | required signed 32-bit JSON integer, exactly 0 |
| finished_error | required signed 32-bit JSON integer, nonzero |
| terminated | required signed 32-bit JSON integer, nonzero |
| launch_failed | forbidden |

The enclosing observed_at is the trusted parent exit time. There is no child-final-present flag,
end-basis label, or invented resource observation.

## Participant summary

participant_summary requires job_id, participant_key, and 1–128 unique, deterministically ordered
attempts. It intentionally omits participant display ID, role, summary ID/revision, created time,
duration, and resource-time totals.

Each attempt requires:

| Field | Presence | Contents |
| --- | --- | --- |
| attempt_id | required | Unique 32-hex attempt ID. |
| environment_key | required | Job-scoped HMAC execution-environment key. |
| start | optional | An enabled observed_at/collection_state/capacity body. Disabled standalone starts are represented by a disabled roster entry, not an accepted participant summary. |
| final | optional | observed_at, capacity, retained_content, and f3. |
| exit | required | observed_at, outcome, and return_code when required by outcome. |

Final requires an enabled start. A start present in an accepted participant summary must be
enabled. Identity is inherited from the enclosing participant/attempt.
Timestamp order is start <= final <= exit; without final it is start <= exit. A launch failure may
have only the required exit. Attempts under the same environment key may be sequential but cannot
overlap. Bundle validation applies that half-open interval rule across participant files,
rejecting concurrent rank reports without confusing a later retry with a duplicate.

## Compact totals

The same flat totals shape appears on every accepted roster entry and once at job level:

| Member | Required contents when reported/partial | Unit and grouping |
| --- | --- | --- |
| cpu | status, groups | Each group has unit_seconds plus optional model and architecture; CPU-unit-seconds grouped by that metadata. |
| memory | status, byte_seconds | Memory byte-seconds. |
| storage | status, byte_seconds | Filesystem-capacity byte-seconds. |
| gpu | status, groups | Each group has kind, instance_seconds, and optional model, memory_bytes, MIG-only profile. |
| retained_content | status, bytes | Derived registered retained bytes. |
| f3 | status, remote_accepted | Primary remote-accepted payload_bytes and messages only. |

Totals statuses are reported, partial, or unavailable. Reported/partial requires its numeric
field or groups and unavailable forbids it. Totals contain no issues: status follows from the
participant lifecycle facts and frozen roster. CPU and GPU groups are sorted/unique and exact sums
by their metadata keys. A reported GPU total may have an empty group array for zero.

## Resource summary and roster

resource_summary requires flat job_id, report_cutoff_at, finalized_at, roster, and totals.
finalized_at is not earlier than the cutoff. The roster has 1–10,000 unique entries and is sorted
by role (client before server), then participant ID, then participant key.

Every roster entry requires participant_id, participant_key, role, and status. Missing/disabled
entries contain only those four facts. Invalid entries additionally require the trusted
received_at and applicable issues describing why the received candidate was rejected. Accepted
entries instead additionally require:

| Field | Type/bound | Rule |
| --- | --- | --- |
| received_at | UTC timestamp | No later than report_cutoff_at. |
| summary_sha256 | 64 lowercase hexadecimal characters | Digest of the accepted participant bytes. |
| observation_seconds | canonical U128 decimal seconds, at most 9 fractional digits | Exact sum of that participant's derived attempt intervals. |
| totals | compact totals object | Recomputed from the referenced participant lifecycle facts. |

The first valid authenticated summary received by cutoff wins. Identical digest replay is
idempotent; a conflicting digest is rejected. An invalid candidate does not reserve the roster
entry.

Job totals are recomputed from accepted roster totals. Missing, invalid, or disabled roster
members make any otherwise numeric job total partial. With no numeric contribution, the total is
unavailable. Roster counts, coverage, contributor lists, warnings, and qualifications are derived
and are not stored.

## Manifest

manifest requires 1–10,001 sorted unique entries:

| Field | Type/bound | Rule |
| --- | --- | --- |
| relative_path | resource_summary.json or participants/<participant_key>.json | Exactly the summary plus one file per accepted roster member. |
| sha256 | 64 lowercase hexadecimal characters | Must match the referenced canonical bytes. |

record_kind and byte_count are deliberately absent. Kind derives from path/parsed content and the
actual file length is already available; the digest detects content mismatch.

## Formula and numeric bounds

Attempt interval is derived from start observed_at to final observed_at, or to parent-exit
observed_at when no final exists. Resource time is startup capacity multiplied by this interval.
Missing or numerically changed final capacity makes the derived result partial; optional metadata
change alone does not.

Decimal products round at most once to nine fractional digits using round-half-even, then remove
trailing zeros. All U32/U64/U128 limits are inclusive. Booleans are never accepted as integers.

| Structural item | Bound |
| --- | ---: |
| JSON nesting | at most 32 levels |
| Attempts per participant | 1–128 |
| GPU/CPU groups per applicable array | 0–4,096 |
| Frozen-roster participants | 1–10,000 |
| Retained entries | 0–4,096 |
| Issues per list | 1–4 when present |
| Hardware model label | at most 128 ASCII characters |
| Relative path | at most 512 bytes in the safe ASCII path grammar |

## Serialized record bounds

Limits are checked on received UTF-8 bytes before parsing and aggregation:

| Record kind | Maximum bytes |
| --- | ---: |
| attempt_start | 256 KiB |
| attempt_final | 1 MiB |
| attempt_parent_exit | 64 KiB |
| participant_summary | 64 MiB |
| resource_summary | 64 MiB |
| manifest | 4 MiB |

## Privacy exclusions

Allowed data is restricted to authenticated product identity, job-scoped HMAC keys, normalized
hardware display metadata, normalized registered relative paths, numeric facts, statuses, and
issues.

Forbidden data includes environment/argument dumps, raw CUDA masks, GPU UUID or PCI identity,
CPU serials/flags/topology, host/IP/PID/container/pod/scheduler identity, absolute cgroup or
workspace paths, credentials, secrets, tokens, message payloads/topics, raw exceptions, and
tracebacks. Site policy may suppress optional CPU/GPU metadata without changing numeric status.
