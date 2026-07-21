# Results And Next Steps: 2026-07-20

## Executive Decision

The synthetic FLARE stress harness has a measured distributed curve from 135M
through a completed 32.5B, three-client, three-round model shape, plus controlled
pressure and OOM evidence. That 32B run completed in 1h54m02s on a 503.49 GiB
server with 245.46 GiB peak process-tree RSS. Its 494.10 GiB cgroup gauge did not
represent 494 GiB of live tensors: the highest sampled composition was 224.70
GiB anonymous, 261.57 GiB file cache, and 7.63 GiB kernel memory.

The immediate priority is now transport efficiency, not 72B. The same network
carried about 23.6 Gbps with concurrent `iperf3`, while NVFlare used only about
0.75--0.80 Gbps per flow. Generic F3 buffer tuning improved the critical path by
only 8%, and a 384-times-larger tensor request batch did not help. Lease one 256
GiB server and two 128 GiB clients for six hours to run instrumented gRPC+TLS
versus TCP+TLS tests and one targeted pipeline/single-flight iteration. Add a
third client only after a candidate passes the two-client gate.

Defer 72B until the critical path improves by at least 30% without correctness,
retry, or memory regression. When resumed, use two clients: a 768 GiB server is
the intentional one-round boundary and a 1 TiB server is the low-risk starting
point. Three clients are a separate fan-out experiment, not a prerequisite.

## Scope And Evidence Boundary

These results are real measurements of exact-size PyTorch state dictionaries
moving through production FLARE services: server distribution, client receipt,
full-model return, aggregation, disk offload, checkpoint persistence, pressure,
and failure recovery. They are not Hugging Face weight downloads and do not
include tokenization, forward/backward passes, activations, gradients, or
optimizer states. No completed capacity run used a GPU.

The selected model names remain appropriate. Official model cards identify
[Qwen2.5-14B](https://huggingface.co/Qwen/Qwen2.5-14B) as 14.7B parameters,
[Qwen2.5-32B](https://huggingface.co/Qwen/Qwen2.5-32B) as 32.5B, and
[Qwen2.5-72B](https://huggingface.co/Qwen/Qwen2.5-72B) as 72.7B. The new data
changes the resource estimates, not those parameter counts or the value of
keeping one family for the 14B/32B/72B scaling curve.

## Results At A Glance

| Gate | Payload | Rounds/clients | Outcome | Server process peak | Client process peaks | Duration | Main conclusion |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| 10B BF16 | 18.63 GiB | 1/2 | Pass | 57.38 GiB | 21.76/22.00 GiB | 8.3 min | Exact requested lower tier passed. |
| 12B BF16 bridge | 22.35 GiB | 1/2 | Pass | 68.65 GiB | 25.57/25.91 GiB | 10.4 min | Confirmed the one-round linear curve. |
| Qwen2.5 14.7B BF16 | 27.38 GiB | 1/2 | Pass | 83.94 GiB | 31.17/31.19 GiB | 13.1 min | Clean first large-model baseline. |
| Qwen2.5 14.7B BF16 | 27.38 GiB | 2/2 | Pass | 111.08 GiB | 31.46/31.81 GiB | 26.6 min | Two rounds fit the 256/128 GiB class. |
| Qwen2.5 14.7B BF16 | 27.38 GiB | 3/2 | FL complete; criterion fail | 110.97 GiB | 31.21/31.79 GiB | 40.6 min | Memory stabilized after a one-time round-1 increase, but first-to-last growth exceeded 10%. |
| Qwen2.5 14.7B FP16 | 27.38 GiB | 1/2 | Pass | 83.44 GiB | about 31 GiB | 13.0 min | BF16 and FP16 capacity were equivalent. |
| Qwen2.5 14.7B, 8 MiB chunks | 27.38 GiB | 1/2 | Pass | 83.37 GiB | about 31 GiB | 14.0 min | Larger transport chunks were slower overall; retain 2 MiB. |
| Qwen2.5 32.5B BF16 | 60.54 GiB | 1/2 | Pass | 184.51 GiB | 65.98/66.44 GiB | 30.3 min | 256/128 GiB machines are sufficient for one round. |
| Qwen2.5 32.5B BF16 | 60.54 GiB | 2/2 | Natural soft stall; operator-induced OOM capture | 226.03 GiB | 66.32/67.39 GiB | 63.0 min | Round two stalled under reclaim but did not naturally OOM at 235 GiB. Lowering the limit below live usage intentionally captured OOM behavior. |
| Qwen2.5 32.5B, one client | 60.54 GiB | 1/1 | FL complete; attribution fail | 180.33 GiB | 61.33 GiB point observation | 31.1 min | One client improved transfer time but barely changed server process peak. |
| Qwen2.5 32.5B BF16 | 60.54 GiB | 3/3 | FL complete; cumulative-growth criterion fail | 245.46 GiB | about 67 GiB each | 1h54m02s | All 9 sentinels and all three-client aggregations passed; live RSS plateaued while reclaimable file cache drove the cgroup gauge to 494.10 GiB. |

The distributed ramp below 10B also passed at 135M, 0.49B, 1.54B, 3.09B, and
7.61B. The original Mac-only 0.49B `ENOBUFS` failure did not recur with separate
hosts and is classified as a same-host transport artifact, not a model-memory
limit.

## What The Real Data Changed

### Memory

The 10B, 12B, 14B, and 32B one-round points fit:

- server process RSS: `3.034 × payload GiB + 0.86 GiB`;
- client process RSS: `1.058 × payload GiB + 2.15 GiB`.

Applied to the 135.41 GiB 72B payload, these fits forecast approximately
411.7 GiB server process RSS and 145.5 GiB on each client for one round. The
successful smaller two-round curve forecasts approximately 546.5 GiB server
process RSS for 72B. Use ranges rather than point guarantees: 390--450 GiB for
one round and 520--650 GiB for two rounds are reasonable server process-RSS
planning bands.

Cgroup memory is not interchangeable with process RSS. It includes reclaimable
file cache, kernel allocations, and socket buffers and is strongly affected by
the configured `memory.high`. Machine decisions must combine process RSS,
system-available memory, cgroup anonymous/file charge, pressure, and OOM events.

The 32B two-round trace is an allocation-ordering boundary, not evidence that
Linux merely needed more time to reclaim ordinary cache. By the stall, cgroup
file memory was approximately zero and anonymous memory was about 225.85 GiB.
Round zero released roughly one payload while final averaging completed; round
one could not reach that release point because the first accumulator allocation
was already blocked. See [server memory attribution](server-memory-attribution.md).

### Disk

The 32B one-round server consumed 121.09 GiB of incremental disk and the
two-round run consumed 241.86 GiB, almost exactly two payload-equivalents of
disk growth per round. This does not prove that two distinct model objects were
resident in server memory.
At 72B, plan for 270.83 GiB of run growth for one round and 541.66 GiB for two,
then add workspace, dependency, log, and failure-retention reserve. Client disk
growth during the synthetic runs was negligible, but clients still need room for
the runtime and any future Hugging Face cache.

### Network And Time

The two-client 32B run moved each 65.0 GB downlink in about 842.7 seconds and
each return in about 756--757 seconds. That is only about 0.62 Gbit/s per client
down and 0.69 Gbit/s per client up at the application layer, despite higher NIC
line rates. At the same path efficiency, each 72B downlink is about 31.4 minutes
and each return about 28.2 minutes. Budget 65--80 minutes for one 72B round and
130--165 minutes for two rounds before setup and artifact review.

The one-client 32B run completed the server downlink in 555.46 seconds and the
return in 511.14 seconds, about one-third faster than the two-client case. Its
server process peak fell only 2.3%, showing that the resident model and one
returned update dominate memory while client fan-out mainly affects transfer
contention. The run's formal attribution failure also established an operational
rule: stop non-target client services before a one-client test, or monitor every
registered client because task assignment can select any eligible identity.

## Machines To Lease

| Next gate | Server | Two clients | Free fast storage | Expected usage | Lease if ready | Lease if fresh |
| --- | --- | --- | --- | --- | ---: | ---: |
| **Transport engineering, next** | **256 GiB RAM, 64--96 CPU** | **128 GiB RAM, 32 CPU each** | **500 GiB server, 150 GiB each client** | 1.5B driver A/B and repeats, one targeted code iteration, 14B confirmation, optional 32B one round | 4 h | 6 h |
| 32B soft-reclaim sweep, after transport | 512 GiB RAM, 64--96 CPU | 128 GiB RAM, 32 CPU each | 500 GiB server, 150 GiB each client | Three rounds with natural `memory.max` and absolute `memory.high` at 384/320/optional 288 GiB | 5 h | 8 h |
| 72B BF16, one round, deferred | 768 GiB boundary or 1 TiB low-risk, 96--128 CPU | 256 GiB RAM, 32--64 CPU each | 750 GiB server, 200 GiB each client | 390--450 GiB fitted server RSS before transport improvements | 3 h | 4 h |
| 72B BF16, two rounds, deferred | 1 TiB RAM, 96--128 CPU | 256 GiB RAM, 32--64 CPU each | 1 TiB server, 200 GiB each client | 520--650 GiB fitted server RSS before transport improvements | 5 h | 6 h |

No GPU is required for these synthetic gates. Keep all three machines in the
same low-latency placement and measure the actual path. Network speed is a
recorded property, not a pass requirement. Faster advertised networking should
not reduce the lease budget until a smoke transfer demonstrates higher FLARE
application throughput.

For a public cloud analogue, current AWS R8idn sizes provide 512, 768, and
1,024 GiB server classes with local NVMe, while R8idn 4xlarge/8xlarge provide
128/256 GiB clients. See the official
[AWS R8i family table](https://aws.amazon.com/ec2/instance-types/r8i/).
Google Cloud also offers multi-terabyte memory-optimized families in its
[official machine guide](https://docs.cloud.google.com/compute/docs/memory-optimized-machines).

### Copyable Immediate Request

Request three same-placement CPU machines for six hours for transport engineering:

- one server with 256 GiB RAM, 64--96 logical CPUs, no swap, and at least
  500 GiB free on fast local or provisioned high-throughput storage;
- two clients with 128 GiB RAM, 32 logical CPUs, no swap, and at least 150 GiB
  free storage each;
- direct private connectivity, passwordless test-scoped administration, and no
  GPU requirement;
- measured 10/25-Gbps-class private connectivity and permission to select either
  gRPC+TLS or direct TCP+TLS for the FLARE service deployment;
- permission to retain or copy the local run artifact before teardown, and the
  lease-expiry timestamp so the harness can checkpoint 15 minutes beforehand.

## Recommended Run Order

1. **Transport baseline:** record bidirectional `iperf3`, then repeat the
   instrumented 1.5B gRPC+TLS job with the winning 4/128/32 MiB F3 profile.
2. **Driver A/B:** redeploy the same three machines with direct TCP+TLS and
   repeat the exact job. Require intact sentinels and aggregation.
3. **Targeted optimization:** use serialization duplication, cache peak,
   offload-write, and materialization counters to choose single-flight
   serialization or bounded pipelining. Do not sweep larger generic buffers.
4. **Scale confirmation:** require at least 30% critical-path improvement at
   1.5B, then run 14B one round and optional 32B one round on the same lease.
5. **Fan-out regression:** add a third client only after the candidate passes.
6. **32B reclaim sweep:** on a later 512 GiB server, set only absolute
   `memory.high` at 384/320/optional 288 GiB; retain the natural `memory.max`.
7. **72B qualification:** after transport closure, run one round with two 256
   GiB clients and a 768 GiB boundary or 1 TiB low-risk server.
8. **Real-model confirmation:** separately pre-stage a pinned Qwen revision and
   run a tiny adapter or selected-layer update. Do not describe the synthetic
   sentinel update as LLM training, and do not size full fine-tuning from these
   server-path measurements.

## Work Completed

- Built exact-parameter synthetic BF16/FP16 models with configurable tensor
  shards, transport chunks, rounds, client count, and memory cleanup cadence.
- Added production FLARE deployment, SSH-based host telemetry, process-tree and
  cgroup sampling, pressure/OOM capture, live status, immutable artifacts, and
  automatic service recovery plus five-minute/pre-expiry artifact checkpoints.
- Added structured F3 serialization/cache and tensor-offload write/materialize
  counters that are imported into each run's `events.jsonl`.
- Added thin result collection to avoid unreliable large post-run checkpoint
  downloads and a watcher that distinguishes active FL work from artifact
  collection.
- Completed the distributed curve through 32B with three clients and three
  rounds, and captured reusable local `ENOBUFS`, soft-pressure stall, expected
  hard OOM, unexpected boundary
  OOM, round-growth, result-download, and client-attribution failure artifacts.
- Compared BF16 with FP16 and 2 MiB with 8 MiB transport chunks; retained BF16
  and 2 MiB as the cross-tier baseline.

## Remaining Gaps

1. A transport path that materially improves on 0.75--0.80 Gbps per flow.
2. A 32B absolute-`memory.high` reclaim curve with natural `memory.max`.
3. Any 72B artifact.
4. GPU-backed real-model loading and a genuine forward/backward update.
5. A deterministic one-client participant-selection check in the harness.
6. A reliable large result-bundle retrieval path; thin mode remains the primary
   capacity-run mitigation.

## Artifact Map

- Historical local behavior: [local baseline](local-baseline-2026-07-15.md)
- Distributed 135M--12B results: [three-host qualification](qualification-session-2026-07-15.md)
- 14B/32B execution record: [July 17 session](session-plan-2026-07-17.md)
- Metric definitions: [metrics guide](metrics-guide.md)
- Access and lease preparation: [access runbook](access-runbook.md)
- Current machine request: [machine decision guide](machine-plan.md)

Primary large-run IDs:

- 14B one round: `20260717T161123Z-qwen25-14b-shape-1r-ac219ce8`
- 14B two rounds: `20260717T163651Z-qwen25-14b-shape-557c2f4f`
- 14B three rounds: `20260717T203906Z-qwen25-14b-shape-3r-3cbfc7f6`
- 32B one round: `20260717T195343Z-qwen25-32b-shape-1r-91de0834`
- 32B two-round OOM: `20260717T213434Z-qwen25-32b-shape-39c994bf`
- 32B one-client isolation: `20260717T231945Z-qwen25-32b-shape-1client-1r-0f7e92e4`
