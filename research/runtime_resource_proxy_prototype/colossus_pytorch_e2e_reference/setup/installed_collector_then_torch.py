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

"""Exercise the installed NVFlare capacity probe before importing PyTorch."""

from __future__ import annotations

import json
import sys

from nvflare.private.fed.resource_stats.collector import probe_capacity


print(f"torch_loaded_before_probe={'torch' in sys.modules}")
capacity = probe_capacity()
print("capacity=" + json.dumps(capacity, sort_keys=True, separators=(",", ":")))
print(f"torch_loaded_after_probe={'torch' in sys.modules}")

gpu_groups = capacity.get("gpu", {}).get("groups", [])
if len(gpu_groups) != 1 or gpu_groups[0].get("kind") != "full_gpu" or gpu_groups[0].get("count") != 1:
    raise RuntimeError(f"expected one full GPU from the production probe; got {gpu_groups!r}")

import torch  # noqa: E402

print(f"torch_version={torch.__version__}")
print(f"torch_cuda_available={torch.cuda.is_available()}")
print(f"torch_cuda_device_count={torch.cuda.device_count()}")
print(f"torch_cuda_device_0={torch.cuda.get_device_name(0)}")
left = torch.randn((2048, 2048), device="cuda")
right = torch.randn((2048, 2048), device="cuda")
product = left @ right
torch.cuda.synchronize()
print(f"matmul_shape={tuple(product.shape)}")
print(f"matmul_device={product.device}")
print(f"matmul_finite={bool(torch.isfinite(product).all().item())}")
