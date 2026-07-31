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

import pytest

torch = pytest.importorskip("torch")

from research.llm_fl_stress.real_training.full_state_server_preflight import _validate_materialized_state


def test_materialized_full_state_requires_exact_bf16_schema_and_counts():
    state = {
        "model.layer.weight": torch.arange(8, dtype=torch.bfloat16).reshape(2, 4),
        "model.norm.weight": torch.ones(2, dtype=torch.bfloat16),
    }

    result = _validate_materialized_state(
        state,
        expected_payload_bytes=20,
        expected_tensor_count=2,
        expected_parameters=10,
    )

    assert result["payload_bytes"] == 20
    assert result["tensor_count"] == 2
    assert result["parameter_count"] == 10
    assert result["strategy"] == "schema-sha256-plus-bounded-values"


def test_materialized_full_state_rejects_non_bf16_state():
    with pytest.raises(RuntimeError, match="non-BF16"):
        _validate_materialized_state(
            {"model.weight": torch.ones(2, dtype=torch.float32)},
            expected_payload_bytes=8,
            expected_tensor_count=1,
            expected_parameters=2,
        )
