# Runtime-visible resource statistics research prototype

This is a local, research-only companion to the NVFlare runtime resource-statistics design. It
does not change production NVFlare behavior. It combines real user-space probes, a strict typed
candidate-v1 contract, realistic golden archives, and CLI projections so the design can be
reviewed before integration.

Start with the [linear review guide](REVIEW_GUIDE.md). The
[accepted simplification decisions](SIMPLIFICATION_REVIEW.md) explain why the earlier generic
metric envelope was replaced and record all ten approved review sections.

## Which artifacts are authoritative?

| Area | Use | Do not confuse it with |
| --- | --- | --- |
| [`schema/`](schema/) | Candidate-v1 JSON Schema, executable validator, field/status catalogs, and normative goldens. | Production NVFlare implementation. |
| [`schema/golden/v1/finalized_job/`](schema/golden/v1/finalized_job/) | Coherent server archive, exact query copy, and human/JSON CLI output. | Live data from this machine. |
| [`generated/`](generated/) | Real local probe captures and review-hardening fixtures. | Candidate-v1 wire format; these predate it. |
| [`examples/`](examples/) | Earlier design exploration. | Current schema or CLI contract. |
| [`GAPS.md`](GAPS.md) | Remaining integration and policy work. | Unresolved core field design; the simplification decisions are now approved. |

The machine source of truth is the [canonical schema bundle](schema/README.md):
`resource_stats_v1.schema.json` defines closed shapes and
`contract_v1.py` enforces arithmetic, identity, ordering, aggregation, and bundle relationships
that JSON Schema alone cannot express.

## What Phase 1 measures

| Resource | Trusted observation rule | Stored fact |
| --- | --- | --- |
| GPU | Successful CUDA-runtime enumeration first; optional NVML enrichment only for matched devices. | Positive full-GPU and applicable MIG groups, with optional normalized model/memory/profile. |
| CPU | Effective affinity/cpuset and finite cgroup quota, using their minimum; online CPUs only as a fallback. | Visible CPU units and normalized selector evidence. |
| Memory | Smaller finite cgroup and physical RAM observation. | Visible bytes. |
| Storage | `statvfs` total for the filesystem containing the job run directory. | Visible filesystem-capacity bytes. |
| Retained content | Platform registry of frozen regular result files. | Relative path, exact descriptor size, and SHA-256 per entry. |
| F3 | Attempt-local counters at the CellNet sender boundary. | Five explicit application-payload outcome buckets and a cutoff. |

These are runtime-visible proxies. They are not allocation, reservation, utilization, ownership,
physical capacity, or billing claims. Participant-visible totals may overlap within a site and
across jobs.

The Linux CPU/memory selectors follow cgroup semantics: `cpu.max` expresses quota and period,
`memory.max` is the hard memory limit, and effective constraints may appear at an ancestor.
[Linux cgroup v2 documentation](https://docs.kernel.org/admin-guide/cgroup-v2.html)

`CUDA_VISIBLE_DEVICES` affects CUDA enumeration, but its raw string is diagnostic only. The
contract stores only a mask-present boolean and requires successful CUDA-runtime enumeration for
any numeric GPU inventory, including zero. NVML can enrich but cannot establish visibility or
count authority. [CUDA visibility documentation](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/environment-variables.html),
[NVML MIG API](https://docs.nvidia.com/deploy/nvml-api/group__nvmlMultiInstanceGPU.html)

## Accepted stored representation

Typed objects replace generic metric arrays. An enabled lifecycle capacity observation has CPU,
memory, storage, and GPU members. Units and meanings follow from field names and schema version;
they are not repeated in every value.

CPU evidence uses normalized `affinity_count`, `cpuset_count`, `quota_units`, or an explicit
`online_count` fallback. Raw `quota_us` and `period_us` remain internal to the probe. Optional CPU
model and architecture are reported only after normalization; a heterogeneous affinity-visible
set omits the model. Optional GPU metadata is attached only to CUDA-validated groups. Site policy
may suppress all such hardware labels without changing a numeric capacity status.

An ordinary non-MIG client has no MIG group. Within a successfully reported GPU inventory,
absence means observed zero; when CUDA enumeration is unavailable or fails, no numeric count is
inferred. The human CLI similarly omits the MIG column and MIG-specific notices unless positive
MIG instance-time is applicable.

Start/final observations are child self-reports. The parent authenticates their identity and
writes accepted bytes to parent-owned durable storage. A normal final keeps a full capacity
snapshot, retained content, and F3 facts. A crash has a parent exit but no invented final.

The server derives resource time:

```text
startup capacity × (final time or parent-exit time − startup time)
```

The startup value remains the basis even when the final value changed; the derived total then
becomes partial. The system never averages two endpoint samples.

## F3 semantics

The final record stores five factual buckets:

- `remote_accepted` — remote payload accepted for transport before the cutoff; the primary total;
- `local_delivered` — direct delivery kept separate;
- `remote_failed_before_acceptance` — remote traffic that failed before acceptance;
- `late_after_cutoff` — post-cutoff traffic excluded from the frozen total; and
- `summary_excluded` — resource-summary traffic excluded through a platform-owned non-spoofable
  path.

Each bucket has payload bytes and messages. Fixed traffic classes and mechanism names are
versioned implementation rules, not repeated record strings.

## Participant and server records

One participant file contains the detailed accepted lifecycle facts for all distinct attempts.
It has no `role`, summary revision, or materialized resource-time totals. The first valid,
authenticated participant summary received by the cutoff is immutable: an identical digest retry
is a no-op, while a different digest is rejected as a conflicting replacement.

The server summary freezes one roster. `role` appears once there. Accepted members include their
summary digest, receipt time, derived `observation_seconds`, and compact typed totals. Missing and
disabled members need only identity, role, and status; invalid members additionally retain trusted
receipt time and compact issues. Job totals use the same shape. Coverage and user-facing notices
derive from these facts.

```text
<parent-owned durable root>/resource_stats/
  attempts/<attempt_id>/start.json
  attempts/<attempt_id>/final.json          # only when a valid child final exists
  attempts/<attempt_id>/parent_exit.json
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
- [typed final record](schema/golden/v1/attempt_final.json) and
  [large-value final](schema/golden/v1/attempt_final_large_value.json);
- [participant record](schema/golden/v1/participant_summary.json);
- [server resource summary](schema/golden/v1/resource_summary.json);
- [manifest](schema/golden/v1/manifest.json);
- [human CLI](schema/golden/v1/finalized_job/cli/resources-all.txt);
- [single-site hardware detail](schema/golden/v1/finalized_job/cli/resources-site-1-details.txt); and
- [JSON CLI](schema/golden/v1/finalized_job/cli/resources-all.json).

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
It should consume this materialization rather than introducing a second collector or formula.
Hardware-model telemetry labels remain optional and require cardinality/privacy review.

See [GAPS.md](GAPS.md) for the concrete NVFlare work still needed before this prototype becomes a
product implementation.
