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

"""Fail a CPU preparation job if the pinned distributed APIs are unavailable."""

import json

import torch
import torchvision
import transformers
from torch.distributed.checkpoint.state_dict import StateDictOptions, get_model_state_dict, set_model_state_dict
from torch.distributed.fsdp import MixedPrecisionPolicy, fully_shard
from transformers.models.qwen2.modeling_qwen2 import Qwen2ForCausalLM

import nvflare
from nvflare.app_opt.pt.fsdp2_state_bridge import FSDP2StateBridge


def main() -> None:
    required_apis = (
        StateDictOptions,
        get_model_state_dict,
        set_model_state_dict,
        MixedPrecisionPolicy,
        fully_shard,
        FSDP2StateBridge,
        Qwen2ForCausalLM,
    )
    if not all(required_apis):
        raise RuntimeError("one or more required FSDP2 state APIs are unavailable")
    if not torch.__version__.startswith("2.12.0"):
        raise RuntimeError(f"expected PyTorch 2.12.0, got {torch.__version__}")
    if torch.version.cuda != "12.6":
        raise RuntimeError(f"expected a cu126 PyTorch build, got torch.version.cuda={torch.version.cuda!r}")
    if not torchvision.__version__.startswith("0.27.0+cu126"):
        raise RuntimeError(f"expected torchvision 0.27.0+cu126, got {torchvision.__version__}")
    if not hasattr(torch.ops.torchvision, "nms"):
        raise RuntimeError("torchvision compiled operators did not register torchvision::nms")
    result = {
        "event": "real_training_dependency_check",
        "status": "PASS",
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "torchvision_version": torchvision.__version__,
        "transformers_version": transformers.__version__,
        "qwen2_model_class": Qwen2ForCausalLM.__name__,
        "nvflare_version": nvflare.__version__,
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
