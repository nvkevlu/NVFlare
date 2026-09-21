# Production reference output

This directory shows the exact files and text produced by the current
production implementation. It is separate from the broader design goldens:
the design goldens can illustrate planned hooks, while these files include
only data the implementation can produce today.

See the [implemented-path walkthrough](../PRODUCTION_IMPLEMENTATION.md) for
when each record is collected, sent, accepted, archived, and queried.

The generator sends controlled, realistic inputs through the same code path
used by a job:

1. `JobResourceCollector` integrates runtime-visible capacity using private
   monotonic clock readings.
2. The child writes and the parent reads the fixed terminal handoff.
3. `assemble_participant_summary` binds the trusted participant name.
4. `ResourceStatsCoordinator` validates each report and writes the final
   `resource_stats` bundle under the normal server run directory.
5. An in-memory normal `WORKSPACE` ZIP is read by
   `WorkspaceResourceStatsReader`, including exact summary-derived inventory
   and cross-record reconciliation.
6. The production job and study renderers produce the CLI text.

No prototype aggregation or formatting code is copied into the generator.
The fixture controls clocks, capacities, timestamps, and filesystem capacity
observations so regeneration is deterministic. Those are inputs to the
production code, not precomputed output values.

## What is here

- [`artifacts/workspace/resource_stats/participants/site-1.json`](artifacts/workspace/resource_stats/participants/site-1.json)
  is the accepted client report. The participant name remains readable.
- [`artifacts/workspace/resource_stats/participants/server.json`](artifacts/workspace/resource_stats/participants/server.json)
  is the accepted server report.
- [`artifacts/workspace/resource_stats/resource_summary.json`](artifacts/workspace/resource_stats/resource_summary.json)
  is the deterministic job rollup stored in the same `WORKSPACE` archive.
  Production writes it last in the live run directory as the publication
  marker; the later ZIP member order is irrelevant to readers.
- [`artifacts/query/resources-study.json`](artifacts/query/resources-study.json)
  is the validated transient payload returned by the server study query. It is
  derived from retained job workspaces and is not another persisted copy of
  the job report.
- [`artifacts/cli/resources-job.txt`](artifacts/cli/resources-job.txt),
  [`artifacts/cli/resources-site-1.txt`](artifacts/cli/resources-site-1.txt),
  and [`artifacts/cli/resources-study.txt`](artifacts/cli/resources-study.txt)
  are the production human-readable views.
- [`artifacts/cli/resources-job.json`](artifacts/cli/resources-job.json),
  [`artifacts/cli/resources-site-1.json`](artifacts/cli/resources-site-1.json),
  and [`artifacts/cli/resources-study.json`](artifacts/cli/resources-study.json)
  are the exact one-line success envelopes printed by the same commands with
  `--format json`. They include the CLI contract fields around the server
  payload, so they intentionally differ from `query/resources-study.json`.

The job table derives average visible CPU units, memory GiB, and full-GPU
count by dividing each participant's resource-time by its measured interval.
The additive resource-time values remain in a separately labelled block.
These are display-only derivations: the JSON schema and stored records are
unchanged. Columns for saved content, F3 traffic, and MIG appear only when the
corresponding data is present, so this reference omits the first two while
their `unavailable/not_bound` state remains visible in JSON.

The `workspace/` directory mirrors members inside the normal stored
`WORKSPACE` ZIP. It is not a proposed second storage component.

`retained_content` and `f3` are explicitly `unavailable` with `not_bound` in
these outputs. Their authoritative production hooks are not implemented yet,
so this reference does not invent measurements for them.

Participant identity is the readable registered name (`site-1` or `server`) in
filenames, stored records, rollups, and CLI output. The summary's accepted
participant names define the exact archive namespace. The reader validates
the summary schema; a participant-detail read also validates that selected
record's identity and reconciles its copied values. The normal ZIP CRC can
detect accidental corruption in a member when it is read, but it is not a
signature. Public JSON reports elapsed decimal seconds and derived
resource-seconds. Human output converts those quantities to hours. Raw private
monotonic nanosecond readings are not serialized.

## Regenerate or verify

From the repository root, with NVFlare and its test dependencies available:

```console
python -m research.runtime_resource_proxy_prototype.production_reference.generate_reference --write
python -m research.runtime_resource_proxy_prototype.production_reference.generate_reference --check
pytest -q research/runtime_resource_proxy_prototype/production_reference/test_reference_artifacts.py
```

`--check` does not modify the checked-in artifacts. The test also validates
the schema, recomputes rollups, verifies the archive through the production
reader, confirms its exact summary-derived inventory, and compares all files
byte-for-byte with a fresh regeneration.
