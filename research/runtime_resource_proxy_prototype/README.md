# Job resource statistics: implementation and design artifacts

This directory contains the exact production path now implemented in this
branch, deterministic output produced by that path, and broader design and
schema fixtures for behavior that is not implemented yet.

## Review path

| Step | Read | Purpose |
| ---: | --- | --- |
| 1 | [Split collector walkthrough](collector_walkthrough/README.md) | Run each CPU, memory, GPU, filesystem, and resource-time source separately on the verified Colossus host. |
| 2 | [Implemented path](PRODUCTION_IMPLEMENTATION.md) | Follow the exact current collect, handoff, send, accept, archive, and CLI code, including explicit limitations. |
| 3 | [Production reference output](production_reference/README.md) | Inspect files and CLI text regenerated through the production implementation. |
| 4 | [Real PyTorch Colossus E2E output](colossus_pytorch_e2e_reference/README.md) | Inspect a complete real CUDA training run, exact resource/CLI output, the GPU-runtime discovery gap it exposed, and the environment used to validate the current fix. |
| 5 | [Review guide](REVIEW_GUIDE.md) | Learn the schema and user-facing concepts in plain language. |
| 6 | [Rollup flow](ROLLUP_FLOW.md) | Follow a terminal participant report through job and study rollups. |
| 7 | [Implementation gaps](GAPS.md) | See what remains incomplete without confusing it with implemented behavior. |
| 8 | [Detailed integration design](CURRENT_CODE_INTEGRATION.md) | Review exact code hooks, the unimplemented completion-topic fallback, and the F3 implementation. |
| 9 | [Phase 1 implementation plan](../../docs/design/job_resource_statistics_implementation_plan.md) | Discuss the broader contract, tradeoffs, and remaining work. |
| 10 | [Phase 2 JobStatsReporter sketch](../../docs/design/job_resource_statistics_phase2_telemetry_sketch.md) | Discuss finalized-summary publication and the deferred periodic-capacity direction. |

For a review of what this branch actually does, steps 1 through 4 and step 7
are enough.
The catalogs below are lookup material for exact field and validation rules.

## The whole flow in plain language

1. Each client or server job process observes its visible CPU, memory, and GPU
   capacity before custom job imports and accumulates capacity-time in memory.
2. When that process finishes, cleanup stops new application commands, lets
   already-admitted callbacks and F3 sends settle within fixed bounds, and
   writes one private `terminal_handoff.json` in the existing run workspace.
3. The long-lived client or server parent freezes its own job-scoped F3
   counter, validates that fixed handoff, checked-merges parent and child F3,
   binds the trusted participant name, and creates the only public
   `participant_summary`.
4. A client parent frees launcher-managed compute resources and sends those
   exact report bytes once with the existing authenticated completion request.
   The server parent submits its own report to the same acceptance code
   locally.
5. The root server validates each expected participant report and retains the
   first accepted canonical bytes until the existing job-completion cutoff.
6. At cutoff it reconciles accepted and missing participants, writes accepted
   participant files, writes `resource_summary.json` last, and saves everything
   only in the normal `WORKSPACE` archive.
7. `nvflare job resources --job ...` reads one retained workspace;
   `nvflare job resources --study ...` reads matching retained workspaces and
   builds an on-demand study total. No separate `RESOURCE_STATS` store exists.

CPU, memory, GPU resource time, workspace-filesystem capacity, and F3 are bound
in production. Saved-result bytes remain `unavailable/not_bound` until a
workflow owner can identify a complete bounded retained-result set.

### Production code map

| Part of the flow | Main files |
| --- | --- |
| Observe capacity and accumulate resource time | [`resource_stats/probes`](../../nvflare/private/fed/resource_stats/probes), [`accumulator.py`](../../nvflare/private/fed/resource_stats/accumulator.py), and [`collector.py`](../../nvflare/private/fed/resource_stats/collector.py) |
| Classify and count F3 sends | [`f3_counter.py`](../../nvflare/private/fed/resource_stats/f3_counter.py), [`f3_bindings.py`](../../nvflare/private/fed/resource_stats/f3_bindings.py), and [`send_accounting.py`](../../nvflare/fuel/f3/send_accounting.py) |
| Close the child and transfer its private result | [`job_process_cleanup.py`](../../nvflare/private/fed/app/job_process_cleanup.py) and [`handoff.py`](../../nvflare/private/fed/resource_stats/handoff.py) |
| Assemble client/server reports | [`client_executor.py`](../../nvflare/private/fed/client/client_executor.py), [`job_runner.py`](../../nvflare/private/fed/server/job_runner.py), and [`collector.py`](../../nvflare/private/fed/resource_stats/collector.py) |
| Authenticate, validate, reduce, and publish | [`fed_server.py`](../../nvflare/private/fed/server/fed_server.py), [`coordinator.py`](../../nvflare/private/fed/resource_stats/coordinator.py), and [`contract.py`](../../nvflare/private/fed/resource_stats/contract.py) |
| Read the archived result for CLI queries | [`archive_reader.py`](../../nvflare/private/fed/resource_stats/archive_reader.py), [`job_cmds.py`](../../nvflare/private/fed/server/job_cmds.py), and [`job_cli.py`](../../nvflare/tool/job/job_cli.py) |

## What is included

The implementation and its supporting prototype contain:

- ordinary-user CPU, memory, and visible workspace-filesystem capacity probes,
  plus production CUDA Runtime enumeration, metadata-owned discovery of one
  allowlisted NVIDIA runtime under pre-custom-import roots, CUDA Driver identity
  lookup, and optional NVML enrichment;
- a closed JSON Schema and semantic validator;
- one terminal site report containing internally accumulated CPU, memory, and
  GPU resource time, a final workspace-filesystem observation, and typed
  saved-result/F3 objects;
- production F3 ownership, trusted bindings for deployment, real task
  responses, and task results, origin-only send accounting, a fixed cutoff,
  and checked child/parent merge; the focused suite passes, while a new live
  process-mode reference remains to be captured;
- a production Option A completion/report envelope, direct canonical-byte
  duplicate/conflict comparison, and a bounded live accepted-byte ledger, plus
  a separate prototype for expanded fallback/retry behavior;
- production server reconciliation with missing participants kept visible;
- an internally consistent minimal `WORKSPACE` resource namespace with local
  summary-last publication and a reader that validates the summary and its
  derived namespace; a `--site` read additionally validates that selected
  participant's schema, identity, and copied values; and
- production human and JSON CLI rendering, including an on-demand study
  rollup.

The implemented-path document is the authority for current behavior. The
review guide introduces requirements, trust, formulas, and the broader worked
example; the rollup-flow document expands the record transformations.

## Completion transport

The implemented path attaches the optional report to the one existing
authenticated `REPORT_JOB_FAILURE` / `report_job_failure` request. The client
makes one application-level send and the flat reply carries
`resource_report_status`. There is no report retry loop or receipt tombstone.

A versioned `REPORT_JOB_COMPLETION` request remains a documented fallback if
reviewers reject the historical topic name or handler ownership. It is not
implemented or registered in this branch. See
[Implemented path](PRODUCTION_IMPLEMENTATION.md#2-parent-assembly-and-one-client-send)
for the exact current behavior.

The earlier [NumPy Colossus smoke run](colossus_e2e_reference/README.md) remains
useful as a successful system-runtime GPU-discovery case. The PyTorch run in
step 4 is the primary live reference because it exercises a substantial CUDA
workload and preserves the earlier safe failure when its NVIDIA runtime was not
system-loader-resolvable. The current collector closes that specific gap by
loading one unique, contained runtime owned by an allowlisted NVIDIA
distribution under roots frozen before custom imports. It does not import
Torch or require an environment change, configuration, privilege, subprocess,
or report-format addition. Legacy `torch`-owned runtimes and conda-only layouts
remain outside the initial adapter and fail closed.

## Concrete artifacts

The authoritative implemented outputs are under
[production_reference](production_reference/README.md). They are regenerated
through the production collector, coordinator, archive reader, and CLI
renderers:

| Artifact | What to inspect |
| --- | --- |
| [Production job CLI](production_reference/artifacts/cli/resources-job.txt) | Exact default text from the implemented renderer. |
| [Production site detail](production_reference/artifacts/cli/resources-site-1.txt) | Exact optional model and filesystem detail. |
| [Production study CLI](production_reference/artifacts/cli/resources-study.txt) | Exact on-demand retained-job view. |
| [Production site report](production_reference/artifacts/workspace/resource_stats/participants/site-1.json) | Exact accepted client record with a readable participant name. |
| [Production job summary](production_reference/artifacts/workspace/resource_stats/resource_summary.json) | Exact implemented rollup. |

The following broader goldens are design and contract examples. Some include
reported F3 or retained-content values that are not claims about the older
captured live runs. Retained content still has no general authoritative source;
F3 has production bindings and passing focused/socket-backed suites, but no new
process-mode live reference yet. See
[F3 implementation status](F3_GAP.md#validation-status):

| Artifact | What to inspect |
| --- | --- |
| [One-job text](schema/golden/v1/finalized_job/cli/resources-all.txt) | Default proposed output with every expected participant. |
| [Study text](schema/golden/v1/finalized_job/cli/resources-study.txt) and [study JSON](schema/golden/v1/finalized_job/cli/resources-study.json) | On-demand view across retained jobs in one study. |
| [Site-1 detail](schema/golden/v1/finalized_job/cli/resources-site-1-details.txt) | Optional CPU and GPU model display. |
| [Site-2 detail](schema/golden/v1/finalized_job/cli/resources-site-2-details.txt) | Partial measurement evidence and an unavailable saved-result total. |
| [CLI JSON](schema/golden/v1/finalized_job/cli/resources-all.json) | Machine-readable command envelope. |
| [Site-1 report](schema/golden/v1/participant_summary.json) | One complete terminal site report. |
| [Site-2 report](schema/golden/v1/participant_summary_partial.json) | A terminal report whose single compute status explains incomplete resource time. |
| [Server report](schema/golden/v1/participant_summary_server.json) | A terminal server report with no visible GPU and the saved-result total. |
| [Job summary](schema/golden/v1/resource_summary.json) | Reconciled expected participants and job totals. |
| [Study summary](schema/golden/v1/study_summary.json) | Derived coverage, per-job inclusion state, and totals across retained jobs. |
| [Finalized job fixture](schema/golden/v1/finalized_job) | Pre-archive `server_run` construction input, a minimal representative existing `WORKSPACE` archive, and CLI outputs. The unpacked input is retained only so reviewers can inspect and regenerate the ZIP; it is not a second proposed job-store component. |
| [Generation receipt](schema/golden/v1/finalized_job/generation_receipt.json) | Derived totals and the Colossus scale reference. |

Other JSON files directly under [schema/golden/v1](schema/golden/v1) are
independent boundary cases. They are valid examples, but they are not all one
job history.

## Exact technical references

| File | Purpose |
| --- | --- |
| [Implemented path](PRODUCTION_IMPLEMENTATION.md) | Exact current collection, transport, persistence, and CLI hooks. |
| [F3 implementation status](F3_GAP.md) | Exact traffic semantics, production bindings, cutoff/merge behavior, and remaining proof. |
| [Detailed integration design](CURRENT_CODE_INTEGRATION.md) | Deeper target behavior and fallback alternatives; clearly distinguish these from implemented code. |
| [Schema guide](schema/README.md) | Record relationships and calculation rules. |
| [Field catalog](schema/FIELD_CATALOG.md) | Every field, type, unit, and bound. |
| [Code catalog](schema/CODE_CATALOG.md) | Every status, issue, participant state, and F3 class. |
| [JSON Schema](schema/resource_stats_v1.schema.json) | Closed Draft 2020-12 structure. |
| [Semantic contract](schema/contract_v1.py) | Cross-record validation and exact arithmetic. |
| [Artifact generator](schema/build_review_artifacts.py) | Deterministic source for the canonical artifacts. |
| [Runtime probe](runtime_probe.py) | Ordinary-user collection experiments. |
| [Legacy F3 fixture](f3_finalization.py) | Simplified deterministic input for standalone contract tests; production F3 behavior is defined by `F3_GAP.md` and the production code anchors listed there. |
| [Terminal report transport](terminal_report_transport.py) | Prototype of expanded retry/conflict/cutoff behavior; it is not the production client send loop. |
| [Prototype contracts](prototype_contract.py) | Reporter, workspace-file, and fixed-member workspace-archive reader. |
| [Behavior fixtures](review_contract_fixtures.py) | Synthetic cases a standalone process cannot observe. |

Optional background:

- [Simplification history](SIMPLIFICATION_REVIEW.md) records decisions already
  made and why earlier fields were removed.
- [Generated-output note](generated/README.md) explains one-off local probe
  output for prototype developers.

Neither is part of the main review path.

## Rebuild and test

From the repository root:

~~~bash
python3 research/runtime_resource_proxy_prototype/production_reference/generate_reference.py --check
python3 -m pytest -q \
  research/runtime_resource_proxy_prototype/production_reference/test_reference_artifacts.py
python3 research/runtime_resource_proxy_prototype/schema/build_review_artifacts.py
python3 -m unittest discover \
  -s research/runtime_resource_proxy_prototype/tests \
  -p 'test_*.py'
~~~

The production reference check proves the exact checked-in outputs still match
the implementation. The schema generator rewrites the broader standalone
goldens and complete finalized-job tree. The tests cover schema and semantic
validation, resource-time accumulation, GPU authority, F3 finalization, the one final
workspace-filesystem capacity observation, terminal-report validation and
replay, safe workspace archive access, job and study CLI output, and
deterministic regeneration.

For a one-off observation of the current machine:

~~~bash
python3 research/runtime_resource_proxy_prototype/generate_artifacts.py \
  --output research/runtime_resource_proxy_prototype/generated/actual_local \
  --observation-seconds 1
~~~

That exploratory output is not a canonical schema example or deployment
design.
