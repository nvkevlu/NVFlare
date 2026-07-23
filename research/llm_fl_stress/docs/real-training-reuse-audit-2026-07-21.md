# Real GPU Training Reuse Audit

## Conclusion

The repository already contains most of the generic federated and distributed
training plumbing needed for a real-model client. A new implementation should
reuse the Client API rank contract, external `torchrun` launch, Hugging Face
training examples, Qwen rank coordination, and the existing Slurm wrapper.

The feature worktree now contains an FSDP2-specific NVFlare state bridge in
`nvflare/app_opt/pt/fsdp2_state_bridge.py`. It implements the narrow boundary
that was missing from the repository:

1. Load the full NVFlare state into an FSDP model without broadcasting a full
   application object to every rank.
2. Gather a CPU full state on rank zero after training without creating full
   copies on every rank.
3. Return explicit state size and duration telemetry to the client so it can
   retain the rank-zero export through the FLARE send and then release it
   deterministically.

At the time of this audit, the remaining work was client integration: connect
this bridge to rank-zero Client API receive/send, the selected Hugging Face
training loop, and explicit post-send cleanup. That integration and the
four-A100 14B gate subsequently passed on CS-OCI-ORD. See the operational
[runbook](cs-oci-ord-real-training-runbook.md) and dated
[qualification record](cs-oci-ord-real-training-qualification-2026-07-22.md).

## Existing Building Blocks

| Requirement | Existing implementation | Reuse assessment |
| --- | --- | --- |
| Real Hugging Face construction | `examples/advanced/llm_hf/client.py` and `examples/advanced/qwen3-vl` load real pretrained models | Reuse directly with the selected model class and pinned revision |
| Tokenization and datasets | HF SFT loads JSON datasets; Qwen3-VL includes model-specific multimodal preprocessing | Reuse or simplify to a tiny fixed text dataset for the first gate |
| Forward/backward/optimizer | HF `SFTTrainer`, Qwen trainer, DDP CIFAR example, and BioNeMo all run real optimization | Reuse framework training loops rather than writing a trainer from scratch |
| Multi-process launch | `PTMultiProcessExecutor`, `ClientAPIExecutor(external_process)`, and recipes launch `torchrun` | Reuse; NVFlare should not reimplement inter-rank communication |
| Rank-zero NVFlare control | Client API uses global `RANK`; the torchrun integration test and Qwen client broadcast control state from rank zero | Reuse the contract and error/stop propagation pattern |
| Generic distributed model sharing | DDP examples use broadcast or shared checkpoints; Lightning uses `trainer.strategy.broadcast` | Reuse only for control metadata; a 60 GiB full model needs an FSDP-aware state path |
| Multi-node Slurm | `examples/advanced/llm_hf/client_wrapper.sh`, `nvflare.slurm`, and `MULTINODE.md` implement `srun` plus `torchrun` | Reuse and adapt to the leased site's scheduler |
| Pyxis | No repository implementation found | Add only when the target cluster requires containerized Slurm execution |
| Training metrics | HF reports evaluation loss and W&B/TensorBoard; Qwen has experiment tracking but currently sends `NaN` loss | Reuse logging, then add deterministic loss/parameter-change assertions |
| FSDP load/gather | No implementation found | New focused adapter and tests required |

## How Existing Large Projects Handle It

### Hugging Face LLM SFT

`examples/advanced/llm_hf` performs real SFT/PEFT with Hugging Face and supports
multi-node Slurm. It uses DDP-style replication: each rank constructs a complete
model, rank zero communicates with NVFlare, and shared checkpoints coordinate
round state. This solves orchestration and rank ownership but does not solve
32B full-model GPU memory.

### Qwen3-VL

`examples/advanced/qwen3-vl` is the closest reusable client implementation. It:

- launches each client with `torchrun`;
- restricts Client API calls to global rank zero;
- broadcasts running state, round state, and failures;
- converts received FL parameters to a Hugging Face checkpoint for multi-rank
  training;
- loads the trained checkpoint on rank zero and sends it to NVFlare; and
- optionally exchanges only LoRA adapters.

Its multi-rank full-model path is still DDP/checkpoint based. The training
export helper calls ordinary `model.state_dict()` and moves every value to CPU,
so it is not an FSDP rank-zero full-state gather.

### BioNeMo/NeMo

The BioNeMo example delegates large-model parallelism and distributed optimizer
state to NeMo/Megatron, then uses `flare.patch(trainer)` for the FL boundary.
This is the other common pattern: let the training framework own sharding and
teach the NVFlare boundary how to import/export the framework's model state.
It demonstrates that NVFlare does not need to own the distributed optimizer.

### PyTorch Lightning

The Lightning integration already receives on rank zero and broadcasts through
the trainer strategy. Its current send path uses
`pl_module.cpu().state_dict()`, however, and is not a demonstrated FSDP
full-state export. It is useful infrastructure but not a drop-in FSDP solution.

## Revised Implementation Scope

The earlier list overstated the amount of new work. The revised scope is:

| Work item | Status |
| --- | --- |
| Hugging Face model, tokenizer, and dataset | Existing; adapt |
| Forward/backward/optimizer and mixed precision | Existing; configure |
| `torchrun`, NCCL, rank ownership, stop/error propagation | Existing; reuse |
| Slurm multi-node wrapper | Existing; adapt |
| FSDP wrapping policy and mixed precision | Implemented for Qwen2/Qwen2.5 decoder blocks |
| NVFlare full state to FSDP load | Implemented and tested locally in the FSDP2 state bridge |
| FSDP rank-zero CPU full-state gather to NVFlare | Implemented and tested locally in the FSDP2 state bridge |
| Memory-safe lifecycle around gather/send | Implemented; client retains rank-zero export through send, then cleans round memory |
| Deterministic correctness and GPU-memory metrics | Implemented with fail-closed per-rank round telemetry |
| Pyxis/Enroot integration | Implemented for CS-OCI-ORD Slurm jobs |

## Recommended Prototype

Start from the Qwen3-VL rank-control pattern but use a small text-only Hugging
Face model and one client with two GPUs:

1. Run one tiny FSDP training step.
2. Receive the full PyTorch state only on rank zero.
3. Load it through the FSDP full-state API with CPU offload enabled.
4. Verify every rank starts from the same sentinel parameter.
5. Train and verify loss is finite and one selected parameter changes.
6. Gather a rank-zero-only CPU full state and send it through NVFlare.
7. Record per-rank GPU peak, rank-zero CPU RSS, gather duration, and transfer
   duration.

Once this passes at 1B--3B, scale the same adapter to 14B and then 32B. LoRA is
an easier real-training milestone but does not validate the full-state server
path because it exchanges a much smaller payload.

## Bridge Verification and Completed GPU Gate

The local bridge gate is complete:

- 12 focused unit tests cover process-group and FSDP2 enforcement, rank-zero
  ownership, strict wrapper-prefix conversion, CPU-only full states,
  synchronized validation failures, full-state options, and telemetry.
- A real two-rank CPU/Gloo integration test applies `fully_shard` bottom-up,
  loads a full state supplied only on rank zero, and gathers an identical CPU
  full state only on rank zero.
- The full `tests/unit_test/app_opt/pt` area passes with the bridge included.

The planned GPU ladder is now complete. The four-rank NCCL bridge gate passed,
followed by a 1.5B real-training gate, a 14B exchange-only memory baseline, and
a 14B real forward/backward/optimizer round. The final 14B run reported a finite
loss, positive known-parameter change, per-rank GPU/RSS telemetry, a complete
29.54 GB full-state round trip, one-of-one server aggregation, and persisted
global state. Exact jobs, timings, and memory measurements are preserved in the
[July 22 qualification record](cs-oci-ord-real-training-qualification-2026-07-22.md).

## Evidence Paths

- Client API global-rank contract: `nvflare/client/api.py`
- External trainer command and lifecycle: `nvflare/app_common/executors/client_api_executor.py`
- PyTorch torchrun launcher: `nvflare/app_opt/pt/multi_process_executor.py`
- Torchrun rank-zero integration test: `tests/integration_test/data/jobs/pt_client_api_torchrun_cpu`
- Multi-GPU DDP example: `examples/docker/jobs/pt-ddp-docker`
- Hugging Face multi-node example: `examples/advanced/llm_hf`
- Qwen distributed client: `examples/advanced/qwen3-vl/client.py`
- Qwen state export: `examples/advanced/qwen3-vl/qwenvl/train/train_qwen.py`
- Lightning rank integration: `nvflare/app_opt/lightning/api.py`
- BioNeMo trainer integration: `examples/tutorials/self-paced-training/part-5_federated_learning_applications_in_industries/chapter-11_federated_learning_in_healthcare_lifescience/11.2_drug_discovery/11.2.1_drug_discovery_bionemo`
- Multi-process/HPC design contract: `docs/design/client_api_execution_modes.md`
- FSDP2 full-state bridge: `nvflare/app_opt/pt/fsdp2_state_bridge.py`
- FSDP2 unit coverage: `tests/unit_test/app_opt/pt/fsdp2_state_bridge_test.py`
- FSDP2 two-rank collective coverage: `tests/integration_test/fsdp2_state_bridge_test.py`
