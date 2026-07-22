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

from pathlib import Path

import pytest

from research.llm_fl_stress.real_training.config import RealTrainingConfig, validate_local_model_dir


def _make_model_dir(tmp_path: Path) -> Path:
    model_path = tmp_path / "model"
    model_path.mkdir()
    for name in ("config.json", "tokenizer_config.json", "tokenizer.json", "model.safetensors"):
        (model_path / name).write_text("{}")
    return model_path


def _config(model_path: Path, **overrides) -> RealTrainingConfig:
    values = {
        "model_path": model_path,
        "workspace_root": model_path.parent / "workspace",
        "export_root": model_path.parent / "export",
        "nproc_per_node": 4,
        "num_rounds": 1,
        "local_steps": 1,
        "max_length": 128,
        "learning_rate": 1.0e-5,
        "trainable_target": "last-layer",
        "run_mode": "train",
    }
    values.update(overrides)
    return RealTrainingConfig(**values)


def test_valid_local_snapshot_passes(tmp_path):
    model_path = _make_model_dir(tmp_path)

    _config(model_path).validate()


@pytest.mark.parametrize(
    "missing_name,match",
    [
        ("config.json", "config.json"),
        ("tokenizer_config.json", "tokenizer_config.json"),
        ("tokenizer.json", "tokenizer data"),
        ("model.safetensors", "weight files"),
    ],
)
def test_incomplete_local_snapshot_is_rejected(tmp_path, missing_name, match):
    model_path = _make_model_dir(tmp_path)
    (model_path / missing_name).unlink()

    with pytest.raises(ValueError, match=match):
        validate_local_model_dir(model_path)


def test_remote_identifier_is_rejected():
    with pytest.raises(ValueError, match="absolute"):
        validate_local_model_dir(Path("Qwen/Qwen2.5-14B"))


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"nproc_per_node": 1}, "at least 2"),
        ({"num_rounds": 0}, "greater than zero"),
        ({"local_steps": 0}, "greater than zero"),
        ({"max_length": 0}, "greater than zero"),
        ({"learning_rate": 0.0}, "greater than zero"),
        ({"trainable_target": "unknown"}, "must be one of"),
        ({"run_mode": "unknown"}, "must be one of"),
    ],
)
def test_invalid_training_config_is_rejected(tmp_path, overrides, match):
    model_path = _make_model_dir(tmp_path)

    with pytest.raises(ValueError, match=match):
        _config(model_path, **overrides).validate()


def test_workspace_and_export_must_be_different(tmp_path):
    model_path = _make_model_dir(tmp_path)
    same_path = tmp_path / "same"

    with pytest.raises(ValueError, match="must be different"):
        _config(model_path, workspace_root=same_path, export_root=same_path).validate()
