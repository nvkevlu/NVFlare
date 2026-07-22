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

"""Dependency-free validation shared by the real-training job and tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TRAINABLE_TARGETS = ("last-layer", "lm-head", "all")
RUN_MODES = ("exchange-only", "train")
_TOKENIZER_FILES = ("tokenizer.json", "tokenizer.model", "vocab.json")
_WEIGHT_PATTERNS = ("model*.safetensors", "pytorch_model*.bin")


@dataclass(frozen=True)
class RealTrainingConfig:
    model_path: Path
    workspace_root: Path
    export_root: Path
    nproc_per_node: int = 4
    num_rounds: int = 1
    local_steps: int = 1
    max_length: int = 128
    learning_rate: float = 1.0e-5
    trainable_target: str = "last-layer"
    run_mode: str = "train"

    def validate(self, require_model_files: bool = True) -> None:
        if require_model_files:
            validate_local_model_dir(self.model_path)
        elif not self.model_path.is_absolute():
            raise ValueError("model_path must be absolute")

        for name, value in (
            ("nproc_per_node", self.nproc_per_node),
            ("num_rounds", self.num_rounds),
            ("local_steps", self.local_steps),
            ("max_length", self.max_length),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")
        if self.nproc_per_node < 2:
            raise ValueError("nproc_per_node must be at least 2 for an FSDP2 qualification run")
        if self.learning_rate <= 0:
            raise ValueError("learning_rate must be greater than zero")
        if self.trainable_target not in TRAINABLE_TARGETS:
            choices = ", ".join(TRAINABLE_TARGETS)
            raise ValueError(f"trainable_target must be one of: {choices}")
        if self.run_mode not in RUN_MODES:
            choices = ", ".join(RUN_MODES)
            raise ValueError(f"run_mode must be one of: {choices}")
        if not self.workspace_root.is_absolute():
            raise ValueError("workspace_root must be absolute")
        if not self.export_root.is_absolute():
            raise ValueError("export_root must be absolute")
        if self.workspace_root == self.export_root:
            raise ValueError("workspace_root and export_root must be different directories")


def validate_local_model_dir(model_path: Path) -> None:
    """Reject remote identifiers and incomplete local Hugging Face snapshots."""

    if not model_path.is_absolute():
        raise ValueError("model_path must be absolute; remote model downloads are disabled during GPU jobs")
    if not model_path.is_dir():
        raise ValueError(f"model_path is not a directory: {model_path}")
    if not (model_path / "config.json").is_file():
        raise ValueError(f"model_path is missing config.json: {model_path}")
    if not (model_path / "tokenizer_config.json").is_file():
        raise ValueError(f"model_path is missing tokenizer_config.json: {model_path}")
    if not any((model_path / name).is_file() for name in _TOKENIZER_FILES):
        expected = ", ".join(_TOKENIZER_FILES)
        raise ValueError(f"model_path has no tokenizer data file ({expected}): {model_path}")
    if not any(any(model_path.glob(pattern)) for pattern in _WEIGHT_PATTERNS):
        raise ValueError(f"model_path has no safetensors or PyTorch weight files: {model_path}")
