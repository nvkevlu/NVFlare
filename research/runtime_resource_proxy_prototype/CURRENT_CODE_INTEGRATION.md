# Phase 1 integration with the current NVFlare code

Status: proposed production integration for review.

This document connects the Phase 1 data contract to the code that exists
today. It does not assume any particular future task runner or GPU-release
design.

The proposed path is:

1. The current client and server job processes each record one measurement
   period.
2. Each job process leaves one final site report in its existing job
   workspace.
3. The client parent sends the client report with the terminal job-outcome
   request it already sends to the server parent.
4. The server parent validates every report, calculates the totals, and writes
   the final files into the existing server job workspace.
5. The normal workspace archive stores those files in the existing
   `WORKSPACE` job-store component.
6. `nvflare job resources` reads the files from that archived workspace.

There is no `RESOURCE_STATS` component and no second copy of
`resource_summary.json`.

This design requires NVFlare code changes. It requires no new privilege,
mount, sidecar, service, launcher option, environment variable, job setting,
or operator setting.

## Process names used below

| Short name | Current process | Relevant responsibility |
| --- | --- | --- |
| CP | Client parent | Launches and waits for a client job, then reports its terminal outcome. |
| CJ | Client job process | Runs one client's job application. |
| SP | Server parent | Launches the server job, receives client outcomes, finalizes the job, and archives the workspace. |
| SJ | Server job process | Runs the server-side job application. |

These names describe the current code only. The record API below does not
require the future implementation to keep these process boundaries.

## End-to-end flow

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
    Note over CJ,SJ: begin one current-process measurement period
    SJ-->>SP: job ends; workspace is already local or returned
    CJ-->>CP: job ends; workspace is already local or returned
    CP->>SP: existing terminal-outcome request + optional report bytes
    SP-->>CP: report status and digest
    Note over SP: fixed cutoff; validate and reduce all expected participants
    SP->>Store: archive existing server workspace as WORKSPACE
    CLI->>SP: authenticated job-resources request
    SP->>Store: open archived WORKSPACE
    SP-->>CLI: validated summary and optional site detail
```

The site report is `participant_summary`. The server rollup is
`resource_summary`. The exact fields and formulas remain those in the
[field catalog](schema/FIELD_CATALOG.md) and the
[semantic contract](schema/contract_v1.py).

## Exact lifecycle in the current code

### 1. The server fixes the expected clients

`JobRunner._start_run()` receives the selected clients, starts the server job,
starts each client job, and then narrows its existing
`_pending_client_outcomes` set to clients that replied successfully.

Current call sites:

- `nvflare/private/fed/server/job_runner.py:295-360`

Before sending those start-job requests, the resource-statistics implementation
must separately freeze the selected clients and add the server participant.
It does not shrink this resource-report list when a start reply times out. A
selected client that never starts therefore remains visible as `missing`
instead of disappearing from coverage. It must not create the list from reports
that happen to arrive; that would hide missing reports.

The SP creates a random per-job HMAC key, then derives:

```text
participant_key = "sha256-" + HMAC-SHA-256(
    job_hmac_key, "participant\0" + role + "\0" + participant_id)

environment_key = "sha256-" + HMAC-SHA-256(
    job_hmac_key, "environment\0" + role + "\0" + participant_id +
                  "\0current-job-process")
```

The server overwrites a reserved `JobMetaKey.RESOURCE_STATS_CONTEXT` entry in
the job metadata before it starts either job process. Its current-code value is
a map from participant ID to the two derived keys.

The two local delivery paths are not identical today:

- `ClientExecutor.start_app()` already receives `job.meta`, preserves the
  deploy-time fields it treats as authoritative, and writes the result to the
  client's deployed `job_meta.json` before launcher selection
  (`nvflare/private/fed/client/client_executor.py:224-252`). Phase 1 adds the
  reserved entry to that already-written map.
- `ServerEngine._start_runner_process()` currently reads the deployed file and
  builds an updated in-memory `job_meta`, but does **not** write that copy back
  (`nvflare/private/fed/server/server_engine.py:236-254`). Phase 1 must add a
  narrow server-side update before `get_job_launcher()`: copy only the
  server-owned `RESOURCE_STATS_CONTEXT` into the deployed `job_meta.json`,
  preserve the deploy-time `BYOC` decision, and replace the file atomically.

The CJ/SJ recorder then reads its own entry from that existing file using its
platform-known site name. This changes a file in the existing run workspace;
it does not mutate persisted submitted-job metadata or introduce a new
launcher path.

The HMAC key itself never leaves the SP. The derived values are opaque
correlation keys, not secrets or authentication credentials. The reserved
metadata value is platform-owned: submitted job metadata cannot select or
override it. This path adds no launcher argument, environment variable,
allowlist entry, job option, or operator setting.

The SP retains the derived expected map in its per-job finalization state. It
still derives the sender identity from the authenticated connection and checks
that the report's key matches the expected key. Current code has one reporter
scope per job process; a future execution design may allocate more environment
keys without changing the report format.

### 2. A current job process opens one measurement period

The CJ has an appropriate platform call site immediately after its workspace
object is created and before NVFlare adds the job's custom directory to
`sys.path`:

- `nvflare/private/fed/app/client/worker_process.py:61-64`

The equivalent SJ call site is:

- `nvflare/private/fed/app/server/runner_process.py:68-71`

At that point the recorder does the following, in order:

1. It records `participant_start`, including the visible capacity of the
   filesystem that contains `Workspace.get_run_dir(job_id)`.
2. It generates a random 128-bit `attempt_id` inside NVFlare.
3. It begins one measurement period and records CPU, memory, and GPU capacity.

The ID is not passed through a launcher. The current implementation has one
period for the lifetime of this job process, so it does not need a launcher
change to correlate multiple periods.

The recorder samples start capacity first and records `opened_at` immediately
after that sample. At shutdown it takes the optional final capacity sample and
then records `closed_at`. Both serialized timestamps come from one wall-clock
anchor advanced with `time.monotonic_ns()`. A wall-clock adjustment during the
job therefore cannot create a negative or inflated period.

`Workspace.get_run_dir()` resolves the current job directory as
`<workspace>/<job_id>`:

- `nvflare/apis/workspace.py:232-235`

The best available current call site is before NVFlare explicitly enables
job custom imports. It cannot defend against Python code injected before
`worker_process.main()` through a pre-existing `PYTHONPATH`, `sitecustomize`,
or equivalent launcher environment. The report is therefore a platform-
collected self-report, not proof against a malicious local job. Fixing that
stronger threat model would require a separate launcher-hardening decision.
It must not be hidden by calling the current snapshot "trusted evidence."

This is a real current-code limitation, not a theoretical one. The process,
Docker, Kubernetes, and Slurm launchers can put job or site custom paths in
the child Python path before the module entry point runs:

- process: `nvflare/app_common/job_launcher/process_launcher.py:66-81`
- Docker: `nvflare/app_opt/job_launcher/docker_launcher.py:640-661`
- Kubernetes: `nvflare/app_opt/job_launcher/k8s_launcher.py:1098-1115`
- Slurm: `nvflare/app_opt/job_launcher/slurm/launcher.py:428-431,511-527`

### 3. The job runs

The CJ starts `ClientAppRunner` at
`nvflare/private/fed/app/client/worker_process.py:121-126`.
`ClientRunner` fires `START_RUN`, runs the workload, and fires
`ABOUT_TO_END_RUN` and `END_RUN` during its normal finalization:

- `nvflare/private/fed/client/client_runner.py:689-702`
- `nvflare/private/fed/client/client_runner.py:712-788`
- `nvflare/private/fed/client/client_runner.py:812-835`

The SJ follows the same broad pattern. It fires `START_RUN`, runs its
workflows, sends the existing fire-and-forget `END_RUN` request to clients,
and then fires its local `END_RUN`:

- `nvflare/private/fed/server/server_runner.py:185-237`

### 4. The job process closes the period and writes its report

The closest current finalization hook is `_archive_results()` in each job
process:

- CJ: `nvflare/private/fed/app/client/worker_process.py:131-146`
- SJ: `nvflare/private/fed/app/server/runner_process.py:132-149`

At a normal end, the recorder:

1. takes the optional final CPU, memory, and GPU observation;
2. closes the period with `released`, `failed`, or `terminated` as applicable;
3. takes the final workspace-filesystem capacity observation;
4. records the bounded saved-result byte total, when NVFlare knows such a set;
5. closes the job-scoped F3 counters; and
6. serializes one canonical `participant_summary`.

The staging path is:

```text
<workspace>/<job_id>/resource_stats/staging/participant_summary.json
```

It is created with a temporary file followed by `os.replace`. The serialized
bytes are frozen after that replacement. A retry never rebuilds the report.

The current shutdown helper closes command admission before it invokes
`_archive_results()`, but it waits for already-admitted command callbacks only
after streaming and the Cell have been stopped:

- `nvflare/private/fed/app/job_process_cleanup.py:24-66`

That order is not yet sufficient for an exact F3 cutoff. A callback admitted
before the gate could still finish while the counters are being frozen. The
production change must drain the admitted job callbacks before freezing F3,
or it must make the F3 counter's atomic freeze the authoritative cutoff and
classify later callback completions as late. This is an internal ordering
change, not a deployment setting.

### 5. The report returns to the parent through the current workspace path

For a launcher that shares the workspace with its parent, no transfer is
needed. For a launcher with a separate workspace, the current shutdown path
ZIPs the whole `<workspace>/<job_id>` directory and returns it before the job
process exits:

- archive construction: `nvflare/app_opt/job_launcher/workspace_cell_transfer.py:185-207`
- upload: `nvflare/app_opt/job_launcher/workspace_cell_transfer.py:689-767`
- shutdown wrapper: `nvflare/app_opt/job_launcher/workspace_cell_transfer.py:769-779`
- parent extraction: `nvflare/app_opt/job_launcher/workspace_cell_transfer.py:399-445`

This means the same staging path works with the current launchers. Process,
Docker, and Slurm expose the job directory through their existing workspace
or mount. Kubernetes uses the existing workspace-transfer path shown above.
The resource-statistics feature adds no launcher argument or transfer
protocol.

In today's client lifecycle, the CP does not call
`resource_manager.free_resources()` until after the job handle has ended and
the terminal request has been attempted
(`nvflare/private/fed/client/client_executor.py:622-682`). The single current
period therefore closes before that parent-side release. This observation is
about today's code, not a requirement for the future resource-management
design.

A hard process, pod, or node failure can bypass this `finally` path. In that
case a remote parent may never receive the staging file. The design reports
that participant as missing; it does not invent a zero or claim durability the
current launcher does not provide.

### 6. The client parent sends the report with the terminal outcome

The CP already waits for the job handle, reads its return code, sends a
terminal request to the root server, then frees allocated resources:

- `nvflare/private/fed/client/client_executor.py:622-688`

The request currently uses:

| Item | Current value |
| --- | --- |
| target | `FQCN.ROOT_SERVER` |
| channel | `CellChannel.SERVER_MAIN`, whose wire value is `task` |
| topic | `CellChannelTopic.REPORT_JOB_FAILURE`, whose wire value is `report_job_failure` |
| timeout | `job_query_timeout`, currently defaulting to 5 seconds |

The definitions are at `nvflare/private/defs.py:160-188`, and the timeout is
set at `nvflare/private/fed/client/client_executor.py:194-196`.

The topic name is historical and misleading: the current code sends this
request after every child exit, including return code zero. Reusing this
exchange is backward compatible and avoids a second completion race. A later
cleanup may rename the Python constant, but it does not need a new wire topic.

The extended request payload is:

```text
{
  "job_id": string,
  "code": integer,
  "reason": string or null,
  "resource_report": {                 # optional
    "sha256": 64 lowercase hex chars,
    "participant_summary": bytes       # canonical UTF-8 JSON, at most 64 MiB
  }
}
```

The digest is over the exact `participant_summary` bytes. The CP reads those
bytes only after the job handle has finished, so a separate-workspace launcher
has already completed its result upload. The CP computes the digest itself;
it does not trust a digest stored beside the child file.

If the staging file is absent, unreadable, or larger than 64 MiB, the CP still
sends the terminal outcome without `resource_report`. Resource reporting must
never change the job return code.

The Cell serializes the whole envelope before sending it. The current default
Cell payload limit is just under 2 GiB, but a deployment may already use a
smaller limit:

- `nvflare/fuel/f3/comm_config.py:18-22,82-83`
- `nvflare/fuel/f3/drivers/net_utils.py:39-42`

Before the first send, the CP checks the serialized envelope against the
Cell's effective limit. If it does not fit, the CP sends the terminal outcome
once without the report and logs that resource statistics were omitted. It
does not ask an operator to raise the limit, and it does not repeatedly send a
message that the Cell will reject.

`send_request_before_shutdown()` serializes the send with client logout, so
the existing token is still usable:

- `nvflare/private/fed/client/fed_client_base.py:423-443`

#### Retry rule

The CP makes at most three attempts. Each attempt uses the existing
`job_query_timeout`. It waits one second between attempts. It sends the same
frozen bytes and the same digest every time.

It retries only when there is no reply or the transport reports a timeout or
communication failure. It does not retry an explicit `accepted`, `duplicate`,
`invalid`, `conflict`, `too_late`, `not_provided`, or `server_error` report
status. Resource reporting is best effort. On the client, the network-wait
budget is three `job_query_timeout` intervals plus the two one-second gaps.
Reading, hashing, and serializing the local file happen before that budget, so
this is not a hard wall-clock bound on resource release.

On the server, the selected v1 handler validates and stores a candidate before
it resolves that participant's pending terminal outcome. That work is on the
existing outcome request's critical path. It can delay server finalization, but
it cannot change the job result and it adds no second reporting window. The
existing client-outcome deadline remains the normal waiting budget once the SJ
has ended, not a strict wall-clock bound: a callback already in a filesystem
commit can hold the shared acceptance lock past the nominal deadline. This
latency tradeoff is explicit; moving validation off that path would require a
separate in-flight-report and cutoff protocol.

These constants are internal defaults; they do not add a user setting.

The server reply uses an overall successful Cell return code once it has
processed the terminal outcome. Resource-report validation is reported
separately:

```text
{
  "resource_report": {
    "status": "accepted" | "duplicate" | "invalid" | "conflict" |
              "too_late" | "not_provided" | "server_error",
    "summary_sha256": string or absent
  }
}
```

An invalid resource report does not turn a successful job into a failed job.
Likewise, a failed job may still have a valid resource report.

### 7. The server parent authenticates and accepts the report

The current SP registers the terminal-outcome callback at
`nvflare/private/fed/server/fed_server.py:438-466` and handles it at
`nvflare/private/fed/server/fed_server.py:906-957`.

The CP's outgoing filter adds its client name, token, token signature, and
SSID:

- `nvflare/private/fed/client/communicator.py:107-131`
- `nvflare/fuel/sec/authn.py:68-92,114-150`

In secure mode, the SP verifies the signed token and binds it to the message's
CellNet origin before the callback runs:

- `nvflare/private/fed/server/fed_server.py:522-550,1226-1237`
- `nvflare/private/fed/authenticator.py:384-420`

The callback then maps the token to the registered client and checks that the
job expects that client. The payload's `participant_key` is never treated as
authentication.

The current callback drops a second terminal outcome when
`is_client_outcome_pending()` is false. The resource-report check must be
separate from that outcome check. An expected participant may retry the same
report while report acceptance is still open, even when its job outcome was
already resolved. This separation is what makes a lost acknowledgement
idempotent.

In a non-secure deployment, the existing terminal handler still requires a
token registered to a current client. The resource feature does not silently
upgrade the trust guarantees of a non-secure deployment.

The acceptance function performs these steps in this order:

1. Check the authenticated job and participant against the expected list.
2. Check that `participant_summary` is bytes and no larger than 64 MiB.
3. Compute SHA-256 and compare it with the envelope digest.
4. Decode strict UTF-8 JSON, reject duplicate object keys and non-finite JSON
   values, and run the schema and semantic validators.
5. Check the report's `job_id`, `participant_key`, and every current-adapter
   `environment_key` against the derived values in trusted server state.
6. Recompute the participant totals. Do not accept totals from the site.
7. Write the exact bytes to a unique temporary file in the server run
   directory and flush that file. Do not hold the acceptance lock during JSON
   parsing, semantic validation, or the temporary-file write.
8. Acquire the per-job acceptance lock and inspect the accepted digest for this
   participant. The same digest is `duplicate`, including after cutoff. If
   acceptance is closed, any other digest is `too_late`. While it is open, a
   different accepted digest is `conflict`. For an empty slot, atomically
   replace `resource_stats/participants/<participant_key>.json` with the
   temporary file, `fsync` the containing participant directory, and only then
   record its digest in the accepted ledger before releasing the lock. If the
   directory flush fails, do not add the ledger entry; attempt to remove the
   unaccepted canonical file and return `server_error`.
9. Return `accepted` only after the canonical participant file and ledger entry
   exist. If validation or storage fails, return `invalid` or `server_error`
   and do not mark the report accepted.

Every branch that does not install the candidate removes its unique temporary
file. Cleanup failure is logged but never makes that candidate part of the
accepted ledger.

In a `finally` path after these steps, the handler processes and resolves the
terminal job outcome regardless of the resource-report status. The overall
Cell return code is successful once that terminal outcome has been handled;
accounting validation or storage failure never changes the job return code.
The synchronous work can add latency to this existing request, as noted above;
it does not create a later report wait.

The validator entry point already models steps 2 through 4:

- `research/runtime_resource_proxy_prototype/schema/contract_v1.py:1295-1364`

The replay rule is:

- The first valid digest wins.
- The same digest is `duplicate` and succeeds without another contribution.
- A different digest after acceptance but before cutoff is `conflict`; it never
  overwrites the accepted bytes.
- An invalid candidate does not reserve the slot. A valid report may still be
  accepted before cutoff.
- After cutoff, a digest that was already accepted may still receive a
  `duplicate` acknowledgement, but no stored result changes. Any new digest is
  `too_late`.

The SP writes accepted bytes before acknowledging them so an acknowledgement
does not get ahead of the existing filesystem. This is not a claim of
immutability against an administrator or malicious code with the same OS
permissions. The finalizer re-reads and revalidates the stored bytes before it
builds the manifest.

The server's own report follows the same validation and storage function. It
does not send a fake network request. After the SJ has ended and its workspace
has been returned, the SP reads the SJ staging file and calls the acceptance
function with the expected local server identity.

## Cutoff, reduction, and archival

### Fixed report cutoff

When `_job_complete_process()` first observes that the SJ has exited, it makes
one parent-local acceptance attempt for the server staging report before it
starts or closes the client-outcome wait. A per-job flag makes this step
idempotent across completion-loop iterations. There is no loopback message.
After that attempt, the server participant is accepted, invalid, or missing
before the common cutoff closes.

Normal completion reuses the current client-outcome wait. The default wait is
900 seconds:

- `nvflare/private/fed/server/job_runner.py:109-111`
- `nvflare/private/fed/server/job_runner.py:441-481`

The wait starts after the SJ process has ended. It ends early when every
expected client terminal outcome has been resolved. The resource-report cutoff
is the instant that this wait closes. If a client terminal outcome arrives
without report bytes, that participant is resolved as missing; the server does
not add a second reporting wait.

Cutoff and acceptance use the same per-job lock. Under that lock, the
finalizer changes the acceptance state from `open` to `closed` and snapshots
the accepted ledger. It then releases the lock and reduces only that snapshot.
A callback may validate and prepare a temporary file before cutoff, but it is
included only if its final locked commit happens first. A callback that reaches
the lock after closure discards its temporary file and returns `too_late`.
Consequently no participant file can race into the manifest after the accepted
ledger has been frozen.

Abnormal server and abort paths skip the client-outcome wait to match the
current code. They still make the one server-local acceptance attempt described
above, then close acceptance without a client reporting window. Reports that
arrive after that cutoff cannot change the result:

- `nvflare/private/fed/server/job_runner.py:451-481`

The UTC `report_cutoff_at` is recorded once when acceptance closes. The code
must use a monotonic deadline for waiting and a wall-clock timestamp only for
the serialized record.

### Deterministic reduction

Before `_save_workspace()` runs, the SP performs one reduction:

1. Re-read each accepted participant file and check its digest and contract.
2. Make the participant directory match the frozen ledger exactly: remove and
   directory-flush any unaccepted file left by an interrupted or failed commit.
   If exact cleanup or verification fails, do not write the completion manifest
   or expose a resource bundle; the CLI will report statistics unavailable.
3. Classify every expected participant as `accepted`, `missing`, `invalid`, or
   `disabled`.
4. Derive each accepted participant's totals from its periods.
5. Sum only accepted numeric contributions into the job totals.
6. Remove the SJ staging file after it has been accepted or classified. It is
   not part of the final archive.
7. Write canonical `resource_stats/resource_summary.json` atomically.
8. Build a manifest that covers the summary and every accepted participant
   file.
9. Write `resource_stats/manifest.json` last. Its presence is the completion
   marker for the bundle.

The manifest does not include invalid candidate bytes. An invalid participant
entry keeps only the allowed generic issue and trusted receipt time.

The existing job-completion loop calls `_save_workspace()` before publishing
the terminal job status:

- `nvflare/private/fed/server/job_runner.py:493-538`

`_save_workspace()` collects the run, result, log, and audit roots and passes
them to the job manager:

- `nvflare/private/fed/server/job_runner.py:587-631`

`JobDefManager.save_workspace()` stores this archive as the existing
`WORKSPACE` component:

- `nvflare/apis/impl/job_def_manager.py:567-573`

The filesystem store writes a temporary ZIP and atomically replaces the
component. Directory contents are stored relative to each source directory:

- `nvflare/app_common/storages/filesystem_storage.py:33-90,229-249`

The resulting resource-statistics members inside `WORKSPACE` are exactly:

```text
resource_stats/resource_summary.json
resource_stats/manifest.json
resource_stats/participants/<participant_key>.json
```

There is no `RESOURCE_STATS` component. The job has one copy of each final
file, inside its normal archived workspace.

## CLI reads the existing `WORKSPACE` archive

The proposed commands remain:

```text
nvflare job resources JOB_ID
nvflare job resources JOB_ID --site SITE
nvflare job resources JOB_ID --format json
```

The CLI may run on a different machine from the server, so it cannot literally
open the server's filesystem path. "Read the workspace" means that an
authenticated server command opens the job's existing archived `WORKSPACE`
component and returns only the requested resource records.

The implementation adds one narrow job command, `get_job_resources`. It uses
the same job authorization as `get_job_meta`, `download_job`, and other job
commands:

- command registration pattern: `nvflare/private/fed/server/job_cmds.py:159-264`
- job authorization: `nvflare/private/fed/server/job_cmds.py:279-326`
- session command and error mapping: `nvflare/fuel/flare_api/flare_api.py:230-328`
- CLI session selection: `nvflare/tool/job/job_cli.py:1093-1096`

The handler does the following:

1. Require the job to have a terminal status. A running job returns the
   existing `JOB_RUNNING` result, which the API maps to `JobNotDone`.
2. Ask `JobDefManager.get_storage_for_download()` for the existing
   `WORKSPACE` file. The filesystem implementation creates a local symlink,
   so it does not load the whole archive into memory.
3. Open the ZIP and read only the fixed members under `resource_stats/`.
4. Reject duplicate member names, unsafe paths, symlinks, oversized
   uncompressed members, truncated reads, and missing manifest entries.
5. Validate the manifest and the digest of every record it will return. The
   default view need not decompress every participant report; it checks the
   manifest entry for `resource_summary.json`. A `--site` request also checks
   the selected participant entry.
6. Validate `resource_summary.json` against the v1 contract.
7. Check that the manifest path set exactly matches the accepted participant
   keys in the validated summary, without decompressing every participant
   file.
8. For `--site`, find the participant by `participant_id` in the validated
   summary, then use its validated `participant_key` to read the exact
   participant member. Its digest must match both the manifest and the
   participant entry. Never put raw CLI input into a ZIP path.
9. Return the validated data to the CLI, which produces either the human
   table or the JSON envelope.

The default and `--format json` responses contain one decoded
`resource_summary`. A `--site` response contains a small server-derived job
header, that site's trusted participant entry from the summary, and at most one
decoded `participant_summary`; it does not repeat the complete job summary.
After serialization, every response is checked against both a fixed 66 MiB
command-response cap and the Cell's effective payload limit. If it does not
fit, the command returns a resource-statistics error rather than a partial
record. The CLI does not receive an archive path and cannot request arbitrary
ZIP members.

Relevant existing APIs and patterns are:

- staged storage access:
  `nvflare/apis/impl/job_def_manager.py:575-593`
- filesystem download link:
  `nvflare/app_common/storages/filesystem_storage.py:377-392`
- current archived-log extraction pattern:
  `nvflare/private/fed/server/job_cmds.py:645-710`
- current full job download, including `workspace.zip`:
  `nvflare/private/fed/server/job_cmds.py:1683-1756`

The exact record limits are 4 MiB for the manifest and 64 MiB each for a
participant or resource summary. The handler checks `ZipInfo.file_size` before
reading and also enforces a bounded streaming read. It does not extract the ZIP
to a general directory.

Expected CLI outcomes are:

| Condition | Result |
| --- | --- |
| Job is still running | `JobNotDone` |
| Job does not exist or caller is not authorized | Existing job-command behavior |
| Terminal job has no resource bundle | Resource statistics unavailable |
| Manifest, digest, ZIP, or record is invalid | Resource statistics invalid; do not display unverified totals |
| Valid summary, no `--site` | Show the all-participant rollup |
| Valid `--site` for an accepted participant | Also show that participant's observations and hardware models |
| Requested participant is missing, invalid, or disabled | Show its status; no detailed report exists |

Downloading the full job already makes the workspace available locally, but
making that a prerequisite for `job resources` would transfer the job
definition, logs, and all results unnecessarily. The narrow command still
reads the existing workspace and creates no duplicate stored object.

## F3 network semantics and the current hook gap

Phase 1 uses sender-only counters. A receiver does not add the same payload to
the primary total.

### Current route and binding table

The low-level route alone is not the authority. Platform code assigns the job
and class at the call site below; job payloads and caller-supplied headers
cannot opt traffic in or out.

| Phase 1 class | Current route | Platform binding and rule |
| --- | --- | --- |
| `task_request` | `server_command/get_task` from `Communicator.pull_task()` (`client/communicator.py:373-410`) | The communicator has the trusted FLContext job ID. Hold the accepted request's byte count by request ID. Commit it only when the matching reply contains a real task; discard it for `__try_again__`, `__end_run__`, timeout, or error. This excludes polling without pretending the request route alone proves work. |
| `task_response` | Reply to `server_command/get_task` | In `ServerCommandAgent`, after `GetTaskCommand.process()` returns and before reply encoding (`server_command_agent.py:65-110`), tag only a platform-produced reply whose `TASK_NAME` is neither `__try_again__` nor `__end_run__`. The SJ supplies the trusted job ID. |
| `task_result` | `server_command/submit_update` from `Communicator.submit_update()` (`client/communicator.py:468-530`) | The communicator has the trusted FLContext job ID and assigns the fixed class. The server reply is an ACK and is excluded. |
| `job_application` | Inner admin topic `train.deploy`, sent over outer `admin/admin` (`server/job_runner.py:137-147,243-248`) | `_make_deploy_message()` assigns the job ID and class before encoding. The shared outer `admin/admin` route is never sufficient; deploy replies are excluded. |
| `job_stream_data` | DownloadService transaction followed by `sm__STREAM/sm__DATA` chunks | When an included parent payload creates its `ObjectDownloader`, register trusted `{job_id, class}` provenance for that transaction. Workspace-transfer callers register an exclusion. The chunk sender uses that registry, counts `CHUNK` and `FINAL` data once per destination and logical sequence, and does not count reliable retransmissions. |

Relevant response constants are `__try_again__` and `__end_run__` in
`private/defs.py:26-30`. DownloadService's shared route is
`download_service__/download_service__download`
(`fuel/f3/streaming/download_service.py:47-49`); it cannot distinguish tensors
from workspace files without the transaction registry.

The correlation above adds only internal observer state. It adds no wire
option, job setting, or operator configuration.

### Exact exclusions

The classifier defaults to excluded. Its explicit exclusions are:

- empty `get_task` polls and `__end_run__` replies, including their paired
  requests;
- replies to `submit_update` and `train.deploy`;
- stream `sm__ACK` and `sm__ERROR`, plus `ACK`, `RESUME`, `RESUME_ACK`, and
  `ERROR` data types;
- DownloadService confirm/cancel traffic;
- the `cellnet.channel/bulk` envelope, because its logical children are
  classified separately;
- `workspace_transfer/prepare_download` and
  `workspace_transfer/publish_results`, including their stream transactions;
- the terminal resource report on `task/report_job_failure` and its reply;
- registration, challenge, heartbeat, quit, shutdown, and job-heartbeat
  traffic;
- metrics/logging, federated-event, and HCI traffic; and
- every unrecognized channel/topic or unbound download transaction.

Default exclusion is important: `admin/admin`, DownloadService, and streaming
routes all carry both included and excluded traffic.

The exact rules are:

- Count `task_request`, `task_response`, `task_result`, `job_application`, and
  `job_stream_data`.
- Exclude `job_stream_control`, `bulk_envelope`, `workspace_transfer`,
  `platform_control`, `log_export`, unknown classes, and resource-report
  publication.
- Measure `len(message.payload)` after payload encoding and optional
  end-to-end encryption. Do not include Cell headers, driver or TLS framing,
  transport compression, or retransmissions.
- For a remote destination, increment `remote_accepted` only after
  `Communicator.send()` returns successfully. This means accepted by the local
  transport, not confirmed delivery by the receiver.
- Put a direct in-process delivery in `local_delivered`, not
  `remote_accepted`.
- Put a remote send that fails before acceptance in
  `remote_failed_before_acceptance`.
- Count fan-out once per destination. A participant that forwards a message
  counts its own sending hop.
- Freeze all three counters atomically before serializing
  `participant_final`. Later completions do not change the report.

`CoreCell._send_to_endpoint()` already exposes the useful low-level boundary:
it encodes and encrypts the payload, distinguishes direct delivery from
`communicator.send()`, and records its generic sent-size pool after a
successful call:

- `nvflare/fuel/f3/cellnet/core_cell.py:1326-1358`
- per-destination setup:
  `nvflare/fuel/f3/cellnet/core_cell.py:1365-1407`

That generic pool is not enough for Phase 1. It uses floating-point MiB,
includes protocol traffic, has no reliable job traffic class, does not keep
direct delivery separate, and does not provide the required failed-send or
atomic-cutoff record. `JobStatsReporter` currently reads those broad process-
level pools:

- `nvflare/app_common/widgets/job_stats_reporter.py:1380-1424`

Production therefore needs a platform-owned observer in the F3 send path. The
observer receives a platform-assigned job ID, class, and optional correlation
token. The report sender uses the explicit exclusion above, so the report
cannot count itself.

Four implementation details still need proof:

1. Pair an accepted `get_task` request with its reply before committing or
   discarding the pending request bytes.
2. Carry trusted provenance from an included large object into its
   DownloadService/stream transaction while marking workspace transfer
   excluded.
3. Re-establish trusted class provenance at an intermediate forwarder without
   accepting a job-supplied opt-in header.
4. Deduplicate reliable stream retries by logical stream ID, sequence, and
   destination.

Until the relevant path is implemented and tested, its F3 fact is
`unavailable/not_bound` or `partial/counter_gap`. The implementation must not
substitute the current generic sent/received totals.

## Why the other delivery mechanisms are not the default

| Mechanism | Useful property | Why it is not the final-report path |
| --- | --- | --- |
| Extend the current CP-to-SP terminal outcome | Uses an authenticated parent connection after the job process ends; covers success and failure; server already waits for it. | Recommended for current code. The old topic name is confusing, and synchronous validation/workspace commit adds latency to this request, but it avoids a second delivery and cutoff protocol. |
| Add a separate CP-to-SP CellNet topic | Clearer name and independent acknowledgement. | Adds another completion message and race without improving the trust or lifecycle boundary. |
| CJ-to-SJ Aux request | Job-scoped request/reply API already exists. | The job cells are tearing down, sends use the run abort signal, and a crashed CJ cannot send. `AuxRunner` behavior is at `nvflare/private/aux_runner.py:297-423`. |
| Federated event | Convenient application event interface and receiver-side duplicate IDs. | Outgoing delivery is fire-and-forget Aux traffic and shutdown is best effort. See `nvflare/widgets/fed_event.py:32-39,82-147,163-243`. An event can trigger local collection, but it is not the durable delivery acknowledgement. |
| Attach the report to task or model-result metadata | Reuses an existing result message. | Some jobs have no final task result, results may be retried or filtered, and the server rejects late submissions after workflow teardown. Current `JobStatsReporter` attaches per-task telemetry before result filters at `nvflare/app_common/widgets/job_stats_reporter.py:901-934`; server submission admission closes at `nvflare/private/fed/server/server_runner.py:460-470`. |
| Server pulls from each CJ at the end | Server controls timing and gets a reply. | It requires every job cell to remain alive, blocks server teardown, and couples the design to today's process topology. |
| Workspace only, with no CP-to-SP message | No report message. | The server's normal workspace archive contains the server workspace, not every client's local workspace. The SP would not know that a client report is ready or authentic. |
| Separate `RESOURCE_STATS` job-store component | Small direct query object. | It duplicates the summary already in `WORKSPACE` and creates a consistency problem. The narrow archive reader provides the same query without a second stored copy. |

## Failure and crash behavior

Resource statistics never change the job's success, failure, or abort result.

| Event | Resource-statistics result |
| --- | --- |
| One CPU, memory, GPU, storage, retained-content, or F3 probe fails | Encode the applicable `unavailable`, `error`, or `partial` typed value. Continue the job. |
| Normal Python exception reaches the CJ/SJ `finally` block | Close the period as failed, write the report if possible, and use the normal workspace return. |
| Final capacity check is missing | Keep the valid start-based contribution and mark that resource total partial. |
| Process never reaches recorder start | No site report. The expected participant becomes missing. |
| SIGKILL, pod loss, node loss, or another failure bypasses `finally` | A remote parent may receive no final staging file. The participant becomes missing. A leftover local fragment is not called a complete report. |
| Workspace result upload fails | Parent sends the terminal outcome without a report; participant becomes missing unless a valid report was already accepted. |
| CP-to-SP request or reply is lost | CP retries the same bytes up to the fixed limit. An acknowledgement loss becomes an idempotent duplicate. |
| Report is malformed or its digest is wrong | Record an invalid candidate. Do not use its values. A later valid candidate may still win before cutoff. |
| A second valid but different digest arrives | Keep the first valid report and return `conflict`. |
| Client report arrives after a normal cutoff | Return `too_late`; do not rewrite the summary. |
| SJ fails or the job is aborted | Make the one server-local acceptance attempt, skip the client-outcome wait, and close acceptance. Late client reports do not change the result. |
| SP stops after accepting a report but before finalization | Reload the acceptance ledger from the existing participant files when job recovery resumes. If the underlying workspace did not survive, report the loss; do not reconstruct accepted values from memory. |
| Workspace archival fails | Current code retries for up to 60 seconds and may publish terminal status without archived artifacts. In that case `job resources` reports unavailable. See `nvflare/private/fed/server/job_runner.py:501-524`. |
| Archived ZIP, manifest, or digest is corrupt | CLI reports invalid data and prints no totals from it. |

Site-side staging files are self-reports. They are not immutable evidence. An
accepted report becomes part of the server's normal job archive only after the
SP has validated it and the existing workspace save succeeds.

## Future-neutral recorder API

The schema already allows several measurement periods. The production API
should expose period boundaries without mentioning a process, GPU lease,
worker, or scheduler:

```python
participant = recorder.begin_participant(job_id, participant_key, workspace)
period = participant.begin_period(environment_scope)

# Current code runs the job here.

participant.end_period(period, reason="released", take_final_observation=True)
report_bytes = participant.finish(retained_content_source)
```

The API rules are:

- `begin_participant()` is called once for one site's job participation.
- `begin_period()` generates its own `attempt_id` and probes the current
  environment. It returns an opaque handle.
- `end_period()` is idempotent for that handle. It records one end time and an
  optional final observation.
- `finish()` ends any still-open period conservatively, closes participant
  facts and F3 counters, and freezes canonical report bytes. An implicitly
  closed period uses `terminated` and has no final stability observation.
- Job code cannot supply resource values, identity, status, traffic class, or
  timestamps to these methods.
- Probe failure is data, not an exception that fails the job.

Today, the adapter makes exactly one `begin_period()` call near the start of
`worker_process.main()` or `runner_process.main()` and one `end_period()` call
at job-process finalization. A future resource-management implementation may
call the same API several times around whatever boundaries it chooses. The
record schema, reduction rules, archived layout, and CLI do not depend on the
future process owner. The CP terminal-outcome transport is the concrete adapter
for today's code; it remains usable only while an equivalent parent terminal
path exists. If the roadmap removes that boundary, the delivery adapter and
assembly owner must change, while the report and stored formats stay the same.

The `environment_scope` is a platform-owned opaque value. For the current
single-period adapter it identifies that one site job-process scope. A future
multi-process or multi-node implementation must define scopes that prevent
overlapping ranks from reporting the same visible environment twice.

## Production change map

This is the expected implementation surface. It is not a request for new
deployment files or configuration.

| Current file or area | Phase 1 change |
| --- | --- |
| `nvflare/apis/fl_constant.py` | Add the reserved resource-context job-meta key and `GET_JOB_RESOURCES` admin command name. |
| `nvflare/private/fed/server/job_runner.py` | Freeze expected participants and derived keys before start, accept the local server report, apply the existing outcome cutoff, reduce the job result, write the manifest last, then call the unchanged workspace save. |
| `nvflare/private/fed/server/server_engine.py` | Before server launcher selection, atomically add only the platform-owned resource context to deployed `job_meta.json` while preserving the deploy-time BYOC decision. |
| `nvflare/private/fed/app/client/worker_process.py` and `.../server/runner_process.py` | Call the collector at the exact start hook and in `_archive_results()`; write the frozen candidate report in the existing run workspace. |
| New or nearby platform resource-statistics module | Own probes, one-clock timestamping, canonical fragment/report assembly, semantic validation, exact arithmetic, atomic writes, and the future-neutral recorder API. |
| `nvflare/private/fed/client/client_executor.py` | After `job_handle.wait()`, read/bound/hash the candidate and extend the existing terminal request; keep terminal outcome delivery when no report exists. |
| `nvflare/private/defs.py` | Add fixed request/reply key and resource-report status constants. No launcher or user-facing option is added. |
| `nvflare/private/fed/server/fed_server.py` | Extend `process_job_failure()` with authenticated participant binding and the acceptance state machine; resolve the terminal outcome in `finally` regardless of report status. |
| F3 platform call sites and `fuel/f3/cellnet/core_cell.py` | Assign trusted job/class/correlation state at platform call sites, then measure accepted bytes at `_send_to_endpoint()` and keep direct/failure buckets separate. |
| `nvflare/private/fed/server/job_cmds.py` | Add the authorized job-resources handler and safe fixed-member workspace reader. Reuse `get_storage_for_download()`; add no job-store component. |
| `nvflare/fuel/flare_api/flare_api.py` and `nvflare/tool/job/job_cli.py` | Add `Session.get_job_resources()` and the three proposed CLI forms, with existing job-command error mapping. |
| `JobDefManager` and storage implementations | No new save/get resource API. Reuse the existing `WORKSPACE` save and staged-download interfaces. |

## Remaining implementation gaps

| Gap | Decision or proof still needed | Safe behavior until resolved |
| --- | --- | --- |
| Pre-`main()` Python injection | Decide whether the supported launchers can sanitize platform startup without new user setup. | Describe current observations as self-reported; never claim tamper-proof evidence. |
| Root-parent restart recovery | Prove how the derived expected-participant map, accepted digests, and cutoff state reload from the existing run workspace. | If state cannot be recovered, make the resource summary unavailable; never infer it from logs or unauthenticated files. |
| F3 ownership and class mapping | Add the platform-only job/class mapping and prove how CP/CJ and SP/SJ counters combine without gaps or duplicates. | Report F3 unavailable or partial; do not reuse generic process totals. |
| F3 callback ordering | Choose callback drain before freeze or prove that atomic freeze correctly classifies every later completion. | Mark a known gap as `partial/counter_gap`. |
| Saved-result set | Identify the existing NVFlare-owned bounded result set for each supported workflow. | Use `unavailable/not_bound`; do not scan arbitrary files. |
| Crash recovery | Add tests that reload accepted report files and the cutoff state after an SP restart. | Never acknowledge before the participant file is stored; report unrecoverable loss honestly. |
| Mixed-version behavior | Confirm new SP/old CP and old SP/new CP behavior and the exact response payload version. | Omitted report means missing; unknown added request fields must not affect the terminal outcome. |
| Initial platform support | Select and test the ordinary-user OS, cgroup, CUDA-runtime, Docker, Kubernetes, and Slurm matrix. | Unsupported probes use the canonical unavailable status. |
| Archive reader hardening | Implement bounded ZIP reads, duplicate-name rejection, manifest verification, and authorization tests. | Do not fall back to unverified direct ZIP extraction in the CLI. |

The transport, cutoff, reduction order, archive location, and CLI storage
source are no longer open in this proposal. The remaining items are bounded
implementation details or support-matrix decisions.
