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
import math
import struct

import pytest

from research.llm_fl_stress.real_training import trainable_server_preflight as preflight

_DTYPE_BYTES = {"BF16": 2, "F32": 4}


def _save_safetensors(path, tensors):
    """Write a minimal valid safetensor without materializing tensors in torch."""

    header = {}
    offset = 0
    for name, (dtype, shape) in tensors.items():
        size = math.prod(shape) * _DTYPE_BYTES[dtype]
        header[name] = {"dtype": dtype, "shape": shape, "data_offsets": [offset, offset + size]}
        offset += size
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    header_bytes += b" " * (-len(header_bytes) % 8)
    path.write_bytes(struct.pack("<Q", len(header_bytes)) + header_bytes + bytes(offset))
    return offset


def _write_indexed_snapshot(tmp_path):
    model_path = tmp_path / "indexed-model"
    model_path.mkdir()
    shards = {
        "model-00001-of-00002.safetensors": {
            "model.layers.0.input_layernorm.weight": ("BF16", [8]),
            "model.layers.0.self_attn.q_proj.weight": ("BF16", [4, 8]),
        },
        "model-00002-of-00002.safetensors": {
            "model.layers.1.input_layernorm.weight": ("BF16", [8]),
            "model.layers.1.mlp.down_proj.weight": ("BF16", [8, 6]),
        },
    }
    weight_map = {}
    total_size = 0
    for filename, state in shards.items():
        total_size += _save_safetensors(model_path / filename, state)
        for key in state:
            weight_map[key] = filename
    index = {"metadata": {"total_size": total_size}, "weight_map": weight_map}
    (model_path / "model.safetensors.index.json").write_text(json.dumps(index), encoding="utf-8")
    return model_path, index, total_size


def test_indexed_safetensor_validation_opens_every_shard_and_computes_exact_bytes(tmp_path, monkeypatch):
    model_path, index, total_size = _write_indexed_snapshot(tmp_path)
    real_safe_open = preflight.safe_open
    opened = []

    def recording_safe_open(path, *args, **kwargs):
        opened.append(path.name)
        return real_safe_open(path, *args, **kwargs)

    monkeypatch.setattr(preflight, "safe_open", recording_safe_open)

    result = preflight.validate_indexed_safetensors(
        model_path,
        expected_safetensor_files=2,
        expected_tensor_bytes=total_size,
    )

    assert opened == sorted(set(index["weight_map"].values()))
    assert result["indexed_tensor_count"] == len(index["weight_map"])
    assert result["index_total_size_bytes"] == total_size
    assert result["computed_tensor_bytes"] == total_size
    assert result["validated_safetensor_file_count"] == 2


def test_unindexed_single_safetensor_is_structurally_validated(tmp_path):
    model_path = tmp_path / "unindexed-model"
    model_path.mkdir()
    state = {
        "model.layers.0.input_layernorm.weight": ("BF16", [8]),
        "model.layers.0.self_attn.q_proj.weight": ("BF16", [4, 8]),
    }
    total_size = _save_safetensors(model_path / "model.safetensors", state)

    result = preflight.validate_indexed_safetensors(
        model_path,
        expected_safetensor_files=1,
        expected_tensor_bytes=total_size,
    )

    assert result["index_path"] is None
    assert result["indexed_tensor_count"] == len(state)
    assert result["computed_tensor_bytes"] == total_size
    assert result["validated_safetensor_files"] == ["model.safetensors"]


def test_unindexed_multi_shard_model_is_rejected(tmp_path):
    model_path = tmp_path / "unindexed-model"
    model_path.mkdir()
    _save_safetensors(model_path / "model-00001-of-00002.safetensors", {"a": ("F32", [1])})
    _save_safetensors(model_path / "model-00002-of-00002.safetensors", {"b": ("F32", [1])})

    with pytest.raises(RuntimeError, match="exactly one"):
        preflight.validate_indexed_safetensors(model_path)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"expected_safetensor_files": -1}, "expected_safetensor_files"),
        ({"expected_tensor_bytes": -1}, "expected_tensor_bytes"),
    ],
)
def test_safetensor_validation_rejects_negative_expectations(tmp_path, kwargs, match):
    with pytest.raises(ValueError, match=match):
        preflight.validate_indexed_safetensors(tmp_path, **kwargs)


def test_indexed_safetensor_validation_rejects_metadata_total_size_mismatch(tmp_path):
    model_path, index, _ = _write_indexed_snapshot(tmp_path)
    index["metadata"]["total_size"] += 2
    (model_path / "model.safetensors.index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(RuntimeError, match="index total-size mismatch"):
        preflight.validate_indexed_safetensors(model_path, expected_safetensor_files=2)


def test_indexed_safetensor_validation_rejects_expected_tensor_bytes_mismatch(tmp_path):
    model_path, _, total_size = _write_indexed_snapshot(tmp_path)

    with pytest.raises(RuntimeError, match="tensor bytes mismatch"):
        preflight.validate_indexed_safetensors(
            model_path,
            expected_safetensor_files=2,
            expected_tensor_bytes=total_size + 2,
        )


def test_indexed_safetensor_validation_rejects_on_disk_shard_set_mismatch(tmp_path):
    model_path, _, _ = _write_indexed_snapshot(tmp_path)
    _save_safetensors(model_path / "model-00003-of-00003.safetensors", {"unexpected": ("F32", [1])})

    with pytest.raises(RuntimeError, match="shard-set mismatch"):
        preflight.validate_indexed_safetensors(model_path, expected_safetensor_files=2)


def test_indexed_safetensor_validation_rejects_exact_shard_key_mismatch(tmp_path):
    model_path, index, _ = _write_indexed_snapshot(tmp_path)
    original_key = next(iter(index["weight_map"]))
    filename = index["weight_map"].pop(original_key)
    index["weight_map"]["model.layers.0.unexpected.weight"] = filename
    (model_path / "model.safetensors.index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(RuntimeError, match="shard key mismatch"):
        preflight.validate_indexed_safetensors(model_path, expected_safetensor_files=2)


def test_indexed_safetensor_validation_rejects_corrupt_nonselected_shard(tmp_path):
    model_path, _, _ = _write_indexed_snapshot(tmp_path)
    shard = model_path / "model-00001-of-00002.safetensors"
    shard.write_bytes(shard.read_bytes()[:32])

    with pytest.raises(RuntimeError, match="cannot structurally open"):
        preflight.validate_indexed_safetensors(model_path, expected_safetensor_files=2)
