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

import ast
from pathlib import Path

import pytest

LOGIN_VALIDATORS = [
    Path("research/llm_fl_stress/real_training/cs_oci_ord/validate_14b_full_model_readiness.py"),
    Path("research/llm_fl_stress/real_training/cs_oci_ord/validate_72b_readiness.py"),
]

POST_PYTHON38_RUNTIME_APIS = [
    ".is_relative_to(",
    ".removeprefix(",
    ".removesuffix(",
]


@pytest.mark.parametrize("validator", LOGIN_VALIDATORS)
def test_login_readiness_validator_preserves_python38_contract(validator):
    source = validator.read_text(encoding="utf-8")

    ast.parse(source, filename=str(validator), feature_version=8)
    for api in POST_PYTHON38_RUNTIME_APIS:
        assert api not in source, f"{validator} uses post-Python-3.8 API {api}"
