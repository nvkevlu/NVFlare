# Runtime resource proxy prototype

This directory turns the Phase 1 design into inspectable JSON, CLI output, and
small Python contracts. It does not implement production NVFlare integration.

## Review path

| Step | Read | Purpose |
| ---: | --- | --- |
| 1 | [Review guide](REVIEW_GUIDE.md) | Walk through the proposal in plain language. |
| 2 | [Rollup flow](ROLLUP_FLOW.md) | Follow observations through the site report, job summary, archived workspace, and CLI. |
| 3 | [Current-code integration](CURRENT_CODE_INTEGRATION.md) | See exact current hooks, terminal-outcome transport, server acceptance, archival, and CLI lookup. |
| 4 | [All-site CLI](schema/golden/v1/finalized_job/cli/resources-all.txt), [one site report](schema/golden/v1/participant_summary.json), and [job summary](schema/golden/v1/resource_summary.json) | See the user output, site input, and server rollup. |
| 5 | [Open decisions](GAPS.md) | Review the authoritative list of choices still to make. |
| 6 | [Phase 1 implementation plan](../../docs/design/job_resource_statistics_implementation_plan.md) | Discuss code placement, delivery, tests, or work breakdown. |
| 7 | [Phase 2 JobStatsReporter sketch](../../docs/design/job_resource_statistics_phase2_telemetry_sketch.md) | Discuss publication after Phase 1. |

The main design meeting can stop after step 5. The catalogs below are lookup
material for questions about an exact field or rule.

## What is included

The prototype contains:

- ordinary-user CPU, memory, GPU, and visible workspace-filesystem capacity probes;
- a closed JSON Schema and semantic validator;
- exact CPU, memory, and GPU resource-time calculations;
- an F3 counter and cutoff prototype;
- a terminal-outcome report envelope and idempotent acceptance prototype;
- server reconciliation with missing participants kept visible;
- a byte-consistent minimal `WORKSPACE` archive, manifest, and safe fixed-member
  workspace reader; and
- generated human and JSON CLI output.

The review guide is the primary overview of requirements, trust, collection
rules, formulas, and the worked example. The rollup-flow document expands the
record transformations.

## Concrete artifacts

| Artifact | What to inspect |
| --- | --- |
| [All-site text](schema/golden/v1/finalized_job/cli/resources-all.txt) | Default proposed CLI output. |
| [Site-1 detail](schema/golden/v1/finalized_job/cli/resources-site-1-details.txt) | Optional CPU and GPU model display. |
| [Site-2 detail](schema/golden/v1/finalized_job/cli/resources-site-2-details.txt) | Partial measurement evidence and an unavailable saved-result total. |
| [CLI JSON](schema/golden/v1/finalized_job/cli/resources-all.json) | Machine-readable command envelope. |
| [Site-1 report](schema/golden/v1/participant_summary.json) | One complete 37-minute, 3-second site report. |
| [Site-2 report](schema/golden/v1/participant_summary_partial_periods.json) | Two measured periods separated by a five-minute gap. |
| [Server report](schema/golden/v1/participant_summary_server.json) | Server report with no visible GPU and the saved-result total. |
| [Job summary](schema/golden/v1/resource_summary.json) | Reconciled expected participants and job totals. |
| [Finalized job fixture](schema/golden/v1/finalized_job) | Pre-archive `server_run` construction input, a minimal representative existing `WORKSPACE` archive, manifest, and CLI outputs. The unpacked input is retained only so reviewers can inspect and regenerate the ZIP; it is not a second proposed job-store component. |
| [Generation receipt](schema/golden/v1/finalized_job/generation_receipt.json) | Digests, derived totals, and the Colossus scale reference. |

Other JSON files directly under [schema/golden/v1](schema/golden/v1) are
independent boundary cases. They are valid examples, but they are not all one
job history.

## Exact technical references

| File | Purpose |
| --- | --- |
| [Current-code integration](CURRENT_CODE_INTEGRATION.md) | Exact current collection, transport, persistence, and CLI hooks. |
| [Schema guide](schema/README.md) | Record relationships and calculation rules. |
| [Field catalog](schema/FIELD_CATALOG.md) | Every field, type, unit, and bound. |
| [Code catalog](schema/CODE_CATALOG.md) | Every status, issue, end reason, and F3 class. |
| [JSON Schema](schema/resource_stats_v1.schema.json) | Closed Draft 2020-12 structure. |
| [Semantic contract](schema/contract_v1.py) | Cross-record validation and exact arithmetic. |
| [Artifact generator](schema/build_review_artifacts.py) | Deterministic source for the canonical artifacts. |
| [Runtime probe](runtime_probe.py) | Ordinary-user collection experiments. |
| [F3 finalization](f3_finalization.py) | Counter inclusion, acceptance, and cutoff behavior. |
| [Terminal report transport](terminal_report_transport.py) | Executable envelope, authenticated participant binding, validation, retry, conflict, and cutoff rules. |
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
python3 research/runtime_resource_proxy_prototype/schema/build_review_artifacts.py
python3 -m unittest discover \
  -s research/runtime_resource_proxy_prototype/tests \
  -p 'test_*.py'
~~~

The generator rewrites the standalone goldens and complete finalized-job tree,
including all digests. The tests cover schema and semantic validation, exact
arithmetic, GPU authority, F3 finalization, visible workspace-filesystem
capacity observation, terminal-report validation and replay, safe workspace
archive access, CLI output, and deterministic regeneration.

For a one-off observation of the current machine:

~~~bash
python3 research/runtime_resource_proxy_prototype/generate_artifacts.py \
  --output research/runtime_resource_proxy_prototype/generated/actual_local \
  --observation-seconds 1
~~~

That exploratory output is not a canonical schema example or deployment
design.
