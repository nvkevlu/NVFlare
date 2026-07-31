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


def test_multiround_wrapper_runs_five_target_rounds_without_gate_allocations():
    wrapper = (
        Path(__file__).resolve().parents[1]
        / "real_training"
        / "cs_oci_ord"
        / "two_client_14b_full_model_multiround.slurm"
    ).read_text()

    for token in (
        "#SBATCH --gpus-per-node=8",
        "#SBATCH --mem=512G",
        "#SBATCH --time=02:00:00",
        "#SBATCH --signal=TERM@300",
        "#SBATCH --no-requeue",
        "MINIMUM_SLURM_REMAINING_SECONDS=6900",
        'EXPECTED_HEAD="${EXPECTED_HEAD:-}"',
        "EXPECTED_HEAD must pin the exact reviewed checkout",
        "QUALIFICATION_PROFILE=full-model-14b-multiround",
        "TARGET_READY_TIMEOUT=7200",
        "TARGET_STALL_TIMEOUT=7200",
        "EXPECTED_TARGET_TRAINABLE_PARAMETERS=14770033664",
        "EXPECTED_TARGET_PAYLOAD_BYTES=29540067328",
        'GATE_MODEL_PATH="${TARGET_MODEL_PATH}"',
    ):
        assert token in wrapper

    assert "CONTROL_JOB_ID" not in wrapper
    assert "PREFLIGHT_JOB_ID" not in wrapper
    assert "GPU_PREFLIGHT_JOB_ID" not in wrapper
    assert "Qwen2.5-1.5B" not in wrapper


def test_common_launcher_accepts_target_only_multiround_profile():
    launcher = (
        Path(__file__).resolve().parents[1] / "real_training" / "cs_oci_ord" / "two_client_14b.slurm"
    ).read_text()

    assert '"${QUALIFICATION_PROFILE}" != "full-model-14b-multiround"' in launcher
    assert "gate_executed=false" in launcher
