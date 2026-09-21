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

"""Validate an absolute-path CUDA Runtime load before importing PyTorch."""

from __future__ import annotations

import ctypes
import importlib.metadata
import os
from pathlib import Path
import re
import sys


_ALLOWED_DISTRIBUTIONS = {"nvidia-cuda-runtime"}
_LINUX_CUDART_NAME = re.compile(r"^libcudart\.so(?:\.\d+)*$")


def _normalized_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def find_bundled_cudart() -> Path:
    candidates: set[Path] = set()
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name", "")
        if _normalized_distribution_name(name) not in _ALLOWED_DISTRIBUTIONS:
            continue
        for owned_file in distribution.files or ():
            if not _LINUX_CUDART_NAME.fullmatch(Path(owned_file).name):
                continue
            candidate = Path(distribution.locate_file(owned_file))
            if candidate.is_symlink() or not candidate.is_file():
                continue
            candidate = candidate.resolve(strict=True)
            if candidate.stat().st_size > 0:
                candidates.add(candidate)
    if len(candidates) != 1:
        rendered = ", ".join(str(path) for path in sorted(candidates)) or "none"
        raise RuntimeError(f"expected one NVIDIA-owned CUDA Runtime; found: {rendered}")
    return candidates.pop()


def load_and_count_devices(path: Path) -> tuple[ctypes.CDLL, int]:
    mode = getattr(os, "RTLD_LOCAL", 0) | getattr(os, "RTLD_NOW", 0)
    runtime = ctypes.CDLL(str(path), mode=mode)
    cuda_get_device_count = runtime.cudaGetDeviceCount
    cuda_get_device_count.argtypes = [ctypes.POINTER(ctypes.c_int)]
    cuda_get_device_count.restype = ctypes.c_int
    count = ctypes.c_int()
    result = cuda_get_device_count(ctypes.byref(count))
    if result != 0:
        raise RuntimeError(f"cudaGetDeviceCount failed with CUDA error {result}")
    return runtime, count.value


print(f"python={sys.executable}")
print(f"cuda_visible_devices={os.environ.get('CUDA_VISIBLE_DEVICES')!r}")
print(f"torch_loaded_before_probe={'torch' in sys.modules}")
cudart_path = find_bundled_cudart()
print(f"bundled_cudart={cudart_path}")
_runtime, pre_torch_count = load_and_count_devices(cudart_path)
print(f"pre_torch_cuda_device_count={pre_torch_count}")
print(f"torch_loaded_after_probe={'torch' in sys.modules}")

import torch  # noqa: E402

print(f"torch_version={torch.__version__}")
print(f"torch_cuda_version={torch.version.cuda}")
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
