# Generated outputs

This directory is reserved for temporary local probe runs. Its contents are
ignored by Git because machine values and timestamps vary.

The old local captures were removed: they predated canonical v1 and contained
superseded design experiments. Do not use a newly generated local capture as a
schema example.

## Current review artifacts

The reproducible review set lives in the
[canonical v1 finalized-job tree](../schema/golden/v1/finalized_job/):

- [generation receipt](../schema/golden/v1/finalized_job/generation_receipt.json)
- [server resource summary](../schema/golden/v1/finalized_job/server_run/resource_stats/resource_summary.json)
- [all-site CLI output](../schema/golden/v1/finalized_job/cli/resources-all.txt)
- [study CLI output](../schema/golden/v1/finalized_job/cli/resources-study.txt)
- [one-site CLI with hardware details](../schema/golden/v1/finalized_job/cli/resources-site-1-details.txt)
- [partial site CLI output](../schema/golden/v1/finalized_job/cli/resources-site-2-details.txt)
- [JSON CLI output](../schema/golden/v1/finalized_job/cli/resources-all.json)

The full typed record set is in [schema/golden/v1](../schema/golden/v1/).

Rebuild it from the repository root:

~~~bash
python3 research/runtime_resource_proxy_prototype/schema/build_review_artifacts.py
~~~

For a one-off observation of the current machine, use
`generate_artifacts.py --output generated/actual_local`. That output is probe
evidence only. It uses the same one-terminal-report shape, but it is not a
deployment or performance result. The inspectable private child handoff is
written to
`client_child/resource_stats/staging/terminal_handoff.json`; the client
parent's public record is
`client_parent/resource_stats/participant_summary.json`. The private handoff
is the only file in child staging. Research-only raw probe evidence is kept
separately at `prototype_diagnostics/probe_evidence.json`; neither file enters
the generated job workspace archive.
