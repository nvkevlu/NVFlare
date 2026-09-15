# Runtime resource statistics: linear review guide

This is the recommended entry point for a design review. It explains the system from collection
to CLI output and points to the artifact that makes each step concrete. The accepted reductions
and their rationale are recorded in the [simplification decision record](SIMPLIFICATION_REVIEW.md).

## One-minute explanation

NVFlare cannot reliably infer cloud allocation or billable usage from inside a job. Phase 1
therefore records narrower facts it can defend:

- capacity visible to one trusted job execution environment at startup and, when available, at
  normal completion;
- how long that observation applies;
- exact bytes in platform-registered retained result files; and
- exact application payload accepted at the F3 outbound sender boundary.

The parent authenticates and durably stores child self-reports, closes crashed processes with a
parent-observed exit, and creates one detailed participant file. The server freezes the expected
roster, accepts at most one immutable participant summary per participant by a fixed cutoff,
computes a compact job summary, and publishes that exact summary through `RESOURCE_STATS`.

```text
sanitized launcher
      |
      v
start capacity -----> parent-owned attempt fragments <----- final capacity + retained + F3
      |                            ^                                  |
      |                            |                                  |
      +----------------------- parent exit ----------------------------+
                                   |
                                   v
                    one detailed participant file
                                   |
                     authenticated delivery by cutoff
                                   v
             frozen roster + compact participant/job totals
                                   |
             resource_summary.json + digest-only manifest
                                   |
                 RESOURCE_STATS query copy and CLI
```

## What to open during the meeting

| Order | File | What it answers |
| ---: | --- | --- |
| 1 | [Accepted decisions](SIMPLIFICATION_REVIEW.md) | What was removed, what remains, and why typed objects were chosen. |
| 2 | [Contract overview](schema/README.md) | The cross-record rules, formulas, trust boundary, privacy policy, and artifact topology. |
| 3 | [Field catalog](schema/FIELD_CATALOG.md) | Every stored field, type, condition, unit, and bound. |
| 4 | [Status/issue catalog](schema/CODE_CATALOG.md) | What reported, partial, unavailable, error, disabled, and each issue mean. |
| 5 | [Startup golden](schema/golden/v1/attempt_start.json) | A typed CPU/memory/storage/GPU observation with normalized evidence and models. |
| 6 | [Final golden](schema/golden/v1/attempt_final.json) | Final capacity, retained entries, and all five F3 facts. |
| 7 | [Crash golden](schema/golden/v1/parent_exit_crash.json) | How the parent closes an attempt without inventing a final sample. |
| 8 | [Participant golden](schema/golden/v1/participant_summary.json) | Multiple lifecycle facts preserved in one immutable participant archive. |
| 9 | [Resource summary golden](schema/golden/v1/resource_summary.json) | The compact frozen roster and typed participant/job totals. |
| 10 | [Manifest golden](schema/golden/v1/manifest.json) | Canonical paths and SHA-256 digests, with no duplicate length or kind fields. |
| 11 | [Finalized job tree](schema/golden/v1/finalized_job/) | The coherent server archive, exact query copy, and CLI projections. |
| 12 | [Remaining gaps](GAPS.md) | What is contract-complete versus still requiring NVFlare integration or product policy. |

## Approved review order

| Section | Plain-language question | Accepted direction |
| --- | --- | --- |
| 1. Product output | What must a user or estimator be able to answer? | Default CLI versus JSON/detail output. |
| 2. Identity and role | What joins records and prevents duplicate reporters? | Role once in the frozen roster. |
| 3. Hardware metadata | Which CPU/GPU model facts may be disclosed? | Normalization, suppression, heterogeneous CPUs. |
| 4. Capacity | What is observed and what evidence makes it authoritative? | Typed selectors and CUDA-only GPU counts. |
| 5. Lifecycle and trust | Who reports each fact and what happens on crash? | Durable parent handoff and final capacity rules. |
| 6. Status and issues | How do zero, partial, unavailable, disabled, and error differ? | Small closed vocabularies. |
| 7. Resource time | Which timestamp and capacity define the formula? | Startup value times derived interval. |
| 8. Retained/F3 | Which exact output and traffic facts are included? | Registered files and five F3 buckets. |
| 9. Aggregation | What is canonical and how are retries handled? | Immutable participant summary and compact roster/totals. |
| 10. CLI/Phase 2 | What is shown now and exported later? | Adaptive MIG display and `JobStatsReporter` boundary. |

All ten decisions are approved in the [decision record](SIMPLIFICATION_REVIEW.md). The goal of a
meeting pass is therefore to confirm that the executable artifacts faithfully implement those
decisions, not to re-review fields removed from the contract.

## Step 1: trusted startup observation

The parent creates a random attempt ID and launches the job through a platform-owned sanitized
bootstrap. Custom-code import paths are withheld until the initial observation is complete. The
attempt ID must be explicitly allowlisted through process, Docker, Kubernetes, and Slurm launch
paths.

The child reports typed CPU, memory, storage, and GPU objects:

- CPU: minimum applicable affinity, effective cpuset, and finite quota expressed as normalized
  `quota_units`; online CPUs are a host-visible fallback only.
- Memory: minimum finite cgroup/physical bytes.
- Storage: total bytes for the filesystem containing the job-run directory.
- GPU: groups returned by successful CUDA-runtime enumeration only.

The raw CUDA visibility string is never stored or parsed for a count. A true successful zero is
represented by an empty group array; unavailable enumeration has no numeric result. A MIG group
is omitted when no MIG instance is visible, so the routine client record and human output remain
small.

Review: [startup](schema/golden/v1/attempt_start.json),
[zero GPU](schema/golden/v1/attempt_start_zero_gpu.json), and
[CUDA unavailable](schema/golden/v1/attempt_start_cuda_unavailable.json).

## Step 2: final and crash facts

On a normal child finish, the system keeps a second full capacity snapshot plus retained-content
and F3 facts. The final is useful evidence of capacity change, but resource-time still uses the
startup capacity. If the child crashes, the parent records the process exit and never synthesizes
a final sample.

Child start/final contents remain self-reports. Parent-owned, write-once durable storage prevents
later mutation of accepted bytes; it does not turn child observations into independent parent
measurements. A child-writable file or Kubernetes `emptyDir` alone is not this boundary.

Review: [normal final](schema/golden/v1/attempt_final.json) and
[parent crash closure](schema/golden/v1/parent_exit_crash.json).

## Step 3: derive resource time

For each attempt, the parent/server derives the interval from start to final, or start to
parent-observed exit if a final is absent:

```text
resource time = startup runtime-visible capacity × interval seconds
```

The calculation uses decimal arithmetic and preserves exact large values as strings. A missing
final or changed numeric final makes the result partial because the startup value is an uncertain
extrapolation over some or all of the interval. It is not averaged with the final endpoint.

CPU totals group by optional normalized model and architecture. GPU totals group by full GPU or
MIG kind and optional model, per-entity memory, and MIG profile. Suppressed/unknown metadata forms
an unlabeled group without changing numeric authority.

One TiB of storage for one day is `94997804639846400` byte-seconds, already above JavaScript's
safe integer range. All measured and derived counters are canonical decimal strings to preserve
exact values across languages. Review the independent
[large-value final](schema/golden/v1/attempt_final_large_value.json) and
[derived participant](schema/golden/v1/participant_summary_large_value.json) fixtures.

## Step 4: retained content and F3

Retained content includes only final regular files explicitly registered and frozen by the
platform. Each entry stores a normalized relative path, exact descriptor size, and digest. The
total is derived; the system does not sweep the workspace or count its archive.

F3 freezes five factual buckets at the final cutoff:

- `remote_accepted`: remote payload accepted for transport before cutoff; the primary total;
- `local_delivered`: direct delivery, never folded into the primary total;
- `remote_failed_before_acceptance`: remote sends that failed before acceptance;
- `late_after_cutoff`: later events excluded from the frozen total; and
- `summary_excluded`: publication traffic excluded by a platform-owned non-spoofable path.

Each bucket stores application payload bytes and messages. Fixed included traffic classes and the
sender/exclusion mechanisms belong to the versioned implementation contract, not record labels.

## Step 5: participant acceptance and retries

The participant file preserves detailed attempts, including accepted lifecycle facts, final data
when present, and crash evidence. It does not repeat role or materialize resource-time totals.

There is deliberately no participant revision number. The first valid, authenticated summary
received by the report cutoff wins. A retry with the identical SHA-256 digest is an idempotent
no-op; a different digest is a conflicting attempt to replace an accepted measurement and is
rejected. A malformed/invalid candidate does not reserve the participant slot. Distinct execution
attempts remain distinct items inside the one terminal participant summary.

Review: [participant summary](schema/golden/v1/participant_summary.json).

## Step 6: server aggregation

The frozen roster is the single coverage source. Every entry records participant ID, job-scoped
participant key, role, and `accepted | missing | invalid | disabled`. Accepted entries also
contain receipt time, summary digest, derived `observation_seconds`, and compact typed totals.
Invalid entries add trusted receipt time and compact issues; missing/disabled entries need only
identity, role, and status.
The job `totals` has the same shape:

- resource time: CPU groups, memory byte-seconds, storage byte-seconds, and GPU groups;
- retained content: bytes; and
- F3: only remote-accepted payload bytes and messages.

Roster gaps make a numeric job total partial. With no usable contributions, it is unavailable.
Counts and warning prose derive from the roster/status facts; they are not stored in parallel.
Cross-job overlap remains intentional. These participant-visible sums are never advertised as
available physical capacity.

Review: [resource summary](schema/golden/v1/resource_summary.json).

## Step 7: archive, query, and CLI

The server archive is:

```text
resource_stats/
  resource_summary.json
  participants/<participant_key>.json
  manifest.json
```

The manifest contains only sorted path/digest pairs for the resource summary and exactly one file
per accepted participant. The exact validated `resource_summary.json` bytes are the job-store
`RESOURCE_STATS` query copy. Storage uses an exact component and narrow save/get APIs; a generic
prefix must not authorize arbitrary `RESOURCE_STATS_*` names.

The default CLI presents a compact per-participant table and qualified aggregate. It adds a MIG
column or MIG-specific prose only when the selected data contains positive MIG instance-time.
JSON preserves all typed groups and base units. A missing expected participant remains a valid
partial result; an unknown participant, not-ready job, absent legacy data, or failed integrity
check has a distinct command error.

```text
nvflare job resources JOB_ID --site all
nvflare job resources JOB_ID --site SITE
nvflare --format json job resources JOB_ID --site all
```

Review the coherent files in [the finalized job tree](schema/golden/v1/finalized_job/), especially
the [human output](schema/golden/v1/finalized_job/cli/resources-all.txt) and
[JSON output](schema/golden/v1/finalized_job/cli/resources-all.json). The optional model view is
shown separately in [single-site hardware detail](schema/golden/v1/finalized_job/cli/resources-site-1-details.txt).

## Phase 2 relationship

Phase 1 owns measurement, validation, durable evidence, finalization, query data, and CLI
semantics. Phase 2 can have `JobStatsReporter` publish selected finalized values to telemetry.
It reads the validated Phase 1 result and must not create a second definition of capacity,
resource time, F3 inclusion, or participant coverage.

Hardware model labels in telemetry are optional and require an explicit label/cardinality/privacy
review. Detailed attempt records and raw evidence remain in the Phase 1 archive rather than being
turned into high-cardinality metrics.

## What remains implementation work

The contract and fixtures are reviewable; NVFlare production integration is not complete. The
remaining launcher, CUDA adapter, durable handoff, artifact registry, CellNet hook, server
materializer, and CLI work is tracked in [GAPS.md](GAPS.md). The real local captures under
[`generated/`](generated/) are probe evidence and predate the canonical v1 format; do not use
them as wire-format examples.
