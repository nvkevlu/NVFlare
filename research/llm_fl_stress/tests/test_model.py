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

import unittest

try:
    import torch
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "PyTorch is not installed")
class SyntheticShardModelTest(unittest.TestCase):
    def test_parameter_count_dtype_and_sharding_are_exact(self):
        from research.llm_fl_stress.model import SyntheticShardModel

        model = SyntheticShardModel(parameter_count=13, dtype="float32", tensor_shard_mib=1)

        self.assertEqual(13, sum(parameter.numel() for parameter in model.parameters()))
        self.assertTrue(all(parameter.dtype == torch.float32 for parameter in model.parameters()))
        self.assertTrue(all(not parameter.requires_grad for parameter in model.parameters()))


if __name__ == "__main__":
    unittest.main()
