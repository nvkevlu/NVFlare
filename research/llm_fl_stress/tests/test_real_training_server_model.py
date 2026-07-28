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

from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")

from research.llm_fl_stress.real_training import model as server_model  # noqa: E402


class TinyCausalLM(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.model = torch.nn.Module()
        self.model.layers = torch.nn.ModuleList([torch.nn.Linear(2, 2, bias=False), torch.nn.Linear(2, 2, bias=False)])
        self.model.layers[-1].register_buffer("scale", torch.tensor(2.0))
        self.lm_head = torch.nn.Linear(2, 4, bias=False)
        self.config = SimpleNamespace(model_type="tiny")


def test_trainable_server_model_retains_only_last_layer_with_client_keys(monkeypatch):
    loaded = TinyCausalLM()
    monkeypatch.setattr(
        server_model.AutoModelForCausalLM,
        "from_pretrained",
        lambda *_args, **_kwargs: loaded,
    )
    cleanup_calls = []
    monkeypatch.setattr(server_model, "cleanup_memory", lambda: cleanup_calls.append(True))

    model = server_model.HFTrainableStateModel("/models/tiny", revision="revision")

    assert list(model.state_dict()) == ["model.model.layers.1.weight"]
    assert model.state_dict()["model.model.layers.1.weight"].shape == (2, 2)
    assert cleanup_calls == [True]
    with pytest.raises(RuntimeError, match="state container"):
        model(torch.ones(1, 2))


def test_trainable_server_model_rejects_unsupported_architecture(monkeypatch):
    loaded = torch.nn.Linear(2, 2)
    loaded.config = SimpleNamespace(model_type="unsupported")
    monkeypatch.setattr(
        server_model.AutoModelForCausalLM,
        "from_pretrained",
        lambda *_args, **_kwargs: loaded,
    )

    with pytest.raises(RuntimeError, match="unsupported"):
        server_model.HFTrainableStateModel("/models/tiny")
