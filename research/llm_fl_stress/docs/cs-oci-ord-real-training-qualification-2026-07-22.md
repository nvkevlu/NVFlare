# CS-OCI-ORD real-training qualification — 2026-07-22

This record preserves the evidence behind the
[CS-OCI-ORD real-training runbook](cs-oci-ord-real-training-runbook.md). It separates observed facts from the
repeatable procedure and records failed experiments that materially changed the implementation.

## Qualified scope

- Cluster: CS-OCI-ORD, MARS-managed Slurm on OCI
- Account: `coreai_edgeai_flresearch`
- Execution: one Slurm node, one NVFLARE server, one NVFLARE client, four local torchrun ranks
- GPUs: four NVIDIA A100-SXM4-80GB devices
- Distribution: PyTorch FSDP2, one model shard per rank
- Federated boundary: full BF16 state received/exported by rank zero and synchronized across ranks
- Training: deterministic embedded text, sequence length 128, one local optimizer step, last decoder block trainable
- Persistence: one-client aggregation and raw `FL_global_model.pt` server checkpoint archived in `run.tar`

The result demonstrates real Qwen2.5 model construction, sharding, forward/backward/optimizer work, full-state
NVFLARE exchange, aggregation, and persistence. It does not demonstrate a production dataset, convergence,
multi-client federation, multi-node FSDP, privacy controls, failure recovery, or WAN networking.

## Immutable inputs

| Input | Qualified value |
| --- | --- |
| Code commit for final runs | `a2fa58923ea1dd374b9f705246106f20e58c9833` |
| Container | `nvcr.io/nvidia/pytorch:25.01-py3` |
| Saved image | `pytorch-25.01-py3.sqsh`, approximately 25 GB |
| 1.5B snapshot | `Qwen/Qwen2.5-1.5B@8faed761d45a263340a0528343f099c05c9a4323` |
| 14B snapshot | `Qwen/Qwen2.5-14B@97e1e76335b7017d8f67c08a19d103c0504298c9` |
| PyTorch | `2.12.0+cu126` |
| Torchvision | `0.27.0+cu126` |
| Transformers | `4.57.6` |
| NCCL observed by FSDP2 gate | `2.29.3` |

An initial GPU inspection observed driver `535.129.03`, driver-advertised CUDA `12.2`, and an A100-SXM4-80GB.
The qualified Python environment reports CUDA runtime `12.6`; the containerized CUDA 12.x stack passed the actual
GPU preflight and is compatible with the installed R535 data-center driver.

## Qualification ladder

| Job | Purpose | State / elapsed | Result |
| --- | --- | --- | --- |
| `30568944` | One-GPU interactive hardware check | allocated; approximately 2 min request | A100-SXM4-80GB visible as device 0; `nvidia-smi` passed |
| `30572571` | CPU-only environment construction | `COMPLETED`, 00:12:53 | lock file created; no GPU allocated |
| `30574243` | Initial one-GPU container preflight | `COMPLETED`, 00:01:36 | NVFLARE/PyTorch/CUDA environment `PASS` |
| `30574552` | Four-GPU synthetic FSDP2 gate | `COMPLETED`, 00:01:23 | four A100s, optimizer change, load/export `PASS` |
| `30576208` | First real-model attempt | `FAILED`, 00:01:47 | mismatched generic Torchvision wheel blocked Qwen import |
| `30579635` | Final dependency-aware preflight | `COMPLETED`, 00:01:42 | Qwen class and CUDA Torchvision operator `PASS` |
| `30580188` | Pre-telemetry 1.5B operational run | `COMPLETED`, 00:03:22 | exposed missing fail-closed round evidence; not the final qualification |
| `30582714` | Final 1.5B training gate | `COMPLETED`, 00:03:47 | real step, positive loss/change, full state persisted |
| `30583098` | 14B exchange-only baseline | `COMPLETED`, 00:12:21 | full 29.54 GB state round trip, no optimizer step |
| `30584129` | 14B real training | `COMPLETED`, 00:10:26 | real last-block step, positive loss/change, full state persisted |

An earlier interactive request, job `30568478`, used `srun --immediate=60` and ended with `Requested nodes are busy`.
It did not hold a GPU while waiting beyond that immediate window.

## Four-GPU FSDP2 gate — job 30574552

The synthetic gate tested the distributed bridge before loading a published model:

| Metric | Observed value |
| --- | ---: |
| World size | 4 |
| State tensors | 11 |
| State payload | 20,996,096 bytes |
| Selected parameter change | `5.327165126800537e-07` |
| Peak GPU allocated per rank | 42,429,440 bytes |
| Peak GPU reserved per rank | 94,371,840 bytes |
| Rank RSS | approximately 1.22–1.25 GB |
| Status | `PASS` |

All ranks identified their GPU as NVIDIA A100-SXM4-80GB. This isolated FSDP2 construction, a real optimizer
change, distributed full-state load/export, and NCCL before the larger NVFLARE path was exercised.

## Final 1.5B training gate — job 30582714

| Metric | Observed value |
| --- | ---: |
| Trainable parameters | 46,797,824 |
| Training loss | `5.397667407989502` |
| Selected maximum absolute change | `1.52587890625e-05` |
| Internal state payload | 3,554,176,000 bytes |
| Streamed state bytes | 3,554,202,488 bytes |
| State tensors | 339 |
| Server-to-client transfer | 16.07 s |
| Client-to-server transfer | approximately 20.00 s |
| Distributed round work | 4.530 s |
| Rank-zero load | 0.423 s |
| Other-rank load | approximately 0.126 s |
| Export | approximately 1.581 s |
| Peak GPU allocated per rank | 1,948,413,952 bytes |
| Peak GPU reserved per rank | 2,267,021,312 bytes |
| Rank-zero maximum RSS | 10,387,173,376 bytes |
| Other-rank maximum RSS | approximately 3.98 GB |
| Archived run | approximately 3.4 GB |

The positive finite loss and parameter change prove that this was not an exchange-only or unchanged-model pass.

## 14B exchange-only baseline — job 30583098

| Metric | Observed value |
| --- | ---: |
| Selected trainable-target parameter count | 275,268,608 |
| Training loss / parameter change | `0.0` / `0.0` (expected for exchange-only) |
| Internal state payload | 29,540,067,328 bytes |
| Streamed state bytes | 29,540,115,112 bytes |
| State tensors | 579 |
| Server-to-client transfer | 138.28 s |
| Client-to-server transfer | 136.76 s |
| Server serialization phases | approximately 54.88 s and 53.07 s |
| Distributed round work | 13.445 s |
| Rank-zero load | 3.448 s |
| Other-rank load | approximately 0.406 s |
| Export | approximately 9.794 s |
| Peak GPU allocated per rank | 8,942,152,704 bytes |
| Peak GPU reserved per rank | 10,676,600,832 bytes |
| Rank-zero maximum RSS | 61,213,249,536 bytes |
| Other-rank maximum RSS | approximately 7.247 GB |
| Archived run | approximately 28 GB |

This run established that full 14B state exchange and persistence fit comfortably on the selected node before
adding backward and optimizer memory.

## 14B real training — job 30584129

| Metric | Observed value |
| --- | ---: |
| Trainable parameters | 275,268,608 |
| Training loss | `4.7506103515625` |
| Selected maximum absolute change | `1.52587890625e-05` |
| Internal state payload | 29,540,067,328 bytes |
| Streamed state bytes | 29,540,115,112 bytes |
| State tensors | 579 |
| Server-to-client transfer | 85.94 s |
| Client-to-server transfer | 85.32 s |
| Server serialization phases | approximately 27.44 s and 26.84 s |
| Distributed round work | 10.139 s |
| Rank-zero load | 2.040 s |
| Other-rank load | approximately 0.271 s |
| Export | approximately 5.021 s |
| Peak GPU allocated per rank | 14,999,866,368 bytes |
| Peak GPU reserved per rank | 16,317,939,712 bytes |
| Rank-zero maximum RSS | 62,150,246,400 bytes |
| Other-rank maximum RSS | approximately 7.247 GB |
| Archived run | approximately 28 GB |

NVFLARE aggregated one of one client results and persisted the global model. The positive finite loss and
parameter change, together with the higher GPU memory versus exchange-only, demonstrate the real training path.

The shorter elapsed time and transfer phases relative to exchange-only should not be interpreted as a general
performance guarantee. Shared filesystem caching, node state, and transient load differ between runs. Capacity and
correctness, not benchmark-quality timing, were the objectives.

## Defects found and corrected during qualification

### CUDA Torchvision wheel mismatch

The initial dependency install selected a generic `torchvision==0.27.0` wheel after installing PyTorch from the
CUDA 12.6 index. Import failed at `torchvision::nms`, which Transformers surfaced as an inability to import
`Qwen2ForCausalLM`. The live environment was repaired with the cu126 wheel, and commit `fd66c769` pinned both
PyTorch and Torchvision to matching cu126 builds. The dependency preflight now imports Qwen and checks the compiled
operator.

### Successful outer job could hide a distributed round failure

The first operational 1.5B result created a valid raw `FL_global_model.pt`, but it lacked explicit loss/delta
telemetry. Audit found that a rank error could be caught and converted into unchanged parameters with NaN metrics,
allowing the outer run to appear successful. Commit `a2fa5892` now synchronizes rank outcomes, raises any distributed
error, exits 143 on SIGTERM, and prints one rank-zero `real_training_round` success record only after the model is
sent. The focused real-training tests passed 44 cases after this change.

### Raw persistor output was mistaken for a missing metadata artifact

`PTFileModelPersistor` writes `FL_global_model.pt`; it does not create `FL_global_model.pt.metadata`. The checkpoint
for the first operational run was present at:

```text
./workspace/llm_fsdp2_real_training/server/simulate_job/app_server/FL_global_model.pt
```

The runbook now searches for the raw checkpoint and relies on the round record, server aggregation/persistence,
manifest, archive, and Slurm exit status.

## Resource interpretation

- Rank zero's approximately 62 GB host RSS is expected because it bridges the complete CPU state between NVFLARE
  and FSDP2. Other ranks use roughly 7.25 GB host RSS.
- Training used approximately 15.0 GB allocated and 16.3 GB reserved GPU memory per A100, leaving substantial
  80 GB device headroom for this deliberately narrow one-step, last-block workload.
- Full-state transfer and archive creation dominate much of the elapsed time. Low sampled GPU utilization,
  especially on rank zero or in exchange-only mode, is not evidence that a rank is missing.
- The 28 GB archive is expected because it contains the persisted full BF16 global state and workspace evidence.
- The model is sharded for compute, but the current federated boundary is full-state, so server/rank-zero host RAM,
  serialization, and transfer remain the scaling constraints.

## Reproducibility conclusion

The qualification supports proceeding from synthetic server stress tests to a controlled real 14B NVFLARE/FSDP2
experiment on CS-OCI-ORD. The next scientific step should replace or augment the embedded deterministic batch with
an approved, locally staged dataset and define model-quality metrics. The next systems step, if required, should
qualify more than one real client and account for multiplied full-state transfer/storage costs. Neither extension is
implied by this one-client result.
