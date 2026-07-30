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

from pathlib import Path

import pytest

from research.llm_fl_stress.real_training import real_model_fsdp2_gpu_gate as gate


def test_training_args_are_exactly_bounded_to_last_layer(tmp_path):
    args = gate._define_parser().parse_args(
        [
            "--model-name-or-path",
            str(tmp_path),
            "--model-revision",
            "revision",
            "--expected-payload-bytes",
            "1755369472",
        ]
    )

    gate._validate_args(args)
    training = gate._training_args(args)

    assert training.trainable_target == "last-layer"
    assert training.local_steps == 2
    assert training.max_length == 128
    assert training.timeout_seconds == 2400


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--expected-payload-bytes", "0"),
        ("--local-steps", "0"),
        ("--max-length", "0"),
        ("--timeout-seconds", "0"),
        ("--required-headroom-mib", "0"),
        ("--learning-rate", "0"),
    ],
)
def test_capacity_gate_rejects_nonpositive_limits(tmp_path, flag, value):
    argv = [
        "--model-name-or-path",
        str(tmp_path),
        "--model-revision",
        "revision",
        "--expected-payload-bytes",
        "1755369472",
        flag,
        value,
    ]
    args = gate._define_parser().parse_args(argv)

    with pytest.raises(ValueError, match="greater than zero"):
        gate._validate_args(args)


def test_capacity_gate_requires_existing_absolute_model_directory(tmp_path):
    args = gate._define_parser().parse_args(
        [
            "--model-name-or-path",
            str(Path("relative-model")),
            "--model-revision",
            "revision",
            "--expected-payload-bytes",
            "1755369472",
        ]
    )

    with pytest.raises(ValueError, match="existing absolute directory"):
        gate._validate_args(args)
