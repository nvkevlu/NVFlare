# Qualification Session Plan: 2026-07-17

## Objective

Establish passing 14.7B and 32.5B synthetic capacity points on the new lease,
then isolate round-count, dtype, and transport-chunk effects without changing
more than one variable per comparison.

## Active Topology

| Role | SSH alias | Capacity | Purpose |
| --- | --- | --- | --- |
| Server | `flare-server` | 96 logical CPUs, 251 GiB RAM | FLARE server, aggregation, persistence |
| Client 1 | `flare-site-1` | 32 logical CPUs, 125 GiB RAM | `site-1` full-model receive/update/return |
| Client 2 | `flare-spare` | 32 logical CPUs, 125 GiB RAM | Replacement host for logical `site-2`; full-model receive/update/return |
| Expired | `flare-site-2` | Hostname no longer resolves | Former `site-2`; do not use |

All hosts use `local-kevlu`, `/bin/bash`, the short-lived stress-test SSH key,
and no swap. The 14.7B conservative plans are 206.61 GiB available server RAM,
86.19 GiB available RAM per client, and 136.90 GiB free server disk.

## Current Status

| Gate | Run | Result | Duration | Key observations |
| --- | --- | --- | ---: | --- |
| Replacement server setup | `ipp2-iop1-02.ipp2a1.colossus.nvidia.com` | Ready | 9.7 min | 96 CPUs, 251 GiB RAM, 825 GiB free disk; source synchronized, NVFlare/PyTorch installed, scenario validation passed. |
| Replacement thin smoke | `20260717T184845Z-synthetic-smoke-daa4c109` | Pass | 1.2 min | New TLS deployment passed 4/4 sentinels, complete telemetry, and zero OOM/failure signals using `flare-spare` as logical `site-2`. |
| Full-result retrieval diagnostic | `20260717T184520Z-synthetic-smoke-0346e213` | Harness fail after FLARE pass | 1.8 min | FLARE completed both rounds, but the 15 MiB result bundle hit a 30-second transfer-progress timeout; thin mode avoided this unreliable post-run path. |
| Thin smoke | `20260717T161006Z-synthetic-smoke-89f4d677` | Pass | 65 s | Completed status, sentinels, telemetry, and zero OOM events. |
| 14B BF16, one round | `20260717T161123Z-qwen25-14b-shape-1r-ac219ce8` | Pass | 13.1 min | Two 27.38 GiB downlinks and returns completed; zero failure/OOM/pressure events. |
| 14B BF16, two rounds | `20260717T163651Z-qwen25-14b-shape-557c2f4f` | Pass | 26.6 min | Both rounds aggregated 2/2 clients, 4/4 sentinels passed, and all artifacts reached the Mac before lease loss. |
| 14B BF16, three rounds | `20260717T203906Z-qwen25-14b-shape-3r-3cbfc7f6` | FL completed; qualification fail | 40.6 min | All three rounds completed with 6/6 sentinels and zero OOMs, but cumulative round-end RSS growth was 49.13% versus the required 10% maximum. |
| 14B FP16, one round | `20260717T185252Z-qwen25-14b-shape-fp16-1r-5498b434` | Pass | 13.7 min | 2/2 sentinels, complete telemetry, and zero OOM/failure signals; capacity and elapsed time matched BF16 closely. |
| 14B BF16, 8 MiB chunks | `20260717T192816Z-qwen25-14b-shape-chunk8m-1r-cb6b6d30` | Pass | 14.6 min | Clean run, but aggregate transfer was about 6.4% slower than the replacement 2 MiB baseline; retain 2 MiB for 32B. |
| 32B BF16, one round | `20260717T195343Z-qwen25-32b-shape-1r-91de0834` | Pass | 30.3 min | Two 65.00 GB downlinks and returns completed, 2/2 clients aggregated, 2/2 sentinels passed, and no OOM occurred under the 235 GiB server guard. |
| 32B BF16, two rounds | `20260717T213434Z-qwen25-32b-shape-39c994bf` | Natural soft stall; operator-induced OOM capture | 63.0 min | Round 0 passed; round 1 completed both downlinks and returns but stalled before aggregation under sustained reclaim. It did not naturally OOM at the original 235 GiB limit; an audited reduction below live usage intentionally produced the captured cgroup OOM. |
| 32B BF16, one client, one round | `20260717T231945Z-qwen25-32b-shape-1client-1r-0f7e92e4` | FL completed; attribution fail | 31.1 min | One 65.00 GB downlink and return completed with zero OOMs. FLARE assigned the task to connected logical `site-2`, but telemetry covered idle `site-1`, so required client/sentinel attribution failed. The missing `site-2` service log was recovered after the run. |

The 14B run peaked at 83.92 GiB server process-tree RSS and 140.06 GiB
server cgroup memory. Minimum system-available memory remained 159.38 GiB on
the server and 91.40/92.04 GiB on the clients. Each downlink took about 361
seconds, each return about 350 seconds, aggregation took 1.61 seconds, and
persistence took 16.65 seconds. Server system-available memory recovered to
about 242.57 GiB by the final monitor samples.

The two-round run peaked at 111.07 GiB server process-tree RSS and 221.86 GiB
server cgroup memory, while minimum system-available memory remained 131.78 GiB.
The 47.37% round-end RSS increase is advisory for a two-round run and should be
revisited with at least three rounds if sustained growth becomes the objective.
Round-one and round-two persistence took 22.49 and 35.39 seconds. The lease
ended after `result.json`, service logs, telemetry, evidence, and the passing
summary were already collected locally, so this gate does not need to be rerun.

The three-round run resolved that advisory. FLARE completed all three rounds,
aggregated 2/2 clients each round, and passed all 6 sentinels, but the harness
correctly failed the required cumulative-growth criterion. Server round-end RSS
was 55.79, 83.06, and 83.19 GiB: growth was 48.89% from round 0 to round 1 but
only 0.16% from round 1 to round 2. This supports a one-time retained-memory or
warm-up effect rather than continuing linear growth, but it does not satisfy the
configured 10% first-to-last qualification threshold. Peak server process-tree
RSS was 110.97 GiB, cgroup memory peaked at 188.23 GiB, minimum server-available
memory was 131.13 GiB, and all `memory.events:high`, `oom`, and `oom_kill`
counters remained zero.

The FP16 job duration was 781.0 seconds versus 784.3 seconds for BF16. Server
process-tree RSS peaked at 83.44 GiB versus 83.94 GiB, and server cgroup memory
peaked at 139.52 GiB versus 140.06 GiB. FP16 downlinks took about 385.5 seconds
versus 361.9 seconds, while returns took about 327.6 seconds versus 352.5
seconds. These transfer differences largely canceled and may reflect the new
server/client path rather than dtype. Both dtypes use two bytes per parameter.

The 8 MiB transport gate passed but did not improve throughput. Its downlinks
took about 380.8 seconds versus 385.5 seconds at 2 MiB, but returns took about
377.6 seconds versus 327.6 seconds. Aggregate transfer increased from about
713.1 to 758.4 seconds, and total FL execution increased from 781.0 to 838.0
seconds. Retain 2 MiB for 32B. Do not repeat the 14B gates unless service
identity or topology changes again.

The 32.5B BF16 gate passed in 1,817.5 seconds of FL execution. Each 65.00 GB
downlink took about 842.7 seconds at the server and each return took about
756--757 seconds. Aggregation took 6.47 seconds and persistence took 46.09
seconds. Peak process-tree RSS was 184.51 GiB on the server and 65.98/66.44
GiB on the clients; minimum system-available memory was 54.39 GiB on the server
and 55.76/56.28 GiB on the clients.

The server cgroup peaked at 211.504 GiB under a 211.5 GiB `memory.high` and
235 GiB `memory.max`. Crossing the soft threshold by about 4 MiB generated
2,973 `memory.events:high` reclaim events and 0.747 seconds of total memory
pressure, but `memory.events:max`, `oom`, and `oom_kill` all remained zero.
The event count is the number of times allocation was forced into reclaim, not
seconds stalled or failed allocations. This is a successful but near-soft-limit
result with 23.5 GiB still between the soft and hard cgroup limits.

The 32B two-round gate established the repeatability boundary. Round 0 completed
normally: downlinks took 852.7 seconds, returns took about 718 seconds,
aggregation took 4.40 seconds, and persistence took 46.62 seconds. Round 1
completed both 812.9-second downlinks and both 757--759-second returns, and all
4 client sentinels passed, but no round-1 aggregation event occurred.

After the second returns completed, the server remained near 226.3 GiB with
memory-pressure `avg10` around 80% and no forward progress for more than seven
minutes. The run accumulated 7,717,234 `memory.events:high` events and 368.44
seconds of cumulative full pressure, but no natural OOM at the original 235 GiB
`memory.max`. To avoid waiting for the 90-minute timeout,
the audited control first lowered `memory.max` from 235 to 226.5 GiB, then to
225 GiB. The second adjustment immediately produced 308 max events, 2,201 OOM
events, four OOM kills, and one group kill. Peak server process-tree RSS was
226.03 GiB, cgroup memory peaked at 226.42 GiB, and minimum system-available
memory was 16.09 GiB. The harness classified the outcome as
`FAILED:CGROUP_OOM`, collected all telemetry and service logs, and restored the
service automatically.

The 32B one-client isolation run completed the FL workflow and aggregated one
valid 65.00 GB update. The server-side downlink took 555.46 seconds and the
return took 511.14 seconds, corresponding to about 0.94 and 1.02 Gbit/s of
payload throughput. These phases were 34.1% and 32.4% faster than the
two-client run because they did not share the server/network path. Aggregation
took 4.08 seconds and persistence took 44.66 seconds. The server workflow ran
from round start through runner end in about 18.7 minutes, while the report's
end-to-end job/monitor span was 1,866.1 seconds (31.1 minutes), including
terminal-status and collection delay.

Server process-tree RSS peaked at 180.33 GiB, only 4.18 GiB (2.26%) below the
184.51 GiB two-client peak. This indicates that the resident full model and one
returned update dominate server process memory; client count is not a linear
process-RSS multiplier at this scale. Server cgroup memory instead peaked at
223.26 GiB, 11.76 GiB above the two-client result, because this run used a
looser 223.25 GiB `memory.high` rather than 211.5 GiB. The cgroup therefore
retained more page cache before reclaim. It recorded 1,862 high events and only
0.133 seconds of full pressure, with zero max, OOM, or OOM-kill events. Minimum
server-available memory was 52.35 GiB. The recovered active-client event showed
61.33 GiB RSS and 60.80 GiB system-available memory after receipt, but this is a
point observation rather than a monitored client peak.

The official harness result remains `FAIL`, despite terminal status
`FINISHED:COMPLETED`, because both logical clients remained registered and
FedAvg selected `site-2` for the single task. Remote monitoring was configured
only for expected `site-1`, which stayed idle, so the original report had zero
client-round and sentinel events. The late-recovered `site-2` service log proves
that its sentinel passed and its update completed, but it does not retroactively
provide process telemetry. For future one-client lanes, stop every non-target
client service before submission and confirm the sole registered identity; if
client selection is intentionally unconstrained, monitor every connected client
and treat the actual task recipient as part of the result.

## Aggressive Lease Plan and Outcome

Use at most two more primary runs on this topology:

1. **Completed: 14B BF16, 8 MiB chunks, one round.** All required checks passed,
   but aggregate transfer was 6.4% slower, so the 2 MiB baseline remains selected.
2. **Completed: 32.5B BF16, one round.** The requested 30B-class gate passed
   under the 235 GiB server `memory.max` and 211.5 GiB `memory.high`. The
   measured 184.51 GiB server process-tree RSS closely matched the 184 GiB
   forecast, and the complete thin-mode artifact was collected locally.
3. **Completed: 32.5B BF16, two rounds.** Round 0 passed, but round 1 entered
   sustained reclaim after both valid client returns and never reached
   aggregation. The workload did not naturally OOM under the original 235 GiB
   hard limit. The audited 225 GiB adjustment intentionally converted the soft
   stall into a contained OOM with complete evidence and automatic recovery.
4. **Completed with attribution caveat: 32.5B BF16, one client, one round.**
   The FL workload completed without OOM and quantified transfer fan-out, but
   unconstrained task assignment selected unmonitored logical `site-2`. Retain
   the server measurements and recovered client log; rerun only when a formally
   passing one-client qualification artifact is required.

This topology supports one 32B round but not two rounds within a 235 GiB server
guard. Do not attempt 72B here: its 135.41 GiB BF16 payload already exceeds the
clients' roughly 123 GiB available RAM before framework overhead.

## Lease Utilization Procedure

1. Pre-stage source, dependencies, and caches on retained clients while the new
   server is provisioning.
2. Start the local watcher as soon as `job.py` prints the run directory:
   `python3 research/llm_fl_stress/ops/watch_run.py RUN_DIR`.
3. Treat `COLLECTING_ARTIFACTS` as “FL work is over but do not release yet.”
   Release or advance only after `RUN_COMPLETE` exists.
4. Use `ops/live_status.py` every two or three minutes for remote phase and
   memory detail. Do not wait on buffered `tee` output.
5. Chain already-approved gates with `set -euo pipefail`; a failed smoke or
   scenario must stop the chain, while a pass starts the next gate immediately.
6. Reserve the server through the expected run duration plus a 10-minute
   collection/recovery margin. The measured 14B one- and two-round durations
   are 13.1 and 26.6 minutes.

## Execution Gates

Stop after any failed gate until its complete local artifact has been reviewed.

1. **Intake:** collect fresh host facts, verify at least 220/100/100 GiB
   available RAM on server/client/client, verify at least 200 GiB free server
   disk and 100 GiB per client, and record the actual NIC and route.
2. **Runtime:** synchronize the current source revision to the three active
   hosts, create `~/nvflare-stress-src/.venv`, install `.[app_opt]`, and run the
   scenario validator remotely.
3. **Network:** measure each client-to-server path sequentially, then both
   concurrently. Network throughput is measured, not a pass requirement.
4. **Deployment:** provision fresh TLS kits for
   `ipp2-iop1-02.ipp2a1.colossus.nvidia.com`, deploy role-specific kits, and
   confirm both clients register.
5. **Smoke:** run `smoke.json` with full result retrieval. Require job success,
   4/4 sentinels, monitor coverage, and zero new OOM events.
6. **14B BF16 one round:** run `qwen25-14b-1r.json` with two clients, 2 MiB
   transport chunks, 128 MiB tensor shards, disk offload, and thin retrieval.
7. **14B BF16 two rounds:** run `qwen25-14b.json` unchanged. Compare server
   peak, round-end growth, persistence time, and system-available memory.
8. **14B BF16 three rounds:** run `qwen25-14b-3r.json` under the 235 GiB hard
   cgroup guard. FL completed, but the run remains a qualification failure due
   to 49.13% cumulative round-end RSS growth; the final transition was 0.16%.
9. **14B FP16 one round:** run `qwen25-14b-fp16-1r.json`. This is a compatibility
   comparison, not a capacity increase, because BF16 and FP16 are both two bytes.
10. **14B 8 MiB chunk:** run `qwen25-14b-chunk8m-1r.json`. Compare transfer time,
   CPU, retry/timeout evidence, and memory against the 2 MiB BF16 one-round run.
11. **32B BF16 one round:** run `qwen25-32b-1r.json` with 2 MiB chunks, 256 MiB
    shards, thin retrieval, and the documented 235/211.5 GiB server cgroup
    limits. This gate passed; retain its configuration for future 30B baselines.
12. **32B BF16 two rounds:** run `qwen25-32b.json` under the 235/223.25 GiB
    cgroup limits. This gate established a sustained round-1 soft stall; the OOM
    was intentionally induced afterward by lowering the hard limit below live
    usage. Do not repeat it on this topology.
13. **32B BF16 one-client isolation:** before submission, stop logical `site-2`
    and confirm only `site-1` is registered, or extend telemetry to every
    connected client. This run completed the workload but failed formal
    attribution because logical `site-2` won the single task while `site-1` was
    the only monitored client.
14. **Optional only after review:** a three-client fan-out now requires another
    leased client because `flare-spare` is serving as logical `site-2`. Four
    clients would require five simultaneously reachable machines.

## Time Budget

| Phase | Expected elapsed time |
| --- | ---: |
| Intake, dependencies, network, deployment | 45--75 min |
| Smoke and review | 10--15 min |
| 14B BF16 one round and review | 20--25 min |
| 14B BF16 two rounds and review | 30--40 min |
| FP16 one round and review | 20--25 min |
| 8 MiB chunk comparison and review | 20--25 min |
| 32B BF16 one round and review | 40--45 min |
| 32B BF16 two rounds and failure collection | 75--90 min |
| 32B BF16 one-client isolation and review | 35--40 min |
| Recovery and final collection reserve | 30--45 min |

Target three to four hours. Do not spend the recovery reserve on an optional
fan-out or OOM run until every primary artifact is present locally.

## Current Execution Limitation

Outbound SSH requires explicit approval for narrowly scoped dated scripts. Fresh
TLS kits now target `ipp2-iop1-02.ipp2a1.colossus.nvidia.com`, and the passing
thin smoke confirms server, `site-1`, and replacement `site-2` registration.
Full result-bundle retrieval remains unreliable; use thin mode for primary
capacity gates and preserve the diagnostic failure artifact separately.
