# Local Baseline: 2026-07-15

This baseline establishes what the same-host harness can measure on a developer
machine before any large-memory server is available. Raw run directories are
local and git-ignored; the run IDs below connect these findings to their full
manifests, logs, metrics, and reports.

The run directories are immutable and retain the provisional capacity formula
used on the run date. After comparing that formula with the passing measurements,
the harness raised its fixed overhead and payload-copy allowances. Use these run
reports for observed values and current `validate.py` output for future machine
planning; the [metrics and sizing guide](metrics-guide.md) explains the difference.

## Environment

- Apple M2 Pro, 12 logical/physical CPUs, arm64.
- 32 GiB unified memory and no configured swap reported by `psutil`.
- macOS 26.5.2 and Python 3.12.13.
- PyTorch 2.13.0 and `nvflare-nightly` 2.8.0rc1+211.g43034da23.dirty.
- NVFlare source commit `43034da232ec53c4d60dd549f1325dcae03ed744`.
- Two simulated sites, two rounds, external client processes, and tensor disk
  offload for every run.

## Results

| Run | Payload | Result | Duration | Peak process tree | Peak server | Workspace |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `20260715T155344Z-synthetic-smoke-88aea1a9` | 0.06 GiB | Pass | 28.15 s | 2.33 GiB | 0.69 GiB | 0.13 GiB |
| `20260715T160645Z-smollm2-135m-shape-1446efbb` | 0.25 GiB | Pass | 28.10 s | 3.87 GiB | 1.72 GiB | 0.50 GiB |
| `20260715T155452Z-qwen25-0-5b-shape-a1d0692f` | 0.91 GiB | Fail | 623.88 s | 3.88 GiB | 2.38 GiB | <0.01 GiB |

Both passing runs completed every round, aggregated both clients, passed all
four sentinel checks, created two checkpoints, recorded no swap, and exceeded
90% monitor coverage. Their two-point server round-end RSS growth was 14.10%
and 13.99%, respectively. The report preserves this as an advisory because two
rounds cannot distinguish allocator warm-up from sustained growth.

The 135M run is the recommended first meaningful local baseline. Its 270 MB
BF16 payload produced a 1.72 GiB server peak and a 3.87 GiB same-host
process-tree peak, demonstrating why payload bytes alone are not a machine-size
estimate.

## 0.49B Failure

The 0.49B run did not fail from memory pressure:

- The process-tree peak was 3.88 GiB, the server peak was 2.38 GiB, no swap was
  observed, and no OOM signal was recorded.
- Both initial concurrent client downloads logged macOS `OSError: [Errno 55]
  No buffer space available`.
- FLARE then logged `comm_error`, missing client paths, zero-byte active stream
  progress, transaction timeouts near 310 seconds, and `PEER_GONE` after the
  300-second heartbeat interval.
- No client received a model, no sentinel ran, no aggregation completed, and no
  checkpoint was written.
- FLARE returned `FINISHED:COMPLETED` after its task timeout despite zero
  completed rounds. The harness correctly marked the run `FAIL` from the
  independent round, sentinel, aggregation, and failure-evidence gates.

The failure classifier was expanded after this run to label future occurrences
as `NETWORK_BUFFER_EXHAUSTED`, `TRANSFER_PROGRESS_TIMEOUT`, `PEER_GONE`, and
`SUBPROCESS_SHUTDOWN`. The original immutable report contains the already
detected `PEER_GONE` evidence; the raw log retains the earlier root cause.

## Interpretation

The single-machine results are representative for recipe correctness, exact
payload allocation, local serialization/streaming, FedAvg aggregation,
persistence, server phase RSS, process-tree amplification, and failure-artifact
capture. They are not a prediction of remote NIC/TLS throughput, scheduler
behavior, or independent server/client memory limits.

The 0.49B outcome is specifically a same-host concurrent transport result, not
proof that a 32 GiB machine lacks memory for that payload. Diagnose it with two
controlled follow-ups, changing one variable per run:

1. Run `configs/qwen25-0.5b-small-shards.json`, which keeps two clients and the
   0.49B payload but reduces shards from 64 MiB to 16 MiB.
2. Run `configs/qwen25-0.5b-serial.json`, which restores 64 MiB shards but reduces
   simulator concurrency from two threads to one.

Do not move to 1.5B on this host until one 0.49B diagnostic passes or the same
payload passes with clients on separate machines.
