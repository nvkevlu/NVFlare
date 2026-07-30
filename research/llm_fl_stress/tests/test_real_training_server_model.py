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

import json

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
from safetensors.torch import save_file  # noqa: E402
from transformers import BertConfig, Qwen2Config  # noqa: E402
from transformers.models.qwen2.modeling_qwen2 import Qwen2DecoderLayer  # noqa: E402

from research.llm_fl_stress.real_training import model as server_model  # noqa: E402


def _write_tiny_qwen_snapshot(tmp_path):
    model_path = tmp_path / "tiny-qwen"
    model_path.mkdir()
    config = Qwen2Config(
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        torch_dtype="bfloat16",
    )
    config.architectures = ["Qwen2ForCausalLM"]
    config.save_pretrained(model_path)
    layer = Qwen2DecoderLayer(config, 1).to(dtype=torch.bfloat16)
    state = {}
    for index, (name, parameter) in enumerate(layer.named_parameters(), start=1):
        state[f"model.layers.1.{name}"] = torch.full_like(parameter, float(index))
    shard_name = "model-00001-of-00001.safetensors"
    save_file(state, model_path / shard_name)
    (model_path / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {}, "weight_map": {key: shard_name for key in state}}),
        encoding="utf-8",
    )
    return model_path, state


def test_trainable_server_model_loads_only_last_layer_with_client_keys(tmp_path, monkeypatch):
    model_path, expected = _write_tiny_qwen_snapshot(tmp_path)
    cleanup_calls = []
    monkeypatch.setattr(server_model, "cleanup_memory", lambda: cleanup_calls.append(True))

    model = server_model.HFTrainableStateModel(str(model_path))

    observed = model.state_dict()
    assert set(observed) == {key.replace("model.layers.", "model.model.layers.") for key in expected}
    for key, value in expected.items():
        assert torch.equal(observed[key.replace("model.layers.", "model.model.layers.")], value)
    assert cleanup_calls == [True]
    with pytest.raises(RuntimeError, match="state container"):
        model(torch.ones(1, 1, 16))


def test_trainable_server_model_rejects_unsupported_architecture(tmp_path):
    model_path = tmp_path / "unsupported"
    model_path.mkdir()
    config = BertConfig()
    config.architectures = ["BertModel"]
    config.save_pretrained(model_path)

    with pytest.raises(RuntimeError, match="unsupported"):
        server_model.HFTrainableStateModel(str(model_path))


def test_trainable_server_model_rejects_incomplete_last_layer(tmp_path):
    model_path, state = _write_tiny_qwen_snapshot(tmp_path)
    missing_key = next(iter(state))
    index_path = model_path / "model.safetensors.index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    del index["weight_map"][missing_key]
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(RuntimeError, match="schema mismatch"):
        server_model.HFTrainableStateModel(str(model_path))


def test_qwen25_72b_last_layer_has_exact_qualification_payload():
    config = Qwen2Config(
        hidden_size=8192,
        intermediate_size=29568,
        num_hidden_layers=80,
        num_attention_heads=64,
        num_key_value_heads=8,
        torch_dtype="bfloat16",
    )
    with torch.device("meta"):
        layer = Qwen2DecoderLayer(config, 79)

    parameters = dict(layer.named_parameters())
    assert len(parameters) == 12
    assert sum(parameter.numel() for parameter in parameters.values()) == 877_684_736
    assert sum(parameter.numel() * 2 for parameter in parameters.values()) == 1_755_369_472
