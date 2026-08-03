# CS-OCI-ORD single-client 32B full-model capacity qualification — 2026-08-02

## Outcome

Slurm job `31351265` is a **formal capacity-experiment pass** for one eight-rank FSDP2 client training every
parameter of the pinned Qwen2.5-32B BF16 model on one eight-A100-SXM4-80GB CS-OCI-ORD node.

The allocation completed in 14:03 with Slurm state `COMPLETED` and exit code `0:0`. The experiment manifest,
capacity result, GPU monitor, allocation monitor, and top-level qualification all report `PASS`. The reviewed Slurm
stderr contained no traceback, CUDA out-of-memory error, `OutOfMemoryError`, fatal NCCL marker, or `RuntimeError`.

The exact implementation under test was:

- Git commit `fcf2671a05b99ae2c85017ea0be6e0375475e9f2` in a detached, clean release worktree;
- experiment release `2026-08-02-single-client-full-model-32b-v3`;
- pinned Qwen2.5-32B revision `1818d35814b8319459f4bd55ed1ac8709630f003`;
- one client with eight FSDP2 ranks, one rank per allocated A100;
- all 32,763,876,352 parameters trainable and no frozen parameters;
- full-state load and export through `FSDP2StateBridge`;
- six optimizer steps per rank at sequence length 512, covering 48 distinct fixed records; and
- AdamW with BF16 parameters and BF16 moment tensors, `foreach=false`, and `fused=false`.

## Claim boundary

This was intentionally a **single-client, in-process capacity experiment**, not a federated production run. It did
not start an NVFLARE server, use provisioned TLS transport, aggregate multiple clients, or persist a server model.
It therefore proves that one 32B client can train all parameters and exercise the exact NVFLARE FSDP2 full-state
bridge on eight A100s. It does not prove two-client 32B full-model federation, server memory capacity for a 65.53-GB
state, inter-node transport throughput, FedAvg, server persistence, convergence, or model quality.

Those framework behaviors have separate evidence at smaller or sparse payloads. They must not be combined with
this result to claim that the untested two-client 32B full-model topology itself ran.

## Immutable inputs and structural readiness

The wrapper accepted the exact zero-GPU readiness artifact bound to the release worktree, static model result,
model manifest, container manifest, and Python requirements lock. The retained manifest records the readiness
artifact SHA-256 `e08a41c7c4c1d35875085804ef3148f63ab195efe6b8a1f00d9f61ed4f4fe029` and static-result SHA-256
`c67232fbf82a584c7dae578236b09b9b81877fa13697e90473e7c076a28b7602`.

The accepted static contract distinguished the model's logical state from its physical checkpoint:

| Property | Accepted value |
| --- | ---: |
| Safetensor shards | 17 |
| Parameter tensors | 771 |
| Parameters | 32,763,876,352 |
| Parameter dtype | entirely BF16 |
| Logical full state | 65,527,752,704 bytes (61.027 GiB) |
| Physical checkpoint files | 65,527,841,752 bytes (61.028 GiB) |
| Physical-file overhead | 89,048 bytes |

The physical checkpoint size is storage evidence. The logical state size is the correct bridge-payload and
in-memory model-state quantity; the two are not interchangeable.

## Exact execution path

The capacity process performed these operations on all eight ranks:

1. initialized the distributed process group and bound each rank to one A100;
2. loaded the tokenizer and complete Hugging Face model from the staged local-files-only checkpoint;
3. selected and validated all model parameters as trainable BF16 parameters;
4. applied FSDP2 sharding over the 64 decoder layers and root model;
5. exported the initial complete 771-tensor state through `FSDP2StateBridge`;
6. loaded that rank-zero state back through the bridge on all ranks;
7. completed six AdamW optimizer steps per rank on fixed data; and
8. exported and validated the final complete state with an unchanged tensor schema.

The initial export and load are deliberate bridge tests, not a server transfer. Rank zero materialized the full
exported Python state in this process group; no separate NVFLARE server received it.

## Training and optimizer evidence

The result passed fail-closed checks for eight distinct ranks and local ranks 0–7, the expected A100 model name,
exact model coverage, finite training, optimizer creation, and a changed parameter probe.

Measured training evidence includes:

- six finite-loss steps on every rank, for 48 finite rank-step losses in total;
- exactly 48 unique expected sample IDs, with no record reuse;
- final mean loss `6.177677631378174`;
- bounded selected-parameter maximum absolute change `9.1552734375e-05`;
- finite, nonzero gradient probes in early, middle, and late decoder layers; and
- unchanged full-state tensor schema between the initial and final exports.

The update probe is bounded sampling evidence. Its positive result proves that sampled parameters changed, but it
is not a tensor-by-tensor proof that every scalar changed. Six steps over 48 qualification records are sufficient
for capacity and activity evidence; they are not a convergence or quality experiment.

The exact BF16 AdamW moment check reported:

| Optimizer quantity | Measured value |
| --- | ---: |
| Trainable parameters | 32,763,876,352 |
| BF16 moment values | 65,527,752,704 |
| BF16 moment bytes | 131,055,505,408 (122.055 GiB) |

This is exactly two BF16 moment values per trainable parameter across the eight shards. It is evidence for this
BF16 optimizer-state path, not for conventional FP32 Adam moments, FP32 master weights, or a mixed optimizer
implementation with different memory requirements.

## Full-state bridge evidence

Both bridge exports reported exactly 771 tensors and 65,527,752,704 logical bytes. Per-rank timings were tightly
grouped:

- initial full-state export: 8.833–8.869 seconds;
- full-state load: 1.380–1.383 seconds on ranks 1–7 and 3.835 seconds on rank zero; and
- final full-state export: 8.706–8.707 seconds.

The result rejected a changed schema, wrong byte count, wrong tensor count, bridge error, or unchanged dense
training probe. The state remained within one local process group, so these timings do not include NVFLARE
serialization, TLS, network transfer, aggregation, or persistence.

## GPU memory and utilization

All eight GPU indices were observed and active. Each GPU reached 100% utilization in at least one five-second
sample and reached the same monitored peak memory of 53,863 MiB (52.60 GiB), leaving approximately 28,057 MiB
(27.40 GiB) below the nominal 80-GiB device capacity.

Every rank separately reported:

- peak PyTorch allocated memory: 43,844,322,816 bytes (40.833 GiB); and
- peak PyTorch reserved memory: 55,289,315,328 bytes (51.492 GiB).

The difference between the PyTorch allocator peak and `nvidia-smi` process-memory peak is expected because they
measure different scopes and allocator/runtime overhead. The experiment intentionally imposed no arbitrary minimum
GPU-headroom threshold; successful execution and measured headroom are the retained result.

A manual post-run reduction of the raw `gpu-samples.csv` produced:

| GPU | Samples | Mean sampled utilization | Samples above 0% | Peak utilization |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 155 | 3.6% | 138 | 100% |
| 1 | 155 | 4.7% | 138 | 100% |
| 2 | 155 | 4.9% | 138 | 100% |
| 3 | 155 | 4.8% | 138 | 100% |
| 4 | 155 | 5.0% | 137 | 100% |
| 5 | 155 | 5.1% | 139 | 100% |
| 6 | 155 | 4.6% | 138 | 100% |
| 7 | 155 | 4.6% | 138 | 100% |

These are unweighted means of five-second `nvidia-smi` samples over the complete monitored child lifetime, including
checkpoint loading and initialization. They prove low sampled fleet utilization despite activity on all eight GPUs.
They are not kernel-level occupancy, step-only utilization, or a throughput benchmark.

The official telemetry analyzer subsequently validated all 1,240 GPU rows, with zero rejected rows and zero
duplicate GPU/timestamp records, and reconstructed 155 complete eight-GPU snapshots. It reported:

- fleet mean sampled utilization: `4.683870967741935%`;
- median snapshot mean utilization: `1.0%`;
- 95th-percentile snapshot mean utilization: `3.8%`;
- fraction of snapshots with all eight GPUs active: `0.8709677419354839`;
- peak concurrent memory across all eight devices: 430,904 MiB; and
- per-device peak memory 53,863 MiB and peak utilization 100% on every GPU.

The 430,904-MiB value is the sum across eight concurrently sampled devices, not memory on one GPU. The analyzer
marks a sampled GPU average as a supported claim. It explicitly does not support a continuous-time average or
phase attribution, so the sampled statistics must not be generalized beyond their five-second observation cadence
or assigned specifically to loading, training, or bridge phases.

## Timing and the replicated-loading bottleneck

The Slurm allocation lasted 843 seconds. The monitored capacity child lasted 775.153 seconds. Its two broad timing
regions were:

| Region | Maximum measured duration | Share of monitored child |
| --- | ---: | ---: |
| Model-ready phase | 664.983 s (11:05) | 85.8% |
| Post-ready bridge, training, and validation work | 38.381 s | 5.0% |

The remaining child time and the difference from the Slurm allocation cover distributed launch, static checks,
monitor startup, result collection, container/Slurm lifecycle, and cleanup. These categories were not separately
instrumented and should not be assigned invented durations.

The 664.983-second value is measured as **model readiness**, not as pure filesystem I/O. It includes tokenizer and
model construction, checkpoint deserialization, exact parameter/dtype validation, and FSDP2 sharding. However, the
checked-in execution order identifies a concrete replicated-loading bottleneck: every one of the eight ranks calls
`AutoModelForCausalLM.from_pretrained(..., low_cpu_mem_usage=True)` on the complete 17-shard checkpoint **before**
`fully_shard()` is applied. Therefore every rank independently visits the complete 65.53-GB physical checkpoint.

Eight complete logical passes correspond to as much as 524.22 decimal GB of checkpoint-file demand at the
process level. That is not a measurement of 524.22 GB read from Lustre: page cache, client cache, and storage-layer
behavior were not instrumented and can reduce backend traffic. Nor can the current telemetry split checkpoint I/O
from CPU deserialization, model construction, validation, or FSDP collectives. The defensible conclusion is that
replicated pre-shard loading is structurally present and that the combined model-ready phase dominated the run.

Only six short optimizer steps followed readiness, so useful GPU computation could not amortize the 11-minute
startup. The low mean utilization is therefore consistent with a capacity test dominated by replicated checkpoint
loading and initialization. It does not indicate that training or bridge operations were skipped.

The next engineering experiment, if pursued, should first replace replicated pre-shard loading with a rank-aware
or meta-device/sharded loading path, then run enough local steps to measure steady-state throughput. Repeating this
exact workload unchanged would primarily remeasure the already-identified startup bottleneck.

## Host memory and scratch evidence

The job requested 900 GiB of host memory. The allocation monitor collected 149 samples and reported:

- peak process-tree PSS: 73,472,503,808 bytes (68.427 GiB);
- peak process-tree RSS: 75,648,450,560 bytes (70.453 GiB);
- minimum system `MemAvailable`: 2,010,485,141,504 bytes (1,872.410 GiB);
- minimum local-scratch free space: 18,900,127,490,048 bytes (17.19 TiB); and
- zero `max`, `oom`, and `oom_kill` placeholders in the allocation-monitor summary.

The official analyzer accepted all 149 allocation samples and reported zero rejected samples. Across those samples,
mean process-tree RSS was 38,012,593,145.12752 bytes, while the peak RSS, peak PSS, minimum system availability,
and minimum scratch space exactly matched the values above.

Allocation-wide cgroup metrics were unavailable, so the reliable memory scope is the monitored process tree plus
system-wide availability. This was the analyzer's only warning: unavailable allocation-wide cgroup metrics and
their zero placeholders are not evidence about allocation-wide OOM behavior. The clean exit and error scan show no
observed OOM failure, but subtracting the process-tree RSS from the 900-GiB request is not an allocation-wide cgroup
headroom measurement. Likewise, system `MemAvailable` is not memory granted to this job and must not be treated as
permission to exceed the Slurm request.

There was no NVFLARE server in this experiment. The manifest's `server_state_copies=1` and host projection fields
are report-only planning inputs, not evidence that a server process or server copy existed. This run therefore adds
no isolated server-RAM measurement.

## Timeout and allocation behavior

The wrapper recorded 7,193 seconds remaining at its allocation check, against a 6,900-second minimum. It used a
10,800-second distributed collective timeout, a two-hour Slurm limit, `TERM` five minutes before the wall, and no
automatic requeue.

Both application elapsed cutoffs were explicitly disabled:

- `max_model_ready_seconds=0`; and
- `max_work_seconds=0`.

The 665-second healthy initialization therefore was not stopped by an arbitrary application deadline. The job
finished normally well before the scheduler wall and released the node. Its 14:03 allocation consumed approximately
1.87 allocated A100-hours.

## Retained evidence

The durable evidence root is:

```text
$PROJECT_ROOT/artifacts/32b-full-model-single-client-31351265
```

Primary records include:

- `manifest.txt`;
- `qualification.json`;
- `configuration.json`;
- `dependency-check.json`;
- `static-model-preflight.json`;
- `capacity-experiment.json`;
- `gpu-monitor.json` and `gpu-samples.csv`;
- `allocation-monitor.json` and `allocation-memory.jsonl`;
- `telemetry-analysis.json`.

The corresponding Slurm output is:

```text
$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-32b-single-client-31351265.{out,err}
```

The official analyzer artifact is retained at:

```text
$PROJECT_ROOT/artifacts/32b-full-model-single-client-31351265/telemetry-analysis.json
```

It reports top-level `status=PASS`, `qualification_status=PASS`, an empty error list, the single cgroup-scope warning
described above, and all 22 consistency checks as `PASS`. Its claim-support matrix accepts sampled GPU averages and
rejects allocation-wide cgroup, server-only memory, phase attribution, and continuous-time average claims. No
telemetry-analysis JSON SHA-256 was printed during closure, so none is asserted here.

## Qualification conclusion

Job `31351265` proves that, with this exact BF16 AdamW implementation:

- one Qwen2.5-32B client fits and trains all parameters across eight A100-SXM4-80GB GPUs;
- all eight ranks complete six finite optimizer steps over 48 distinct records;
- exact BF16 optimizer moments are materialized for every trainable parameter;
- the NVFLARE FSDP2 bridge loads and exports the complete 771-tensor, 65.53-GB logical state;
- sampled parameters change and representative gradients are finite and nonzero;
- all eight GPUs are active with approximately 27.4 GiB of monitored device-memory headroom; and
- the workload exits cleanly without an observed GPU or host OOM condition.

It also establishes a practical limitation: the current replicated pre-shard Hugging Face loading path makes the
11:05 model-ready phase dominate a six-step workload, producing only 3.6–5.1% mean utilization over the monitored
child despite 100% peaks on every GPU.

No unchanged rerun is required. This qualification should be retained as the completed 32B full-model capacity
result; any future GPU allocation should answer a new question, such as sharded-loader efficiency, sustained
training throughput, multi-client 32B server/transport capacity, FP32 optimizer-state cost, or model quality.
