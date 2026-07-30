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

"""Measure one real model's four-rank FSDP2 last-layer training capacity."""

from __future__ import annotations

import argparse
import json
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
    _load_model_and_tokenizer,
    _max_rss_bytes,
    _select_trainable_parameters,
    _setup_distributed,
    _shard_model,
    _train_round,
)
from job import DATA_FILES
from state_evidence import file_sha256, load_text_partition, tensor_state_summary

from nvflare.app_opt.pt.fsdp2_state_bridge import FSDP2StateBridge

_MIB = 1024 * 1024


def _define_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name-or-path", required=True, type=Path)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--expected-payload-bytes", required=True, type=int)
    parser.add_argument("--expected-gpu-name-substring", default="A100-SXM4-80GB")
    parser.add_argument("--local-steps", type=int, default=2)
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1.0e-5)
    parser.add_argument("--timeout-seconds", type=int, default=2400)
    parser.add_argument("--required-headroom-mib", type=int, default=8192)
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    for name in (
        "expected_payload_bytes",
        "local_steps",
        "max_length",
        "timeout_seconds",
        "required_headroom_mib",
    ):
        if getattr(args, name) <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be greater than zero")
    if args.learning_rate <= 0:
        raise ValueError("--learning-rate must be greater than zero")
    if not args.model_name_or_path.is_absolute() or not args.model_name_or_path.is_dir():
        raise ValueError("--model-name-or-path must be an existing absolute directory")


def _training_args(args: argparse.Namespace) -> Namespace:
    return Namespace(
        model_name_or_path=str(args.model_name_or_path),
        model_revision=args.model_revision,
        trainable_target="last-layer",
        local_steps=args.local_steps,
        max_length=args.max_length,
        learning_rate=args.learning_rate,
        timeout_seconds=args.timeout_seconds,
    )


def _run(args: argparse.Namespace) -> None:
    training_args = _training_args(args)
    rank, world_size, local_rank, device = _setup_distributed(args.timeout_seconds)
    try:
        if world_size != 4:
            raise RuntimeError(f"real-model capacity gate requires exactly four ranks, found {world_size}")
        gpu_name = torch.cuda.get_device_name(device)
        if args.expected_gpu_name_substring not in gpu_name:
            raise RuntimeError(f"GPU name must contain {args.expected_gpu_name_substring!r}, observed {gpu_name!r}")

        torch.cuda.reset_peak_memory_stats(device)
        started_at = time.perf_counter()
        model, tokenizer = _load_model_and_tokenizer(training_args)
        _select_trainable_parameters(model, training_args.trainable_target)
        _shard_model(model, world_size)
        trainable = [parameter for parameter in model.parameters() if parameter.requires_grad]
        if not trainable:
            raise RuntimeError("FSDP2 sharding left no trainable parameters")
        model_ready_seconds = time.perf_counter() - started_at

        bridge = FSDP2StateBridge(model, exchange_prefix="model.")
        initial_export = bridge.export_trainable_state_dict()
        if initial_export.stats.payload_bytes != args.expected_payload_bytes:
            raise RuntimeError(
                f"initial trainable payload mismatch: expected {args.expected_payload_bytes}, "
                f"observed {initial_export.stats.payload_bytes}"
            )
        initial_state = initial_export.state_dict if rank == 0 else None
        initial_summary = tensor_state_summary(initial_state) if rank == 0 else None
        load_result = bridge.load_trainable_state_dict(initial_state)
        if rank == 0 and initial_state is not None:
            initial_state.clear()

        dataset_path = DATA_FILES["site-1"]
        dataset_records = load_text_partition(dataset_path, expected_sha256=file_sha256(dataset_path))
        loss, max_change, loss_trajectory, sample_ids = _train_round(
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
        final_export = bridge.export_trainable_state_dict()
        if final_export.stats.payload_bytes != args.expected_payload_bytes:
            raise RuntimeError(
                f"final trainable payload mismatch: expected {args.expected_payload_bytes}, "
                f"observed {final_export.stats.payload_bytes}"
            )
        final_summary = tensor_state_summary(final_export.state_dict) if rank == 0 else None
        if rank == 0:
            if initial_summary is None or final_summary is None:
                raise RuntimeError("rank zero did not receive trainable state summaries")
            if initial_summary["sha256"] == final_summary["sha256"]:
                raise RuntimeError("real optimizer steps did not change the exported trainable state")

        torch.cuda.synchronize(device)
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
            "state_load_seconds": load_result.stats.duration_seconds,
            "initial_export_seconds": initial_export.stats.duration_seconds,
            "final_export_seconds": final_export.stats.duration_seconds,
            "loss": loss,
            "loss_trajectory": loss_trajectory,
            "sample_ids": sample_ids,
            "selected_max_abs_change": max_change,
        }
        gathered = [None for _ in range(world_size)] if rank == 0 else None
        dist.gather_object(local_metrics, gathered, dst=0)

        if rank == 0:
            assert gathered is not None
            required_headroom_bytes = args.required_headroom_mib * _MIB
            insufficient = [
                record["rank"] for record in gathered if record["reserved_headroom_bytes"] < required_headroom_bytes
            ]
            if insufficient:
                raise RuntimeError(
                    f"ranks {insufficient} retained less than {args.required_headroom_mib} MiB reserved headroom"
                )
            result = {
                "event": "real_model_fsdp2_gpu_capacity_gate",
                "status": "PASS",
                "model_path": str(args.model_name_or_path),
                "model_revision": args.model_revision,
                "world_size": world_size,
                "trainable_target": "last-layer",
                "local_steps": args.local_steps,
                "max_length": args.max_length,
                "payload_bytes": final_export.stats.payload_bytes,
                "tensor_count": final_export.stats.tensor_count,
                "required_headroom_mib": args.required_headroom_mib,
                "initial_state": initial_summary,
                "final_state": final_summary,
                "ranks": gathered,
            }
            print(json.dumps(result, sort_keys=True), flush=True)
            if final_export.state_dict is not None:
                final_export.state_dict.clear()
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
