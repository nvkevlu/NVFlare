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

"""Measure one real model's exact-rank FSDP2 training and state-exchange capacity."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from argparse import Namespace
from pathlib import Path

import torch
import torch.distributed as dist

REAL_TRAINING_DIR = Path(__file__).resolve().parent
if str(REAL_TRAINING_DIR) not in sys.path:
    sys.path.insert(0, str(REAL_TRAINING_DIR))

from client import (
    _aggregate_training_evidence,
    _collect_first_error,
    _cuda_memory_snapshot,
    _load_model_and_tokenizer,
    _max_rss_bytes,
    _model_parameter_evidence,
    _select_trainable_parameters,
    _setup_distributed,
    _shard_model,
    _train_round,
)
from job import DATA_FILES
from state_evidence import (
    file_sha256,
    load_text_partition,
    select_partition_record,
    tensor_state_probe,
    tensor_state_summary,
)

from nvflare.app_opt.pt.fsdp2_state_bridge import FSDP2StateBridge

_MIB = 1024 * 1024
_GIB = 1024 * 1024 * 1024


def _define_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name-or-path", required=True, type=Path)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--expected-world-size", type=int, default=4)
    parser.add_argument("--expected-payload-bytes", required=True, type=int)
    parser.add_argument("--expected-tensor-count", type=int, default=0)
    parser.add_argument("--expected-trainable-parameters", type=int, default=0)
    parser.add_argument("--expected-gpu-name-substring", default="A100-SXM4-80GB")
    parser.add_argument("--local-steps", type=int, default=2)
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1.0e-5)
    parser.add_argument("--trainable-target", choices=("last-layer", "lm-head", "all"), default="last-layer")
    parser.add_argument("--state-scope", choices=("full", "trainable"), default="trainable")
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument("--required-headroom-mib", type=int, default=16384)
    parser.add_argument("--full-job-memory-gib", type=int, default=1600)
    parser.add_argument("--full-job-client-count", type=int, default=2)
    parser.add_argument("--required-fixed-host-headroom-gib", type=int, default=128)
    parser.add_argument("--server-state-copies", type=int, default=1)
    parser.add_argument("--host-projection-mode", choices=("enforce", "report-only"), default="enforce")
    parser.add_argument("--max-model-ready-seconds", type=float, default=2400.0)
    parser.add_argument("--max-work-seconds", type=float, default=1200.0)
    parser.add_argument("--result-path", type=Path)
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    for name in (
        "expected_payload_bytes",
        "expected_world_size",
        "local_steps",
        "max_length",
        "timeout_seconds",
        "full_job_memory_gib",
        "full_job_client_count",
        "required_fixed_host_headroom_gib",
        "server_state_copies",
    ):
        if getattr(args, name) <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be greater than zero")
    if args.learning_rate <= 0:
        raise ValueError("--learning-rate must be greater than zero")
    for name in (
        "expected_tensor_count",
        "expected_trainable_parameters",
        "required_headroom_mib",
        "max_model_ready_seconds",
        "max_work_seconds",
    ):
        if getattr(args, name) < 0:
            raise ValueError(f"--{name.replace('_', '-')} must not be negative")
    if not args.model_name_or_path.is_absolute() or not args.model_name_or_path.is_dir():
        raise ValueError("--model-name-or-path must be an existing absolute directory")
    if args.full_job_client_count < 1:
        raise ValueError("--full-job-client-count must be at least one")
    if args.result_path is not None and not args.result_path.is_absolute():
        raise ValueError("--result-path must be absolute when provided")
    if args.state_scope == "trainable" and args.trainable_target != "last-layer":
        raise ValueError("--state-scope=trainable requires --trainable-target=last-layer")
    if args.trainable_target == "all" and args.expected_trainable_parameters <= 0:
        raise ValueError("--trainable-target=all requires --expected-trainable-parameters")
    if args.trainable_target == "all" and args.expected_tensor_count <= 0:
        raise ValueError("--trainable-target=all requires --expected-tensor-count")


def _training_args(args: argparse.Namespace) -> Namespace:
    return Namespace(
        model_name_or_path=str(args.model_name_or_path),
        model_revision=args.model_revision,
        trainable_target=args.trainable_target,
        state_scope=args.state_scope,
        local_steps=args.local_steps,
        max_length=args.max_length,
        learning_rate=args.learning_rate,
        timeout_seconds=args.timeout_seconds,
    )


def _full_job_host_projection(
    rank_metrics: list[dict],
    *,
    state_payload_bytes: int,
    checkpoint_file_bytes: int,
    full_job_memory_gib: int,
    full_job_client_count: int,
    required_fixed_host_headroom_gib: int,
    server_state_copies: int = 1,
) -> dict:
    """Project full-job host use without treating safetensor headers as in-memory state."""

    rank_peak_rss = [record.get("max_rss_bytes") for record in rank_metrics]
    if not rank_peak_rss or not all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in rank_peak_rss
    ):
        raise RuntimeError(f"capacity gate has invalid rank peak RSS values: {rank_peak_rss}")
    if state_payload_bytes <= 0:
        raise RuntimeError(f"capacity gate has invalid state payload bytes: {state_payload_bytes}")
    if checkpoint_file_bytes < state_payload_bytes:
        raise RuntimeError(
            "capacity gate checkpoint file bytes cannot be smaller than the logical state payload: "
            f"checkpoint_file_bytes={checkpoint_file_bytes}, state_payload_bytes={state_payload_bytes}"
        )

    one_client_rank_peak_rss_bytes = sum(rank_peak_rss)
    projected_full_job_rank_peak_rss_bytes = one_client_rank_peak_rss_bytes * full_job_client_count
    required_fixed_host_headroom_bytes = required_fixed_host_headroom_gib * _GIB
    full_job_memory_bytes = full_job_memory_gib * _GIB
    # Preserve the original physical-file projection fields for existing 14B
    # readiness artifacts, but make the logical-state projection explicit and
    # use it for the capacity decision. Safetensor headers are not another copy
    # of the server model in memory.
    physical_server_state_reserve_bytes = checkpoint_file_bytes * server_state_copies
    projected_physical_full_job_host_bytes = (
        projected_full_job_rank_peak_rss_bytes
        + physical_server_state_reserve_bytes
        + required_fixed_host_headroom_bytes
    )
    logical_server_state_reserve_bytes = state_payload_bytes * server_state_copies
    projected_logical_full_job_host_bytes = (
        projected_full_job_rank_peak_rss_bytes + logical_server_state_reserve_bytes + required_fixed_host_headroom_bytes
    )
    return {
        "full_job_memory_gib": full_job_memory_gib,
        "full_job_memory_bytes": full_job_memory_bytes,
        "full_job_client_count": full_job_client_count,
        "required_fixed_host_headroom_gib": required_fixed_host_headroom_gib,
        "required_fixed_host_headroom_bytes": required_fixed_host_headroom_bytes,
        "checkpoint_bytes": checkpoint_file_bytes,
        "checkpoint_file_bytes": checkpoint_file_bytes,
        "checkpoint_file_overhead_bytes": checkpoint_file_bytes - state_payload_bytes,
        "logical_state_payload_bytes": state_payload_bytes,
        "server_state_copies": server_state_copies,
        "server_state_reserve_bytes": physical_server_state_reserve_bytes,
        "physical_server_state_reserve_bytes": physical_server_state_reserve_bytes,
        "logical_server_state_reserve_bytes": logical_server_state_reserve_bytes,
        "one_client_rank_peak_rss_bytes": one_client_rank_peak_rss_bytes,
        "projected_full_job_rank_peak_rss_bytes": projected_full_job_rank_peak_rss_bytes,
        "projected_full_job_host_bytes": projected_physical_full_job_host_bytes,
        "projected_full_job_host_headroom_bytes": full_job_memory_bytes - projected_physical_full_job_host_bytes,
        "physical_host_projection_basis": "checkpoint-files",
        "projected_physical_full_job_host_bytes": projected_physical_full_job_host_bytes,
        "projected_physical_full_job_host_headroom_bytes": (
            full_job_memory_bytes - projected_physical_full_job_host_bytes
        ),
        "logical_host_projection_basis": "logical-state-payload",
        "projected_logical_full_job_host_bytes": projected_logical_full_job_host_bytes,
        "projected_logical_full_job_host_headroom_bytes": (
            full_job_memory_bytes - projected_logical_full_job_host_bytes
        ),
    }


def _write_result(path: Path | None, result: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _validate_rank_metrics(rank_metrics: list[dict], expected_world_size: int) -> None:
    if len(rank_metrics) != expected_world_size:
        raise RuntimeError(
            f"capacity gate expected {expected_world_size} gathered rank records, found {len(rank_metrics)}"
        )
    if not all(isinstance(record, dict) for record in rank_metrics):
        raise RuntimeError("capacity gate gathered a non-mapping rank record")
    expected_ranks = set(range(expected_world_size))
    ranks = [record.get("rank") for record in rank_metrics]
    local_ranks = [record.get("local_rank") for record in rank_metrics]
    if any(not isinstance(value, int) or isinstance(value, bool) for value in ranks):
        raise RuntimeError(f"capacity gate has invalid rank identities: {ranks}")
    if any(not isinstance(value, int) or isinstance(value, bool) for value in local_ranks):
        raise RuntimeError(f"capacity gate has invalid local-rank identities: {local_ranks}")
    if set(ranks) != expected_ranks or len(set(ranks)) != expected_world_size:
        raise RuntimeError(f"capacity gate rank identities are incomplete or duplicated: {ranks}")
    if set(local_ranks) != expected_ranks or len(set(local_ranks)) != expected_world_size:
        raise RuntimeError(f"capacity gate local-rank identities are incomplete or duplicated: {local_ranks}")


def _validate_training_contract(
    rank_metrics: list[dict],
    dataset_records: list[dict[str, str]],
    *,
    world_size: int,
    local_steps: int,
) -> dict:
    """Require exact finite-step and non-repeating dataset coverage across all ranks."""

    expected_ids = [
        select_partition_record(
            dataset_records,
            current_round=0,
            local_step=local_step,
            rank=rank,
            world_size=world_size,
            local_steps=local_steps,
        )["id"]
        for local_step in range(local_steps)
        for rank in range(world_size)
    ]
    observed_ids = []
    for record in rank_metrics:
        rank = record["rank"]
        sample_ids = record.get("sample_ids")
        losses = record.get("loss_trajectory")
        if not isinstance(sample_ids, list) or len(sample_ids) != local_steps:
            raise RuntimeError(
                f"rank {rank} sample coverage mismatch: expected {local_steps} IDs, observed {sample_ids!r}"
            )
        if (
            not isinstance(losses, list)
            or len(losses) != local_steps
            or not all(
                isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                for value in losses
            )
        ):
            raise RuntimeError(
                f"rank {rank} loss trajectory must contain exactly {local_steps} finite values: {losses!r}"
            )
        observed_ids.extend(sample_ids)

    if len(set(observed_ids)) != len(observed_ids):
        raise RuntimeError(f"capacity gate reused dataset sample IDs: {observed_ids}")
    if set(observed_ids) != set(expected_ids):
        raise RuntimeError(
            "capacity gate dataset coverage mismatch: "
            f"expected={sorted(expected_ids)}, observed={sorted(observed_ids)}"
        )
    return {
        "status": "PASS",
        "sample_count": len(observed_ids),
        "unique_sample_count": len(set(observed_ids)),
        "finite_loss_count": world_size * local_steps,
        "sample_ids": sorted(observed_ids),
    }


def _model_dtype_evidence(model: torch.nn.Module) -> dict:
    histogram = {}
    payload_bytes = 0
    for parameter in model.parameters():
        dtype = str(parameter.dtype)
        if dtype.startswith("torch."):
            dtype = dtype[len("torch.") :]
        item = histogram.setdefault(dtype, {"tensor_count": 0, "numel": 0, "bytes": 0})
        numel = parameter.numel()
        nbytes = numel * parameter.element_size()
        item["tensor_count"] += 1
        item["numel"] += numel
        item["bytes"] += nbytes
        payload_bytes += nbytes
    return {"parameter_dtype_histogram": histogram, "parameter_payload_bytes": payload_bytes}


def _require_exact_bf16_model(
    dtype_evidence: dict,
    *,
    expected_parameters: int,
    expected_tensor_count: int,
    expected_payload_bytes: int,
) -> dict:
    histogram = dtype_evidence.get("parameter_dtype_histogram")
    if not isinstance(histogram, dict) or set(histogram) != {"bfloat16"}:
        raise RuntimeError(f"capacity gate model is not entirely BF16: {histogram!r}")
    observed = histogram["bfloat16"]
    expected = {
        "tensor_count": expected_tensor_count,
        "numel": expected_parameters,
        "bytes": 2 * expected_parameters,
    }
    if observed != expected:
        raise RuntimeError(f"capacity gate BF16 model coverage mismatch: expected {expected}, observed {observed!r}")
    if expected_payload_bytes != expected["bytes"]:
        raise RuntimeError(
            "capacity gate expected payload is inconsistent with the exact BF16 parameter count: "
            f"expected_payload_bytes={expected_payload_bytes}, bf16_parameter_bytes={expected['bytes']}"
        )
    if dtype_evidence.get("parameter_payload_bytes") != expected_payload_bytes:
        raise RuntimeError(
            "capacity gate model parameter payload mismatch: "
            f"expected {expected_payload_bytes}, observed {dtype_evidence.get('parameter_payload_bytes')!r}"
        )
    return {
        "status": "PASS",
        "dtype": "bfloat16",
        "parameter_count": expected_parameters,
        "parameter_tensor_count": expected_tensor_count,
        "parameter_payload_bytes": expected_payload_bytes,
    }


def _export_state(bridge: FSDP2StateBridge, state_scope: str):
    return bridge.export_trainable_state_dict() if state_scope == "trainable" else bridge.export_full_state_dict()


def _load_state(bridge: FSDP2StateBridge, state_scope: str, state: dict | None):
    return bridge.load_trainable_state_dict(state) if state_scope == "trainable" else bridge.load_full_state_dict(state)


def _state_evidence(state: dict, state_scope: str) -> dict:
    return tensor_state_summary(state) if state_scope == "trainable" else tensor_state_probe(state)


def _sample_values(summary: dict) -> dict[tuple[str, int], float]:
    return {(sample["key"], sample["index"]): float(sample["value"]) for sample in summary["samples"]}


def _require_exact_bf16_adamw_moments(training_evidence: dict, trainable_parameters: int) -> dict:
    """Require two BF16 AdamW moment values for every trainable parameter."""

    optimizer = training_evidence.get("optimizer_state")
    if not isinstance(optimizer, dict):
        raise RuntimeError("capacity gate is missing aggregated optimizer-state evidence")
    config = optimizer.get("config")
    if (
        not isinstance(config, dict)
        or config.get("name") != "AdamW"
        or config.get("foreach") is not False
        or config.get("fused") is not False
    ):
        raise RuntimeError(f"capacity gate has unsupported AdamW configuration: {config!r}")
    expected_values = 2 * trainable_parameters
    expected_bytes = 4 * trainable_parameters
    histogram = optimizer.get("global_dtype_histogram")
    moments = histogram.get("bfloat16") if isinstance(histogram, dict) else None
    if not isinstance(moments, dict):
        raise RuntimeError("capacity gate optimizer state is missing BF16 moment evidence")
    observed_values = moments.get("numel")
    observed_bytes = moments.get("bytes")
    if observed_values != expected_values or observed_bytes != expected_bytes:
        raise RuntimeError(
            "capacity gate BF16 AdamW moment coverage mismatch: "
            f"expected {expected_values} values/{expected_bytes} bytes, "
            f"observed {observed_values!r} values/{observed_bytes!r} bytes"
        )
    return {
        "status": "PASS",
        "dtype": "bfloat16",
        "trainable_parameters": trainable_parameters,
        "moment_values": observed_values,
        "moment_bytes": observed_bytes,
        "foreach": False,
        "fused": False,
    }


def _run(args: argparse.Namespace) -> None:
    training_args = _training_args(args)
    rank, world_size, local_rank, device = _setup_distributed(args.timeout_seconds)
    try:
        if world_size != args.expected_world_size:
            raise RuntimeError(
                f"real-model capacity gate requires exactly {args.expected_world_size} ranks, found {world_size}"
            )
        gpu_name = torch.cuda.get_device_name(device)
        if args.expected_gpu_name_substring not in gpu_name:
            raise RuntimeError(f"GPU name must contain {args.expected_gpu_name_substring!r}, observed {gpu_name!r}")

        torch.cuda.reset_peak_memory_stats(device)
        started_at = time.perf_counter()
        model, tokenizer = _load_model_and_tokenizer(training_args)
        _select_trainable_parameters(model, training_args.trainable_target)
        model_evidence = _model_parameter_evidence(model)
        model_dtype_evidence = _model_dtype_evidence(model)
        if args.expected_trainable_parameters and (
            model_evidence["trainable_parameters"] != args.expected_trainable_parameters
        ):
            raise RuntimeError(
                f"trainable parameter mismatch: expected {args.expected_trainable_parameters}, "
                f"observed {model_evidence['trainable_parameters']}"
            )
        if args.trainable_target == "all" and (
            model_evidence["trainable_parameters"] != model_evidence["total_parameters"]
            or model_evidence["frozen_parameters"] != 0
        ):
            raise RuntimeError(f"all-parameter selection evidence is invalid: {model_evidence}")
        exact_bf16_model_evidence = None
        if args.trainable_target == "all":
            exact_bf16_model_evidence = _require_exact_bf16_model(
                model_dtype_evidence,
                expected_parameters=args.expected_trainable_parameters,
                expected_tensor_count=args.expected_tensor_count,
                expected_payload_bytes=args.expected_payload_bytes,
            )
        _shard_model(model, world_size)
        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        if not trainable:
            raise RuntimeError("FSDP2 sharding left no trainable parameters")
        model_ready_seconds = time.perf_counter() - started_at
        model_ready_error = None
        if args.max_model_ready_seconds and model_ready_seconds > args.max_model_ready_seconds:
            model_ready_error = (
                f"rank {rank} model readiness took {model_ready_seconds:.3f}s, "
                f"exceeding {args.max_model_ready_seconds:.3f}s"
            )
        model_ready_error = _collect_first_error(model_ready_error)
        if model_ready_error:
            raise RuntimeError(model_ready_error)
        post_ready_started_at = time.perf_counter()

        bridge = FSDP2StateBridge(model, exchange_prefix="model.")
        initial_export = _export_state(bridge, args.state_scope)
        if initial_export.stats.payload_bytes != args.expected_payload_bytes:
            raise RuntimeError(
                f"initial exchanged payload mismatch: expected {args.expected_payload_bytes}, "
                f"observed {initial_export.stats.payload_bytes}"
            )
        if args.expected_tensor_count and initial_export.stats.tensor_count != args.expected_tensor_count:
            raise RuntimeError(
                f"initial exchanged tensor-count mismatch: expected {args.expected_tensor_count}, "
                f"observed {initial_export.stats.tensor_count}"
            )
        initial_state = initial_export.state_dict if rank == 0 else None
        initial_summary = None
        initial_summary_error = None
        if rank == 0:
            try:
                initial_summary = _state_evidence(initial_state, args.state_scope)
            except Exception as exc:
                initial_summary_error = f"rank-zero initial-state summary failed: {type(exc).__name__}: {exc}"
        initial_summary_error = _collect_first_error(initial_summary_error)
        if initial_summary_error:
            raise RuntimeError(initial_summary_error)
        load_result = _load_state(bridge, args.state_scope, initial_state)
        if rank == 0 and initial_state is not None:
            initial_state.clear()

        dataset_path = DATA_FILES["site-1"]
        dataset_records = load_text_partition(dataset_path, expected_sha256=file_sha256(dataset_path))
        loss, max_change, loss_trajectory, sample_ids, training_evidence = _train_round(
            model,
            tokenizer,
            trainable,
            training_args,
            rank,
            world_size,
            device,
            "capacity-gate",
            0,
            dataset_records,
        )
        final_export = _export_state(bridge, args.state_scope)
        training_evidence["cuda_phases"].append(_cuda_memory_snapshot(device, "after_state_export"))
        if final_export.stats.payload_bytes != args.expected_payload_bytes:
            raise RuntimeError(
                f"final exchanged payload mismatch: expected {args.expected_payload_bytes}, "
                f"observed {final_export.stats.payload_bytes}"
            )
        if args.expected_tensor_count and final_export.stats.tensor_count != args.expected_tensor_count:
            raise RuntimeError(
                f"final exchanged tensor-count mismatch: expected {args.expected_tensor_count}, "
                f"observed {final_export.stats.tensor_count}"
            )
        final_summary = None
        final_validation_error = None
        if rank == 0:
            try:
                final_summary = _state_evidence(final_export.state_dict, args.state_scope)
                if initial_summary is None:
                    raise RuntimeError("rank zero did not receive the initial state evidence")
                if args.state_scope == "trainable":
                    changed = initial_summary["sha256"] != final_summary["sha256"]
                else:
                    if initial_summary["schema_sha256"] != final_summary["schema_sha256"]:
                        raise RuntimeError("full-state tensor schema changed during the capacity gate")
                    initial_values = _sample_values(initial_summary)
                    final_values = _sample_values(final_summary)
                    changed = any(final_values[key] != value for key, value in initial_values.items())
                # A BF16 update can be smaller than the four exported-state sample
                # coordinates even when the denser training probe changed. Retain
                # this observation as evidence; _train_round already fails closed
                # unless its bounded 64-value-per-shard probe detects an update.
                final_summary["bounded_values_changed"] = changed
            except Exception as exc:
                final_validation_error = f"rank-zero final-state validation failed: {type(exc).__name__}: {exc}"
        final_validation_error = _collect_first_error(final_validation_error)
        if final_validation_error:
            raise RuntimeError(final_validation_error)

        torch.cuda.synchronize(device)
        post_ready_work_seconds = time.perf_counter() - post_ready_started_at
        total_memory_bytes = torch.cuda.get_device_properties(device).total_memory
        peak_allocated_bytes = torch.cuda.max_memory_allocated(device)
        peak_reserved_bytes = torch.cuda.max_memory_reserved(device)
        reserved_headroom_bytes = total_memory_bytes - peak_reserved_bytes
        local_metrics = {
            "rank": rank,
            "local_rank": local_rank,
            "gpu_name": gpu_name,
            "total_gpu_memory_bytes": total_memory_bytes,
            "peak_gpu_allocated_bytes": peak_allocated_bytes,
            "peak_gpu_reserved_bytes": peak_reserved_bytes,
            "reserved_headroom_bytes": reserved_headroom_bytes,
            "max_rss_bytes": _max_rss_bytes(),
            "model_ready_seconds": model_ready_seconds,
            "post_ready_work_seconds": post_ready_work_seconds,
            "state_load_seconds": load_result.stats.duration_seconds,
            "initial_export_seconds": initial_export.stats.duration_seconds,
            "final_export_seconds": final_export.stats.duration_seconds,
            "loss": loss,
            "loss_trajectory": loss_trajectory,
            "sample_ids": sample_ids,
            "selected_max_abs_change": max_change,
            "training_evidence": training_evidence,
        }
        gathered = [None for _ in range(world_size)] if rank == 0 else None
        dist.gather_object(local_metrics, gathered, dst=0)

        if rank == 0:
            assert gathered is not None
            _validate_rank_metrics(gathered, args.expected_world_size)
            training_contract = _validate_training_contract(
                gathered,
                dataset_records,
                world_size=world_size,
                local_steps=args.local_steps,
            )
            aggregate_training_evidence = _aggregate_training_evidence(gathered)
            optimizer_moment_evidence = None
            if args.trainable_target == "all":
                optimizer_moment_evidence = _require_exact_bf16_adamw_moments(
                    aggregate_training_evidence,
                    model_evidence["trainable_parameters"],
                )
            required_headroom_bytes = args.required_headroom_mib * _MIB
            checkpoint_file_bytes = sum(
                path.stat().st_size for path in args.model_name_or_path.glob("model*.safetensors") if path.is_file()
            )
            host_projection = _full_job_host_projection(
                gathered,
                state_payload_bytes=final_export.stats.payload_bytes,
                checkpoint_file_bytes=checkpoint_file_bytes,
                full_job_memory_gib=args.full_job_memory_gib,
                full_job_client_count=args.full_job_client_count,
                required_fixed_host_headroom_gib=args.required_fixed_host_headroom_gib,
                server_state_copies=args.server_state_copies,
            )
            observed_max_model_ready_seconds = max(record["model_ready_seconds"] for record in gathered)
            observed_max_work_seconds = max(record["post_ready_work_seconds"] for record in gathered)
            insufficient = [
                record["rank"] for record in gathered if record["reserved_headroom_bytes"] < required_headroom_bytes
            ]
            failures = []
            if insufficient:
                failures.append(
                    f"ranks {insufficient} retained less than {args.required_headroom_mib} MiB reserved headroom"
                )
            if args.max_model_ready_seconds and observed_max_model_ready_seconds > args.max_model_ready_seconds:
                failures.append(
                    f"model readiness took {observed_max_model_ready_seconds:.3f}s, "
                    f"exceeding {args.max_model_ready_seconds:.3f}s"
                )
            if args.max_work_seconds and observed_max_work_seconds > args.max_work_seconds:
                failures.append(
                    f"post-ready work took {observed_max_work_seconds:.3f}s, " f"exceeding {args.max_work_seconds:.3f}s"
                )
            if (
                args.host_projection_mode == "enforce"
                and host_projection["projected_logical_full_job_host_headroom_bytes"] < 0
            ):
                failures.append(
                    "projected logical full-job host bytes "
                    f"{host_projection['projected_logical_full_job_host_bytes']} exceed "
                    f"{args.full_job_memory_gib} GiB ({host_projection['full_job_memory_bytes']} bytes)"
                )
            result = {
                "event": "real_model_fsdp2_gpu_capacity_gate",
                "experiment_scope": "single-client-fsdp2-capacity",
                "status": "FAIL" if failures else "PASS",
                "model_path": str(args.model_name_or_path),
                "model_revision": args.model_revision,
                "world_size": world_size,
                "expected_world_size": args.expected_world_size,
                "trainable_target": args.trainable_target,
                "state_scope": args.state_scope,
                **model_evidence,
                **model_dtype_evidence,
                "exact_bf16_model_evidence": exact_bf16_model_evidence,
                "local_steps": args.local_steps,
                "max_length": args.max_length,
                "payload_bytes": final_export.stats.payload_bytes,
                "tensor_count": final_export.stats.tensor_count,
                "required_headroom_mib": args.required_headroom_mib,
                "host_projection_mode": args.host_projection_mode,
                "max_model_ready_seconds": args.max_model_ready_seconds,
                "observed_max_model_ready_seconds": observed_max_model_ready_seconds,
                "max_work_seconds": args.max_work_seconds,
                "observed_max_work_seconds": observed_max_work_seconds,
                **host_projection,
                "initial_state": initial_summary,
                "final_state": final_summary,
                "training_evidence": aggregate_training_evidence,
                "optimizer_moment_evidence": optimizer_moment_evidence,
                "training_contract": training_contract,
                "ranks": gathered,
            }
            _write_result(args.result_path, result)
            print(json.dumps(result, sort_keys=True), flush=True)
            if final_export.state_dict is not None:
                final_export.state_dict.clear()
            if failures:
                raise RuntimeError("; ".join(failures))
    finally:
        if dist.is_initialized():
            dist.destroy_process_group()


def main() -> None:
    args = _define_parser().parse_args()
    _validate_args(args)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the real-model FSDP2 capacity gate")
    _run(args)


if __name__ == "__main__":
    main()
