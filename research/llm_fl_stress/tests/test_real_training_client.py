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
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("nvflare")

from research.llm_fl_stress.real_training.client import (  # noqa: E402
    _decoder_layers,
    _select_trainable_parameters,
    _validate_args,
)


class TinyCausalLM(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.model = torch.nn.Module()
        self.model.layers = torch.nn.ModuleList([torch.nn.Linear(4, 4), torch.nn.Linear(4, 4)])
        self.lm_head = torch.nn.Linear(4, 8, bias=False)

    def get_output_embeddings(self):
        return self.lm_head


def test_last_layer_selection_freezes_every_other_parameter():
    model = TinyCausalLM()

    selected = _select_trainable_parameters(model, "last-layer")

    assert selected
    assert all(param.requires_grad for param in model.model.layers[-1].parameters())
    assert not any(param.requires_grad for param in model.model.layers[0].parameters())
    assert not any(param.requires_grad for param in model.lm_head.parameters())


def test_lm_head_selection_only_unfreezes_output_embeddings():
    model = TinyCausalLM()

    selected = _select_trainable_parameters(model, "lm-head")

    assert selected == list(model.lm_head.parameters())
    assert all(param.requires_grad for param in model.lm_head.parameters())
    assert not any(param.requires_grad for param in model.model.layers.parameters())


def test_unsupported_architecture_is_rejected():
    model = torch.nn.Linear(4, 4)
    model.config = SimpleNamespace(model_type="tiny-unsupported")

    with pytest.raises(RuntimeError, match="tiny-unsupported"):
        _decoder_layers(model)


def test_client_validation_requires_local_absolute_model_dir(tmp_path):
    args = Namespace(
        model_name_or_path=str(tmp_path),
        local_steps=1,
        max_length=128,
        timeout_seconds=60,
        learning_rate=1.0e-5,
    )

    _validate_args(args)

    args.model_name_or_path = "Qwen/Qwen2.5-14B"
    with pytest.raises(ValueError, match="absolute local path"):
        _validate_args(args)
