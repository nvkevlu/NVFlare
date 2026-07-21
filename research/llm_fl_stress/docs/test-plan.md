# Expedited Test Plan

This plan is intentionally measured in hours and days, not weeks. Machine
procurement can proceed in parallel with local harness validation.

## First Four Hours

1. Run `python3 research/llm_fl_stress/validate.py` to validate every scenario
   and review calculated payload, wire, and provisional capacity values.
2. Run the 16M-parameter smoke scenario for two clients and two rounds.
3. Run `smollm2-135m.json` for the first payload scaling point. If it passes,
   run the 0.49B small-shard and serial diagnostics defined in the README.
4. Confirm server phase events, client sentinel checks, process samples, and the
   generated report.
5. Reserve `qwen25-1.5b.json` and larger tiers for the three-node qualification
   environment, then verify that peak RSS scales with payload size.

## Day One

1. Request the exact three-node qualification environment in
   [the machine decision guide](machine-plan.md), run through 7B, then optionally
   run the one-round 10B capacity-risk diagnostic before resizing the same roles
   to the documented 14B configuration.
2. Run BF16, two clients, two rounds, 2 MiB chunks, and tensor disk offload.
3. Repeat once with disk offload disabled if the machine has sufficient memory.
4. Set the observed peak plus 20% as the provisional 14B server requirement.

## Day Two

1. Repeat the selected 14B configuration to verify reproducibility.
2. Run one controlled failure with `--cgroup-memory-max-gib HOST=GIB`,
   `--expect-cgroup-oom HOST`, and `--allow-capacity-risk`. Keep telemetry outside
   the temporary cgroup and use `--cgroup-memory-high-ratio 1.0` for a hard-OOM
   lane rather than a prolonged soft-pressure lane.
3. Confirm the failure is classified and that cgroup, FLARE, and monitor evidence
   are retained; attach scheduler output or permitted kernel excerpts separately.
4. Move directly to 32B if the 14B artifact and failure gates pass.

## Network Optimization Day

1. Lease one 256 GiB server and two 128 GiB clients for six hours, with local
   NVMe and measured 10/25-Gbps-class private connectivity. GPUs are unnecessary.
2. Reproduce the instrumented 1.5B gRPC+TLS baseline, then run the same job over
   direct TCP+TLS. Compare critical path, throughput, serialization duplication,
   F3 cache peak, offload-write time, and correctness.
3. Carry only a candidate that improves critical path by at least 30% to 14B
   one round and optional 32B one round. Add a third client only after the
   two-client gate passes.
4. Delay 72B until the network/software path improves; the current 0.75--0.80
   Gbps per-flow path wastes too much large-memory lease time.
5. Add one actual Qwen2.5-14B one-step confirmation after the synthetic 14B
   baseline; do not repeat it at larger tiers unless tensor topology materially
   changes the measured memory ratio.

## Baseline Success Criteria

A baseline run passes only when all required checks pass:

- FLARE reports `FINISHED:COMPLETED`.
- The server records the expected number of aggregated clients for every round.
- Every configured client sends one contribution for every configured round.
- Every client validates the deterministic sentinel before sending its update.
- Required artifacts and telemetry samples are present.
- Telemetry covers at least 90% of the measured job interval.
- No OOM, disk-full, peer-gone, transfer-timeout, serialization, or checkpoint
  failure signal is found.
- For runs with at least three rounds, server round-end RSS after the last
  persistence is no more than 10% above the first. One- and two-round runs
  report the same comparison as an advisory because they cannot distinguish
  allocator warm-up from sustained growth.

The 14.7B, 32.5B, and 72.7B Qwen2.5-shaped scenarios represent the requested
10B, 30B, and 70B tiers while keeping model family and BF16 dtype constant.

## Measurements

Capture these for every run:

- Peak and phase-specific server RSS/VMS.
- Process-tree RSS to expose simulator and subprocess amplification.
- Per-client RSS before and after receive/send.
- System available memory, swap, cgroup current/peak, `memory.stat`, pressure,
  and OOM counters.
- GPU memory and utilization when a real-model smoke lane is added.
- Bytes read/written, disk free space, and checkpoint size.
- Round, receive, send, aggregation, and persistence duration.
- Stream retries, transfer timeouts, peer disconnects, and final job status.
- Scenario, source revision, package versions, host description, and command.

## Initial Test Matrix

| Gate | Payload | Clients | Rounds | Disk offload | Purpose |
| --- | ---: | ---: | ---: | --- | --- |
| S0 | 16M FP32 | 2 | 2 | On | Harness correctness |
| S1 | 135M BF16 | 2 | 2 | On | First laptop scaling point |
| S2a | 0.49B BF16, 16 MiB shards | 2 | 2 | On | Local transport diagnostic |
| S2b | 0.49B BF16, one thread | 2 | 2 | On | Local concurrency diagnostic |
| S2c | 0.49B BF16, distributed | 2 | 2 | On | First remote-client baseline |
| S3 | 1.54B BF16 | 2 | 2 | On | Qualification cluster scaling |
| S4 | 3.09B BF16 | 2 | 2 | On | Small server baseline |
| S4a | 7.61B BF16 | 2 | 2 | On | Qualification cluster ceiling |
| S4b | 10B BF16 | 2 | 1 | On | Monitored capacity-risk diagnostic |
| S4c | 12B BF16 | 2 | 1 | On | Measured bridge to the 14B tier |
| S5 | 14.7B BF16 | 2 | 2 | On | First large baseline |
| S6 | 14.7B BF16 | 2 | 2 | Off | Offload comparison |
| S7 | 32.5B BF16 | 2 | 2 | Selected | Scale validation |
| S8 | 72.7B BF16 | 2 | 2 | Selected | Maximum baseline |
| S9 | Actual 14.7B topology | 2 | 1 | Selected | Real-model confirmation |

Do not run the full Cartesian product. Tune at 14B, freeze the configuration,
then carry it to 32B and 72B.

## Machine Intake Checklist

Complete the [short-lived access runbook](access-runbook.md) before the lease
starts. Keep SSH private keys and NVFlare startup kits outside the repository.
Before consuming a large allocation, record RAM, swap, cgroup or scheduler
memory limit, CPU count, local filesystem type and free space, container runtime,
kernel, Python, PyTorch, NVFlare revision, and `nvidia-smi` output. Confirm the
job workspace is on local high-throughput storage rather than a small root disk.
If a scheduler or kernel kills the launcher, copy the allocation output and any
permitted OOM excerpt into the run's `logs/` directory, then run the finalizer.
