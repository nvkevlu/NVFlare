# Resource statistics: accepted simplification decisions

This record captures the decisions accepted for the candidate v1 resource-statistics contract.
It is no longer a proposal or a list of alternatives. The normative machine contract is the
[JSON Schema and executable validator](schema/README.md); this file records why the smaller
shape was chosen and gives reviewers a section-by-section discussion path.

The governing rule is:

> Persist each independently useful fact once. Derive units, interpretation, coverage, and
> display notices from the typed field, its location, and `schema_version`.

## Accepted outcome

The generic metric envelope has been replaced with typed resource objects. A generic envelope
made every metric repeat its name, unit, basis, scope, sharing state, coverage, source, timestamp,
and caveats. It was technically possible to reconcile, but every new rule had to be expressed as
a matrix over metric name, location, source, unit, status, and dimensions. Typed objects put the
rule beside the value it governs: CPU evidence belongs to CPU, CUDA authority belongs to GPU,
and F3 counter rules belong to F3. This materially reduces both the wire format and the number
of invalid combinations a reader must reject.

The accepted reductions are:

- no persisted metric `name`, `unit`, `basis`, `scope`, `sharing`, `coverage`, repeated
  `observed_at`, source label, caveat list, warning list, or fixed qualification list;
- no child-computed resource-time rollups; the trusted parent/server derives them after pairing
  accepted lifecycle facts;
- `role` appears once in the frozen server roster, not in child lifecycle or participant files;
- one small context-neutral issue vocabulary replaces resource-specific reason codes;
- detailed attempts live only in participant files; `resource_summary.json` contains a compact
  roster projection and aggregate totals;
- CPU and GPU model metadata is optional, normalized, privacy-controlled, and retained where it
  helps an estimator; and
- MIG remains a supported GPU group but is absent from records and hidden in human CLI output
  when it is inapplicable.

## 1. Product output — approved

A user or estimator can answer:

- which participants were expected and which reported by the fixed cutoff;
- how long each accepted participant was observed;
- CPU-, memory-, storage-, full-GPU-, and applicable MIG-resource time;
- retained NVFlare result bytes;
- F3 remote-accepted application payload bytes and messages; and
- optional normalized CPU/GPU model information.

The default human CLI stays compact. Detailed hardware groups and diagnostic outcome buckets are
available in JSON and may later be exposed by a detail view. Every total is described as a sum of
participant-visible proxies, never as physical capacity, reservation, allocation, utilization,
or billable usage.

## 2. Identity and role — approved

Lifecycle records keep job, participant, attempt, and execution-environment identity so the
parent cannot pair records from different attempts or accept duplicate rank reporters for one
environment. The participant archive is keyed by a job-scoped HMAC participant key. The server's
frozen roster stores the participant display ID and `role: client | server` once.

Payload identity still does not authenticate itself. The parent/server must compare it with its
trusted launcher and roster context. Execution-environment keys and participant keys are
job-scoped platform HMAC values, not plain hashes of enumerable infrastructure labels.

## 3. Hardware description and privacy — approved

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

## 4. Typed capacity observations — approved

An enabled start or final observation has typed CPU, memory, storage, and GPU objects. CPU keeps
only normalized evidence used by the selector:

```text
affinity_count, cpuset_count, quota_units, optional online_count fallback
```

`quota_units` is the already-normalized quota divided by period. For example, an internal
`quota_us=150000` and `period_us=100000` becomes `quota_units="1.5"`. The raw microsecond pair is
probe-internal and is not persisted. CPU visible units are the minimum of the applicable strong
constraints; `online_count` is used only as an explicit host-visible fallback.

Memory is the smaller finite cgroup/physical byte observation. Storage is total bytes for the
filesystem containing the job run directory. GPU numeric authority requires successful CUDA-
runtime enumeration. `cuda_mask_present` is diagnostic only; the raw string and token count are
forbidden and cannot produce a numeric count.

A reported GPU inventory contains only positive groups. Absence of a full-GPU or MIG group after
successful enumeration means an observed zero for that kind. If enumeration is unavailable or
fails, no numeric GPU count is inferred. Thus ordinary clients have no MIG group or MIG display
field at all.

## 5. Lifecycle, trust, and final capacity — approved

The trusted flow is start observation, optional child final observation, and required parent exit.
Start/final facts remain child self-reports even after authenticated handoff to parent-owned,
write-once durable storage. Parent exit is a parent-observed lifecycle fact.

The full final capacity snapshot is kept whenever the child supplies a valid final record. It is
useful for detecting change and for audit; it is not a replacement for startup capacity. On a
crash or missing/invalid final record, the system does not invent a final sample from the parent
exit. Resource time still uses startup capacity over the derived observed interval and is marked
partial when the tail or capacity stability is uncertain.

Trusted bootstrap remains an implementation boundary: every launcher must start through a
platform-owned sanitized bootstrap, take the snapshot before enabling custom imports, and pass
the platform-minted attempt ID through an explicit argument allowlist.

## 6. Status and issues — approved

Point capacity uses `reported | unavailable | error`. Derived resource time, retained content,
and F3 additionally use `partial`. Global collection policy uses one `enabled | disabled` state
rather than four repeated disabled resources. Summary totals use
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

## 7. Resource-time derivation — approved

The parent/server derives each attempt interval from the accepted start time and the final time,
or the parent exit time when no final exists. It multiplies the startup capacity by that exact
interval:

```text
resource time = startup runtime-visible capacity × derived interval seconds
```

Startup is intentionally the basis; the two endpoint snapshots do not justify averaging. A
missing final or changed numeric final produces a partial result. CPU totals stay grouped by
normalized model and architecture when known. GPU totals stay grouped by kind, normalized model,
per-entity memory, and MIG profile when known. Unknown/suppressed metadata forms an unlabeled
group rather than invalidating the numeric value.

Participant files do not persist a second resource-time copy. Accepted roster entries and job
totals materialize the derived values needed for queries. `observation_seconds` is retained on an
accepted roster entry as a checked convenience: it is the sum of that participant's derived
attempt intervals, not an independently measured duration.

## 8. Retained content and F3 — approved

Retained content stores a status plus bounded entries containing normalized relative path,
`size_bytes`, and SHA-256. `artifact_id`, stored total bytes, and fixed explanatory labels are
removed. Total retained bytes derive from the entry sizes. Only regular files registered and
frozen by the platform are eligible.

F3 stores five factual outcome buckets:

1. `remote_accepted` — payload accepted by remote transport before the cutoff; this alone is the
   primary F3 total;
2. `local_delivered` — direct/local delivery, kept separately;
3. `remote_failed_before_acceptance` — attempted remote traffic that failed before acceptance;
4. `late_after_cutoff` — events after the fixed terminal cutoff; and
5. `summary_excluded` — resource-summary publication traffic excluded by a platform-owned,
   non-spoofable mechanism.

Each bucket contains application `payload_bytes` and `messages`. The terminal F3 object retains
the accepted sequence cutoff. Fixed traffic classes, sender semantics, and the exclusion
mechanism are contract/integration rules rather than repeated strings in each record.

## 9. Aggregation, replay, and storage — approved

The server freezes one roster. Each entry has identity, role, and one of
`accepted | missing | invalid | disabled`. Accepted entries add receipt time, participant-summary
digest, `observation_seconds`, and compact totals; invalid entries add receipt time and compact
issues describing the rejected candidate. The job-level `totals` has the same typed shape.
Missing/invalid/disabled entries make otherwise numeric job totals partial; if there are no
numeric contributions, the affected total is unavailable.

There is no participant `summary_revision`. That rejected field would have allowed a participant
to replace an already accepted terminal measurement before the cutoff. Replacement creates
ordering and reconciliation questions without helping normal retry delivery. Instead, the first
valid authenticated participant summary received by the cutoff wins. An identical digest retry
is an idempotent no-op; a conflicting replacement is rejected. An invalid candidate does not
reserve the participant slot. Multiple execution attempts remain distinct entries inside the
single immutable participant summary—this rule does not erase retries or relaunches.

The server archive keeps one detailed participant file per accepted roster entry, one compact
`resource_summary.json`, and a manifest containing only normalized `relative_path` and `sha256`.
The manifest covers the resource summary and exactly the accepted participant files. The exact
resource summary is the query copy stored behind the narrow `RESOURCE_STATS` save/get API.

## 10. CLI and Phase 2 — approved

The default Phase 1 CLI shows roster status, observation duration, compact typed totals, and clear
proxy qualification. It hides MIG columns and text unless positive MIG time is applicable to the
selection. JSON preserves typed hardware groups and diagnostic F3 buckets. Optional hardware
models belong in JSON and a future detail/single-site view rather than the default table.

Phase 2 may publish selected finalized values through `JobStatsReporter`. It consumes the same
validated Phase 1 materialization; it does not redefine collection authority, lifecycle pairing,
F3 semantics, or the durable evidence archive. Telemetry labels must remain bounded and explicit,
with hardware model labels optional/reviewable because of cardinality and privacy.

## Decision log

| Section | Status | Accepted decision |
| --- | --- | --- |
| 1. Product output | Approved | Compact default output; typed JSON/detail; proxy totals only. |
| 2. Identity and role | Approved | Minimal lifecycle identity; role once in frozen roster. |
| 3. Hardware description | Approved | Optional normalized CPU/GPU models with suppression policy. |
| 4. Capacity observations | Approved | Required typed resources; CUDA-only numeric GPU authority; omit inapplicable MIG groups. |
| 5. Lifecycle and trust | Approved | Durable parent handoff; preserve valid final capacity; never invent crash final. |
| 6. Status and issues | Approved | Small status domains and eight context-neutral issues. |
| 7. Resource-time | Approved | Parent/server derivation from startup × interval; model-qualified groups. |
| 8. F3 and retained content | Approved | Five F3 facts; path/size/digest retained entries. |
| 9. Aggregation and storage | Approved | Immutable first valid summary; compact roster/totals; path+digest manifest. |
| 10. CLI and Phase 2 | Approved | Adaptive human display; typed JSON; `JobStatsReporter` consumes finalized Phase 1 data. |

Future discussion may refine product defaults or implementation hooks, but it must not silently
restore removed duplication. Any stored field added later should answer: which independent fact
would be lost if a reader derived it from the surrounding typed object and schema version?
