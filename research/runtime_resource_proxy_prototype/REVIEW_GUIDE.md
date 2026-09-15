# Runtime resource statistics: linear review guide

This is the recommended entry point for a design review. It explains the system from collection
to CLI output and points to the artifact that makes each step concrete. The candidate reductions
and their rationale are recorded in the [simplification review record](SIMPLIFICATION_REVIEW.md).

## One-minute explanation

NVFlare cannot reliably infer cloud allocation or billable usage from inside a job. Phase 1
therefore records narrower facts it can defend:

- CPU, memory, and GPU capacity visible inside each stable reporter-environment vector;
- how long the durable lifecycle owner confirms each vector remained open;
- persistent run-filesystem capacity across the whole logical participant;
- exact bytes in platform-registered retained result files; and
- exact application payload accepted at the F3 outbound sender boundary.

This follows the [GPU-release roadmap](../../docs/roadmap.rst): a durable, GPU-free site
supervisor keeps the logical job alive while transient workers acquire, reconfigure, and release
compute resources. One **attempt** is one stable `(resource lease, reporter environment,
CPU/memory/GPU vector)` window—not the entire job, scheduler allocation, or necessarily a retry.
A GPU-only release opens a zero-GPU successor while held CPU/memory continue to accrue. Only a
period after all counted compute resources have been released has no open attempt and contributes
zero to every transient resource. Persistent storage and F3 may continue across either case.

The supervisor immediately authenticates and durably stores resource-worker snapshots. Its own
clock records **opened_at** at confirmed acquisition before bootstrap and **end.closed_at** after
release/reconfiguration; worker snapshots do not define duration timestamps. It creates one
detailed participant file.
The server snapshots expected identity and role from authenticated job-selection/deployment state
independently of resource-report arrivals, classifies that immutable roster at a cutoff, accepts
at most one immutable participant summary per participant, computes a compact job summary, and
publishes that exact summary through `RESOURCE_STATS`.

```text
durable GPU-free site supervisor: participant start ---------------- participant final
                                 storage start         storage + retained + all-job F3
                                      |                              |
 attempt A: CPU + memory + GPU -------| reconfigured                 |
 attempt B: CPU + memory + zero GPU --|---------------- reconfigured |
 attempt C: CPU + memory + GPU -------|----------------------- release
        opened_at -> untimed worker snapshots -> end.closed_at
                  \____________ immediate durable handoff __________/
                                           |
                               one detailed participant file
                                           |
                      client terminal send / server local ingest
                                           v
                       fixed roster + participant/job totals
                                           |
                       resource_summary.json + manifest
                                           |
                           RESOURCE_STATS query copy and CLI
```

### Four terms to keep distinct

| Term | Plain meaning |
| --- | --- |
| Logical participant | One site's participation in the federated job from start through terminal finalization. |
| Durable site supervisor | Platform-owned, GPU-free owner that preserves identity and accepted fragments across worker release/resume. |
| Resource window / attempt | One half-open interval of a stable lease/environment capacity vector, bounded by supervisor `opened_at` and `end.closed_at`. |
| Resource worker | Disposable or resumable execution environment that runs custom work while a resource window is open. |

The contract uses these lifecycle meanings rather than a generic "parent" or "child," because the
roadmap implementation may restart a Client Job, cycle a worker below it, or preserve only
CPU-side state. The accounting boundary is a trusted capacity-vector transition, not a particular
process class. A changed GPU vector must be probed in a fresh, CUDA-uninitialized worker/helper;
an already initialized CUDA process is not assumed to rediscover new visibility.

### Current code versus roadmap target

| Layer | Current behavior | Roadmap-compatible interpretation |
| --- | --- | --- |
| Client Parent (CP) | Long-lived site control process that currently reserves resources before launching a Client Job and frees them after it exits. | Natural home, or coordinator, for the durable GPU-free supervisor responsibilities. |
| Client Job (CJ) | Currently lives for the participant job and waits between tasks. | May become a transient worker, preserve CPU-side state, or coordinate a fresh GPU worker/helper; changed GPU visibility is never inferred from a stale CUDA context. |
| External trainer | May already restart per task and release CUDA process memory. | Its exit is not by itself an NVFlare/Slurm resource-release confirmation and therefore cannot close an attempt. |

The current lifecycle is documented in
[system architecture](../../docs/system_architecture/system_architecture.rst). The roadmap changes
which process holds resources, but the design keys accounting to the trusted acquire/release hook
so it remains valid as that implementation lands.

## What to open during the meeting

| Order | File | What it answers |
| ---: | --- | --- |
| 1 | [Candidate decisions](SIMPLIFICATION_REVIEW.md) | What was removed, what remains, and why typed objects were chosen. |
| 2 | [Contract overview](schema/README.md) | The cross-record rules, formulas, trust boundary, privacy policy, and artifact topology. |
| 3 | [Field catalog](schema/FIELD_CATALOG.md) | Every stored field, type, condition, unit, and bound. |
| 4 | [Status/issue catalog](schema/CODE_CATALOG.md) | What reported, partial, unavailable, error, disabled, and each issue mean. |
| 5 | [Participant start](schema/golden/v1/participant_start.json) and [final](schema/golden/v1/participant_final.json) | Persistent storage and exactly-once retained/F3 facts across the logical participant. |
| 6 | [Attempt start](schema/golden/v1/attempt_start.json) and [final](schema/golden/v1/attempt_final.json) | CPU/memory/GPU capacity inside one acquired resource window. |
| 7 | [Preemption end](schema/golden/v1/attempt_end_terminated.json) | How the supervisor closes a released window without inventing a worker final. |
| 8 | [Participant golden](schema/golden/v1/participant_summary.json) and [preempt/resume golden](schema/golden/v1/participant_summary_preempted_resume.json) | Normal zero-GPU reconfiguration versus a true all-resource gap and recovery. |
| 9 | [Resource summary golden](schema/golden/v1/resource_summary.json) | The compact fixed roster and typed participant/job totals. |
| 10 | [Manifest golden](schema/golden/v1/manifest.json) | Canonical paths and SHA-256 digests, with no duplicate length or kind fields. |
| 11 | [Finalized job tree](schema/golden/v1/finalized_job/) | The coherent server archive, exact query copy, and CLI projections. |
| 12 | [Remaining gaps](GAPS.md) | What is contract-complete versus still requiring NVFlare integration or product policy. |

## Proposed review order

| Section | Plain-language question | Candidate direction |
| --- | --- | --- |
| 1. Product output | What must a user or estimator be able to answer? | Default CLI versus JSON/detail output. |
| 2. Identity and role | What joins records and prevents duplicate reporters? | Role once in the fixed expected-participant roster. |
| 3. Hardware metadata | Which CPU/GPU model facts may be disclosed? | Normalization, suppression, heterogeneous CPUs. |
| 4. Capacity | What is observed and what evidence makes it authoritative? | Typed selectors and CUDA-only GPU counts. |
| 5. Lifecycle and trust | Which facts follow the participant versus a resource window? | Durable GPU-free supervisor, one clock, immediate handoff, vector-transition end. |
| 6. Status and issues | How do zero, partial, unavailable, disabled, and error differ? | Small closed vocabularies. |
| 7. Resource time | Which timestamp and capacity define each formula? | Supervisor open/close for compute; participant start/final for storage. |
| 8. Retained/F3 | Which exact output and traffic facts are included? | Participant-lifetime registered files and three F3 buckets, finalized once. |
| 9. Aggregation | What is canonical and how are retries handled? | Immutable participant summary and compact roster/totals. |
| 10. CLI/Phase 2 | What is shown now and exported later? | Adaptive MIG display and `JobStatsReporter` boundary. |

The ten sections are ready for review in the [candidate decision record](SIMPLIFICATION_REVIEW.md).
The meeting pass should confirm both the simplifications and that the executable artifacts
faithfully implement the lifecycle audit corrections.

## Step 1: begin the participant and acquire a resource window

The GPU-free supervisor first records the persistent run-filesystem capacity for the logical
participant. Later, whenever a stable compute vector opens, it creates a random attempt ID and
records **opened_at** on its own clock as soon as acquisition is confirmed. A fresh worker then
enters an absolute platform-owned bootstrap artifact using `python -I -S`, a platform-owned
working directory, and a fixed minimal pre-Python environment allowlist. `-S -m` is not sufficient
because cwd can shadow the module. Custom-code import paths remain withheld until the capacity
snapshot has been accepted. The attempt ID and opaque supervisor-handoff locator must both be
explicitly allowlisted through process, Docker, Kubernetes, and Slurm launch paths. Bootstrap time
is already inside the window.

The resource worker reports typed CPU, memory, and GPU objects:

- CPU: minimum applicable affinity, effective cpuset, and finite quota expressed as normalized
  `quota_units`; online CPUs are a host-visible fallback only.
- Memory: minimum finite cgroup/physical bytes.
- GPU: groups returned by successful CUDA-runtime enumeration only.

The raw CUDA visibility string is never stored or parsed for a count. A true successful zero is
represented by an empty group array; unavailable enumeration has no numeric result. A MIG group
is omitted when no MIG instance is visible, so the routine client record and human output remain
small.

Every GPU-vector change applies new visibility and probes it in a fresh, CUDA-uninitialized worker
or platform helper before custom GPU work resumes. An already CUDA-initialized process cannot be
assumed to re-enumerate. A CPU/memory successor is numeric zero-GPU only after a successful empty
CUDA enumeration; otherwise GPU is unavailable. The contract does not make OS process exit the
accounting boundary, though worker replacement may be needed for a valid GPU transition.

Review: [participant start](schema/golden/v1/participant_start.json),
[attempt start](schema/golden/v1/attempt_start.json),
[zero GPU](schema/golden/v1/attempt_start_zero_gpu.json), and
[CUDA unavailable](schema/golden/v1/attempt_start_cuda_unavailable.json).

## Step 2: close the resource window honestly

Before a normal release or reconfiguration, the worker provides an optional second CPU/memory/GPU
snapshot. It has no duration timestamp and is only capacity-change evidence. After the lifecycle
owner confirms the transition, it records required **end.closed_at** on the same clock as
**opened_at**. For a partial release that changes the vector while retaining the same reporter
environment and other counted resources, reason **reconfigured** closes the old vector and the
successor opens at that exact boundary. If the worker crashes or is preempted, the supervisor
closes resources and records the end without synthesizing a final sample.

This is a one-way lifecycle assertion: **reconfigured** requires an immediate same-environment
successor at the boundary. When both snapshots are comparable, they must differ; an unavailable
successor snapshot is allowed and makes affected totals partial or unavailable. A fully released
lease can be reacquired at that exact timestamp with a changed vector and still remain a
release/reacquire pair; adjacency alone is not reconfiguration.

A launch failure after acquisition still has **opened_at** and **end.closed_at**. Its known
duration contributes to `resource_window_seconds`, but the missing capacity snapshot makes
transient totals partial or unavailable.

Worker start/final contents remain self-reports. Supervisor-owned, write-once durable storage
prevents later mutation of accepted bytes; it does not turn worker observations into independent
supervisor measurements. A worker-writable file or Kubernetes `emptyDir` alone is not this
boundary. The supervisor hands off each accepted fact immediately; it does not wait for logical
job completion.

Review: [normal final](schema/golden/v1/attempt_final.json), the released ends embedded in the
[participant summary](schema/golden/v1/participant_summary.json), and the standalone
[preemption end](schema/golden/v1/attempt_end_terminated.json).

## Step 3: derive resource time

For each attempt, the supervisor/server derives the CPU, memory, and GPU interval from one durable
lifecycle-owner clock:

```text
resource-window seconds = end.closed_at - opened_at
compute resource time = worker start capacity × resource-window seconds
```

The calculation uses decimal arithmetic and preserves exact large values as strings. Worker
snapshots do not carry duration timestamps. A missing attempt final or changed numeric attempt
final makes the result partial because the start value is an uncertain extrapolation over some or
all of the interval. It is not averaged with the final snapshot.

The main golden keeps CPU and memory throughout an eight-minute participant while releasing its
GPU for the middle five minutes. It therefore has three contiguous stable vectors:

| Window | Duration | CPU/memory | GPU |
| --- | ---: | --- | --- |
| A | 60 s | held | 1 |
| B | 300 s | held | reported zero |
| C | 120 s | held | 1 |

It reports **480 resource-window seconds**, **480 seconds of CPU/memory capacity**, and **180
GPU-instance-seconds**. The two GPU transitions use **reconfigured** and have no all-resource gap.
The separate preempt/resume golden releases every counted compute resource for 300 seconds; that
interval has no attempt and its missing worker final makes the transient totals partial.

One scheduler allocation may contain concurrent reporter environments. Their attempt durations
are summed, so `resource_window_seconds` can exceed participant wall time.

Storage uses the logical participant clock instead:

```text
storage-capacity time = participant-start filesystem capacity
                      × (participant-final time - participant-start time)
```

It includes release/resume intervals only when the supervisor guarantees the persistent run
filesystem remained continuously available. Otherwise storage time is partial or unavailable.
The durable supervisor's own CPU and memory are excluded from the per-job compute proxy.

CPU totals group by optional normalized model and architecture. GPU totals group by full GPU or
MIG kind and optional model, per-entity memory, and MIG profile. Suppressed/unknown metadata forms
an unlabeled group without changing numeric authority.

One TiB of storage for one day is `94997804639846400` byte-seconds, already above JavaScript's
safe integer range. All measured and derived counters are canonical decimal strings to preserve
exact values across languages. Review the independent
[participant final](schema/golden/v1/participant_final.json) and
[derived participant](schema/golden/v1/participant_summary_large_value.json) fixtures.

## Step 4: retained content and F3

Retained content includes only final regular files explicitly registered and frozen by the
platform. Each entry stores a normalized relative path, exact descriptor size, and digest. The
total is derived; the system does not sweep the workspace or count its archive. The supervisor
freezes this registry once at logical participant finalization, so files created across several
resource windows are not counted repeatedly.

F3 belongs to the logical participant and spans all its resource windows and release/resume gaps.
The durable participant owner atomically freezes three factual buckets before participant-final
serialization:

- `remote_accepted`: remote payload accepted for transport before the atomic freeze; the primary total;
- `local_delivered`: direct delivery, never folded into the primary total;
- `remote_failed_before_acceptance`: remote sends that failed before acceptance.

Each bucket stores application payload bytes and messages. Counter callbacks completing after the
atomic freeze are ignored for canonical totals. Fixed included traffic classes, freeze behavior,
and non-spoofable platform-only summary-publication exclusion belong to platform behavior, not
record labels or counters in the immutable summary; including the publication's own size would be
circular.

The included classes are exactly `task_request`, `task_response`, `task_result`,
`job_application`, and `job_stream_data`; `job_stream_control`, `bulk_envelope`,
`workspace_transfer`, `platform_control`, `log_export`, unknown classes, and summary publication
are excluded. At each destination, payload bytes mean `len(message.payload)` after encoding and
optional end-to-end encryption, immediately before direct delivery or remote send. Headers,
transport framing, network/TLS overhead, compression effects, and retransmissions are excluded.
Fan-out counts once per destination, and forwarding counts once again at each participant sender
hop. Remote counts advance only after send acceptance; direct delivery uses its separate bucket.

Review: [participant final](schema/golden/v1/participant_final.json).

## Step 5: participant acceptance and retries

The participant file preserves one participant start/final and all detailed resource-window attempts,
including optional worker finals and trusted release/preemption ends. It does not repeat role or
materialize resource-time totals.

There is deliberately no participant revision number. The first valid, authenticated summary
received by the report cutoff wins. A retry with the identical SHA-256 digest is an idempotent
no-op; a different digest is a conflicting attempt to replace an accepted measurement and is
rejected. A malformed/invalid candidate does not reserve the participant slot. Distinct resource
windows remain distinct items inside the one terminal participant summary; multiple attempts are
normal and do not by themselves mean a retry.

The client supervisor sends attempt fragments only to its own durable local store as they occur.
It sends one consolidated participant summary to the central server at terminal completion, with
exact-byte retries allowed by the digest rule. The server parent/job supervisor performs the same
lifecycle ownership for `role: server`, but locally ingests its summary instead of sending to
itself.

Review: [participant summary](schema/golden/v1/participant_summary.json).

## Step 6: server aggregation

The expected-participant roster is sourced from authenticated job-selection/deployment state,
never the resource reports that happen to arrive. At the report cutoff the server snapshots that
membership, makes it immutable, and classifies each slot, so missing reporters remain visible.
This roster is the single coverage source. Every entry records participant ID, job-scoped
participant key, role, and `accepted | missing | invalid | disabled`. Accepted entries also
contain receipt time, summary digest, derived `resource_window_seconds`, and compact typed totals.
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

`resource_window_seconds` is a sum of reporter-environment windows. It may exceed participant
wall time when multiple environments run concurrently; this is intentional and is not a physical-
capacity claim.

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

The default CLI presents a compact per-participant table and qualified accepted-report aggregate.
It keeps report-acceptance **STATUS** separate from measurement **QUALITY**, calls summed reporter-
environment duration **ENV WINDOW**, and labels the primary payload column **F3 REMOTE**. It adds a MIG
column or MIG-specific prose only when the selected data contains positive MIG instance-time.
JSON preserves all typed groups and base units. A missing expected participant remains a valid
partial result; an unknown participant, not-ready job, absent legacy data, or failed integrity
check has a distinct command error.

The table's window-time column is the sum of stable reporter-environment vectors, not necessarily
elapsed logical-job time. It can exceed wall time under concurrent environments. A GPU-only
reconfiguration stops GPU time but continues still-held CPU/memory time; a full-release gap stops
all transient totals. Storage-capacity time intentionally spans the participant lifecycle when
continuous workspace availability is guaranteed.

```text
nvflare job resources JOB_ID --site all
nvflare job resources JOB_ID --site SITE
nvflare --format json job resources JOB_ID --site all
```

Review the coherent files in [the finalized job tree](schema/golden/v1/finalized_job/), especially
the [human output](schema/golden/v1/finalized_job/cli/resources-all.txt) and
[JSON output](schema/golden/v1/finalized_job/cli/resources-all.json). The
[partial preempt/resume output](schema/golden/v1/finalized_job/cli/resources-preempted-resume.txt)
makes the true all-resource gap and incomplete transient totals visible. The
[complete selected-site output](schema/golden/v1/finalized_job/cli/resources-site-1-details.txt)
includes its optional hardware detail below the selected participant.

## Phase 2 relationship

Phase 1 owns measurement, validation, durable evidence, finalization, query data, and CLI
semantics. Phase 2 can have `JobStatsReporter` publish selected finalized values to telemetry.
It reads the validated Phase 1 result and must not create a second definition of capacity,
resource time, F3 inclusion, or participant coverage.

Phase 2 receives no per-window open, reconfigure, close, or resume events. It begins only after
Phase 1 has accepted participant summaries and finalized `resource_summary.json`.

Hardware model labels in telemetry are optional and require an explicit label/cardinality/privacy
review. Detailed attempt records and raw evidence remain in the Phase 1 archive rather than being
turned into high-cardinality metrics.

## What remains implementation work

The contract and fixtures are reviewable; NVFlare production integration is not complete. The
remaining roadmap lifecycle hook, launcher, CUDA adapter, durable supervisor handoff, artifact
registry, CellNet hook, server materializer, and CLI work is tracked in [GAPS.md](GAPS.md). The real local captures under
[`generated/`](generated/) are probe evidence and predate the canonical v1 format; do not use
them as wire-format examples.
