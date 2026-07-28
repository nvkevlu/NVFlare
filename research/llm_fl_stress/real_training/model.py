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

import torch
from transformers import AutoModelForCausalLM

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
    """Expose only the final decoder layer while retaining client-compatible keys."""

    def __init__(self, model_name_or_path: str, revision: str | None = None):
        super().__init__()
        loaded_model = AutoModelForCausalLM.from_pretrained(
            model_name_or_path,
            revision=revision,
            local_files_only=True,
            trust_remote_code=False,
            dtype=torch.bfloat16,
            low_cpu_mem_usage=True,
        )
        base = getattr(loaded_model, "model", None)
        layers = getattr(base, "layers", None)
        if not isinstance(layers, torch.nn.ModuleList) or not layers:
            model_type = getattr(getattr(loaded_model, "config", None), "model_type", type(loaded_model).__name__)
            raise RuntimeError(
                f"unsupported model architecture {model_type!r}: expected a non-empty model.layers ModuleList"
            )

        last_index = len(layers) - 1
        selected_layer = layers[last_index]
        layers[last_index] = torch.nn.Identity()
        for module in selected_layer.modules():
            for buffer_name in tuple(module._buffers):
                module._buffers[buffer_name] = None

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
        del layers, base, loaded_model
        cleanup_memory()

    def forward(self, *_args, **_kwargs):
        raise RuntimeError("HFTrainableStateModel is a server-side state container and cannot run forward")
