# Canonical resource-statistics contract v1

This directory is the single candidate-v1 contract for Phase 1 resource statistics. It supersedes
the exploratory shapes under `../examples/` and `../generated/`.

Conformance requires both machine-readable parts:

- `resource_stats_v1.schema.json` is the authoritative Draft 2020-12 shape, type, nullability,
  enum, and structural-bound definition.
- `contract_v1.py` enforces duplicate-key and byte/depth limits, decimal bounds and formulas,
  selector evidence, timestamp/identity relationships, aggregate arithmetic, replay rules, and
  bundle integrity that JSON Schema alone cannot express.

`FIELD_CATALOG.md` is the human field/unit/bound index. `CODE_CATALOG.md` is the status, issue,
roster, and lifecycle-state index. The files under `golden/v1/` are normative examples.

A production reader must bound received UTF-8 bytes, reject duplicate JSON keys, validate against
the JSON Schema, run the cross-record validator with authenticated platform context, and only then
aggregate or display the record. A digest proves byte identity, not the truth of a child claim.

## Version and record kinds

Every record has exact `schema_version: "1.0"`, rejects unknown fields, and uses one namespaced
kind:

| Kind | Purpose |
| --- | --- |
| `nvflare.resource_stats.attempt_start` | Child startup capacity self-report after sanitized bootstrap. |
| `nvflare.resource_stats.attempt_final` | Child final capacity, retained-content, and F3 self-report. |
| `nvflare.resource_stats.attempt_parent_exit` | Parent-observed process exit; never a synthesized final sample. |
| `nvflare.resource_stats.participant_summary` | Detailed accepted lifecycle facts for one participant's distinct attempts. |
| `nvflare.resource_stats.resource_summary` | Frozen server roster with compact participant and job totals. |
| `nvflare.resource_stats.manifest` | Canonical path/digest inventory for summary and accepted participant files. |

The contract is still an unpublished prototype, so the accepted incompatible simplification keeps
the candidate version `"1.0"`. After release, additive or incompatible changes require an explicit
supported version transition; readers never silently reinterpret old bytes.

## Lifecycle and trust model

Attempt start, final, and parent-exit records share job, participant, attempt, and
`environment_key` identity plus one `observed_at` timestamp. Role is absent from lifecycle and
participant records; it is stored once in the server's frozen roster.

Collection is enabled or disabled once for the start. An enabled start contains a complete typed
capacity container with CPU, memory, storage, and GPU objects. A disabled start has no capacity or
final record. Parent exit remains required for successful, failed, terminated, launch-failed,
crashed, and collection-disabled attempts.

A valid normal final keeps a second full capacity observation plus retained content and F3 facts.
This final is audit/change-detection evidence, not a new resource-time basis. If the child crashes
or its final is absent/invalid, the parent records only the exit and never invents final capacity,
retained files, or F3 counters.

Start/final payloads are `child_self_reported` by their record kind. The parent authenticates the
expected identity and writes accepted bytes once into durable storage outside the child-writable
job area. Parent exit is parent-observed. Server summaries are server-derived. Those facts follow
from trusted transport/storage context; a payload `trust` claim was deliberately removed.

The production launcher must use a platform-owned sanitized bootstrap before custom imports and
must propagate the parent-minted attempt ID through every explicit launcher argument allowlist.
Capturing merely before `worker_process.main()` is not sufficient if `PYTHONPATH` can import job
custom code first.

## Typed capacity objects

Typed resources replace generic metric arrays. Field names and record location define the unit,
meaning, and authority; the record does not repeat unit, basis, scope, sharing, coverage, source,
or caveat strings.

### CPU

A reported CPU object contains positive `visible_units` and normalized evidence. Strong evidence
may include positive `affinity_count`, `cpuset_count`, and `quota_units`; visible units equal their
minimum. If none is available, positive `online_count` is the explicit host-visible fallback and
equals visible units. Raw quota/period microseconds are probe-internal: for example,
`150000 / 100000` is persisted only as `quota_units: "1.5"`.

Optional normalized `model` and `architecture` do not affect count authority. Report a CPU model
only when every affinity-visible processor normalizes to the same value. A heterogeneous set or a
site suppression policy omits metadata without downgrading a reported capacity value.

### Memory and storage

Reported memory `visible_bytes` equals the smaller finite value among its physical and effective
cgroup evidence; an unlimited cgroup value is omitted. Physical-only evidence is an explicit
host-visible fallback. Swap is excluded.

Reported storage `capacity_bytes` is total bytes from `statvfs` for the filesystem containing the
job run directory. Free space and filesystem class are not retained because they do not enter the
approved resource-time output. The absolute observed path is forbidden.

### GPU

A reported GPU inventory means CUDA-runtime enumeration succeeded. It contains only positive
groups, separated by `kind: full_gpu | mig_compute_instance`; an empty array is a successfully
observed zero. Absence of one kind inside a reported inventory means zero for that kind, so a
normal non-MIG client has no MIG group. When enumeration is unavailable or errors, no numeric
count is inferred.

`cuda_mask_present` is only a boolean diagnostic. The raw `CUDA_VISIBLE_DEVICES` string/token
count is forbidden and cannot establish a count. Optional model, per-entity memory, and MIG
profile apply only to CUDA-enumerated groups. NVML may refine metadata for matching devices but
cannot add groups or change counts. Full GPUs and MIG instances remain separate and are never
summed into one capacity value.

## Values, units, and large numbers

Measured/derived values use canonical non-negative decimal strings, never JSON numbers. Integer
strings have no sign, exponent, decimal point, or leading zero. Fractional strings use at most
nine fractional digits and no trailing fractional zero. Structural counts such as array lengths
and process return codes remain bounded JSON integers.

| Typed value | Unit | Bound |
| --- | --- | ---: |
| GPU group `count` | full-GPU or MIG instances by group kind | U32 |
| CPU `visible_units`, `quota_units` | CPU units | 1,048,576; at most 9 fractional digits |
| Memory/storage/model-memory values | bytes | U64 |
| `observation_seconds` | seconds | U128; at most 9 fractional digits |
| CPU group `unit_seconds` | CPU-unit-seconds | U128; at most 9 fractional digits |
| Memory/storage `byte_seconds` | byte-seconds | U128; at most 9 fractional digits |
| GPU group `instance_seconds` | full-GPU- or MIG-instance-seconds by kind | U128; at most 9 fractional digits |
| Retained/F3 bytes, F3 messages, sequence cutoff | bytes/messages/sequence | U128 |

String encoding is ordinary interoperability protection. One TiB for one day is
`94997804639846400` byte-seconds, already beyond JavaScript's largest safe integer. A lossy case,
`10000000000001 × 901 = 9010000000000901`, rounds if represented as an IEEE-754/JavaScript
`Number`. Decimal strings preserve both values exactly.

## Status and issue rules

Point capacity uses `reported | unavailable | error`; partial instantaneous capacity is not
meaningful. Retained content and F3 use `reported | partial | unavailable | error`. Materialized
participant/job totals use `reported | partial | unavailable`. Global policy uses one
`collection_state: enabled | disabled`.

Reported values contain required numeric facts and no `issues`. Partial values contain numeric
facts plus applicable issues. Unavailable/error values contain no numeric facts and identify why
through the bounded `issues` list. A real zero is the string `"0"` or, for GPU groups, a reported
empty array. Missing collection is never encoded as zero.

The exact context-neutral issue vocabulary is:

```text
not_bound  counter_gap  observation_incomplete  attribution_incomplete
unsupported  permission_denied  dependency_missing  malformed_source
```

Context comes from the containing typed object. There are no persisted caveat, warning,
qualification, source, or coverage code lists. Renderers derive stable explanatory notices from
schema version, type, status, roster, and observed facts.

## Resource-time formula

Participant files preserve lifecycle facts rather than child or participant resource-time
rollups. The parent/server derives each attempt interval using start and final `observed_at`; when
no valid final exists, it uses parent-exit `observed_at` and marks the result partial.

```text
resource time = startup runtime-visible capacity × derived interval seconds
```

Decimal multiplication rounds once, if needed, to nine fractional digits using round-half-even,
then removes trailing fractional zeros. The startup value remains the explicit proxy even if the
final differs; a changed numeric final makes the derived value partial. Optional metadata changes
alone do not constitute capacity change.

CPU resource time is grouped by optional normalized model and architecture. GPU resource time is
grouped by kind plus optional normalized model, per-entity memory, and MIG profile. Memory and
storage use byte-seconds. Suppressed/unknown metadata is an unlabeled group and does not invalidate
the numeric contribution.

An accepted roster entry stores `observation_seconds`, the checked sum of its derived attempt
intervals, as a query convenience. It is not a second clock measurement.

## Retained content and F3

Reported or partial retained content contains up to 4,096 sorted, unique entries with normalized
relative path, `size_bytes`, and SHA-256. Reported empty entries is exact zero. Total retained
bytes are derived from entry sizes. Files must come from a frozen platform registry, be regular
files, and be sized through an open descriptor; the workspace tree/archive is not scanned.

F3 reported/partial terminal data has `cutoff_sequence` and five required counter pairs:

| Bucket | Meaning |
| --- | --- |
| `remote_accepted` | Remote application payload accepted by transport before cutoff; the only primary total. |
| `local_delivered` | Direct/local delivery, deliberately separate. |
| `remote_failed_before_acceptance` | Remote attempt that failed before send acceptance. |
| `late_after_cutoff` | Post-cutoff event excluded from the frozen total. |
| `summary_excluded` | Summary-publication traffic excluded through a platform-owned non-spoofable path. |

Each pair contains U128 `payload_bytes` and `messages`; zero messages requires zero bytes. The
fixed traffic-class allowlist, sender acceptance boundary, and summary exclusion mechanism are
versioned integration rules rather than stored labels. Failure bytes are recorded only when the
post-serialization size is known; an earlier unknown failure affects status/coverage instead.

## Participant acceptance and server aggregation

A participant summary is one immutable detailed file containing distinct attempts. Every attempt
has an environment key, optional start/final facts, and required parent exit; retained content and
F3 exist only inside a valid final. A final requires an enabled start, and any stored start in an
accepted participant summary is enabled. A launch failure has only parent exit. Disabled
collection is represented by the frozen roster instead of an accepted participant file. No role,
summary ID/revision, duration, or resource-time total is duplicated there.

The first valid authenticated participant summary received by the server cutoff wins. An
identical digest retry is idempotent. A conflicting digest is rejected rather than treated as a
revision; an invalid candidate does not reserve the slot. Distinct job execution attempts remain
separate attempt entries inside the winning file.

The resource summary has job identity, report cutoff, finalization time, one frozen roster, and
typed job totals. Roster states are `accepted | missing | invalid | disabled`. Role occurs once per
roster entry. Accepted members also retain receipt time, participant digest, checked
`observation_seconds`, and compact totals. The job totals have the same shape. Roster gaps make an
otherwise numeric job result partial; no usable contributions produces unavailable.

Cross-job overlap remains intentional. Within a job, the validator rejects overlapping half-open
observation intervals that claim the same environment key across participant/rank files, while
allowing sequential retries. It does not infer physical ownership. A participant or job sum is
always a reported-visible proxy, never a capacity statement.

## Manifest and query copy

The server archive contains:

```text
resource_stats/
  resource_summary.json
  participants/<participant_key>.json
  manifest.json
```

The manifest contains sorted unique `relative_path`/`sha256` pairs: exactly
`resource_summary.json` plus one canonical participant path for every accepted roster entry.
Record kind and byte count are derived and therefore not stored. Bundle validation recomputes all
digests and membership.

The exact validated `resource_summary.json` bytes are the `RESOURCE_STATS` job-store query copy.
Storage uses one exact allowed component and narrow save/get APIs; a generic prefix allowlist must
not accidentally authorize arbitrary `RESOURCE_STATS_*` names.

## Privacy and structural limits

Allowed identity is limited to existing job/participant labels plus job-scoped HMAC-SHA-256
participant/environment keys. Optional hardware display labels are bounded and normalized.
Forbidden content includes environment/argument dumps, raw CUDA masks, GPU UUID/PCI identity,
CPU serials/flags/topology, host/IP/PID/container/pod/scheduler identity, absolute cgroup/workspace
paths, credentials/tokens, message payloads/topics, raw exceptions, and tracebacks.

Core structural limits are JSON depth 32, 128 attempts per participant, 10,000 roster entries,
4,096 CPU/GPU groups, 4,096 retained entries, four unique issues per list, 128 ASCII characters
per hardware-model label, and
512 UTF-8 bytes per normalized relative path. Received-byte limits are enforced before parsing;
see `FIELD_CATALOG.md` for the exact per-record values.

## Viewable golden records

- [attempt start](golden/v1/attempt_start.json),
  [collection disabled](golden/v1/attempt_start_disabled.json),
  [zero GPU](golden/v1/attempt_start_zero_gpu.json), and
  [CUDA unavailable](golden/v1/attempt_start_cuda_unavailable.json);
- [attempt final](golden/v1/attempt_final.json) and
  [attempt final with a large value](golden/v1/attempt_final_large_value.json);
- [parent exit after crash](golden/v1/parent_exit_crash.json);
- [participant summary](golden/v1/participant_summary.json) and
  [large-value participant](golden/v1/participant_summary_large_value.json);
- [resource summary](golden/v1/resource_summary.json) and
  [large-value resource summary](golden/v1/resource_summary_large_value.json); and
- [manifest](golden/v1/manifest.json).

The coherent [finalized job tree](golden/v1/finalized_job/) includes the canonical server archive,
byte-identical `RESOURCE_STATS` copy, and [human](golden/v1/finalized_job/cli/resources-all.txt) /
[JSON](golden/v1/finalized_job/cli/resources-all.json) CLI projections. The human renderer shows
MIG only when positive MIG instance-time is applicable; JSON retains typed MIG groups whenever
present. Optional model disclosure is demonstrated in the
[single-site hardware detail](golden/v1/finalized_job/cli/resources-site-1-details.txt).

Regenerate the tree from the repository root with:

```bash
python3 -B research/runtime_resource_proxy_prototype/schema/build_review_artifacts.py
```
