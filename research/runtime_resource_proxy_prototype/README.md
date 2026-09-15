# Runtime-visible resource statistics research prototype

This is a local, research-only companion to the NVFlare runtime resource-statistics design. It
does not change production NVFlare behavior. It combines real user-space probes, a strict typed
candidate-v1 contract, realistic golden archives, and CLI projections so the design can be
reviewed before integration.

Start with the [linear review guide](REVIEW_GUIDE.md). The
[candidate simplification decisions](SIMPLIFICATION_REVIEW.md) explain why the earlier generic
metric envelope was replaced and organize all ten sections for review.

## Which artifacts are authoritative?

| Area | Use | Do not confuse it with |
| --- | --- | --- |
| [`schema/`](schema/) | Candidate-v1 JSON Schema, executable validator, field/status catalogs, and normative goldens. | Production NVFlare implementation. |
| [`schema/golden/v1/finalized_job/`](schema/golden/v1/finalized_job/) | Coherent server archive, exact query copy, and human/JSON CLI output. | Live data from this machine. |
| [`generated/`](generated/) | Real local probe captures and review-hardening fixtures. | Candidate-v1 wire format; these predate it. |
| [`examples/`](examples/) | Earlier design exploration. | Current schema or CLI contract. |
| [`GAPS.md`](GAPS.md) | Remaining integration and policy work. | The reviewable candidate contract itself. |

The machine source of truth is the [canonical schema bundle](schema/README.md):
`resource_stats_v1.schema.json` defines closed shapes and
`contract_v1.py` enforces arithmetic, identity, ordering, aggregation, and bundle relationships
that JSON Schema alone cannot express.

## What Phase 1 measures

The [roadmap](../../docs/roadmap.rst) requires the logical job to survive while GPUs are released
during aggregation, barriers, and downloads. The contract therefore uses two clocks:

```text
logical participant:  start --------------------------------------------- final
attempt A:              CPU + memory + GPU ===== reconfigured
attempt B:                                   CPU + memory + zero GPU ===== reconfigured
attempt C:                                                                  CPU + memory + GPU ===== release
```

The durable site supervisor owns the logical participant and holds no job GPU. Each **attempt**
is one stable `(resource lease, reporter environment, CPU/memory/GPU vector)` window, not
necessarily an entire scheduler allocation. A GPU-only release ends the old vector and opens a
CPU/memory-plus-zero-GPU successor if those resources remain held. Only full release of every
counted compute resource creates a no-attempt gap.

| Lifecycle | Resource/fact | Observation rule | Stored fact |
| --- | --- | --- | --- |
| Resource window | GPU | Successful CUDA-runtime enumeration after acquire; optional NVML enrichment only for matched devices. | Positive full-GPU and applicable MIG groups, with optional normalized model/memory/profile. |
| Resource window | CPU | Effective affinity/cpuset and finite cgroup quota after acquire, using their minimum; online CPUs only as a fallback. | Visible CPU units and normalized selector evidence. |
| Resource window | Memory | Smaller finite cgroup and physical RAM observation after acquire. | Visible bytes. |
| Logical participant | Storage | Supervisor `statvfs` total for the persistent job-run filesystem at participant start/final. | Visible filesystem-capacity bytes. |
| Logical participant | Retained content | Supervisor freezes the platform registry of regular result files once at participant finalization. | Relative path, exact descriptor size, and SHA-256 per entry. |
| Logical participant | F3 | All-job counters at the trusted CellNet sender boundary, across worker release/resume. | Three application-payload outcome buckets atomically frozen before participant-final serialization. |

These are runtime-visible proxies. They are not utilization, ownership, physical capacity, or
billing claims. The trusted resource-manager release event supplies the window boundary, but its
declared resource quantity does not replace runtime capacity observation. Participant-visible
totals may overlap within a site and across jobs. The shared supervisor's CPU/memory overhead is
not charged to every participant.

The Linux CPU/memory selectors follow cgroup semantics: `cpu.max` expresses quota and period,
`memory.max` is the hard memory limit, and effective constraints may appear at an ancestor.
[Linux cgroup v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html)

`CUDA_VISIBLE_DEVICES` affects CUDA enumeration, but its raw string is diagnostic only. The
contract stores only a mask-present boolean and requires successful CUDA-runtime enumeration for
any numeric GPU inventory, including zero. NVML can enrich but cannot establish visibility or
count authority. [CUDA visibility documentation](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/environment-variables.html),
[NVML MIG API](https://docs.nvidia.com/deploy/nvml-api/group__nvmlMultiInstanceGPU.html)

## Candidate stored representation

Typed objects replace generic metric arrays. An accepted attempt capacity observation has CPU,
memory, and GPU members; participant start/final has storage. Units and meanings follow from
field names and schema version; they are not repeated in every value.

CPU evidence uses normalized `affinity_count`, `cpuset_count`, `quota_units`, or an explicit
`online_count` fallback. `quota_units` is the exact quota/period ratio floored to at most nine
fractional decimal digits, so normalization cannot overstate visible capacity. Raw `quota_us` and
`period_us` remain internal to the probe. Optional CPU model and architecture are reported only
after normalization; a heterogeneous affinity-visible set omits the model. Optional GPU metadata
is attached only to CUDA-validated groups. GPU `memory_bytes` is per visible entity, and differing
values produce separate groups. Site policy may suppress all such hardware labels without
changing a numeric capacity status.

An ordinary non-MIG client has no MIG group. Within a successfully reported GPU inventory,
absence means observed zero; when CUDA enumeration is unavailable or fails, no numeric count is
inferred. The human CLI similarly omits the MIG column and MIG-specific notices unless positive
MIG instance-time is applicable.

Every GPU-vector transition is probed after new visibility is applied in a fresh,
CUDA-uninitialized worker or platform helper. An already CUDA-initialized process is not assumed
to rediscover a changed visibility mask. A CPU/memory successor reports zero GPU only after a
successful empty CUDA-runtime enumeration; otherwise GPU is unavailable and its total is
partial/unavailable.

Attempt start/final capacity snapshots are resource-worker self-reports and have no duration
timestamps. The durable lifecycle owner supplies **opened_at** at confirmed acquisition, before
bootstrap, and **attempt_end.closed_at** after release/reconfiguration confirmation using one
clock. Bootstrap time therefore counts. The supervisor immediately stores accepted bytes outside
the disposable allocation. A crash or preemption has an end but no invented final.

Fresh workers enter an absolute platform-owned bootstrap artifact with `python -I -S`, a
platform-owned cwd, and a fixed minimal pre-Python environment allowlist. Using `-S -m` is not
enough because cwd can shadow the module. The launcher allowlists the attempt ID and opaque
supervisor-handoff locator, and custom import paths are enabled only after the snapshot is
accepted.

A GPU-only change ends the old vector with **reconfigured** and opens its CPU/memory-plus-zero-GPU
successor at the same timestamp. A launch failure after acquisition retains `opened_at` and
`closed_at` without a capacity snapshot: its duration counts, while transient totals are partial
or unavailable.

`reconfigured` is asserted by the trusted lifecycle authority and requires an immediate
same-environment successor. When both snapshots are comparable, they must differ; an unavailable
successor snapshot is allowed and makes affected totals partial or unavailable. The converse is
not true: a fully released lease may be reacquired at the same timestamp with a different vector
and still uses the normal release/reacquire lifecycle.

The supervisor also owns one participant start and one participant final. Those platform facts
hold the two storage observations and, at finalization, retained content and all-job F3 exactly
once. They are not repeated for every resumed worker.

The server derives resource time on the matching lifecycle:

```text
attempt-start CPU/memory/GPU × (end.closed_at − opened_at)
participant-start storage × (participant-final − participant-start)
```

The start value remains the basis even when the corresponding final value changed; the derived
total then becomes partial. The system never averages endpoint samples. A GPU-only interval adds
zero GPU time but still adds CPU/memory time when those resources remain held. Only a full-release
gap adds zero to every transient total. Storage time and F3 may continue across either case.

One scheduler allocation may contain concurrent reporter environments, each with its own attempt.
`resource_window_seconds` sums those environment windows and can exceed wall time. Storage time
requires the supervisor to guarantee continuous workspace availability across release/resume;
otherwise it is partial or unavailable.

## F3 semantics

The participant final stores three factual buckets exactly once for the logical job:

- `remote_accepted` — remote payload accepted for transport before the participant-final counter freeze; the primary total;
- `local_delivered` — direct delivery kept separate;
- `remote_failed_before_acceptance` — remote traffic that failed before acceptance.

Each bucket has payload bytes and messages. The durable participant owner atomically freezes all
three counters before participant-final serialization; callbacks completing afterward are ignored
for canonical totals. Fixed traffic classes, atomic-freeze behavior, and the non-spoofable,
platform-only summary-publication exclusion path are versioned platform behavior, not repeated
record strings or circular counters inside the summary.

Included classes are exactly `task_request`, `task_response`, `task_result`, `job_application`,
and `job_stream_data`. Excluded classes are `job_stream_control`, `bulk_envelope`,
`workspace_transfer`, `platform_control`, `log_export`, unknown classes, and summary publication.
Bytes are `len(message.payload)` after encoding and optional end-to-end encryption, immediately
before direct delivery or remote send; headers, lower-level framing, network/TLS overhead,
compression effects, and retransmissions do not count. One message is counted per destination and
again at each forwarding sender hop. Remote counts advance only on send acceptance; direct
delivery remains separate.

## Participant and server records

One participant file contains one logical participant start/final and the detailed accepted facts
for all distinct stable environment-vector windows. Multiple attempts are normal when GPUs are
reconfigured or fully released and later reacquired; they do not imply retries. It has no `role`,
summary revision, or materialized
resource-time totals. The first valid,
authenticated participant summary received by the cutoff is immutable: an identical digest retry
is a no-op, while a different digest is rejected as a conflicting replacement.

The server sources participant identity and role from authenticated job-selection/deployment
state, never from resource-report arrivals. At the report cutoff it snapshots and classifies that
membership as the immutable expected-participant roster, so a missing report cannot hide its own
slot. `role` appears once there. Accepted members include their summary digest, receipt time, derived
`resource_window_seconds`, and compact typed totals. Missing and disabled members need only
identity, role, and status; invalid members additionally retain trusted receipt time and compact
issues. Job totals use the same shape. Coverage and user-facing notices derive from these facts.

Each client supervisor sends one terminal participant summary to the server. The server
parent/job supervisor owns the same lifecycle for `role: server` and uses local durable ingestion
instead of sending to itself. Role remains stored once in the fixed roster.

```text
<supervisor-owned durable root>/<job_id>/<participant_key>/
  participant_start.json
  attempts/<attempt_id>/start.json
  attempts/<attempt_id>/final.json          # only when a valid worker final exists
  attempts/<attempt_id>/end.json
  participant_final.json
  participant_summary.json

<server job archive>/resource_stats/
  participants/<participant_key>.json
  resource_summary.json
  manifest.json
```

The manifest contains only canonical `relative_path` and `sha256` pairs for the resource summary
and exactly one file per accepted participant. The validated resource summary is copied byte for
byte into the exact `RESOURCE_STATS` job-store component behind narrow save/get APIs; a generic
`DataTypes` prefix expansion must not authorize arbitrary `RESOURCE_STATS_*` components.

## View and regenerate artifacts

The most useful directly viewable paths are:

- [typed startup record](schema/golden/v1/attempt_start.json);
- [participant start](schema/golden/v1/participant_start.json) and
  [participant final](schema/golden/v1/participant_final.json);
- [typed attempt final](schema/golden/v1/attempt_final.json),
  [preemption end](schema/golden/v1/attempt_end_terminated.json);
- [normal multi-window participant](schema/golden/v1/participant_summary.json) and
  [preempt/resume participant](schema/golden/v1/participant_summary_preempted_resume.json);
- [server resource summary](schema/golden/v1/resource_summary.json);
- [manifest](schema/golden/v1/manifest.json);
- [human CLI](schema/golden/v1/finalized_job/cli/resources-all.txt);
- [partial preempt/resume CLI](schema/golden/v1/finalized_job/cli/resources-preempted-resume.txt);
- [complete selected-site output with hardware detail](schema/golden/v1/finalized_job/cli/resources-site-1-details.txt); and
- [JSON CLI](schema/golden/v1/finalized_job/cli/resources-all.json).

The normal participant golden has three contiguous vector windows over 480 seconds. CPU and
memory remain held for all 480 seconds; GPU is present only for 60 + 120 = 180 seconds. The
preempt/resume golden is deliberately different: all counted compute resources are released for
300 seconds, so it has a real no-attempt gap and partial transient totals.

The human outputs deliberately separate report-acceptance **STATUS** from measurement **QUALITY**,
label summed reporter-environment time **ENV WINDOW**, label the primary payload counter **F3
REMOTE**, and qualify the aggregate as accepted-report totals rather than physical capacity.

Regenerate and validate the coherent candidate-v1 review tree from the repository root:

```bash
python3 -B research/runtime_resource_proxy_prototype/schema/build_review_artifacts.py
python3 -B -m unittest discover \
  -s research/runtime_resource_proxy_prototype/tests -p 'test_canonical_schema.py'
```

Capture actual local user-space values into a fresh pre-v1 evidence directory:

```bash
python3 research/runtime_resource_proxy_prototype/generate_artifacts.py \
  --output research/runtime_resource_proxy_prototype/generated/actual_local \
  --observation-seconds 1
```

`runtime_probe.py` uses only the standard library and leaves GPU enumeration as an adapter seam.
Do not treat a local host fallback or an unavailable GPU/F3 adapter as production support.

## Phase 2

Phase 1 owns collection, validation, durable evidence, server finalization, query storage, and
CLI semantics. Phase 2 can use `JobStatsReporter` to publish selected finalized Phase 1 values.
It starts only after Phase 1 finalization and consumes this materialization rather than receiving
per-window open/reconfiguration/close events or introducing a second collector or formula.
Hardware-model telemetry labels remain optional and require cardinality/privacy review.

See [GAPS.md](GAPS.md) for the concrete NVFlare work still needed before this prototype becomes a
product implementation.
