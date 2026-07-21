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

from argparse import Namespace

import pytest

from research.llm_fl_stress.fsdp2_gpu_gate import TinyTrainingModel, _rank_zero_full_state, _validate_args


def _args(**overrides) -> Namespace:
    values = {
        "hidden_size": 16,
        "num_layers": 2,
        "batch_size": 4,
        "learning_rate": 1.0e-3,
        "timeout_seconds": 60,
    }
    values.update(overrides)
    return Namespace(**values)


def test_rank_zero_full_state_is_cpu_prefixed_and_deterministic():
    model = TinyTrainingModel(hidden_size=16, num_layers=2)

    first = _rank_zero_full_state(model, rank=0)
    second = _rank_zero_full_state(model, rank=0)

    assert first is not None
    assert second is not None
    assert set(first) == {
        "model.layers.0.weight",
        "model.layers.0.bias",
        "model.layers.1.weight",
        "model.layers.1.bias",
        "model.norm.weight",
        "model.norm.bias",
        "model.head.weight",
    }
    for key, value in first.items():
        assert value.device.type == "cpu"
        assert value.equal(second[key])


def test_nonzero_rank_does_not_construct_full_state():
    model = TinyTrainingModel(hidden_size=16, num_layers=2)

    assert _rank_zero_full_state(model, rank=1) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("hidden_size", 0),
        ("num_layers", -1),
        ("batch_size", 0),
        ("learning_rate", 0.0),
        ("timeout_seconds", -1),
    ],
)
def test_validate_args_rejects_nonpositive_values(field, value):
    with pytest.raises(ValueError, match="must be greater than zero"):
        _validate_args(_args(**{field: value}))
