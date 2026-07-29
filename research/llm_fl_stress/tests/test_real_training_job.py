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
    assert "--dataset-file site-1.jsonl" in recipe.per_site_config["site-1"]["train_args"]
    assert "--dataset-file site-2.jsonl" in recipe.per_site_config["site-2"]["train_args"]
    assert recipe.per_site_config["site-1"]["train_args"] != recipe.per_site_config["site-2"]["train_args"]
    assert recipe.aggregation_weights == {"site-1": 1.0, "site-2": 1.0}


@pytest.mark.parametrize("name", ["two_client_14b_trainable.slurm", "two_client_32b_trainable.slurm"])
def test_slurm_wrappers_resolve_launcher_from_repo_not_spooled_script(name):
    wrapper = (Path(__file__).resolve().parents[1] / "real_training" / "cs_oci_ord" / name).read_text()

    assert "BASH_SOURCE" not in wrapper
    assert 'QUALIFICATION_SCRIPT="${REPO_ROOT}/research/llm_fl_stress/real_training/' in wrapper
    assert 'exec bash "${QUALIFICATION_SCRIPT}"' in wrapper


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
