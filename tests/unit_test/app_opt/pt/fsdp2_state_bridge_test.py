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

from collections import namedtuple

import pytest
import torch
import torch.nn as nn

import nvflare.app_opt.pt.fsdp2_state_bridge as state_bridge
from nvflare.app_opt.pt.fsdp2_state_bridge import FSDP2StateBridge

IncompatibleKeys = namedtuple("IncompatibleKeys", ["missing_keys", "unexpected_keys"])


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setattr(state_bridge, "_require_process_group", lambda: (0, 4))
    monkeypatch.setattr(state_bridge, "_require_fsdp2_model", lambda model: None)
    monkeypatch.setattr(state_bridge, "_broadcast_rank_zero_control", lambda value, rank: value)
    return FSDP2StateBridge(nn.Linear(3, 2), exchange_prefix="model.")


def test_requires_initialized_process_group():
    bridge = FSDP2StateBridge(nn.Linear(2, 1))

    with pytest.raises(RuntimeError, match="initialized torch.distributed process group"):
        bridge.load_full_state_dict({"weight": torch.ones(1, 2), "bias": torch.zeros(1)})


def test_rejects_exchange_prefix_without_separator():
    with pytest.raises(ValueError, match="must end with"):
        FSDP2StateBridge(nn.Linear(2, 1), exchange_prefix="model")


def test_rejects_model_that_has_not_been_sharded_with_fsdp2(monkeypatch):
    monkeypatch.setattr(state_bridge, "_require_process_group", lambda: (0, 1))
    bridge = FSDP2StateBridge(nn.Linear(2, 1))

    with pytest.raises(RuntimeError, match="sharded with torch.distributed.fsdp.fully_shard"):
        bridge.load_full_state_dict({"weight": torch.ones(1, 2), "bias": torch.zeros(1)})


def test_rank_zero_load_strips_prefix_and_uses_full_state_broadcast(bridge, monkeypatch):
    weight = torch.full((2, 3), 2.0)
    bias = torch.full((2,), -1.0)
    observed = {}
    controls = []

    def fake_broadcast(value, rank):
        controls.append((value, rank))
        return value

    def fake_set_model_state_dict(model, state_dict, options):
        observed["model"] = model
        observed["state_dict"] = dict(state_dict)
        observed["options"] = options
        return IncompatibleKeys([], [])

    monkeypatch.setattr(state_bridge, "set_model_state_dict", fake_set_model_state_dict)
    monkeypatch.setattr(state_bridge, "_broadcast_rank_zero_control", fake_broadcast)
    incoming_state = {"model.weight": weight, "model.bias": bias}

    result = bridge.load_full_state_dict(incoming_state)

    assert observed["model"] is bridge.model
    assert observed["state_dict"] == {"weight": weight, "bias": bias}
    assert observed["state_dict"]["weight"] is weight
    assert incoming_state == {"model.weight": weight, "model.bias": bias}
    assert observed["options"].full_state_dict is True
    assert observed["options"].broadcast_from_rank0 is True
    assert observed["options"].strict is True
    assert result.missing_keys == ()
    assert result.unexpected_keys == ()
    assert result.stats.tensor_count == 2
    assert result.stats.payload_bytes == weight.numel() * weight.element_size() + bias.numel() * bias.element_size()
    assert result.stats.world_size == 4
    assert controls == [((None, result.stats.tensor_count, result.stats.payload_bytes), 0)]


def test_load_clears_shallow_working_state_when_dcp_fails(bridge, monkeypatch):
    observed = {}

    def fake_set_model_state_dict(model, state_dict, options):
        observed["working_state"] = state_dict
        raise RuntimeError("DCP load failed")

    monkeypatch.setattr(state_bridge, "set_model_state_dict", fake_set_model_state_dict)
    incoming_state = {
        "model.weight": torch.ones(2, 3),
        "model.bias": torch.zeros(2),
    }

    with pytest.raises(RuntimeError, match="DCP load failed"):
        bridge.load_full_state_dict(incoming_state)

    assert observed["working_state"] == {}
    assert set(incoming_state) == {"model.weight", "model.bias"}


def test_nonzero_rank_load_passes_empty_state_and_receives_small_metadata(monkeypatch):
    monkeypatch.setattr(state_bridge, "_require_process_group", lambda: (2, 4))
    monkeypatch.setattr(state_bridge, "_require_fsdp2_model", lambda model: None)
    controls = []

    def fake_broadcast(value, rank):
        controls.append((value, rank))
        return None, 7, 1234

    monkeypatch.setattr(state_bridge, "_broadcast_rank_zero_control", fake_broadcast)
    observed = {}

    def fake_set_model_state_dict(model, state_dict, options):
        observed["state_dict"] = dict(state_dict)
        return IncompatibleKeys([], [])

    monkeypatch.setattr(state_bridge, "set_model_state_dict", fake_set_model_state_dict)
    bridge = FSDP2StateBridge(nn.Linear(3, 2))

    result = bridge.load_full_state_dict({"this": "is ignored on nonzero ranks"})

    assert controls == [((None, 0, 0), 2)]
    assert observed["state_dict"] == {}
    assert result.stats.tensor_count == 7
    assert result.stats.payload_bytes == 1234


def test_rank_zero_validation_failure_is_synchronized_and_skips_dcp(bridge, monkeypatch):
    called = False

    def fake_set_model_state_dict(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(state_bridge, "set_model_state_dict", fake_set_model_state_dict)

    with pytest.raises(RuntimeError, match=r"does not start with 'model\.'"):
        bridge.load_full_state_dict({"weight": torch.ones(2, 3)})

    assert called is False


def test_nonzero_rank_raises_rank_zero_validation_failure_before_dcp(monkeypatch):
    monkeypatch.setattr(state_bridge, "_require_process_group", lambda: (1, 4))
    monkeypatch.setattr(state_bridge, "_require_fsdp2_model", lambda model: None)
    monkeypatch.setattr(
        state_bridge,
        "_broadcast_rank_zero_control",
        lambda value, rank: ("ValueError: bad rank-zero state", 0, 0),
    )
    called = False

    def fake_set_model_state_dict(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(state_bridge, "set_model_state_dict", fake_set_model_state_dict)
    bridge = FSDP2StateBridge(nn.Linear(3, 2))

    with pytest.raises(RuntimeError, match="bad rank-zero state"):
        bridge.load_full_state_dict(None)

    assert called is False


def test_rank_zero_load_rejects_non_cpu_full_state(bridge, monkeypatch):
    monkeypatch.setattr(
        state_bridge,
        "set_model_state_dict",
        lambda *args, **kwargs: pytest.fail("DCP load should not run"),
    )

    with pytest.raises(RuntimeError, match="must be on CPU"):
        bridge.load_full_state_dict({"model.weight": torch.empty(2, 3, device="meta")})


def test_rank_zero_export_gathers_cpu_full_state_and_restores_prefix(bridge, monkeypatch):
    weight = torch.full((2, 3), 3.0)
    bias = torch.full((2,), 4.0)
    observed = {}

    def fake_get_model_state_dict(model, options):
        observed["model"] = model
        observed["options"] = options
        return {"weight": weight, "bias": bias}

    monkeypatch.setattr(state_bridge, "get_model_state_dict", fake_get_model_state_dict)

    result = bridge.export_full_state_dict()

    assert observed["model"] is bridge.model
    assert observed["options"].full_state_dict is True
    assert observed["options"].cpu_offload is True
    assert result.state_dict == {"model.weight": weight, "model.bias": bias}
    assert result.state_dict["model.weight"] is weight
    assert result.stats.tensor_count == 2
    assert result.stats.payload_bytes == weight.numel() * weight.element_size() + bias.numel() * bias.element_size()


def test_nonzero_rank_export_returns_no_full_state(monkeypatch):
    monkeypatch.setattr(state_bridge, "_require_process_group", lambda: (3, 4))
    monkeypatch.setattr(state_bridge, "_require_fsdp2_model", lambda model: None)
    monkeypatch.setattr(
        state_bridge,
        "_broadcast_rank_zero_control",
        lambda value, rank: (None, 5, 4321),
    )
    observed = {}

    def fake_get_model_state_dict(model, options):
        observed["options"] = options
        return {}

    monkeypatch.setattr(state_bridge, "get_model_state_dict", fake_get_model_state_dict)
    bridge = FSDP2StateBridge(nn.Linear(3, 2))

    result = bridge.export_full_state_dict()

    assert observed["options"].full_state_dict is True
    assert observed["options"].cpu_offload is True
    assert result.state_dict is None
    assert result.stats.tensor_count == 5
    assert result.stats.payload_bytes == 4321


def test_rank_zero_export_rejects_non_cpu_tensor(bridge, monkeypatch):
    monkeypatch.setattr(
        state_bridge,
        "get_model_state_dict",
        lambda model, options: {"weight": torch.empty(2, 3, device="meta")},
    )

    with pytest.raises(RuntimeError, match="must be on CPU"):
        bridge.export_full_state_dict()
