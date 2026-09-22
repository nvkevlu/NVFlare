# Phase 1 simplification decisions

This file records why the current prototype is smaller than earlier drafts. It
is decision history, not the main review document. For the current design, read
[REVIEW_GUIDE.md](REVIEW_GUIDE.md).

## Latest decision: one terminal report

Earlier drafts stored a participant start, one or more public measurement
periods, optional final capacity observations, period end reasons, and a
participant final. That structure made resource changes independently
replayable, but it also exposed lifecycle details the first version does not
need.

V1 now has one public participant record, written when that participant's part
of the job ends. It contains:

- `resource_time`, accumulated by NVFlare while work runs;
- one final `workspace_filesystem` observation;
- one `retained_content` observation; and
- final F3 counters.

There are no public attempts, start/final pairs, environment keys, end reasons,
or capacity-stability comparisons. Only the terminal report is transmitted and
archived.

This simplifies both the wire contract and review:

- one canonical report per participant;
- one compute status instead of separate CPU, memory, GPU, start, and final
  statuses;
- no interval identity, ordering, overlap, or lifecycle reconciliation rules;
- no status propagation caused only by a missing final stability sample; and
- a much smaller participant payload.

The tradeoff is deliberate. The archive no longer contains a resource-change
timeline, the server cannot recalculate resource time from public intervals,
and loss of the participant parent before delivery becomes a missing report.
Loss of only the job child instead produces a parent-built report with
child-derived fields unavailable and any usable parent F3 marked partial. The
site collector must therefore use exact arithmetic and freeze its internal
accumulator before producing its private handoff.

## Current code and future execution work

Today's adapter starts a private accumulator at the existing client/server job
process hook, attributes the selected CPU, memory, and GPU capacity while that
process runs, and freezes one bounded private handoff after runner `END_RUN`
processing. CP or SP closes and freezes its own F3 counter immediately,
validates that handoff, merges parent and child F3, assembles the one public
report, and deletes the handoff before archival. “Private” means transient
platform handoff state, not a new privileged service or protected storage
area.

Future GPU release or task-runner work does not require public attempts. If
resources change while the current process remains alive, platform code can
close the current private interval and begin another inside the accumulator.
If workers are replaced or tasks move to another process, an owner spanning
the participant's logical work must preserve or take over the accumulated
state. Only terminal totals cross the participant boundary. The public schema
does not prescribe whether that future owner is CP, a child, or another
component.

No new privilege, mount, service, launcher flag, environment variable, or
user/operator setting is allowed. Site files remain self-reported until the
server accepts them.

## Status reduction

`resource_time` has one status for compute accounting as a whole:

- `reported`: measured time plus CPU, memory, and GPU resource time are all
  complete;
- `partial`: at least one numeric compute value is useful, but compute
  coverage is incomplete; or
- `unavailable`: no usable compute resource-time value exists.

Its one issue list explains `partial` or `unavailable`. CPU, memory, and GPU do
not repeat status or issue fields.

Three other terminal facts keep separate statuses because they come from
independent sources and can fail independently:

- `workspace_filesystem` is one point-in-time observation;
- `retained_content` depends on an authoritative bounded saved-result set; and
- `f3` depends on platform-owned message classification and counters.

The server's expected-participant state remains `accepted`, `missing`,
`invalid`, or `disabled`. Job and study aggregate statuses are derived from
participant/job coverage and their typed statuses rather than copied into an
extra warning list.

## Hardware fields

CPU and GPU models remain useful review information and stay as optional,
bounded display metadata in resource-time groups.

- A CPU model is emitted only when the visible CPU set is homogeneous.
- A numeric GPU count comes only from successful CUDA Runtime enumeration.
- NVML may enrich CUDA-validated devices but cannot add devices.
- Full GPUs and MIG instances use separate groups.
- MIG fields are absent when no MIG instance applies.

Raw CPU topology, CUDA masks, GPU UUIDs, PCI addresses, and other host identity
are not stored.

## CPU and memory selection

The private collector still uses the same ordinary-user selection rules. CPU
units are the minimum applicable value from process affinity, cgroup cpuset,
and finite CPU quota; online CPU count is the fallback only when no stronger
source is usable. Raw quota and period values are not persisted.

Visible memory is the minimum finite value from the cgroup memory limit and
process-visible physical memory. Swap is excluded. These selected values feed
the internal resource-time accumulator; they are not repeated as public start
or final observations.

## Resource-time arithmetic

The public record stores the accumulated result, not the internal intervals.
Conceptually, for each interval known to the platform:

~~~text
CPU time    += selected CPU units × elapsed seconds
memory time += selected memory bytes × elapsed seconds
GPU time    += visible GPU instances × elapsed seconds
~~~

Products use exact decimal arithmetic and the v1 rounding rule. The final
`measured_seconds` states how much time the accumulator covered. Missing
coverage changes the single `resource_time.status` to `partial`; it does not
create a public gap or end-reason record.

## Workspace filesystem and saved results

Visible workspace-filesystem capacity and saved-result bytes are different
facts.

- `workspace_filesystem` is observed once, during terminal finalization, for
  only the filesystem containing the existing NVFlare job workspace. Other
  mounted filesystems are not enumerated or summed.
- `retained_content` is the exact sum for a complete bounded result set already
  known to NVFlare, or a separately statused partial/unavailable result.

Workspace capacity is not usage, allocation, billable storage, storage owned
by the job, or a time-based measure. It is never added across participants or
jobs. Saved-result bytes are additive and remain in participant, job, and
study totals.

## F3 decisions

Keep only one final counter: remote accepted. Exact final delivery to an
in-process logical destination and failed send attempts are outside the v1
public metric.

Include exactly three trusted semantic operations: job application deployment,
a response containing a real task, and a submitted task result. Do not count
task requests or add another contribution at a forwarding process. One message
is one top-level logical send to one remote destination. A remote destination
reached through a local first-hop relay still counts once at its origin; only
an exact final in-process delivery is excluded.

Count the main payload after FOBS encoding and before optional encryption. If
FOBS moves a large value through `DownloadService`, fold successfully accepted
unique source bytes into the same operation without another message. Do not
store headers, encryption expansion, TLS overhead, lower-layer
retransmissions, or retries.

The accounting context stays inside the process that originates the trusted
operation. Child cleanup closes command admission and pre-drains admitted
callbacks for up to five seconds while transport remains alive; timeout or
error marks `counter_gap`. The child then performs its fixed F3
close/drain/freeze before transport stop. The parent closes and freezes
immediately because its included blocking operations must already have
settled; an unexpected pending admission becomes `counter_gap`. The parent
checked-merges their non-overlapping contributions. Platform code freezes
before terminal-report serialization, so the report is excluded without a
spoofable marker.

## Server, storage, and query decisions

The root server reconciles terminal reports against the participants it already
expects. It marks each participant accepted, missing, invalid, or disabled at
the cutoff, validates and copies accepted terminal values, and aggregates the
job summary. It cannot reconstruct private resource-time intervals.

The bundle lives only in the job's existing `WORKSPACE` archive. The query
handler reads fixed `resource_stats/...` members and never accepts a
caller-selected archive path. There is no duplicate `RESOURCE_STATS`
component.

The normal job CLI reads one summary. The study form:

~~~text
nvflare job resources --study NAME
~~~

finds matching jobs still retained by the normal job store, validates their
archived summaries, and computes a response on demand. It adds only resource
time, retained-content bytes, and the primary F3 accepted-remote counter. It
does not add workspace capacity and does not persist a study total. Jobs
removed by normal retention are outside the result, so this is not permanent
historical accounting.

## Earlier reductions retained

The final-only change preserves the previously approved reductions:

- role appears once in each expected-participant entry;
- report acceptance and measurement completeness are distinct;
- missing data is never encoded as zero;
- saved results have no per-file names or content hashes;
- model files are not guessed or hashed;
- no resource-specific checksum or separate archive index is retained;
- summary warnings are derived rather than stored twice;
- one summary is written last in local construction as the publication marker
  and determines the exact accepted-participant file namespace, independent of
  later ZIP member order; and
- no cross-participant workspace-capacity total exists.

## Decisions still open

This history does not maintain another decision list. See
[GAPS.md](GAPS.md) for the authoritative remaining questions.
