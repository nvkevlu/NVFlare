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

import json
from pathlib import Path

import pytest
import torch

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
    assert training.timeout_seconds == 7200
    assert args.expected_world_size == 4
    assert args.required_headroom_mib == 16384
    assert args.full_job_memory_gib == 1600
    assert args.full_job_client_count == 2
    assert args.required_fixed_host_headroom_gib == 128
    assert args.max_model_ready_seconds == 2400
    assert args.max_work_seconds == 1200


@pytest.mark.parametrize(
    ("flag", "value", "message"),
    [
        ("--expected-payload-bytes", "0", "greater than zero"),
        ("--expected-world-size", "0", "greater than zero"),
        ("--local-steps", "0", "greater than zero"),
        ("--max-length", "0", "greater than zero"),
        ("--timeout-seconds", "0", "greater than zero"),
        ("--required-headroom-mib", "-1", "must not be negative"),
        ("--full-job-memory-gib", "0", "greater than zero"),
        ("--full-job-client-count", "0", "greater than zero"),
        ("--required-fixed-host-headroom-gib", "0", "greater than zero"),
        ("--learning-rate", "0", "greater than zero"),
    ],
)
def test_capacity_gate_rejects_invalid_limits(tmp_path, flag, value, message):
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

    with pytest.raises(ValueError, match=message):
        gate._validate_args(args)


@pytest.mark.parametrize("flag", ["--max-model-ready-seconds", "--max-work-seconds"])
def test_capacity_gate_allows_zero_to_disable_elapsed_time_cutoffs(tmp_path, flag):
    args = gate._define_parser().parse_args(
        [
            "--model-name-or-path",
            str(tmp_path),
            "--model-revision",
            "revision",
            "--expected-payload-bytes",
            "1755369472",
            flag,
            "0",
        ]
    )

    gate._validate_args(args)


def test_capacity_gate_configures_all_parameter_full_state_lane(tmp_path):
    args = gate._define_parser().parse_args(
        [
            "--model-name-or-path",
            str(tmp_path),
            "--model-revision",
            "revision",
            "--expected-payload-bytes",
            "29540067328",
            "--expected-tensor-count",
            "579",
            "--expected-trainable-parameters",
            "14770033664",
            "--trainable-target",
            "all",
            "--state-scope",
            "full",
        ]
    )

    gate._validate_args(args)
    training = gate._training_args(args)
    assert training.trainable_target == "all"
    assert training.state_scope == "full"


def test_capacity_gate_requires_exact_tensor_count_for_all_parameter_lane(tmp_path):
    args = gate._define_parser().parse_args(
        [
            "--model-name-or-path",
            str(tmp_path),
            "--model-revision",
            "revision",
            "--expected-payload-bytes",
            "29540067328",
            "--expected-trainable-parameters",
            "14770033664",
            "--trainable-target",
            "all",
            "--state-scope",
            "full",
        ]
    )

    with pytest.raises(ValueError, match="requires --expected-tensor-count"):
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


def test_capacity_gate_accepts_single_client_projection(tmp_path):
    args = gate._define_parser().parse_args(
        [
            "--model-name-or-path",
            str(tmp_path),
            "--model-revision",
            "revision",
            "--expected-payload-bytes",
            "1755369472",
            "--full-job-client-count",
            "1",
        ]
    )

    gate._validate_args(args)
    assert args.full_job_client_count == 1


def test_full_job_host_projection_includes_two_clients_checkpoint_and_fixed_headroom():
    gib = 1024 * 1024 * 1024
    rank_metrics = [{"max_rss_bytes": value * gib} for value in (10, 20, 30, 40)]

    result = gate._full_job_host_projection(
        rank_metrics,
        state_payload_bytes=50 * gib,
        checkpoint_file_bytes=50 * gib + 100,
        full_job_memory_gib=1600,
        full_job_client_count=2,
        required_fixed_host_headroom_gib=128,
    )

    assert result == {
        "full_job_memory_gib": 1600,
        "full_job_memory_bytes": 1600 * gib,
        "full_job_client_count": 2,
        "required_fixed_host_headroom_gib": 128,
        "required_fixed_host_headroom_bytes": 128 * gib,
        "checkpoint_bytes": 50 * gib + 100,
        "checkpoint_file_bytes": 50 * gib + 100,
        "checkpoint_file_overhead_bytes": 100,
        "logical_state_payload_bytes": 50 * gib,
        "server_state_copies": 1,
        "server_state_reserve_bytes": 50 * gib + 100,
        "physical_server_state_reserve_bytes": 50 * gib + 100,
        "logical_server_state_reserve_bytes": 50 * gib,
        "one_client_rank_peak_rss_bytes": 100 * gib,
        "projected_full_job_rank_peak_rss_bytes": 200 * gib,
        "projected_full_job_host_bytes": 378 * gib + 100,
        "projected_full_job_host_headroom_bytes": 1222 * gib - 100,
        "physical_host_projection_basis": "checkpoint-files",
        "projected_physical_full_job_host_bytes": 378 * gib + 100,
        "projected_physical_full_job_host_headroom_bytes": 1222 * gib - 100,
        "logical_host_projection_basis": "logical-state-payload",
        "projected_logical_full_job_host_bytes": 378 * gib,
        "projected_logical_full_job_host_headroom_bytes": 1222 * gib,
    }


def test_full_model_host_projection_reserves_three_server_state_copies():
    gib = 1024 * 1024 * 1024
    result = gate._full_job_host_projection(
        [{"max_rss_bytes": 10 * gib} for _ in range(4)],
        state_payload_bytes=30 * gib,
        checkpoint_file_bytes=30 * gib + 100,
        full_job_memory_gib=512,
        full_job_client_count=2,
        required_fixed_host_headroom_gib=128,
        server_state_copies=3,
    )

    assert result["server_state_reserve_bytes"] == 90 * gib + 300
    assert result["logical_server_state_reserve_bytes"] == 90 * gib
    assert result["projected_logical_full_job_host_bytes"] == 298 * gib
    assert result["projected_logical_full_job_host_headroom_bytes"] == 214 * gib


@pytest.mark.parametrize(
    ("rank_metrics", "state_payload_bytes", "checkpoint_file_bytes", "match"),
    [
        ([{"max_rss_bytes": 0}], 1, 1, "rank peak RSS"),
        ([{"max_rss_bytes": "1"}], 1, 1, "rank peak RSS"),
        ([{"max_rss_bytes": 1}], 0, 1, "state payload bytes"),
        ([{"max_rss_bytes": 1}], 2, 1, "cannot be smaller"),
    ],
)
def test_full_job_host_projection_rejects_invalid_measurements(
    rank_metrics, state_payload_bytes, checkpoint_file_bytes, match
):
    with pytest.raises(RuntimeError, match=match):
        gate._full_job_host_projection(
            rank_metrics,
            state_payload_bytes=state_payload_bytes,
            checkpoint_file_bytes=checkpoint_file_bytes,
            full_job_memory_gib=1600,
            full_job_client_count=2,
            required_fixed_host_headroom_gib=128,
        )


def test_capacity_gate_accepts_exact_eight_rank_identity_set():
    gate._validate_rank_metrics([{"rank": rank, "local_rank": rank} for rank in range(8)], 8)


def test_capacity_gate_writes_one_atomic_result_document(tmp_path):
    result_path = tmp_path / "evidence" / "capacity-experiment.json"
    result = {"event": "real_model_fsdp2_gpu_capacity_gate", "status": "PASS"}

    gate._write_result(result_path, result)

    assert json.loads(result_path.read_text(encoding="utf-8")) == result
    assert not (result_path.parent / f".{result_path.name}.tmp").exists()


@pytest.mark.parametrize(
    ("rank_metrics", "match"),
    [
        ([{"rank": rank, "local_rank": rank} for rank in range(7)], "expected 8 gathered"),
        (
            [{"rank": 0 if rank == 7 else rank, "local_rank": rank} for rank in range(8)],
            "rank identities are incomplete or duplicated",
        ),
        (
            [{"rank": rank, "local_rank": 0 if rank == 7 else rank} for rank in range(8)],
            "local-rank identities are incomplete or duplicated",
        ),
    ],
)
def test_capacity_gate_rejects_inexact_eight_rank_identity_set(rank_metrics, match):
    with pytest.raises(RuntimeError, match=match):
        gate._validate_rank_metrics(rank_metrics, 8)


def test_capacity_gate_requires_exact_bf16_model_coverage():
    result = gate._require_exact_bf16_model(
        {
            "parameter_dtype_histogram": {
                "bfloat16": {"tensor_count": 771, "numel": 32763876352, "bytes": 65527752704}
            },
            "parameter_payload_bytes": 65527752704,
        },
        expected_parameters=32763876352,
        expected_tensor_count=771,
        expected_payload_bytes=65527752704,
    )

    assert result == {
        "status": "PASS",
        "dtype": "bfloat16",
        "parameter_count": 32763876352,
        "parameter_tensor_count": 771,
        "parameter_payload_bytes": 65527752704,
    }


def test_capacity_gate_collects_model_parameter_dtype_evidence():
    model = torch.nn.Linear(2, 3, dtype=torch.bfloat16)

    assert gate._model_dtype_evidence(model) == {
        "parameter_dtype_histogram": {
            "bfloat16": {"tensor_count": 2, "numel": 9, "bytes": 18},
        },
        "parameter_payload_bytes": 18,
    }


@pytest.mark.parametrize(
    ("evidence", "expected_payload_bytes", "match"),
    [
        (
            {
                "parameter_dtype_histogram": {
                    "bfloat16": {"tensor_count": 770, "numel": 32763876352, "bytes": 65527752704}
                },
                "parameter_payload_bytes": 65527752704,
            },
            65527752704,
            "coverage mismatch",
        ),
        (
            {
                "parameter_dtype_histogram": {
                    "bfloat16": {"tensor_count": 771, "numel": 32763876352, "bytes": 65527752704},
                    "float32": {"tensor_count": 1, "numel": 1, "bytes": 4},
                },
                "parameter_payload_bytes": 65527752708,
            },
            65527752704,
            "not entirely BF16",
        ),
        (
            {
                "parameter_dtype_histogram": {
                    "bfloat16": {"tensor_count": 771, "numel": 32763876352, "bytes": 65527752704}
                },
                "parameter_payload_bytes": 65527752704,
            },
            65527841752,
            "inconsistent with the exact BF16 parameter count",
        ),
    ],
)
def test_capacity_gate_rejects_inexact_bf16_model_coverage(evidence, expected_payload_bytes, match):
    with pytest.raises(RuntimeError, match=match):
        gate._require_exact_bf16_model(
            evidence,
            expected_parameters=32763876352,
            expected_tensor_count=771,
            expected_payload_bytes=expected_payload_bytes,
        )


def test_rank_zero_final_state_validation_is_synchronized_before_gather():
    source = Path(gate.__file__).read_text(encoding="utf-8")

    synchronized = source.index("final_validation_error = _collect_first_error(final_validation_error)")
    gathered = source.index("dist.gather_object(local_metrics, gathered, dst=0)")

    assert synchronized < gathered


def _aggregated_bf16_adamw_evidence(*, numel=20, nbytes=40, foreach=False, fused=False):
    return {
        "optimizer_state": {
            "config": {"name": "AdamW", "foreach": foreach, "fused": fused},
            "global_dtype_histogram": {
                "bfloat16": {"tensor_count": 4, "numel": numel, "bytes": nbytes},
                "float32": {"tensor_count": 2, "numel": 2, "bytes": 8},
            },
        }
    }


def test_capacity_gate_requires_exact_bf16_adamw_moments():
    result = gate._require_exact_bf16_adamw_moments(_aggregated_bf16_adamw_evidence(), 10)

    assert result == {
        "status": "PASS",
        "dtype": "bfloat16",
        "trainable_parameters": 10,
        "moment_values": 20,
        "moment_bytes": 40,
        "foreach": False,
        "fused": False,
    }


@pytest.mark.parametrize(
    ("evidence", "match"),
    [
        (_aggregated_bf16_adamw_evidence(numel=19), "moment coverage mismatch"),
        (_aggregated_bf16_adamw_evidence(nbytes=80), "moment coverage mismatch"),
        (_aggregated_bf16_adamw_evidence(foreach=True), "unsupported AdamW configuration"),
    ],
)
def test_capacity_gate_rejects_inexact_or_unbounded_adamw_moments(evidence, match):
    with pytest.raises(RuntimeError, match=match):
        gate._require_exact_bf16_adamw_moments(evidence, 10)


def test_capacity_gate_exposes_aggregated_training_evidence_after_state_export():
    source = Path(gate.__file__).read_text(encoding="utf-8")

    exported = source.index('training_evidence["cuda_phases"].append')
    gathered = source.index("dist.gather_object(local_metrics, gathered, dst=0)")
    exposed = source.index('"training_evidence": aggregate_training_evidence')

    assert exported < gathered < exposed
