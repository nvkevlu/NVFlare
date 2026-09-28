# Where CJ and SJ take their measurements

This note pins down exactly where, and when, the two job processes take the
measurements that become a participant's resource report:

- **CJ** — the client job process, `nvflare/private/fed/app/client/worker_process.py`.
- **SJ** — the server job process, `nvflare/private/fed/app/server/runner_process.py`.

Both are launched through `nvflare/private/fed/app/job_process_bootstrap.py`
under `python -I` and follow the same measurement sequence. Code is cited by
function name because line numbers drift.

The parents (CP, SP) take no resource-time, CPU-consumption, filesystem, or
retained-content measurements. They only add their own F3 counter and
assemble the report; see
[What the parents add](#what-the-parents-add).

## Summary

| Measurement | Taken in | When | What exactly is observed |
|---|---|---|---|
| Capacity snapshot (CPU, memory, GPU) | `JobResourceCollector.__init__` → `probe_capacity()`, constructed at the top of `worker_process.main()` / `runner_process.main()` | Once, at job-process start, before `download_workspace()` and `activate_job_python_path()` — before any job or site custom code is importable | Capacity visible to *this process*: cgroup CPU quota/cpuset and affinity, cgroup or physical memory limit, and GPUs enumerated by the CUDA Runtime (which honors a launcher- or resource-manager-set `CUDA_VISIBLE_DEVICES`), enriched by NVML |
| Resource-time interval **start** | `ResourceTimeAccumulator.observe()`, called by the constructor | Monotonic clock read *immediately after* `probe_capacity()` returns (the probe's own duration is excluded) | Start of `measured_seconds` |
| Resource-time interval **end** | `JobResourceCollector.finish()` → `ResourceTimeAccumulator.finish()` | Inside `_archive_results()` during teardown, after the command-callback pre-drain and the child F3 drain | `measured_seconds` = end − start. Each resource-time total = start capacity × `measured_seconds`. Capacity is **not** re-sampled at the end, and this is capacity-time, not utilization |
| CPU consumed | Job-process collector, at lifecycle hooks adjacent to the resource-time boundaries | Read once just after the resource-time start clock and once just before its final clock in `_archive_results()` | Linux/macOS `RUSAGE_SELF` user plus system delta for CJ/SJ and `RUSAGE_CHILDREN` delta for descendants exited and waited/reaped between readings, regardless of launch time. This includes short-lived waited children without periodic sampling. It is separate from CPU capacity × time. |
| Workspace filesystem capacity | `observe_workspace_filesystem(run_dir)` inside `finish()` | Same moment as the interval end | `statvfs` total size (`f_blocks × f_frsize`) of the filesystem holding the job's run directory |
| Retained content | `observe_retained_content(run_dir)` inside `finish()` | Same moment as the interval end | Sum of regular-file sizes under the job's run directory (`Workspace.get_run_dir(job_id)`), excluding the top-level `resource_stats/`; symlinks are not followed. A scan error yields `partial/observation_incomplete` |
| Child F3 | Counter started by `start_job_f3_counter()` right after the collector; records at the CoreCell send boundary for sends bound by `Communicator.submit_update()` (CJ, `task_result`) and `ServerCommandAgent` real `GET_TASK` replies (SJ, `task_response`) | From counter start until `freeze()` inside `_archive_results()` | Bytes after FOBS encoding and before optional encryption, counted when the local transport accepts the send; one message per remote destination |

## Timeline

Both processes follow this order. ⛔ marks work outside the measured resource-time
window; ✅ marks work inside it.

1. ⛔ Interpreter and `job_process_bootstrap.py` start; argument parsing;
   `Workspace(...)` object construction.
2. ⛔ `probe_capacity()` runs inside `JobResourceCollector(run_dir)`: cgroup and
   `/proc` reads, CUDA Runtime/Driver/NVML loading and enumeration.
3. **Interval start:** `ResourceTimeAccumulator.observe()` reads the monotonic
   clock. On an SJ snapshot restore (`restore_snapshot`), the collector is built
   with `prior_observation_incomplete=True`, so resource time is reported
   `partial/observation_incomplete`. The CPU-consumption baseline is taken
   immediately after this clock read; prior server-process CPU remains
   unavailable.
4. ✅ `start_job_f3_counter()` starts the process-global child F3 counter. On an
   SJ restore, `mark_prior_history_incomplete()` makes F3 `partial` with
   `attribution_incomplete`.
5. ✅ `download_workspace()` (does nothing unless the launcher configured
   workspace transfer — currently the Kubernetes launcher), then
   `activate_job_python_path()`. Job and site custom code is importable only
   from this point on.
6. ✅ Setup.
   - CJ: stats-pool config, restart-file cleanup, FOBS init, security init,
     then (inside the main `try`) configuration, logging, and client creation.
   - SJ: stats-pool config, then (inside the outer `try`) `chdir`, FOBS init,
     security init, configuration, logging, decomposers, and server and Cell
     creation.
7. ✅ The job runs (`ClientAppRunner.start_run` / `ServerAppRunner.start_server_app`).
   CJ task results and SJ real task responses are counted in child F3 as they
   are accepted by the transport.
8. ✅ Teardown via `shutdown_job_process_runtime()`
   (`nvflare/private/fed/app/job_process_cleanup.py`):
   1. Stop admitting new application commands.
   2. Wait up to 5 s (`_COMMAND_CALLBACK_DRAIN_TIMEOUT`) for in-flight command
      callbacks. A timeout or error marks child F3 `counter_gap`.
   3. `_archive_results()`:
      1. Child F3 `close_and_drain(5 s)` (`F3_DRAIN_TIMEOUT_SECONDS`), then
         `freeze()` — child F3 is now fixed.
      2. **`finish()` — final CPU-consumption reading and interval end**, then
         the filesystem `statvfs` and the run-directory walk.
      3. `write_terminal_handoff()` writes
         `run_dir/resource_stats/staging/terminal_handoff.json`.
      4. ⛔ `create_stats_pool_files_for_job()` — written after the walk, so
         `stats_pool_summary.json` is not in retained content.
      5. ⛔ `upload_results_on_shutdown()` — Kubernetes workspace transfer only;
         it also carries the handoff back to the parent.
   4. ⛔ F3 streaming shutdown, Cell stop, security close.
9. ⛔ Process exit.

## What is inside and outside the measured window

- **Inside:** everything from the clock read in step 3 to `finish()` in step
  8.3.2 — workspace download, custom-path activation, setup, the job itself,
  and up to about 10 s of teardown waiting (5 s callback pre-drain + 5 s F3
  drain; both return early when nothing is pending).
- **Outside:** interpreter start and bootstrap; the capacity probe itself;
  anything after `finish()` — stats-pool files, result upload, transport and
  Cell shutdown, security close, and process exit; and all parent-side work
  (waiting for the child, assembling and sending the report).
- **CPU consumed:** user plus system execution by the job process and waited
  descendants. The shared CP/SP site parent is excluded. `RUSAGE_CHILDREN`
  does not include an unawaited or still-running child; a known gap is partial
  or unavailable, never an implicit zero. Current PyTorch
  `MultiProcessExecutor` ranks are not waited for, and the XGBoost v2
  partial-HE process pool cannot be verified as fully reaped, so their CPU is not covered
  by the counter. The SJ restore path cannot recover its earlier process CPU.
- **Snapshot timing for the two point-in-time fields:** workspace filesystem
  capacity and retained content are observed once, at `finish()`. Files written
  after that — `stats_pool_summary.json`, the terminal handoff itself, late log
  lines — are not counted.

## Execution context by launcher

The collector runs *inside* the job process, so every probe reports that
process's own view.

| Launcher | Where the job process runs | What the probes see | Run directory that is walked |
|---|---|---|---|
| Process | Local subprocess on the parent's host | The subprocess's cgroup limits and CPU affinity; GPUs visible to it | The parent's own workspace run directory |
| Docker | Job container | The container's cgroup limits; container-visible GPUs | The job run directory bind-mounted read-write from the host at `/var/tmp/nvflare/workspace/<job_id>` |
| Kubernetes | Job pod | The pod container's cgroup limits; pod-visible GPUs | With workspace transfer: the pod-local copy (downloaded after the interval starts; results uploaded after the measurement). Otherwise the mounted volume |
| Slurm | Allocated node(s); the collector runs on rank zero only | Rank zero's cgroup limits and GPUs | Rank zero's run directory. For multi-node jobs (`NVFL_NNODES` ≠ 1) resource time is reported `unavailable/unsupported` because rank zero cannot describe the other nodes |

## When no child measurement arrives

The child handoff is written only by `_archive_results()`. If the process ends
without reaching it, the parent still sends a participant report, but its
child-derived fields (resource time, workspace filesystem, retained content,
child F3, CPU consumed) are `unavailable/observation_incomplete`. The parent's
own F3 zero is
then merged as `partial/attribution_incomplete`. This happens when:

- `JobResourceCollector(...)` construction fails. This is silent by design.
- **CJ** fails between collector start and entering the main `try` in
  `worker_process.main()`: workspace download, custom-path activation, stats-pool
  config, restart-file removal (which calls `sys.exit(-1)`), FOBS init, or
  security init.
- **SJ** fails between collector start and the inner `try` in
  `runner_process.main()`: workspace download, custom-path activation, stats-pool
  config, `chdir`, FOBS init, security init, configuration, logging, or
  decomposer registration.
- The process is killed hard (OOM kill, `SIGKILL`, pod eviction).

If only `start_job_f3_counter()` fails, the handoff is still written, with
`child_f3` `unavailable/observation_incomplete`.

## What the parents add

- **CP** — `JobExecutor._wait_child_process_finish()` in
  `nvflare/private/fed/client/client_executor.py`, after the job handle
  finishes:
  1. Freeze CP F3 without a drain (`F3_PARENT_DRAIN_TIMEOUT_SECONDS = 0.0`).
  2. Read and validate the child handoff.
  3. `assemble_participant_summary()` binds identity from parent-owned state and
     merges child and parent F3.
  4. Remove the handoff, free compute resources, and send the report on
     `REPORT_JOB_FAILURE`.

  Before launch, CP creates and syncs a per-job CPU-attempt marker under the
  site workspace root, outside the redeployed run directory and job archive.
  An existing marker, earlier launch seen in memory, or scheduler attempt
  count above one makes the new CPU subtotal partial. Marker persistence
  failure also makes the current subtotal partial without blocking launch.
  If no marker persisted before a later crash, a fresh parent cannot recover
  that attempt from an unchanged scheduler count.

  The freeze precedes the send, so the report cannot count itself.
- **SP** — `JobRunner._job_complete_process()` in
  `nvflare/private/fed/server/job_runner.py`:
  1. Freeze SP F3 without a drain.
  2. `_accept_server_resource_report()` reads the SJ handoff, builds the server
     participant report, and accepts it.
  3. `ResourceStatsCoordinator.finalize_job()` writes the participant files and
     then `resource_summary.json`, before the WORKSPACE archive is saved.

## Code anchors

- Collector construction and child F3 start: `worker_process.main()`,
  `runner_process.main()`
- Capacity probes: `probes/cgroup_linux.probe_cpu`, `probe_memory`;
  `probes/gpu_nvidia.probe_gpu`; composed by `collector.probe_capacity`
- Interval math: `accumulator.ResourceTimeAccumulator.observe` / `.finish`
- CPU-consumption counters: job-process `RUSAGE_SELF` and
  `RUSAGE_CHILDREN` start/end readings
- Final observations: `collector.JobResourceCollector.finish`,
  `observe_workspace_filesystem`, `observe_retained_content`
- Teardown order: `job_process_cleanup.shutdown_job_process_runtime`; the
  `_archive_results` closures in both job entry points
- Child handoff: `handoff.write_terminal_handoff`, `read_terminal_handoff`
- F3 bindings: `Communicator.submit_update` (`task_result`),
  `ServerCommandAgent` (`task_response`); counting at
  `CoreCell._send_to_endpoint` via `fuel/f3/send_accounting.py`
- Drain bounds: `job_process_cleanup._COMMAND_CALLBACK_DRAIN_TIMEOUT`,
  `f3_counter.F3_DRAIN_TIMEOUT_SECONDS`, `f3_counter.F3_PARENT_DRAIN_TIMEOUT_SECONDS`

## Related documents

- [ROLLUP_FLOW.md](ROLLUP_FLOW.md) — collection map table (what each field
  measures).
- [PRODUCTION_IMPLEMENTATION.md](PRODUCTION_IMPLEMENTATION.md) §1 — collection,
  bootstrap, drains, and handoff as implemented.
- [CURRENT_CODE_INTEGRATION.md](CURRENT_CODE_INTEGRATION.md) §4 — the
  `_archive_results()` hook in detail.
- [F3_GAP.md](F3_GAP.md) — exact F3 semantics and cutoff rules.
