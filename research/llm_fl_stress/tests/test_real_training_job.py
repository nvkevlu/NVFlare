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
    assert _build_recipe(args).min_clients == 2


def test_trainable_recipe_uses_sparse_server_model_and_distinct_site_data():
    args = _args(num_clients=2, nproc_per_node=4, state_scope="trainable")

    recipe = _build_recipe(args)

    assert recipe.model["path"] == "model.HFTrainableStateModel"
    assert set(recipe.per_site_config) == {"site-1", "site-2"}
    assert "--dataset-file data/site-1.jsonl" in recipe.per_site_config["site-1"]["train_args"]
    assert "--dataset-file data/site-2.jsonl" in recipe.per_site_config["site-2"]["train_args"]
    assert recipe.per_site_config["site-1"]["train_args"] != recipe.per_site_config["site-2"]["train_args"]
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
    assert "#SBATCH --mem=1400G" in wrapper
    assert "#SBATCH --time=03:00:00" in wrapper
    assert "QUALIFICATION_PROFILE=trainable-72b" in wrapper
    assert "efba10c8e54e91e0d9570ab5f7b51a958474d4cb" in wrapper
    assert "EXPECTED_TARGET_HIDDEN_SIZE=8192" in wrapper
    assert "EXPECTED_TARGET_INTERMEDIATE_SIZE=29568" in wrapper
    assert "EXPECTED_TARGET_NUM_HIDDEN_LAYERS=80" in wrapper
    assert "EXPECTED_TARGET_NUM_ATTENTION_HEADS=64" in wrapper
    assert "EXPECTED_TARGET_NUM_KEY_VALUE_HEADS=8" in wrapper
    assert "EXPECTED_TARGET_SAFETENSOR_FILES=37" in wrapper
    assert "EXPECTED_TARGET_PAYLOAD_BYTES=1755369472" in wrapper
    assert "TARGET_READY_TIMEOUT=3600" in wrapper
    assert "TARGET_STALL_TIMEOUT=1800" in wrapper


def test_72b_gpu_gate_is_real_four_rank_training_with_headroom_requirement():
    wrapper = (
        Path(__file__).resolve().parents[1] / "real_training" / "cs_oci_ord" / "model_72b_gpu_preflight.slurm"
    ).read_text()

    assert "#SBATCH --gpus-per-node=4" in wrapper
    assert "#SBATCH --mem=768G" in wrapper
    assert "--nproc_per_node=4" in wrapper
    assert "--local-steps 2" in wrapper
    assert "--expected-payload-bytes 1755369472" in wrapper
    assert "--required-headroom-mib 8192" in wrapper
    assert "NCCL_P2P_DISABLE" in wrapper
    assert "real_model_fsdp2_gpu_gate.py" in wrapper


def test_72b_cpu_preflight_checks_sparse_state_and_exported_job():
    wrapper = (
        Path(__file__).resolve().parents[1] / "real_training" / "cs_oci_ord" / "model_72b_preflight.slurm"
    ).read_text()

    assert "#SBATCH --partition=cpu" in wrapper
    assert "#SBATCH --mem=32G" in wrapper
    assert "trainable_server_preflight.py" in wrapper
    assert "--expected-hidden-size 8192" in wrapper
    assert "--expected-intermediate-size 29568" in wrapper
    assert "--expected-num-hidden-layers 80" in wrapper
    assert "--expected-num-attention-heads 64" in wrapper
    assert "--expected-num-key-value-heads 8" in wrapper
    assert "--expected-safetensor-files 37" in wrapper
    assert "--expected-payload-bytes 1755369472" in wrapper
    assert "--max-payload-bytes 2147483648" in wrapper
    assert "--num-clients 2" in wrapper
    assert "--nproc-per-node 4" in wrapper
    assert "--state-scope trainable" in wrapper
    assert "exported_job_preflight.py" in wrapper


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

    site_2_config_path = job_root / "app_site-2" / "config" / "config_fed_client.json"
    site_2_config = json.loads(site_2_config_path.read_text())
    del site_2_config["download_complete_timeout"]
    site_2_config_path.write_text(json.dumps(site_2_config))
    with pytest.raises(RuntimeError, match="download_complete_timeout"):
        validate_exported_job(job_root, args.timeout_seconds)
