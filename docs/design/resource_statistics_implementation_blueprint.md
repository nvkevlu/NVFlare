# Resource statistics implementation reference

This reference explains the collection methods, report flow, and query rules.
Resource statistics uses one final report, the existing job-completion
notification, and the normal workspace archive. Collection is best effort.

Read the [simple design](resource_statistics_simple_design.md) first. The
[current contract](../../research/runtime_resource_proxy_prototype/schema/CAPACITY_REPORT_CONTRACT_V3.md)
and [JSON Schema](../../research/runtime_resource_proxy_prototype/schema/resource_stats_v3.schema.json)
define stored fields. Production validation lives in
[contract.py](../../nvflare/private/fed/resource_stats/contract.py); the research
entry point reuses it rather than implementing a second validator.

## Scope

Collection needs no additional privilege, mount, service, package, resource
setting, or user configuration. Keep normal Python startup, imports, launch
commands, resource assignment, and process ownership. Do not create isolated
CPU groups, poll process trees, or introduce a periodic sampler.

Schema 3.0 stores raw capacities and matching seconds. Products and totals
are calculated when queried.

## Measurement and handoff flow

```text
worker_process / runner_process
  workspace download and custom-path refresh (existing)
  JobResourceCollector: observe capacity and open counters
  application execution (existing)
  final collection and staging/terminal_handoff.json
       |
       v
client parent: read handoff -> assemble report -> free resources
       |
       v
existing REPORT_JOB_OUTCOME request, with optional resource report
       |
       v
server completion handler -> ResourceStatsCoordinator.accept_resource_report
       |
       v
finalize_job: participant files -> resource_summary.json -> workspace archive
       |
       v
authorized job/site/study query -> archive reader -> derived totals -> CLI
```

The server job process has the corresponding runner/parent path. The shared
site parent is not an extra compute-capacity participant. Several jobs can
observe the same hardware; reports are not deduplicated into a host inventory.
The client parent has no counter for the included application traffic; it
passes the child's counters through. The server additionally includes its
parent process's deployment sends.

The [collector](../../nvflare/private/fed/resource_stats/collector.py) is created
after normal workspace preparation and before application construction in
[worker_process.py](../../nvflare/private/fed/app/client/worker_process.py) and
[runner_process.py](../../nvflare/private/fed/app/server/runner_process.py).
It writes the child-owned temporary
[handoff](../../nvflare/private/fed/resource_stats/handoff.py). The client parent
consumes that handoff before freeing resources and sends afterward.

## CPU and RAM capacity

[cgroup_linux.py](../../nvflare/private/fed/resource_stats/probes/cgroup_linux.py)
uses `/proc/self/cgroup` and `/proc/self/mountinfo` to find the process's
existing limit directories. Docker and Kubernetes use these cgroup limits
to restrict CPU time and memory, even when host counts are larger.
Linux exposes v1 or v2 formats, with CPU and memory controls sometimes in
different directories. Readable parent limits also apply. Collection stays
within visible mounts and does not request access to hidden host limits.

| Input | Exact query or file | Selection |
| --- | --- | --- |
| Allowed logical CPUs | `os.sched_getaffinity(0)` | Base logical-CPU count. |
| Online-CPU fallback | `os.sysconf("SC_NPROCESSORS_ONLN")`, then `os.cpu_count()` | Use when affinity is unavailable; mark incomplete. |
| CPU set | v2 `cpuset.cpus.effective`; v1 `cpuset.effective_cpus` or `cpuset.cpus` | Count allowed IDs and ranges. |
| CPU quota | v2 `cpu.max`; v1 `cpu.cfs_quota_us` / `cpu.cfs_period_us` | Finite quota divided by period. |
| Physical RAM | `os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")` | Physical-byte upper bound. |
| RAM limit | v2 `memory.max`; v1 `memory.limit_in_bytes` | Smallest finite visible limit or physical RAM. |
| CPU descriptions | `/proc/cpuinfo`, `platform.machine()` | Optional model groups and architecture. |

CPU capacity is the smallest usable observed bound, starting with affinity
or the online logical-CPU count. RAM capacity starts with physical RAM and
applies smaller readable memory bounds. An unreadable or malformed limit
does not erase those values: retain the best available capacity and mark
`resource_capacity` with `partial` and `observation_incomplete` when a
restriction cannot be checked. Host-count fallback when affinity is unavailable
uses the same indication. An absent controller or explicitly unlimited limit
is not a read error. A missing file required by an assigned v1 controller is.
Use unavailable only when no usable positive value can be obtained for that
dimension. Independent dimensions remain usable.

Keep this indication at the capacity-block level, including when all resource
values and duration are present. Do not add per-bound status fields. The compact
report cannot identify which particular limit failed. Its derived products
retain the same indication; CPU consumption uses its own independent clock and
quality. A CPU probe failure must not erase memory, CUDA, or their duration.

Quota ratios are rounded down to at most nine fractional digits. A CPU-time budget of
200,000 microseconds per 100,000-microsecond period means two logical-CPU
units; it does not pin the process to two particular CPUs. CPU shares/weights
are not fixed capacities. Best-effort capacity can exceed the true limit
when a restriction is unreadable; it is not exclusive allocation or a
guaranteed view of every host ancestor.

The same period with a 50,000-microsecond budget means 0.5 CPU units.
CPU time adds across logical CPUs: two CPUs working for 100 milliseconds
each consume 200 milliseconds of CPU time.

Parse CPU descriptions once per CPU observation. If affinity-selected CPUs
have different models and a tighter quota applies, keep scalar units without
guessing how the quota divides between models. Missing or contradictory model
descriptions do not erase numeric capacity. A shell or container-exec process
is not an observation of a different already-running worker. Inspect saved
measurements with the normal `nvflare job resources --job JOB_ID --site site-1`
command.

## CUDA capacity and descriptions

[gpu_nvidia.py](../../nvflare/private/fed/resource_stats/probes/gpu_nvidia.py)
loads the system CUDA Driver with ctypes: Linux `libcuda.so.1`, not a bundled
CUDA Runtime or framework dependency. The numeric authority is
`cuInit(0)` followed by `cuDeviceGetCount(int *)` on success. Successful zero
and explicit `CUDA_ERROR_NO_DEVICE` mean observed zero. Missing Driver, missing
required symbols, other errors, or invalid counts mean unavailable.

Every counted ordinal contributes once. `cuDeviceGet` obtains the handle;
`cuDeviceGetName` and `cuDeviceTotalMem_v2(size_t *, CUdevice)` provide optional
model and CUDA total memory. Metadata errors cannot remove a counted device.
Use `cuDeviceGetUuid_v2` privately when available. Optional NVML matches that
identity and calls `nvmlDeviceIsMigDeviceHandle`: verified non-MIG is
`full_gpu`, verified MIG is `mig_compute_instance`, otherwise the device stays
`cuda_device_unclassified`. Missing NVML or failed lookup/classification never
sets the count or converts an unverified device to a full GPU. The NVIDIA
Management Library (NVML) is optional; it classifies devices, not counts them.

The CLI shows total CUDA-device capacity/time and applicable classification
detail without counting devices twice. Do not persist UUIDs, ordinals, PCI
addresses, or environment masks. Do not parse `CUDA_VISIBLE_DEVICES` for a
count. `nvidia-smi` is management inventory, not the calling process's CUDA
selection. No subprocess, PyTorch, cuda-python, pynvml, or toolkit is required.
Native Driver/NVML calls do not have a guaranteed hard timeout.
On a CPU-only host without a loadable CUDA Driver, the CUDA count is unavailable,
not an observed zero.

## Duration and CPU work

[ResourceCapacityRecorder](../../nvflare/private/fed/resource_stats/accumulator.py)
opens an interval after probing, then closes it with the monotonic clock at
finish. Store decimal seconds; include waiting inside that interval, not
workspace preparation or the later file scan. Normal jobs have one capacity
observation. An integration can explicitly supply a changed capacity; this
closes one interval and opens another. The recorder does not discover
resource releases or poll for changes.

[CpuConsumedAccountant](../../nvflare/private/fed/resource_stats/cpu_consumed.py)
subtracts baseline from final `getrusage(RUSAGE_SELF)` and
`getrusage(RUSAGE_CHILDREN)` user-plus-system time. It records its own matching
monotonic duration. Average CPU used divides this work by that duration, not
the capacity duration, and does not depend on GPU success.

The OS accounts for children after termination and waiting; grandchildren
depend on the chain of waits. Existing managed-worker registration flags known
coverage gaps without taking over wait ownership. Do not add worker CPU a
second time. Lost earlier-attempt measurements remain incomplete. Arbitrary
unregistered descendants and boundary-crossing child lifetimes are not
guaranteed complete. Whole-group `cpu.stat` accounting is out of scope.

Inspect a completed worker's values through the normal report:

```bash
nvflare job resources --job JOB_ID --site site-1 --format json
```

That report's `cpu_consumed.seconds` and `cpu_consumed.measured_seconds` are
the work and denominator. Capacity-time uses each raw capacity's own covered
seconds, with bounded decimal arithmetic. It is derived only for queries.

## Filesystem and remaining content

At final collection, `observe_workspace_filesystem(run_dir)` uses
`os.statvfs(run_dir)` and reports `f_blocks * f_frsize`. Query only the
filesystem containing the existing run directory. Do not enumerate or sum
other filesystems or calculate storage capacity-time.

`observe_retained_content(run_dir)` streams an `os.scandir` walk and sums
regular pathname `st_size`. Skip symlinks, non-regular entries, directory sizes,
and the top-level `resource_stats` directory. Sparse apparent length counts;
hardlinks count per path. This includes inputs, logs, and configuration, not
just saved models. Preserve ordinary reachable mounted subdirectories; do not
search separately configured result roots. Only the byte total is saved, not
filenames or a file inventory.

The file walk stops after 100,000 entries, depth 64, or the cooperative
one-second budget checked between entries. Keep a partial subtotal on traversal
failure or a limit; observed empty is zero. A blocked filesystem call can
exceed the budget. Neither the walk nor the self-report is an atomic snapshot.

## Application communication

Generic [send accounting](../../nvflare/fuel/f3/send_accounting.py) measures
accepted originating logical sends, not every transport hop. Trusted local
call sites select job deployment, actual task response, and task result.
Count serialized application-payload bytes before encryption, credited after local acceptance. A completed
stream contributes once; frames, retransmissions, control/statistics traffic,
empty polling, and final same-process direct delivery do not become extra
application messages. Known rejected sends contribute nothing. Instrumentation
failures and unresolved accounting contributions leave a gap.

Managed trainers can serve tensors directly. The bounded optional contribution
on the existing `RESULT_SOURCE_SETTLED` path joins those bytes to the one task
result. Separately served tensor bytes do not create another logical message.
The [trainer bridge guide](client_api_resource_transfer_bridge.md) explains
the source association and existing site credentials. Missing proof or accounting
does not reject valid downloads or alter source cleanup, cancellation, or retries.
Site credentials identify the site, not an independently verified trainer
process. No credential or private transfer reference is saved in reports.

Use `message_traffic.sent_to` in participant JSON for accepted bytes/messages.
The CLI derives bytes sent to a participant from other participants' reports;
it is not measured receipt. Missing senders leave inbound incomplete. Counters
close before report construction so reports cannot count themselves.

## Completion notification and server storage

Attach the optional report to the existing `REPORT_JOB_OUTCOME` request.
Its existing wire topic remains `report_job_failure`. The
[server completion handler](../../nvflare/private/fed/server/fed_server.py) binds the sender
to its authenticated site/job, then calls
[ResourceStatsCoordinator](../../nvflare/private/fed/resource_stats/coordinator.py).
This is a CellNet request, not model metadata or an FL event.

The server records expected participants when starting the job. Validate bounded
values and uniqueness, normalize equivalent numeric spellings/order, and
accept the first valid report. Equivalent retries do not add measurements;
changed retries conflict. First reports after finalization are too late.

Accepted reports stay in memory until finalization writes
`resource_stats/participants/<name>.json`, then publishes
`resource_stats/resource_summary.json` last. The summary keeps participant
measurements for query-time totals. Normal workspace archival follows even
if optional statistics cannot be published. A crash before those files are
written can lose accepted reports; there is no additional recovery journal.

Preserve bounded writes, identity/path checks, atomic publication, symlink
protection, duplicate-key rejection, and report-size bounds. Child handoffs
are self-reports, not immutable evidence. Unknown is not zero; success omits
status, while exceptions use the current `partial`/`unavailable` and participant
gap forms. CPU/RAM fallback uses those same fields.

Validate each named handoff measurement independently with
`normalize_measurement(field, value)`. Replace a malformed measurement with
`unavailable` and `malformed_source`, retaining valid siblings. Malformed JSON,
identity, and envelope checks still reject the handoff as a whole. Validate
the complete public report at the server boundary. `participant_measurements`
copies the accepted measurements into a summary; it does not calculate totals.

### Explaining gaps

Successful measurements omit status and issues. The CLI shows a short reason
beside affected data; users do not need to interpret raw issue codes.

| Issue code | Concrete cause | Consequence |
| --- | --- | --- |
| `observation_incomplete` | An unreadable CPU/RAM limit, failed GPU observation, interrupted file scan, or missing earlier attempt. | Keep usable values. Fallback capacity may be too high; a stopped file scan may be too low. |
| `attribution_incomplete` | Missing waited-child CPU time or an unassociated trainer transfer. | Some CPU work or message bytes may be missing. |
| `counter_gap` | A failed accounting callback or unresolved transfer at counter closure. | Some accepted message bytes/counts may be missing. |
| `unsupported` | A platform or multi-node arrangement cannot supply this measurement. | No usable value; do not substitute zero. |
| `malformed_source` | A malformed numeric value or measurement object in the child handoff. | Discard the invalid value; keep independent valid measurements and contributions. |

## Archive queries and shutdown behavior

The [archive reader](../../nvflare/private/fed/resource_stats/archive_reader.py)
reads known members of the existing workspace archive. Extra files are harmless.
The summary is sufficient for job/study totals even when a detail file is
missing. A requested participant detail must match its summary identity and
measurements. Duplicate requested members and unsafe data remain rejected.

[Study queries](../../nvflare/private/fed/server/job_cmds.py) apply individual
job permissions before archives, rows, totals, or coverage counts. The
[CLI](../../nvflare/tool/job/job_resources.py) sorts for readability and derives
totals from participant measurements. Job names come from existing metadata, not stored
resource reports. Applicable MIG detail is shown only when relevant.

Before final collection, command callbacks may drain for up to five seconds,
and in-flight child send accounting for up to five seconds. A failed callback
drain can use a further five-second fallback after the messaging endpoint
stops. Already-settled work does not sleep for these bounds. Parent counter
freeze adds no wait. These are separate bounds, not one overall deadline;
unresolved contributions become partial data. The server uses its normal
client-outcome wait rather than an additional statistics-only wait.

## Validation and review

Run focused tests before broader lifecycle, authorization, transfer, and CLI
regressions. Regenerate current synthetic examples through production code:

```bash
PYTHONPATH=. python3 research/runtime_resource_proxy_prototype/schema/generate_v3_examples.py --check
```

Deployment validation checks process jobs, constrained Docker/Kubernetes jobs,
and single-node Slurm separately. Check both readable limits and failed-limit
fallbacks, interrupted jobs, managed trainers, and concurrent cleanup. GPU
qualification distinguishes multiple GPUs, visibility masks, and MIG. A method
description or successful training run alone does not establish that every
deployment or measurement path has been tested.
