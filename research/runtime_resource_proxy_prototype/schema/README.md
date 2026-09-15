# Canonical resource-statistics contract v1

This directory is the candidate Phase 1 resource-statistics contract. It supersedes exploratory
shapes under `../examples/` and `../generated/`.

Conformance requires both machine-readable parts:

- `resource_stats_v1.schema.json` fixes shapes, wire types, nullability, enums, and structural
  bounds using JSON Schema Draft 2020-12.
- `contract_v1.py` enforces duplicate-key and byte/depth limits, numeric formulas, selector
  evidence, lifecycle relationships, overlap rules, aggregate arithmetic, and bundle integrity.

`FIELD_CATALOG.md` is the human field/unit/bound index. `CODE_CATALOG.md` is the status, issue,
roster, and lifecycle-code index. Files under `golden/v1/` are executable examples.

A production reader must bound received UTF-8 bytes, reject duplicate keys, validate the schema,
run semantic validation with authenticated platform context, and only then aggregate or display a
record. A digest proves byte identity, not the truth of an untrusted worker observation.

## Version and record kinds

Every object rejects unknown fields and has exact `schema_version: "1.0"` plus one kind:

| Kind | Purpose |
| --- | --- |
| `nvflare.resource_stats.participant_start` | Durable supervisor begins participant accounting and observes persistent storage. |
| `nvflare.resource_stats.attempt_start` | Worker observes transient CPU/memory/GPU after one resource lease becomes active. |
| `nvflare.resource_stats.attempt_final` | Optional worker stability observation before lease closure. |
| `nvflare.resource_stats.attempt_end` | Lifecycle owner confirms the resource lease/window closed. |
| `nvflare.resource_stats.participant_final` | Supervisor freezes storage, retained content, and F3 once for the participant. |
| `nvflare.resource_stats.participant_summary` | Immutable participant lifecycle reconstruction. |
| `nvflare.resource_stats.resource_summary` | Server roster plus checked participant/job totals. |
| `nvflare.resource_stats.manifest` | Canonical path/digest inventory. |

This is still an unpublished prototype, so the incompatible roadmap alignment retains candidate
version `"1.0"`. After release, incompatible semantics require an explicit version transition;
readers must never silently reinterpret old bytes.

## Roadmap-compatible lifecycle

The contract separates the long-lived logical participant from short-lived compute allocations:

```text
participant_start ─────────────────────────────────── participant_final
       │                                                        │
       ├─ attempt A: opened ── start/final capacity ── closed   │
       │                all-counted-resources-released gap       │
       └─ attempt B:             opened ── capacity ── closed ──┘
```

An attempt is one stable transient resource-allocation window, not one federated job and not
necessarily one OS process. A durable GPU-free supervisor may preserve participant identity while
workers or leases are released and reacquired. The same process may produce multiple sequential
attempts through trusted acquire/release hooks. Every reacquisition gets a new `attempt_id`.

Every attempt carries supervisor-owned `opened_at`; `end.closed_at` is the time that same durable
supervisor confirms lease closure. Worker start/final bodies contain capacity only, so duration
never mixes worker and supervisor clocks. Resource time always uses `[opened_at,closed_at)`.

End reasons are `released | failed | terminated | launch_failed | reconfigured`. There is no
return code because process outcome is not the measured boundary. `launch_failed` means a lease
opened but no trusted capacity snapshot exists; it still contributes window seconds while making
transient totals unavailable/partial. All other reasons require start. Failure/termination alone
does not lower evidence quality if matching start/final capacity exists. `reconfigured` is
asserted by trusted lifecycle authority and requires a same-environment successor at that exact
boundary. Equal numeric vectors are rejected when both snapshots are comparable; an unavailable
successor remains representable. A full release and reacquisition may use `released` even when
its timestamps touch.

An accepted participant summary requires participant start and final. If the durable supervisor
never produces terminal facts/a summary, the server roster is missing or invalid rather than
accepting a half-terminal record. An individual attempt may still lack final after crash or
preemption; its trusted end preserves the interval and the affected compute totals become partial.

## Capture, handoff, and trust

1. The durable supervisor begins the participant lifecycle, captures storage, and persists a
   `participant_start` fact outside disposable worker storage.
2. On resource acquisition, it mints an attempt ID, records `opened_at`, and passes the identity
   plus an opaque supervisor-handoff locator through every launcher allowlist.
3. A platform-owned sanitized bootstrap runs before custom imports, observes CPU/memory/GPU after
   the allocation is applied, and immediately hands `attempt_start` to the supervisor.
4. The worker may hand off capacity-only `attempt_final` just before release. This is stability
   evidence only, not a clock boundary.
5. The lifecycle owner closes/releases the lease and writes supervisor-owned `closed_at` in a
   self-contained `attempt_end`, even if launch or execution failed. A later allocation starts a
   new attempt.
6. At participant finalization, the supervisor freezes persistent storage and registered retained
   content, atomically freezes all three participant-wide F3 counters, and then serializes one
   `participant_final` fact. Callback completions after the freeze are ignored.
7. It constructs one canonical participant summary. Clients send it through the terminal outcome
   path; the server participant uses equivalent local durable ingestion. Exact-byte retries are
   idempotent.

Attempt start/final capacity values are worker self-reports preserved by supervisor-owned storage.
Attempt opened/closed bounds and participant lifecycle timestamps are supervisor-observed. These trust properties come
from transport/storage context rather than a payload `trust` claim.

## Typed resource observations

Transient attempt `capacity` has exactly `cpu`, `memory`, and `gpu`:

- CPU `visible_units` is the minimum of available affinity count, effective cpuset count, and
  quota units. Raw quota/period division uses exact decimals and conservatively floors to nine
  fractional digits (`1 / 3` becomes `0.333333333`). `online_count` is used only when none is
  usable. Optional model is emitted only for a homogeneous affinity-visible CPU set and when
  policy permits.
- Memory `visible_bytes` is the minimum finite value among physical RAM and effective cgroup
  limit. Swap is excluded.
- GPU groups are numeric only when CUDA-runtime enumeration succeeds. `cuda_mask_present` is a
  diagnostic boolean; raw mask contents/token counts are forbidden. NVML may enrich matching
  CUDA-enumerated devices but cannot establish count. Optional `memory_bytes` is runtime-reported
  memory per visible entity, not aggregate group memory; differing values form separate groups.
  Full GPUs and MIG instances remain separate.

A GPU-only release closes the old vector and immediately opens a successor that may report an
empty GPU group array while CPU/memory continue. That zero requires runtime enumeration in a fresh
or CUDA-uninitialized worker/helper after the new visibility is applied. A reused CUDA-initialized
process cannot establish the new vector.

Participant `storage` is observed at participant start/final. It is `statvfs` total capacity for
the durable participant run filesystem. It is intentionally absent from attempts because that
filesystem can persist while compute workers and GPUs are released. Reported storage requires a
supervisor guarantee of continuous workspace availability; uncertain continuity uses partial (if
a numeric proxy remains usable) or unavailable/error. V1 has no storage sub-windows.

Optional hardware model/architecture labels do not change numeric status. Site policy may omit
them. Raw CPU info/flags/topology, device UUID/PCI/serial identity, host identity, absolute paths,
and raw environment values are forbidden.

## Status and issue rules

Point CPU/memory/GPU uses `reported | unavailable | error`. Participant storage, retained content,
and F3 use `reported | partial | unavailable | error`. Materialized totals use
`reported | partial | unavailable`. Disabled collection is a server roster state, not a repeated
lifecycle field.

The exact issue vocabulary is:

```text
not_bound  counter_gap  observation_incomplete  attribution_incomplete
unsupported  permission_denied  dependency_missing  malformed_source
```

Reported values carry numeric facts and no issues. Partial values carry usable facts plus issues.
Unavailable/error values carry no numeric result. The typed location narrows which issue values
are legal; see `CODE_CATALOG.md`. No separate source, coverage, caveat, warning, or qualification
lists are persisted because they would duplicate derivable facts.

## Formulas and the two clocks

For each supervisor-owned half-open `[opened_at,closed_at)` window:

```text
CPU-unit-seconds       = start CPU units × (closed_at - opened_at)
memory byte-seconds    = start memory bytes × (closed_at - opened_at)
GPU-instance-seconds   = start group count × (closed_at - opened_at)
```

`attempt_final` has no timestamp and never changes an interval endpoint. It only checks whether
numeric capacity stayed stable. A missing final, nonreported final, or numeric change makes the
affected total partial; startup capacity remains the explicit proxy.

Storage uses the participant clock exactly once:

```text
storage byte-seconds = participant-start capacity × (participant final - participant start)
```

Retained content and F3 also come exactly once from participant final. They are not summed across
resumed attempts. The accepted roster's `resource_window_seconds` is the sum of every environment
window, including launch failures; overlapping different environments can make it exceed
participant wall time. A valid summary with `attempts: []` derives reported zero transient compute
time. Launch-failed capacity is unavailable, not zero.

Products round once, when needed, to nine fractional digits using round-half-even before summing.
CPU/GPU totals are grouped by optional normalized hardware metadata. Suppressed metadata creates
an unlabeled group without invalidating the numeric value.

## F3 and retained content

The participant final has one retained-content registry snapshot and one atomic F3 counter freeze.
Retained entries are sorted registered regular files with safe relative path, size, and SHA-256;
reported empty entries means exact zero. The workspace tree is not scanned.

F3 contains three required counter pairs: `remote_accepted`, `local_delivered`, and
`remote_failed_before_acceptance`. Only remote-accepted application payload is the primary
aggregate. The lifecycle supervisor atomically freezes all three counters before serializing
participant final; callback completions after that freeze never enter canonical counters, and no
ordinal is exposed. Summary publication bypasses accounting through a platform-owned
non-spoofable path instead of being embedded in the summary itself. The exact included traffic
classes are `task_request`, `task_response`, `task_result`, `job_application`, and
`job_stream_data`. The integration excludes
`job_stream_control`, `bulk_envelope`, `workspace_transfer`, `platform_control`, `log_export`,
unknown classes, and summary publication. Because F3 belongs to the supervisor lifecycle,
applicable traffic while no GPU worker is running is still represented.

For an included message, `payload_bytes` is `len(message.payload)` after `encode_payload` and,
when enabled, end-to-end `encrypt_payload`, sampled immediately before direct delivery or
`Communicator.send`. It excludes headers, SFM/driver/TLS/network framing, transport compression,
and retransmissions. Cardinality is per destination: fan-out counts once for every destination,
and a forwarding participant counts its sender hop again. F3 therefore measures participant-hop
traffic, not unique logical data. Direct delivery increments `local_delivered`; a remote send
increments `remote_accepted` only after `Communicator.send` returns successfully, while a failure
before acceptance increments `remote_failed_before_acceptance`.

## Acceptance, aggregation, and overlap

One participant summary contains 0–4,096 unique attempts sorted by attempt ID. The higher bound
supports long allocation-per-round jobs; the independent 64 MiB record limit remains decisive.

Attempts with the same `environment_key` may be sequential but their half-open intervals cannot
overlap. Bundle validation enforces this across all participant files, preventing concurrent rank
duplicates without rejecting later reuse of an execution environment. Different environment keys
may overlap; `resource_window_seconds` deliberately sums their durations. Cross-job overlap remains
intentional and totals are never presented as physical capacity or utilization.

The fixed expected-participant roster comes from authenticated job deployment/selection state,
independently of which resource reports arrive. At cutoff, every expected member is classified
exactly once as `accepted | missing | invalid | disabled`, and that roster is immutable. The server
accepts the first valid authenticated participant digest by cutoff. An identical digest retry is
idempotent; a conflicting digest is rejected rather than treated as a revision. Role is stored once
per roster entry. Roster gaps make otherwise numeric job totals partial; no usable numeric
contribution makes them unavailable.

## Numeric representation and limits

Measured values are canonical non-negative decimal strings, never JSON numbers. This preserves
U128 products beyond JavaScript's safe-integer range. Integer strings have no sign, exponent,
decimal point, or leading zero. Fractional strings have at most nine digits and no trailing zero.

Core limits are: JSON depth 32; 4,096 attempts per participant; 10,000 roster entries; 4,096
CPU/GPU groups; 4,096 retained entries; four issues per list; 128 ASCII characters per model; and
512 bytes per safe relative path. Participant/resource summaries are bounded to 64 MiB. Exact
per-record limits are in `FIELD_CATALOG.md`.

## Manifest and query copy

The server archive is:

```text
resource_stats/
  resource_summary.json
  participants/<participant_key>.json
  manifest.json
```

The manifest contains sorted `relative_path`/`sha256` pairs for exactly the resource summary and
accepted participant files. Bundle validation recomputes membership and digests. The exact
validated `resource_summary.json` bytes are the narrow `RESOURCE_STATS` job-store query copy.

## Viewable examples

The records and finalized job tree under `golden/v1/` demonstrate sequential compute windows,
zero-GPU windows, all-compute gaps, crash/preemption recovery, persistent storage, terminal
F3/retained facts, large-number arithmetic, and unavailable CUDA. The CLI projections omit MIG
rows when MIG is inapplicable.

Regenerate and validate them from the repository root with:

```bash
python3 -B research/runtime_resource_proxy_prototype/schema/build_review_artifacts.py
```
