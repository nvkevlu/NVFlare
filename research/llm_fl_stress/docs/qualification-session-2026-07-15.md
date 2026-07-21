# Three-Host Qualification Session: 2026-07-15

This is a sanitized readiness record and execution plan. It intentionally omits
addresses, usernames, SSH fingerprints, and credential locations. Raw host facts
remain under the ignored `.local/host-facts/` directory.

## Decision

**Complete** for distributed correctness, transport-failure, and memory
qualification through a one-round 12B diagnostic and controlled 10B pressure
and OOM lanes. The passing 12B run preserved at least 54.19 GiB of server
system-available memory and 34.62 GiB on each client. A one-round 14B diagnostic
is therefore the next capacity-risk tier, but it should start only with a fresh
lease window and active monitoring rather than during teardown. The network is
a measured property, not a requirement; do not label this cluster as a 25 Gbps
baseline.

The completed two-client 0.49B run shows that the Mac's `ENOBUFS` failure was a
same-host transport artifact in that test configuration. The 1.5B, 3B, 7B, and
one-round 10B and 12B gates also passed.

## Completed Results

All production gates used two clients and zero GPU devices. The 10B and 12B
diagnostics used one round; earlier gates used two. BF16 was used except for the
FP32 smoke test. `Thin` means the harness retained remote telemetry and service
logs but deliberately did not download the large checkpoint result bundle to
the local Mac.

| Gate | Result mode | Harness duration | Server peak tree RSS | `site-1` peak tree RSS | `site-2` peak tree RSS | Correctness/OOM |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Smoke | Full result | 96.8 s | 1.10 GiB | 1.37 GiB | 1.38 GiB | 4/4 sentinels; zero OOM |
| 135M | Full result | 286.4 s | 1.91 GiB | 1.74 GiB | 1.72 GiB | 4/4 sentinels; zero OOM |
| 0.49B | Full result | 977.0 s | 4.83 GiB | 2.79 GiB | 2.77 GiB | 4/4 sentinels; zero OOM |
| 1.5B | Thin | 182.5 s | 12.39 GiB | 4.89 GiB | 4.88 GiB | 4/4 sentinels; zero OOM |
| 3B | Thin | 326.1 s | 24.00 GiB | 8.41 GiB | 8.61 GiB | 4/4 sentinels; zero OOM |
| 7B | Thin | 769.4 s | 57.97 GiB | 17.35 GiB | 17.79 GiB | 4/4 sentinels; zero OOM |
| 10B, one round | Thin | 495.4 s | 57.38 GiB | 21.76 GiB | 22.00 GiB | 2/2 sentinels; zero OOM |
| 12B, one round | Thin | 625.7 s | 68.65 GiB | 25.57 GiB | 25.91 GiB | 2/2 sentinels; zero OOM |

The 3B payload was 6,180,003,760 bytes per model transfer. Individual 3B
downlinks and returns completed in roughly 58--70 seconds. Server persistence
took 3.7 seconds after round 0 and 18.9 seconds after round 1. The server's
round-end RSS growth warning remains advisory for a two-round run; all required
checks passed and no failure signal was found.

The 7B payload was 15,220,009,224 bytes per model transfer. Downlinks completed
in roughly 142--146 seconds and returns in 161--165 seconds. Server persistence
took 9.7 seconds after round 0 and 46.4 seconds after round 1. Process-tree RSS
peaked at 57.97 GiB. The cgroup's per-run current maximum was 114.86 GiB and its
persistent `memory.peak` reached 115.01 GiB, but these values are not equivalent
to unreclaimable application RAM: cgroup accounting also includes filesystem
cache, kernel memory, socket buffers, and descendant processes. At the cgroup
current maximum Linux still reported 78.25 GiB system-available memory; at the
process-tree RSS maximum it reported 65.42 GiB available. After the job,
available memory returned to 123.00 GiB while cgroup current fell to 42.36 GiB.
This is strong evidence that checkpoint/offload cache dominated the difference.
Use process-tree RSS, system-available memory, pressure/OOM events, and the
captured `memory.stat` breakdown together; do not use the persistent cgroup peak
alone as an OOM boundary. Minimum observed server disk free space was 747.64 GiB. All
required checks passed and no timeout, OOM, peer-loss, or transport failure
signal was found.

The one-round 10B payload was 20,000,012,392 bytes per model transfer. Client
downlinks completed in 192.42 and 192.64 seconds, and result uploads completed in
about 210 seconds. Aggregation took 2.41 seconds and persistence took 16.62
seconds. Server process-tree RSS peaked at 57.38 GiB while Linux still reported
65.60 GiB available; the minimum observed server availability was 65.51 GiB.
The cgroup's per-run current maximum was 122.67 GiB, but at that sample the
process tree was 46.12 GiB and Linux reported 77.05 GiB available. This again
shows that cgroup current included substantial reclaimable cache. The clients'
minimum available memory was 39.31 and 38.62 GiB, minimum server disk free was
738.73 GiB, and all OOM deltas remained zero. Final server availability returned
to 122.33 GiB. All required gates passed with no timeout, peer-loss, disk, or
transport failure signal.

The one-round 12B payload was 24,000,014,952 bytes per model transfer. Both
downlinks took about 241 seconds and both result uploads took about 257 seconds.
Aggregation took 2.70 seconds and persistence took 24.09 seconds. Server
process-tree RSS peaked at 68.65 GiB, client peaks were 25.57 and 25.91 GiB, and
minimum system-available memory was 54.19 GiB on the server and 35.17/34.62 GiB
on the clients. Server cgroup current peaked at 99.80 GiB, including an anonymous
peak of 68.25 GiB and a separately observed file-cache peak of 44.72 GiB. Full
memory pressure totaled only 0.34 seconds, all OOM counters remained zero, and
monitor coverage was 100%. Run artifacts are in
`runs/20260715T213902Z-synthetic-12b-shape-1r-6d80658e`.

All results in this document used 0.25-second process and cgroup sampling. The
scenario defaults were subsequently changed to 0.5 seconds to halve observer
work while retaining multiple samples across the shortest measured aggregation
phase. Future comparisons must read the effective interval from each run's
`scenario.json` rather than assuming the cadence is identical.

## Controlled 10B Failure Results

The failure controls are model-independent harness options, not edits to the
10B scenario. They create a temporary host-specific cgroup, leave monitoring and
admin processes outside it, capture cgroup stat/event/pressure telemetry, and
restore a killed FLARE service after collection.

| Lane | Hard/soft limit | Outcome | Key evidence |
| --- | --- | --- | --- |
| Soft pressure | 48 GiB hard, 43.2 GiB soft; hard lowered to 44 GiB live | `FAIL`: expected OOM did not occur; job timed out | 2,238,010 high events; 280.6 s full pressure; zero OOM kills |
| Hard OOM | 42 GiB hard and soft | `EXPECTED_FAILURE` after 436.2 s | 1 OOM event; 4 killed processes; 1 group kill; 35,454 max events |
| Boundary OOM | 55 GiB hard and soft | `FAIL`: unexpected OOM at about 460 s | 1 OOM event; 3 killed processes; 1 group kill; 46,144 max events |

The soft lane completed both client returns and sentinel checks but never
entered server aggregation. Anonymous memory reached 43.72 GiB and the cgroup
spent about 281 seconds with all tasks stalled on memory before the 900-second
job timeout. This demonstrates that `memory.high` can create a pressure-induced
stall without an OOM; the harness correctly rejected the configured OOM
expectation instead of treating any failure as success.

The hard lane also completed both client returns and sentinel checks, then
reached the 42 GiB cgroup limit before aggregation. Cgroup current peaked at the
limit, anonymous memory peaked at 41.90 GiB, and the group OOM killed the server
service and its job processes. Both clients then recorded the expected
`PEER_GONE` cascade. Monitoring coverage was 100% on all hosts, raw final cgroup
files were retained, the report returned `EXPECTED_FAILURE`, the temporary
cgroup was removed, and the server automatically restarted outside the test
cgroup. These two artifacts provide reusable soft-pressure and hard-OOM examples
for selecting limits on larger model tiers.

The 55 GiB boundary probe completed both client returns, then OOM-killed the
server about 33 seconds after the server accepted the returns and before any
aggregation marker. Anonymous memory reached 54.86 GiB. Because this exploratory
run did not declare an expected OOM, the original polling path waited for the
1,800-second result timeout after the server disappeared. The artifact still
retained the cgroup counters, client peer-loss cascade, final raw cgroup files,
and automatic service restoration. The harness now polls every managed cgroup,
so future unexpected OOMs terminate promptly as `FAILED:CGROUP_OOM` rather than
consuming the remaining lease. The artifact is
`runs/20260715T215211Z-falcon3-10b-shape-1r-d9388863`.

The 10B server peak was slightly below the two-round 7B peak because allocation,
offload, aggregation, and persistence lifetimes are not a simple linear function
of parameter count. Use the measured headroom rather than extrapolating from a
single RSS peak. The next-tier estimates remain diagnostic bounds, not
guarantees:

| Synthetic tier | BF16 payload | Server tree RSS | Client tree RSS | Recommendation |
| --- | ---: | ---: | ---: | --- |
| 10B | 18.63 GiB | 57.38 GiB measured | 21.76--22.00 GiB measured | Passed one round, thin result |
| 12B | 22.35 GiB | 68.65 GiB measured | 25.57--25.91 GiB measured | Passed one round, thin result |
| 14B | 27.38 GiB | unmeasured | unmeasured | Next one-round capacity-risk tier on a fresh lease |
| 32B+ | at least 60.54 GiB | unmeasured | unmeasured | Resize before attempting |

## Hugging Face Boundary

No completed gate downloaded a Hugging Face model. The harness uses the public
model cards only to select representative parameter counts, then constructs an
exact-size synthetic tensor model on each FLARE server process. The 3B, 7B, and
10B gates and the generic 12B gate required no Hugging Face token, Hub cache, NVIDIA model mirror, or
outbound Hub traffic.

For a later real-model validation:

1. Public, non-gated repositories can be downloaded without a token, but an
   authenticated read-scoped token is preferable for repeated automated pulls
   because authenticated requests receive identifiable rate-limit accounting.
2. Private or gated repositories require a user who has access and a token with
   read permission. Model-license acceptance remains a separate prerequisite.
3. Pre-stage a pinned revision once into a persistent `HF_HOME` cache on each
   machine rather than letting every FLARE process download independently.
4. Inject `HF_TOKEN` through the site environment or a mounted secret file. Do
   not put it in a scenario, job argument, exported job, startup kit, or log.
5. Outbound PyPI and Git access was verified on these hosts, but no Hugging Face
   mirror or preconfigured organization token was verified. Do not assume one.

## Verified Inventory

| Role | CPU | Total/available RAM | Free root storage | Active NIC | Runtime state |
| --- | ---: | ---: | ---: | ---: | --- |
| FLARE server | 16 vCPU | 125.66/123.72 GiB | 834 GiB | 10 Gbps | NVFlare/PyTorch environment ready |
| `site-1` | 10 vCPU | 62.45/61.09 GiB | 834 GiB | 10 Gbps | NVFlare/PyTorch environment ready |
| `site-2` | 20 vCPU | 62.45/60.96 GiB | 834 GiB | 10 Gbps | NVFlare/PyTorch environment ready |

Storage capacity is verified; storage throughput and media type are not yet
benchmarked.

Common verified properties:

- Ubuntu 24.04.4 LTS, x86-64, no configured swap, and synchronized clocks.
- Passwordless `sudo`, Git, rsync, curl, tmux, Python virtual-environment support,
  and outbound HTTPS access to PyPI.
- NVFlare, PyTorch, psutil, and `iperf3` are installed; no GPUs are present.
- Clients can reach the server directly with approximately 0.2 ms average ICMP
  latency; this is not a same-host or relayed SSH-only topology.
- TLS FLARE server and client services are deployed and registered.
- Soft/hard open-file limits are 1,024/1,048,576. Launch FLARE services with a
  65,535 soft limit to avoid an unrelated file-descriptor ceiling.
- Linux socket maxima are still at host defaults. Preserve them for the first
  baseline; change them only in a separately labeled diagnostic run.

## Capacity Fit

The plan values already include fixed runtime overhead and 20% reserve.

| Scenario | Server plan | Each client plan | Disk plan | Fits this cluster? |
| --- | ---: | ---: | ---: | --- |
| Smoke | 1.72 GiB | 0.82 GiB | 0.31 GiB | Yes |
| 135M | 3.14 GiB | 1.41 GiB | 1.26 GiB | Yes |
| 0.49B | 8.10 GiB | 3.48 GiB | 4.56 GiB | Yes |
| 1.5B | 22.76 GiB | 9.59 GiB | 14.34 GiB | Yes |
| 3B | 44.42 GiB | 18.61 GiB | 28.78 GiB | Yes |
| 7B | 107.56 GiB | 44.92 GiB | 70.87 GiB | Completed |
| 10B, one round | 140.95 GiB | 58.83 GiB | 93.13 GiB | Completed with server risk override |

The conservative 7B preflight passed. The 10B diagnostic intentionally
overrode only `server.memory`; measured system-available memory never approached
the 25 GiB stop threshold, and the run completed without OOM. The high cgroup
charge was mostly reclaimable according to simultaneous system-available
memory. A 12B diagnostic remains outside the current conservative planning
envelope and must be explicitly labeled a capacity-risk run.

## Network Expectation

The server's 10 Gbps interface is the aggregate bottleneck for two clients.
These are wire-byte lower bounds, not expected round durations.

| Scenario | Logical wire per round | 10 Gbps minimum |
| --- | ---: | ---: |
| Smoke | 0.25 GiB | 0.2 s |
| 135M | 1.01 GiB | 0.9 s |
| 0.49B | 3.65 GiB | 3.1 s |
| 1.5B | 11.47 GiB | 9.9 s |
| 3B | 23.02 GiB | 19.8 s |
| 7B | 56.70 GiB | 48.7 s |
| 10B | 74.51 GiB | 64.0 s |

Real time also includes serialization, retries, aggregation, offload, and
checkpointing. Record this environment as `10gbps` so it is never mixed with a
future 25/50/100 Gbps throughput curve.

## Harness Status

The production harness now executes `ProdEnv`, starts and retrieves per-host
monitors, preserves host-specific peaks and OOM counters, captures service logs,
and supports thin runs with `--skip-result-download`. Client heartbeat timeout
is aligned with each scenario's tensor-streaming timeout. Twenty-two targeted tests
pass, including production reporting, remote telemetry, capacity checks, and
run-window evidence filtering.

## Time-Boxed Run Order

### Phase 1: Runtime Setup

Run setup concurrently on all three machines:

1. Install `python3-pip`, `python3-venv`, and `iperf3` from Ubuntu packages.
2. Synchronize the current NVFlare source revision and this stress-harness folder.
3. Create one virtual environment per host and install this repository with
   `.[app_opt]` so PyTorch, psutil, and NVFlare are identical everywhere.
4. Run `validate.py` and record package versions on all three hosts.
5. Start every FLARE service shell with `ulimit -Sn 65535`; do not change the
   hard limit or kernel socket settings yet.

### Phase 2: Network Baseline

1. Run one sequential `iperf3` transfer from each client to the server.
2. Run both clients concurrently and record the server's aggregate receive rate.
3. Repeat in the reverse direction if time permits.
4. Preserve commands, duration, parallel-stream count, retransmits, and measured
   Gbps. Do not infer throughput from the interface's advertised link speed.

### Phase 3: Secure FLARE Deployment

1. Keep provisioning output outside Git under a private local data directory.
2. Use production TLS startup kits. For this single-operator, short-lived test,
   centralized provisioning is acceptable if each machine receives only its own
   role kit; distributed provisioning remains preferable when ownership differs.
3. Verify the root-CA fingerprint out of band, then copy only the server kit to
   the server and each client kit to its matching client.
4. Start server and clients in named tmux sessions, with logs and monitor output
   written outside the startup-kit directories.
5. Confirm both clients register before submitting any payload.

### Phase 4: Test Gates

Run two clients, BF16 except for the FP32 smoke scenario, and disk offload
enabled. Use two rounds unless a gate explicitly says otherwise:

1. Smoke: proves deployment, monitoring, result retrieval, and sentinels.
2. 135M: proves the first meaningful distributed payload and checkpoint path.
3. 0.49B standard: the session's primary result. Repeat once if it passes.
4. 0.49B small shards: run only if the standard case fails in transport.
5. 1.5B, then 3B: completed after every prior report passed.
6. 7B: completed after a fresh server/client/disk preflight.
7. 10B: completed as a one-round thin capacity-risk diagnostic with active
   monitoring and a 25 GiB server-available stop threshold.

Do not run the serial-client diagnostic first: separate hosts are intended to
exercise concurrent clients. Serial execution is a failure-isolation follow-up.

## Stop Conditions

Stop the current tier and preserve all artifacts if any of these occurs:

- Harness status is not `PASS`, even if FLARE says `FINISHED:COMPLETED`.
- A client misses a sentinel, a round aggregates fewer than two updates, or a
  checkpoint is absent.
- Any OOM/cgroup kill, peer loss, zero-byte transfer stall, `ENOBUFS`, or disk
  failure signal appears.
- Monitoring coverage is below 90% or a role's monitor exits early.
- Available server memory falls below the scenario preflight plan before launch,
  unless the run is an explicitly approved capacity-risk diagnostic.
- During a capacity-risk diagnostic, server system-available memory approaches
  25 GiB.
- Less than 200 GiB remains on the server before 7B, leaving insufficient room
  for evidence retention and a controlled retry.

## Lease Priorities

If setup consumes most of the lease, preserve useful evidence rather than
rushing tiers:

1. Must have: network baseline, smoke, 135M, and one standard 0.49B attempt.
2. Strong result: repeat 0.49B and complete 1.5B.
3. Stretch: 3B completed.
4. Optional: 7B and the one-round 10B diagnostic completed.

Before release, retrieve reports, native logs, monitor CSVs, provisioning-free
workspaces, and the network baseline. Then stop services, unload the SSH key,
remove local startup kits, and have the provider terminate all machines.
