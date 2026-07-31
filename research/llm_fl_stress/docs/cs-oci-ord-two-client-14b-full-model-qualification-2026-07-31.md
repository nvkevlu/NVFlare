# CS-OCI-ORD two-client 14B full-model qualification — 2026-07-31

## Outcome

Slurm job `31218631` is a **formal qualification pass** for two-client, all-parameter federated training of the
pinned Qwen2.5-14B model on one eight-A100 node.

The allocation completed in 13:43 with Slurm state `COMPLETED` and exit code `0:0`. The exact-topology 1.5B gate,
14B target, full-state probe, checkpoint persistence watcher, GPU monitor, allocation monitor, and top-level
qualification all report `PASS`. A recursive scan of the retained text artifacts and both Slurm logs found no
traceback, CUDA out-of-memory error, fatal NCCL marker, distributed-round failure, execution exception, system
panic, or unsafe-component error.

The exact implementation under test was:

- Git commit `c748a2a0e85def7c9226d9a71a4e7c537bd0c0c7`;
- qualification release `2026-07-31-full-model-14b-v12`;
- production NVFLARE services with provisioned gRPC/TLS, not `SimEnv`;
- one CPU-only server plus two real clients on host `batch-block5-01372`;
- site-1 on GPUs 0–3 and site-2 on GPUs 4–7;
- four FSDP2 ranks per client;
- pinned Qwen2.5-14B revision `97e1e76335b7017d8f67c08a19d103c0504298c9`;
- one federated round with eight local optimizer steps per client at sequence length 512;
- every one of the model's 14,770,033,664 parameters trainable; and
- complete 579-tensor, 29,540,067,328-byte state exchange in both directions.

## Exact topology and data path

All participants ran as separate processes on the same allocated physical node. The provisioned server participant
was named `localhost` and had an empty `CUDA_VISIBLE_DEVICES`. Site-1 owned GPUs 0–3, and site-2 owned GPUs 4–7.
Each client launched four local `torch.distributed.run` workers and used FSDP2 to shard the complete model over its
four GPUs.

The colocated layout exercised real NVFLARE service startup, ephemeral startup kits, TLS transport, client task
execution, serialization, aggregation, and persistence. The transport path was localhost, so this qualification
does not measure inter-node bandwidth, independent failure domains, firewall configuration, or WAN behavior.

Both clients loaded the staged base checkpoint directly from the shared Lustre model path. NVFLARE did not transfer
the Hugging Face checkpoint itself. For the target federated round:

1. the CPU-only server sent one 29,540,067,328-byte global state to each client;
2. each client configured every model parameter as trainable and ran eight optimizer steps on distinct fixed data;
3. each client returned one changed 29,540,067,328-byte state;
4. the server accepted both contributions and completed 2/2 FedAvg aggregation; and
5. the persistence watcher observed a stable 29,540,266,113-byte checkpoint before private-scratch cleanup.

The four server/client directions therefore moved 118,160,269,312 logical bytes, or 118.16 decimal GB
(approximately 110.05 GiB), before serialization, TLS, metadata, and control overhead. Repeating full-state
federation at this scale would make communication and server-side materialization a first-order design cost.

## Pre-submission qualification ladder

The standalone readiness validator, rerun in the pinned container after the login-node interpreter issue described
below, accepted these exact-commit artifacts before submission:

| Slurm job | Purpose | Accepted result |
|---|---|---|
| `31214190` | CPU production control plane and repeated two-client jobs | `COMPLETED 0:0`, `PASS` |
| `31216702` | CPU identity, manifest, dependency, export, and packaged-job preflight | `COMPLETED 0:0`, `PASS` |
| `31217126` | Four-GPU exact-model all-parameter/full-state capacity gate | `COMPLETED 0:0`, `PASS` |

The login readiness artifact reported `safe_to_submit: true` for the exact branch, release, commit, model revision,
model and container manifests, dependency lock, and all three gate IDs. The production allocation repeated the
same readiness validation before starting services.

The first manual login-node invocation exposed an interpreter-only issue before artifact validation: the login
node's Python 3.8 did not provide `str.removeprefix()`. The unchanged evidence-producing commit then passed under
the pinned Python 3.12 container, which is also the environment used by the final wrapper. No CPU or GPU gate was
invalidated or rerun. A post-qualification follow-up replaced that call with Python 3.8-compatible prefix handling
and added a static compatibility regression; this does not change the attribution of job `31218631` to commit
`c748a2a0e`.

The final manifest records:

- exactly eight GPUs and eight total training processes;
- a 524,288-MiB Slurm memory request;
- a 10,800-second NVFLARE transport envelope; and
- 7,191 seconds remaining in the Slurm allocation at the allocation-start safety check.

This was 291 seconds above the 6,900-second feasibility threshold; nine seconds of the two-hour wall time had
elapsed before the check. The threshold itself was designed 300 seconds below the 7,200-second wall. No
application-wide total-runtime deadline cut off healthy work.

## Federated execution evidence

The final job first ran the Qwen2.5-1.5B all-parameter/full-state topology gate. It completed in 108.361 seconds
with both clients, 2/2 aggregation, and persistence. Its successful completion demonstrated the exact provisioned
service topology before the expensive target phase.

The Qwen2.5-14B target then completed in 593.227 seconds (approximately 9:53) with status
`FINISHED:COMPLETED`:

- both clients reported four ranks, 14,770,033,664 total and trainable parameters, and zero frozen parameters;
- gradient checkpointing was enabled;
- each site consumed 32 unique records from a distinct dataset SHA-256;
- each client completed eight local steps and returned one complete state;
- the server aggregated both results and persisted the output; and
- the full-state probe reported 579 tensors, 29,540,067,328 bytes, a common schema SHA-256, and distinct sampled
  client outputs.

The target's internal NVFLARE job ID was `59f210e1-26a6-4c7a-8431-93f8bd18b59c`; the gate's was
`31841711-a983-4384-aafd-4203e6a0a446`. The target probe checked 2,316 bounded values under schema SHA-256
`7b12f14a319d7e73bdbd6e579550f2c4b6a2739367cadef0ff9095a71fd5fa84` and recorded
`client_output_samples_distinct=true`. Site-1's dataset SHA-256 was
`d5c7b1a068ac28d5ce4c26f56dda3de04342690fb8b2fee17a4689dde9542360`; site-2's was
`c46ddc5d2ca407d35e95ca2ca7f9d6a8c390e31965777ba6f0e7171abc6aa3a0`.

The persisted checkpoint record is size evidence retained from the watcher. The original path under
`/raid/scratch/kevlu/31218631` was ephemeral and was removed with the private runtime. This run did not perform a
post-run reload or a tensor-by-tensor reconstruction of the complete 29.54-GB persisted state.

## Training evidence

| Site | Final loss | Local round | Sampled maximum change | Sampled parameter tensors changed |
|---|---:|---:|---:|---:|
| site-1 | 5.3382720947265625 | 26.648 s | 0.0001220703125 | 481 / 579 |
| site-2 | 5.683350086212158 | 24.306 s | 0.0001220703125 | 480 / 579 |

Site-1's loss trajectory was:

```text
5.535498, 6.722119, 6.206524, 5.857318, 5.578782, 5.347579, 5.665802, 5.338272
```

Site-2's loss trajectory was:

```text
5.992422, 6.531734, 5.915997, 6.408172, 6.309942, 6.044414, 6.512615, 5.683350
```

The update probe sampled at most 64 evenly spaced local-shard values from each parameter. Its 481/579 and 480/579
counts are lower-bound sampled evidence, not a claim that the remaining tensors received no optimizer update.

Representative gradient probes were finite and nonzero at the beginning, middle, and end of the 48-layer model:

| Site | Layer 0 L2 norm | Layer 24 L2 norm | Layer 47 L2 norm |
|---|---:|---:|---:|
| site-1 | 2.256940 | 0.654081 | 0.791668 |
| site-2 | 0.572700 | 0.468590 | 0.538260 |

Each client used AdamW with learning rate `1e-5`, `foreach=false`, and `fused=false`. On each FSDP rank, optimizer
telemetry reported 1,158 BF16 moment shards totaling 14,770,033,664 bytes plus 579 FP32 step scalars totaling 2,316
bytes. Across the four ranks of one client, that is 29,540,067,328 BF16 moment values occupying 59,080,134,656
bytes, exactly two BF16 moments per trainable parameter, plus 2,316 FP32 step scalars occupying 9,264 bytes. The
complete per-client optimizer tensor state was therefore 59,080,143,920 bytes before Python and allocator
overhead. This is an all-parameter training proof for this BF16 optimizer path; it is not evidence for conventional
FP32 Adam moments or FP32 master weights.

## GPU utilization and memory

All GPU indices 0–7 were observed and active, and every GPU reached 100% utilization in the five-second samples.
The monitor retained 144 samples per GPU:

| GPUs | Peak monitored device memory | Approximate remaining 80-GiB memory |
|---|---:|---:|
| 0 and 4 | 49,023 MiB (47.87 GiB) | 32,897 MiB (32.13 GiB) |
| 1–3 and 5–7 | 48,639 MiB (47.50 GiB) | 33,281 MiB (32.50 GiB) |

Every target rank separately reported a PyTorch peak of 40,157,044,224 allocated bytes (37.40 GiB) and
49,566,187,520 reserved bytes (46.16 GiB), with 35,608,395,776 bytes (33.16 GiB) of reserved-memory headroom.

The 13:43 eight-GPU allocation consumed approximately 1.83 allocated A100-hours. The monitor establishes that no
GPU was omitted and that all eight reached full utilization; the retained summary does not report time-averaged
utilization, so it should not be used to claim a particular sustained utilization percentage.

## Host-memory evidence and server boundary

The production job requested 512 GiB for the complete server-plus-two-client allocation. The new process-tree and
system monitor collected 129 samples and reported:

- peak process-tree PSS: 143,419,857,920 bytes (133.57 GiB);
- peak process-tree RSS: 146,858,618,880 bytes (136.77 GiB);
- minimum host `MemAvailable`: 1,894,445,584,384 bytes (1,764.34 GiB);
- minimum local-scratch free space: 15,876,148,826,112 bytes (14.44 TiB); and
- no fatal cgroup-event delta reported in the summary.

Allocation-wide cgroup metrics were unavailable on this node, so the reliable scope is the instrumented process
tree plus system-level availability; the empty cgroup counter map cannot independently prove that no cgroup event
occurred. The clean Slurm completion and fatal-pattern scan show no OOM failure. Compared arithmetically with the
512-GiB request, the sampled process-tree RSS peak left about 375.2 GiB, but that is a nominal difference rather
than allocation-wide cgroup or Slurm-accounting headroom. Host `MemAvailable` is not additional memory granted to
this job and must not be treated as permission to exceed the Slurm request.

The two rank-zero client processes reported maximum RSS values of approximately 31.58 and 31.60 GiB, while the
other six ranks were approximately 6.75 GiB each. This asymmetry is consistent with rank zero's explicit full-state
bridge duties, but it does not attribute memory to the separate NVFLARE server.

This monitor still does **not** isolate the server process's peak memory from both client process trees. The exact
server RAM peak therefore cannot be claimed. The server had no GPU and materialized, aggregated, and persisted the
full state; checkpoint size alone is not server RSS because aggregation and serialization may hold additional
copies. A future role-attribution experiment should sample the server PID tree separately, but that missing
attribution is not a reason to rerun this completed qualification.

## Timing and practical bottleneck

The complete Slurm allocation lasted 13:43. Within it, the exact-topology gate took 1:48 and the target production
phase took 9:53. Once both 14B clients were ready, their measured eight-step local rounds took only 24–27 seconds.
The remaining target time was service lifecycle, model loading and distributed initialization, full-state loading
and export, transport, aggregation, persistence, and orderly shutdown.

This result shows that 14B all-parameter computation fits on four A100-80GB GPUs per client with at least 32.1 GiB
of monitored device-memory headroom under this BF16 AdamW and gradient-checkpointing configuration. For repeated
federated rounds, the complete state transfer and server persistence path—not the eight local optimizer steps in
this short test—would require the most immediate design attention.

## Retained evidence

The durable evidence root is:

```text
$PROJECT_ROOT/artifacts/31218631
```

Primary records include:

- `manifest.txt`;
- `qualification.json`;
- `configuration.json`;
- `allocation-start-readiness.json`;
- `dependency-check.json` and `environment.json`;
- `scratch-capacity.json`;
- `services/transport-config.json` and `control-plane.json`;
- `gpu-monitor.json` and `gpu-samples.csv`;
- `allocation-monitor.json` and `allocation-memory.jsonl`;
- `target-identity.json`;
- `gate-1.5b/summary.json`;
- `target-14b-full-model/summary.json`; and
- `target-14b-full-model/persistence/persisted_model.json`.

The retained gate and target participant-log trees provide the underlying server, site-1, and site-2 records used
to construct these summaries.

The source logs are:

```text
$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-14b-full-model-31218631.out
$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-14b-full-model-31218631.err
```

## Qualification conclusion

This run proves, for the pinned software and model revision:

- production NVFLARE orchestration with a TLS server and two required clients;
- concurrent two-client FSDP2 training across all eight allocated A100s;
- all 14.77 billion model parameters participating in the configured optimizer path;
- distinct site-local data consumption, finite losses, and nonzero gradients and sampled updates;
- complete full-state return from both clients;
- 2/2 aggregation and completed full-state persistence;
- measured GPU and whole-process-tree memory with substantial headroom; and
- clean resource release with durable `COMPLETED 0:0` evidence.

It does not establish convergence, useful model quality, multi-round continuity, multi-node networking, exact
server-only memory, FP32-moment capacity, fault tolerance, privacy properties, or scaling of full-model training to
32B or 72B. No rerun is required for this qualification. Any later GPU allocation should answer a new question,
such as multi-round state continuity, isolated server memory, communication reduction, or multi-node behavior.
