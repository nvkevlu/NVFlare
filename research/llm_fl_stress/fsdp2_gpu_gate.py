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

"""Four-GPU CUDA/NCCL qualification gate for the NVFLARE FSDP2 state bridge.

Launch from the repository root with one process per visible GPU:

.. code-block:: bash

   python -m torch.distributed.run --standalone --nproc_per_node=4 \
       research/llm_fl_stress/fsdp2_gpu_gate.py

The gate uses a small deterministic model. It validates rank-zero-only CPU full
state load/export, performs one real sharded optimizer step, verifies that a
parameter changed, and emits one JSON record containing per-rank memory and
timing telemetry. It does not start NVFLARE services or download a model.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import resource
import sys
from datetime import timedelta
from typing import Optional

import torch
import torch.distributed as dist
import torch.nn as nn
from torch.distributed.device_mesh import init_device_mesh
from torch.distributed.fsdp import fully_shard

from nvflare.app_opt.pt.fsdp2_state_bridge import FSDP2StateBridge


class TinyTrainingModel(nn.Module):
    def __init__(self, hidden_size: int, num_layers: int):
        super().__init__()
        self.layers = nn.ModuleList([nn.Linear(hidden_size, hidden_size) for _ in range(num_layers)])
        self.norm = nn.LayerNorm(hidden_size)
        self.head = nn.Linear(hidden_size, hidden_size, bias=False)

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        hidden = inputs
        for layer in self.layers:
            hidden = torch.nn.functional.gelu(layer(hidden))
        return self.head(self.norm(hidden))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hidden-size", type=int, default=1024)
    parser.add_argument("--num-layers", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=1.0e-3)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    for name in ("hidden_size", "num_layers", "batch_size", "timeout_seconds"):
        if getattr(args, name) <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be greater than zero")
    if args.learning_rate <= 0:
        raise ValueError("--learning-rate must be greater than zero")


def _rank_zero_full_state(model: nn.Module, rank: int) -> Optional[dict[str, torch.Tensor]]:
    if rank != 0:
        return None

    generator = torch.Generator(device="cpu")
    generator.manual_seed(20260721)
    state = {}
    for index, (name, param) in enumerate(model.named_parameters()):
        shape = tuple(param.shape)
        if name == "norm.weight":
            value = torch.ones(shape, dtype=param.dtype)
        elif name.endswith("bias"):
            value = torch.zeros(shape, dtype=param.dtype)
        else:
            value = torch.randn(shape, dtype=param.dtype, generator=generator) * (0.01 + index * 0.001)
        state[f"model.{name}"] = value
    return state


def _max_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _nccl_version() -> Optional[str]:
    version = torch.cuda.nccl.version()
    if version is None:
        return None
    if isinstance(version, tuple):
        return ".".join(str(part) for part in version)
    return str(version)


def _shard_model(model: TinyTrainingModel, world_size: int) -> None:
    mesh = init_device_mesh("cuda", (world_size,))
    for layer in model.layers:
        fully_shard(layer, mesh=mesh)
    fully_shard(model.norm, mesh=mesh)
    fully_shard(model.head, mesh=mesh)
    fully_shard(model, mesh=mesh)


def _run_gate(args: argparse.Namespace) -> None:
    local_rank = int(os.environ["LOCAL_RANK"])
    torch.cuda.set_device(local_rank)
    dist.init_process_group("nccl", timeout=timedelta(seconds=args.timeout_seconds))
    rank = dist.get_rank()
    world_size = dist.get_world_size()

    try:
        if world_size < 2:
            raise RuntimeError("the CUDA gate requires at least two ranks")
        if world_size > torch.cuda.device_count():
            raise RuntimeError(f"world size {world_size} exceeds visible CUDA device count {torch.cuda.device_count()}")

        device = torch.device("cuda", local_rank)
        torch.manual_seed(1000 + rank)
        model = TinyTrainingModel(args.hidden_size, args.num_layers).to(device)
        _shard_model(model, world_size)
        bridge = FSDP2StateBridge(model, exchange_prefix="model.")
        full_state = _rank_zero_full_state(model, rank)
        torch.cuda.reset_peak_memory_stats(device)

        load_result = bridge.load_full_state_dict(full_state)
        before_export = bridge.export_full_state_dict()
        pre_export_seconds = before_export.stats.duration_seconds
        selected_key = "model.head.weight"
        selected_before = None
        if rank == 0:
            if before_export.state_dict is None:
                raise AssertionError("rank zero did not receive the pre-training full state")
            if full_state is None:
                raise AssertionError("rank-zero test state was unexpectedly released")
            if before_export.state_dict.keys() != full_state.keys():
                raise AssertionError("pre-training export keys differ from the loaded full state")
            for key, expected in full_state.items():
                if not torch.equal(before_export.state_dict[key], expected):
                    raise AssertionError(f"pre-training round trip changed tensor {key!r}")
            selected_before = before_export.state_dict[selected_key].clone()
            before_export.state_dict.clear()
            full_state.clear()
        del before_export
        del full_state
        gc.collect()

        optimizer = torch.optim.SGD(model.parameters(), lr=args.learning_rate)
        optimizer.zero_grad(set_to_none=True)
        inputs = torch.randn(args.batch_size, args.hidden_size, device=device)
        outputs = model(inputs)
        loss = outputs.float().square().mean()
        if not torch.isfinite(loss):
            raise AssertionError(f"rank {rank} produced non-finite loss {loss.item()}")
        loss.backward()
        optimizer.step()
        optimizer.zero_grad(set_to_none=True)

        after_export = bridge.export_full_state_dict()
        selected_max_abs_change = None
        if rank == 0:
            if after_export.state_dict is None or selected_before is None:
                raise AssertionError("rank zero did not receive the post-training full state")
            selected_after = after_export.state_dict[selected_key]
            selected_max_abs_change = float((selected_after - selected_before).abs().max().item())
            if selected_max_abs_change <= 0.0:
                raise AssertionError(f"optimizer step did not change {selected_key!r}")

        local_metrics = {
            "rank": rank,
            "local_rank": local_rank,
            "gpu_name": torch.cuda.get_device_name(device),
            "loss": float(loss.item()),
            "max_rss_bytes": _max_rss_bytes(),
            "peak_gpu_allocated_bytes": torch.cuda.max_memory_allocated(device),
            "peak_gpu_reserved_bytes": torch.cuda.max_memory_reserved(device),
            "load_seconds": load_result.stats.duration_seconds,
            "pre_export_seconds": pre_export_seconds,
            "post_export_seconds": after_export.stats.duration_seconds,
        }
        gathered_metrics = [None] * world_size if rank == 0 else None
        dist.gather_object(local_metrics, gathered_metrics, dst=0)

        if rank == 0:
            result = {
                "event": "fsdp2_gpu_gate",
                "status": "PASS",
                "world_size": world_size,
                "torch_version": torch.__version__,
                "torch_cuda_version": torch.version.cuda,
                "nccl_version": _nccl_version(),
                "model": {
                    "hidden_size": args.hidden_size,
                    "num_layers": args.num_layers,
                    "batch_size": args.batch_size,
                    "tensor_count": after_export.stats.tensor_count,
                    "payload_bytes": after_export.stats.payload_bytes,
                },
                "selected_parameter": selected_key,
                "selected_max_abs_change": selected_max_abs_change,
                "ranks": gathered_metrics,
            }
            print(json.dumps(result, sort_keys=True), flush=True)
            after_export.state_dict.clear()
    finally:
        if dist.is_initialized():
            dist.destroy_process_group()


def main() -> None:
    args = _parse_args()
    _validate_args(args)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the FSDP2 GPU qualification gate")
    _run_gate(args)


if __name__ == "__main__":
    main()
