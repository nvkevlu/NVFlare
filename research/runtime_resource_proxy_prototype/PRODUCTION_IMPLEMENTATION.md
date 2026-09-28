# Job resource statistics: implemented path

Status: authoritative description of the code in this branch.

This document describes what the implementation does now. The broader design
documents contain additional target behavior; when they disagree with this
file, this file and the production reference artifacts are the current truth.

The implementation needs no new privilege, mount, service, launcher argument,
environment variable, job setting, or operator setting. It uses the job
processes, authenticated client session, server run directory, normal
`WORKSPACE` archive, and job-store authorization that NVFlare already has.

## End-to-end path

```text
client job process                         client parent
------------------                         -------------
start platform worker with Python -I
create Workspace
create JobResourceCollector
read initial job-process CPU accounting
start child F3 counter
  before workspace download/custom activation
download workspace; enable custom imports
run application
close command admission; pre-drain callbacks with transport alive
close/drain/freeze child F3; read final CPU accounting and finish collector in _archive_results()
write private terminal_handoff.json  --->  wait for child exit
                                             close/freeze parent F3 immediately
                                             read + validate fixed handoff
                                             checked-merge child + parent F3
                                             bind trusted client name
                                             build participant_summary bytes
                                             delete private handoff
                                             send once with terminal outcome
                                                        |
                              authenticated CellNet request: task/report_job_failure
                                                        |
                                                        v
server job process                         root server parent
------------------                         ------------------
same collector and private handoff  --->  bind trusted name "server"
                                            accept locally through same coordinator
                                            authenticate client sender names
                                            validate and hold bounded reports in memory
                                            close at existing completion cutoff
                                            derive resource_summary
                                            write + fsync participant files
                                            write resource_summary last locally
                                            archive normal WORKSPACE
                                                        |
                                                        v
                                       job CLI: read one WORKSPACE
                                     study CLI: read retained WORKSPACEs
```

There is one public report per participant. There is no public start record,
end record, attempt ID, environment key, or participant identity hash.
`participant_summary`, its completion-message envelope, and the archived
`resource_summary` contain `job_id` but not `job_name`. The authorized CLI
resolves a display label from existing persisted job metadata when requested;
a participant cannot claim or replace it. Reusing this metadata introduces no
new privilege, configuration, transport field, or resource-probe privacy
category. This is a pre-release v1 correction rather than a schema-version
bump.

## 1. Collection inside each job process

The client hook is in
`nvflare/private/fed/app/client/worker_process.py::main()`. The server hook is
in `nvflare/private/fed/app/server/runner_process.py::main()`. Both create
`JobResourceCollector` after `Workspace` is available, but before workspace
download and before `activate_job_python_path()` enables app or site custom
imports.

The official Process, Docker, Kubernetes, and Slurm launch paths start the
NVFlare worker through the fixed platform bootstrap in Python isolated mode
(`-I`). The Process launcher invokes the absolute platform-owned
`job_process_bootstrap.py` file with a fixed `client` or `server` selector;
that bootstrap adds only its own NVFlare package root and then runs the
corresponding fixed worker module. This keeps source, editable, and user-site
installations working without trusting `PYTHONPATH`. Docker, Kubernetes, and
Slurm invoke the installed bootstrap module with `-I -u -m` and the same
fixed selector. Their historical executable-module value is only an exact
allowlisted input for choosing one of those two selectors; it is never copied
into the command, and any other value fails before launch.

The launcher-owned environment also keeps app and site custom directories out
of the effective startup path. The Process launcher removes the known custom
paths from its copied `PYTHONPATH`; container and Slurm environments may
preserve dependency paths, but isolated mode ignores the entire `PYTHONPATH`
during worker startup in all four cases. After the initial resource snapshot
and workspace download, the worker adds the preserved dependency paths plus
app and site custom paths to `sys.path` and the environment for normal job
execution. This ordering is automatic and needs no user setting, extra
privilege, launcher argument, or deployment change.

This is a stronger and more concrete startup boundary than merely placing the
collector near the top of `main()`. It is still not hardware attestation. A
bring-your-own-container entrypoint can run before the launcher-supplied Python
command, and a `sitecustomize` installed in the interpreter's global site
packages can still run under `-I`. Job code also shares the process after the
snapshot and can affect later evidence or the private handoff.

`nvflare/private/fed/resource_stats/collector.py` implements the collector:

- `probe_cpu()` selects process-visible CPU capacity from Linux affinity,
  effective cpuset, finite cgroup quota, and online logical CPUs. It retains a
  bounded model and architecture only when the evidence is usable.
- `probe_memory()` selects the smaller applicable physical-memory and finite
  cgroup limit.
- If an applicable cgroup CPU or memory constraint exists but is unreadable or
  malformed, that entire dimension is unavailable. The probe does not fall
  back to a wider affinity, online-CPU, or physical-memory value that might
  overstate capacity.
- `probe_gpu()` accepts a numeric count only after CUDA Runtime enumeration.
  `CUDA_VISIBLE_DEVICES` by itself is not numeric evidence. NVML only enriches
  CUDA-validated devices with model, memory, and full-GPU/MIG classification.
- The collector freezes its absolute Python distribution roots when the
  trusted module is imported, before app/site custom-path activation. If the
  normal loader path cannot both load and enumerate a CUDA Runtime, it searches
  installed distribution metadata under only those roots for an owned runtime
  from an allowlisted `nvidia-cuda-runtime` or
  `nvidia-cuda-runtime-cuNN` distribution. One contained regular target is
  loaded by absolute path with `RTLD_LOCAL | RTLD_NOW` on POSIX. Contained
  aliases and hard links are deduplicated; distinct candidates fail closed.
- `ResourceTimeAccumulator` multiplies each observed capacity by elapsed time.
  `JobResourceCollector.observe_capacity_change()` is an available internal
  seam, but the current launch paths do not call it after startup.
- `observe_workspace_filesystem()` calls `os.statvfs()` only on the current job
  run directory. The recorded value is visible filesystem capacity at that
  instant, not job storage use or an allocation.

Production does not spawn `taskset`, `lscpu`, `nvidia-smi`, `df`, or another
shell command. It uses these exact ordinary-process interfaces:

| Value | Production sources |
| --- | --- |
| CPU units | `os.sched_getaffinity(0)`; cgroup paths resolved from `/proc/self/cgroup` and `/proc/self/mountinfo`; v2 ancestor `cpuset.cpus.effective` and `cpu.max`; v1 ancestor `cpuset.effective_cpus`/`cpuset.cpus` and `cpu.cfs_quota_us`/`cpu.cfs_period_us`; `SC_NPROCESSORS_ONLN` only when no narrower source is usable |
| CPU model | affinity-visible entries in `/proc/cpuinfo`; architecture from `platform.machine()` |
| Memory bytes | `SC_PAGE_SIZE * SC_PHYS_PAGES`; v2 ancestor `memory.max`; or v1 ancestor `memory.limit_in_bytes`; choose the smallest finite positive value |
| GPU groups | Normal CUDA Runtime loader lookup, with a fallback to one unique contained runtime owned by an allowlisted NVIDIA runtime distribution under import-time frozen Python roots; absolute `ctypes` loading with `RTLD_LOCAL | RTLD_NOW` on POSIX; CUDA Runtime `cudaGetDeviceCount`; CUDA Driver `cuDeviceGetUuid_v2`; then NVML UUID lookup, MIG classification, name, and total memory for those CUDA-validated devices |
| Workspace filesystem | `os.statvfs(run_dir)`, reported as `f_blocks * f_frsize` |

The measured interval begins at this hook, immediately before NVFlare enables
the job custom directory and starts the application runner. It ends in
`_archive_results()` after the runner returns and before workspace upload and
the remaining process shutdown. In the current ordering, the final reading is
taken after the command-callback pre-drain and child F3 drain, so their actual
elapsed cleanup tails are included. Those two condition waits return
immediately in the normal empty case, but can add up to five seconds each in a
pathological case. The optional post-stop callback wait happens after the
handoff and is not included. This is the implemented measurement window, not
the operating-system process's entire lifetime or active-task utilization.

Job-process cleanup first rejects new application commands and waits up to five
seconds for already admitted command callbacks while Cell and streaming remain
alive. A timeout or error marks the child counter `partial/counter_gap`. At
`_archive_results()`, both job entry points then close new F3 admissions, wait
up to the fixed five-second internal bound for admitted logical sends, freeze
the child snapshot, and pass it to `JobResourceCollector.finish()`. They call
`write_terminal_handoff()` before streaming and Cell stop. If the callback
pre-drain failed, cleanup also retains one bounded post-stop callback wait
before closing security state. The handoff is atomically written at:

```text
<run_dir>/resource_stats/staging/terminal_handoff.json
```

The child waits use condition variables and return immediately when no callback
or F3 admission is pending; five seconds is only the maximum for each. They run
at job finalization, not in the steady-state send path. Parent F3 finalization
does not wait: CP originates no included class, SP's blocking deployment sends
have already returned, and a parent admission still pending is immediately
marked as a counter gap. It therefore cannot stall the server's serial
completion loop or another job's terminal publication.

It is a private, identity-free transfer record with these exact members:

```text
internal_version
kind
resource_time
cpu_consumed
workspace_filesystem
retained_content
child_f3
```

It is bounded to 1 MiB. The parent opens only this fixed path, does not follow
symlinks, requires a regular file, rejects duplicate JSON keys and invalid
schema values, and deletes the staging file after assembly. It is not included
in the final resource namespace.

### What is measured now

CPU, memory, CUDA-authorized GPU resource time, CPU consumed, the final
workspace-filesystem capacity observation, retained content, and
`message_traffic` are
implemented.

`cpu_consumed` is a separate typed user plus system CPU-seconds total. On
Linux and macOS, `RUSAGE_SELF` and `RUSAGE_CHILDREN` are read once just after
the start clock and once just before the final clock. The adjacent reads are
not simultaneous. Own-process
CPU and exited, waited-for descendant CPU are added from disjoint counter
deltas. A short-lived child launched and waited for between boundaries is
included without periodic sampling. The shared client or server site parent
is excluded because its CPU is shared among jobs. An unawaited or still-running
child cannot be read through `RUSAGE_CHILDREN`; known missing work leaves
the value partial or unavailable. Current PyTorch `MultiProcessExecutor`
ranks are not waited for, the XGBoost v2 partial-HE process pool cannot be
verified as fully reaped, and a restored server worker cannot recover the
prior process's CPU, so those paths cannot claim complete consumption. This
metric is a practical billing proxy for covered execution, not an
independently verified invoice ledger.
`JobExecutor` marks a client relaunch's new CPU subtotal
`partial/observation_incomplete` when it finds the per-job attempt marker,
has seen that job ID before, or the scheduler attempt count is greater than
one. The exclusive, synced marker is created in the site workspace root
before launch, outside the redeployed run directory and archive; it survives
a normal site-parent restart even if the attempt count is unchanged. Marker
persistence failure leaves the current CPU subtotal partial and does not
block launch. An attempt whose marker never persisted before a later crash
cannot be reconstructed, so billing use still needs a storage-reliability or
policy decision for that exceptional case.

In v1, `retained_content` is a terminal best-effort scan of the participant's
run directory. It sums logical `st_size` for regular files and excludes the
top-level `resource_stats/` subtree. Symlinks and other non-regular entries are
ignored, hard links count once per path, and sparse files count their logical
rather than allocated size. A clean empty scan reports zero. The contract
requires a useful subtotal after a scan error to be
`partial/observation_incomplete`, otherwise unavailable.

This is not a curated result inventory. It includes application,
configuration, input, log, temporary, and output files found in the run
directory. The traversal is non-atomic and runs before the private handoff is
written, stats-pool files are created, an optional workspace upload begins, and
later cleanup/log growth. It is a participant self-report; the parent validates
the typed value but does not attest or remeasure the files. Separately
configured result, log, and audit roots are not covered today.

Job and study totals add participant observations. They are not unique retained
storage, the normal `WORKSPACE` archive size, allocated disk usage, or billable
storage. The remaining bounds/error-handling and root-coverage work is tracked
in [Remaining implementation gaps](GAPS.md#2-retained-result-bytes).

Public `message_traffic.sent_to` has one sender-confirmed counter pair per
named remote recipient. It includes only job application
deployment, a response containing a real task, and a submitted task result.
Task requests, acknowledgements, final delivery to an in-process logical
destination, failures before acceptance, an extra relay contribution,
workspace transfer, and the terminal report are excluded. A remote logical
destination routed through a local first-hop relay still counts once at its
origin. Recipient names come from trusted participant identity, not the
first-hop relay. No participant scalar `sent` or measured `received` field is
stored. The CLI derives outgoing and “sent to site” amounts on demand; the
latter is addressed, sender-accepted traffic, not confirmed receipt or an
exact-delivery guarantee.

One message is one top-level logical operation per remote destination. The main
payload is measured after FOBS encoding and before optional encryption. When
FOBS creates a `DownloadService` transaction, successfully accepted unique
source bytes are folded into that same operation without another message or
retry duplication. Classification and accounting context remain process-local
at the trusted semantic origin; they are never accepted from a wire header.
For a blob stream, the admission remains pending until its whole
`StreamFuture` succeeds. An asynchronous stream error or cancellation abandons
the operation, while individual frames and retries cannot add counters.

For a Slurm launch with more than one node, the current rank-zero observation
cannot cover every node. The collector therefore discards the rank-zero
numeric resource-time totals and emits exactly:

```json
{"issues":["unsupported"],"status":"unavailable"}
```

A platform-owned multi-node collector is still needed before multi-node Slurm
resource time can be reported.

### Why the private clock uses nanoseconds

`ResourceTimeAccumulator` reads `time.monotonic_ns()` so elapsed time is not
affected by a wall-clock adjustment and does not first pass through binary
floating point. The large absolute integer is private and short-lived. The
collector subtracts the two clock readings first, converts only the elapsed
delta to exact decimal seconds, and serializes seconds with at most nine
fractional digits.

```text
elapsed_seconds      = (current_monotonic_ns - previous_monotonic_ns) / 1e9
CPU unit-seconds     += visible_CPU_units * elapsed_seconds
CPU consumed seconds = Δ(RUSAGE_SELF user+system) + Δ(RUSAGE_CHILDREN user+system)
memory byte-seconds += visible_memory_bytes * elapsed_seconds
GPU instance-seconds += visible_GPU_instances * elapsed_seconds
```

Each interval product is rounded only when it exceeds nine fractional digits,
using round-half-even, before exact decimal addition.
CPU consumed uses only start/end counter differences. It is not derived from
the capacity-time product and does not provide average CPU utilization.

For example, private readings near `8000000000000000000` can produce the
public value:

```json
"measured_seconds":"2223.5"
```

No absolute nanosecond timestamp enters a report or CLI output. The `_ns`
interface is a unit and arithmetic choice; it does not claim the host clock is
accurate to one nanosecond.

## 2. Parent assembly and one client send

After the child handle completes, the surrounding client-executor path and
`nvflare/private/fed/client/client_executor.py::_build_participant_resource_report()`:

1. closes new parent F3 admissions and freezes immediately; a pending parent
   operation is an instrumentation gap because all current parent-originated
   included traffic must already have settled;
2. reads the fixed handoff through `read_terminal_handoff()`;
3. checked-merges the child and parent F3 snapshots;
4. calls `assemble_participant_summary()` with the parent's existing
   `client.client_name`;
5. validates the report and serializes it with the production deterministic,
   readable JSON encoder; and
6. removes the private handoff in a `finally` block.

If the handoff is absent or invalid, the parent still builds a report, with
child-derived values marked unavailable and any usable parent F3 subtotal
marked partial. A child drain gap or unexpected pending parent admission
likewise preserves bounded values as partial.
CPU-consumption failure is independent of the capacity-time, memory, GPU, and
retained-content statuses.
Resource-report failures are logged but do not change the job outcome or
prevent resource release. The parent freezes before it serializes the terminal
report, so that report cannot count itself.

After consuming and deleting the handoff, the client parent frees the
launcher's allocated compute resources. Only then does it wait for the
completion request's CellNet reply. A slow or unavailable root server therefore
does not keep the completed client's GPU, CPU, or memory allocation held.

The parent then makes exactly one application-level call to
`send_request_before_shutdown()`:

| Property | Implemented value |
| --- | --- |
| target | `FQCN.ROOT_SERVER` |
| channel | `CellChannel.SERVER_MAIN` (`task`) |
| topic | `CellChannelTopic.REPORT_JOB_FAILURE` (`report_job_failure`) |
| timeout | existing `job_query_timeout` |
| report field | `resource_report.participant_summary` as exact bytes, at most 1 MiB |
| reply field | flat `resource_report_status` |

The request already carries `job_id`, terminal `code`, and `reason`. The
resource report is optional, so failure to build it cannot suppress the
terminal outcome.

There is no new application-level retry loop and no persisted receipt
tombstone in this implementation. The coordinator is idempotent while its
in-memory job state exists, but the current client performs one send. A lost
request can therefore leave the participant missing. If only the reply is
lost, the server may already have accepted the report, but the client does not
retry or learn that status.

The implemented transport is Option A: extend the existing historical
`REPORT_JOB_FAILURE` exchange. A new versioned `REPORT_JOB_COMPLETION` remains
a design fallback; it is not registered or sent by this branch.

## 3. Authenticated server acceptance

`nvflare/private/fed/server/fed_server.py::process_job_failure()` handles the
request. It uses the existing client token to obtain the registered client
name. It does not trust the name in the JSON as authentication.

Before resolving that client's pending terminal outcome, the handler calls
`JobRunner.accept_client_resource_report()`, which delegates to
`ResourceStatsCoordinator.accept_resource_report()` in
`nvflare/private/fed/resource_stats/coordinator.py`.

The coordinator:

1. requires the exact `{participant_summary: bytes}` envelope;
2. enforces the 1 MiB bound before decoding;
3. validates the closed schema and semantic contract and requires the bytes to
   equal the production serializer's deterministic encoding of that record;
4. requires report `job_id` and `participant_name` to match trusted state;
5. compares the exact canonical bytes directly with any report already
   accepted for that participant;
6. retains the first accepted canonical bytes and receipt time only in the
   bounded root-parent memory ledger; the per-report limit is 1 MiB and
   the accepted canonical bytes for one job are capped at 64 MiB; and
7. returns one of `accepted`, `duplicate`, `invalid`, `conflict`, `too_late`,
   `not_provided`, `not_expected`, or `server_error`.

The first valid canonical byte sequence is accepted. An exact byte-for-byte
retry is a duplicate, while different valid canonical bytes before cutoff are
a conflict and cannot replace the first report. New bytes after cutoff are too
late.

The CellNet reply payload is flat:

```json
{"resource_report_status":"accepted"}
```

An invalid or unavailable resource report does not change the terminal job
outcome. `accepted` means validated and retained in the live coordinator; it
does not mean restart-durable or already written to the workspace.

When a job proceeds after deployment, the root parent registers the server and
every originally selected client with `ResourceStatsCoordinator.start_job()`
before starting the server and deployable client subset. A selected client
that failed deployment, never starts successfully, or never supplies a valid
report remains visible as `missing`. After the server job process
finishes, `JobRunner._accept_server_resource_report()` reads the server
handoff, binds the participant name `server`, and calls the same coordinator
directly. It does not send a loopback CellNet message.

The originally selected client names are also persisted in job metadata as
`JobMetaKey.RESOURCE_PARTICIPANTS`. A restored root parent uses that list to
rebuild the same expected participant set; older jobs without the key fall
back to the restored active-client list.

The job's display name remains in existing server job metadata, not
coordinator resource state or the archived summary. The CLI can resolve
`JobMetaKey.JOB_NAME`, then `JobMetaKey.JOB_FOLDER_NAME`, then `job_id` for
legacy metadata. It is not added to the participant wire report.

The accepted canonical-byte ledger still lives only in the
root parent's memory. Restart recovery deliberately resets the in-progress
`resource_stats` directory instead of trusting files without the lost ledger.
Consequently, a client report accepted only before the restart is not restored
and, because the current client does not retry, that participant is normally
`missing` in the eventual summary. The cutoff and invalid-candidate history
also start fresh after restore. A restored server job process starts a new
collector for the remaining interval even without a component snapshot. An
internal launch flag marks both numeric `resource_time` and `cpu_consumed`
`partial/observation_incomplete` so the shorter interval cannot be mistaken
for the complete logical job.

## 4. Finalization, files, and the normal archive

Normal completion waits for the existing pending client outcomes or the
existing client-outcome deadline. There is no second resource-report window.
If the server job process itself fails, `JobRunner` skips that client wait and
uses the failure observation as the immediate cutoff; remaining client reports
are late. Abort follows the same no-wait behavior.
Before `JobRunner._save_workspace()`, `ResourceStatsCoordinator.finalize_job()`
closes acceptance and classifies every expected participant. Accepted entries
omit `status`; `invalid`, `missing`, and `disabled` are explicit. The accepted
measurement values likewise omit `status` and `issues` when complete, while
partial, unavailable, and error values retain their exception fields.

The final `resource_summary` has `job_id` but no `job_name`. The ID is the
unique acceptance, reconciliation, storage, and ordering key. A human-facing
name can be looked up from trusted job metadata by the authorized CLI; names
need not be unique and are never derived from participant bytes.

The coordinator copies accepted participant values from the validated
canonical bytes held in its live ledger; it does not trust a child-side file
as an input. It keeps the acceptance cutoff private. The persisted summary
contains no aggregate totals or cutoff/finalization timestamps. Only at
finalization does it write and fsync the exact accepted bytes through
parent-owned, no-symlink descriptors. It then atomically writes and fsyncs the
summary last in the local construction directory as the publication marker.
If this publication fails, `JobRunner` discards the incomplete resource
directory and continues normal job finalization without a resource view.
The resulting server run directory contains:

```text
resource_stats/
  resource_summary.json
  participants/
    server.json
    <accepted-client-name>.json
```

`JobRunner._save_workspace()` then uses the existing job completion path to
store the server run, result, log, and audit roots in the normal `WORKSPACE`
component. Packaging remains the existing job-store behavior; no second full
ZIP is built just for resource statistics. Because those roots can be
flattened into one ZIP namespace, the archive reader fails closed unless the
final `resource_stats/` inventory exactly matches the summary-derived
namespace. The reader treats `resource_summary.json` as the publication marker
and derives one `participants/<participant_name>.json` filename for each
accepted participant. Without that summary, orphan participant files are an
unpublished incomplete bundle. Duplicate, staging, missing, or extra resource
members make the resource view unavailable instead of being silently selected.
There is no `RESOURCE_STATS` storage component, database copy, or study-summary
file.

The summary-last rule applies only to the parent-owned local construction that
precedes `_save_workspace()`. The existing archiver may emit ZIP members in any
order, and the reader never relies on archive entry order.

`participant_name` is the readable registered site name, such as `site-1`.
The live coordinator compares canonical bytes directly for duplicate/conflict
decisions. This is an equality check, not a cryptographic integrity or signing
claim.

## 5. Reading one job and one study

`WorkspaceResourceStatsReader` in
`nvflare/private/fed/resource_stats/archive_reader.py` reads the fixed
`resource_stats/` members from a `WORKSPACE` ZIP. It validates the summary
publication marker, derives the exact accepted participant filenames, checks
the complete namespace, summary size bound, and duplicate ZIP names. A
participant-detail read additionally checks that selected member's size,
schema, job and participant identity, and copied-value reconciliation with the
summary. It does not extract arbitrary archive paths. The ZIP CRC can detect
accidental corruption in a member when it is read, but it is not a
cryptographic integrity check or signature.

The authenticated APIs are:

- `Session.get_job_resources(job_id, site=None)` -> `GET_JOB_RESOURCES`;
- `Session.get_study_resources()` -> `GET_STUDY_RESOURCES`.

The user commands are:

```console
nvflare job resources                         # show help
nvflare job resources --job JOB_ID            # job in the default study
nvflare job resources --job JOB_ID --study STUDY_NAME
nvflare job resources --job JOB_ID --study STUDY_NAME --site SITE_NAME
nvflare job resources --study STUDY_NAME      # all retained jobs in that study
```

The standard CLI output mode can also return JSON. `--site` is available only
with `--job`; it adds the accepted participant report, including optional CPU
and GPU models and the final visible workspace-filesystem capacity.

`JobCommandModule.get_job_resources()` reads and verifies one retained
`WORKSPACE`. It resolves any human display name from the selected job's
trusted persisted metadata, not from the resource archive.
It derives additive job totals from the accepted participant entries on
demand, using checked decimal arithmetic.
`get_study_resources()` filters the existing job list by the active study,
materializes each job's ID, trusted name, and status, excludes nonterminal
jobs from totals, and reads each retained terminal job's summary on demand. It
derives each included job's totals from accepted participant entries before
adding the study values. Every row still contains a metadata-derived name and
job ID, while the resource archive contains only the ID. Both use the existing
`get_storage_for_download(...)` API to stage the normal `WORKSPACE` component
in a request-scoped temporary directory. The archive reader opens that file
directly and reads only the size-bounded fixed resource-statistics members, so
neither query materializes the complete archive as Python `bytes`. The
temporary directory is removed after each read. The implementation does not
persist the study result, add workspace-filesystem capacities, or introduce a
second durable resource-statistics component.

The study reader rejects more than 10,000 retained jobs. While scanning, it
also charges the canonical size of each prospective row against a 64 MiB
cumulative budget before appending that row; if the budget is exhausted, the
whole request fails without deriving or returning partial totals. The complete
serialized study record is checked against the same 64 MiB bound again before
it is returned.

The job renderer starts with `Recorded resources for job NAME (ID: JOB_ID).`
The study renderer uses separate `JOB ID` and `NAME` columns. Names may repeat,
so rows are sorted and reconciled by ID. JSON exposes the same two fields.

## 6. Exact reference output

[Production reference output](production_reference/README.md) is generated
through `JobResourceCollector`, private handoff read/write,
`assemble_participant_summary`, `ResourceStatsCoordinator`, the verified
workspace reader, and the production CLI renderers. Its controlled inputs make
the output deterministic, but it does not copy or reimplement the production
math.

The most useful files are:

- [job CLI](production_reference/artifacts/cli/resources-job.txt);
- [site detail CLI](production_reference/artifacts/cli/resources-site-1.txt);
- [study CLI](production_reference/artifacts/cli/resources-study.txt);
- [job JSON CLI envelope](production_reference/artifacts/cli/resources-job.json);
- [site-detail JSON CLI envelope](production_reference/artifacts/cli/resources-site-1.json);
- [study JSON CLI envelope](production_reference/artifacts/cli/resources-study.json);
- [site participant report](production_reference/artifacts/workspace/resource_stats/participants/site-1.json);
- [job summary](production_reference/artifacts/workspace/resource_stats/resource_summary.json).

Regenerate and verify them from the repository root:

```console
python -m research.runtime_resource_proxy_prototype.production_reference.generate_reference --write
python -m research.runtime_resource_proxy_prototype.production_reference.generate_reference --check
pytest -q research/runtime_resource_proxy_prototype/production_reference/test_reference_artifacts.py
```

The larger files under `schema/golden/v1/` remain design and contract examples.
They demonstrate complete and boundary message-traffic/retained-content cases. They are not
evidence that the older live runs exercised the new F3 bindings or the current
run-directory retained-content scan.

### Live process-mode proof

The earlier substantial
[PyTorch Colossus E2E reference](colossus_pytorch_e2e_reference/README.md) was
captured from a real one-server, two-client Process-launch POC on
September 21, 2026. The stock `hello-pt` job performed three FedAvg rounds,
four local CIFAR-10 epochs per client and round, and cross-site evaluation on
one NVIDIA L40. Unlike the deterministic reference generator, this run crossed
the installed Python `-I` bootstrap, three real job child processes, private
child-to-parent handoffs, authenticated client CellNet completion requests,
root-parent reconciliation, normal `WORKSPACE` archival, the admin API, and
the job, site, and study CLI paths.

That run predates both the F3 bindings and the run-directory retained-content
scan in this branch, so those fields remain `unavailable/not_bound` in the
historical files.

All three reports were accepted. The archived records passed the production
bundle validator current at capture time, and the job, participant, and study
views reconciled exactly. This old job/study shape is intentionally not valid
under the current contract.
Independent one-second telemetry proves both client PyTorch processes used the
L40 for the 76-second training window.

This archived run exposed an important implementation gap at the time it was
captured. The driver-only host made `libcuda` and NVML system-resolvable, while
an installed NVIDIA Python distribution supplied its CUDA 13 Runtime outside
the system loader path. The then-current pre-import collector could not resolve
that `libcudart`, so the preserved reports are honestly
`partial/observation_incomplete`, and their CLI output shows GPU resource time
as `N/A`, even though the workload used the GPU.

The current collector closes that specific discovery gap. On the same class of
environment it resolves the metadata-owned NVIDIA runtime under the roots
frozen before custom imports, loads the one unique contained target by absolute
path, and successfully performs CUDA Runtime enumeration without importing
Torch. Normal PyTorch CUDA initialization and work continue afterward. This
uses no loader-path setting, system CUDA toolkit, environment change,
configuration, privilege, subprocess, or persisted path/hash/manifest. The
archived report is not rewritten; it remains evidence of the earlier safe
failure behavior.

The earlier [NumPy Colossus E2E reference](colossus_e2e_reference/README.md)
remains a useful comparison: its system-resolvable CUDA Runtime allowed the
collector to report an L40G. The PyTorch environment additionally validates
the installed-NVIDIA-distribution fallback. These runs cover the Process
launcher on Linux hosts; they do not substitute for live Docker, Kubernetes,
Slurm, constrained-cgroup, CUDA-subset, multi-GPU, or MIG coverage.

A later
[retained-content/F3 PyTorch reference](colossus_pytorch_retained_content_e2e_reference/README.md)
ran one server and two clients through the same Process-launch path on
September 22, 2026. All three reports were accepted with `reported` resource
time, terminal run-directory content, and old F3. The historical 14-message total matches
two deployments, six real task responses, and six task results. That capture
predates the intermediate job-name addition, so its stored JSON is historical
runtime evidence rather than a current
contract example. The deterministic production reference covers the current
contract.

That live repetition is now captured in the
[historical job-name reference](colossus_pytorch_job_name_e2e_reference/README.md).
Job `a624b97e-2eba-4b1c-bb44-765d83dd945b` ran `hello-pt` in study
`job-name-validation`, completed in 32.9 seconds, and accepted all three
participants. The archived job summary and derived study row both contain
`job_name: "hello-pt"`. Human output renders
`Recorded resources for job hello-pt (ID: ...).` and separate study `JOB ID`
and `NAME` columns. Resource time, retained content, and old F3 are all reported.
Its archived participant and job records predate the current contract,
including removal of the stored job name; the
[deterministic production reference](production_reference/README.md) is the
current contract example.

## 7. Known implementation and validation gaps

- The retained-content walk is not yet bounded by entry count, elapsed time, or
  filesystem boundary.
- Only the run directory is scanned. Separately configured result, log, and
  audit roots can contain retained outputs but are not represented; including
  them needs an explicit deduplication rule.
- The current focused and socket-backed F3 suites pass, and the historical
  Process-launch run supplies live origin-only sender-count evidence. Container,
  scheduler, multi-GPU, MIG, and other platform variants remain unproven.
- `observe_capacity_change()` is not wired to runtime resource changes. No
  future worker, GPU-release, or supervisor topology is assumed here.
- Official Process, Docker, Kubernetes, and Slurm workers use `-I`, sanitize
  startup `PYTHONPATH`, and snapshot before workspace download/custom-path
  activation. A bring-your-own-container entrypoint or globally installed
  `sitecustomize` remains outside that boundary. Measurements remain
  authenticated site self-reports, not tamper-resistant attestation.
- Slurm multi-node resource time is `unavailable/unsupported`; rank-zero
  numeric totals are intentionally not published.
- CUDA Runtime discovery from allowlisted NVIDIA Python distribution metadata
  is implemented and validated for the observed `nvidia/cu13` layout. Broader
  CUDA/Python packaging versions, CUDA device subsets, multiple GPUs, MIG, and
  container/scheduler environments still need live coverage. Legacy runtimes
  owned directly by a `torch` distribution and conda-only layouts remain
  unsupported and safely produce partial or unavailable compute data until a
  separately validated adapter is added.
- Expected client names are restored from `RESOURCE_PARTICIPANTS`, but the
  live accepted-report ledger, cutoff, and invalid history are not. Pre-restart
  accepted reports therefore become missing unless a new
  post-restart report is accepted.
- A restored server job process measures only its new process interval and
  marks `resource_time` and `cpu_consumed` as `partial/observation_incomplete`,
  even without a component snapshot. It never presents that post-restore
  interval as the complete logical-job duration.
- The client makes one application-level completion send; no retry/tombstone
  behavior is promised.
- Study queries stage one retained `WORKSPACE` archive at a time and avoid
  materializing it as Python `bytes`; remote-store and large-study latency
  still needs performance validation.

These gaps do not require a schema redesign. They either populate an existing
typed field, improve delivery/recovery, or replace the current collection
adapter while retaining the same final participant and job records.
