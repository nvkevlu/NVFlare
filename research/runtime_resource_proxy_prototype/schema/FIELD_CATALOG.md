# Canonical v1 field catalog

This is the human index for `resource_stats_v1.schema.json`. The JSON Schema
and `contract_v1.py` are normative. Every object is closed, unknown fields are
rejected, JSON `null` is never a substitute for omission, and measured numbers
are canonical decimal strings rather than JSON numbers.

## Public records

| Record | Required members | Purpose |
| --- | --- | --- |
| `participant_summary` | schema_version, kind, job_id, participant_name, reported_at, resource_time, workspace_filesystem, retained_content, f3 | One terminal report from one participant. |
| `resource_summary` | schema_version, kind, job_id, report_cutoff_at, finalized_at, participants, totals | Final server result for one job. |
| `study_summary` | schema_version, kind, selection, generated_at, coverage, jobs, totals | On-demand view over matching retained jobs; never archived as the study's history. |

Stored records use exact `schema_version: "1.0"` and their namespaced
`nvflare.resource_stats.*` kinds. There are no standalone collection
fragments. In particular, v1 has no public start, final, attempt, capacity
snapshot, environment-key, end-reason, or stability record.

The exact kinds are `nvflare.resource_stats.participant_summary`,
`nvflare.resource_stats.resource_summary`,
and `nvflare.resource_stats.study_summary`.

## Numeric serialization

| Form | Canonical encoding |
| --- | --- |
| Unsigned integer | `"0"` or 1–39 decimal digits with no leading zero. |
| Positive unsigned integer | 1–39 decimal digits, first digit nonzero. |
| Unsigned decimal | Canonical integer form plus at most 9 fractional digits; no trailing fractional zero. |
| Positive decimal | Same decimal form, but greater than zero. |

The semantic validator applies the stated U64/U128 domain bound in addition to
the lexical limit. Booleans and JSON numbers are never accepted as measured
numeric values.

## Common identity and time

| Field | Type and serialized rule | Purpose |
| --- | --- | --- |
| job_id | 1–128 ASCII characters; alphanumeric first, then alphanumeric, dot, underscore, or hyphen | Authenticated job identity. |
| participant_name | 1–128 ASCII characters; first character is alphanumeric, underscore, or hyphen; remaining characters are alphanumeric, underscore, dot, or hyphen | Existing trusted client-site or server participant identity and participant archive filename stem. |
| reported_at | calendar-valid UTC RFC 3339 ending in `Z`, with zero to nine fractional digits | Participant terminal serialization time. |
| report_cutoff_at | same timestamp form | Fixed last acceptance point for participant reports. |
| received_at | same timestamp form, no later than cutoff | Trusted server receipt time. |
| finalized_at | same timestamp form, not earlier than cutoff | Job-summary construction time. |
| generated_at | same timestamp form | Study-response generation time. |

The server records the existing registered site name for a client and the
configured server participant name for SP. It derives no resource-specific
pseudonym and sends no extra identity field in `START_JOB`. For a client
report, the server obtains the trusted name from the authenticated sender and
job context, requires the JSON field to match it, and checks that the trusted
name is a single safe archive path component before constructing the filename.
A syntactically valid name never authenticates itself.

The completion envelope carries the canonical participant-summary bytes. The
server compares those exact bytes directly for idempotent retry/conflict
detection. An accepted resource-summary row adds no receipt token.

## Participant summary

`participant_summary` is the only participant wire/storage record. It is
written once when that participant's part of the job ends.

| Field | Rule |
| --- | --- |
| schema_version | Exact `"1.0"`. |
| kind | Exact participant-summary kind. |
| job_id | Must match the authenticated selected completion-request context. |
| participant_name | Must match the authenticated expected participant name. |
| reported_at | Terminal report time. |
| resource_time | One compute status and accumulated numeric values. |
| workspace_filesystem | One independent terminal point observation. |
| retained_content | One independent terminal saved-result observation. |
| f3 | One independent set of finalized message counters. |

The report has no role; the server supplies it from trusted
expected-participant state. It has no attempt list, start/final pair, raw
measurement periods, or process outcome.

## Resource time

`resource_time.status` is the single compute-completeness decision for
measured time, CPU, memory, and GPU together.

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, partial, unavailable | Applies to the whole object. |
| issues | partial/unavailable only | 1–4 sorted unique issue codes | Explains incomplete/no usable compute data. |
| measured_seconds | reported; optional on partial | unsigned decimal, at most 9 fractional digits | Time covered by the internal accumulator. |
| cpu | reported; optional on partial | CPU resource-time object | No nested status. |
| memory | reported; optional on partial | Memory resource-time object | No nested status. |
| gpu | reported; optional on partial | GPU resource-time object | No nested status. |

`reported` requires all four numeric members and forbids issues. `partial`
requires issues and at least one numeric member. `unavailable` requires issues
and forbids every numeric member. The participant does not publish the private
intervals used to form these values.

### CPU resource time

CPU contains a `groups` array. Each group contains:

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| unit_seconds | required | unsigned decimal, at most 9 fractional digits | Selected visible CPU units multiplied by internally covered seconds. |
| model | optional | normalized display-safe ASCII, at most 128 characters | Present only for a homogeneous visible CPU set. |
| architecture | optional | normalized ASCII, 1–32 characters | Display metadata; not numeric authority. |

The array contains 1–4,096 groups. Groups are consolidated, unique, and
sorted by optional model/architecture.
The private collector selects CPU units as the minimum applicable value from
process affinity, effective cgroup cpuset, and finite quota. Online CPU count
is fallback only. Raw affinity, cpuset, quota, period, and online-count evidence
is not part of the terminal schema.

### Memory resource time

Memory contains only `byte_seconds`, an unsigned decimal string with at most
nine fractional digits. Internally, selected memory is the minimum finite
value from the effective cgroup limit and process-visible physical memory.
Unlimited values are ignored and swap is excluded. Raw source evidence is not
persisted.

### GPU resource time

GPU contains a sorted, unique `groups` array. Each group contains:

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| kind | required | full_gpu or mig_compute_instance | Keeps full-GPU and MIG time separate. |
| instance_seconds | required | positive decimal, at most 9 fractional digits | Runtime-visible instances multiplied by internally covered seconds. |
| model | optional | normalized display-safe ASCII, at most 128 characters | Hardware display metadata. |
| memory_bytes | optional | positive U64 integer string | Runtime-reported memory per visible entity represented by the group. |
| mig_profile | optional for MIG only | normalized MIG profile, at most 32 characters | Forbidden on full-GPU groups. |

CUDA Runtime enumeration is the only numeric GPU-count authority. NVML may
enrich CUDA-validated devices but cannot add one. The raw
`CUDA_VISIBLE_DEVICES` value and even a boolean derived from it are diagnostic
inputs, not terminal fields. Different optional metadata creates separate
groups. Empty reported `groups` is authoritative zero GPU time. MIG fields are
absent when inapplicable.

## Resource-time arithmetic

For every private interval whose selected capacity is known:

~~~text
CPU time    += visible CPU units × interval seconds
memory time += visible memory bytes × interval seconds
GPU time    += visible GPU instances × interval seconds
~~~

Each product is rounded at most once to nine fractional digits using
round-half-even before summation. The current adapter opens one private
process-lifetime interval. A future platform-owned resource-change event may
close that interval and open another without changing the public record. One
terminal capacity snapshot must never be multiplied by the whole job duration.

## Workspace filesystem

`workspace_filesystem` is one terminal point observation:

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, unavailable, error | Independent point-observation state. |
| capacity_bytes | reported only | positive U64 integer string | Total visible capacity of the filesystem containing the existing job workspace. |
| issues | unavailable/error only | 1–4 sorted unique issue codes | Cause in this typed context. |

The collector calls the ordinary-user filesystem API on the existing job
workspace only. It does not enumerate or sum mounts. Free bytes, filesystem
class, and absolute path are not stored. The value is not usage, allocation,
billable storage, job-owned storage, or storage time. It is never included in
participant, job, or study additive totals.

## Retained content

| Field | Presence | Type/bound | Rule |
| --- | --- | --- | --- |
| status | required | reported, partial, unavailable, error | Independent saved-result state. |
| bytes | reported/partial only | U128 integer string | Complete total or exact observed subtotal. |
| issues | partial/unavailable/error only | 1–4 sorted unique issue codes | Cause in this typed context. |

Reported bytes require a complete bounded result set already known to NVFlare;
reported zero means that known set is empty. Partial bytes are only the exact
subtotal for the successfully observed subset. `unavailable/not_bound` is used
when no authoritative bounded set exists. Filenames and content hashes are not
stored.

## F3

Reported/partial F3 requires exactly three counter pairs. Every pair contains
U128 integer strings `payload_bytes` and `messages`; zero messages requires
zero bytes.

| Counter | Meaning |
| --- | --- |
| remote_accepted | Remote application payload accepted before counters close; primary F3 total. |
| local_delivered | Direct/local application delivery, kept separate. |
| remote_failed_before_acceptance | Remote traffic that failed before sender acceptance. |

`status` is reported, partial, unavailable, or error. Reported forbids issues;
partial requires counters and issues; unavailable/error requires issues and
forbids counters. Platform code closes all counters before terminal report
serialization. Later callbacks do not alter the record.

Included classes are task request, task response, task result, job application,
and attributable job-stream data. Control, workspace transfer, log export,
unknown traffic, and resource-report traffic are excluded. See
[CODE_CATALOG.md](CODE_CATALOG.md) for the exact semantic boundary.

## Resource summary and expected participants

`participants` is the full expected set, not the set that reported. It has
1–10,000 unique entries sorted by role, then participant name. Every entry
contains `participant_name`, `role`, and `status`.

| Participant status | Additional fields |
| --- | --- |
| accepted | received_at, resource_time, retained_content, f3 |
| invalid | received_at, issues |
| missing | none |
| disabled | none |

For `invalid`, `issues` is exactly `["malformed_source"]`; authentication,
late arrival, omission, and server faults do not become participant-invalid.

Accepted participant values are validated and copied from the exact accepted
terminal report. The server cannot reconstruct `resource_time` because private
intervals are not public. Workspace-filesystem capacity is deliberately not
copied into the expected-participant entry or job totals; it remains available
in the participant file for site detail.

Job `totals` contains:

| Member | Numeric content |
| --- | --- |
| resource_time | measured_seconds, CPU unit-seconds groups, memory byte-seconds, GPU instance-seconds groups |
| retained_content | saved-result bytes |
| f3 | additive `remote_accepted` counter pair |

Aggregate statuses are reported, partial, or unavailable. Aggregate
`resource_time` uses the same one issue list when partial/unavailable;
retained-content and F3 totals contain no issues. The server sums accepted
numeric contributions and derives status from expected-participant coverage
and accepted typed statuses. CPU/GPU groups are consolidated and sorted.
Missing data is not zero.

## Study query response

The JSON response contains:

| Field | Shape and rule |
| --- | --- |
| schema_version, kind | Exact `"1.0"` and `nvflare.resource_stats.study_summary`. |
| selection.study_name | Requested existing study context. |
| generated_at | Server response-generation time. |
| coverage | selected_jobs, included_jobs, unavailable_jobs, and nonterminal_jobs counts. |
| jobs | Zero to 10,000 rows, unique and sorted by `job_id`, one for every retained job returned by the query's one job-store scan. |
| totals | Additive resource_time, retained_content, and F3 totals only. |

`selection.study_name` reuses NVFlare's existing study-name rule: 1–63
lowercase ASCII characters, alphanumeric at both ends, with lowercase
alphanumeric, underscore, or hyphen inside. It names the existing study
authorization/selection context; it is not a new resource-statistics
configuration field.

Each coverage count is a U128 integer string. The semantic contract requires
`selected_jobs` to equal the number of rows and the other three counts to be a
complete partition of those rows.

Each job row has the job ID, bounded underlying NVFlare `job_status`, and
`resource_data` classification:

`job_status` is 1–64 display-safe ASCII characters, begins alphanumeric, and
then permits alphanumeric, space, dot, underscore, colon, slash, plus, or
hyphen. It records the underlying NVFlare lifecycle value and is deliberately
separate from resource-data availability. `included` and `unavailable` rows
require a value beginning `FINISHED:` or the exact legacy value `FINISHED_OK`,
`FINISHED_EXCEPTION`, `ABORTED`, `ABANDONED`, or `FAILED`; `nonterminal` rows
forbid those terminal values.

| resource_data | Additional fields and effect |
| --- | --- |
| included | Validated job totals; contributes to study totals. |
| unavailable | no numeric totals; terminal job without a readable valid resource summary. |
| nonterminal | no numeric totals; excluded because the job was not terminal when its scanned status was recorded. |

Coverage counts exactly match the rows. Study totals use the same group
consolidation, exact arithmetic, and aggregate-status rules as job reduction.
They sum included rows only. Any unavailable or nonterminal row makes an
otherwise numeric aggregate partial. Study totals never include
`workspace_filesystem`. The response is generated on demand from matching jobs
that normal retention still keeps; it is not written back as a durable study
record.

## Final archive bundle

The server writes one participant file for every accepted expected
participant, then atomically writes `resource_summary.json` last in the live
run directory as the publication marker. The normal workspace archiver may
order ZIP members differently; readers do not use member order.

The reader validates `resource_summary.json` first and derives the complete
allowed participant-file set from its accepted `participant_name` rows. It
rejects a missing, extra, or duplicate file. A `--site` detail read also
validates the selected participant record's schema, job identity, participant
identity, and copied values against the summary. ZIP CRC checking can detect
accidental corruption in a member when it is read, but it is not a signature
or a proof of provenance.

Fixed archive layout:

~~~text
resource_stats/participants/<participant_name>.json
resource_stats/resource_summary.json
~~~

## Structural and serialized bounds

| Structural item | Bound |
| --- | ---: |
| JSON nesting | 32 levels |
| CPU groups per CPU object | 1–4,096 |
| GPU groups per GPU object | 0–4,096 |
| Expected participants | 1–10,000 |
| Study job rows | 0–10,000 |
| Issues per list | 1–4 when present |
| Hardware model label | 128 ASCII characters |

| Record/response | Maximum bytes |
| --- | ---: |
| participant_summary | 1 MiB |
| resource_summary | 64 MiB |
| study_summary | 64 MiB |

The private terminal handoff is also limited to 1 MiB. The transport enforces
the participant-summary limit before JSON decoding.
Workspace readers apply independent per-member bounds before parsing.

## Privacy exclusions

Allowed data is restricted to authenticated product identity, normalized
hardware display metadata, the fixed summary-derived archive namespace, numeric
facts, statuses, and issues. Optional hardware models may be omitted without
changing numeric status. This feature adds no model-publication setting.

Forbidden data includes environment/argument dumps, raw CUDA masks, GPU UUID/
PCI identity, CPU serials/flags/topology, host/IP/PID/container/pod/scheduler
identity, absolute cgroup/workspace paths, credentials, tokens, message
payloads/topics, raw exceptions, and tracebacks.
