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

"""Run the trainable-only FSDP2 state bridge on two real CPU ranks."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import torch
import torch.distributed as dist
import torch.multiprocessing as mp
import torch.nn as nn
from torch.distributed.device_mesh import init_device_mesh
from torch.distributed.fsdp import fully_shard

from nvflare.app_opt.pt.fsdp2_state_bridge import FSDP2StateBridge


def _worker(rank: int, world_size: int, rendezvous_file: str) -> None:
    dist.init_process_group(
        "gloo",
        init_method=f"file://{rendezvous_file}",
        rank=rank,
        world_size=world_size,
    )
    try:
        mesh = init_device_mesh("cpu", (world_size,))
        model = nn.Sequential(nn.Linear(2, 3), nn.Linear(3, 1))
        for parameter in model.parameters():
            parameter.requires_grad_(False)
        for parameter in model[1].parameters():
            parameter.requires_grad_(True)
        fully_shard(model[0], mesh=mesh)
        fully_shard(model[1], mesh=mesh)
        fully_shard(model, mesh=mesh)

        expected = {
            "model.1.weight": torch.full((1, 3), 7.0),
            "model.1.bias": torch.full((1,), 8.0),
        }
        bridge = FSDP2StateBridge(model, exchange_prefix="model.")
        loaded = bridge.load_trainable_state_dict(expected if rank == 0 else None)
        if loaded.stats.tensor_count != len(expected):
            raise RuntimeError(f"trainable load returned {loaded.stats.tensor_count} tensors")
        if set(loaded.missing_keys).intersection({"1.weight", "1.bias"}) or loaded.unexpected_keys:
            raise RuntimeError(
                f"trainable load returned missing={loaded.missing_keys}, unexpected={loaded.unexpected_keys}"
            )

        exported = bridge.export_trainable_state_dict()
        if exported.stats.tensor_count != len(expected):
            raise RuntimeError(f"trainable export returned {exported.stats.tensor_count} tensors")
        if rank == 0:
            if exported.state_dict is None or exported.state_dict.keys() != expected.keys():
                raise RuntimeError("rank zero trainable export returned an unexpected schema")
            for key, value in expected.items():
                if not torch.equal(exported.state_dict[key], value):
                    raise RuntimeError(f"rank zero trainable export changed {key}")
        elif exported.state_dict is not None:
            raise RuntimeError(f"nonzero rank {rank} received a full exported state")
    finally:
        dist.destroy_process_group()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="nvflare-fsdp2-trainable-") as directory:
        rendezvous_file = str(Path(directory) / "rendezvous")
        mp.spawn(_worker, args=(2, rendezvous_file), nprocs=2, join=True)
    print(
        json.dumps(
            {
                "event": "fsdp2_trainable_cpu_gate",
                "status": "PASS",
                "torch_version": torch.__version__,
                "world_size": 2,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
