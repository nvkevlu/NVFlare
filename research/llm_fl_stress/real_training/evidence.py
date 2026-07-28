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

"""Fail-closed evidence validation for a real-training simulation."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

_ROUND_EVENT = "real_training_round"
_LOG_PATTERNS = ("*.log", "*.txt")


def _log_files(root: Path) -> list[Path]:
    files: set[Path] = set()
    for pattern in _LOG_PATTERNS:
        files.update(root.rglob(pattern))
    return sorted(files)


def _json_events(paths: Iterable[Path], event: str) -> list[dict[str, Any]]:
    records = []
    for log_path in paths:
        with log_path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                marker = line.find("{")
                if marker < 0:
                    continue
                try:
                    record = json.loads(line[marker:])
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and record.get("event") == event:
                    records.append(record)
    return records


def _unique_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {}
    for record in records:
        unique[json.dumps(record, sort_keys=True)] = record
    return list(unique.values())


def _require_rank_evidence(
    record: dict[str, Any],
    *,
    site_name: str,
    run_mode: str,
    nproc_per_client: int,
    expected_gpu_name_substring: str | None,
) -> None:
    if record.get("status") != "PASS":
        raise RuntimeError(f"{site_name} round did not report PASS")
    if record.get("site_name") != site_name:
        raise RuntimeError(f"{site_name} round has mismatched site_name={record.get('site_name')!r}")
    if record.get("run_mode") != run_mode:
        raise RuntimeError(f"{site_name} round has run_mode={record.get('run_mode')!r}, expected {run_mode!r}")
    if record.get("world_size") != nproc_per_client:
        raise RuntimeError(
            f"{site_name} round has world_size={record.get('world_size')!r}, expected {nproc_per_client}"
        )

    ranks = record.get("ranks")
    if not isinstance(ranks, list) or len(ranks) != nproc_per_client:
        raise RuntimeError(f"{site_name} round does not contain telemetry for {nproc_per_client} ranks")
    if {rank.get("rank") for rank in ranks} != set(range(nproc_per_client)):
        raise RuntimeError(f"{site_name} round has incomplete global rank telemetry")
    if {rank.get("local_rank") for rank in ranks} != set(range(nproc_per_client)):
        raise RuntimeError(f"{site_name} round has incomplete local rank telemetry")
    if expected_gpu_name_substring:
        for rank in ranks:
            gpu_name = str(rank.get("gpu_name", ""))
            if expected_gpu_name_substring not in gpu_name:
                raise RuntimeError(
                    f"{site_name} rank {rank.get('rank')} used GPU {gpu_name!r}, "
                    f"expected a name containing {expected_gpu_name_substring!r}"
                )

    loss = record.get("loss")
    change = record.get("selected_max_abs_change")
    if not isinstance(loss, (int, float)) or not math.isfinite(loss):
        raise RuntimeError(f"{site_name} round has non-finite loss={loss!r}")
    if not isinstance(change, (int, float)) or not math.isfinite(change):
        raise RuntimeError(f"{site_name} round has non-finite selected_max_abs_change={change!r}")
    if run_mode == "train":
        if loss <= 0.0:
            raise RuntimeError(f"{site_name} training loss must be positive, got {loss!r}")
        if change <= 0.0:
            raise RuntimeError(f"{site_name} training did not change a selected parameter")
    elif loss != 0.0 or change != 0.0:
        raise RuntimeError(f"{site_name} exchange-only round unexpectedly changed the model")

    if not isinstance(record.get("payload_bytes"), int) or record["payload_bytes"] <= 0:
        raise RuntimeError(f"{site_name} round has invalid payload_bytes={record.get('payload_bytes')!r}")
    if not isinstance(record.get("tensor_count"), int) or record["tensor_count"] <= 0:
        raise RuntimeError(f"{site_name} round has invalid tensor_count={record.get('tensor_count')!r}")


def _validate_evidence(
    client_roots: dict[str, Path],
    server_root: Path,
    *,
    site_names: list[str],
    run_mode: str,
    nproc_per_client: int,
    num_rounds: int = 1,
    expected_gpu_name_substring: str | None = None,
    expected_model_path: Path | None = None,
) -> dict[str, Any]:
    client_records = []
    for site_name in site_names:
        site_root = client_roots.get(site_name)
        if site_root is None:
            raise RuntimeError(f"result is missing client root for {site_name}")
        if not site_root.is_dir():
            raise RuntimeError(f"result is missing client directory: {site_root}")
        records = _unique_records(_json_events(_log_files(site_root), _ROUND_EVENT))
        matching = sorted(
            (
                record
                for record in records
                if record.get("site_name") == site_name
                and (expected_model_path is None or record.get("model_path") == str(expected_model_path))
            ),
            key=lambda record: record["current_round"] if isinstance(record.get("current_round"), int) else -1,
        )
        if len(matching) != num_rounds:
            raise RuntimeError(
                f"{site_name} must have exactly {num_rounds} unique {_ROUND_EVENT} records, found {len(matching)}"
            )
        observed_rounds = {record.get("current_round") for record in matching}
        if observed_rounds != set(range(num_rounds)):
            raise RuntimeError(f"{site_name} has incomplete round indices: {observed_rounds!r}")
        for record in matching:
            _require_rank_evidence(
                record,
                site_name=site_name,
                run_mode=run_mode,
                nproc_per_client=nproc_per_client,
                expected_gpu_name_substring=expected_gpu_name_substring,
            )
            client_records.append(record)

    payloads = {record["payload_bytes"] for record in client_records}
    tensor_counts = {record["tensor_count"] for record in client_records}
    if len(payloads) != 1 or len(tensor_counts) != 1:
        raise RuntimeError("client round records disagree on full-state shape")

    if not server_root.is_dir():
        raise RuntimeError(f"result is missing server directory: {server_root}")
    server_text = "\n".join(
        log_path.read_text(encoding="utf-8", errors="replace") for log_path in _log_files(server_root)
    )
    expected_aggregation = f"Aggregated {len(site_names)}/{len(site_names)} results"
    observed_aggregations = server_text.count(expected_aggregation)
    if observed_aggregations < num_rounds:
        raise RuntimeError(
            f"server log contains {observed_aggregations} {expected_aggregation!r} records, expected at least {num_rounds}"
        )
    if "End persist model on server." not in server_text:
        raise RuntimeError("server log does not confirm final model persistence")

    return {
        "event": "real_training_federation",
        "status": "PASS",
        "num_clients": len(site_names),
        "num_rounds": num_rounds,
        "sites": [
            {
                "site_name": record["site_name"],
                "current_round": record["current_round"],
                "loss": record["loss"],
                "selected_max_abs_change": record["selected_max_abs_change"],
                "payload_bytes": record["payload_bytes"],
                "tensor_count": record["tensor_count"],
                "round_seconds": record["round_seconds"],
                "max_rank_rss_bytes": max(rank["max_rss_bytes"] for rank in record["ranks"]),
                "max_gpu_allocated_bytes": max(rank["peak_gpu_allocated_bytes"] for rank in record["ranks"]),
                "max_gpu_reserved_bytes": max(rank["peak_gpu_reserved_bytes"] for rank in record["ranks"]),
            }
            for record in client_records
        ],
        "aggregated_results": len(site_names),
        "persisted": True,
        "payload_bytes_per_client": payloads.pop(),
        "tensor_count": tensor_counts.pop(),
    }


def validate_simulation_evidence(
    run_root: Path,
    *,
    site_names: list[str],
    run_mode: str,
    nproc_per_client: int,
    num_rounds: int = 1,
    expected_gpu_name_substring: str | None = None,
) -> dict[str, Any]:
    """Require every configured simulation client plus server aggregation and persistence."""

    if not run_root.is_dir():
        raise RuntimeError(f"simulation result directory does not exist: {run_root}")
    return _validate_evidence(
        {site_name: run_root / site_name for site_name in site_names},
        run_root / "server",
        site_names=site_names,
        run_mode=run_mode,
        nproc_per_client=nproc_per_client,
        num_rounds=num_rounds,
        expected_gpu_name_substring=expected_gpu_name_substring,
    )


def validate_production_evidence(
    *,
    client_roots: dict[str, Path],
    server_root: Path,
    site_names: list[str],
    model_path: Path,
    run_mode: str,
    nproc_per_client: int,
    num_rounds: int = 1,
    expected_gpu_name_substring: str | None = None,
) -> dict[str, Any]:
    """Validate one provisioned production job without downloading its full model."""

    return _validate_evidence(
        client_roots,
        server_root,
        site_names=site_names,
        run_mode=run_mode,
        nproc_per_client=nproc_per_client,
        num_rounds=num_rounds,
        expected_gpu_name_substring=expected_gpu_name_substring,
        expected_model_path=model_path,
    )
