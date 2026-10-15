# Resource statistics implementation guide

Resource statistics adds best-effort observation to the existing job lifecycle.
The implementation keeps one final report and uses the existing completion
notification and workspace archive. Minimal changes and explainable values
take priority over a broader or more exact monitoring system.

Read the [simple design](resource_statistics_simple_design.md) first. The
[current contract](../../research/runtime_resource_proxy_prototype/schema/CAPACITY_REPORT_CONTRACT_V3.md)
and [JSON Schema](../../research/runtime_resource_proxy_prototype/schema/resource_stats_v3.schema.json)
define stored fields. Production validation lives in
[contract.py](../../nvflare/private/fed/resource_stats/contract.py); the research
entry point reuses it rather than implementing a second validator.

## Boundaries that must not change

Collection needs no additional privilege, mount, service, package, resource
setting, or user configuration. Keep normal Python startup, imports, launch
commands, resource assignment, and process ownership. Do not create isolated
CPU groups, poll process trees, or introduce a periodic sampler.

Only the current schema 3.0 format is supported. Older prototype formats were
never released and do not need production readers or version-specific totals.
Their historical files remain in the preserved prototype, not this feature's
runtime. Normal report quantities are raw capacities plus matching seconds;
products and totals are calculated when queried.

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
root handler -> ResourceStatsCoordinator.accept_resource_report
       |
       v
finalize_job: participant files -> resource_summary.json -> workspace archive
       |
       v
authorized job/site/study query -> archive reader -> derived totals -> CLI
```

The server job process has the corresponding runner/parent path. The shared
site parent is not an extra compute-capacity participant. Each job may see
shared hardware; do not deduplicate observations using private device IDs.

The [collector](../../nvflare/private/fed/resource_stats/collector.py) is created
after normal workspace preparation and before application construction in
[worker_process.py](../../nvflare/private/fed/app/client/worker_process.py) and
[runner_process.py](../../nvflare/private/fed/app/server/runner_process.py).
It writes the child-owned temporary
[handoff](../../nvflare/private/fed/resource_stats/handoff.py). The client parent
consumes that handoff before freeing resources and sends afterward. Preserve
current main's exception publication and MainProcessMonitor cleanup ownership.

## CPU and RAM capacity

[cgroup_linux.py](../../nvflare/private/fed/resource_stats/probes/cgroup_linux.py)
reads `/proc/self/cgroup` and `/proc/self/mountinfo` once per combined capacity
observation. Resolve controller membership relative to the covering mount root,
including escaped paths. CPU, CPU-set, and memory controllers are resolved
independently for v1, v2, and hybrid layouts. Walk only visible ancestors up to
that mount root; do not discover hidden limits through privileged host access.

| Input | Exact query or file | Selection |
| --- | --- | --- |
| Allowed logical CPUs | `os.sched_getaffinity(0)`; existing online-CPU fallback if unavailable | Candidate CPU population. |
| CPU set | v2 `cpuset.cpus.effective`; v1 `cpuset.effective_cpus` or `cpuset.cpus` | Count allowed IDs and ranges. |
| CPU quota | v2 `cpu.max`; v1 `cpu.cfs_quota_us` / `cpu.cfs_period_us` | Finite quota divided by period. |
| Physical RAM | `os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")` | Physical-byte upper bound. |
| RAM limit | v2 `memory.max`; v1 `memory.limit_in_bytes` | Smallest finite visible limit or physical RAM. |
| CPU descriptions | `/proc/cpuinfo`, `platform.machine()` | Optional model groups and architecture. |

CPU capacity is the smallest valid observed bound. Preserve nine-decimal quota
normalization and unlimited sentinels. An applicable unreadable or malformed
limit must not turn into a wider host-capacity fallback. Independent valid
dimensions remain usable. The claim is limits visible to the process, not
exclusive allocation or a guaranteed view of every host ancestor.

Parse CPU descriptions once per CPU observation. If affinity-selected CPUs
have different models and a tighter quota applies, keep scalar units without
guessing how the quota divides between models. Missing or contradictory model
descriptions do not erase numeric capacity. Each new probe has fresh discovery;
there is no global cache. Standalone no-argument probe APIs remain available.

To inspect the selected methods in the current Python process:

```bash
python3 - <<'PY'
import json
from nvflare.private.fed.resource_stats.collector import probe_capacity, probe_cpu, probe_memory
print(json.dumps({"cpu": probe_cpu(), "memory": probe_memory(), "combined": probe_capacity()}, indent=2))
PY
```

These three calls are separate diagnostic observations. Production uses one
combined observation. A shell or container-exec process is not an observation
of a different already-running job worker. `nproc` can miss fractional quota;
`free` can show host RAM rather than a container's readable limit.

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
sets the count or converts an unverified device to a full GPU.

```bash
python3 - <<'PY'
import json
from nvflare.private.fed.resource_stats.collector import probe_gpu
print(json.dumps(probe_gpu(), indent=2))
PY
```

The CLI shows total CUDA-device capacity/time and applicable classification
detail without counting devices twice. Do not persist UUIDs, ordinals, PCI
addresses, or environment masks. Do not parse `CUDA_VISIBLE_DEVICES` for a
count. `nvidia-smi` is management inventory, not the calling process's CUDA
selection. No subprocess, PyTorch, cuda-python, pynvml, or toolkit is required.
Native Driver/NVML calls do not have a guaranteed hard timeout.

## Duration and CPU work

[ResourceCapacityRecorder](../../nvflare/private/fed/resource_stats/accumulator.py)
opens an interval after probing, then closes it with the monotonic clock at
finish. Store decimal seconds; include waiting inside that interval, not
workspace preparation or the later file scan. Normal jobs have one flat
observation. The existing explicitly supplied capacity-change hook remains
recording-only; it does not add automatic GPU-release detection or probing.

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
search separately configured result roots.

```bash
python3 - /absolute/path/to/existing/job/run-directory <<'PY'
import json
import sys
from nvflare.private.fed.resource_stats.collector import observe_retained_content, observe_workspace_filesystem
print(json.dumps({"filesystem": observe_workspace_filesystem(sys.argv[1]),
                  "files": observe_retained_content(sys.argv[1])}, indent=2))
PY
```

The file walk stops after 100,000 entries, depth 64, or the cooperative
one-second budget checked between entries. Keep a partial subtotal on traversal
failure or a limit; observed empty is zero. A blocked filesystem call can
exceed the budget. Neither the walk nor the self-report is an atomic snapshot.

## Application communication

Generic [send accounting](../../nvflare/fuel/f3/send_accounting.py) measures
accepted originating logical sends, not every transport hop. Trusted local
call sites select job deployment, actual task response, and task result.
Count post-FOBS, pre-encryption payload bytes after local acceptance. A completed
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
Site credentials establish a site trust boundary, not independent trainer
attestation. No credential or private transfer reference is saved in reports.

Use `message_traffic.sent_to` in participant JSON for accepted bytes/messages.
The CLI derives bytes sent to a participant from other participants' reports;
it is not measured receipt. Missing senders leave inbound incomplete. Counters
close before report construction so reports cannot count themselves.

## Completion notification and server storage

Attach the optional report to the existing `REPORT_JOB_OUTCOME` request.
Its existing wire topic remains `report_job_failure`. The
[root handler](../../nvflare/private/fed/server/fed_server.py) binds the sender
to its authenticated site/job, then calls
[ResourceStatsCoordinator](../../nvflare/private/fed/resource_stats/coordinator.py).
This is a CellNet request, not model metadata or an FL event. A new completion
or statistics request is a fallback only if reviewers reject this integration.

The server records expected participants at job admission. Validate bounded
values and uniqueness, normalize equivalent numeric spellings/order, and
accept the first valid report. Equivalent retries do not add measurements;
changed retries conflict. First reports after finalization are too late.

Accepted reports stay in memory until finalization writes
`resource_stats/participants/<name>.json`, then publishes
`resource_stats/resource_summary.json` last. The summary keeps participant
measurements, without stored totals. Normal workspace archival follows even
if optional statistics cannot be published. Acceptance is not crash-proof
storage; no journal or extra durable service is added.

Preserve bounded writes, identity/path checks, atomic publication, symlink
protection, duplicate-key rejection, and report-size bounds. Child handoffs
are self-reports, not immutable evidence. Unknown is not zero; success omits
status, while exceptions use the current `partial`/`unavailable` and participant
gap forms. No new issue vocabulary or status redesign is introduced.

## Archive queries and shutdown behavior

The [archive reader](../../nvflare/private/fed/resource_stats/archive_reader.py)
reads known members of the existing workspace archive. Extra files are harmless.
The summary is sufficient for job/study totals even when a detail file is
missing. A requested participant detail must match its summary identity and
measurements. Duplicate requested members and unsafe data remain rejected.

[Study queries](../../nvflare/private/fed/server/job_cmds.py) apply individual
job permissions before archives, rows, totals, or coverage counts. The
[CLI](../../nvflare/tool/job/job_resources.py) sorts for readability and derives
one current-format total. Job names come from existing metadata, not stored
resource reports. Applicable MIG detail is shown only when relevant.

The existing prototype's bounded drains remain explicit: command callbacks
up to five seconds before publication, admitted child sends up to five
seconds, and up to another five seconds for the post-stop callback fallback.
Settled work does not sleep for those bounds. Parent counter freeze waits
zero seconds. The existing server client-outcome wait is not an additional
statistics-only wait. This port adds no new wait; fault/concurrency overhead
still needs qualification. Preserve current main's cleanup owners and limits.

## Validation and review

Run focused tests before broader lifecycle, authorization, transfer, and CLI
regressions. Regenerate current synthetic examples through production code:

```bash
PYTHONPATH=. python3 research/runtime_resource_proxy_prototype/schema/generate_v3_examples.py --check
```

Historical selected Process, Docker, Kubernetes, bare single-node Slurm, and
multiple-GPU results remain in the preserved prototype. They are not new runs
of this branch. Revalidate the final tree, including startup/import compatibility,
server/two-client Process jobs, secure managed trainers, interrupted jobs,
concurrent cleanup, and selected constrained launch cases. MIG, multi-node/rank,
other Slurm backends, and production deployment policies must not be described
as verified without corresponding evidence.
