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
    from .state_evidence import (
        file_sha256,
        load_text_partition,
        select_partition_record,
        tensor_state_probe,
        tensor_state_summary,
    )
except ImportError:
    custom_root = Path(__file__).resolve().parents[3]
    if str(custom_root) not in sys.path:
        sys.path.insert(0, str(custom_root))
    from state_evidence import (
        file_sha256,
        load_text_partition,
        select_partition_record,
        tensor_state_probe,
        tensor_state_summary,
    )

_TRAINING_TEXT = (
    "Federated learning keeps training data at each participating site.",
    "Fully sharded data parallel training divides model parameters across accelerators.",
    "A short deterministic qualification step can validate gradients and model exchange.",
    "Reliable distributed systems report failures and resource usage with enough context to diagnose them.",
)
_TRAINABLE_TARGETS = ("last-layer", "lm-head", "all")
_RUN_MODES = ("exchange-only", "train")
_STATE_SCOPES = ("full", "trainable")
_PARAMETER_PROBE_VALUES_PER_TENSOR = 64
_GRADIENT_NORM_CHUNK_SIZE = 1_048_576


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


def _local_tensor(tensor: torch.Tensor) -> torch.Tensor:
    value = tensor.to_local() if hasattr(tensor, "to_local") else tensor
    return value.detach()


def _parameter_probe_values(tensor: torch.Tensor, max_values: int) -> torch.Tensor:
    """Select a deterministic bounded sample from a local parameter shard."""

    flat = _local_tensor(tensor).reshape(-1)
    sample_count = min(flat.numel(), max_values)
    if sample_count == 0:
        return flat.clone()
    if sample_count == 1:
        indices = torch.zeros(1, dtype=torch.long, device=flat.device)
    else:
        positions = torch.arange(sample_count, dtype=torch.long, device=flat.device)
        indices = positions * (flat.numel() - 1) // (sample_count - 1)
    return flat.index_select(0, indices).clone()


def _snapshot_trainable(
    trainable: list[torch.nn.Parameter],
    max_values_per_tensor: int = _PARAMETER_PROBE_VALUES_PER_TENSOR,
) -> list[torch.Tensor]:
    """Capture bounded parameter probes without cloning full model shards."""

    if max_values_per_tensor <= 0:
        raise ValueError("max_values_per_tensor must be greater than zero")
    return [_parameter_probe_values(param, max_values_per_tensor) for param in trainable]


def _parameter_probe_change(
    trainable: list[torch.nn.Parameter],
    before: list[torch.Tensor],
    device: torch.device,
) -> dict[str, Any]:
    if len(trainable) != len(before):
        raise RuntimeError(f"parameter probe length mismatch: {len(trainable)} parameters != {len(before)} probes")

    local_max = torch.zeros((), dtype=torch.float32, device=device)
    changed_flags = torch.zeros(len(trainable), dtype=torch.int32, device=device)
    local_sample_count = 0
    for index, (param, original) in enumerate(zip(trainable, before)):
        current = _parameter_probe_values(param, _PARAMETER_PROBE_VALUES_PER_TENSOR)
        if current.shape != original.shape:
            raise RuntimeError(
                f"parameter probe shape changed at tensor {index}: {tuple(original.shape)} -> {tuple(current.shape)}"
            )
        local_sample_count += current.numel()
        if current.numel():
            tensor_max = (current.float() - original.float()).abs().max()
            local_max = torch.maximum(local_max, tensor_max)
            changed_flags[index] = (tensor_max > 0.0).to(dtype=torch.int32)

    global_sample_count = torch.tensor(local_sample_count, dtype=torch.int64, device=device)
    dist.all_reduce(local_max, op=dist.ReduceOp.MAX)
    dist.all_reduce(changed_flags, op=dist.ReduceOp.MAX)
    dist.all_reduce(global_sample_count, op=dist.ReduceOp.SUM)
    return {
        "strategy": "evenly-spaced-local-shard-values",
        "max_values_per_parameter_shard": _PARAMETER_PROBE_VALUES_PER_TENSOR,
        "parameter_tensor_count": len(trainable),
        "global_sampled_value_count": int(global_sample_count.item()),
        "globally_changed_parameter_tensor_count": int(changed_flags.sum().item()),
        "global_max_abs_change": float(local_max.item()),
    }


def _global_max_change(trainable: list[torch.nn.Parameter], before: list[torch.Tensor], device: torch.device) -> float:
    return _parameter_probe_change(trainable, before, device)["global_max_abs_change"]


def _model_parameter_evidence(model: torch.nn.Module) -> dict[str, Any]:
    parameters = list(model.parameters())
    total_parameters = sum(param.numel() for param in parameters)
    trainable_parameters = sum(param.numel() for param in parameters if param.requires_grad)
    total_tensor_count = len(parameters)
    trainable_tensor_count = sum(1 for param in parameters if param.requires_grad)
    return {
        "total_parameters": total_parameters,
        "trainable_parameters": trainable_parameters,
        "frozen_parameters": total_parameters - trainable_parameters,
        "total_tensor_count": total_tensor_count,
        "trainable_tensor_count": trainable_tensor_count,
        "frozen_tensor_count": total_tensor_count - trainable_tensor_count,
        "gradient_checkpointing_enabled": bool(getattr(model, "is_gradient_checkpointing", False)),
    }


def _gradient_probe_parameters(
    model: torch.nn.Module,
    trainable_target: str,
) -> list[tuple[str, int | None, str, torch.nn.Parameter]]:
    if trainable_target == "all":
        layers = _decoder_layers(model)
        requested = (("early", 0), ("middle", len(layers) // 2), ("late", len(layers) - 1))
        probes = []
        for position, layer_index in requested:
            candidate = next(
                ((name, param) for name, param in layers[layer_index].named_parameters() if param.requires_grad),
                None,
            )
            if candidate is None:
                raise RuntimeError(f"no trainable gradient probe parameter in decoder layer {layer_index}")
            relative_name, param = candidate
            probes.append((position, layer_index, f"model.layers.{layer_index}.{relative_name}", param))
        return probes

    candidate = next(((name, param) for name, param in model.named_parameters() if param.requires_grad), None)
    if candidate is None:
        raise RuntimeError("no trainable parameter is available for gradient probing")
    name, param = candidate
    return [("selected", None, name, param)]


def _chunked_local_l2_squared(tensor: torch.Tensor, device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
    flat = _local_tensor(tensor).reshape(-1)
    squared = torch.zeros((), dtype=torch.float32, device=device)
    finite = torch.ones((), dtype=torch.int32, device=device)
    for start in range(0, flat.numel(), _GRADIENT_NORM_CHUNK_SIZE):
        values = flat[start : start + _GRADIENT_NORM_CHUNK_SIZE].float()
        finite = torch.minimum(finite, torch.isfinite(values).all().to(dtype=torch.int32))
        norm = torch.linalg.vector_norm(values)
        squared += norm.square()
    return squared, finite


def _gradient_probe_evidence(
    probes: list[tuple[str, int | None, str, torch.nn.Parameter]],
    device: torch.device,
) -> list[dict[str, Any]]:
    evidence = []
    for position, layer_index, name, param in probes:
        gradient = param.grad
        has_gradient = torch.tensor(int(gradient is not None), dtype=torch.int32, device=device)
        dist.all_reduce(has_gradient, op=dist.ReduceOp.MIN)
        if not has_gradient.item():
            raise RuntimeError(f"gradient probe {position!r} ({name}) is missing on at least one rank")
        squared, finite = _chunked_local_l2_squared(gradient, device)
        dist.all_reduce(squared, op=dist.ReduceOp.SUM)
        dist.all_reduce(finite, op=dist.ReduceOp.MIN)
        global_l2_norm = float(torch.sqrt(squared).item())
        if not finite.item():
            raise RuntimeError(f"gradient probe {position!r} ({name}) is non-finite")
        if global_l2_norm <= 0.0:
            raise RuntimeError(f"gradient probe {position!r} ({name}) has zero global L2 norm")
        evidence.append(
            {
                "position": position,
                "layer_index": layer_index,
                "parameter": name,
                "global_l2_norm": global_l2_norm,
                "finite": True,
                "nonzero": True,
            }
        )
    return evidence


def _optimizer_state_summary(optimizer: torch.optim.Optimizer) -> dict[str, Any]:
    tensor_count = 0
    tensor_numel = 0
    tensor_bytes = 0
    dtype_histogram: dict[str, dict[str, int]] = {}
    for state in optimizer.state.values():
        for value in state.values():
            if not isinstance(value, torch.Tensor):
                continue
            local = _local_tensor(value)
            numel = local.numel()
            nbytes = numel * local.element_size()
            dtype = str(local.dtype).removeprefix("torch.")
            record = dtype_histogram.setdefault(dtype, {"tensor_count": 0, "numel": 0, "bytes": 0})
            record["tensor_count"] += 1
            record["numel"] += numel
            record["bytes"] += nbytes
            tensor_count += 1
            tensor_numel += numel
            tensor_bytes += nbytes
    return {
        "tensor_count": tensor_count,
        "tensor_numel": tensor_numel,
        "tensor_bytes": tensor_bytes,
        "dtype_histogram": dtype_histogram,
    }


def _make_optimizer(trainable: list[torch.nn.Parameter], learning_rate: float) -> torch.optim.AdamW:
    return torch.optim.AdamW(
        trainable,
        lr=learning_rate,
        foreach=False,
        fused=False,
    )


def _cuda_memory_snapshot(device: torch.device, phase: str) -> dict[str, Any]:
    free_bytes, total_bytes = torch.cuda.mem_get_info(device)
    return {
        "phase": phase,
        "allocated_bytes": torch.cuda.memory_allocated(device),
        "reserved_bytes": torch.cuda.memory_reserved(device),
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
        "peak_reserved_bytes": torch.cuda.max_memory_reserved(device),
        "free_bytes": free_bytes,
        "total_bytes": total_bytes,
        "max_rss_bytes": _max_rss_bytes(),
    }


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
) -> tuple[float, float, list[float], list[str], dict[str, Any]]:
    model.train()
    prep_error = None
    before = None
    optimizer = None
    cuda_phases = [_cuda_memory_snapshot(device, "after_state_load")]
    try:
        before = _snapshot_trainable(trainable)
        optimizer = _make_optimizer(trainable, args.learning_rate)
    except Exception as exc:
        prep_error = f"rank {rank} training setup: {type(exc).__name__}: {exc}"
    prep_error = _collect_first_error(prep_error)
    if prep_error:
        raise RuntimeError(prep_error)
    if before is None or optimizer is None:
        raise RuntimeError("training setup completed without required objects")
    cuda_phases.append(_cuda_memory_snapshot(device, "after_optimizer_init"))

    last_loss = None
    loss_trajectory = []
    sample_ids = []
    gradient_probes = _gradient_probe_parameters(model, args.trainable_target)
    gradient_evidence: list[dict[str, Any]] = []

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
        if local_step == 0:
            cuda_phases.append(_cuda_memory_snapshot(device, "after_first_forward"))
        loss.backward()
        if local_step == 0:
            gradient_evidence = _gradient_probe_evidence(gradient_probes, device)
            cuda_phases.append(_cuda_memory_snapshot(device, "after_first_backward"))
        optimizer.step()
        last_loss = loss.detach()
        loss_sum = last_loss.clone()
        dist.all_reduce(loss_sum, op=dist.ReduceOp.SUM)
        mean_step_loss = float((loss_sum / world_size).item())
        loss_trajectory.append(mean_step_loss)
        sample_ids.append(record["id"])
        step_memory = _cuda_memory_snapshot(device, f"after_optimizer_step_{local_step + 1}")
        cuda_phases.append(step_memory)
        if local_step == 0:
            cuda_phases.append({**step_memory, "phase": "after_first_optimizer_step"})
        if local_step == args.local_steps - 1:
            cuda_phases.append({**step_memory, "phase": "after_final_optimizer_step"})
        if rank == 0:
            print(
                json.dumps(
                    {
                        "event": "real_training_step",
                        "status": "PASS",
                        "site_name": site_name,
                        "current_round": current_round,
                        "local_step": local_step + 1,
                        "local_steps": args.local_steps,
                        "loss": mean_step_loss,
                        "cuda": step_memory,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        del batch, output, loss

    if last_loss is None:
        raise RuntimeError("training completed without a loss")
    mean_loss = loss_trajectory[-1]
    update_probe = _parameter_probe_change(trainable, before, device)
    max_change = update_probe["global_max_abs_change"]
    if max_change <= 0.0:
        raise RuntimeError("optimizer step did not change any bounded selected-parameter probe")
    optimizer_state = _optimizer_state_summary(optimizer)
    if optimizer_state["tensor_count"] <= 0 or optimizer_state["tensor_numel"] <= 0:
        raise RuntimeError("optimizer step did not initialize tensor state")
    optimizer_state["config"] = {
        "name": type(optimizer).__name__,
        "learning_rate": args.learning_rate,
        "foreach": False,
        "fused": False,
    }
    training_evidence = {
        "update_probe": update_probe,
        "gradient_probes": gradient_evidence,
        "optimizer_state": optimizer_state,
        "cuda_phases": cuda_phases,
    }
    optimizer.zero_grad(set_to_none=True)
    del optimizer, before
    return mean_loss, max_change, loss_trajectory, sample_ids, training_evidence


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


def _aggregate_training_evidence(rank_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    if not rank_metrics:
        raise RuntimeError("cannot aggregate training evidence without rank metrics")
    first = rank_metrics[0].get("training_evidence")
    if not isinstance(first, dict):
        raise RuntimeError("rank zero did not provide training evidence")

    optimizer_per_rank = []
    cuda_phases = []
    dtype_histogram: dict[str, dict[str, int]] = {}
    global_tensor_count = 0
    global_tensor_numel = 0
    global_tensor_bytes = 0
    expected_optimizer_config = first["optimizer_state"].get("config")
    for rank_record in rank_metrics:
        local = rank_record.get("training_evidence")
        if not isinstance(local, dict):
            raise RuntimeError(f"rank {rank_record.get('rank')} did not provide training evidence")
        optimizer_state = local["optimizer_state"]
        if optimizer_state.get("config") != expected_optimizer_config:
            raise RuntimeError(f"rank {rank_record['rank']} reported a different optimizer configuration")
        optimizer_per_rank.append(
            {
                "rank": rank_record["rank"],
                "tensor_count": optimizer_state["tensor_count"],
                "tensor_numel": optimizer_state["tensor_numel"],
                "tensor_bytes": optimizer_state["tensor_bytes"],
                "dtype_histogram": optimizer_state["dtype_histogram"],
                "config": optimizer_state["config"],
            }
        )
        global_tensor_count += optimizer_state["tensor_count"]
        global_tensor_numel += optimizer_state["tensor_numel"]
        global_tensor_bytes += optimizer_state["tensor_bytes"]
        for dtype, record in optimizer_state["dtype_histogram"].items():
            combined = dtype_histogram.setdefault(dtype, {"tensor_count": 0, "numel": 0, "bytes": 0})
            for key in ("tensor_count", "numel", "bytes"):
                combined[key] += record[key]
        cuda_phases.append({"rank": rank_record["rank"], "phases": local["cuda_phases"]})

    return {
        "update_probe": first["update_probe"],
        "gradient_probes": first["gradient_probes"],
        "optimizer_state": {
            "config": expected_optimizer_config,
            "global_tensor_count": global_tensor_count,
            "global_tensor_numel": global_tensor_numel,
            "global_tensor_bytes": global_tensor_bytes,
            "global_dtype_histogram": dtype_histogram,
            "per_rank": optimizer_per_rank,
        },
        "cuda_phases": cuda_phases,
    }


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
    training_evidence: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], Optional[list[dict[str, Any]]]]:
    peak_gpu_reserved_bytes = torch.cuda.max_memory_reserved(device)
    total_gpu_memory_bytes = torch.cuda.get_device_properties(device).total_memory
    local = {
        "rank": rank,
        "local_rank": local_rank,
        "loss": loss,
        "selected_max_abs_change": max_change,
        "load_seconds": load_seconds,
        "export_seconds": export_seconds,
        "max_rss_bytes": _max_rss_bytes(),
        "peak_gpu_allocated_bytes": torch.cuda.max_memory_allocated(device),
        "peak_gpu_reserved_bytes": peak_gpu_reserved_bytes,
        "total_gpu_memory_bytes": total_gpu_memory_bytes,
        "reserved_headroom_bytes": total_gpu_memory_bytes - peak_gpu_reserved_bytes,
        "gpu_name": torch.cuda.get_device_name(device),
        "loss_trajectory": loss_trajectory,
        "sample_ids": sample_ids,
    }
    if training_evidence is not None:
        local["training_evidence"] = training_evidence
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
    model_evidence: dict[str, Any] | None = None,
    training_evidence: dict[str, Any] | None = None,
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
        "max_length": args.max_length,
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
    if model_evidence is not None:
        summary["model_evidence"] = model_evidence
    if training_evidence is not None:
        summary["training_evidence"] = training_evidence
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
        # Establish the NVFLARE session before heavyweight model loading and
        # FSDP2 sharding. Model readiness is reported separately below.
        flare.init(rank=rank)
        model, tokenizer = _load_model_and_tokenizer(args)
        dataset_records, dataset_sha256 = _resolve_dataset(args)
        _select_trainable_parameters(model, args.trainable_target)
        model_evidence = _model_parameter_evidence(model)
        _shard_model(model, world_size)
        # fully_shard may replace registered Parameter objects with DTensor
        # parameters, so collect optimizer references only after sharding.
        trainable = [param for param in model.parameters() if param.requires_grad]
        if not trainable:
            raise RuntimeError("FSDP2 sharding left no trainable parameters")
        bridge = FSDP2StateBridge(model, exchange_prefix="model.")
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
                "dataset_sha256": dataset_sha256,
                **model_evidence,
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
            training_evidence: dict[str, Any] | None = None
            started_at = time.perf_counter()

            load_error = None
            try:
                if rank == 0:
                    input_state = (
                        tensor_state_summary(received_params)
                        if getattr(args, "state_scope", "full") == "trainable"
                        else tensor_state_probe(received_params)
                    )
                if getattr(args, "state_scope", "full") == "trainable":
                    load_result = bridge.load_trainable_state_dict(received_params)
                else:
                    load_result = bridge.load_full_state_dict(received_params)
                if rank == 0:
                    if received_params is not None:
                        received_params.clear()
                    input_model.params = None
                    received_params = None
            except Exception as exc:
                load_error = f"rank {rank} load: {type(exc).__name__}: {exc}"
            round_error = _collect_first_error(load_error)

            if not round_error:
                train_error = None
                try:
                    if args.run_mode == "train":
                        loss, max_change, loss_trajectory, sample_ids, training_evidence = _train_round(
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
                    if rank == 0:
                        output_state = (
                            tensor_state_summary(export_result.state_dict)
                            if getattr(args, "state_scope", "full") == "trainable"
                            else tensor_state_probe(export_result.state_dict)
                        )
                    if training_evidence is not None:
                        training_evidence["cuda_phases"].append(_cuda_memory_snapshot(device, "after_state_export"))
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
                training_evidence,
            )
            if rank == 0:
                assert rank_metrics is not None
                params = export_result.state_dict
                round_seconds = time.perf_counter() - started_at
                aggregate_training_evidence = (
                    _aggregate_training_evidence(rank_metrics) if training_evidence is not None else None
                )
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
                    "MODEL_EVIDENCE": model_evidence,
                }
                if aggregate_training_evidence is not None:
                    meta["TRAINING_EVIDENCE"] = aggregate_training_evidence
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
                    model_evidence=model_evidence,
                    training_evidence=aggregate_training_evidence,
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
