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

"""Server-side wrapper for a local Hugging Face causal language model."""

import json
from pathlib import Path

import torch
from safetensors import safe_open
from transformers import AutoConfig, AutoModelForCausalLM
from transformers.models.qwen2.modeling_qwen2 import Qwen2DecoderLayer

from nvflare.fuel.utils.memory_utils import cleanup_memory


class HFTextModel(torch.nn.Module):
    """Load a CPU BF16 model whose state keys have the ``model.`` prefix."""

    def __init__(self, model_name_or_path: str, revision: str | None = None):
        super().__init__()
        self.model = AutoModelForCausalLM.from_pretrained(
            model_name_or_path,
            revision=revision,
            local_files_only=True,
            trust_remote_code=False,
            dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
        )

    def forward(self, *args, **kwargs):
        return self.model(*args, **kwargs)


class HFTrainableStateModel(torch.nn.Module):
    """Load only the final Qwen2 decoder layer with client-compatible state keys."""

    def __init__(self, model_name_or_path: str, revision: str | None = None):
        super().__init__()
        model_path = Path(model_name_or_path)
        config = AutoConfig.from_pretrained(
            model_name_or_path,
            revision=revision,
            local_files_only=True,
            trust_remote_code=False,
        )
        if config.model_type != "qwen2" or config.architectures != ["Qwen2ForCausalLM"]:
            raise RuntimeError(f"unsupported model architecture {config.model_type!r}: expected Qwen2ForCausalLM")
        if config.torch_dtype != torch.bfloat16:
            raise RuntimeError(f"unsupported model dtype {config.torch_dtype!r}: expected torch.bfloat16")
        if not isinstance(config.num_hidden_layers, int) or config.num_hidden_layers <= 0:
            raise RuntimeError(f"invalid Qwen2 decoder-layer count: {config.num_hidden_layers!r}")

        last_index = config.num_hidden_layers - 1
        with torch.device("meta"):
            selected_layer = Qwen2DecoderLayer(config, last_index)
        selected_layer.to(dtype=torch.bfloat16)
        selected_layer.to_empty(device="cpu")
        self._load_selected_layer(model_path, last_index, selected_layer)

        # FedAvg persists and aggregates this sparse server module. Identity
        # placeholders retain the exact external keys used by the full client:
        # model.model.layers.<last_index>.*
        self.model = torch.nn.Module()
        self.model.model = torch.nn.Module()
        self.model.model.layers = torch.nn.ModuleList(
            [torch.nn.Identity() for _ in range(last_index)] + [selected_layer]
        )
        parameter_keys = set(dict(self.named_parameters()))
        if not parameter_keys:
            raise RuntimeError("last decoder layer selected no server parameters")
        if set(self.state_dict()) != parameter_keys:
            raise RuntimeError("trainable server state contains non-parameter entries")
        cleanup_memory()

    @staticmethod
    def _weight_map(model_path: Path) -> dict[str, Path]:
        index_path = model_path / "model.safetensors.index.json"
        if index_path.is_file():
            index = json.loads(index_path.read_text(encoding="utf-8"))
            weight_map = index.get("weight_map")
            if not isinstance(weight_map, dict) or not weight_map:
                raise RuntimeError(f"invalid safetensor weight map: {index_path}")
            result = {}
            for key, filename in weight_map.items():
                shard = model_path / filename
                if not shard.is_file():
                    raise RuntimeError(f"safetensor weight {key!r} references missing shard: {shard}")
                result[key] = shard
            return result

        weight_files = sorted(model_path.glob("model*.safetensors"))
        if len(weight_files) != 1:
            raise RuntimeError(
                f"model must contain one unsharded safetensor or an index, found {len(weight_files)} files"
            )
        with safe_open(weight_files[0], framework="pt", device="cpu") as stream:
            return {key: weight_files[0] for key in stream.keys()}

    @classmethod
    def _load_selected_layer(
        cls,
        model_path: Path,
        layer_index: int,
        selected_layer: torch.nn.Module,
    ) -> None:
        weight_map = cls._weight_map(model_path)
        source_prefix = f"model.layers.{layer_index}."
        parameters = dict(selected_layer.named_parameters())
        source_keys = {key for key in weight_map if key.startswith(source_prefix)}
        expected_keys = {f"{source_prefix}{name}" for name in parameters}
        if source_keys != expected_keys:
            raise RuntimeError(
                f"final decoder-layer safetensor schema mismatch: "
                f"missing={sorted(expected_keys - source_keys)}, unexpected={sorted(source_keys - expected_keys)}"
            )

        keys_by_shard: dict[Path, list[tuple[str, str]]] = {}
        for relative_name in parameters:
            source_key = f"{source_prefix}{relative_name}"
            keys_by_shard.setdefault(weight_map[source_key], []).append((relative_name, source_key))

        with torch.no_grad():
            for shard_path, keys in keys_by_shard.items():
                with safe_open(shard_path, framework="pt", device="cpu") as stream:
                    for relative_name, source_key in keys:
                        tensor = stream.get_tensor(source_key)
                        parameter = parameters[relative_name]
                        if tensor.dtype != torch.bfloat16:
                            raise RuntimeError(
                                f"final decoder-layer tensor {source_key!r} has dtype {tensor.dtype}, "
                                "expected torch.bfloat16"
                            )
                        if tensor.shape != parameter.shape:
                            raise RuntimeError(
                                f"final decoder-layer tensor {source_key!r} has shape {tuple(tensor.shape)}, "
                                f"expected {tuple(parameter.shape)}"
                            )
                        parameter.copy_(tensor)

    def forward(self, *_args, **_kwargs):
        raise RuntimeError("HFTrainableStateModel is a server-side state container and cannot run forward")
