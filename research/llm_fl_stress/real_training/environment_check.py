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

"""Emit one JSON record proving the container can see the requested GPUs."""

import json
import os

import torch
import torchvision
import transformers
from transformers.models.qwen2.modeling_qwen2 import Qwen2ForCausalLM

import nvflare


def main() -> None:
    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch cannot access CUDA")
    if os.environ.get("NCCL_P2P_DISABLE"):
        raise RuntimeError("NCCL_P2P_DISABLE must not be carried onto the NVLink A100 cluster")
    if not hasattr(torch.ops.torchvision, "nms"):
        raise RuntimeError("torchvision compiled operators did not register torchvision::nms")

    devices = [torch.cuda.get_device_name(index) for index in range(torch.cuda.device_count())]
    expected_count = int(os.environ.get("EXPECTED_GPU_COUNT", len(devices)))
    if len(devices) != expected_count:
        raise RuntimeError(f"expected {expected_count} visible GPUs, found {len(devices)}")
    expected_name = os.environ.get("EXPECTED_GPU_NAME_SUBSTRING")
    if expected_name and any(expected_name not in name for name in devices):
        raise RuntimeError(f"expected every GPU name to contain {expected_name!r}, got {devices}")
    result = {
        "event": "real_training_environment_check",
        "status": "PASS",
        "cuda_devices": devices,
        "cuda_device_count": len(devices),
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
