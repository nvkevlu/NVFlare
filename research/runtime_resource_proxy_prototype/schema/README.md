# Resource statistics schema v1

This directory contains the Phase 1 contract used by the implementation. It
defines one terminal participant report, the server's job reduction, and the
derived study-query response. It does not expose collector lifecycle records.

## Files

| File | Purpose |
| --- | --- |
| [resource_stats_v1.schema.json](resource_stats_v1.schema.json) | Closed Draft 2020-12 JSON Schema. |
| [contract_v1.py](contract_v1.py) | Cross-record checks, exact arithmetic, and reductions. |
| [FIELD_CATALOG.md](FIELD_CATALOG.md) | Every field, type, unit, and limit. |
| [CODE_CATALOG.md](CODE_CATALOG.md) | Every status, issue, participant state, and F3 class. |
| [golden/v1](golden/v1) | Valid example records and CLI output. |
| [build_review_artifacts.py](build_review_artifacts.py) | Deterministic generator for the goldens. |

Regenerate from the repository root in a Python environment with NVFlare and
its test dependencies installed. The generator uses the production CLI
renderer, so both the repository root and this script's directory must be
importable:

```console
PYTHONPATH=. python research/runtime_resource_proxy_prototype/schema/build_review_artifacts.py
PYTHONPATH=. python -m pytest -q research/runtime_resource_proxy_prototype/tests/test_review_artifacts.py
```

Unknown fields are rejected. JSON `null` is not a substitute for an omitted
field. V1 is not released, so the current contract requires `cpu_consumed` and
uses implicit success states without an archive-compatibility or version-bump
requirement.

## Record flow

Each participant produces exactly one `participant_summary` when its part of
the job ends. The report contains:

- one `resource_time` object for accumulated CPU, memory, and GPU time;
- one independent `cpu_consumed` object for user plus system CPU seconds;
- one final `workspace_filesystem` capacity observation;
- one `retained_content` observation; and
- one final `message_traffic` observation.

Every participant report includes `cpu_consumed`. If its measurement has no
usable value, that typed object explicitly says `unavailable` or `error` and
records the applicable issue; it is not omitted or interpreted as zero.

The root server authenticates and validates reports, reconciles them against
the participants expected for the job, and writes one `resource_summary` with
the job ID and participant entries. It writes that summary last as the live
run-directory publication marker. These are the only
persistent resource-statistics records:

| Kind suffix | Purpose |
| --- | --- |
| participant_summary | One terminal participant report. |
| resource_summary | Final server result for one job. |

There are no public participant-start, participant-final, attempt-start,
attempt-final, or attempt-end records. There are no attempt IDs, environment
keys, end reasons, raw periods, or start/final stability comparisons.

The JSON form of a study query is a derived response, not another archived
record. It is calculated from retained job summaries on demand and disappears
with the response. See the generated [study summary](golden/v1/study_summary.json)
and [study CLI output](golden/v1/finalized_job/cli/resources-study.txt).

## Architecture and deployment constraints

The public contract contains no launcher name, process ID, storage path,
process-coordination token, or resource-manager field. It requires no new:

- privilege;
- container capability;
- host service;
- mount;
- launcher argument;
- environment variable; or
- user/operator configuration.

The current adapter initializes a private in-memory accumulator in the current
client/server job process after workspace construction. After runner `END_RUN`
processing, the child freezes one bounded, versioned private handoff in the
existing job workspace. CP or SP validates that handoff, merges child and
parent F3 counters, builds the sole public participant report, removes the
handoff, and then uses the selected one-message completion transport or local
acceptance. See [Current-code integration](../CURRENT_CODE_INTEGRATION.md).

The participant schema is independent of the completion topic. Option A adds
the optional report to `REPORT_JOB_FAILURE` / `report_job_failure`. Option B
replaces that request with `REPORT_JOB_COMPLETION` /
`report_job_completion`, whose combined envelope has exact integer
`protocol_version: 1`. Under either design, the request carries the same
outcome and exact `participant_summary` bytes into the same acceptance logic.
Production sends exactly one Option A request. If Option B were selected, the
client would instead send exactly one Option B request; retries would not
switch topics, and capability/rollout selection would add no operator setting.
The envelope protocol version is not the report's `schema_version`.

Option B addresses the historical topic name and handler ownership only. It
retains the same validation, filesystem-write, acknowledgement, and retry work
in the critical completion path. If lifecycle control and resource
data must be delivered separately, neither one-message option suffices.

The private accumulator is not part of the schema. Today's adapter assumes one
CJ or SJ process remains alive and that selected visible capacity persists
until finalization unless the platform reports a change. A future design that
replaces workers or moves task execution must move or carry forward the
accumulated state in a component spanning the participant's logical work. The
terminal record does not change, and this design does not choose that future
owner or handoff. No implementation may take one end-of-run snapshot and
multiply it by the whole duration.

## Identity

`job_id` remains the unique lookup, matching, and sort identity. Neither the
participant report nor archived `resource_summary` stores `job_name`. The
authorized job CLI resolves the display name from existing server-owned job
metadata when requested; the on-demand study view still includes that name
beside each job ID. This adds no privilege, configuration, or wire field.
Names are 1–255 ASCII characters, begin alphanumeric, and then permit
alphanumeric, dot, underscore, or hyphen.

New jobs use `JobMetaKey.JOB_NAME`. When reading legacy metadata, the root
server falls back to `JOB_FOLDER_NAME` and then `job_id`; the resolved value is
still server-owned and must satisfy the same field rule.

`participant_name` is the existing configured product identity: the
registered site name for a client and the configured server participant name
for SP. It appears in the participant report, expected-participant row, and
readable archive member
`resource_stats/participants/<participant_name>.json`.

The feature does not derive an HMAC pseudonym or add a resource-specific
`START_JOB` field. Shape validation is not authentication: for a client, the
server binds the incoming report to the existing authenticated sender and job
context, finds that name in the expected participant list, and requires the
JSON name to match. SP uses its already trusted local name. Before constructing
an archive path, the server separately requires the trusted name to satisfy the
bounded participant-name grammar and be one safe path component.

## Trust model

Resource values are authenticated self-reports, not tamper-resistant
attestation. Official launchers take the initial observation before enabling
app/site custom paths, but a bring-your-own-container entrypoint or globally
installed `sitecustomize` remains outside that boundary. Job code then shares
the process and may affect later evidence or alter or remove the private
handoff before the parent validates it. A missing or invalid handoff becomes
typed unavailable/partial data in a parent-built report. Loss of the parent or
delivery path can still leave no accepted report.

“Authenticated” here means the existing Cell sender checks: signed token and
origin in secure mode, or the current registered-client token in insecure
mode. The resource feature adds no stronger identity or hardware attestation.

After receipt, the server validates and stores the exact accepted bytes. The
archive does not add a signature, attestation, or other proof that the
participant's original observations were truthful. The normal ZIP CRC can
detect accidental member corruption, but it is not a cryptographic trust
boundary.

## One compute completeness decision

`resource_time` applies one completeness decision to measured time, CPU,
memory, and GPU together:

- no `status` or `issues` means complete and requires `measured_seconds`, CPU,
  memory, and GPU values;
- `partial` requires issues and at least one usable numeric member; and
- `unavailable` requires issues and carries no numeric members.

CPU, memory, and GPU do not have nested statuses or issue arrays. This makes
the completeness statement intentionally coarse but removes contradictory
per-resource/start/final status combinations.

`cpu_consumed`, `workspace_filesystem`, `retained_content`, and
`message_traffic` keep independent exception statuses.
They use independent sources and can fail even when compute resource time is
complete.

`cpu_consumed` has canonical decimal `seconds` when complete or partial.
Partial carries an issue list and a useful incomplete subtotal; unavailable
carries an issue list and no numeric value. Its status does not change
otherwise sound CPU-capacity, memory, or GPU results. Linux and macOS read
`RUSAGE_SELF` and `RUSAGE_CHILDREN` once at the start and once at the end of
the job-process measurement window. The deltas count the job process and
descendants that exited and were waited for in that window, without double
counting. A short-lived waited child is included without periodic sampling.
An unawaited or still-running known worker makes coverage partial or
unavailable; the shared site parent is excluded. Current PyTorch
`MultiProcessExecutor` ranks are not waited for and the earlier interval of
a restored server worker is unrecoverable from these counters.

The three essential numeric meanings are complete value (status omitted), useful
subtotal (`partial`), and no usable value (`unavailable`). They distinguish an
actual zero from absent evidence. Participant status is likewise omitted for
`accepted`, but explicit `missing`/`invalid`/`disabled` values describe why
a terminal report did not make it into the job summary. The schema also
permits `error` on some measurements; see the
[status catalog](CODE_CATALOG.md#typed-object-statuses) for a proposed
consolidation that has **not** changed the v1 contract.

## Internal resource-time accounting

The participant stores only accumulated results. Conceptually, whenever the
platform knows the selected capacity for an internal interval:

~~~text
CPU time    += visible CPU units × elapsed seconds
memory time += visible memory bytes × elapsed seconds
GPU time    += visible GPU instances × elapsed seconds
~~~

Products use exact decimal arithmetic and are rounded at most once to nine
fractional digits using round-half-even before summation. Private intervals
and resource-change events are not serialized. `measured_seconds` is the time
covered by the accumulator; it need not equal wall-clock job duration when
coverage is incomplete.

Schema v1 does not retain the capacity snapshots used for those private
intervals. For a complete participant, dividing a resource-time total by
`measured_seconds` yields a time-weighted average; it does not recover the
interval sequence. A future periodic snapshot series belongs to a separate
Phase 2 contract and does not add fields to this schema.

### CPU

The selected CPU capacity is the minimum applicable ordinary-user value from:

- process affinity;
- effective cgroup cpuset; and
- finite cgroup CPU quota.

Online CPU count is the fallback only when none of those sources is usable.
The terminal report stores `unit_seconds` groups, not raw selector evidence,
quota, or period values. Optional model and architecture labels describe the
group. A heterogeneous visible CPU set omits the model rather than choosing a
representative string.

### Memory

The selected memory capacity is the minimum finite value from the effective
cgroup memory limit and process-visible physical memory. Unlimited limits are
ignored and swap is excluded. The terminal value is `byte_seconds`.

### GPU

A numeric GPU contribution requires successful CUDA Runtime enumeration. A
raw `CUDA_VISIBLE_DEVICES` string is diagnostic only and is never stored or
used as a count. An unavailable CUDA runtime is not an observed zero.

NVML may enrich devices already validated by CUDA, but it cannot add a device
or change count authority. Full GPUs and MIG compute instances stay in
separate `instance_seconds` groups. Optional model, per-entity memory, and MIG
profile metadata do not change the numeric authority. MIG fields are omitted
when inapplicable. An empty complete GPU group list is authoritative zero.

## Terminal workspace-filesystem observation

During terminal finalization, NVFlare observes the total capacity of only the
filesystem containing the existing job workspace. It does not enumerate or
sum other mounted filesystems.

`workspace_filesystem` omits status and issues when `capacity_bytes` was
observed; otherwise it carries an explicit exception status and issues. It is
a single point observation, not usage, allocation,
billable storage, storage owned by the job, or evidence about capacity earlier
in the run. It is not converted to byte-seconds and is never aggregated across
participants or jobs.

## Retained content

In v1, `retained_content` is a terminal, best-effort observation of one
participant's NVFlare run directory. The collector recursively adds the logical
`st_size` of regular files and excludes the top-level `resource_stats/`
subtree. It does not identify models or distinguish outputs from the deployed
application, configuration, logs, temporary files, or inputs.

Symlinks and other non-regular entries are ignored, and symlink targets are not
followed. Hard-linked files are counted once per directory entry. Sparse files
contribute their logical length rather than allocated blocks. A clean traversal
reports the observed total, including `bytes: "0"` for an empty directory. If
an entry or directory cannot be observed, a useful subtotal is
`partial/observation_incomplete`; if no useful observation can be made, the
value is unavailable.

The traversal is not an atomic filesystem snapshot. It runs after application
execution returns and before the private handoff, stats-pool files, optional
workspace upload, and later cleanup/log growth. It is also a participant
self-report: the parent validates the typed value but does not attest the files
or remeasure them. Participant, job, and study totals are additive observations,
not unique retained storage, archive size, allocation, usage, or billable
storage.

Only the run directory is observed. A separately configured result, log, or
audit root is currently outside this value; covering those roots without
double-counting is a known implementation gap.

## Message traffic counters

The terminal `message_traffic` object has one status and a `sent_to` list of
destination counters:

- `sent_to`: up to 2,048 entries sorted by unique `participant_name`, each with
  `payload_bytes` and positive `messages`. Destinations cannot be the sender;
  accepted summary destinations name another expected participant.

An empty list represents no included sends. Counters freeze in one atomic
operation before the report is serialized. A callback contributes only if it
linearizes before that cutoff; later callbacks cannot change canonical values.
If the platform cannot stop new included traffic and drain already admitted
callbacks before freezing, F3 reports `partial/counter_gap` rather than
claiming a complete value with no status.
Child cleanup first closes command admission and pre-drains admitted callbacks
for up to five seconds while transport remains alive; timeout or error marks
`counter_gap`. The child then uses the fixed five-second F3 drain. The parent
closes and freezes immediately because its current included blocking sends must
already have settled; a pending parent operation becomes `counter_gap` without
delaying cleanup. The parent checked-merges both non-overlapping semantic-origin
contributions. Lost pre-restore history is `partial/attribution_incomplete`.

Five seconds is a maximum child condition wait, not a fixed sleep. A child
drain with no active callback or pending F3 operation returns immediately.

Included application classes are exactly job application, real task response,
and task result. Task requests, empty polling, exact final in-process delivery,
failed send attempts, a relay's duplicate contribution, control traffic,
workspace transfer, logs, unknown classes, and resource-report traffic are
excluded. A remote logical destination through a local first-hop relay remains
counted once at its origin. Remote bytes count only after local transport
acceptance. A streamed send remains pending until its `StreamFuture` ends
successfully; asynchronous failure or cancellation abandons it. Fan-out counts
one logical message per destination, and only the trusted semantic origin
counts it. Bytes are measured after FOBS encoding and before optional
encryption. Successfully accepted unique `DownloadService` data is folded into
that operation without another message or retry duplication. Headers,
encryption expansion, framing, TLS, transport compression, and retransmissions
are outside the metric.
If a large-object contribution or settlement cannot be proved, the affected
operation is discarded and F3 is `partial/counter_gap` rather than a complete
undercount.

## Expected participants and job reduction

The server builds `participants` from authenticated deployment/selection
state, not incoming reports. At cutoff, each expected participant is exactly
one of:

- accepted (no `status` field);
- `missing`;
- `invalid`; or
- `disabled`.

An accepted entry includes the trusted participant name and role, receipt
time, and the validated terminal `resource_time`, `cpu_consumed`,
`retained_content`, and `message_traffic`
objects. Workspace-filesystem capacity remains only in the archived
participant report. A retry with identical bytes is idempotent; different
bytes cannot replace the first accepted report. The server compares the exact
accepted bytes directly; the accepted summary row does not add a receipt token.

The archived job summary contains participant entries and no aggregate
`totals`. The CLI and study query derive job totals from accepted reports when
requested. The derived values contain `resource_time`, `cpu_consumed`,
`retained_content`, and a message-traffic `sent` pair summed from participant
`sent_to` entries. Complete totals omit status and issues; partial or
unavailable totals carry explicit status. There is no
workspace-capacity total. Missing data is not zero.

## Server files

The server writes:

~~~text
resource_stats/
  participants/<participant_name>.json
  resource_summary.json
~~~

The server atomically writes each accepted participant file and then writes
`resource_summary.json` last in the live run directory. That summary is the
publication marker. Normal completion archives this directory inside the
existing job `WORKSPACE` component; archive member order is not contractual.
There is no `RESOURCE_STATS` component or other query copy.

The CLI asks the authenticated server to read fixed members from that archived
workspace. Callers cannot select arbitrary paths. The reader first validates
the summary, derives the exact participant filenames from its accepted
`participant_name` rows, and rejects missing or extra files in the
`resource_stats/` namespace. It also checks duplicate ZIP members, size bounds,
strict JSON, record kinds, job and participant identity, and copied
participant values before returning data. This schema/identity/value
reconciliation is semantic validation, not signing.

## Job and study CLI

One-job queries use:

~~~text
nvflare job resources --job JOB_ID
nvflare job resources --job JOB_ID --study NAME
nvflare job resources --job JOB_ID --study NAME --site SITE_NAME
~~~

`--job` alone reads the job from the `default` study. Combining `--job` and
`--study` reads one job from the named study, which supplies the existing
authorization/selection context. `--site` requires `--job`.

The one-job heading shows the metadata name followed by `ID: JOB_ID`; the
study table uses separate `JOB ID` and `NAME` columns. The archived resource
summary has only `job_id`; the on-demand study JSON includes `job_name` in
each job row.

The command does not search across studies. NVFlare binds job visibility to
the authenticated session's study, so a job in another study intentionally
appears not found, matching the other job commands.

An on-demand study rollup uses:

~~~text
nvflare job resources --study NAME
nvflare job resources --study NAME --format json
~~~

`--study` without `--job` selects all retained jobs in the named study. The
bare `nvflare job resources` command shows help.

For a study query, the server authorizes the active study and materializes job
IDs, persisted names, and statuses from one scan of matching jobs still
retained by the normal job store. It keeps that list fixed while reading
archives and classifies each row as:

- `included`: terminal job with a valid resource summary;
- `unavailable`: terminal job whose valid resource summary cannot be read; or
- `nonterminal`: still running or otherwise not terminal, and excluded from
  additive totals.

The v1 response reuses the existing job-CLI terminal predicate: statuses
beginning `FINISHED:`, plus retained legacy values `FINISHED_OK`,
`FINISHED_EXCEPTION`, `ABORTED`, `ABANDONED`, and `FAILED`. It keeps the
bounded status read during the one scan even if the job changes state while
archives are being read.

The response keeps coverage counts and per-job state so missing summaries are
not mistaken for zero. It adds resource time, CPU consumed seconds,
retained-content bytes, and the message-traffic `sent` pair.
Workspace-filesystem capacity is never included. Only `included` rows
contribute numbers; any unavailable or
nonterminal row makes an otherwise numeric aggregate partial. The response is
not stored, does not include jobs already removed by retention, and is not a
permanent audit or independently verified invoice ledger. CPU consumed is a
practical billing proxy for the included jobs.

The human CLI keeps the main numbers easy to scan: it omits repeated status
columns, marks a useful incomplete number with `*`, and uses `—` for no usable
number. Short data-gap notes point to the affected job, participant, or
measurement. The JSON response preserves explicit exception statuses and issue
codes; omitted success status means accepted or complete in its typed context.
The job table also places average CPU cores used beside average visible CPU
cores. The former divides process CPU seconds by `measured_seconds` only when
the measured interval is complete and positive; a partial CPU-time subtotal
is starred, while a partial interval suppresses the derived average. This is
not a utilization percentage.

## Privacy

Allowed content is restricted to authenticated product identity, normalized
hardware display metadata, the fixed summary-derived archive namespace,
numeric facts, statuses, and issue codes. Optional CPU/GPU model metadata may
be omitted without changing numeric status. This feature adds no privacy or
publication setting.

Forbidden content includes environment/argument dumps, raw CUDA masks, GPU
UUID/PCI identity, CPU serials/flags/topology, host/IP/PID/container/pod/
scheduler identity, absolute cgroup/workspace paths, credentials, tokens,
message contents, raw exceptions, and tracebacks.
