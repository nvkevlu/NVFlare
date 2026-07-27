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

import pytest

from research.llm_fl_stress.real_training.evidence import validate_simulation_evidence


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
