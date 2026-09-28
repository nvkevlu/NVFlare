# Production reference output

This directory is the deterministic reference for the current production
handoff, run-directory observation, public message-traffic rollup, archive-reader,
and CLI path.
It is regenerated from controlled inputs so reviewers can verify every output
byte without depending on a live machine.

See the [implemented-path walkthrough](../PRODUCTION_IMPLEMENTATION.md) for
when each record is collected, sent, accepted, archived, and queried.

The generator sends controlled, realistic inputs through the same code path
used by a job:

1. `JobResourceCollector` integrates runtime-visible capacity using private
   monotonic clock readings.
2. The child writes and the parent reads the fixed terminal handoff.
3. `assemble_participant_summary` binds the trusted participant name.
4. `ResourceStatsCoordinator` validates each report and writes the final
   `resource_stats` bundle under the normal server run directory. The archived
   summary is keyed by job ID alone.
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
  records participant coverage and accepted values in the same `WORKSPACE`
  archive. It has no persisted totals or cutoff/finalization timestamps.
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

The job table derives average visible CPU cores, memory GiB, and full-GPU
count by dividing each participant's resource-time by its measured interval.
It also shows average CPU cores used, derived from separately collected
process CPU time divided by a complete, positive measured interval. A partial
CPU-time subtotal can produce a starred average, but a partial or unavailable
interval produces `—` even when raw CPU seconds exist in JSON. This avoids
dividing CPU time by only part of the job interval. The figure is not a
CPU-utilization percentage: 2 cores used means an average of 2 CPU-seconds
per wall-clock second, regardless of the visible-core count. The additive
resource-time and CPU-time values remain available in the rollup and JSON.

The job and study views derive totals from accepted participant entries when
requested; those calculations add no aggregate field to the stored summary.
The human view omits repeated status columns. A number marked `*` is a useful
but incomplete subtotal; `—` means there is no usable number. Short data-gap
notes identify the affected participant and measurement. In `--format json`,
successful accepted entries and complete measurements omit `status` (and
measurement `issues`); missing, invalid, partial, unavailable, and error
exceptions remain explicit. The text view does not need to repeat them beside
every value. Columns for
run-directory files, message traffic, and MIG appear only when applicable.
This reference shows run-directory files and message traffic, and omits MIG.
Participant reports store `message_traffic.sent_to` by named recipient; the
job/study `sent` and
per-site outgoing/“sent to site” amounts are derived only for requested views.
“Sent to site” is sender-confirmed addressed traffic, not receiver-observed
bytes or a guarantee of delivery. Missing or partial sender reports limit the
coverage of the displayed amount sent to a site.

The one-job header shows both the human-facing name and unique ID. The study
table has separate `JOB ID` and `NAME` columns, and every JSON study row has
both fields. The fixture deliberately treats `job_id` as the reconciliation
and ordering key because names may repeat. Neither `participant_summary` nor
the archived `resource_summary` has `job_name`; the CLI obtains display names
from existing trusted job metadata, and the derived study view includes them.

The `workspace/` directory mirrors members inside the normal stored
`WORKSPACE` ZIP. It is not a proposed second storage component.

`retained_content` has no status and zero bytes for both controlled
participants because their run directories are deliberately empty when the
terminal observation is taken. Current v1 collection sums logical `st_size`
for regular files under the participant run directory while excluding
top-level `resource_stats/`; it is a best-effort self-report rather than a
curated result inventory. Message traffic comes from
deterministic operations admitted and completed through the production
`F3Counter`, then supplied through the production child/parent merge. The
controlled values include main post-FOBS bytes and out-of-band source-byte
contributions, but they are not evidence that a live CellNet route was
exercised. The generator does not infer traffic from generic network
statistics.

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

From the repository root, using a project Python environment with NVFlare and
its test dependencies installed:

```console
python -m research.runtime_resource_proxy_prototype.production_reference.generate_reference --write
python -m research.runtime_resource_proxy_prototype.production_reference.generate_reference --check
pytest -q research/runtime_resource_proxy_prototype/production_reference/test_reference_artifacts.py
```

`--check` does not modify the checked-in artifacts. It must report no
differences. The test also validates the schema, recomputes rollups, verifies
the archive through the production reader, and confirms its exact
summary-derived inventory.
