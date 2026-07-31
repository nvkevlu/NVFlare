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

from research.llm_fl_stress.real_training.evidence import validate_production_evidence, validate_simulation_evidence


def _round_record(site_name: str, loss: float) -> dict:
    return {
        "event": "real_training_round",
        "status": "PASS",
        "current_round": 0,
        "site_name": site_name,
        "run_mode": "train",
        "trainable_target": "last-layer",
        "local_steps": 1,
        "world_size": 4,
        "loss": loss,
        "selected_max_abs_change": 1.0e-5,
        "load_seconds": 2.0,
        "export_seconds": 5.0,
        "payload_bytes": 29_540_067_328,
        "tensor_count": 579,
        "round_seconds": 10.0,
        "ranks": [
            {
                "rank": rank,
                "local_rank": rank,
                "gpu_name": "NVIDIA A100-SXM4-80GB",
                "max_rss_bytes": 64_000_000_000 if rank == 0 else 8_000_000_000,
                "peak_gpu_allocated_bytes": 15_000_000_000,
                "peak_gpu_reserved_bytes": 17_000_000_000,
            }
            for rank in range(4)
        ],
    }


def _write_valid_workspace(tmp_path):
    run_root = tmp_path / "llm_fsdp2_real_training"
    for site_name, loss in (("site-1", 4.5), ("site-2", 4.8)):
        log_path = run_root / site_name / "simulate_job" / "log.txt"
        log_path.parent.mkdir(parents=True)
        log_path.write_text(f"INFO - {json.dumps(_round_record(site_name, loss), sort_keys=True)}\n")
    server_log = run_root / "server" / "simulate_job" / "log.txt"
    server_log.parent.mkdir(parents=True)
    server_log.write_text("INFO - Aggregated 2/2 results\nINFO - End persist model on server.\n")
    return run_root


def test_two_client_evidence_requires_both_sites_aggregation_and_persistence(tmp_path):
    run_root = _write_valid_workspace(tmp_path)

    result = validate_simulation_evidence(
        run_root,
        site_names=["site-1", "site-2"],
        run_mode="train",
        nproc_per_client=4,
        expected_gpu_name_substring="A100-SXM4-80GB",
    )

    assert result["status"] == "PASS"
    assert result["num_clients"] == 2
    assert result["aggregated_results"] == 2
    assert result["persisted"] is True
    assert {site["site_name"] for site in result["sites"]} == {"site-1", "site-2"}
    assert all(len(site["ranks"]) == 4 for site in result["sites"])


def test_two_client_evidence_fails_when_one_client_round_is_missing(tmp_path):
    run_root = _write_valid_workspace(tmp_path)
    (run_root / "site-2" / "simulate_job" / "log.txt").write_text("")

    with pytest.raises(RuntimeError, match="site-2 must have exactly 1"):
        validate_simulation_evidence(
            run_root,
            site_names=["site-1", "site-2"],
            run_mode="train",
            nproc_per_client=4,
        )


def test_two_client_evidence_fails_when_server_did_not_aggregate_both_results(tmp_path):
    run_root = _write_valid_workspace(tmp_path)
    (run_root / "server" / "simulate_job" / "log.txt").write_text("INFO - Aggregated 1/2 results\n")

    with pytest.raises(RuntimeError, match="Aggregated 2/2 results"):
        validate_simulation_evidence(
            run_root,
            site_names=["site-1", "site-2"],
            run_mode="train",
            nproc_per_client=4,
        )


def test_two_client_evidence_requires_positive_gpu_memory_on_every_rank(tmp_path):
    run_root = _write_valid_workspace(tmp_path)
    site_log = run_root / "site-2" / "simulate_job" / "log.txt"
    record = _round_record("site-2", 4.8)
    record["ranks"][3]["peak_gpu_allocated_bytes"] = 0
    site_log.write_text(f"INFO - {json.dumps(record, sort_keys=True)}\n")

    with pytest.raises(RuntimeError, match="rank 3 has invalid peak_gpu_allocated_bytes=0"):
        validate_simulation_evidence(
            run_root,
            site_names=["site-1", "site-2"],
            run_mode="train",
            nproc_per_client=4,
        )


def test_multi_round_evidence_requires_server_aggregation_for_each_round(tmp_path):
    run_root = _write_valid_workspace(tmp_path)
    for site_name in ("site-1", "site-2"):
        log_path = run_root / site_name / "simulate_job" / "log.txt"
        second_round = _round_record(site_name, 4.25)
        second_round["current_round"] = 1
        with log_path.open("a") as stream:
            stream.write(f"INFO - {json.dumps(second_round, sort_keys=True)}\n")

    with pytest.raises(RuntimeError, match="expected at least 2"):
        validate_simulation_evidence(
            run_root,
            site_names=["site-1", "site-2"],
            run_mode="train",
            nproc_per_client=4,
            num_rounds=2,
        )


def test_production_evidence_filters_sequential_jobs_by_model_path(tmp_path):
    gate_model = Path("/models/Qwen2.5-1.5B")
    target_model = Path("/models/Qwen2.5-14B")
    client_roots = {}
    for site_name, loss in (("site-1", 4.5), ("site-2", 4.8)):
        root = tmp_path / site_name
        client_roots[site_name] = root
        log_path = root / "log.txt"
        log_path.parent.mkdir(parents=True)
        gate_record = _round_record(site_name, loss + 1.0)
        gate_record["model_path"] = str(gate_model)
        target_record = _round_record(site_name, loss)
        target_record["model_path"] = str(target_model)
        log_path.write_text(
            f"INFO - {json.dumps(gate_record, sort_keys=True)}\n"
            f"INFO - {json.dumps(target_record, sort_keys=True)}\n"
        )
    server_root = tmp_path / "server"
    server_root.mkdir()
    (server_root / "log.txt").write_text("Aggregated 2/2 results\nEnd persist model on server.\n")

    result = validate_production_evidence(
        client_roots=client_roots,
        server_root=server_root,
        site_names=["site-1", "site-2"],
        model_path=target_model,
        run_mode="train",
        nproc_per_client=4,
    )

    assert result["status"] == "PASS"
    assert {site["loss"] for site in result["sites"]} == {4.5, 4.8}


def _full_model_training_evidence() -> dict:
    phases = [
        {"phase": name}
        for name in (
            "after_state_load",
            "after_optimizer_init",
            "after_first_backward",
            "after_first_optimizer_step",
            "after_final_optimizer_step",
            "after_state_export",
        )
    ]
    return {
        "update_probe": {
            "strategy": "evenly-spaced-local-shard-values",
            "max_values_per_parameter_shard": 64,
            "parameter_tensor_count": 579,
            "global_sampled_value_count": 1000,
            "globally_changed_parameter_tensor_count": 500,
            "global_max_abs_change": 1.0e-5,
        },
        "gradient_probes": [
            {
                "position": position,
                "layer_index": index,
                "parameter": f"model.layers.{index}.weight",
                "global_l2_norm": 1.0,
                "finite": True,
                "nonzero": True,
            }
            for position, index in (("early", 0), ("middle", 24), ("late", 47))
        ],
        "optimizer_state": {
            "config": {"name": "AdamW", "learning_rate": 1.0e-5, "foreach": False, "fused": False},
            "global_tensor_count": 1737,
            "global_tensor_numel": 2 * 14_770_033_664,
            "global_tensor_bytes": 59_080_134_656,
            "global_dtype_histogram": {
                "bfloat16": {
                    "tensor_count": 1158,
                    "numel": 29_540_067_328,
                    "bytes": 59_080_134_656,
                }
            },
        },
        "cuda_phases": [{"rank": rank, "phases": phases} for rank in range(4)],
    }


def _write_full_model_workspace(tmp_path):
    model_path = Path("/models/Qwen2.5-14B")
    roots = {}
    dataset_hashes = {"site-1": "1" * 64, "site-2": "2" * 64}
    for site_name in ("site-1", "site-2"):
        root = tmp_path / site_name
        roots[site_name] = root
        ready = {
            "event": "real_training_client_ready",
            "site_name": site_name,
            "model_path": str(model_path),
            "state_scope": "full",
            "trainable_target": "all",
            "dataset_sha256": dataset_hashes[site_name],
            "total_parameters": 14_770_033_664,
            "trainable_parameters": 14_770_033_664,
            "frozen_parameters": 0,
            "total_tensor_count": 579,
            "trainable_tensor_count": 579,
            "frozen_tensor_count": 0,
            "gradient_checkpointing_enabled": True,
        }
        round_record = _round_record(site_name, 4.5)
        loss_trajectory = [4.5 - 0.01 * step for step in range(8)]
        rank_sample_ids = {rank: [f"{site_name}-rank-{rank}-sample-{step}" for step in range(8)] for rank in range(4)}
        total_gpu_memory_bytes = 80 * 1024**3
        for rank in round_record["ranks"]:
            rank["loss_trajectory"] = loss_trajectory
            rank["sample_ids"] = rank_sample_ids[rank["rank"]]
            rank["total_gpu_memory_bytes"] = total_gpu_memory_bytes
            rank["reserved_headroom_bytes"] = total_gpu_memory_bytes - rank["peak_gpu_reserved_bytes"]
        round_record.update(
            model_path=str(model_path),
            state_scope="full",
            trainable_target="all",
            local_steps=8,
            max_length=512,
            dataset_sha256=dataset_hashes[site_name],
            loss_trajectory=loss_trajectory,
            sample_ids=sorted(sample for values in rank_sample_ids.values() for sample in values),
            model_evidence={
                "total_parameters": 14_770_033_664,
                "trainable_parameters": 14_770_033_664,
                "frozen_parameters": 0,
            },
            training_evidence=_full_model_training_evidence(),
            input_state={
                "strategy": "schema-sha256-plus-bounded-values",
                "schema_sha256": "a" * 64,
                "tensor_count": 579,
                "payload_bytes": 29_540_067_328,
                "samples": [{"key": "model.weight", "index": 0, "value": 1.0}],
            },
            output_state={
                "strategy": "schema-sha256-plus-bounded-values",
                "schema_sha256": "a" * 64,
                "tensor_count": 579,
                "payload_bytes": 29_540_067_328,
                "samples": [{"key": "model.weight", "index": 0, "value": 2.0 if site_name == "site-1" else 3.0}],
            },
        )
        (root / "log.txt").parent.mkdir(parents=True, exist_ok=True)
        (root / "log.txt").write_text(
            f"INFO - {json.dumps(ready, sort_keys=True)}\nINFO - {json.dumps(round_record, sort_keys=True)}\n"
        )
    server_root = tmp_path / "server"
    server_root.mkdir()
    (server_root / "log.txt").write_text("Aggregated 2/2 results\nEnd persist model on server.\n")
    return roots, server_root, model_path, dataset_hashes


def _rewrite_round(root: Path, mutate) -> None:
    log_path = root / "log.txt"
    records = []
    for line in log_path.read_text().splitlines():
        record = json.loads(line.removeprefix("INFO - "))
        if record.get("event") == "real_training_round":
            mutate(record)
        records.append(record)
    log_path.write_text("".join(f"INFO - {json.dumps(record, sort_keys=True)}\n" for record in records))


def test_full_model_evidence_requires_all_parameters_gradients_optimizer_and_data(tmp_path):
    roots, server_root, model_path, dataset_hashes = _write_full_model_workspace(tmp_path)

    result = validate_production_evidence(
        client_roots=roots,
        server_root=server_root,
        site_names=["site-1", "site-2"],
        model_path=model_path,
        run_mode="train",
        nproc_per_client=4,
        expected_state_scope="full",
        expected_trainable_target="all",
        expected_trainable_parameters=14_770_033_664,
        expected_dataset_sha256=dataset_hashes,
        expected_local_steps=8,
        expected_max_length=512,
        required_gpu_reserved_headroom_bytes=16 * 1024**3,
    )

    assert result["status"] == "PASS"
    assert result["payload_bytes_per_client"] == 29_540_067_328
    assert len(result["client_ready"]) == 2
    assert result["unique_samples_per_site"] == {"site-1": 32, "site-2": 32}


def test_full_model_evidence_rejects_last_layer_masquerading_as_all(tmp_path):
    roots, server_root, model_path, dataset_hashes = _write_full_model_workspace(tmp_path)
    log_path = roots["site-2"] / "log.txt"
    log_path.write_text(log_path.read_text().replace('"trainable_target": "all"', '"trainable_target": "last-layer"'))

    with pytest.raises(RuntimeError, match="wrong trainable_target"):
        validate_production_evidence(
            client_roots=roots,
            server_root=server_root,
            site_names=["site-1", "site-2"],
            model_path=model_path,
            run_mode="train",
            nproc_per_client=4,
            expected_state_scope="full",
            expected_trainable_target="all",
            expected_trainable_parameters=14_770_033_664,
            expected_dataset_sha256=dataset_hashes,
        )


def _validate_full_model_workspace(roots, server_root, model_path, dataset_hashes):
    return validate_production_evidence(
        client_roots=roots,
        server_root=server_root,
        site_names=["site-1", "site-2"],
        model_path=model_path,
        run_mode="train",
        nproc_per_client=4,
        expected_state_scope="full",
        expected_trainable_target="all",
        expected_trainable_parameters=14_770_033_664,
        expected_dataset_sha256=dataset_hashes,
        expected_local_steps=8,
        expected_max_length=512,
        required_gpu_reserved_headroom_bytes=16 * 1024**3,
    )


def test_full_model_evidence_rejects_non_bf16_adamw_moments(tmp_path):
    roots, server_root, model_path, dataset_hashes = _write_full_model_workspace(tmp_path)

    def replace_moments(record):
        optimizer = record["training_evidence"]["optimizer_state"]
        optimizer["global_dtype_histogram"] = {
            "float32": {"tensor_count": 1158, "numel": 29_540_067_328, "bytes": 118_160_269_312}
        }

    _rewrite_round(roots["site-1"], replace_moments)

    with pytest.raises(RuntimeError, match="exact BF16 AdamW moment coverage"):
        _validate_full_model_workspace(roots, server_root, model_path, dataset_hashes)


def test_full_model_evidence_rejects_inexact_bf16_adamw_moment_bytes(tmp_path):
    roots, server_root, model_path, dataset_hashes = _write_full_model_workspace(tmp_path)

    def truncate_moments(record):
        record["training_evidence"]["optimizer_state"]["global_dtype_histogram"]["bfloat16"]["bytes"] -= 2

    _rewrite_round(roots["site-1"], truncate_moments)

    with pytest.raises(RuntimeError, match="exact BF16 AdamW moment coverage"):
        _validate_full_model_workspace(roots, server_root, model_path, dataset_hashes)


def test_full_model_evidence_ties_optimizer_coverage_to_pinned_parameter_count(tmp_path):
    roots, server_root, model_path, dataset_hashes = _write_full_model_workspace(tmp_path)

    def forge_self_consistent_small_round(record):
        record["model_evidence"] = {
            "total_parameters": 1,
            "trainable_parameters": 1,
            "frozen_parameters": 0,
        }
        optimizer = record["training_evidence"]["optimizer_state"]
        optimizer["global_tensor_numel"] = 2
        optimizer["global_tensor_bytes"] = 4
        optimizer["global_dtype_histogram"] = {"bfloat16": {"tensor_count": 2, "numel": 2, "bytes": 4}}

    _rewrite_round(roots["site-1"], forge_self_consistent_small_round)

    with pytest.raises(RuntimeError, match="round model parameter count mismatch"):
        _validate_full_model_workspace(roots, server_root, model_path, dataset_hashes)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("local_steps", 7, "local_steps=7"),
        ("max_length", 511, "max_length=511"),
    ],
)
def test_full_model_evidence_rejects_wrong_training_shape(tmp_path, field, value, match):
    roots, server_root, model_path, dataset_hashes = _write_full_model_workspace(tmp_path)
    _rewrite_round(roots["site-1"], lambda record: record.__setitem__(field, value))

    with pytest.raises(RuntimeError, match=match):
        _validate_full_model_workspace(roots, server_root, model_path, dataset_hashes)


def test_full_model_evidence_rejects_short_rank_trajectory(tmp_path):
    roots, server_root, model_path, dataset_hashes = _write_full_model_workspace(tmp_path)

    def truncate_rank_trajectory(record):
        record["ranks"][3]["loss_trajectory"].pop()

    _rewrite_round(roots["site-2"], truncate_rank_trajectory)

    with pytest.raises(RuntimeError, match="mismatched global loss trajectory"):
        _validate_full_model_workspace(roots, server_root, model_path, dataset_hashes)


def test_full_model_evidence_rejects_short_rank_sample_ids(tmp_path):
    roots, server_root, model_path, dataset_hashes = _write_full_model_workspace(tmp_path)

    def truncate_rank_samples(record):
        record["ranks"][3]["sample_ids"].pop()

    _rewrite_round(roots["site-2"], truncate_rank_samples)

    with pytest.raises(RuntimeError, match="rank 3 has invalid sample IDs"):
        _validate_full_model_workspace(roots, server_root, model_path, dataset_hashes)


def test_full_model_evidence_rejects_fewer_than_32_unique_site_samples(tmp_path):
    roots, server_root, model_path, dataset_hashes = _write_full_model_workspace(tmp_path)

    def duplicate_aggregate_sample(record):
        record["sample_ids"][-1] = record["sample_ids"][0]

    _rewrite_round(roots["site-1"], duplicate_aggregate_sample)

    with pytest.raises(RuntimeError, match="expected 32 unique values"):
        _validate_full_model_workspace(roots, server_root, model_path, dataset_hashes)


def test_full_model_evidence_rejects_insufficient_gpu_reserved_headroom(tmp_path):
    roots, server_root, model_path, dataset_hashes = _write_full_model_workspace(tmp_path)

    def reduce_headroom(record):
        rank = record["ranks"][0]
        rank["reserved_headroom_bytes"] = 16 * 1024**3 - 1
        rank["total_gpu_memory_bytes"] = rank["peak_gpu_reserved_bytes"] + rank["reserved_headroom_bytes"]

    _rewrite_round(roots["site-1"], reduce_headroom)

    with pytest.raises(RuntimeError, match="below required"):
        _validate_full_model_workspace(roots, server_root, model_path, dataset_hashes)
