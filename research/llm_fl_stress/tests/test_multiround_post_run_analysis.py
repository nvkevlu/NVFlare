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

from research.llm_fl_stress.real_training.multiround_post_run_analysis import (
    AnalysisError,
    _bf16_round,
    analyze_artifact,
)

_PHASE = "target-14b-full-model-multiround"
_MODEL_PATH = "/models/Qwen2.5-14B"
_ROUNDS = 5
_LOCAL_STEPS = 2
_NPROC = 4
_TENSORS = 2
_PAYLOAD = 16


def _probe(values: dict[tuple[str, int], float]) -> dict:
    return {
        "strategy": "schema-sha256-plus-bounded-values",
        "schema_sha256": "a" * 64,
        "tensor_count": _TENSORS,
        "payload_bytes": _PAYLOAD,
        "samples": [{"key": key, "index": index, "value": value} for (key, index), value in sorted(values.items())],
    }


def _round_record(
    site_name: str,
    round_index: int,
    input_values: dict[tuple[str, int], float],
    output_values: dict[tuple[str, int], float],
) -> dict:
    sample_ids = [
        f"{site_name}-{round_index * _LOCAL_STEPS * _NPROC + index + 1:03d}" for index in range(_LOCAL_STEPS * _NPROC)
    ]
    return {
        "event": "real_training_round",
        "status": "PASS",
        "current_round": round_index,
        "site_name": site_name,
        "model_path": _MODEL_PATH,
        "state_scope": "full",
        "trainable_target": "all",
        "sample_ids": sample_ids,
        "input_state": _probe(input_values),
        "output_state": _probe(output_values),
    }


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _write_artifact(tmp_path: Path, *, divergent_outputs: bool = True) -> Path:
    artifact = tmp_path / "artifact"
    phase = artifact / _PHASE
    artifact.mkdir()
    (artifact / "manifest.txt").write_text(
        "\n".join(
            (
                "job_id=123",
                "status=0",
                "qualification_profile=full-model-14b-multiround",
                "num_rounds=5",
                "local_steps=2",
                "nproc_per_client=4",
                "git_commit=" + "b" * 40,
            )
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        artifact / "qualification.json",
        {"status": "PASS", "profile": "full-model-14b-multiround"},
    )
    _write_json(
        phase / "configuration.json",
        {
            "model_path": _MODEL_PATH,
            "num_clients": 2,
            "nproc_per_client": _NPROC,
            "num_rounds": _ROUNDS,
            "local_steps": _LOCAL_STEPS,
            "state_scope": "full",
            "trainable_target": "all",
            "expected_payload_bytes": _PAYLOAD,
            "expected_tensor_count": _TENSORS,
        },
    )
    _write_json(phase / "summary.json", {"status": "PASS", "job_status": "FINISHED:COMPLETED"})

    inputs = {
        ("model.layer.weight", 0): _bf16_round(1.0),
        ("model.layer.weight", 3): _bf16_round(-0.5),
        ("model.norm.weight", 0): _bf16_round(0.25),
    }
    site_records = {"site-1": [], "site-2": []}
    for round_index in range(_ROUNDS):
        if divergent_outputs:
            first = {
                coordinate: _bf16_round(value + (round_index + 1) * 0.015625) for coordinate, value in inputs.items()
            }
            second = {
                coordinate: _bf16_round(value - (round_index + 1) * 0.0078125) for coordinate, value in inputs.items()
            }
        else:
            first = dict(inputs)
            second = dict(inputs)
        site_records["site-1"].append(_round_record("site-1", round_index, inputs, first))
        site_records["site-2"].append(_round_record("site-2", round_index, inputs, second))
        inputs = {coordinate: _bf16_round((first[coordinate] + second[coordinate]) / 2.0) for coordinate in inputs}

    for site_name, records in site_records.items():
        log_path = phase / "logs" / site_name / "log.txt"
        log_path.parent.mkdir(parents=True)
        log_path.write_text(
            "".join(f"INFO - {json.dumps(record, sort_keys=True)}\n" for record in records),
            encoding="utf-8",
        )
    server_log = phase / "logs" / "localhost" / "log.txt"
    server_log.parent.mkdir(parents=True)
    server_log.write_text(
        "".join(
            "INFO - Aggregated 2/2 results\n"
            "INFO - Start persist model on server.\n"
            "INFO - End persist model on server.\n"
            for _ in range(_ROUNDS)
        ),
        encoding="utf-8",
    )
    for sequence in range(_ROUNDS):
        _write_json(
            phase / "persistence" / f"persisted_model-{sequence}.json",
            {
                "sequence": sequence,
                "size_bytes": _PAYLOAD + 1024,
                "path": f"/ephemeral/FL_global_model-{sequence}.pt",
                "metadata_copied": True,
            },
        )
    return artifact


def _analyze(artifact: Path) -> dict:
    return analyze_artifact(
        artifact,
        expected_rounds=_ROUNDS,
        local_steps=_LOCAL_STEPS,
        nproc_per_client=_NPROC,
        expected_tensor_count=_TENSORS,
        expected_payload_bytes=_PAYLOAD,
        minimum_persisted_size_bytes=_PAYLOAD,
    )


def _round_log(artifact: Path, site_name: str) -> Path:
    return artifact / _PHASE / "logs" / site_name / "log.txt"


def _records(path: Path) -> list[dict]:
    return [json.loads(line.removeprefix("INFO - ")) for line in path.read_text().splitlines()]


def _replace_records(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(f"INFO - {json.dumps(record, sort_keys=True)}\n" for record in records),
        encoding="utf-8",
    )


def test_validates_five_round_continuity_lifecycle_and_size_only_persistence(tmp_path):
    artifact = _write_artifact(tmp_path)

    result = _analyze(artifact)

    assert result["status"] == "PASS"
    assert result["round_records_per_site"] == {"site-1": 5, "site-2": 5}
    assert result["sample_ids"]["unique_samples_per_site"] == {"site-1": 40, "site-2": 40}
    assert result["fedavg_continuity"]["transitions_checked"] == 4
    assert result["server_lifecycle"] == {
        "status": "PASS",
        "aggregation_events": 5,
        "persistence_start_events": 5,
        "persistence_end_events": 5,
    }
    assert result["client_output_divergence"]["status"] == "OBSERVED"
    assert result["persistence"]["validation_scope"] == "SIZE_ONLY"
    assert result["persistence"]["checkpoint_content_loaded"] is False
    assert result["persistence"]["full_checkpoint_values_validated"] is False


def test_missing_client_round_fails_closed(tmp_path):
    artifact = _write_artifact(tmp_path)
    path = _round_log(artifact, "site-2")
    _replace_records(path, _records(path)[:-1])

    with pytest.raises(AnalysisError, match="site-2 has 4 .* expected exactly 5"):
        _analyze(artifact)


def test_round_record_with_wrong_site_identity_fails_closed(tmp_path):
    artifact = _write_artifact(tmp_path)
    path = _round_log(artifact, "site-2")
    records = _records(path)
    records[1]["site_name"] = "site-1"
    _replace_records(path, records)

    with pytest.raises(AnalysisError, match="site-2 log contains round evidence for site_name='site-1'"):
        _analyze(artifact)


def test_duplicate_bounded_coordinate_fails_closed(tmp_path):
    artifact = _write_artifact(tmp_path)
    path = _round_log(artifact, "site-1")
    records = _records(path)
    records[0]["input_state"]["samples"].append(dict(records[0]["input_state"]["samples"][0]))
    _replace_records(path, records)

    with pytest.raises(AnalysisError, match="repeats bounded sample coordinate"):
        _analyze(artifact)


def test_mismatched_client_input_fails_closed(tmp_path):
    artifact = _write_artifact(tmp_path)
    path = _round_log(artifact, "site-2")
    records = _records(path)
    records[2]["input_state"]["samples"][0]["value"] += 1.0
    _replace_records(path, records)

    with pytest.raises(AnalysisError, match="did not receive an identical bounded global input"):
        _analyze(artifact)


def test_non_fedavg_next_input_fails_closed(tmp_path):
    artifact = _write_artifact(tmp_path)
    for site_name in ("site-1", "site-2"):
        path = _round_log(artifact, site_name)
        records = _records(path)
        records[3]["input_state"]["samples"][0]["value"] += 0.25
        _replace_records(path, records)

    with pytest.raises(AnalysisError, match="round 2->3 has 1 bounded samples outside"):
        _analyze(artifact)


def test_unobserved_output_divergence_is_labeled_not_overclaimed(tmp_path):
    artifact = _write_artifact(tmp_path, divergent_outputs=False)

    result = _analyze(artifact)

    assert result["status"] == "PASS"
    assert result["client_output_divergence"]["status"] == "NOT_OBSERVED_IN_BOUNDED_SAMPLES"
    assert result["client_output_divergence"]["rounds_observed"] == 0


def test_extra_server_lifecycle_marker_fails_exact_count(tmp_path):
    artifact = _write_artifact(tmp_path)
    path = artifact / _PHASE / "logs" / "localhost" / "log.txt"
    with path.open("a", encoding="utf-8") as stream:
        stream.write("INFO - End persist model on server.\n")

    with pytest.raises(AnalysisError, match="server has 6 persistence_end_events, expected exactly 5"):
        _analyze(artifact)


def test_small_persisted_checkpoint_fails_size_only_check(tmp_path):
    artifact = _write_artifact(tmp_path)
    path = artifact / _PHASE / "persistence" / "persisted_model-3.json"
    record = json.loads(path.read_text())
    record["size_bytes"] = _PAYLOAD - 1
    _write_json(path, record)

    with pytest.raises(AnalysisError, match="sequence 3 size=15, below 16"):
        _analyze(artifact)


def test_bfloat16_rounding_uses_ties_to_even():
    one = _bf16_round(1.0)
    next_after_one = _bf16_round(1.0 + 1.0 / 128.0)
    midpoint = (one + next_after_one) / 2.0

    assert _bf16_round(midpoint) == one
