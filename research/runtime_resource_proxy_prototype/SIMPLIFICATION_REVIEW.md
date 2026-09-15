# Resource statistics: candidate simplification decisions

This record presents the candidate v1 resource-statistics decisions for design review. The
corresponding executable candidate is the
[JSON Schema and executable validator](schema/README.md); this file records why the smaller
shape was chosen and gives reviewers a section-by-section discussion path.

The governing rule is:

> Persist each independently useful fact once. Derive units, interpretation, coverage, and
> display notices from the typed field, its location, and `schema_version`.

The lifecycle candidate is aligned with the GPU-release roadmap: a durable GPU-free supervisor
owns one logical participant, while each **attempt** represents one stable `(resource lease,
reporter environment, CPU/memory/GPU vector)` window. This refinement preserves the typed design
without returning to generic metric metadata.

## Candidate outcome

The generic metric envelope has been replaced with typed resource objects. A generic envelope
made every metric repeat its name, unit, basis, scope, sharing state, coverage, source, timestamp,
and caveats. It was technically possible to reconcile, but every new rule had to be expressed as
a matrix over metric name, location, source, unit, status, and dimensions. Typed objects put the
rule beside the value it governs: CPU evidence belongs to CPU, CUDA authority belongs to GPU,
and F3 counter rules belong to F3. This materially reduces both the wire format and the number
of invalid combinations a reader must reject.

The candidate reductions are:

- no persisted metric `name`, `unit`, `basis`, `scope`, `sharing`, `coverage`, repeated
  `observed_at`, source label, caveat list, warning list, or fixed qualification list;
- no resource-worker-computed resource-time rollups; the trusted supervisor/server derives them
  after pairing accepted lifecycle facts;
- `role` appears once in the fixed server roster, not in worker lifecycle or participant files;
- one small context-neutral issue vocabulary replaces resource-specific reason codes;
- detailed attempts live only in participant files; `resource_summary.json` contains a compact
  roster projection and aggregate totals;
- CPU, memory, and GPU capacity belong to transient attempts; persistent storage plus terminal
  retained/F3 facts belong once to the logical participant;
- CPU and GPU model metadata is optional, normalized, privacy-controlled, and retained where it
  helps an estimator; and
- MIG remains a supported GPU group but is absent from records and hidden in human CLI output
  when it is inapplicable.

## 1. Product output — ready for review

A user or estimator can answer:

- which participants were expected and which reported by the fixed cutoff;
- how long each accepted participant held transient compute resource windows;
- CPU-, memory-, full-GPU-, and applicable MIG-resource time over confirmed stable-vector windows;
- storage-capacity time over the logical participant lifecycle;
- retained NVFlare result bytes;
- F3 remote-accepted application payload bytes and messages; and
- optional normalized CPU/GPU model information.

The default human CLI stays compact. Its window time is the sum of reporter-environment vector
windows, so it may be shorter than wall time across full-release gaps or greater under concurrent
environments. Detailed hardware groups and diagnostic outcome buckets are
available in JSON and may later be exposed by a detail view. Every total is described as a sum of
participant-visible proxies, never as physical capacity, reservation, allocation, utilization,
or billable usage.

## 2. Identity and role — ready for review

Lifecycle records keep job, participant, attempt, and execution-environment identity so the
supervisor cannot pair records from different vector windows or accept duplicate rank reporters
for one environment. An attempt is a half-open stable lease/environment capacity vector bounded
by lifecycle-owner `opened_at` and `end.closed_at`. One scheduler allocation can contain
concurrent environment attempts or several sequential reconfigurations. Multiple attempts are
normal and do not imply retry. The participant archive is keyed by a job-scoped
HMAC participant key. The server's fixed expected-participant roster stores the participant
display ID and `role: client | server` once.

Payload identity still does not authenticate itself. The supervisor/server must compare it with
trusted launcher and roster context. Execution-environment keys and participant keys are
job-scoped platform HMAC values, not plain hashes of enumerable infrastructure labels.

## 3. Hardware description and privacy — ready for review

CPU may include normalized `model` and `architecture`. Report one CPU model only when all
affinity-visible processors normalize to the same value. A heterogeneous visible CPU set omits
the model; it does not claim one representative processor and does not downgrade a valid capacity
observation.

GPU groups may include normalized model, per-entity memory, and a MIG profile for MIG groups.
GPU metadata comes from properties of devices already validated by CUDA-runtime enumeration;
NVML may enrich those devices but may not create a group or change a count.

Model disclosure is infrastructure fingerprinting. Site policy may suppress optional model,
architecture, memory, or MIG-profile metadata without changing capacity status. Records never
contain raw `/proc/cpuinfo`, CPU flags/topology/serials, GPU UUIDs or PCI addresses, raw CUDA
masks, host/container/pod identity, or raw probe output.

## 4. Typed capacity observations — ready for review

An accepted attempt start/final observation has typed CPU, memory, and GPU objects. Participant
start/final has storage. CPU keeps only normalized evidence used by the selector:

```text
affinity_count, cpuset_count, quota_units, optional online_count fallback
```

`quota_units` is the exact quota divided by period, floored to at most nine fractional decimal
digits so it cannot overstate capacity. For example, an internal `quota_us=150000` and
`period_us=100000` becomes `quota_units="1.5"`; `1/3` becomes `"0.333333333"`. The raw microsecond
pair is probe-internal and is not persisted. CPU visible units are the minimum of the applicable
strong constraints; `online_count` is used only as an explicit host-visible fallback.

Memory is the smaller finite cgroup/physical byte observation. GPU numeric authority requires
successful CUDA-runtime enumeration. `cuda_mask_present` is diagnostic only; the raw string and
token count are forbidden and cannot produce a numeric count. CPU, memory, and GPU are observed
after a transient allocation is acquired and before custom work starts or resumes.

Storage is the total bytes for the persistent filesystem containing the job run directory. It is
observed once at logical participant start and once at participant finalization, not once per
compute attempt. Multiplication across release/resume requires a supervisor guarantee that the
workspace remained continuously available; otherwise storage is partial or unavailable.

A reported GPU inventory contains only positive groups. Absence of a full-GPU or MIG group after
successful enumeration means an observed zero for that kind. If enumeration is unavailable or
fails, no numeric GPU count is inferred. Thus ordinary clients have no MIG group or MIG display
field at all.

Every GPU-vector transition is probed after new visibility is applied in a fresh,
CUDA-uninitialized worker or platform helper. A CPU/memory successor reports zero GPU only after
successful empty enumeration. An already initialized CUDA process is not assumed to reset.

## 5. Lifecycle, trust, and final capacity — ready for review

The trusted flow has two levels. The durable GPU-free supervisor records one participant start,
keeps logical job identity through zero or more transient allocations, and records one participant
final. Each stable vector has lifecycle-owner `opened_at`, an optional worker start/final snapshot
as allowed by status, and required `end.closed_at`. A GPU-only change uses **reconfigured** and an
exact-boundary zero-GPU successor when CPU/memory remain held. A resource window can close without
an OS process exit.

Attempt start/final capacity facts remain untimed resource-worker self-reports even after
authenticated immediate handoff to supervisor-owned, write-once durable storage. `opened_at`,
attempt end, participant storage,
retained-file freeze, and atomic F3 counter freeze are supervisor/platform observations. A worker-writable file
or allocation-scoped `emptyDir` is not durable evidence.

The full CPU/memory/GPU final snapshot is kept whenever the worker supplies a valid attempt final
before transition. It is useful for detecting change and audit; it is not a duration timestamp or
a replacement for attempt-start capacity. On a crash, preemption, or missing/invalid final, the
system never invents a final. It uses the supervisor-observed attempt end and marks the affected
compute proxy partial.

Trusted bootstrap remains an implementation boundary. The supervisor records `opened_at` at
confirmed acquisition so bootstrap time counts. Every launcher invokes an absolute platform-
owned artifact with `python -I -S`, a platform-owned cwd, and a fixed minimal pre-Python
environment allowlist; `-S -m` remains cwd-shadowable. It passes the attempt ID and opaque
supervisor-handoff locator through an explicit launcher allowlist and enables custom imports only
after snapshot acceptance.

## 6. Status and issues — ready for review

Point capacity uses `reported | unavailable | error`. Derived resource time, retained content,
and F3 additionally use `partial`. Disabled collection is one participant roster state rather
than four repeated disabled resources. Summary totals use
`reported | partial | unavailable`.

`reported` means a complete observation and forbids issues. `partial` carries a usable numeric
subset or proxy plus one or more issues. `unavailable` and `error` carry no numeric value.
The exact issue vocabulary is:

```text
not_bound
counter_gap
observation_incomplete
attribution_incomplete
unsupported
permission_denied
dependency_missing
malformed_source
```

The containing object supplies context, so `not_bound` on F3 means its counter was not bound,
while the same spelling on retained content means its registry was not bound. Disabled policy,
roster state, crash state, and capacity change are already facts elsewhere and are not duplicated
as issue codes. An observed zero is the string `"0"`; missing or failed collection is never zero.

## 7. Resource-time derivation — ready for review

The supervisor/server derives each compute interval from the lifecycle owner's one clock. It
multiplies worker start CPU, memory, and GPU capacity by that exact vector-window interval:

```text
resource-window seconds = end.closed_at - opened_at
compute resource time = worker start capacity × resource-window seconds
```

`opened_at` is recorded at confirmed acquisition before bootstrap; worker start/final snapshots
carry no duration timestamps. A launch failure after acquisition retains its duration but has no
capacity, making transient totals partial when another window contributes or otherwise
unavailable.

The participant storage interval instead runs from participant start through participant final:

```text
storage-capacity time = participant-start capacity × logical-participant seconds
```

The corresponding start is intentionally the basis; endpoint snapshots do not justify averaging.
A missing attempt final or changed numeric attempt final produces a partial compute result; a
changed final storage value produces partial storage time. CPU totals stay grouped by
normalized model and architecture when known. GPU totals stay grouped by kind, normalized model,
per-entity memory, and MIG profile when known. Unknown/suppressed metadata forms an unlabeled
group rather than invalidating the numeric value.

A GPU-only change closes the old vector as **reconfigured** and immediately opens a CPU/memory
plus zero-GPU successor. It adds zero GPU time while still-held CPU/memory continue. Only a gap
after all counted compute resources are released adds zero to every transient total. Such gaps
remain inside storage time and may carry F3 traffic. The shared supervisor's own CPU and memory
are excluded.

`reconfigured` is deliberately one-way: the trusted lifecycle authority requires an immediate
same-environment successor at the exact boundary. When both snapshots are comparable, they must
differ; an unavailable successor snapshot is allowed and makes affected totals partial or
unavailable. A full release followed by reacquisition may touch that boundary and change the
vector without being reclassified as reconfiguration.

Participant files do not persist a second resource-time copy. Accepted roster entries and job
totals materialize the derived values needed for queries. `resource_window_seconds` is retained
on an accepted roster entry as a checked convenience: it is the sum of that participant's
environment-attempt intervals, not an independently measured duration. It may exceed logical
participant wall time when distinct environments overlap.

The main golden makes the distinction concrete with three contiguous windows over 480 seconds:
GPU-bearing for 60 seconds, CPU/memory plus reported-zero GPU for 300 seconds, then GPU-bearing
for 120 seconds. CPU and memory therefore accrue for 480 seconds, GPU for 180 seconds, and
participant storage for 480 seconds. The separate preempt/resume golden instead has a true
300-second all-resource gap and partial transient totals.

## 8. Retained content and F3 — ready for review

Retained content stores a status plus bounded entries containing normalized relative path,
`size_bytes`, and SHA-256. `artifact_id`, stored total bytes, and fixed explanatory labels are
removed. Total retained bytes derive from the entry sizes. Only regular files registered and
frozen by the platform are eligible. The supervisor freezes and stores the result once in
participant final, not in every attempt final.

F3 spans the logical participant across worker release/resume and stores three factual outcome
buckets once in participant final:

1. `remote_accepted` — payload accepted by remote transport before the participant-final counter freeze; this alone is the
   primary F3 total;
2. `local_delivered` — direct/local delivery, kept separately;
3. `remote_failed_before_acceptance` — attempted remote traffic that failed before acceptance.

Each bucket contains application `payload_bytes` and `messages`. The durable participant owner
atomically freezes all three counters before participant-final serialization; callbacks completing
afterward are ignored for canonical totals. Included classes are exactly `task_request`, `task_response`,
`task_result`, `job_application`, and `job_stream_data`; `job_stream_control`, `bulk_envelope`,
`workspace_transfer`, `platform_control`, `log_export`, unknown classes, and summary publication
are excluded.

At each destination, bytes are `len(message.payload)` after encoding and optional end-to-end
encryption, immediately before direct delivery or remote send. Headers, lower-level framing,
network/TLS overhead, compression effects, and retransmissions are excluded. Fan-out counts each
destination; forwarding counts each participant sender hop. The remote bucket advances only on
send acceptance, while direct delivery remains separate. These sender semantics, atomic-freeze
behavior, and non-spoofable platform-only summary-publication exclusion are platform rules rather
than repeated strings or circular counters in the immutable summary.

## 9. Aggregation, replay, and storage — ready for review

The server sources expected identity and role from authenticated job-selection/deployment state,
independently of resource-report arrivals. At the report cutoff it snapshots that membership as
the immutable expected-participant roster and classifies every slot, so a missing report cannot
remove itself from coverage. Each entry has identity, role, and one of
`accepted | missing | invalid | disabled`. Accepted entries add receipt time, participant-summary
digest, `resource_window_seconds`, and compact totals; invalid entries add receipt time and compact
issues describing the rejected candidate. The job-level `totals` has the same typed shape.
Missing/invalid/disabled entries make otherwise numeric job totals partial; if there are no
numeric contributions, the affected total is unavailable.

There is no participant `summary_revision`. That rejected field would have allowed a participant
to replace an already accepted terminal measurement before the cutoff. Replacement creates
ordering and reconciliation questions without helping normal retry delivery. Instead, the first
valid authenticated participant summary received by the cutoff wins. An identical digest retry
is an idempotent no-op; a conflicting replacement is rejected. An invalid candidate does not
reserve the participant slot. Multiple stable-vector attempts remain distinct entries inside
the single immutable participant summary. They are expected in normal GPU reconfiguration or release/resume and do
not by themselves indicate a retry or relaunch.

The supervisor accepts and durably stores each local lifecycle fragment immediately. A client
supervisor sends one consolidated summary across the site-to-server boundary at terminal
completion; the server parent/job supervisor applies the same lifecycle contract and locally
ingests `role: server`. Identical-byte delivery retries remain safe under the digest rule.

The server archive keeps one detailed participant file per accepted roster entry, one compact
`resource_summary.json`, and a manifest containing only normalized `relative_path` and `sha256`.
The manifest covers the resource summary and exactly the accepted participant files. The exact
resource summary is the query copy stored behind the narrow `RESOURCE_STATS` save/get API.

## 10. CLI and Phase 2 — ready for review

The default Phase 1 CLI separates report-acceptance **STATUS** from measurement **QUALITY**, calls
the summed reporter-environment duration **ENV WINDOW**, labels the primary payload column **F3
REMOTE**, and qualifies the aggregate as accepted-report resource time. It explains that partial
GPU release stops GPU time while still-held
CPU/memory continue, and that only full-release gaps stop every transient total. Window time may
exceed wall time under concurrent environments; storage follows the logical participant when
continuous workspace availability is guaranteed. It hides MIG columns and text unless positive MIG
time is applicable to the selection. JSON preserves typed hardware groups and diagnostic F3
buckets. Optional hardware models belong in JSON and a future detail/single-site view rather than
the default table.

Phase 2 may publish selected finalized values through `JobStatsReporter`. It consumes the same
validated Phase 1 materialization after finalization; it receives no per-window open/reconfigure/close
events and does not redefine collection authority, lifecycle pairing, F3 semantics, or the
durable evidence archive. Telemetry labels must remain bounded and explicit, with hardware model
labels optional/reviewable because of cardinality and privacy.

## Decision log

| Section | Status | Candidate decision |
| --- | --- | --- |
| 1. Product output | Ready for review | Compact default output; typed JSON/detail; proxy totals only. |
| 2. Identity and role | Ready for review | Logical participant plus stable lease/environment-vector identity; role once in fixed roster. |
| 3. Hardware description | Ready for review | Optional normalized CPU/GPU models with suppression policy. |
| 4. Capacity observations | Ready for review | Attempt CPU/memory/GPU; participant storage; CUDA-only GPU authority; omit inapplicable MIG. |
| 5. Lifecycle and trust | Ready for review | GPU-free supervisor clock; immediate durable handoff; vector-transition end; never invent worker final. |
| 6. Status and issues | Ready for review | Small status domains and eight context-neutral issues. |
| 7. Resource-time | Ready for review | Stable-vector windows; partial release keeps held dimensions; full-release gaps add zero compute. |
| 8. F3 and retained content | Ready for review | Three F3 facts and registered paths finalized once per participant. |
| 9. Aggregation and storage | Ready for review | Immutable first valid summary; compact roster/totals; path+digest manifest. |
| 10. CLI and Phase 2 | Ready for review | Adaptive human display; typed JSON; `JobStatsReporter` consumes finalized Phase 1 data. |

Future discussion may refine product defaults or implementation hooks, but it must not silently
restore removed duplication. Any stored field added later should answer: which independent fact
would be lost if a reader derived it from the surrounding typed object and schema version?
