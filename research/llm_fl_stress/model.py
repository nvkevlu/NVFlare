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

"""Exact-size synthetic PyTorch model for server data-plane stress tests."""

import torch
from torch import nn


_DTYPES = {
    "float16": torch.float16,
    "bfloat16": torch.bfloat16,
    "float32": torch.float32,
}


class SyntheticShardModel(nn.Module):
    """A parameter-only model split into bounded tensors.

    It deliberately has no useful forward pass. The harness exercises FLARE model
    distribution, streamed return, aggregation, and persistence without coupling
    server measurements to a tokenizer, dataset, or transformer implementation.
    """

    def __init__(self, parameter_count: int, dtype: str, tensor_shard_mib: int = 256):
        super().__init__()
        if parameter_count <= 0:
            raise ValueError("parameter_count must be positive")
        if dtype not in _DTYPES:
            raise ValueError(f"dtype must be one of {sorted(_DTYPES)}")
        if tensor_shard_mib <= 0:
            raise ValueError("tensor_shard_mib must be positive")

        torch_dtype = _DTYPES[dtype]
        element_size = torch.empty((), dtype=torch_dtype).element_size()
        elements_per_shard = max(1, tensor_shard_mib * 1024 * 1024 // element_size)
        remaining = parameter_count
        parameters = []
        while remaining:
            shard_elements = min(elements_per_shard, remaining)
            parameters.append(nn.Parameter(torch.zeros(shard_elements, dtype=torch_dtype), requires_grad=False))
            remaining -= shard_elements
        self.shards = nn.ParameterList(parameters)

    def forward(self, *_args, **_kwargs):
        raise RuntimeError("SyntheticShardModel is exchange-only and does not implement forward()")
