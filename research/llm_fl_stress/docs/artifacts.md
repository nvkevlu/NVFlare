# Artifact Contract

Every `job.py` invocation creates a new immutable run directory. A run is the
unit used for review, comparison, archival, and failure diagnosis.

```text
runs/<timestamp>-<scenario>-<id>/
|-- manifest.json
|-- scenario.json
|-- events.jsonl
|-- result.json
|-- live_status.json
|-- RUN_COMPLETE or RUN_FAILED
|-- job_config/
|-- flare_workspace/
|-- logs/
|   |-- launcher_error.log
|   |-- fault-control.jsonl
|   `-- monitor_process.log
|-- metrics/
|   |-- process_samples.csv
|   |-- cgroup_samples.csv
|   |-- gpu_samples.csv
|   |-- monitor_errors.jsonl
|   `-- hosts/<host>/
|       |-- cgroup_samples.csv
|       |-- process_samples.csv
|       |-- cgroup-*-checkpoint.txt
|       `-- cgroup-*-final.txt
`-- report/
    |-- evidence.json
    `-- summary.json
```

## Files

- `manifest.json` records the run ID, command, source revision, host, software
  versions, and calculated payload and capacity estimates. It intentionally does
  not capture environment variables or credentials.
- `scenario.json` is an exact copy of the validated scenario used for the run.
- `events.jsonl` contains harness, client, and server phase events. Each line is
  an independent JSON object.
- `result.json` records terminal status, mode, result path, and exceptions.
- `live_status.json` is an atomically replaced local heartbeat. It records the
  current phase, FLARE status, job ID, elapsed time, update time, and artifact
  path. It does not depend on SSH after the launcher has obtained job status.
- `RUN_COMPLETE` is written only after evidence collection and report
  generation finish with `PASS` or `EXPECTED_FAILURE`. `RUN_FAILED` marks a
  completed unsuccessful harness run. Their presence is the shell-friendly
  answer to whether the local artifact is ready for review.
- `job_config/` contains the exported FLARE job for export and simulation modes.
- `flare_workspace/` is the simulator workspace and contains native FLARE logs,
  checkpoints, and site artifacts.
- `process_samples.csv` records the launcher process tree, per-process RSS/VMS,
  CPU, I/O, system memory and swap, filesystem space, and cgroup memory evidence.
- `cgroup_samples.csv` records one cgroup sample per interval, including
  anonymous/file/kernel/socket memory, hard and soft limits, memory events, and
  `some`/`full` pressure-stall totals. Production runs retain one file per host.
- `cgroup-*-final.txt` preserves the constrained cgroup's final raw
  `memory.current`, `memory.peak`, limits, events, stat, and pressure files before
  the temporary cgroup is removed.
- `cgroup-*-checkpoint.txt` is the latest raw cgroup snapshot recovered while
  the job is still running. It is overwritten by each incremental checkpoint;
  `events.jsonl` records when each recovery occurred and any per-host errors.
- `gpu_samples.csv` records `nvidia-smi` memory and utilization when available.
- `monitor_errors.jsonl` records non-fatal telemetry collection errors.
- `monitor_process.log` records failures from the out-of-process sampler, which
  can continue flushing data when the launcher is abruptly terminated.
- `fault-control.jsonl` records audited live limit adjustments made with
  `ops/adjust_cgroup_limit.py`.
- Additional scheduler output or permitted kernel OOM excerpts can be copied
  into `logs/` before finalization; the evidence collector scans `.log` files.
- `evidence.json` summarizes marker events, aggregation rounds, logs scanned,
  log-classified failure signals, and cgroup-derived `CGROUP_OOM` or
  `MEMORY_PRESSURE_TIMEOUT` signals.
- `summary.json` is the machine-readable pass/fail/expected-failure report.
  It also records phase durations, final workspace size, and checkpoint sizes.

For a managed cgroup, the production poller reads `memory.events` during the
run. A new `oom_kill` ends an undeclared failure lane promptly as
`FAILED:CGROUP_OOM`; an explicitly expected host still produces the stricter
`EXPECTED_FAILURE` report only after its OOM evidence is verified.

Start with `summary.json`: read the harness `status` and failed checks, then the
FLARE terminal status, aggregation and sentinel counts, memory peaks, swap/OOM
evidence, failure signals, workspace size, and durations. The
[metrics and sizing guide](metrics-guide.md) defines each major field and
explains which peak to use for same-host or distributed capacity.

## Event Names

Server events include `server_run_start`, `server_round_start`,
`server_before_aggregation`, `server_after_aggregation`,
`server_before_persist`, `server_after_persist`, and `server_run_end`.

Client events include `client_receive_start`, `client_receive_end`,
`client_send_start`, and `client_send_end`. Receive events include the sentinel
value, expected value, validation status, and process RSS.

Harness events include `run_heartbeat`, `artifact_checkpoint`, and
`run_completed`. A heartbeat is
written immediately when phase or FLARE status changes and otherwise defaults
to once per minute, independent of the five-second status/OOM polling cadence.
Artifact checkpoints default to every five minutes and can also run once at a
configured lead time before lease expiry. They copy flushed telemetry and
service logs without stopping the remote monitor or changing job state.

F3 and tensor-offload service logs contain one structured summary per transfer
or offload lifecycle. Evidence collection imports these records into
`events.jsonl` as `f3_cache_metrics`, `tensor_offload_download`, and
`tensor_offload_lifecycle` events.

## Comparison Rules

- Compare runs only when scenario fields, source revision, and deployment mode
  are recorded.
- Preserve failed runs. Failure evidence is a primary output of the harness.
- Never edit a completed run in place. Create a new run for every retry.
- Use `summary.json` for automation and native logs for diagnosis.
