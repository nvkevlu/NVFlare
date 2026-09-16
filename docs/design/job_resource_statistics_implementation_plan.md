# NVFlare Phase 1 resource statistics — implementation plan

Status: draft for review.

This document describes the data Phase 1 should collect, how to calculate the
results, and how users should read them. It does not choose the future NVFlare
task-process or resource-management architecture.

For a shorter introduction, start with the
[review guide](../../research/runtime_resource_proxy_prototype/REVIEW_GUIDE.md).

## 1. Agreed scope

Phase 1 reports resources visible inside the environment where an NVFlare job
runs. It does not report utilization or authoritative allocation data.

Included:

- visible CPU capacity;
- visible memory capacity;
- CUDA-enumerated GPUs;
- point-in-time visible capacity of the filesystem that contains the existing
  job workspace;
- one exact byte total for a complete NVFlare result set already known to the
  platform; and
- F3 application-payload counters.

Excluded:

- CPU, memory, or GPU utilization;
- Kubernetes requests and limits read from the API;
- Docker configuration or socket data;
- Slurm allocation records;
- cloud instance metadata;
- billing rates or monetary calculations; and
- scans of unrelated files or operating-system network counters.

### Deployment constraint

The feature must work with the permissions and setup NVFlare already has.

It must not require:

- root access;
- a privileged container;
- a host agent or sidecar;
- Docker socket access;
- additional Kubernetes RBAC permissions;
- cloud permissions;
- Slurm administrator access;
- a new volume or mount;
- a new launcher argument or environment variable; or
- new operator or job configuration.

Any implementation that needs one of these is out of scope.

This feature does require NVFlare code changes. It must not require users or
operators to change installation, job configuration, launch commands, or
deployment setup.

## 2. Current-code baseline and architecture boundary

The first implementation targets the process lifecycle that exists today:

- the root server parent starts one server job process;
- each client parent (CP) starts one client job process for the job;
- each job process runs the application and writes in its existing run
  workspace;
- a client parent waits for its job process, reports the terminal outcome to
  the root server, and then releases the resources assigned to that process;
- the root server waits for the server job process and the expected client
  terminal outcomes; and
- the root server archives the server run workspace as the existing
  `WORKSPACE` job-store component before publishing the terminal job status.

The concrete call sites and proposed code changes are documented in
[Current-code integration](../../research/runtime_resource_proxy_prototype/CURRENT_CODE_INTEGRATION.md).
That document is part of this design, rather than an optional implementation
note.

The data contract does not assume that this process model will remain. In the
JSON, an **attempt** means a measurement period. It does not promise that the
period is a process, task, round, scheduler allocation, or resource lease.
Today there is one period for the lifetime of each job process. A future design
may open and close more periods through the same internal collector API.

This keeps the Phase 1 **data design** independent of the GPU-release work.
Changing who executes a task may change which platform component opens and
closes measurement periods and which component delivers the completed site
report. It does not change the record schema, reduction rules, archived layout,
or CLI. The CP terminal-outcome path below is the concrete adapter for current
code, not a requirement that the roadmap retain CP or its present lifetime.

## 3. End-to-end flow in the current code

The arrows below distinguish files from messages:

~~~text
client job process                     client parent (CP)
------------------                     ------------------
participant_start                      wait for job process
attempt_start          workspace       read frozen participant_summary
attempt_final        ------------->    check size + digest
attempt_end                            send with terminal outcome
participant_final                              |
                                               | authenticated CellNet request
                                               | task/report_job_failure
                                               v
server job process                     root server parent
------------------                     ------------------
same local records     workspace       validate client report
                  ----------------->   accept it idempotently
                                       wait at existing outcome cutoff
                                       add server participant
                                       build resource_summary
                                       write resource_stats/*
                                       archive existing WORKSPACE
                                               |
                                               v
                                       nvflare job resources JOB_ID
                                       reads members from WORKSPACE.zip
~~~

In more detail:

1. In `JobRunner._start_run()`, the root server freezes the expected
   participant set: the server plus every selected client. A client that times
   out during launch remains expected and can therefore appear as `missing`
   rather than disappearing from coverage.
2. NVFlare places the server-generated participant identity in existing
   internal start-job state. This is not a job option, launcher argument, or
   operator setting.
3. The client and server job entry points create `participant_start` and the
   first `attempt_start` after the workspace exists and before the explicit
   custom-directory import path is enabled.
4. The runners take the optional final observation and close the attempt after
   their normal `END_RUN` sequence, before F3 and streaming shutdown.
5. Each job process writes best-effort fragments and a local summary below the
   existing `resource_stats/` run-workspace directory. These are site
   self-reports, not immutable evidence.
6. After the client job process exits, `ClientExecutor._wait_child_process_finish()`
   reads and validates the summary from the returned/shared job workspace. It
   sends the exact bounded JSON bytes with the terminal outcome, before it
   frees the allocated resources and before the CP fires `JOB_COMPLETED`.
7. The request reuses the authenticated CP-to-root-server CellNet request that
   exists today: target `FQCN.ROOT_SERVER`, channel `task`, topic
   `report_job_failure`. The topic name is historical; it already carries both
   successful and failed terminal outcomes.
8. `FedServer.process_job_failure()` authenticates the CP session, binds the
   report to the registered client and expected job, and tries to validate and
   store the first valid version before it resolves that client's pending
   terminal outcome. It resolves the outcome even when the resource report is
   absent, invalid, or cannot be stored. This synchronous work can delay that
   existing outcome request, but cannot change the outcome and does not create
   a second reporting window.
9. After the server job process exits, the root parent accepts its local report
   through the same validator without a loopback message.
10. The existing terminal-outcome wait is the report cutoff. On normal
    completion it is currently at most 900 seconds after the server process
    exits. An abort or server-process failure skips the client wait after one
    server-local acceptance attempt. The resource feature adds no second client
    reporting window or setting.
11. Immediately before `JobRunner._save_workspace()`, the root parent
    classifies expected reports, recomputes all totals, writes
    `resource_summary.json`, and writes `manifest.json` last.
12. `_save_workspace()` archives those files with the rest of the run directory
    in the existing `WORKSPACE` component. The CLI reads the archive; it does
    not contact clients and no second `RESOURCE_STATS` component is created.

If a site has no valid summary at the cutoff, the job can still finish. That
participant is `missing` or `invalid`, and the job totals show reduced
coverage rather than substituting zero.

## 4. Records

Candidate v1 has eight closed record types:

| Record | Purpose |
| --- | --- |
| **participant_start** | Start of one site's part of the job and initial visible workspace-filesystem capacity observation. |
| **attempt_start** | Start of one measurement period and its CPU, memory, and GPU observation. |
| **attempt_final** | Optional final resource observation for that period. |
| **attempt_end** | End time and reason for that period. |
| **participant_final** | Final visible workspace-filesystem capacity observation, one saved-result byte total, and F3 counters. |
| **participant_summary** | One complete site report built from the preceding facts. |
| **resource_summary** | Job result with every expected participant classified. |
| **manifest** | Hashes of the exact stored server files. |

The exact required fields and types are in the
[field catalog](../../research/runtime_resource_proxy_prototype/schema/FIELD_CATALOG.md).
The machine-readable rules are in the
[JSON Schema](../../research/runtime_resource_proxy_prototype/schema/resource_stats_v1.schema.json).

### Identity

Each measurement period has a random 128-bit **attempt_id**. This is an internal
record ID generated by platform code. It is stored in the workspace fragment;
it is not passed through a launcher argument.

Before launch, the root server creates one opaque, job-scoped
**participant_key** for each expected participant. The key is the HMAC-SHA-256
form defined by the field catalog. It derives the current process's
**environment_key** the same way, using a different domain string.

The server overwrites a reserved `JobMetaKey.RESOURCE_STATS_CONTEXT` map before
launch. Only the derived keys enter this existing job-metadata path; the HMAC
key never leaves the root server. The client parent already writes its runtime
metadata to deployed `job_meta.json` before selecting a launcher. The server
parent currently builds only an in-memory copy, so Phase 1 must add a narrow
change in `ServerEngine._start_runner_process()`: atomically add only the
server-owned resource context to deployed `job_meta.json`, preserving the
deploy-time `BYOC` decision, before selecting the server launcher. The job
process then reads its own entry from that existing file. This adds no launcher
argument, environment variable, allowlist, or operator setting and does not
modify persisted submitted-job metadata.

On receipt, the server ignores a claimed participant name as an authority and
uses the authenticated CP session plus its expected-participant map.

Each period has the **environment_key**, called the measurement-scope key in
prose. Today each job process has one reporter slot and uses the derived value
from that reserved metadata. A future platform component may ask the root
server to allocate more keys without changing the record format.

Periods with the same measurement-scope key may not overlap. This prevents two
ranks in one environment from reporting the same visible capacity at the same
time. Periods from different jobs are not deduplicated. Therefore totals across
jobs may count the same physical hardware more than once.

The keys hide raw process, node, container, GPU, and launcher identities. They
are correlations inside one job, not authentication credentials and not
stable identities across jobs.

## 5. Resource rules

The commands below are troubleshooting equivalents. Production collection uses
Python or library calls from the NVFlare process, parses bounded data, and never
executes a shell command supplied by a job.

### CPU

Report effective CPU capacity in CPU units. One unit is the scheduling capacity
of one logical CPU.

Read these values when available:

- process affinity count;
- effective CPU-set count; and
- finite CPU quota divided by period.

Use the smallest applicable value. If none is available, use the online logical
CPU count visible to the process.

On Linux, the adapter performs these exact steps:

1. Read `os.sched_getaffinity(0)` and count the unique allowed CPU IDs.
2. Resolve this process's actual cgroup paths by parsing `/proc/self/cgroup`
   together with `/proc/self/mountinfo`. Do not assume `/sys/fs/cgroup` is the
   mount or concatenate an untrusted path directly.
3. For cgroup v2, read `cpuset.cpus.effective`. For cgroup v1, read
   `cpuset.effective_cpus`, falling back to `cpuset.cpus`. Count the union of
   the parsed CPU-list ranges; do not store the list or CPU IDs.
4. Walk from the process cgroup to the cgroup mount root. At every level, read
   a finite v2 `cpu.max`, or the v1 `cpu.cfs_quota_us` and
   `cpu.cfs_period_us`. Convert each finite quota to quota units.
5. Select the smallest positive affinity, CPU-set, and finite quota value. Use
   `os.sysconf("SC_NPROCESSORS_ONLN")` only when none of those sources yields a
   value.

**quota_units** is the exact quota/period ratio rounded down to at most nine
decimal places. Rounding down avoids overstating capacity. Raw **quota_us** and
**period_us** remain inside the probe and are not stored.

The normalized CPU model and architecture are optional. Report a CPU model only
when every affinity-visible CPU normalizes to the same model. Otherwise omit it.

For Linux model evidence, parse only the `processor` and `model name` fields in
`/proc/cpuinfo`, retain models for affinity-visible processors, trim and collapse
whitespace, enforce the schema length bound, and emit the model only when the
complete visible set is homogeneous. Architecture comes from
`platform.machine()` after bounded normalization.

Useful diagnostics are:

~~~console
taskset -pc $$
getconf _NPROCESSORS_ONLN
cat /proc/self/cgroup
cat /proc/self/mountinfo
lscpu
~~~

The cgroup filenames must be read at the paths resolved for the process, not
blindly at the shell user's cgroup root.

### Memory

Report effective visible RAM in bytes.

Use the smaller finite value from:

- a memory maximum enforced on the process environment; and
- physical memory visible to the process.

Treat an unlimited cgroup value as no finite limit. Do not add swap.

Physical memory is `SC_PAGE_SIZE * SC_PHYS_PAGES`. As with CPU quota, resolve
the process cgroup and inspect every ancestor to the mount root. Read v2
`memory.max`, or v1 `memory.limit_in_bytes`, and ignore an explicit unlimited
value. Select the smallest finite positive value together with physical memory.
Diagnostic equivalents are:

~~~console
getconf PAGE_SIZE
getconf _PHYS_PAGES
cat /proc/self/cgroup
cat /proc/self/mountinfo
~~~

### GPU

A numeric GPU count requires successful CUDA-runtime enumeration. A raw
**CUDA_VISIBLE_DEVICES** string never provides a count.

NVML may add model, per-device memory, and MIG profile only for devices already
found by CUDA. NVML cannot add a device or change the count.

Keep full GPUs and MIG instances in separate groups. **memory_bytes** is the
runtime-reported memory for each entity in the group. Devices with different
memory values use different groups.

MIG fields and CLI columns are omitted when no positive MIG value is present.

Production code calls `cudaGetDeviceCount` and the CUDA runtime property API
available to that process. If either enumeration or required property lookup
fails, it does not emit a numeric count. `nvidia-smi -L` and the raw
`CUDA_VISIBLE_DEVICES` value are useful diagnostics only:

~~~console
nvidia-smi -L
printenv CUDA_VISIBLE_DEVICES
~~~

NVML is optional enrichment. The adapter may add model, memory, and MIG profile
only after it can match an NVML entity to one already validated by CUDA. If it
cannot safely distinguish a full GPU from a MIG compute instance, GPU capacity
is unavailable rather than assigned to the wrong group.

### Visible workspace-filesystem capacity

At participant start and final, read the total visible capacity of exactly the
filesystem containing the existing NVFlare job workspace. Do not enumerate or
sum other mounted filesystems, and do not export the workspace's absolute path.

Treat the two readings as independent point observations. They need not match
and do not prove availability between those instants. The capacity may describe
a shared filesystem; it is not usage, allocation, billable storage, or storage
owned by this job.

Do not calculate storage byte-seconds. Do not add visible workspace-filesystem
capacity to participant totals or combine it across participants.

This is a deliberate v1 boundary: a shared filesystem cannot be attributed to
the job without privileges or configuration that this feature is not allowed
to require.

The implementation calls `os.statvfs(Workspace.get_run_dir(job_id))` and
calculates `(f_frsize or f_bsize) * f_blocks`. It calls this once for the start
observation and once for the final observation. The troubleshooting equivalent
is:

~~~console
df -B1 --output=size /path/to/the/existing/job/run/directory
~~~

The path is never serialized, and the adapter does not enumerate mounts.

### Saved-result byte total

Record one exact byte total only when existing NVFlare state identifies a
complete, bounded result set. Calculate it from that set without exporting
per-file data. If no such set exists, retained content is unavailable with
`not_bound`. Do not add an artifact registry, job setting, or scan of unrelated
directories.

Keep only status and a byte count. A reported value is the complete total; a
partial value is the exact observed subtotal. Do not export result filenames
or hash model content. Keep saved-result bytes separate from filesystem
capacity.

The current code does not expose one authoritative, complete saved-result file
set: result and run roots can overlap, and persisted files are application
dependent. Therefore the initial adapter reports `unavailable/not_bound`
unless the owning NVFlare component hands it a complete bounded file set. It
must not scan the workspace or guess that a filename such as `model.pt` is the
result.

### F3 network counters

Count these job traffic classes:

- task request;
- task response;
- task result;
- job application; and
- job stream data.

Do not count:

- job stream control;
- bulk envelopes;
- workspace transfer;
- platform control;
- log export;
- unknown traffic classes; or
- the resource-summary publication itself.

For remote delivery, count payload bytes only after the payload is encoded and
any end-to-end encryption is applied, immediately before the normal F3 send.
Increment the remote counter only after the send is accepted.

Keep three counters:

- remote accepted;
- local delivered; and
- remote failed before acceptance.

These are sender-side counters. A receiver does not count the same remote
payload again. Client-to-server and server-to-client traffic are both present
in the job rollup because the client and server reports each contribute the
messages they sent. This avoids counting every network delivery twice while
still covering both directions.

For fan-out, count each destination. For forwarding, count each sender hop.
Exclude headers, driver framing, TLS framing, compression overhead, and
retransmissions below this boundary.

Before writing the final site report, NVFlare closes all three counters in one
operation. Later callbacks do not change the stored totals. Job code cannot
mark its own traffic as excluded.

The proposed production hook is the job-scoped path immediately around
`CoreCell._send_to_endpoint()`. It measures the encoded/encrypted payload,
increments `remote_accepted` only after `communicator.send()` succeeds, and
increments `remote_failed_before_acceptance` if acceptance fails. Direct
delivery increments `local_delivered` separately. The platform classifier,
not a job-provided header, assigns included and excluded traffic classes.

The existing process-global `StatsPool` and `JobStatsReporter` histograms mix
different semantics and are not the Phase 1 counter source. Phase 1 needs
job-scoped counters that each owning process freezes and hands to the site
summary reducer.

The current route audit and exact binding points are in
[Current-code integration](../../research/runtime_resource_proxy_prototype/CURRENT_CODE_INTEGRATION.md#current-route-and-binding-table).
In particular, an accepted `get_task` request is held pending and counted only
when its reply carries a real task; empty polls are discarded. Large-object
stream bytes require trusted DownloadService transaction provenance so model
data can be included while workspace ZIP transfer is excluded. A path without
that correlation reports `not_bound` or `counter_gap`, never generic F3 totals.

## 6. Time and totals

Both timestamps for one measurement period must come from the same NVFlare
clock.

Use the half-open interval from **opened_at** up to, but not including,
**closed_at**:

~~~text
duration_seconds = closed_at - opened_at

cpu_unit_seconds =
    visible_cpu_units × duration_seconds

memory_byte_seconds =
    visible_memory_bytes × duration_seconds

gpu_instance_seconds =
    visible_gpu_instances × duration_seconds
~~~

Round each product to nine decimal places using round-half-even, then add the
period values.

A final resource observation does not define duration. It checks whether the
startup value appears to have remained valid. If it is missing or numerically
different, mark the affected total partial.

The saved-result byte total and F3 counters contribute once per site report.

A measurement period that started but could not capture resources may retain
its known start and end times. Its resource values are unavailable, and job
totals are partial.

A completed site report with no measurement periods means zero observed
compute time only when NVFlare knows that the list is complete. If it cannot
make that statement, the site report must be missing or invalid rather than
claiming zero.

## 7. Status and issue codes

Status depends on the fact being described:

| Fact | Allowed status |
| --- | --- |
| Point-in-time CPU, memory, GPU, or visible workspace-filesystem capacity | **reported**, **unavailable**, **error** |
| Saved results or F3 counters | **reported**, **partial**, **unavailable**, **error** |
| Derived resource-time total | **reported**, **partial**, **unavailable** |

Point-in-time CPU, memory, GPU, and visible workspace-filesystem capacity
cannot be partial. NVFlare either obtains a valid selected value at that
moment or it does not. Saved-result and F3 facts may be partial when they
retain useful numeric data but have incomplete coverage.

The server classifies each expected participant as:

| Status | Meaning |
| --- | --- |
| **accepted** | A valid final site report arrived before the cutoff. |
| **missing** | No valid report was accepted into the server run workspace before cutoff. This includes no report, transfer loss, or a server storage failure. |
| **invalid** | A report arrived but failed validation. |
| **disabled** | Existing policy disabled collection for that site. |

Issue codes explain partial, unavailable, and error states. The fixed list is in
the [code catalog](../../research/runtime_resource_proxy_prototype/schema/CODE_CATALOG.md).
Missing data is never replaced with zero.

End reasons are **released**, **reconfigured**, **failed**, **terminated**, and
**launch_failed**. These are descriptive only; they do not change the time
formula. **reconfigured** means NVFlare ended a measurement period after
observing a capacity change. It does not require or imply a later period.

## 8. Trust, delivery, finalization, and storage

### 8.1 Site-side trust and crash behavior

The current process, Docker, Kubernetes, and Slurm launch paths can put job
custom code on `PYTHONPATH` before Python enters `worker_process.main()` or
`runner_process.main()`. A job could therefore run `sitecustomize` before the
earliest practical in-process probe. Without a separate privileged service or
sanitized launcher setup, which this feature is not allowed to require, these
values cannot be presented as tamper-resistant evidence.

Phase 1 therefore labels site observations accurately: they are
platform-collected site self-reports. Authentication proves which registered
site sent the final bytes. The server manifest proves which accepted bytes were
archived. Neither proves that hostile job code could not influence a local
observation.

The current prototype writes best-effort, create-once fragments below the
existing job workspace. They can be changed by job code and may disappear in a
hard crash, especially when a Kubernetes `emptyDir` disappears with the pod.
Normal Docker, Kubernetes, and Slurm shutdown already returns or exposes the
job directory to the parent; Phase 1 uses that existing path. It adds no mount,
service, or durable site store. Missing crash data is reported as missing or
partial rather than described as immutable.

### 8.2 Chosen client-to-server transport

The client report is attached to the existing CP terminal-outcome CellNet
request in `ClientExecutor._wait_child_process_finish()`:

| Property | Value |
| --- | --- |
| sender | client parent after `job_handle.wait()` |
| target | `FQCN.ROOT_SERVER` |
| channel | `CellChannel.SERVER_MAIN` (`task`) |
| topic | `CellChannelTopic.REPORT_JOB_FAILURE` (`report_job_failure`) |
| receiver | `FedServer.process_job_failure()` |
| authentication | existing outgoing client-session token filter |
| timing | before resource release, logout, and CP `JOB_COMPLETED` |

Despite its old name, this request already carries the terminal outcome for a
successful child as well as failures. The existing payload remains compatible:

~~~text
{
  "job_id": "...",
  "code": 0,
  "reason": null,
  "resource_report": {
    "sha256": "<digest of the exact bytes below>",
    "participant_summary": <exact canonical UTF-8 JSON bytes>
  }
}
~~~

`resource_report` is omitted when the parent cannot recover a candidate report.
That omission must not prevent the terminal outcome from being sent. The
participant summary is capped at 64 MiB before decoding, and the server
recomputes SHA-256 instead of trusting the supplied digest.

`send_request_before_shutdown()` already serializes the request ahead of token
retirement. Phase 1 adds up to two retries only for timeout, no reply, or a
communication return code, using the same bytes and the existing
`job_query_timeout`. It waits one second between tries. It does not retry an
accepted, duplicate, invalid, conflicting, unauthenticated, or too-late reply.
On the client this gives a network-wait budget of three `job_query_timeout`
intervals plus two seconds. Local file reading, hashing, and serialization
happen before that budget, so it is not a hard wall-clock bound on resource
release. These constants are internal and add no configuration.

The server attempts these resource-report steps before replying and before it
resolves the pending client outcome:

1. Authenticate the client token and obtain the registered client name.
2. Verify that `(job_id, client_name)` is in the frozen expected set.
3. Enforce the byte limit and recompute the digest.
4. Decode UTF-8 JSON while rejecting duplicate object keys.
5. Validate JSON Schema and the semantic contract.
6. Verify job ID, participant key, and every current-adapter environment key
   against trusted server state. Supply display participant ID and role from
   that trusted state; they are intentionally absent from the site report.
7. Recompute attempt and participant totals; never trust supplied arithmetic.
8. Write and flush a unique temporary file in the server run workspace.
9. Under the per-job acceptance lock, inspect any accepted digest and the
   cutoff state. The same accepted digest is `duplicate`, even after cutoff.
   Any other digest after cutoff is `too_late`. Before cutoff, a different
   accepted digest is `conflict`; an empty slot atomically installs the
   candidate, flushes the containing directory, and then records the ledger
   entry. A failed directory flush leaves no accepted ledger entry and returns
   `server_error`.
10. Remove every temporary file that was not installed.

It then processes and resolves the terminal outcome regardless of the report
status. A resource validation or storage error cannot change the job return
code. The validation and workspace write are synchronous before outcome
resolution, so they can delay this existing request and server finalization.
They do not add a later report wait; the current client-outcome deadline remains
the normal waiting budget after the SJ exits. It is not a strict wall-clock
bound because a callback already committing to the workspace can hold the
shared acceptance lock past the nominal deadline. The response uses the normal
successful Cell return code once the terminal outcome is processed and carries
the separate report status. A lost transport response is retryable; an explicit
report error is not automatically retried.

The first valid digest for one expected participant wins. The same digest is
an idempotent retry. Before cutoff, a later different digest is a conflict and
never overwrites accepted data; after cutoff, any different digest is
`too_late`. An invalid candidate does not reserve the slot, so a later valid
retry can still be accepted before the cutoff.

### 8.3 Why this transport was selected

| Alternative | Benefit | Reason it is not the Phase 1 path |
| --- | --- | --- |
| Extend the existing terminal-outcome request | Already authenticated, sent by the parent after child exit, and already participates in the server's completion wait. | Selected for current code. Validation and workspace commit add latency to this request, but this avoids a second delivery and cutoff protocol. |
| New accounting CellNet topic | Cleaner name and independent handler. | Adds another completion protocol and correlation path without improving availability. |
| Client-job to server-job auxiliary request | Familiar job-cell API. | The job cell may already be shutting down or dead, and `END_RUN` delivery is fire-and-forget. |
| Root server pulls from every client | Central control. | Couples finalization to live client/job cells and introduces a second wait and failure mode. |
| Federated event | Familiar event integration and optional federated delivery over Aux. | Outgoing federated delivery is fire-and-forget and teardown is best effort, so it does not provide the durable acceptance reply needed here. |
| Task or model-result metadata | Travels with existing results. | Repeats per task, may be filtered or transformed, and may never be produced on abort or a no-result job. |
| Job metadata | Easy to query. | It is defined before final measurements exist and is not a client final-delivery path. |

Model artifacts are deliberately unrelated. Phase 1 does not attach data to a
model, assume a `model.pt` filename, or hash model content.

### 8.4 Cutoff and rollup

The root server freezes expected participants before sending start-job
requests. Incoming reports do not create the list, because that would hide a
selected client that never starts or never reports.

For an ordinary completion, the existing
`ConfigVarName.CLIENT_OUTCOME_WAIT_TIMEOUT` controls the only wait. Its current
default is 900 seconds beginning after the server job process exits. A report
accepted before that deadline is included. A report arriving after
finalization receives `too_late` and cannot change archived bytes.

When the completion loop first observes the SJ exit, it makes exactly one
parent-local acceptance attempt for the server staging report before starting
or closing that client-outcome wait. A per-job flag makes this idempotent across
loop iterations. The server report therefore reaches the same validator before
the common cutoff; it does not use a loopback CellNet request.

The current abort and server-process-failure paths skip the client-outcome
wait. Phase 1 follows that behavior after the single server-local acceptance
attempt; any client report not already accepted is missing. Resource reporting
never changes the federated job outcome, but the local acceptance attempt and
any commit already holding the shared lock can add the processing latency
described above.

Acceptance and cutoff use one per-job lock. Under that lock, the finalizer
changes the state from `open` to `closed` and snapshots the accepted ledger.
It reduces only that snapshot. A callback that prepared a temporary file but
reaches the lock after closure deletes the file and returns `too_late`. A
callback that commits first is in the snapshot. This prevents a participant
file from appearing after manifest construction has begun.

At the cutoff, the root parent:

1. closes acceptance and snapshots the ledger under the shared lock;
2. removes and directory-flushes any participant file not in that ledger, then
   verifies that the directory matches it exactly; if this cannot be done, it
   omits the completion manifest and resource bundle;
3. classifies every frozen participant as `accepted`, `missing`, `invalid`, or
   `disabled`;
4. recomputes every accepted participant total from its attempts;
5. combines only accepted participant totals into job totals;
6. writes the exact accepted participant summaries;
7. writes `resource_summary.json`; and
8. writes `manifest.json` last, with SHA-256 for every finalized file.

The complete server-run layout is:

~~~text
<existing server run directory>/resource_stats/
  resource_summary.json
  manifest.json
  participants/
    <participant_key>.json
~~~

`JobRunner._save_workspace()` then saves the existing run directory as the
ordinary `WORKSPACE` component and removes the live directories through its
normal cleanup. There is no `RESOURCE_STATS` component, query copy, storage
alias, or extra persistence API. The files inherit the job workspace's current
retention, authorization, and deletion behavior.

If archival keeps failing, current code retries for 60 seconds and can
exceptionally publish a terminal job status without an archived workspace. In
that case the CLI says the resource summary is unavailable; it does not query
sites or reconstruct a second copy.

## 9. CLI and archive reader

Proposed CLI:

~~~text
nvflare job resources JOB_ID
nvflare job resources JOB_ID --site SITE
nvflare job resources JOB_ID --format json
~~~

The command is a finalized-job view. It reads the existing archived server
workspace and does not contact clients.

The production path is:

~~~text
nvflare job resources
  -> Session.get_job_resources()
  -> authenticated admin command GET_JOB_RESOURCES
  -> JobCommandModule handler with normal job authorization
  -> JobDefManager.get_storage_for_download(..., WORKSPACE, ...)
  -> exact ZIP-member reader
  -> schema/semantic validation
  -> JSON response or text formatter
~~~

This follows the same pattern as the current job-log command, which already
extracts a fixed member from archived `WORKSPACE`. The handler stages the
archive server-side and reads only these exact normalized member names:

~~~text
resource_stats/resource_summary.json
resource_stats/manifest.json
resource_stats/participants/<participant_key>.json   # --site only
~~~

The reader requires exactly one matching regular-file entry, rejects absolute
or traversing names, duplicate members, bad ZIP/CRC data, non-UTF-8 data,
oversized members, duplicate JSON keys, unsupported schema versions, digest
mismatches, and a job ID that differs from the requested job. It verifies the
summary and selected participant digest against `manifest.json` before
returning them. The manifest limit is 4 MiB; each resource or participant
summary limit is 64 MiB.

The default response needs only the job summary. `--site SITE` resolves the
site through the summary's participant entry and then reads that one accepted
participant file. This detail view may show hardware models and the two visible
workspace-filesystem capacity observations. It must not call the latter usage,
allocation, billable storage, or job-owned capacity.

The `--site` response does not repeat the full job summary. It returns a small
job header, the site's trusted summary entry, and the selected participant
report. Every serialized command response must fit both a fixed 66 MiB cap and
the Cell's effective payload limit; otherwise the command returns an error and
does not emit a partial record.

For a filesystem job store, the existing `get_storage_for_download()` can
stage the archive without loading the entire ZIP into Python memory. A backend
that cannot expose a local staged file may initially retrieve the whole
archive on the server. The CLI still receives only validated JSON, not the
workspace ZIP. If this is later a performance problem, add a job-store
archive-member read API or a derived cache; do not add another durable copy of
the resource record.

Text output shows:

- expected-report coverage;
- one row per expected site;
- report status and measurement quality;
- measured time;
- GPU hours;
- CPU hours;
- memory GiB-hours;
- saved-result GiB; and
- accepted remote F3 GiB.

The default command does not show or aggregate visible workspace-filesystem
capacity. Those point observations remain in the accepted participant reports.

The command says clearly that job totals may contain overlapping physical
resources and are not physical capacity.

Examples:

- [all sites](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-all.txt)
- [one site with models](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-site-1-details.txt)
- [site with partial measurement evidence](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-site-2-details.txt)
- [JSON](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-all.json)

## 10. Current collection hooks

The first implementation adds a small platform-owned collector API:

~~~text
begin_participant(context, initial_workspace_capacity)
open_measurement(capacity) -> attempt_id
close_measurement(attempt_id, final_capacity, reason)
finish_participant(final_workspace_capacity, retained_content, frozen_f3)
~~~

Calls are idempotent only for byte-identical facts. A conflicting repeat is an
error in the local report and is never silently overwritten.

For the process model in the repository today, the exact calls are:

| Point | Current call site | Resource action |
| --- | --- | --- |
| Identity creation | `server/job_runner.py`, before `start_app_on_server()` and `start_client_job()` | freeze expected participants; derive participant and current-process environment keys in server-owned state |
| Server identity delivery | `server/server_engine.py::_start_runner_process()`, before `get_job_launcher()` | atomically copy only the reserved resource context into deployed `job_meta.json`, preserving deploy-time BYOC |
| Client start | `private/fed/app/client/worker_process.py`, after workspace download and `Workspace` construction, before `refresh_custom_dir_import_path()` | `begin_participant()` and `open_measurement()` |
| Server start | `private/fed/app/server/runner_process.py`, at the equivalent point before `refresh_custom_dir_import_path()` | `begin_participant()` and `open_measurement()` |
| Client normal final | `_archive_results()` in client `worker_process.py`, after `ClientRunner` has returned and before F3 streaming shutdown and workspace upload | final probe, freeze job-scoped F3 counters, `close_measurement()`, and `finish_participant()` |
| Server normal final | `_archive_results()` in server `runner_process.py`, after `ServerRunner` has returned and before F3 streaming shutdown and workspace upload | same final sequence |
| Client parent reduction | `ClientExecutor._wait_child_process_finish()`, immediately after `job_handle.wait()` | read fragments, validate/reduce, then send with terminal outcome |
| Server parent reduction | `JobRunner._job_complete_process()`, after the server process exits and before `_save_workspace()` | read server fragments, finalize job rollup |

The start hooks are the earliest practical points after the job workspace is
known. They precede NVFlare's explicit custom-directory import, but they do not
defeat Python code injected through `PYTHONPATH` before process entry. That is
why the design calls these values site self-reports rather than trusted
attestation.

The current cleanup helper stops admission before `_archive_results()` but
drains already-admitted callbacks later. Production F3 integration must either
drain those callbacks before freezing the counters or make the atomic freeze
the documented cutoff and mark later completions as late. Until that ordering
is resolved, F3 uses `partial/counter_gap` rather than claiming completeness.

Process launchers use their existing workspace behavior. The direct process
launcher shares it; normal Docker, Kubernetes, and Slurm completion returns or
exposes the job directory to the parent. No attempt ID, secret, locator,
environment variable, or new argument is added to any launcher allowlist.

With current code, one open/close pair covers each job process lifetime. A
future execution design may call the same API from a different component or
use multiple non-overlapping periods. The schema, reduction rules, stored
layout, and CLI do not depend on a particular future process owner. The CP
terminal-outcome delivery is today's adapter. A roadmap design that removes
that parent boundary must replace the delivery adapter and assembly owner, not
the data contract.

## 11. Phase 2 and JobStatsReporter

Phase 2 is separate. It may use **JobStatsReporter** to publish selected fields
from the finalized Phase 1 summary.

The current JobStatsReporter runs inside client/server job applications and
writes its utilization summary during the server job's `END_RUN`. The Phase 1
job summary cannot exist then: the root server parent still has to receive
client terminal outcomes, apply the cutoff, and archive `WORKSPACE`.

Therefore Phase 2 needs a small parent-side adapter invoked by the Phase 1
finalizer, or a post-finalization reader that uses the same fixed
`WORKSPACE`-member helper as the CLI. It must not have every in-job reporter
publish a duplicate or read a separate storage component.

Phase 2 must not:

- collect Phase 1 values;
- read in-progress site fragments;
- turn utilization samples into Phase 1 capacity;
- change Phase 1 totals; or
- make the job fail when publication fails.

The detailed mapping is in
[job_resource_statistics_phase2_telemetry_sketch.md](job_resource_statistics_phase2_telemetry_sketch.md).

## 12. Implementation slices

| Slice | Work | Done when |
| --- | --- | --- |
| P1-01 | Finalize the schema, fields, units, codes, formulas, and examples. | Schema, validator, and goldens agree. |
| P1-02 | Add normal-user CPU, memory, GPU, and visible workspace-filesystem capacity probes at the selected NVFlare call site. | No extra setup is required; probe failure cannot fail a job. |
| P1-03 | Add per-job F3 counters. | Included traffic, excluded traffic, acceptance, and cutoff behavior are tested. |
| P1-04 | Extend the current terminal-outcome request with one bounded participant report. | Missing, duplicate, invalid, conflicting, late, and retried reports behave predictably. |
| P1-05 | Finalize into the server run workspace and expose the archive-backed CLI/API. | JSON, manifest, safe ZIP reader, and CLI output match the goldens; no duplicate component exists. |
| P1-06 | Integrate the current process, Docker, Kubernetes, and Slurm workspace paths. | Normal completion produces the same schema without new privileges, arguments, or configuration. |
| P2-01 | Add an optional JobStatsReporter publisher for finalized Phase 1 data. | Publication is bounded, redacted, retry-safe, and non-fatal. |

## 13. Required tests

Tests must cover:

- CPU affinity, CPU set, fractional quota, conflicting limits, and fallback;
- finite, unlimited, malformed, and unreadable memory limits;
- CUDA-enumerated full GPUs, zero visible GPUs, unavailable CUDA, and MIG;
- hardware-model suppression and heterogeneous CPUs;
- exact selection of the existing job-workspace filesystem, no enumeration or
  summation of other mounts, and unreadable workspace filesystems;
- exact saved-result byte totals;
- all included and excluded F3 traffic classes;
- fan-out, forwarding, local delivery, failed send, and cutoff;
- normal completion, missing final observation, crash, and launch failure;
- duplicate reports in one measurement scope;
- intentional overlap across jobs;
- missing, invalid, disabled, and accepted participants;
- large exact integer values;
- terminal-outcome report authentication, size, digest, retry, conflict, and
  late-arrival behavior;
- archive member safety, manifest hashes, and exact `WORKSPACE` member bytes;
- text and JSON CLI output; and
- ordinary-user execution with no extra privileges or configuration.

## 14. Open-decision shortlist

[GAPS.md](../../research/runtime_resource_proxy_prototype/GAPS.md) is the
authoritative list. The current-code lifecycle, transport, cutoff, storage,
and CLI source are now concrete. The remaining implementation questions are:

1. Which CUDA runtime and NVML versions the first GPU adapter supports.
2. The complete mapping from current F3 channels/topics to the included traffic
   classes.
3. Which current owning component, if any, can supply a complete saved-result
   file set; otherwise v1 consistently reports `not_bound`.
4. Whether Linux is the only fully supported v1 platform.
5. Whether the `reconfigured` reason is useful before current code can observe
   a mid-process capacity change.
6. Whether the 4,096-attempt bound covers expected future long-running jobs.
7. The exact parent-side Phase 2 publication API and event names.

Use the GAPS review table for the complete set, constraints, and Phase 2
questions. This shortlist should not be maintained as a second complete list.

## 15. Golden example

The main finalized-job example has four expected participants:

- `site-1` has a complete 37-minute, 3-second report;
- `site-2` has an accepted report with incomplete measurement evidence;
- `site-3` has no valid report before the cutoff; and
- the server has a complete 37-minute, 3-second report.

`site-1` reports 32 visible CPU units, 192 GiB of memory, four A100 80 GB
GPUs, a 1 TiB point-in-time visible workspace-filesystem capacity, a known
empty saved-result set, and 147,700,336,640 bytes of accepted remote F3
payload. Its derived values are:

~~~text
CPU:     32 × 2,223 = 71,136 CPU-unit-seconds
Memory:  192 GiB × 2,223 = 458,290,190,352,384 byte-seconds
GPU:     4 × 2,223 = 8,892 GPU-instance-seconds
~~~

The 1 TiB visible workspace-filesystem capacity observation is not multiplied
by time and is not included in participant or job totals.

The [`site-2` report](../../research/runtime_resource_proxy_prototype/schema/golden/v1/participant_summary_partial_periods.json)
contains a five-minute 16-CPU, 128-GiB, two-GPU period that ends without a
final observation, a five-minute unmeasured gap, and a later 27-minute,
3-second 32-CPU, 192-GiB, four-GPU period. Its report is accepted, but CPU,
memory, and GPU totals are partial. Its saved-result byte count is unavailable
with `not_bound` because no complete result set is known. No compute time is
claimed for the gap.

This example says only that one measurement ended and another later began. It
does not claim that a client disconnected, a process changed, or resources were
released. Those meanings depend on the resource-management architecture.

The [resource summary](../../research/runtime_resource_proxy_prototype/schema/golden/v1/resource_summary.json)
shows all four expected participants, each accepted participant's derived
totals, and the job totals. `site-3` is the missing participant; the server is
accepted rather than being described as interrupted. The server reports the
complete 29,540,266,113-byte saved-result total. Across accepted reports, the
example contains 145,656 CPU-unit-seconds, 986,880,405,405,696 memory
byte-seconds, 15,984 GPU-instance-seconds, and 590,801,346,560 accepted remote
F3 payload bytes.

The scale comes from a completed five-round, two-client Qwen2.5-14B Colossus
qualification. That run used four A100s per client, lasted 37:03, exchanged a
29,540,067,328-byte state in twenty directions, and observed a
29,540,266,113-byte saved result. The golden example is not a replay: its CPU,
memory, visible workspace-filesystem capacity, and measurement-period
partitions are illustrative. The historical run recorded logical tensor size
but did not measure post-encoding
F3 acceptance bytes. The example sets its F3 counters to the derived logical
volume only to use a realistic scale.

Large quantities are stored as decimal strings so JavaScript and other clients
do not lose integer precision.
