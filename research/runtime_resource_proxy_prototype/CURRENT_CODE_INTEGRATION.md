# Phase 1 integration with current NVFlare code

Status: detailed design and code audit. A production subset now exists.

For the authoritative description of what this branch implements, read
[PRODUCTION_IMPLEMENTATION.md](PRODUCTION_IMPLEMENTATION.md). This longer file
also records the current F3 bindings and remaining proof, plus target designs
for retained-content binding, delivery retries/tombstones, and the versioned
completion-topic fallback. Target-only sections are not claims about current
production behavior.

This document names the current processes, code hooks, messages, files, and
cutoffs. It makes no assumption about which GPU-release design will be chosen.

The implemented path is:

1. Each client and server job process starts one in-memory resource-time
   accumulator and one process-local F3 counter. CP and SP keep job-scoped
   parent counters from trusted lifecycle state.
2. From `_archive_results()`, the job process writes one private terminal
   measurement handoff, including its frozen F3 contribution, in its existing
   job workspace. This is not a `participant_summary` and is never retained in
   the job-store archive.
3. After the job handle finishes, the parent closes and freezes its own F3
   counter, validates the child handoff, checked-merges the two process
   contributions, binds its trusted participant name, creates the one
   canonical `participant_summary`, and deletes staging. Retained content is
   currently typed `unavailable/not_bound` unless a bounded source is added.
4. The client parent attaches those exact final bytes to one completion
   request on the existing `REPORT_JOB_FAILURE` topic. It makes one
   application-level send; the versioned `REPORT_JOB_COMPLETION` transport is
   a design fallback, not implemented code. The server parent passes its own
   final bytes through the same local acceptance rules.
5. The server parent authenticates and validates reports, then holds the first
   accepted canonical bytes in its bounded in-memory ledger.
6. At cutoff, the server parent adds accepted final totals and writes and
   fsyncs participant files, then writes and fsyncs one job
   `resource_summary` last in the parent-owned workspace as the publication
   marker.
7. Normal job archival stores those files in the existing `WORKSPACE`
   component.
8. Job and study CLI handlers read those archived workspace members.

The live acceptance path compares canonical bytes directly for
duplicate/conflict decisions while the root-parent state exists. The
implementation does not restore that ledger after a root-parent restart and
does not retain a post-finalization receipt tombstone. The expected client
names are persisted in job metadata and restored, but accepted reports are
not. Job and study handlers stage one retained
`WORKSPACE` archive at a time on disk and read only fixed, bounded members;
they do not materialize the whole archive as Python `bytes`.

There is no second `RESOURCE_STATS` component. Nothing is written at
participant startup. There are no public start/final pairs, attempts, raw
periods, environment keys, end reasons, or stability checks.

This design requires NVFlare code changes. It requires no new privilege,
mount, sidecar, service, launcher argument, environment variable, job setting,
or operator setting.

## Process names

| Short name | Current process | Relevant responsibility |
| --- | --- | --- |
| CP | Client parent | Launches and waits for a client job, assembles its terminal report, releases the job's allocated compute resources, and then sends the report once. |
| CJ | Client job process | Runs one client's job application and leaves one private terminal measurement handoff for CP. |
| SP | Server parent | Launches the server job, assembles its local report, accepts reports, finalizes the rollup, and archives the server workspace. |
| SJ | Server job process | Runs the server-side application and leaves one private terminal measurement handoff for SP. |

These labels describe the code today. The stored record does not depend on
these processes continuing to exist in a future execution design.

## End-to-end sequence

```mermaid
sequenceDiagram
    participant CJ as Client job process
    participant CP as Client parent
    participant SP as Server parent
    participant SJ as Server job process
    participant Store as Existing job store
    participant CLI as nvflare CLI

    SP->>SJ: start server job
    CP->>CJ: start client job
    Note over CJ,SJ: start in-memory resource-time accumulators
    Note over CJ,SJ: no startup file or message
    SJ-->>SP: process ends; private handoff is local or returned
    CJ-->>CP: process ends; private handoff is local or returned
    Note over CP,SP: validate handoff; bind trusted name; assemble final bytes
    Note over CP: free launcher-managed compute resources
    CP->>SP: one REPORT_JOB_FAILURE completion request plus optional final report bytes
    SP-->>CP: terminal result plus resource-report status
    Note over SP: pass its final bytes through local acceptance; close cutoff and add accepted totals
    SP->>Store: archive existing server workspace as WORKSPACE
    CLI->>SP: authenticated job or study resources request
    SP->>Store: open retained WORKSPACE archive(s)
    SP-->>CLI: validated job or study result
```

## Exact current lifecycle

### 1. The server fixes expected participants

`JobRunner._start_run()` in
`nvflare/private/fed/server/job_runner.py` receives both the original selected
client names and the deployable subset that remains after deployment failures.
It starts the server and only that deployable client subset.

Before those start requests, the resource implementation records a separate
participant list containing every originally selected client and the server.
The list is fixed: neither a deployment failure nor a later start timeout
removes an entry. A selected client that never starts successfully or never
reports therefore remains visible as `missing`.

The selected client names are written to job metadata as
`JobMetaKey.RESOURCE_PARTICIPANTS`. If the root parent restarts while the job
is live, restore uses that field to rebuild the expected set; an older job
without the field falls back to the restored active clients. This preserves
the denominator across restart, but it does not restore reports that were
already accepted before the restart.

The expected entry uses the existing registered site name for a client and the
fixed trusted name `server` for SP. The name is already available in trusted
server state, so this feature
does not derive an HMAC pseudonym, distribute a new `START_JOB` header, or add
a launcher option, environment variable, or deployment setting.

The SP keeps the participant name and role in trusted per-job state. For an
incoming client report, it derives the expected name from the authenticated
sender and job context and requires the report to match. A name contained in
JSON is not authentication. The server also validates the trusted name as a
single safe archive path component before using
`participants/<participant_name>.json`. No attempt ID or environment key is
generated or delivered.

### 2. Each job process starts an in-memory accumulator

The official launchers establish a platform-owned startup boundary before the
hook:

| Launcher | Worker startup behavior |
| --- | --- |
| Process | The command is `<sys.executable> -I <absolute platform job_process_bootstrap.py> {client\|server} <existing args>`. The copied environment removes known app and site custom paths from `PYTHONPATH`; the bootstrap adds only its own NVFlare package root before running the fixed worker. |
| Docker | The command is `<configured python> -I -u -m nvflare.private.fed.app.job_process_bootstrap {client\|server} <existing args>`. Image `PYTHONPATH` remains in the environment but is ignored during startup and can be enabled after the snapshot. |
| Kubernetes | It uses the same installed bootstrap-module command. Image/template or study dependency paths are ignored during startup and can be enabled after the snapshot. |
| Slurm | Rank zero uses the same installed bootstrap-module command; its established dependency path remains in the environment but is ignored during startup. Launcher-owned nonzero-node commands receive their normal path. |

Python isolated mode ignores `PYTHONPATH` during worker interpreter startup,
so the effective startup search path is sanitized even when a dependency value
is preserved in the environment for later activation. This behavior is
internal to NVFlare and requires no job option, launcher argument, operator
configuration, or extra privilege.

All four launchers enter the same fixed bootstrap with a literal `client` or
`server` selector. The historical executable-module value is exact-allowlisted
only to select one of those two paths; it is never inserted into the command,
and any other value fails before launch.

The current CJ hook is immediately after its `Workspace` object exists and
before workspace download and before NVFlare activates the job and site custom
directories:

- `nvflare/private/fed/app/client/worker_process.py::main()`

The equivalent SJ hook is:

- `nvflare/private/fed/app/server/runner_process.py::main()`

The hook:

1. probes CPU, memory, and CUDA-visible GPU capacity;
2. records one monotonic clock anchor; and
3. creates an identity-free in-memory accumulator.

It does not write a start record, send a message, or persist recovery state.

After the snapshot, the worker downloads the workspace and calls
`activate_job_python_path()` to add the app and site custom directories to
`sys.path` and the environment for normal execution.

The accumulator integrates the initial capacity through the next explicit
capacity-change call or finalization. Current NVFlare code has no such mid-run
call, so this adapter assumes the initial capacity remains visible through the
measured window. That window begins before workspace download,
custom-directory activation, and application-runner setup, and ends in
`_archive_results()` after the runner returns and before workspace upload. The
current final reading follows the callback pre-drain and child F3 drain, so it
includes their actual elapsed tails; each is normally immediate and bounded by
five seconds. The optional post-stop callback wait occurs after publication and
is excluded. The window otherwise includes idle waits, but not the operating-
system process's entire lifetime. Phase 1 reports visible capacity-time, not
active-task time or hardware utilization.

The current collection adapter nevertheless exposes a platform notification:

```python
resource_collector.observe_capacity_change(new_capacity)
```

Before installing `new_capacity`, the call adds the previous capacity times
the elapsed monotonic duration. A future resource manager can use this method
when one accumulator owner remains alive for the participant. If future work
uses transient workers or runs tasks in CP/SP, it must instead move the
accumulator to an existing platform component whose lifetime spans the logical
participation. That is a replacement collection adapter, not a schema change,
and it does not require a user option or added privilege.

Each private interval product is rounded at most once to nine fractional
digits using round-half-even before checked exact-decimal addition. No binary
floating-point value enters the terminal JSON.

An end-of-job snapshot must never be multiplied by the entire process
duration. If a future allocator changes resources without notifying the
accumulator, the report is incomplete and must not pretend otherwise.

The current Slurm multi-node path needs the same honesty. It starts the NVFlare
worker on rank 0 and can run launcher-owned commands on other nodes. A probe in
the rank-0 process cannot observe those other nodes. Until a platform-owned
multi-node collector exists, a job with more than one Slurm node discards the
rank-zero numeric resource-time result and emits exactly
`resource_time: {status: unavailable, issues: [unsupported]}`. It never
presents rank-zero capacity as either a partial or complete multi-node total.

CPU and memory probing also fails closed at an applicable cgroup constraint.
If its value is unreadable or malformed, the affected dimension is omitted;
the code does not fall back to a wider affinity, online-CPU, or physical-memory
value. Other valid dimensions may remain, making the single compute result
partial. If none remains, it is unavailable.

When the server job process is restored from a snapshot, it starts a new
collector for the interval this new process can actually observe. Its numeric
post-restore values are retained, but the result is marked
`partial/observation_incomplete`; it is never presented as the complete
logical-job interval.

### 3. The application runs normally

The CJ starts `ClientAppRunner` from
`nvflare/private/fed/app/client/worker_process.py::main()`.
`ClientRunner` fires `START_RUN`, executes the workload, then fires
`ABOUT_TO_END_RUN` and `END_RUN`:

- `nvflare/private/fed/client/client_runner.py:689-702`
- `nvflare/private/fed/client/client_runner.py:712-788`
- `nvflare/private/fed/client/client_runner.py:812-835`

The SJ follows the same broad lifecycle and sends the existing fire-and-forget
`END_RUN` request before its local `END_RUN`:

- `nvflare/private/fed/server/server_runner.py:185-237`

No application event is the durable resource-report transport. Custom code
has no supported API for supplying capacity, timestamps, totals, models, or
traffic classes. This is not a tamper-proof boundary: a bring-your-own-
container entrypoint can run before the launcher-supplied Python command, a
global interpreter `sitecustomize` can still run under `-I`, and same-process
job code can affect later visible sources or alter the private handoff.

### 4. `_archive_results()` freezes a private child handoff

The final hook is `_archive_results()` in each job process:

- CJ: `nvflare/private/fed/app/client/worker_process.py::main()`
- SJ: `nvflare/private/fed/app/server/runner_process.py::main()`

After the runner has returned, cleanup first stops new application-command
admission. It waits up to five seconds for callbacks already admitted by that
gate while Cell and streaming are still alive. Timeout or error marks child F3
`partial/counter_gap`, because one of those callbacks could otherwise
originate traffic after publication. Before F3 streaming shutdown and workspace
upload, `_archive_results()` then:

1. advances the resource-time accumulator through the final monotonic time;
2. finalizes one `resource_time` object with one overall status;
3. observes the capacity of the filesystem containing the existing job
   workspace;
4. records retained content as `unavailable/not_bound`;
5. closes F3 admission, drains admitted operations for the fixed five-second
   internal bound, and freezes the child snapshot; and
6. serializes one private terminal measurement handoff.

Only after the handoff attempt does cleanup stop F3 streaming and Cell. If the
live-transport callback pre-drain did not finish, it performs one bounded
post-stop callback wait before closing security state. This keeps publication
bounded without freezing while an admitted callback can still send normally.

It writes the handoff atomically at:

```text
<workspace>/<job_id>/resource_stats/staging/terminal_handoff.json
```

`terminal_handoff.json` has an internal, bounded format. It carries the child
resource-time result, workspace-filesystem observation, retained-content
result, and child-local F3 counters. It is not the public schema and is never
renamed into `participants/`. The parent supplies the trusted job and
participant name when it assembles the public record.

```text
internal_version = "1"
kind = "nvflare.resource_stats.internal.terminal_handoff"
resource_time
workspace_filesystem
retained_content
child_f3
```

Those six fields are exact; the private handoff contains no job or participant
identity.

The parent reads only this fixed path. It requires a regular, non-symlink file,
enforces the 1 MiB bound before decoding, and uses the same strict UTF-8 JSON,
duplicate-key, finite-number, exact-number, and semantic-bound checks as the
public validator. The internal version, kind, and four typed measurement
objects are required; unknown fields are rejected.

After either parent has assembled final bytes, it removes the handoff and the
empty `staging` directory. SP must also remove them after a failed local
assembly or acceptance attempt. Finalization must confirm that no
`resource_stats/staging` member can enter the normal workspace archive.
For a separate-workspace launcher, the handoff may travel inside the existing
transient result-workspace ZIP so the parent can read it; that transfer bundle
is not the retained server `WORKSPACE` archive.

The process writes no public start or end observations. The parent-built final
report contains accumulated totals, not the private capacity-change intervals
used to calculate them.

If a normal Python exception reaches this `finally` path, the process still
attempts to finish the accumulator and write the handoff. `SIGKILL`, pod loss,
node loss, or another failure that bypasses the hook produces no child
handoff. If the parent survives and reaches assembly, it still builds one
public report with typed unavailable or partial results; it never invents
missing child measurements. Loss of the parent/site can still leave the
expected participant without a report.

The `child_f3` member contains the child process's origin-only F3 snapshot.
Trusted call sites classify real task responses and task results; a missing or
incomplete observation remains typed partial or unavailable. The later F3
section defines the exact boundary.

### 5. The existing launcher workspace path returns the private handoff

The parent does not need a new file-transfer mechanism:

- process, Docker, and Slurm launchers already expose the job workspace at the
  parent-visible run directory;
- the Kubernetes launcher already uploads the result workspace ZIP and
  extracts it before the job handle returns.

The CP reads the private handoff only after `job_handle.wait()`. The SJ handoff
is already in, or has been returned to, the SP run workspace when
`_job_complete_process()` observes that the server handle has finished.

Current client code waits for the handle, consumes the private handoff and
builds the terminal request, and then frees the allocated resources in
`nvflare/private/fed/client/client_executor.py::ClientExecutor._wait_child_process_finish()`.

At that point each parent performs one bounded assembly operation:

1. read and strictly validate the bounded child handoff;
2. close and freeze its job-scoped F3 counter immediately;
3. checked-merge child and parent contributions;
4. create the canonical `participant_summary` from trusted parent identity and
   the final measurements; and
5. delete the child handoff and empty staging directory.

If the child handoff is absent or invalid, the parent still assembles one
report. Child-derived resource time, workspace capacity, and retained content
are typed unavailable (or partial only where valid child values actually
exist). A usable parent F3 subtotal is retained as
`partial/attribution_incomplete`; if neither side is usable, F3 is unavailable.
The parent does not substitute elapsed wall time, an end snapshot, filenames,
or generic process network totals.

CP frees launcher-managed compute resources immediately after this assembly
and handoff cleanup, then sends the canonical bytes once and waits for the
CellNet reply. SP passes its canonical bytes directly through the local
acceptance function. Neither parent retains the private handoff, and the
handoff is never a final resource-namespace or retained job-store archive member.

The current measurement closes before CP frees the allocated resources, but
the completion request and its reply wait occur after that release. A slow or
unavailable root server therefore does not keep a completed client's GPU, CPU,
or memory allocation held. This is a description of current ordering, not an
assumption that a future workflow must hold resources for the whole job.

### 6. F3 owner and cutoff

SP creates its job-scoped parent F3 counter after the scheduler selects a job
and before `JobRunner._deploy_job()`. This is early enough to count the
included `job_application` sends. SP forwarding does not count again.

CP creates its counter in `ClientExecutor.start_app()` after it has validated
the authoritative `START_JOB` metadata against deployed metadata and before it
selects the launcher or calls `launch_job()`. The current three-class allowlist
normally gives CP a zero contribution. The earlier deployment payload is
incoming and is counted once by its SP origin, not by CP. Merely seeing an
untrusted low-level route or a job-supplied header cannot create or bind a
counter.

The parent counter API is internal platform state keyed by the trusted job
context. It adds no launcher argument, environment variable, job setting, or
operator configuration. The resource-report request and workspace upload are
excluded by traffic class and occur only after CP's counter has frozen.

## Client-to-server completion transport

The implemented transport is Option A: one application-level send on the
existing `REPORT_JOB_FAILURE` request. It carries the job outcome and optional
resource report together, uses the existing authenticated sender binding, and
returns a flat report status. There is no report retry loop or receipt
tombstone.

Option B remains an unimplemented fallback if review rejects Option A's name or
handler ownership. It would require mixed-version selection, but no operator,
job, or launcher setting and no dual send.

### Option A: extend the existing CellNet exchange

The CP already sends a terminal request after every child exit, including exit
code zero:

| Item | Current value |
| --- | --- |
| Target | `FQCN.ROOT_SERVER` |
| Channel | `CellChannel.SERVER_MAIN`, wire value `task` |
| Topic | `CellChannelTopic.REPORT_JOB_FAILURE`, wire value `report_job_failure` |
| Timeout | existing `job_query_timeout`, default five seconds |
| Receiver | `FedServer.process_job_failure()` |

The channel and topic are defined in
`nvflare/fuel/f3/cellnet/defs.py`; `JobFailureMsgKey` is in
`nvflare/private/defs.py`. The current handler is registered by
`FedServer._register_cell_callbacks()` and implemented by
`FedServer.process_job_failure()` in
`nvflare/private/fed/server/fed_server.py`.

The topic name is historical: the request is already sent on success. Reusing
it provides one existing session-bound completion exchange and one cutoff. In
secure mode, the Cell incoming filter validates the signed token and binds it
to the message origin before this handler runs. In insecure mode, the handler
has only the existing registered-session-token check; resource statistics do
not add attestation that the deployment did not already have.

This is the implemented choice because it changes the fewest completion-path
mechanics. Its drawbacks are the stale failure-oriented name and placing new
resource-report work in the historically named failure handler.

### Option B: use a new versioned completion exchange

If reviewers reject modifying `REPORT_JOB_FAILURE` because of its name or
handler ownership, CP can instead send the combined outcome and report on a
new completion topic:

| Item | Proposed value |
| --- | --- |
| Target | `FQCN.ROOT_SERVER` |
| Channel | `CellChannel.SERVER_MAIN`, wire value `task` |
| Topic | `CellChannelTopic.REPORT_JOB_COMPLETION`, wire value `report_job_completion` |
| Protocol field | exact integer `protocol_version: 1` |
| Timeout | existing `job_query_timeout`, default five seconds |
| Receiver | new `FedServer.process_job_completion()` delegating to the shared completion and report-acceptance logic |

If implemented, Option B would replace Option A for that completion; it would
not be a second report message. It would use the same connection, completion
cutoff, validation, and live acceptance rules. The protocol field would
version the combined completion envelope; the embedded `participant_summary`
would retain its independent `schema_version`.

Option B fixes only the stale topic name and ownership objection. Validation,
direct canonical-byte comparison, bounded in-memory ledger insertion, and
reply handling still run in the critical job-completion path. Participant-file
publication still occurs later at finalization under either option. If
reviewers require lifecycle control and resource-data delivery to be separate,
neither Option A nor Option B satisfies that requirement; a different two-path
protocol would be needed.

### Completion envelopes

Option A extends the existing envelope:

```text
{
  "job_id": string,
  "code": integer,
  "reason": string or null,
  "resource_report": {                 # optional
    "participant_summary": bytes       # canonical UTF-8 JSON, at most 1 MiB
  }
}
```

Option B carries the identical outcome and resource-report members, with an
explicit envelope version:

```text
{
  "protocol_version": 1,
  "job_id": string,
  "code": integer,
  "reason": string or null,
  "resource_report": {                 # optional
    "participant_summary": bytes       # canonical UTF-8 JSON, at most 1 MiB
  }
}
```

`reason` is part of the existing terminal job outcome. It is not a resource
measurement end reason and is not copied into `participant_summary`.

The CP sends the exact parent-assembled bytes once. The child does not provide
the public bytes. A missing or invalid child handoff normally
produces a valid parent-built report with typed unavailable or partial values.
CP omits `resource_report` only if parent assembly itself
fails, the final bytes exceed the bound, or they cannot fit the Cell's
effective payload limit; it still sends the unchanged terminal outcome.

`send_request_before_shutdown()` serializes the selected send with logout so
the existing client token remains usable:

- `nvflare/private/fed/client/fed_client_base.py:423-443`

### Send and reply

CP makes one application-level call with the existing `job_query_timeout`.
SP keeps the first accepted canonical bytes in the live coordinator state and
compares retries with them directly. It does not keep a post-finalization
receipt tombstone or restore this accepted state across a root-parent restart. Restore
rebuilds expected names from `RESOURCE_PARTICIPANTS`, clears the stale
in-progress resource directory, and starts a new empty acceptance ledger. A
pre-restart client report therefore becomes `missing` unless that client sends
a new valid report after restore; current clients send only once.

The reply is:

```text
{
  "resource_report_status": "accepted" | "duplicate" | "invalid" |
                            "conflict" | "too_late" | "not_provided" |
                            "not_expected" | "server_error"
}
```

This acceptance status describes validation and insertion into the live
root-parent ledger; it is separate from the one measurement status inside
`resource_time`. It does not mean that a participant file is already written
or that the acknowledgement survives a root-parent restart.

Under implemented Option A, validation, canonicalization, direct byte
comparison, and bounded ledger insertion happen before the server resolves
that participant's terminal
outcome. This synchronous work can add latency to completion, but participant
file writes and fsync occur only at finalization. The report cannot change the
job result and does not add a second reporting window.

## Server authentication and acceptance

The outgoing filter adds the client name, token, token signature, and SSID:

- `nvflare/private/fed/client/communicator.py:107-131`
- `nvflare/fuel/sec/authn.py:68-92,114-150`

In secure mode the SP verifies the signed token and binds it to the CellNet
origin before the callback:

- `nvflare/private/fed/server/fed_server.py:522-550,1226-1237`
- `nvflare/private/fed/authenticator.py:384-420`

In insecure mode that cryptographic filter is not installed. The callback
still requires a token in the current registered-client map at
`nvflare/private/fed/server/fed_server.py:910-918`. The design inherits that
existing trust level; it does not describe an insecure deployment as signed or
attested.

The callback maps that token to a registered client and checks that the
participant list fixed before start requests contains the client. It then requires the
JSON `participant_name` to equal that trusted registered name; the field never
authenticates itself.

The implemented handler first authenticates and binds the job/client, then handles
the optional resource report idempotently, and only then processes the terminal
outcome if that outcome is still pending. This ordering is implemented under
Option A, so a repeated request can still reach live report acceptance without
replaying a job failure/abort action. Option B is not implemented.

The resource acceptance function:

1. checks the authenticated job and participant;
2. checks the 1 MiB bound before decoding;
3. performs strict UTF-8 JSON parsing, rejecting duplicate keys and non-finite
   numbers;
4. validates the schema, semantic bounds, job ID, expected participant name,
   model grouping, one overall resource-time status, and exact number forms;
5. requires the bytes to equal the deterministic canonical serialization of
   that validated record;
6. accepts `resource_time` as the parent-assembled participant total derived
   from the child's private handoff;
7. under the per-job lock, compares the canonical bytes directly with any
   accepted bytes for that participant and retains the first valid canonical
   bytes and receipt time in the root parent's live ledger; and
8. acknowledges `accepted` after that in-memory insertion.

Each report is capped at 1 MiB. Across one live job, accepted canonical report
bytes are capped at 64 MiB. Acceptance performs no participant-file write or
fsync. Those operations happen at finalization, so an `accepted`
acknowledgement is not restart-durable.

The server cannot recompute CPU unit-seconds, memory byte-seconds, or GPU
instance-seconds because the simplified report contains no raw periods. It can
still reject malformed, impossible, negative, non-finite, inconsistent, or
out-of-bound values. This is the principal trust tradeoff of the final-only
design.

Replay behavior is deterministic only while live acceptance state exists:

- first valid canonical byte sequence: `accepted`;
- the same accepted bytes: `duplicate`, including after cutoff while the live
  job state remains;
- different valid canonical bytes before cutoff: `conflict`;
- invalid candidate: `invalid`, without reserving the slot;
- new bytes after cutoff: `too_late`.

The terminal outcome is resolved in a `finally` path regardless of resource
status. Resource reporting never changes success, failure, or abort.

SP validates the SJ handoff, checked-merges SJ and SP F3 snapshots, and
assembles canonical bytes with its trusted local identity. It passes the bytes
through the same validator and live-ledger function, which performs the same
direct byte comparison. It does not send a fake loopback CellNet message. After either accepting or
rejecting the final bytes, SP removes the private handoff and staging
directory. Staging is not part of the final resource namespace and is not
copied into the final job archive.

## Cutoff, reduction, and workspace archival

### Existing cutoff

When `_job_complete_process()` first observes that SJ has exited, the server
job handle has already completed. SP builds the server participant report from
the SJ handoff as described above, makes one local acceptance attempt, and
removes the staging path whether the attempt succeeds or fails. Normal
completion then reuses the existing client-outcome wait, whose current default
is 900 seconds. The setting and cutoff are owned by `JobRunner.__init__()` and
`JobRunner._job_complete_process()`.

There is no separate resource-report wait. Once every pending outcome arrives
or the existing deadline expires, SP closes acceptance and snapshots the
expected list and accepted ledger under the same lock used by acceptance.

Abort and server-process failure follow today's immediate finalization path:
SP performs the same bounded parent assembly and local acceptance, does not
wait for clients, and closes acceptance immediately. The existing 900-second
client-outcome grace period is not applied after a server-process failure.
Late reports cannot rewrite the result.

### Reduction

For each expected participant, the finalizer records:

- `accepted` plus the validated resource values;
- `invalid` only when no report was accepted and at least one correctly bound,
  pre-cutoff candidate failed report validation; its `received_at` is the first
  such rejection and its issue is `malformed_source`;
- `missing` when no report was accepted and the remaining outcomes were only
  `not_provided`, `too_late`, authentication/binding rejection, or
  `server_error`; and
- `disabled` when collection was intentionally unavailable for that expected
  participant.

An accepted report always wins the final classification. `duplicate` keeps it
accepted, and `conflict` can occur only after that accepted slot exists. A
server persistence or validation fault is therefore never relabeled as
client-invalid.

For accepted entries the finalizer adds the final reported values:

```text
job measured seconds       = sum(participant measured seconds)
job CPU unit-seconds       = sum(participant CPU unit-seconds)
job memory byte-seconds    = sum(participant memory byte-seconds)
job GPU instance-seconds   = sum(participant GPU instance-seconds)
job retained bytes         = sum(participant retained bytes)
job F3 remote-accepted bytes/messages = sum(participant remote-accepted values)
```

`measured_seconds` is additive participant time. It can exceed the job's wall
clock duration when several participants run at the same time.

It validates these additions with checked arithmetic, but it does not recreate
participant totals from hidden or guessed intervals.

The finalizer never sums `workspace_filesystem.capacity_bytes`.

It derives totals from the validated canonical bytes already held in the live
coordinator, not by trusting a child-side re-read. Only at finalization does it
write and fsync the exact accepted in-memory participant bytes through
parent-owned, no-symlink descriptors. It then writes and fsyncs
`resource_summary.json` atomically last in the local construction directory as
the publication marker.

The server serializes and size-checks the completed bundle before publication.
If `resource_summary.json` exceeds 64 MiB, it removes the incomplete
`resource_stats` construction directory and continues normal job archival. The
job outcome is unchanged, but its resource view is unavailable.

Before either write, finalization verifies that `resource_stats/staging` is
absent. Archive tests enumerate every `resource_stats/` ZIP member and fail if
a staging member or any file other than the summary and the participant files
derived from its accepted entries is present.

### One stored copy

`JobRunner._save_workspace()` stores the server workspace in the existing
`WORKSPACE` job-store component.

The relevant members are exactly:

```text
resource_stats/participants/<participant_name>.json
resource_stats/resource_summary.json
```

There is no `RESOURCE_STATS` component, database copy, or generic component
prefix. If normal workspace archival ultimately fails, the job can still have
a terminal status but its resource data is unavailable to the CLI.

The local summary-last sequence happens before `_save_workspace()`. It does not
constrain ZIP member order; the reader validates the summary-derived namespace
without relying on archive entry position.

The existing workspace layout may flatten separate run, result, log, and audit
roots into one ZIP namespace. Resource reporting does not build a second
filtered workspace archive. On read, the fixed-member verifier treats the
summary as the publication marker, derives the exact accepted participant
filenames, and requires the complete `resource_stats/` ZIP inventory to equal
that namespace. It rejects duplicate names, staging files, missing expected
files, and every extra member. A collision introduced by another flattened
root therefore makes the resource view unavailable rather than selecting one
ambiguous copy.

## CLI reads the existing workspace

The CLI may run on another machine, so it cannot literally open the server's
filesystem. An authenticated server command opens the already stored
`WORKSPACE` on the CLI's behalf and returns only validated resource JSON.

### One job

```bash
nvflare job resources --job JOB_ID
nvflare job resources --job JOB_ID --study STUDY_NAME
nvflare job resources --job JOB_ID --study STUDY_NAME --site SITE_NAME
nvflare job resources --job JOB_ID --study STUDY_NAME --format json
```

`--job` alone uses the `default` study. Combining `--job` with `--study`
selects that active study during CLI login; the study name is not trusted from
the resource report.

The command does not search across studies. Job visibility is bound to the
authenticated session's active study, so a job outside that study intentionally
appears not found, matching the other job commands.

The new `GET_JOB_RESOURCES` handler uses existing job/study authorization and
the current staging path:

```text
JobDefManager.get_storage_for_download(
    jid=job_id,
    download_dir=request_temp_dir,
    component=WORKSPACE,
    download_file=WORKSPACE_ZIP,
    fl_ctx=fl_ctx,
)
```

Relevant current patterns are `JobDefManager.get_storage_for_download()`, the
filesystem backend's download-link path, and the existing archived-log and
full-job download handlers in `nvflare/private/fed/server/job_cmds.py`.

The handler stages the archive as a request-scoped file and reads only the
fixed summary name and, for `--site`, the one participant name derived from
it. It rejects duplicate ZIP names, encrypted entries, unsafe paths,
oversized records, truncation, duplicate JSON keys, an invalid summary, and
any missing or extra resource member. A participant-detail read additionally
rejects an invalid schema, identity mismatch, or copied-value reconciliation
failure for that selected participant. It does not extract the archive into a
general directory. It removes the request-scoped temporary directory in a
`finally` path after the response has been assembled. The whole archive is
never loaded into a Python `bytes` object.

Without `--site`, it returns the validated job summary. With `--site`, it
validates the requested name against the trusted participant list and then
opens the exactly derived `participants/<participant_name>.json` member.

Python's ZIP reader verifies the stored CRC while reading a member, which can
detect accidental corruption of that member. That CRC is not a cryptographic
integrity check or signature, and the feature makes no signing claim for these
files.

The handler uses the current job-CLI terminal predicate: a status beginning
with `FINISHED:`, or the exact legacy value `FINISHED_OK`,
`FINISHED_EXCEPTION`, `ABORTED`, `ABANDONED`, or `FAILED`. For any other status
it returns the existing `JOB_RUNNING`/not-done style error without trying to
read a live workspace.

### All retained jobs in one study

```bash
nvflare job resources --study STUDY_NAME
nvflare job resources --study STUDY_NAME --format json
```

`--study` without `--job` selects all retained jobs in that study. The bare
`nvflare job resources` command shows help, and `--site` requires `--job`.
The study name selects the active study at login. The `GET_STUDY_RESOURCES`
handler:

1. applies the server's current active-study authorization;
2. runs one existing job-store scan, materializes the returned job IDs and
   statuses, and does not reclassify them while it reads archives;
3. applies that same current job-CLI terminal predicate and excludes every
   other status;
4. stages one terminal job's `WORKSPACE` in a temporary directory, reads and
   validates its `resource_summary.json` through the same fixed-member reader,
   then removes that temporary directory before advancing to the next job;
5. labels each terminal job `included` or `unavailable`;
6. adds resource-time, retained-content, and F3 remote-accepted values for
   included jobs; and
7. never adds workspace-filesystem capacity.

The server selects study membership from existing trusted job metadata, never
from a value supplied by a participant report.

One unavailable terminal archive does not discard other valid jobs. The
response includes included, unavailable, and nonterminal-excluded counts and a
per-job status list.

This is one materialized scan, not an atomic job-store snapshot. A job observed
as nonterminal by the scan remains nonterminal in that response even if it
finishes while archives are being read. A terminal archive that is absent when
read is unavailable. At most one complete workspace archive is staged for this
loop at a time, and the reader loads only the bounded resource members into
Python memory.

If the materialized scan contains more than 10,000 jobs, v1 fails the request
before reading archives and returns no rows or totals. It does not page a total
that could be mistaken for the whole study.

Before appending each job, the handler charges that prospective row's
canonical JSON size against a cumulative 64 MiB row budget. It then serializes
the complete study response and checks the same 64 MiB limit again. If either
check fails, it returns `RESOURCE_VIEW_TOO_LARGE` with no partial rows or
totals. It never truncates a study result or derives totals from a prefix.

This view is calculated on demand. It creates no study-level stored component
or duplicate job summary. It covers only retained jobs materialized by that
scan; a deleted job has no archive to query. The output must not be described
as an audit or billing ledger.

For a filesystem backend, staging may use a local link. A remote backend may
need to fetch each retained workspace archive. If that is too expensive at
study scale, the later optimization is a narrow archive-member read or bounded
server cache—not a second durable copy of the same statistics.

## F3 counter bindings

Phase 1 counts the sender only. The receiver does not add the same payload to
the primary total. More precisely, it counts only the process that originates
one of the trusted semantic operations. A relaying or forwarding process does
not count the payload again. A remote logical destination still counts once at
the origin when routing begins through a local first-hop relay; that is not a
final in-process delivery.

F3 pools are process-local, so one process cannot claim traffic observed by
another. Phase 1 adds one job-scoped counter in each parent and one in each job
process. The child freezes its local contribution into the private handoff.
After the job handle finishes, the parent closes admission to its own counter,
freezes immediately, and merges compatible child and parent fields with checked
arithmetic before it creates `participant_summary`. CP originates no included
class, and SP's blocking deployment sends have already finished. Any parent
operation still pending is therefore a `counter_gap`, not work to delay
terminal publication for.

Any missing contribution or incomplete child drain is represented honestly. If one
bounded contribution remains usable, F3 is partial with the applicable issue;
if none is usable, F3 is unavailable. A missing or invalid child handoff never
causes the parent to substitute generic process totals. A restored server
parent keeps its new subtotal as `partial/attribution_incomplete`, rather than
claiming that pre-restore traffic was zero.

The parent/child merge combines non-overlapping semantic origins. SP originates
job deployment, SJ originates real task responses, and CJ originates task
results. CP owns a counter for lifecycle consistency but normally has no
positive contribution under this three-class allowlist. The accounting context
is a local Python object and is not serialized, so a receiver or forwarder
cannot inherit counting authority.

The low-level route cannot decide by itself whether bytes belong to a job.
Platform code assigns job and traffic class at these call sites:

| Class | Current route | Binding rule |
| --- | --- | --- |
| `task_response` | Reply to `server_command/get_task` | `ServerCommandAgent` tags only a platform-produced real-task reply and pre-admits its known SJ/requester pair before the callback returns. Encoding and transport later supply the byte count and outcome. |
| `task_result` | `server_command/submit_update` from `Communicator.submit_update()` | The communicator supplies trusted job ID and fixed class. Exclude the ACK. |
| `job_application` | Inner `train.deploy` over outer `admin/admin` | `JobRunner` supplies the existing job-scoped SP counter and fixed class when it sends the deployment requests. The shared outer route alone is not authority. |

There is no task-request class. A real task response already represents the
useful work assignment. There is also no separate stream class. If FOBS moves a
large value through `DownloadService`, its successfully accepted unique source
bytes remain part of the originating job-application, task-response, or
task-result operation.

Explicit exclusions include task requests, empty polling, all ACK/control
traffic, final delivery to an in-process logical destination, sends that fail
before acceptance, a relay's duplicate contribution, workspace transfer, the
terminal resource report, authentication, heartbeat, quit, shutdown, job
heartbeat, logs, federated events, HCI, bulk envelopes, and every unrecognized
or unbound route.

Count the main payload after FOBS encoding and before optional end-to-end
encryption. Exclude Cell headers, encryption expansion, driver/TLS framing,
transport compression, and retransmissions. Fan-out counts one top-level
logical message per remote destination. `DownloadService` data adds bytes to
that operation without another message; repeated chunks and retries do not add
bytes again. Increment `remote_accepted` only after local transport acceptance.

For a normal CoreCell send, `_send_to_endpoint()` encodes, reuses an owner
pre-admission or lazily admits, retains the encoded size, optionally encrypts,
and then sends. A send without error
completes the admission unless the chosen local endpoint is also the logical
destination. An error or that exact final local delivery abandons it. A local
endpoint used only as the first hop toward a different destination still
completes the origin's remote logical send.

For an existing Cell blob stream, `ByteStreamer.send()` admits the already
FOBS-encoded `BlobStream` immediately before it constructs and starts `TxTask`.
A final process-local target is not admitted, while a remote logical target
remains admitted even if its first routing hop is local. A setup/start exception
abandons the admission. Otherwise it remains pending until the entire
`StreamFuture` reaches a terminal result: success commits `stream.get_size()`
once, and asynchronous failure or cancellation abandons it. Stream frames and
retries do not carry the accounting context.

During FOBS encoding, each `DownloadService` transaction registers against the
same operation before the main transport attempt; the task-response owner
admission may already exist. A source data reply
uses a stable source-owned logical chunk identity and adds only its raw produced
data length after local acceptance. The operation completes only after the
main send and every registered transaction succeed for that destination. A
failed transaction, unknown receiver, unstable chunk identity, or ambiguous
settlement discards that operation and records `partial/counter_gap` rather
than publishing an undercount.

`CoreCell._send_to_endpoint()` exposes the useful low-level boundary:

- `nvflare/fuel/f3/cellnet/core_cell.py:1326-1358`
- `nvflare/fuel/f3/cellnet/core_cell.py:1365-1407`

The existing generic StatsPool is not sufficient because it combines protocol
traffic, lacks reliable job/class ownership, uses floating-point MiB, and does
not provide the required cutoff record. Any runtime coverage gap remains
partial or unavailable rather than being replaced by generic process totals.
The focused [F3 status document](F3_GAP.md#validation-status) records the
passing focused/socket-backed suites and the remaining live-run evidence.

## Why use one completion message

| Mechanism | Useful property | Decision or limitation |
| --- | --- | --- |
| Option A: extend `REPORT_JOB_FAILURE` | Reuses the current authenticated parent request after child exit; covers success and failure; server already waits. | Primary proposal. The old topic name and handler ownership are confusing, and synchronous report work adds completion latency. |
| Option B: new versioned `REPORT_JOB_COMPLETION` | Gives the combined lifecycle outcome and report an accurate name and explicit envelope version. | Fallback for the naming/ownership objection. It replaces Option A rather than adding a message, but needs a mixed-version rollout decision and has the same completion-path cost. |
| Separate resource-report CellNet topic | Separates lifecycle control from resource data. | Adds another message, acknowledgement, correlation path, and cutoff race. This is a different design and is required if reviewers insist on that separation; neither one-message option provides it. |
| CJ-to-SJ Aux | Existing job-scoped request/reply. | Job cells are tearing down and a crashed CJ cannot send. |
| Federated event | Convenient application event. | Outgoing delivery is best effort and is not durable acceptance. |
| Task/model metadata | Reuses application messages. | Some jobs have no final result; messages can be filtered, retried, or rejected after workflow teardown. |
| Server pull | Central timing. | Requires every job cell to stay alive and couples the format to current topology. |
| Client workspace only | No explicit report message. | The server archive does not automatically contain each client workspace and has no authenticated readiness signal. |
| Separate job-store component | Fast direct lookup. | Duplicates `WORKSPACE` data and creates consistency problems. |

Current production uses Option A and sends exactly one completion request.
If Option B is later implemented, it should change only the envelope/topic,
not the public report, acceptance semantics, archive, cutoff, or CLI. There is
no dual-send mode or operator configuration.

## Current failure behavior and explicit target cases

| Event | Result |
| --- | --- |
| One startup probe fails | Finish one report with partial or unavailable resource time; do not fail the job. |
| An applicable cgroup CPU or memory value is unreadable or malformed | Fail that dimension closed; do not substitute a wider host or process-visible value. Keep other valid dimensions as partial, or report unavailable when none remains. |
| Slurm uses more than one node | Resource time is `unavailable/unsupported`; publish no rank-zero numeric totals and do not infer other-node capacity. |
| Server job process is restored from a snapshot | Measure the new process interval and mark it `partial/observation_incomplete`; do not claim that it covers the pre-restore interval. |
| Normal application exception reaches child finalization | Freeze the private handoff if possible; the parent still owns final assembly. |
| A command callback is still active during child cleanup | Close command admission and pre-drain for up to five seconds while Cell/streaming remain alive. Timeout or error marks F3 `partial/counter_gap`; after publication and transport stop, retain one bounded post-stop wait. |
| A child F3 operation is still active at the cutoff | After the callback pre-drain, stop waiting after the fixed five-second F3 drain, freeze once, and preserve the bounded subtotal as `partial/counter_gap`. |
| A blob stream fails or is cancelled asynchronously | Keep its admission pending until terminal `StreamFuture` outcome, then abandon it without adding public counters. |
| A parent F3 operation is unexpectedly pending at cleanup | Freeze immediately and mark the merged F3 subtotal partial with `counter_gap`; do not block parent completion. |
| Hard child or launcher-managed pod loss bypasses `_archive_results()`, but the parent survives | Parent builds one report with unavailable child-derived measurements; any usable parent F3 subtotal is `partial/attribution_incomplete`. |
| Parent/site loss prevents parent assembly or delivery | No report reaches SP; the expected participant is missing. |
| Separate-workspace upload fails | Parent treats the handoff as missing and builds the same typed partial/unavailable report. |
| Selected CP completion request or reply is lost | Current CP does not retry. A lost request can leave a missing report; a lost reply can follow successful acceptance. |
| Invalid JSON or schema | Reject candidate without reserving the participant slot. |
| Different second valid report | Keep the first and return conflict. |
| Report arrives after cutoff | Return too late and do not change archived bytes. |
| Server job process fails | Skip the normal client-outcome grace period, perform the server's bounded local assembly, and close acceptance immediately. |
| Root parent restarts after accepting client reports but before rollup | Restore rebuilds the original expected names, resets stale resource artifacts, and starts an empty ledger. Pre-restart reports are not restored and normally become `missing` because clients do not retry. |
| Private staging cleanup cannot be completed | Do not publish `resource_summary.json`; discard the incomplete bundle so the handoff cannot be archived. |
| Workspace archival fails | Resource data is unavailable to both job and study CLI. |
| Stored ZIP or resource record is corrupt or inconsistent | Do not print unverified totals; mark that job unavailable in a study view. |

Child handoffs and their child-derived measurements are self-reports, not
immutable evidence. The parent supplies trusted identity, but this still is
not hardware attestation. Durability exists
only after the normal server workspace save succeeds.

## Current adapter and future GPU release

The current adapter is deliberately small:

```python
resource_collector = JobResourceCollector(run_dir)

# Existing job process runs. Current code makes no capacity-change calls.

handoff = resource_collector.finish()
```

A future resource implementation may keep the current accumulator owner and
call:

```python
resource_collector.observe_capacity_change(current_capacity)
```

at each boundary it owns. The accumulator first closes the elapsed private
interval, then changes capacity. The private handoff and parent-built final
report still contain only totals.

Nothing in this contract assumes a permanent supervisor, a GPU-free process,
a successor worker, or held CPU/memory capacity. The *current adapter* does
assume that one CJ/SJ process survives from initial probe through finalization.
If future code replaces that lifetime with transient workers or CP/SP task
execution, it must replace the child collection/handoff adapter with one that
covers the actual execution intervals. The parent-assembly boundary is the
stable seam: it accepts typed terminal measurements plus parent F3 and emits
the same final participant format. The job rollup, archived workspace layout,
and CLI contract do not change, and no user-facing configuration is
introduced.

## Production code and remaining changes

| Current file or area | Change |
| --- | --- |
| `nvflare/apis/fl_constant.py` | **Implemented:** `GET_JOB_RESOURCES` / `GET_STUDY_RESOURCES`; no resource-specific start identity. |
| `private/fed/server/job_runner.py` | **Implemented:** persist all selected client names, launch only the deployable subset, own SP F3 deployment accounting, restore expected/F3 state conservatively, perform server local assembly, cutoff, rollup, local summary-last publication, and unchanged normal workspace save. **Remaining:** accepted-ledger/cutoff recovery. |
| official Process/Docker/Kubernetes/Slurm launchers | **Implemented:** run the NVFlare worker with Python `-I` and keep app/site custom paths out of startup `PYTHONPATH`, without a user setting or extra privilege. BYOC entrypoints and global interpreter `sitecustomize` remain outside this boundary. |
| client/server job-process entry points | **Implemented:** start the in-memory accumulator before workspace download and custom-path activation, then freeze one private terminal handoff in `_archive_results()`. |
| client/server command and communicator paths | **Implemented:** bind only real task responses and task results at their trusted semantic origins; task requests and acknowledgements remain excluded. |
| `private/fed/resource_stats/*` | **Implemented:** fail-closed probes, accumulation, F3 state/cutoff, private-handoff validation, checked child/parent F3 merge, canonical final assembly, public validation, exact arithmetic, bounded in-memory acceptance, finalization-time atomic/fsynced files, and a fail-closed path-backed archive reader. **Remaining:** retained-result provider. |
| `private/fed/client/client_executor.py` | **Implemented:** after `job_handle.wait()`, close/freeze parent F3 immediately, validate and merge the handoff, bind the trusted site name, delete staging, free allocated compute resources, and then send exact bytes once on Option A. **Remaining:** any approved retry/recovery behavior. |
| `fuel/f3/cellnet/defs.py` | **Implemented:** keep `REPORT_JOB_FAILURE`. **Fallback only:** Option B would add `REPORT_JOB_COMPLETION`. |
| `private/defs.py` | **Implemented:** Option A report and flat status keys. **Fallback only:** Option B would add a versioned completion envelope. |
| `private/fed/server/fed_server.py` | **Implemented:** Option A authenticates and processes the report before the once-only terminal outcome. **Remaining:** no receipt tombstone; Option B is not registered. |
| F3 call sites, FOBS/DownloadService, and CoreCell | **Implemented and focused-tested:** process-local trusted context, origin-only fan-out, after-FOBS/before-encryption sizing, accepted unique large-object byte folding, retry suppression, streamed terminal outcome, child callback pre-drain, and remote-acceptance completion. The focused/socket-backed suites pass; a new live run remains. |
| `private/fed/server/job_cmds.py` | **Implemented:** authorized job/study handlers that stage one normal workspace archive at a time and use the safe fixed-member reader without loading the full archive into memory. |
| `fuel/flare_api/flare_api.py` and `tool/job/job_cli.py` | **Implemented:** session APIs and exact job/study CLI forms. |
| JobDefManager/storage backends | No new resource component API. The private handoff uses the existing run workspace temporarily; only final resource members remain in the normal `WORKSPACE` archive. |

## Remaining code proofs

1. Broaden platform coverage and validate CUDA/NVML matching across supported
   CUDA Runtime, NVML, full-GPU, and MIG versions.
2. Capture a new process-mode F3 run; the focused suite for semantic filtering,
   transport, streaming, OOB data, lifecycle cutoff, merge, restore, and
   self-exclusion already passes the current focused/socket-backed suites.
3. Identify authoritative bounded retained-result sets.
4. Decide whether root-parent restart must recover accepted report bytes,
   invalid history, and cutoff state. Expected participant names are already
   persisted and restored; accepted state is not.
5. Test the fixed 10,000-job study bound and remote-store performance.
6. Keep implemented Option A, or implement and prove mixed-version selection
   for Option B without dual sending or a new operator setting.
7. Select the initial OS, cgroup, container, Kubernetes, and Slurm support
   matrix; keep Slurm multi-node resource time `unavailable/unsupported` until
   a collector covers non-rank-0 nodes.
8. Decide whether delivery retries/tombstones are required; if so, implement
   and test them. Continue proving staging-member absence from every archive.

These gaps change coverage or the chosen one-message completion hook, not the
one-report format, shared acceptance semantics, workspace-only storage, or
study-rollup semantics.
