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

from research.llm_fl_stress.real_training.evidence import validate_trainable_state_evidence
from research.llm_fl_stress.real_training.job import DATA_FILES
from research.llm_fl_stress.real_training.state_evidence import (
    file_sha256,
    load_text_partition,
    select_partition_record,
    tensor_state_probe,
    tensor_state_summary,
)


def _state(digit: str, value: float) -> dict:
    return {
        "sha256": digit * 64,
        "tensor_count": 1,
        "payload_bytes": 16,
        "samples": [{"key": "model.model.layers.47.weight", "index": 0, "value": value}],
    }


def _record(site_name: str, round_index: int, input_state: dict, output_state: dict) -> dict:
    trajectory = [4.0, 3.5]
    rank_records = [
        {
            "rank": rank,
            "loss_trajectory": trajectory,
            "sample_ids": [f"{site_name}-r{round_index}-{rank * 2 + index}" for index in range(2)],
        }
        for rank in range(4)
    ]
    return {
        "event": "real_training_round",
        "status": "PASS",
        "site_name": site_name,
        "model_path": "/models/qwen-14b",
        "current_round": round_index,
        "state_scope": "trainable",
        "dataset_sha256": {"site-1": "1" * 64, "site-2": "2" * 64}[site_name],
        "loss_trajectory": trajectory,
        "sample_ids": [f"{site_name}-r{round_index}-{index}" for index in range(8)],
        "ranks": rank_records,
        "payload_bytes": 16,
        "tensor_count": 1,
        "input_state": input_state,
        "output_state": output_state,
    }


def _write_records(tmp_path: Path) -> dict[str, Path]:
    roots = {}
    states = {
        0: {
            "input": _state("a", 1.0),
            "site-1": _state("b", 2.0),
            "site-2": _state("c", 4.0),
        },
        1: {
            "input": _state("d", 3.0),
            "site-1": _state("e", 4.0),
            "site-2": _state("f", 6.0),
        },
    }
    for site_name in ("site-1", "site-2"):
        root = tmp_path / site_name
        roots[site_name] = root
        root.mkdir()
        records = [
            _record(site_name, round_index, states[round_index]["input"], states[round_index][site_name])
            for round_index in range(2)
        ]
        (root / "log.txt").write_text("".join(f"INFO - {json.dumps(record, sort_keys=True)}\n" for record in records))
    return roots


def test_fixed_partitions_are_distinct_and_cover_three_target_rounds():
    partitions = {site_name: load_text_partition(path) for site_name, path in DATA_FILES.items()}

    assert {site_name: len(records) for site_name, records in partitions.items()} == {
        "site-1": 48,
        "site-2": 48,
    }
    assert file_sha256(DATA_FILES["site-1"]) != file_sha256(DATA_FILES["site-2"])
    assert {record["id"] for record in partitions["site-1"]}.isdisjoint(record["id"] for record in partitions["site-2"])
    selected = {
        select_partition_record(
            partitions["site-1"],
            current_round=round_index,
            local_step=step,
            rank=rank,
            world_size=4,
            local_steps=4,
        )["id"]
        for round_index in range(3)
        for step in range(4)
        for rank in range(4)
    }
    assert len(selected) == 48


def test_trainable_evidence_proves_fedavg_and_round_continuity(tmp_path):
    roots = _write_records(tmp_path)
    persisted = [
        {"reload_status": "PASS", "state": _state("d", 3.0)},
        {"reload_status": "PASS", "state": _state("9", 5.0)},
    ]

    result = validate_trainable_state_evidence(
        client_roots=roots,
        site_names=["site-1", "site-2"],
        model_path=Path("/models/qwen-14b"),
        num_rounds=2,
        local_steps=2,
        nproc_per_client=4,
        expected_dataset_sha256={"site-1": "1" * 64, "site-2": "2" * 64},
        persisted_models=persisted,
        max_payload_bytes=1024,
    )

    assert result["status"] == "PASS"
    assert result["logical_wire_bytes"] == 16 * 2 * 2 * 2
    assert result["unique_samples_per_site"] == {"site-1": 16, "site-2": 16}
    assert result["persisted_checkpoints_reloaded"] == 2


def test_trainable_evidence_rejects_non_averaged_persistence(tmp_path):
    roots = _write_records(tmp_path)
    persisted = [
        {"reload_status": "PASS", "state": _state("d", 2.0)},
        {"reload_status": "PASS", "state": _state("9", 5.0)},
    ]

    with pytest.raises(RuntimeError, match="not the equal-weight client mean"):
        validate_trainable_state_evidence(
            client_roots=roots,
            site_names=["site-1", "site-2"],
            model_path=Path("/models/qwen-14b"),
            num_rounds=2,
            local_steps=2,
            nproc_per_client=4,
            expected_dataset_sha256={"site-1": "1" * 64, "site-2": "2" * 64},
            persisted_models=persisted,
            max_payload_bytes=1024,
        )


def test_tensor_summary_hashes_bfloat16_deterministically():
    torch = pytest.importorskip("torch")
    state = {
        "z": torch.tensor([1.0, 2.0], dtype=torch.bfloat16),
        "a": torch.tensor([[3.0]], dtype=torch.float32),
    }

    first = tensor_state_summary(state)
    second = tensor_state_summary({"a": state["a"], "z": state["z"]})

    assert first == second
    assert first["tensor_count"] == 2
    assert first["payload_bytes"] == 8
    assert len(first["sha256"]) == 64


def test_tensor_state_probe_records_exact_schema_without_full_content_hash():
    torch = pytest.importorskip("torch")
    state = {
        "z": torch.arange(100, dtype=torch.bfloat16),
        "a": torch.ones(2, dtype=torch.bfloat16),
    }

    result = tensor_state_probe(state)

    assert result["strategy"] == "schema-sha256-plus-bounded-values"
    assert result["tensor_count"] == 2
    assert result["payload_bytes"] == 204
    assert len(result["schema_sha256"]) == 64
    assert len(result["samples"]) <= 8
