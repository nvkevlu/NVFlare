# Metrics and Sizing Guide

This guide explains the numbers printed by `validate.py` and stored in each
run's `manifest.json` and `report/summary.json`.

## Planned Numbers

Planned values are calculated before a run. They are safety envelopes used for
machine requests and preflight checks, not measured consumption.

| Metric | Meaning | Formula for this harness |
| --- | --- | --- |
| Parameter count | Number of synthetic model elements | Exact scenario input |
| Dtype bytes | Bytes per element | BF16/FP16 = 2; FP32 = 4 |
| Payload | Raw model tensor bytes | `parameter_count × dtype_bytes` |
| Wire per round | Aggregate logical two-way model traffic | `payload × clients × 2` |
| Server RAM plan | RAM envelope for a remote-client server | `(1 GiB + payload × 6) ÷ 0.8` |
| Client RAM plan | RAM envelope for each remote client | `(0.5 GiB + payload × 2.5) ÷ 0.8` |
| Same-host RAM plan | Envelope when server and both clients share one host | `(2 GiB + payload × (6 + clients × 2.5)) ÷ 0.8` |
| Disk plan | Workspace/offload/checkpoint allowance | `payload × 5` |

The division by `0.8` preserves 20% memory reserve. The fixed overhead and copy
factors were raised after the 2026-07-15 baseline: the original payload-only
formula understated Python, PyTorch, FLARE, process, and allocator overhead.
The values intentionally round above the two measured passing runs. A copy
factor is a conservative sizing coefficient; it does not claim that exactly six
server tensors or 2.5 client tensors exist at every instant.

### Example: 135M BF16

- Parameters: 135,000,000.
- Payload: `135,000,000 × 2 = 270,000,000 bytes = 0.251 GiB`.
- Wire per round: `270,000,000 × 2 clients × 2 directions = 1.006 GiB`.
- Planned server RAM: 3.14 GiB; measured peak server RSS: 1.72 GiB.
- Planned same-host RAM: 5.96 GiB; measured peak process-tree RSS: 3.87 GiB.

The plan being larger than the measurement is expected. It includes reserve and
rounded copy factors so a small change in allocator behavior does not invalidate
the machine request.

## Common Sources Of Confusion

- **GB versus GiB:** Model counts use decimal billions, while the tables convert
  bytes to binary GiB. A 14.7B BF16 payload is 29.4 GB but 27.38 GiB; these are
  the same byte count in different units.
- **Payload versus wire:** Payload is one raw model. With two clients, the server
  sends two payloads and receives two, so logical wire traffic is four times the
  payload per round.
- **Server peak versus process-tree peak:** Use server RSS for a dedicated server
  with remote clients. Use process-tree RSS only when server and clients share a
  host, as they do in local simulation.
- **Planned versus observed:** A plan is a pre-run envelope with reserve. An
  observed peak is what one specific run reached and may change with allocator,
  OS, transport, model topology, or failure phase.
- **Failed-run peak versus completed-run peak:** A failed transfer can stop before
  client materialization, aggregation, and persistence. Its low peak is not proof
  that the full scenario fits.
- **Historical versus current plan:** Run directories are immutable. Baseline
  manifests retain the formula used when they were created; current
  `validate.py` output contains the recalibrated forward-looking estimate.

## Observed Memory Metrics

| Metric | What it answers | How to use it |
| --- | --- | --- |
| `peak_process_tree_rss_bytes` | What was the largest simultaneous resident-memory total for all launcher, simulator, server, and client processes? | Primary number for same-host capacity. |
| `peak_rss_bytes_by_role.server` | What was the server process's highest resident memory? | Primary number for sizing a server with remote clients. |
| `peak_rss_bytes_by_role.client` | What was the combined client-process high-water mark on this host? | Divide cautiously when clients are symmetric; use separate-host runs for final client sizing. |
| `rss_bytes` | How much physical memory was resident at one sample or phase event? | Use for actual pressure and peaks. |
| `rss_anon_bytes` / `rss_file_bytes` | How much process RSS is anonymous versus file-backed? | Anonymous RSS is the important signal when page-cache reclaim is exhausted. |
| `unique_tensor_storage_bytes` | How many bytes are held by unique PyTorch storages visible to the observer? | Compare with anonymous RSS to separate known tensors from transport or allocator memory. |
| `tensor_storage_bytes_by_owner` | Which server owner references each tensor storage? | Values overlap by design; use the unique total for capacity and the owner map for attribution. |
| `server_before_contribution_accept` | What was resident immediately before a returned update began aggregation? | This is the decisive boundary for failures inside in-time aggregation. |
| `server_allocator_trim_probe` | What remained after the optional pre-contribution `gc.collect()` and `malloc_trim(0)` diagnostic? | Present only when the scenario explicitly enables the trim probe; compare its RSS with the preceding contribution event. |
| `vms_bytes` | How much virtual address space was mapped or reserved? | Diagnostic only; do not request RAM from VMS on macOS. |
| `system_available_bytes` | How much memory the OS estimated could be allocated without heavy reclaim? | Preflight input; more useful than simply `total - used`. |
| `maximum_swap_used_bytes` | Did the host move memory to swap at any sampled point? | A nonzero or rising value means the run is no longer a clean RAM-capacity measurement. |
| `cgroup_memory_peak_bytes` | What did a Linux cgroup report as its peak? | Preferred container/scheduler evidence when available. |
| `cgroup_oom_event_delta` | Did the cgroup record a new OOM event during this run? | Must remain zero for a baseline pass. |
| `cgroup.peaks.memory_stat_anon_bytes` | How much anonymous memory did the constrained workload charge? | Best cgroup input for selecting a hard OOM threshold; unlike file cache, it is not normally reclaimable. |
| `cgroup.peaks.memory_stat_file_bytes` | How much page cache did the workload charge? | Explains why cgroup current can greatly exceed process RSS without exhausting host memory. |
| `cgroup.counter_deltas.memory_events_high` | How often did allocation cross `memory.high` and enter reclaim/throttling? | Large growth with no OOM indicates a soft-pressure or stall lane. |
| `cgroup.counter_deltas.memory_events_max` | How often did allocation reach the hard limit? | Use with OOM counters and pressure; retries can make this much larger than one. |
| `pressure_some_total_usec` / `pressure_full_total_usec` | How long were some or all cgroup tasks stalled on memory? | Distinguishes useful reclaim from a pressure-induced livelock or timeout. |

RSS is resident set size: physical pages currently associated with a process.
The process-tree peak is calculated per sample and then maximized; it is not the
sum of each process's independent peak at different times.

`memory.high` and `memory.max` answer different questions. `memory.high` is a
soft reclaim/throttling threshold: allocations can exceed it while Linux tries
to reclaim cache. `memory.max` is the hard charge ceiling at which allocations
can trigger a cgroup OOM. `--cgroup-memory-high-gib server=320` sets only the
soft threshold and leaves the natural hard ceiling unchanged; it is the correct
way to test whether a smaller server can reclaim the large offload page cache
without manufacturing an OOM at 320 GiB.

## Transfer and Timing Metrics

| Metric | Meaning |
| --- | --- |
| `job_duration_seconds` | Wall-clock time between harness job start and finish. With full result retrieval this includes FLARE monitoring, downloading and unzipping the result bundle, and copying it into the run artifact; it is not training time. With `--skip-result-download`, it is much closer to execution plus status-polling time. |
| `phase_durations.client_receive` | Time inside the client receive instrumentation after the streamed model is materialized; transport timing also appears in native FLARE logs. |
| `phase_durations.client_send` | Time until the client is told the server downloaded its returned tensors. The final round may terminate before a last `send_end` marker, so round completion is checked independently. |
| `phase_durations.server_aggregation` | Time between server before/after aggregation events. |
| `phase_durations.server_persistence` | Time spent writing the global model checkpoint. |
| `monitor_coverage` | Fraction of job wall time spanned by process samples. Baselines require at least 90%. |
| `wire_bytes_per_round` | Logical tensor bytes, not packet captures. It excludes framing, TLS, retransmission, and retries. |
| `f3_cache_metrics.serialization_seconds` | Cumulative wall time spent producing whole serialized items for one outbound transaction. Concurrent attempts can overlap, so this is work time rather than transaction wall time. |
| `f3_cache_metrics.duplicate_productions` | Number of tensors redundantly serialized because receivers requested an uncached item concurrently. Nonzero values directly quantify the single-flight opportunity. |
| `f3_cache_metrics.cached_bytes_peak` | Largest serialized-item cache working set measured by F3 for that transaction. It is not a separate full model per client. |
| `tensor_offload_download.bytes_written` / `disk_write_seconds` | Raw safetensors bytes written and cumulative file-write time by one incoming offload download. Compare with elapsed transfer time to determine whether storage is dominant. |
| `tensor_offload_lifecycle.on_disk_bytes` | Unique offload-file bytes owned by one lazy tensor dictionary. |
| `tensor_offload_lifecycle.materialized_bytes` / `materialization_seconds` | Bytes and cumulative time loaded from offload files for aggregation. Repeated access is counted each time. |

For full-result production runs, the downloaded `meta.json` contains FLARE's
own execution duration. Compare that value with `job_duration_seconds` to
separate remote execution from result retrieval. Native transfer-log entries
are the authoritative timing for individual tensor streams.

These structured transaction summaries are imported from service logs into
`events.jsonl`. They add constant-counter and timer updates around work already
being performed; they do not poll, sample every frame, or emit one log line per
tensor.

## Correctness and Status Metrics

| Metric | Meaning |
| --- | --- |
| `status` | Harness verdict: `PASS`, `FAIL`, or `EXPECTED_FAILURE`. The last is success only for an explicitly configured and observed failure. |
| `terminal_status` | Status returned by FLARE. It is necessary but not sufficient for a pass. |
| `aggregated_clients_by_round` | Number of client updates incorporated in each round. |
| `sentinel_event_count` | Number of clients that checked the deterministic model value before updating. |
| `sentinel_pass_count` | Number of sentinel checks that matched the expected prior global model. |
| `server_round_end_growth_percent` | Change from first to final round-end server RSS. Advisory for one or two rounds; required for three or more. |
| `failure_signals` | Classified evidence such as OOM, disk full, timeout, peer loss, serialization failure, or `NETWORK_BUFFER_EXHAUSTED`. |
| `artifact_checkpoint` | Result and duration of an incremental local recovery of remote telemetry and service logs. A periodic checkpoint does not mean the FLARE job finished. |

The 0.49B local run demonstrates why `status` and `terminal_status` are separate:
FLARE returned `FINISHED:COMPLETED`, but no client received a model, no sentinel
ran, and no aggregation completed. The harness therefore returned `FAIL`.

An expected cgroup OOM is equally strict in the other direction: a timeout or
peer-loss cascade remains `FAIL` unless every `--expect-cgroup-oom` host records
a new OOM kill. Correctness and aggregation checks become informational after
the expected failure point, while artifact, telemetry, coverage, expectation,
and recovery checks remain required.

## Disk Metrics

| Metric | Meaning |
| --- | --- |
| `workspace.total_bytes` | Bytes actually stored inside this run's FLARE workspace. Use this for per-run disk consumption. |
| `workspace.checkpoint_count` | Number of recognized `.pt`, `.pth`, or `.ckpt` files. |
| `workspace.checkpoints` | Largest checkpoint paths and sizes. |
| `minimum_disk_free_bytes` | Lowest free space observed on the filesystem that holds the run. |
| `maximum_disk_used_bytes` | Highest total used bytes for that entire filesystem, not bytes written by this run. |
| Per-process `read_bytes`/`write_bytes` | OS-reported process I/O counters when the platform exposes them. macOS may report them as unavailable. |

## What To Read First

Review these fields in order:

1. `status` and the failed entries in `checks`.
2. `terminal_status`, aggregation counts, and sentinel counts.
3. Peak server RSS for distributed sizing or process-tree RSS for same-host sizing.
4. Swap and cgroup OOM deltas.
5. `failure_signals` and their source-log excerpts.
6. Workspace and checkpoint sizes.
7. Phase durations and native logs for performance diagnosis.

Do not compare the 0.49B failure peak directly with the successful 135M peak:
the failed job stopped before client materialization, aggregation, and
checkpointing, so it never reached the expected memory phases.
