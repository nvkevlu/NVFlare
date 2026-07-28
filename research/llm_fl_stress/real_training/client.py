# Copyright (c) 2026, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""One-client, multi-GPU Hugging Face/FSDP2 NVFLARE training worker.

This script is launched once by NVFLARE through ``torchrun``. Every process
owns one FSDP2 shard. Only global rank zero calls NVFLARE receive/send, and the
FSDP2 state bridge transfers the configured CPU state directly between rank
zero and the distributed model shards.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import signal
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

import torch
import torch.distributed as dist
from torch.distributed.device_mesh import init_device_mesh
from torch.distributed.fsdp import MixedPrecisionPolicy, fully_shard
from transformers import AutoModelForCausalLM, AutoTokenizer

import nvflare.client as flare
from nvflare.app_opt.pt.fsdp2_state_bridge import FSDP2StateBridge

try:
    from .state_evidence import file_sha256, load_text_partition, select_partition_record, tensor_state_summary
except ImportError:
    custom_root = Path(__file__).resolve().parents[3]
    if str(custom_root) not in sys.path:
        sys.path.insert(0, str(custom_root))
    from state_evidence import file_sha256, load_text_partition, select_partition_record, tensor_state_summary

_TRAINING_TEXT = (
    "Federated learning keeps training data at each participating site.",
    "Fully sharded data parallel training divides model parameters across accelerators.",
    "A short deterministic qualification step can validate gradients and model exchange.",
    "Reliable distributed systems report failures and resource usage with enough context to diagnose them.",
)
_TRAINABLE_TARGETS = ("last-layer", "lm-head", "all")
_RUN_MODES = ("exchange-only", "train")
_STATE_SCOPES = ("full", "trainable")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name-or-path", required=True)
    parser.add_argument("--model-revision", default=None)
    parser.add_argument("--local-steps", type=int, default=1)
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1.0e-5)
    parser.add_argument("--trainable-target", choices=_TRAINABLE_TARGETS, default="last-layer")
    parser.add_argument("--run-mode", choices=_RUN_MODES, default="train")
    parser.add_argument("--state-scope", choices=_STATE_SCOPES, default="full")
    parser.add_argument("--dataset-file", default=None)
    parser.add_argument("--dataset-sha256", default=None)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    if not os.path.isabs(args.model_name_or_path):
        raise ValueError("--model-name-or-path must be an absolute local path")
    if not os.path.isdir(args.model_name_or_path):
        raise ValueError(f"model directory does not exist: {args.model_name_or_path}")
    for name in ("local_steps", "max_length", "timeout_seconds"):
        if getattr(args, name) <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be greater than zero")
    if args.learning_rate <= 0:
        raise ValueError("--learning-rate must be greater than zero")
    state_scope = getattr(args, "state_scope", "full")
    if state_scope == "trainable":
        if getattr(args, "trainable_target", "last-layer") != "last-layer":
            raise ValueError("--state-scope=trainable requires --trainable-target=last-layer")
        if getattr(args, "run_mode", "train") != "train":
            raise ValueError("--state-scope=trainable requires --run-mode=train")
        if not getattr(args, "dataset_file", None):
            raise ValueError("--state-scope=trainable requires --dataset-file")


def _setup_distributed(timeout_seconds: int) -> tuple[int, int, int, torch.device]:
    if "RANK" not in os.environ or "WORLD_SIZE" not in os.environ or "LOCAL_RANK" not in os.environ:
        raise RuntimeError("client must be launched by torchrun")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the real-training client")

    local_rank = int(os.environ["LOCAL_RANK"])
    torch.cuda.set_device(local_rank)
    dist.init_process_group("nccl", timeout=timedelta(seconds=timeout_seconds))
    rank = dist.get_rank()
    world_size = dist.get_world_size()
    if world_size < 2:
        raise RuntimeError("FSDP2 real-training qualification requires at least two ranks")
    if world_size > torch.cuda.device_count():
        raise RuntimeError(f"world size {world_size} exceeds visible CUDA devices {torch.cuda.device_count()}")
    return rank, world_size, local_rank, torch.device("cuda", local_rank)


def _decoder_layers(model: torch.nn.Module) -> torch.nn.ModuleList:
    """Return decoder blocks for Qwen2/Llama-like causal language models."""

    base = getattr(model, "model", None)
    layers = getattr(base, "layers", None)
    if not isinstance(layers, torch.nn.ModuleList) or not layers:
        model_type = getattr(getattr(model, "config", None), "model_type", type(model).__name__)
        raise RuntimeError(
            f"unsupported model architecture {model_type!r}: expected a non-empty model.layers ModuleList"
        )
    return layers


def _select_trainable_parameters(model: torch.nn.Module, target: str) -> list[torch.nn.Parameter]:
    for param in model.parameters():
        param.requires_grad_(False)

    if target == "all":
        selected_modules = [model]
    elif target == "last-layer":
        selected_modules = [_decoder_layers(model)[-1]]
    elif target == "lm-head":
        output_embeddings = model.get_output_embeddings()
        if output_embeddings is None:
            raise RuntimeError("model does not expose output embeddings for --trainable-target=lm-head")
        selected_modules = [output_embeddings]
    else:
        raise ValueError(f"unknown trainable target: {target}")

    for module in selected_modules:
        for param in module.parameters():
            param.requires_grad_(True)
    trainable = [param for param in model.parameters() if param.requires_grad]
    if not trainable:
        raise RuntimeError(f"trainable target {target!r} selected no parameters")
    return trainable


def _shard_model(model: torch.nn.Module, world_size: int) -> None:
    mesh = init_device_mesh("cuda", (world_size,))
    mp_policy = MixedPrecisionPolicy(param_dtype=torch.bfloat16, reduce_dtype=torch.float32)
    for layer in _decoder_layers(model):
        fully_shard(layer, mesh=mesh, mp_policy=mp_policy)
    fully_shard(model, mesh=mesh, mp_policy=mp_policy)


def _load_model_and_tokenizer(args: argparse.Namespace) -> tuple[torch.nn.Module, Any]:
    common = {
        "revision": args.model_revision,
        "local_files_only": True,
        "trust_remote_code": False,
    }
    tokenizer = AutoTokenizer.from_pretrained(args.model_name_or_path, **common)
    if tokenizer.pad_token_id is None:
        if tokenizer.eos_token_id is None:
            raise RuntimeError("tokenizer has neither a pad token nor an EOS token")
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        args.model_name_or_path,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        **common,
    )
    model.config.use_cache = False
    if args.trainable_target == "all" and hasattr(model, "gradient_checkpointing_enable"):
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    return model, tokenizer


def _local_tensor(param: torch.nn.Parameter) -> torch.Tensor:
    value = param.to_local() if hasattr(param, "to_local") else param
    return value.detach()


def _snapshot_trainable(trainable: list[torch.nn.Parameter]) -> list[torch.Tensor]:
    return [_local_tensor(param).float().clone() for param in trainable]


def _global_max_change(trainable: list[torch.nn.Parameter], before: list[torch.Tensor], device: torch.device) -> float:
    local_max = torch.zeros((), dtype=torch.float32, device=device)
    for param, original in zip(trainable, before):
        current = _local_tensor(param).float()
        if current.numel():
            local_max = torch.maximum(local_max, (current - original).abs().max())
    dist.all_reduce(local_max, op=dist.ReduceOp.MAX)
    return float(local_max.item())


def _training_text(site_name: str, rank: int) -> str:
    local_text = _TRAINING_TEXT[rank % len(_TRAINING_TEXT)]
    return f"Deterministic local partition for federated client {site_name}. {local_text}"


def _make_batch(
    tokenizer: Any,
    max_length: int,
    device: torch.device,
    text: str,
) -> dict[str, torch.Tensor]:
    encoded = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        padding="max_length",
        max_length=max_length,
    )
    input_ids = encoded["input_ids"].to(device)
    attention_mask = encoded["attention_mask"].to(device)
    labels = input_ids.clone()
    labels[attention_mask == 0] = -100
    return {"input_ids": input_ids, "attention_mask": attention_mask, "labels": labels}


def _train_round(
    model: torch.nn.Module,
    tokenizer: Any,
    trainable: list[torch.nn.Parameter],
    args: argparse.Namespace,
    rank: int,
    world_size: int,
    device: torch.device,
    site_name: str,
    current_round: int,
    dataset_records: list[dict[str, str]] | None,
) -> tuple[float, float, list[float], list[str]]:
    model.train()
    prep_error = None
    before = None
    optimizer = None
    try:
        before = _snapshot_trainable(trainable)
        optimizer = torch.optim.AdamW(trainable, lr=args.learning_rate)
    except Exception as exc:
        prep_error = f"rank {rank} training setup: {type(exc).__name__}: {exc}"
    prep_error = _collect_first_error(prep_error)
    if prep_error:
        raise RuntimeError(prep_error)
    if before is None or optimizer is None:
        raise RuntimeError("training setup completed without required objects")

    last_loss = None
    loss_trajectory = []
    sample_ids = []

    for local_step in range(args.local_steps):
        if dataset_records is None:
            record = {"id": f"{site_name}-rank-{rank}", "text": _training_text(site_name, rank)}
        else:
            record = select_partition_record(
                dataset_records,
                current_round=current_round,
                local_step=local_step,
                rank=rank,
                world_size=world_size,
                local_steps=args.local_steps,
            )
        batch = _make_batch(tokenizer, args.max_length, device, record["text"])
        optimizer.zero_grad(set_to_none=True)
        output = model(**batch)
        loss = output.loss.float()
        finite = torch.isfinite(loss).to(dtype=torch.int32)
        dist.all_reduce(finite, op=dist.ReduceOp.MIN)
        if not finite.item():
            raise RuntimeError("at least one rank produced a non-finite loss")
        loss.backward()
        optimizer.step()
        last_loss = loss.detach()
        loss_sum = last_loss.clone()
        dist.all_reduce(loss_sum, op=dist.ReduceOp.SUM)
        loss_trajectory.append(float((loss_sum / world_size).item()))
        sample_ids.append(record["id"])
        del batch

    if last_loss is None:
        raise RuntimeError("training completed without a loss")
    mean_loss = loss_trajectory[-1]
    max_change = _global_max_change(trainable, before, device)
    if max_change <= 0.0:
        raise RuntimeError("optimizer step did not change any selected parameter shard")
    optimizer.zero_grad(set_to_none=True)
    del optimizer, before
    return mean_loss, max_change, loss_trajectory, sample_ids


def _broadcast_rank_zero(value: Any, rank: int) -> Any:
    values = [value if rank == 0 else None]
    dist.broadcast_object_list(values, src=0)
    return values[0]


def _collect_first_error(local_error: Optional[str]) -> Optional[str]:
    errors = [None for _ in range(dist.get_world_size())]
    dist.all_gather_object(errors, local_error)
    return next((error for error in errors if error), None)


def _max_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _round_metrics(
    rank: int,
    local_rank: int,
    device: torch.device,
    loss: float,
    max_change: float,
    load_seconds: float,
    export_seconds: float,
    loss_trajectory: list[float],
    sample_ids: list[str],
) -> tuple[dict[str, Any], Optional[list[dict[str, Any]]]]:
    local = {
        "rank": rank,
        "local_rank": local_rank,
        "loss": loss,
        "selected_max_abs_change": max_change,
        "load_seconds": load_seconds,
        "export_seconds": export_seconds,
        "max_rss_bytes": _max_rss_bytes(),
        "peak_gpu_allocated_bytes": torch.cuda.max_memory_allocated(device),
        "peak_gpu_reserved_bytes": torch.cuda.max_memory_reserved(device),
        "gpu_name": torch.cuda.get_device_name(device),
        "loss_trajectory": loss_trajectory,
        "sample_ids": sample_ids,
    }
    gathered = [None for _ in range(dist.get_world_size())] if rank == 0 else None
    dist.gather_object(local, gathered, dst=0)
    metrics = {
        "loss": loss,
        "neg_loss": -loss,
        "selected_max_abs_change": max_change,
        "load_seconds": load_seconds,
        "export_seconds": export_seconds,
    }
    return metrics, gathered


def _require_round_success(round_error: Optional[str]) -> None:
    if round_error:
        raise RuntimeError(f"distributed round failed: {round_error}")


def _make_round_summary(
    current_round: int,
    site_name: str,
    args: argparse.Namespace,
    world_size: int,
    metrics: dict[str, Any],
    rank_metrics: list[dict[str, Any]],
    payload_bytes: int,
    tensor_count: int,
    round_seconds: float,
    *,
    input_state: dict[str, Any] | None = None,
    output_state: dict[str, Any] | None = None,
    dataset_sha256: str | None = None,
) -> dict[str, Any]:
    summary = {
        "event": "real_training_round",
        "status": "PASS",
        "current_round": current_round,
        "site_name": site_name,
        "model_path": args.model_name_or_path,
        "model_revision": args.model_revision,
        "run_mode": args.run_mode,
        "state_scope": getattr(args, "state_scope", "full"),
        "trainable_target": args.trainable_target,
        "local_steps": args.local_steps,
        "world_size": world_size,
        "loss": metrics["loss"],
        "selected_max_abs_change": metrics["selected_max_abs_change"],
        "load_seconds": metrics["load_seconds"],
        "export_seconds": metrics["export_seconds"],
        "payload_bytes": payload_bytes,
        "tensor_count": tensor_count,
        "round_seconds": round_seconds,
        "ranks": rank_metrics,
    }
    if input_state is not None:
        summary["input_state"] = input_state
    if output_state is not None:
        summary["output_state"] = output_state
    if dataset_sha256 is not None:
        summary["dataset_sha256"] = dataset_sha256
        summary["loss_trajectory"] = rank_metrics[0]["loss_trajectory"]
        summary["sample_ids"] = sorted(
            sample_id for rank_record in rank_metrics for sample_id in rank_record["sample_ids"]
        )
    return summary


def _resolve_dataset(args: argparse.Namespace) -> tuple[list[dict[str, str]] | None, str | None]:
    dataset_file = getattr(args, "dataset_file", None)
    if not dataset_file:
        return None, None
    path = Path(dataset_file)
    if not path.is_absolute():
        candidates = [
            Path(__file__).resolve().parent / path,
            Path(__file__).resolve().parents[3] / path,
        ]
        path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    records = load_text_partition(path, expected_sha256=getattr(args, "dataset_sha256", None))
    return records, file_sha256(path)


def _free_round_memory(device: torch.device) -> None:
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)


def _run(args: argparse.Namespace) -> None:
    rank, world_size, local_rank, device = _setup_distributed(args.timeout_seconds)
    try:
        model, tokenizer = _load_model_and_tokenizer(args)
        dataset_records, dataset_sha256 = _resolve_dataset(args)
        _select_trainable_parameters(model, args.trainable_target)
        _shard_model(model, world_size)
        # fully_shard may replace registered Parameter objects with DTensor
        # parameters, so collect optimizer references only after sharding.
        trainable = [param for param in model.parameters() if param.requires_grad]
        if not trainable:
            raise RuntimeError("FSDP2 sharding left no trainable parameters")
        bridge = FSDP2StateBridge(model, exchange_prefix="model.")
        flare.init(rank=rank)
        site_name = _broadcast_rank_zero(flare.get_site_name() if rank == 0 else None, rank)
        if not isinstance(site_name, str) or not site_name:
            raise RuntimeError(f"rank zero did not provide a valid site name: {site_name!r}")

        if rank == 0:
            summary = {
                "event": "real_training_client_ready",
                "site_name": site_name,
                "world_size": world_size,
                "model_path": args.model_name_or_path,
                "trainable_target": args.trainable_target,
                "run_mode": args.run_mode,
                "state_scope": getattr(args, "state_scope", "full"),
                "trainable_parameters": sum(param.numel() for param in trainable),
                "dataset_sha256": dataset_sha256,
            }
            print(json.dumps(summary, sort_keys=True), flush=True)

        while _broadcast_rank_zero(flare.is_running() if rank == 0 else None, rank):
            input_model = flare.receive() if rank == 0 else None
            should_continue = _broadcast_rank_zero(input_model is not None if rank == 0 else None, rank)
            if not should_continue:
                break

            current_round = _broadcast_rank_zero(input_model.current_round if rank == 0 else None, rank)
            received_params = input_model.params if rank == 0 else None
            torch.cuda.reset_peak_memory_stats(device)
            load_result = None
            export_result = None
            input_state = None
            output_state = None
            loss = float("nan")
            max_change = 0.0
            loss_trajectory: list[float] = []
            sample_ids: list[str] = []
            started_at = time.perf_counter()

            load_error = None
            try:
                if rank == 0 and getattr(args, "state_scope", "full") == "trainable":
                    input_state = tensor_state_summary(received_params)
                if getattr(args, "state_scope", "full") == "trainable":
                    load_result = bridge.load_trainable_state_dict(received_params)
                else:
                    load_result = bridge.load_full_state_dict(received_params)
            except Exception as exc:
                load_error = f"rank {rank} load: {type(exc).__name__}: {exc}"
            round_error = _collect_first_error(load_error)

            if not round_error:
                train_error = None
                try:
                    if args.run_mode == "train":
                        loss, max_change, loss_trajectory, sample_ids = _train_round(
                            model,
                            tokenizer,
                            trainable,
                            args,
                            rank,
                            world_size,
                            device,
                            site_name,
                            current_round,
                            dataset_records,
                        )
                    else:
                        loss, max_change = 0.0, 0.0
                except Exception as exc:
                    train_error = f"rank {rank} train: {type(exc).__name__}: {exc}"
                round_error = _collect_first_error(train_error)

            if not round_error:
                export_error = None
                try:
                    if getattr(args, "state_scope", "full") == "trainable":
                        export_result = bridge.export_trainable_state_dict()
                    else:
                        export_result = bridge.export_full_state_dict()
                    if rank == 0 and getattr(args, "state_scope", "full") == "trainable":
                        output_state = tensor_state_summary(export_result.state_dict)
                except Exception as exc:
                    export_error = f"rank {rank} export: {type(exc).__name__}: {exc}"
                round_error = _collect_first_error(export_error)

            if not round_error:
                result_error = None
                if load_result is None:
                    result_error = f"rank {rank} did not receive a state bridge load result"
                elif export_result is None:
                    result_error = f"rank {rank} did not receive a state bridge export result"
                elif rank == 0 and export_result.state_dict is None:
                    result_error = "rank zero did not receive an exported full state dict"
                round_error = _collect_first_error(result_error)
            _require_round_success(round_error)

            metrics, rank_metrics = _round_metrics(
                rank,
                local_rank,
                device,
                loss,
                max_change,
                load_result.stats.duration_seconds,
                export_result.stats.duration_seconds,
                loss_trajectory,
                sample_ids,
            )
            if rank == 0:
                assert rank_metrics is not None
                params = export_result.state_dict
                round_seconds = time.perf_counter() - started_at
                meta = {
                    "CURRENT_ROUND": current_round,
                    "NUM_STEPS_CURRENT_ROUND": args.local_steps,
                    "PAYLOAD_BYTES": export_result.stats.payload_bytes,
                    "TENSOR_COUNT": export_result.stats.tensor_count,
                    "ROUND_SECONDS": round_seconds,
                    "RANK_METRICS": rank_metrics,
                    "TRAINABLE_TARGET": args.trainable_target,
                    "RUN_MODE": args.run_mode,
                    "SITE_NAME": site_name,
                    "STATE_SCOPE": getattr(args, "state_scope", "full"),
                    "DATASET_SHA256": dataset_sha256,
                }
                summary = _make_round_summary(
                    current_round=current_round,
                    site_name=site_name,
                    args=args,
                    world_size=world_size,
                    metrics=metrics,
                    rank_metrics=rank_metrics,
                    payload_bytes=export_result.stats.payload_bytes,
                    tensor_count=export_result.stats.tensor_count,
                    round_seconds=round_seconds,
                    input_state=input_state,
                    output_state=output_state,
                    dataset_sha256=dataset_sha256,
                )
                flare.send(flare.FLModel(params=params, metrics=metrics, meta=meta))
                print(json.dumps(summary, sort_keys=True), flush=True)
                if params is not received_params:
                    params.clear()
                if received_params is not None:
                    received_params.clear()
                input_model.params = None
                del input_model
            dist.barrier()
            _free_round_memory(device)
    finally:
        if dist.is_initialized():
            dist.destroy_process_group()


def main() -> None:
    args = _parse_args()
    _validate_args(args)

    def _terminate(_signum, _frame):
        raise SystemExit(128 + _signum)

    signal.signal(signal.SIGTERM, _terminate)
    _run(args)


if __name__ == "__main__":
    main()
