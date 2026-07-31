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

from research.llm_fl_stress.real_training import model_structure_preflight as preflight


def _model(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    (model / "REVISION").write_text("revision\n", encoding="utf-8")
    (model / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["Qwen2ForCausalLM"],
                "model_type": "qwen2",
                "torch_dtype": "bfloat16",
                "hidden_size": 5120,
                "intermediate_size": 27648,
                "num_hidden_layers": 64,
                "num_attention_heads": 40,
                "num_key_value_heads": 8,
            }
        ),
        encoding="utf-8",
    )
    (model / "model-00001-of-00002.safetensors").write_bytes(b"first")
    (model / "model-00002-of-00002.safetensors").write_bytes(b"second")
    return model


def _validate(model, monkeypatch, **overrides):
    monkeypatch.setattr(
        preflight,
        "validate_indexed_safetensors",
        lambda *_args, **_kwargs: {
            "indexed_tensor_count": 3,
            "index_total_size_bytes": 12,
            "computed_tensor_bytes": 12,
            "validated_safetensor_files": [
                "model-00001-of-00002.safetensors",
                "model-00002-of-00002.safetensors",
            ],
            "validated_safetensor_file_count": 2,
        },
    )
    values = {
        "model_revision": "revision",
        "expected_hidden_size": 5120,
        "expected_intermediate_size": 27648,
        "expected_num_hidden_layers": 64,
        "expected_num_attention_heads": 40,
        "expected_num_key_value_heads": 8,
        "expected_safetensor_files": 2,
        "expected_tensor_count": 3,
        "expected_parameters": 6,
        "expected_tensor_bytes": 12,
        "expected_checkpoint_file_bytes": 11,
    }
    values.update(overrides)
    return preflight.validate_model_structure(model, **values)


def test_structure_preflight_separates_logical_and_physical_bytes(tmp_path, monkeypatch):
    result = _validate(_model(tmp_path), monkeypatch)

    assert result["status"] == "PASS"
    assert result["parameter_count"] == 6
    assert result["logical_state_payload_bytes"] == 12
    assert result["physical_checkpoint_file_bytes"] == 11
    assert result["tensor_payload_materialized"] is False
    assert result["gpu_required"] is False


def test_structure_preflight_rejects_non_bf16_byte_contract(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="two bytes per parameter"):
        _validate(_model(tmp_path), monkeypatch, expected_tensor_bytes=13)


def test_structure_preflight_rejects_physical_checkpoint_mismatch(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="physical checkpoint byte mismatch"):
        _validate(_model(tmp_path), monkeypatch, expected_checkpoint_file_bytes=12)


def test_dataset_preflight_requires_enough_unique_valid_records(tmp_path):
    dataset = tmp_path / "site-1.jsonl"
    dataset.write_text(
        "".join(json.dumps({"id": f"sample-{index}", "text": f"text {index}"}) + "\n" for index in range(16)),
        encoding="utf-8",
    )

    result = preflight.validate_dataset(dataset, minimum_records=16)

    assert result["record_count"] == 16
    assert result["unique_ids"] == 16
    with pytest.raises(RuntimeError, match="requires at least 17"):
        preflight.validate_dataset(dataset, minimum_records=17)
