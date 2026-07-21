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

"""Real two-rank CPU collective coverage for the FSDP2 state bridge."""

import torch
import torch.distributed as dist
import torch.multiprocessing as mp
import torch.nn as nn
from torch.distributed.device_mesh import init_device_mesh
from torch.distributed.fsdp import fully_shard

from nvflare.app_opt.pt.fsdp2_state_bridge import FSDP2StateBridge


def _expected_state() -> dict[str, torch.Tensor]:
    return {
        "model.0.weight": torch.full((3, 2), 1.0),
        "model.0.bias": torch.full((3,), 2.0),
        "model.1.weight": torch.full((1, 3), 3.0),
        "model.1.bias": torch.full((1,), 4.0),
    }


def _run_fsdp2_round_trip(rank: int, world_size: int, rendezvous_file: str) -> None:
    dist.init_process_group(
        "gloo",
        init_method=f"file://{rendezvous_file}",
        rank=rank,
        world_size=world_size,
    )
    try:
        mesh = init_device_mesh("cpu", (world_size,))
        model = nn.Sequential(nn.Linear(2, 3), nn.Linear(3, 1))
        fully_shard(model[0], mesh=mesh)
        fully_shard(model[1], mesh=mesh)
        fully_shard(model, mesh=mesh)
        bridge = FSDP2StateBridge(model, exchange_prefix="model.")

        expected = _expected_state()
        load_result = bridge.load_full_state_dict(expected if rank == 0 else None)

        assert load_result.missing_keys == ()
        assert load_result.unexpected_keys == ()
        assert load_result.stats.tensor_count == len(expected)
        assert load_result.stats.payload_bytes == sum(v.numel() * v.element_size() for v in expected.values())
        assert load_result.stats.world_size == world_size

        export_result = bridge.export_full_state_dict()
        assert export_result.stats.tensor_count == len(expected)
        assert export_result.stats.payload_bytes == load_result.stats.payload_bytes
        assert export_result.stats.world_size == world_size
        if rank == 0:
            assert export_result.state_dict is not None
            assert export_result.state_dict.keys() == expected.keys()
            for key, value in expected.items():
                assert torch.equal(export_result.state_dict[key], value)
                assert export_result.state_dict[key].device.type == "cpu"
        else:
            assert export_result.state_dict is None
    finally:
        dist.destroy_process_group()


def test_two_rank_fsdp2_full_state_round_trip(tmp_path):
    world_size = 2
    mp.spawn(
        _run_fsdp2_round_trip,
        args=(world_size, str(tmp_path / "fsdp2_rendezvous")),
        nprocs=world_size,
        join=True,
    )
