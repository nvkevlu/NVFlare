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
from argparse import Namespace
from pathlib import Path

import pytest

from research.llm_fl_stress.real_training.exported_job_preflight import validate_exported_job
from research.llm_fl_stress.real_training.job import (
    _build_recipe,
    _client_args,
    _client_names,
    _gpu_config,
    _validated_summary,
)


def _args(**overrides):
    values = {
        "model_name_or_path": Path("/models/qwen with spaces"),
        "model_revision": None,
        "workspace_root": Path("/scratch/workspace"),
        "export_root": Path("/scratch/export"),
        "num_clients": 1,
        "nproc_per_node": 4,
        "num_rounds": 1,
        "local_steps": 1,
        "max_length": 128,
        "learning_rate": 1.0e-5,
        "trainable_target": "last-layer",
        "run_mode": "train",
        "state_scope": "full",
        "timeout_seconds": 1800,
        "expected_gpu_name_substring": None,
    }
    values.update(overrides)
    return Namespace(**values)


def test_client_args_quote_model_path_and_omit_empty_revision():
    result = _client_args(_args())

    assert "'/models/qwen with spaces'" in result
    assert "--model-revision" not in result
    assert "--trainable-target last-layer" in result


def test_client_args_include_pinned_revision():
    result = _client_args(_args(model_revision="abc123"))

    assert "--model-revision abc123" in result


def test_validation_summary_records_exact_process_count():
    args = _args(nproc_per_node=4)
    config = Namespace(
        model_path=args.model_name_or_path,
        workspace_root=args.workspace_root,
        export_root=args.export_root,
        num_clients=1,
        nproc_per_node=4,
        num_rounds=1,
        local_steps=1,
        max_length=128,
        trainable_target="last-layer",
        run_mode="train",
        state_scope="full",
    )

    result = _validated_summary(args, config)

    assert result["nproc_per_node"] == 4
    assert result["num_clients"] == 1
    assert result["clients"] == ["site-1"]
    assert result["gpu_config"] == "[0,1,2,3]"
    assert result["total_gpu_processes"] == 4
    assert "--nproc_per_node=4" in result["client_command"]


def test_two_client_gpu_groups_are_disjoint_and_recipe_requires_both_clients():
    args = _args(num_clients=2, nproc_per_node=4)

    assert _client_names(args.num_clients) == ["site-1", "site-2"]
    assert _gpu_config(args.num_clients, args.nproc_per_node) == "[0,1,2,3],[4,5,6,7]"
    recipe = _build_recipe(args)
    assert recipe.min_clients == 2
    assert recipe.shutdown_timeout == 600.0


def test_trainable_recipe_uses_sparse_server_model_and_distinct_site_data():
    args = _args(num_clients=2, nproc_per_node=4, state_scope="trainable")

    recipe = _build_recipe(args)

    assert recipe.model["path"] == "model.HFTrainableStateModel"
    assert set(recipe.per_site_config) == {"site-1", "site-2"}
    assert "--dataset-file data/site-1.jsonl" in recipe.per_site_config["site-1"]["train_args"]
    assert "--dataset-file data/site-2.jsonl" in recipe.per_site_config["site-2"]["train_args"]
    assert recipe.per_site_config["site-1"]["train_args"] != recipe.per_site_config["site-2"]["train_args"]
    assert recipe.aggregation_weights == {"site-1": 1.0, "site-2": 1.0}


def test_full_model_full_state_recipe_uses_full_server_and_distinct_site_data():
    args = _args(
        num_clients=2,
        nproc_per_node=4,
        local_steps=8,
        max_length=512,
        trainable_target="all",
        state_scope="full",
    )

    recipe = _build_recipe(args)

    assert recipe.model["path"] == "model.HFTextModel"
    assert set(recipe.per_site_config) == {"site-1", "site-2"}
    assert "--trainable-target all" in recipe.per_site_config["site-1"]["train_args"]
    assert "--state-scope full" in recipe.per_site_config["site-1"]["train_args"]
    assert "--local-steps 8" in recipe.per_site_config["site-1"]["train_args"]
    assert "--max-length 512" in recipe.per_site_config["site-1"]["train_args"]
    assert "--dataset-file data/site-1.jsonl" in recipe.per_site_config["site-1"]["train_args"]
    assert "--dataset-file data/site-2.jsonl" in recipe.per_site_config["site-2"]["train_args"]
    assert recipe.aggregation_weights == {"site-1": 1.0, "site-2": 1.0}


@pytest.mark.parametrize(
    "name",
    [
        "two_client_14b_trainable.slurm",
        "two_client_32b_trainable.slurm",
        "two_client_72b_trainable.slurm",
    ],
)
def test_slurm_wrappers_resolve_launcher_from_repo_not_spooled_script(name):
    wrapper = (Path(__file__).resolve().parents[1] / "real_training" / "cs_oci_ord" / name).read_text()

    assert "BASH_SOURCE" not in wrapper
    assert 'QUALIFICATION_SCRIPT="${REPO_ROOT}/research/llm_fl_stress/real_training/' in wrapper
    assert 'exec bash "${QUALIFICATION_SCRIPT}"' in wrapper


def test_72b_wrapper_pins_capacity_identity_and_safe_timeouts():
    wrapper = (
        Path(__file__).resolve().parents[1] / "real_training" / "cs_oci_ord" / "two_client_72b_trainable.slurm"
    ).read_text()

    assert "#SBATCH --gpus-per-node=8" in wrapper
    assert "#SBATCH --mem=1600G" in wrapper
    assert "#SBATCH --time=04:00:00" in wrapper
    assert "#SBATCH --signal=TERM@300" in wrapper
    assert "QUALIFICATION_PROFILE=trainable-72b" in wrapper
    assert 'GATE_MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-1.5B-8faed761d45a"' in wrapper
    assert 'TARGET_MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-72B-efba10c8e54e"' in wrapper
    assert "TARGET_MODEL_PATH:-" not in wrapper
    assert "efba10c8e54e91e0d9570ab5f7b51a958474d4cb" in wrapper
    assert "EXPECTED_TARGET_HIDDEN_SIZE=8192" in wrapper
    assert "EXPECTED_TARGET_INTERMEDIATE_SIZE=29568" in wrapper
    assert "EXPECTED_TARGET_NUM_HIDDEN_LAYERS=80" in wrapper
    assert "EXPECTED_TARGET_NUM_ATTENTION_HEADS=64" in wrapper
    assert "EXPECTED_TARGET_NUM_KEY_VALUE_HEADS=8" in wrapper
    assert "EXPECTED_TARGET_SAFETENSOR_FILES=37" in wrapper
    assert "EXPECTED_TARGET_TENSOR_BYTES=145412407296" in wrapper
    assert "EXPECTED_TARGET_PAYLOAD_BYTES=1755369472" in wrapper
    assert "SERVICE_STARTUP_TIMEOUT=300" in wrapper
    assert "GATE_READY_TIMEOUT=900" in wrapper
    assert "GATE_STALL_TIMEOUT=900" in wrapper
    assert "TARGET_READY_TIMEOUT=7200" in wrapper
    assert "TARGET_STALL_TIMEOUT=1800" in wrapper
    assert "CONTROL_JOB_ID PREFLIGHT_JOB_ID GPU_PREFLIGHT_JOB_ID" in wrapper
    assert "must name the passing gate used by the login-node readiness validator" in wrapper


def test_72b_gpu_gate_is_real_four_rank_training_with_headroom_requirement():
    wrapper = (
        Path(__file__).resolve().parents[1] / "real_training" / "cs_oci_ord" / "model_72b_gpu_preflight.slurm"
    ).read_text()

    assert "#SBATCH --gpus-per-node=4" in wrapper
    assert "#SBATCH --mem=900G" in wrapper
    assert "#SBATCH --time=02:00:00" in wrapper
    assert "#SBATCH --signal=TERM@300" in wrapper
    assert 'MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-72B-efba10c8e54e"' in wrapper
    assert "MODEL_PATH:-" not in wrapper
    assert 'MODEL_VERIFICATION_MARKER="${MODEL_MANIFEST}.verified"' in wrapper
    assert "Model file changed after verification" in wrapper
    assert "--nproc_per_node=4" in wrapper
    assert "--local-steps 2" in wrapper
    assert "--expected-payload-bytes 1755369472" in wrapper
    assert "--timeout-seconds 7200" in wrapper
    assert "--required-headroom-mib 16384" in wrapper
    assert "--full-job-memory-gib 1600" in wrapper
    assert "--full-job-client-count 2" in wrapper
    assert "--required-fixed-host-headroom-gib 128" in wrapper
    assert "--max-model-ready-seconds 2400" in wrapper
    assert "--max-work-seconds 1200" in wrapper
    assert "NCCL_P2P_DISABLE" in wrapper
    assert "real_model_fsdp2_gpu_gate.py" in wrapper


def test_32b_single_client_experiment_pins_exact_eight_rank_capacity_contract():
    wrapper = (
        Path(__file__).resolve().parents[1] / "real_training" / "cs_oci_ord" / "single_client_32b_full_model.slurm"
    ).read_text()

    for token in (
        "#SBATCH --cpus-per-task=64",
        "#SBATCH --gpus-per-node=8",
        "#SBATCH --mem=900G",
        "#SBATCH --time=02:00:00",
        "#SBATCH --signal=TERM@300",
        "#SBATCH --no-requeue",
        'MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-32B-1818d35814b8"',
        'DATASET_PATH="${REPO_ROOT}/research/llm_fl_stress/real_training/data/site-1.jsonl"',
        "1818d35814b8319459f4bd55ed1ac8709630f003",
        "EXPECTED_PARAMETERS=32763876352",
        "EXPECTED_TENSOR_COUNT=771",
        "EXPECTED_STATE_PAYLOAD_BYTES=65527752704",
        "EXPECTED_CHECKPOINT_FILE_BYTES=65527841752",
        "MINIMUM_SLURM_MEMORY_MIB=921600",
        "MINIMUM_SLURM_REMAINING_SECONDS=6900",
        "REQUIRED_SLURM_GPUS_ON_NODE=8",
        'SLURM_ALLOCATION_MEMORY_MIB="${SLURM_MEM_PER_NODE:-UNSET}"',
        'SLURM_ALLOCATION_GPUS_ON_NODE="${SLURM_GPUS_ON_NODE:-UNSET}"',
        'SLURM_ALLOCATION_END_TIME_EPOCH="${SLURM_JOB_END_TIME:-UNSET}"',
        'EXPECTED_HEAD="${EXPECTED_HEAD:-}"',
        'RUN_REPO_ROOT="${RUN_REPO_ROOT:-}"',
        'READINESS_ARTIFACT="${READINESS_ARTIFACT:-}"',
        'REQUIREMENTS_LOCK="${VENV_DIR}/requirements.lock"',
        'STATIC_RESULT="${STATIC_RESULT:-${PROJECT_ROOT}/artifacts/32b-single-client-static-${EXPECTED_HEAD}.json}"',
        "RUN_REPO_ROOT must name an immutable release worktree",
        "RUN_REPO_ROOT must remain a detached immutable release worktree",
        "Readiness artifact is not bound to this exact release",
        "Readiness artifact input changed after validation",
        '\\"requirements_lock_sha256\\"',
        'export PYTHONPATH="${REPO_ROOT}"',
        'export NVFLARE_EXPECTED_SOURCE_ROOT="${REPO_ROOT}"',
        "dependency_check.py",
        "--metadata-only",
        "--expected-source-root '${REPO_ROOT}'",
        "--expected-prefix '${VENV_DIR}'",
        "printf 'pythonpath=%s\\n'",
        "printf 'nvflare_expected_source_root=%s\\n'",
        "EXPECTED_HEAD must pin the exact reviewed checkout",
        "printf 'expected_head=%s\\n'",
        "EXPERIMENT_RELEASE=2026-08-02-single-client-full-model-32b-v3",
        "REQUIRED_BASE_RELEASE=2026-07-31-full-model-14b-v12",
        "printf 'experiment_release=%s\\n'",
        "printf 'required_base_release=%s\\n'",
        "model_structure_preflight.py",
        "--expected-hidden-size 5120",
        "--expected-intermediate-size 27648",
        "--expected-num-hidden-layers 64",
        "--expected-num-attention-heads 40",
        "--expected-num-key-value-heads 8",
        "--expected-safetensor-files 17",
        "--expected-tensor-count '${EXPECTED_TENSOR_COUNT}'",
        "--expected-parameters '${EXPECTED_PARAMETERS}'",
        "--expected-tensor-bytes '${EXPECTED_STATE_PAYLOAD_BYTES}'",
        "--expected-checkpoint-file-bytes '${EXPECTED_CHECKPOINT_FILE_BYTES}'",
        "--dataset-file '${DATASET_PATH}'",
        "--minimum-dataset-records 48",
        '\\"indexed_tensor_count\\": 771',
        "capacity_experiment.py",
        "--gpu-count 8",
        "--nproc_per_node=8",
        "--expected-world-size 8",
        "--trainable-target all",
        "--state-scope full",
        "--local-steps 6",
        "--max-length 512",
        "--required-headroom-mib 0",
        "--full-job-memory-gib 900",
        "--full-job-client-count 1",
        "--required-fixed-host-headroom-gib 64",
        "--server-state-copies 1",
        "--host-projection-mode report-only",
        "--max-model-ready-seconds 0",
        "--max-work-seconds 0",
        "--result-path '${RESULT_PATH}'",
    ):
        assert token in wrapper

    assert "NCCL_P2P_DISABLE" in wrapper
    assert "validate_slurm_allocation" in wrapper
    assert "--nproc_per_node=4" not in wrapper
    assert "import nvflare" not in wrapper
    assert "nvflare.__file__" not in wrapper


def test_32b_single_client_runbook_uses_only_metadata_checks_for_code_update():
    runbook = (
        Path(__file__).resolve().parents[1] / "docs" / "cs-oci-ord-single-client-32b-full-model-runbook.md"
    ).read_text()

    assert "nvflare-32b-import-cleanup.bundle" in runbook
    assert "0beb6021bc27c4b33c9bb4177d613c2aa6588054" in runbook
    assert runbook.count("--metadata-only") == 2
    assert '--expected-source-root "$RUN_REPO_ROOT"' in runbook
    assert '--expected-prefix "$PROJECT_ROOT/envs/nvflare-fsdp2"' in runbook
    assert "nvflare.__file__" not in runbook
    assert "import nvflare" not in runbook
    assert "sha256sum --check MANIFEST.sha256\n" not in runbook
    assert 'sha256sum --check "$CONTAINER_IMAGE.sha256"\n' not in runbook


def test_72b_cpu_preflight_checks_sparse_state_and_exported_job():
    wrapper = (
        Path(__file__).resolve().parents[1] / "real_training" / "cs_oci_ord" / "model_72b_preflight.slurm"
    ).read_text()

    assert "#SBATCH --partition=cpu" in wrapper
    assert "#SBATCH --mem=32G" in wrapper
    assert 'MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-72B-efba10c8e54e"' in wrapper
    assert "MANIFEST.sha256.verified" in wrapper
    assert "model_manifest_verified=PASS" in wrapper
    assert "trainable_server_preflight.py" in wrapper
    assert "--expected-hidden-size 8192" in wrapper
    assert "--expected-intermediate-size 29568" in wrapper
    assert "--expected-num-hidden-layers 80" in wrapper
    assert "--expected-num-attention-heads 64" in wrapper
    assert "--expected-num-key-value-heads 8" in wrapper
    assert "--expected-safetensor-files 37" in wrapper
    assert "--expected-tensor-bytes 145412407296" in wrapper
    assert "--expected-payload-bytes 1755369472" in wrapper
    assert "--max-payload-bytes 2147483648" in wrapper
    assert "--num-clients 2" in wrapper
    assert "--nproc-per-node 4" in wrapper
    assert "--state-scope trainable" in wrapper
    assert "--timeout-seconds 10800" in wrapper
    assert "exported_job_preflight.py" in wrapper


def test_control_plane_preflight_is_pinned_and_records_submit_evidence():
    wrapper = (
        Path(__file__).resolve().parents[1] / "real_training" / "cs_oci_ord" / "control_plane_preflight.slurm"
    ).read_text()

    assert "#SBATCH --time=00:15:00" in wrapper
    assert 'GATE_MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-1.5B-8faed761d45a"' in wrapper
    assert 'TARGET_MODEL_PATH="${GATE_MODEL_PATH}"' in wrapper
    assert "Qwen2.5-14B" not in wrapper
    assert "--timeout-seconds 10800" in wrapper
    assert "--service-startup-timeout 300" in wrapper
    assert "operation_timeout_seconds=10800" in wrapper
    assert "transport_timeout_seconds=10800" in wrapper
    assert "NVFLARE_STREAMING_ACK_WAIT=10800" in wrapper
    assert "NVFLARE_STREAMING_ACK_PROGRESS_TIMEOUT=10800" in wrapper
    assert "NVFLARE_STREAMING_READ_TIMEOUT=10800" in wrapper
    assert "NVFLARE_STREAMING_SEND_TIMEOUT=10800" in wrapper
    assert "git_commit=%s" in wrapper


def test_full_72b_allocation_revalidates_gate_evidence_before_dependency_imports():
    wrapper = (
        Path(__file__).resolve().parents[1] / "real_training" / "cs_oci_ord" / "two_client_14b.slurm"
    ).read_text()

    readiness = wrapper.index("validate_72b_readiness.py")
    dependencies = wrapper.index("dependency_check.py")
    qualification = wrapper.index("qualification.py${QUOTED_QUALIFICATION_ARGS}")

    assert readiness < dependencies < qualification
    assert "allocation-start-readiness.json" in wrapper
    assert "NVFLARE_STREAMING_ACK_WAIT=10800" in wrapper
    assert "NVFLARE_STREAMING_ACK_PROGRESS_TIMEOUT=10800" in wrapper
    assert "NVFLARE_STREAMING_READ_TIMEOUT=10800" in wrapper
    assert "NVFLARE_STREAMING_SEND_TIMEOUT=10800" in wrapper


def test_exported_launcher_uses_packaged_relative_client_path(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("nvflare")
    args = _args(model_name_or_path=Path("/models/Qwen2.5-14B"), model_revision="abc123")
    recipe = _build_recipe(args)

    recipe.export(str(tmp_path))

    config_path = tmp_path / "llm_fsdp2_real_training" / "app" / "config" / "config_fed_client.json"
    config = json.loads(config_path.read_text())
    launcher = next(component for component in config["components"] if component["id"] == "launcher")
    script = launcher["args"]["script"]
    assert "custom/research/llm_fl_stress/real_training/client.py" in script
    assert "custom//" not in script


def test_exported_trainable_datasets_resolve_from_client_runtime(tmp_path, monkeypatch):
    pytest.importorskip("torch")
    pytest.importorskip("nvflare")
    from research.llm_fl_stress.real_training import client
    from research.llm_fl_stress.real_training.job import DATA_FILES

    args = _args(
        model_name_or_path=Path("/models/Qwen2.5-1.5B"),
        model_revision="abc123",
        num_clients=2,
        state_scope="trainable",
    )
    recipe = _build_recipe(args)
    recipe.export(str(tmp_path))
    job_root = tmp_path / "llm_fsdp2_real_training"
    expected_client_config = {
        "EXTERNAL_PRE_INIT_TIMEOUT": args.timeout_seconds,
        "PEER_READ_TIMEOUT": args.timeout_seconds,
        "HEARTBEAT_TIMEOUT": args.timeout_seconds,
        "submit_result_timeout": args.timeout_seconds,
        "download_complete_timeout": args.timeout_seconds,
        "max_resends": 3,
        "last_result_transfer_timeout": args.timeout_seconds,
        "streaming_idle_timeout": args.timeout_seconds,
        "streaming_max_peer_silence": args.timeout_seconds * 1.5,
        "get_task_timeout": args.timeout_seconds,
        "max_runner_sync_timeout": args.timeout_seconds,
        "runner_sync_timeout": 5.0,
        "submit_task_result_timeout": args.timeout_seconds,
        "tensor_streaming_per_request_timeout": args.timeout_seconds,
        "tensor_min_download_timeout": args.timeout_seconds,
    }

    for site_name, source_dataset in DATA_FILES.items():
        app_root = job_root / f"app_{site_name}"
        packaged_dataset = app_root / "custom" / "data" / source_dataset.name
        exported_client = app_root / "custom" / "research" / "llm_fl_stress" / "real_training" / "client.py"
        config_path = app_root / "config" / "config_fed_client.json"
        config = json.loads(config_path.read_text())
        launcher = next(component for component in config["components"] if component["id"] == "launcher")
        dataset_arg = f"data/{source_dataset.name}"

        for key, value in expected_client_config.items():
            assert config[key] == value
        assert launcher["args"]["shutdown_timeout"] == 600.0
        assert packaged_dataset.read_bytes() == source_dataset.read_bytes()
        assert f"--dataset-file {dataset_arg}" in launcher["args"]["script"]

        monkeypatch.setattr(client, "__file__", str(exported_client))
        records, observed_sha256 = client._resolve_dataset(
            Namespace(
                dataset_file=dataset_arg,
                dataset_sha256=client.file_sha256(source_dataset),
            )
        )

        assert records
        assert observed_sha256 == client.file_sha256(source_dataset)

    server_config_path = job_root / "app_server" / "config" / "config_fed_server.json"
    server_config = json.loads(server_config_path.read_text())
    assert server_config["strict_start_job_reply_check"] is True
    assert server_config["sync_client_jobs_require_previous_report"] is True
    assert server_config["streaming_idle_timeout"] == args.timeout_seconds
    assert server_config["streaming_max_peer_silence"] == args.timeout_seconds * 1.5
    assert server_config["tensor_streaming_per_request_timeout"] == args.timeout_seconds
    assert server_config["tensor_min_download_timeout"] == args.timeout_seconds

    preflight = validate_exported_job(job_root, args.timeout_seconds)
    assert preflight["status"] == "PASS"
    assert preflight["clients"] == ["site-1", "site-2"]
    assert preflight["early_flare_init"] is True
    assert preflight["launcher_shutdown_timeout_seconds"] == 600.0
    assert preflight["subprocess_tensor_download_timeout_seconds"] == args.timeout_seconds
    assert preflight["aggregation_weights"] == {"site-1": 1.0, "site-2": 1.0}

    site_2_config_path = job_root / "app_site-2" / "config" / "config_fed_client.json"
    site_2_config = json.loads(site_2_config_path.read_text())
    del site_2_config["download_complete_timeout"]
    site_2_config_path.write_text(json.dumps(site_2_config))
    with pytest.raises(RuntimeError, match="download_complete_timeout"):
        validate_exported_job(job_root, args.timeout_seconds)


def test_exported_job_preflight_rejects_short_launcher_shutdown(tmp_path):
    args = _args(
        model_name_or_path=Path("/models/Qwen2.5-1.5B"),
        model_revision="abc123",
        num_clients=2,
        state_scope="trainable",
    )
    _build_recipe(args).export(str(tmp_path))
    job_root = tmp_path / "llm_fsdp2_real_training"
    config_path = job_root / "app_site-1" / "config" / "config_fed_client.json"
    config = json.loads(config_path.read_text())
    launcher = next(component for component in config["components"] if component["id"] == "launcher")
    launcher["args"]["shutdown_timeout"] = 60.0
    config_path.write_text(json.dumps(config))

    with pytest.raises(RuntimeError, match="shutdown_timeout"):
        validate_exported_job(job_root, args.timeout_seconds)


def test_exported_job_preflight_rejects_wrong_aggregation_weights(tmp_path):
    args = _args(
        model_name_or_path=Path("/models/Qwen2.5-14B"),
        model_revision="abc123",
        num_clients=2,
        state_scope="full",
        trainable_target="all",
    )
    _build_recipe(args).export(str(tmp_path))
    job_root = tmp_path / "llm_fsdp2_real_training"
    config_path = job_root / "app_server" / "config" / "config_fed_server.json"
    config = json.loads(config_path.read_text())
    controller = next(workflow for workflow in config["workflows"] if workflow["id"] == "controller")
    controller["args"]["aggregation_weights"] = {"site-1": 1.0, "site-2": 2.0}
    config_path.write_text(json.dumps(config))

    with pytest.raises(RuntimeError, match="aggregation_weights mismatch"):
        validate_exported_job(job_root, args.timeout_seconds)
