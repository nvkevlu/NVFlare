# Runtime resource proxy prototype

This directory turns the Phase 1 design into inspectable JSON, CLI output, and
small Python contracts.

Start with [REVIEW_GUIDE.md](REVIEW_GUIDE.md). It explains the design in plain
language and links the detailed files.

## What this prototype does

It demonstrates:

- ordinary-user CPU, memory, GPU, and filesystem probes;
- a closed JSON Schema with exact types and bounds;
- resource-time calculations;
- F3 counter behavior;
- one final report per expected participant;
- exact server storage and manifest hashes; and
- human and JSON CLI output.

It does not implement production NVFlare integration.

## What it does not require

The prototype and proposed product behavior require no:

- root access or privileged container;
- host agent or sidecar;
- Docker socket, additional Kubernetes RBAC permissions, cloud permission, or
  Slurm administration;
- new volume or mount;
- launcher argument or environment variable; or
- operator or job configuration.

The old hardening experiment prescribed process-specific bootstrap and launch
changes. Those were not approved requirements and have been removed.

## Architecture boundary

The schema does not choose whether CP, a job process, a child process, or
another NVFlare component records the data.

In the JSON, an **attempt** is one measurement period. It contains the resource
values observed at the start and the time for which that observation applies.
A later period is independent. A resource change does not require a successor
period.

The exact process model and call sites remain open.

## Important trust statement

Site observations are self-reported. Prototype fragments are written in the
existing job workspace and can be changed or lost before the server receives
the final report.

After receipt, the server validates the report and stores the exact accepted
bytes. A digest proves that stored bytes did not change; it does not prove that
the original observation was true.

No separate protected site directory is required.

## File map

| File | Purpose |
| --- | --- |
| [REVIEW_GUIDE.md](REVIEW_GUIDE.md) | Linear design walkthrough. |
| [schema/README.md](schema/README.md) | Exact schema and calculation guide. |
| [schema/FIELD_CATALOG.md](schema/FIELD_CATALOG.md) | Field types, units, and limits. |
| [schema/CODE_CATALOG.md](schema/CODE_CATALOG.md) | Status, issue, and end-reason codes. |
| [schema/resource_stats_v1.schema.json](schema/resource_stats_v1.schema.json) | JSON Schema. |
| [schema/contract_v1.py](schema/contract_v1.py) | Semantic validation and formulas. |
| [schema/build_review_artifacts.py](schema/build_review_artifacts.py) | Deterministic golden generator. |
| [runtime_probe.py](runtime_probe.py) | Ordinary-user probe experiments. |
| [f3_finalization.py](f3_finalization.py) | F3 counter cutoff prototype. |
| [prototype_contract.py](prototype_contract.py) | Reporter, workspace-file, and server-component contracts. |
| [review_contract_fixtures.py](review_contract_fixtures.py) | Synthetic fixtures for behavior that a standalone process cannot observe. |
| [GAPS.md](GAPS.md) | Open integration decisions. |
| [SIMPLIFICATION_REVIEW.md](SIMPLIFICATION_REVIEW.md) | Short decision history. |

## Canonical examples

The schema-validated examples are under [schema/golden/v1](schema/golden/v1).

The main site report is
[participant_summary.json](schema/golden/v1/participant_summary.json). It uses
one stable eight-minute measurement period.

The partial example is
[participant_summary_partial_periods.json](schema/golden/v1/participant_summary_partial_periods.json).
It has two recorded periods and incomplete evidence. It is an example only and
does not prescribe the future process architecture.

CLI examples:

- [all sites](schema/golden/v1/finalized_job/cli/resources-all.txt)
- [one site with hardware details](schema/golden/v1/finalized_job/cli/resources-site-1-details.txt)
- [JSON](schema/golden/v1/finalized_job/cli/resources-all.json)
- [partial multi-period output](schema/golden/v1/finalized_job/cli/resources-partial-periods.txt)

## Key collection rules

### CPU

Use the smallest available strong limit from affinity, CPU set, and finite
quota. Use online CPU count only as a fallback.

The stored quota value is quota divided by period, rounded down to at most nine
decimal places. Raw quota microseconds are not stored.

### Memory

Use the smaller finite value from the process-visible memory limit and physical
memory. Do not add swap.

### GPU

A numeric GPU count requires successful CUDA-runtime enumeration. A raw
CUDA_VISIBLE_DEVICES value is diagnostic only.

NVML may add model and memory details for CUDA-found devices. It cannot create
a count. Full GPUs and MIG instances remain separate, and MIG is omitted when
it is not present.

### Storage and saved results

Read the capacity of the filesystem that contains the existing job workspace.
Record exact sizes only when existing NVFlare state has a complete, bounded
list of result files. Otherwise mark the value unavailable. Do not add a
registry or job setting.

### F3

Keep remote accepted, local delivered, and remote failed-before-acceptance
counters separate. The schema stores application payload bytes, not network or
billing bytes.

## Rebuild the canonical artifacts

From the repository root:

~~~bash
python3 research/runtime_resource_proxy_prototype/schema/build_review_artifacts.py
~~~

The generator rewrites the standalone goldens and the finalized-job tree. It
also writes a receipt with the important derived values and SHA-256 digests.

## Run the tests

~~~bash
python3 -m unittest discover \
  -s research/runtime_resource_proxy_prototype/tests \
  -p 'test_*.py'
~~~

The tests cover JSON Schema validation, semantic validation, exact arithmetic,
GPU authority, F3 finalization, server storage, CLI output, and deterministic
regeneration.

## Capture actual local values

The local probe is exploratory and predates the canonical v1 schema:

~~~bash
python3 research/runtime_resource_proxy_prototype/generate_artifacts.py \
  --output research/runtime_resource_proxy_prototype/generated/actual_local \
  --observation-seconds 1
~~~

It reports only what that ordinary process can observe. Missing CUDA or F3
integration is shown as unavailable rather than fabricated.

The output under generated/actual_local is historical evidence, not the
canonical example.

## Production gaps

This standalone prototype cannot decide:

- which NVFlare component starts and ends a measurement period;
- how the first observation runs before job code can influence it;
- how the measurement-scope key is derived;
- how much crash recovery is possible with existing storage;
- which existing authenticated message carries the final site report; or
- which resource-management architecture the roadmap will choose.

These are listed in [GAPS.md](GAPS.md). None may be solved by adding deployment
privileges or user configuration.
