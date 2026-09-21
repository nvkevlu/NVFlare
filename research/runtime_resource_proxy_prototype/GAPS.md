# Job resource statistics: implementation gaps

This is the status checklist for the code in this branch. For the exact
implemented path, start with
[PRODUCTION_IMPLEMENTATION.md](PRODUCTION_IMPLEMENTATION.md). The broader
[implementation plan](../../docs/design/job_resource_statistics_implementation_plan.md)
contains target designs, but a target is not listed here as implemented until
production code exercises it.

Every remaining change must preserve this deployment rule:

> Resource statistics use existing NVFlare permissions and setup. They require
> no new privilege, mount, service, launcher argument, environment variable,
> job setting, or operator configuration.

## Implemented now

- One terminal `participant_summary` per participant; no public start/final
  pair, attempt ID, or environment key.
- Early client/server job-process collectors for Linux CPU, memory, validated
  CUDA-visible GPUs, and one final observation of the workspace filesystem's
  visible capacity.
- Automatic discovery of one unique CUDA Runtime owned by an allowlisted
  NVIDIA runtime distribution under Python roots frozen before custom-path
  activation. The collector loads that file by contained absolute path when
  normal loader discovery or enumeration fails; it does not import a framework
  or change the environment.
- Platform-owned startup for the official Process, Docker, Kubernetes, and
  Slurm launchers: Python `-I`, the fixed NVFlare bootstrap and `client` or
  `server` selector, sanitized effective startup paths, and the initial
  snapshot before workspace download or custom-path activation. This is
  automatic and adds no user configuration or privilege.
- Exact capacity-time accumulation with private monotonic nanosecond readings
  and public decimal-second values.
- A bounded private terminal handoff at the fixed run-workspace path, strict
  parent read, parent-bound `participant_name`, and staging cleanup.
- One client completion send on the existing authenticated
  `task/report_job_failure` exchange, with an optional 1 MiB report and flat
  `resource_report_status` reply.
- Trusted expected-participant reconciliation, strict schema/semantic
  validation, direct canonical-byte duplicate/conflict comparison, and a
  bounded in-memory ledger of the first accepted bytes. Accepted participant
  bytes are written and fsynced only during finalization. The originally
  selected client names are persisted in
  `JobMetaKey.RESOURCE_PARTICIPANTS` so restore can rebuild the expected set.
- Server-local acceptance through the same coordinator, job reduction,
  local summary-last publication, and unchanged normal `WORKSPACE` archival.
- Verified fixed-member archive reads for a job and on-demand study reduction
  across retained jobs. Queries stage one normal `WORKSPACE` at a time and do
  not materialize the full archive as Python `bytes`. The reader rejects any
  duplicate, staging, missing, or extra `resource_stats/` member introduced by
  flattened multi-root packaging. It treats the summary as the publication
  marker and derives exact participant filenames. A `--site` read additionally
  validates the selected participant's schema, identity, and copied values.
- `nvflare job resources --job ...`, optional `--site`, and
  `nvflare job resources --study ...` human/JSON paths.
- Readable registered participant names. The live coordinator compares exact
  canonical bytes directly. The ZIP reader checks a member's CRC when it reads
  that member, but makes no cryptographic integrity or signing claim.
- Real one-server, two-client Process-launch POCs on Colossus have exercised
  isolated child startup, child-to-parent handoff, client CellNet delivery,
  root reconciliation, normal `WORKSPACE` persistence, and job/site/study CLI
  reads. The substantial
  [PyTorch run](colossus_pytorch_e2e_reference/README.md) is the primary live
  reference. The earlier
  [NumPy smoke run](colossus_e2e_reference/README.md) is the comparison case
  where the CUDA Runtime was system-resolvable and GPU collection succeeded.

The exact files and CLI text generated through these production classes are in
[production_reference](production_reference/README.md).

## Remaining Phase 1 work

### 1. F3 attribution and cutoff

Production currently emits `f3.status=unavailable` with `not_bound`.

Before it can report counters, the implementation needs trusted job/class
attribution for real task requests and responses, task results, job deployment,
and included stream data. It must exclude polling, acknowledgements, workspace
transfer, the resource report itself, and protocol traffic; count a remote
send only after local send acceptance; distinguish direct delivery; suppress
same-hop retry duplication; and freeze all included processes at a defined
cutoff.

The F3 prototype and route analysis remain useful design material, but they
are not connected to the production collector or parent processes.
The focused [F3 reporting gap](F3_GAP.md) records the exact field semantics,
route bindings, cutoff and merge work, integration traps, and recommended
implementation order.

### 2. Retained-result bytes

Production currently emits `retained_content.status=unavailable` with
`not_bound`. This value is hard-coded where
[`JobResourceCollector.finish()`](../../nvflare/private/fed/resource_stats/collector.py)
builds the private child handoff. The rest of the implemented path already
validates, transports, copies, and adds a numeric retained-content result. The
missing piece is the source of that result, not its public schema or rollup.

No current directory is an authoritative saved-result set:

- `Workspace.get_result_root(job_id)` falls back to the run directory, so it
  may contain the deployed app, configuration, logs, statistics, temporary
  files, inputs, and outputs together;
- built-in result owners do not all write through that root; and
- `JobRunner._save_workspace()` archives the available run, result, log, and
  audit roots, while a separate-workspace launcher returns the whole job run
  directory. These paths define what is packaged, not which files are workflow
  results.

Scanning any of those trees would produce a directory-size measurement, not
the exact size of a complete retained-result set. It also cannot prove that an
empty directory means the workflow retained no result. Reported zero is valid
only when an authoritative owner declares that its complete set is empty.

To populate the existing field without new user configuration, each supported
workflow needs a platform-internal, job-scoped retained-result provider. A
small registry is one implementation of that provider, but it is not a public
job setting or a fallback workspace scanner. Built-in components that own
results register their final artifacts after a successful final write and
declare whether the registered set is complete. Unknown or custom workflows
without that ownership contract continue to report `unavailable/not_bound`.

The provider must freeze after workflow finalizers have finished and before
`JobResourceCollector.finish()` writes the terminal handoff in client or server
`_archive_results()`. It should count the logical byte size of only registered
regular files that are actually on the normal result-return/retention path.
File names, paths, and hashes remain private and do not enter the participant
report.

The implementation still needs fixed internal limits for entry count, path
length, and registry memory. It must reject paths outside approved job roots,
symlinks, non-regular files, duplicates, and totals outside the existing U128
contract. A complete successfully observed set reports `reported`, including
`bytes: "0"` for a known empty set. If an owner identifies the intended set but
only an exact subset can be observed, the provider may report that subtotal as
`partial/observation_incomplete`. If completeness or the subtotal cannot be
established, it reports unavailable; malformed or inaccessible registered
content follows the existing typed error rules. Resource reporting remains
best effort and never changes the job outcome.

The final job-store `WORKSPACE` component is authoritative for a different
fact: the bytes in the centrally retained archive. That archive includes app,
configuration, log, audit, and resource-statistics content, is available only
after participant reports are frozen, and is not a per-participant additive
result. Compressed archive size and uncompressed member size would also be
different measurements. If that fact is wanted, it needs a separately named
job-level metric and an explicit byte definition; it must not be substituted
for the current `retained_content` field.

### 3. Resource changes and multi-node collection

`JobResourceCollector.observe_capacity_change()` can close the preceding
interval and begin another, but today's execution path calls only the startup
observation and finalization. No future GPU-release or task-worker topology is
assumed.

When the resource-management work chooses its runtime model, its existing
platform boundary must either call this method for every confirmed capacity
change or replace the adapter with an owner that spans the participant's
logical work. An end snapshot must never be multiplied by the whole duration.

For a Slurm job with more than one node, the rank-zero process cannot observe
the other nodes. Production therefore publishes no rank-zero numeric
resource-time totals and emits exactly
`resource_time: {status: unavailable, issues: [unsupported]}`. Complete
multi-node reporting needs a platform-owned merge with one trusted reporter
per execution environment.

### 4. Delivery and root-parent restart recovery

The client makes one application-level completion request. The coordinator
handles an identical duplicate while live state exists, but there is no client
retry loop and no post-finalization receipt tombstone. A lost request can leave
a participant missing. After a lost reply, the server may already have
accepted the report, but the client does not retry or learn that status.

Here `accepted` means validated and held in the live root parent's bounded
memory ledger, not written or restart-durable. The per-report bound is 1 MiB,
and the total accepted canonical report bytes retained for one job are capped
at 64 MiB. Finalization writes and fsyncs participant files, then writes and
fsyncs the summary last in the parent-owned construction directory as the
publication marker; failure discards the incomplete resource bundle without
changing the job outcome. This local ordering does not constrain ZIP member
order.

The restore path rebuilds the originally selected names from the persisted
`RESOURCE_PARTICIPANTS` job metadata (with an active-client fallback for older
jobs). It resets the in-progress resource directory and does not restore the
cutoff, accepted ledger, or invalid history. Reports accepted
only before the restart therefore become missing unless a new post-restart
report is accepted; the current one-send client will not normally resend them.
If full live-job recovery is a Phase 1 requirement, restore that state from
server-owned data without trusting a child-writable file.

A restored server job process starts a new collector, preserves its numeric
post-restore interval, and marks resource time
`partial/observation_incomplete`. That is implemented; restoring the lost
client accepted ledger remains open.

The implemented transport is Option A, the existing
`REPORT_JOB_FAILURE` request. A new versioned `REPORT_JOB_COMPLETION` remains a
fallback only if review rejects that name or handler ownership. It would need
mixed-version negotiation and tests, but no operator setting or dual send.

### 5. Residual bootstrap trust boundary

The official Process, Docker, Kubernetes, and Slurm launch paths now start the
NVFlare worker with Python `-I`, sanitize launcher startup `PYTHONPATH`, and
take the initial snapshot before workspace download and app/site custom-path
activation. This platform behavior needs no user setup, extra privilege, or
new deployment option.

It does not control code that runs before the launcher-supplied Python command,
such as a bring-your-own-container entrypoint. Python isolated mode also still
loads a `sitecustomize` installed in global interpreter site packages. After
the snapshot, job custom code shares the worker process and can influence
later evidence or the private handoff. The result is therefore still an
authenticated site self-report, not tamper-resistant attestation. Stronger
isolation would require a different trust boundary and is outside the
no-new-privilege/configuration scope.

### 6. Study-query cost and bounds

The study command obtains the retained job list once and caps it at 10,000
rows. It stages one terminal job's existing `WORKSPACE` component at a time
through `get_storage_for_download(...)`, reads the fixed size-bounded members
from that file, and removes the request-scoped staging directory. This avoids
materializing whole archives as Python `bytes`, but latency and temporary-disk
use still need validation against realistic filesystem and remote job stores.

While building the response, the handler charges each prospective canonical
job row to a cumulative 64 MiB budget before appending it, then checks the
complete serialized study object against the same bound. Exceeding either
bound fails the whole request; no subtotal is returned.

If those measurements require further optimization, add a narrow fixed-member
archive API or a bounded cache. Do not add a duplicate durable
resource-statistics component or silently truncate a study total.

### 7. Initial platform coverage

The production adapter implements Linux affinity/cgroup evidence and ordinary
process-visible memory. If an applicable CPU or memory cgroup constraint is
unreadable or malformed, that dimension fails closed instead of falling back
to a wider value. The final compute result is then partial when other numeric
dimensions remain, or unavailable when none do. The team still must decide
whether Phase 1 is Linux-only or which ordinary-user evidence has equivalent
semantics on other supported systems.

CUDA Runtime remains the only authority for a numeric GPU count. NVML may
enrich only CUDA-validated devices. Raw `CUDA_VISIBLE_DEVICES` and
`nvidia-smi` text are diagnostic, not numeric authority.

The original PyTorch run exposed a gap on an otherwise ordinary driver-only
L40 host. PyTorch successfully loaded the CUDA 13 Runtime supplied by an
installed NVIDIA Python distribution and used the GPU, but that runtime was not
visible through the system loader. The archived reports from that run therefore
correctly contain `partial/observation_incomplete` and no GPU group.

The production collector now handles that packaging case before PyTorch or job
custom code is imported. It freezes absolute Python distribution roots when
the trusted collector module is imported. After normal loader resolution or
enumeration fails, it uses installed distribution metadata under only those
roots and accepts an owned runtime only from an allowlisted
`nvidia-cuda-runtime` or `nvidia-cuda-runtime-cuNN` distribution. The resolved
target must be a nonempty regular file contained in the distribution root.
Aliases and hard links to the same contained target are deduplicated; multiple
distinct targets fail closed. A unique target is loaded by absolute path with
`RTLD_LOCAL | RTLD_NOW` on POSIX before the existing Runtime count, Driver UUID,
and NVML enrichment steps run.

This implementation adds no environment variable, toolkit installation,
launcher option, operator setting, privilege, subprocess, or framework import.
Candidate paths, metadata hashes, and lookup errors are not persisted. Legacy
monolithic wheels whose CUDA Runtime is owned directly by the `torch`
distribution and conda-only runtime layouts are intentionally unsupported for
now. They continue to yield partial or unavailable compute data rather than a
guessed GPU count until a separately validated metadata adapter exists.

The live runs prove the ordinary-affinity, non-limiting-cgroup Process-launch
case, system-loader CUDA Runtime discovery, and the allowlisted NVIDIA
distribution fallback on the driver-only PyTorch environment. Constrained
CPU/memory cgroups, CUDA device subsets, multiple GPUs, MIG, additional CUDA
and packaging versions, Docker, Kubernetes, and Slurm still need separate live
coverage; none is required to interpret the proven Process-mode result.

## Consequences of the one-terminal-report design

- There is no archived start snapshot or public capacity-change timeline.
- The server validates totals and bounds but cannot independently reconstruct
  them from public intervals.
- Hard child loss can make child-derived values unavailable; parent/site loss
  can leave the entire expected participant missing.
- The client consumes the terminal handoff and frees launcher-managed compute
  resources before it waits for the completion request's CellNet reply.
- A server-job-process failure skips the normal client-outcome wait and closes
  acceptance immediately; later client reports cannot change the rollup.
- One compute status describes CPU, memory, and GPU resource time together.
- Totals add participant and job reports even when physical resources overlap.
  They are not inventory, ownership, capacity, utilization, or billing data.
- The workspace-filesystem value is one final observation and is never
  multiplied by time or aggregated.
- Normal multi-root workspace packaging remains unchanged. If another
  flattened root creates a duplicate, missing, staging, or extra
  `resource_stats/` member, verification fails closed and that job's resource
  view is unavailable.
- Study output covers only jobs still retained by the job store. It is an
  on-demand view, not a permanent audit ledger.

## Closed design decisions

- no extra privilege or configuration;
- one terminal participant report;
- one compute status, with separate typed workspace, retained-content, and F3
  results;
- site hardware observations are self-reports;
- CUDA Runtime is the only numeric GPU-count authority;
- a loader-invisible CUDA Runtime may be used only when it is the one unique,
  contained file owned by an allowlisted NVIDIA runtime distribution under
  roots frozen before job custom-path activation;
- full GPUs and MIG instances use separate groups, and MIG is absent when it
  does not apply;
- optional bounded CPU and GPU model strings are allowed;
- the registered participant name is used directly and is bound to trusted
  client/server context;
- no resource-specific checksum or separate archive index is stored; live
  retries compare the accepted canonical bytes directly, and finalized reads
  derive their exact file set from `resource_summary.json`;
- missing data is not zero;
- the job-workspace filesystem alone is observed once and is not aggregated;
- the existing `WORKSPACE` archive is the sole durable copy;
- job and study views read that archive rather than a `RESOURCE_STATS`
  component; and
- the schema does not choose the future task/resource process topology.

## Phase 2

The first Phase 2 track may publish selected finalized Phase 1 values through
`JobStatsReporter`. It must read the same final archive/summary rather than
collecting a second copy. Field names, job-only versus optional site
publication, model privacy, delivery limits, and the parent-side publication
hook remain open. The on-demand study CLI is a Phase 1 query feature, not a
Phase 2 stored total.

A separate deferred Phase 2 track may keep a bounded series of periodic or
change-triggered capacity snapshots. Phase 1 v1 remains resource-time-only.
Before that track is implemented, it needs a collection cadence, timestamp and
ordering rules, retention bounds, missing-sample semantics, and an owner that
works with the selected execution model. These snapshots are neither current
JobStatsReporter utilization samples nor a replacement for finalized Phase 1
totals.
