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
import re
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
    expected_state_scope: str | None = None,
    expected_trainable_target: str | None = None,
    expected_local_steps: int = 0,
    expected_max_length: int = 0,
    required_gpu_reserved_headroom_bytes: int = 0,
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
    if expected_state_scope is not None and record.get("state_scope") != expected_state_scope:
        raise RuntimeError(
            f"{site_name} round has state_scope={record.get('state_scope')!r}, expected {expected_state_scope!r}"
        )
    if expected_trainable_target is not None and record.get("trainable_target") != expected_trainable_target:
        raise RuntimeError(
            f"{site_name} round has trainable_target={record.get('trainable_target')!r}, "
            f"expected {expected_trainable_target!r}"
        )
    if expected_local_steps and record.get("local_steps") != expected_local_steps:
        raise RuntimeError(
            f"{site_name} round has local_steps={record.get('local_steps')!r}, expected {expected_local_steps}"
        )
    if expected_max_length and record.get("max_length") != expected_max_length:
        raise RuntimeError(
            f"{site_name} round has max_length={record.get('max_length')!r}, expected {expected_max_length}"
        )

    trajectory = record.get("loss_trajectory")
    aggregate_sample_ids = record.get("sample_ids")
    if expected_local_steps:
        if (
            not isinstance(trajectory, list)
            or len(trajectory) != expected_local_steps
            or not all(isinstance(value, (int, float)) and math.isfinite(value) and value > 0 for value in trajectory)
        ):
            raise RuntimeError(f"{site_name} round has invalid loss trajectory {trajectory!r}")
        expected_sample_count = expected_local_steps * nproc_per_client
        if (
            not isinstance(aggregate_sample_ids, list)
            or len(aggregate_sample_ids) != expected_sample_count
            or len(set(aggregate_sample_ids)) != expected_sample_count
            or not all(isinstance(value, str) and value for value in aggregate_sample_ids)
        ):
            raise RuntimeError(
                f"{site_name} round has invalid aggregate sample IDs; expected {expected_sample_count} unique values"
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
    for rank in ranks:
        for metric in ("max_rss_bytes", "peak_gpu_allocated_bytes", "peak_gpu_reserved_bytes"):
            value = rank.get(metric)
            if not isinstance(value, int) or value <= 0:
                raise RuntimeError(f"{site_name} rank {rank.get('rank')} has invalid {metric}={value!r}")
        if rank["peak_gpu_reserved_bytes"] < rank["peak_gpu_allocated_bytes"]:
            raise RuntimeError(
                f"{site_name} rank {rank.get('rank')} reports reserved GPU memory below allocated memory"
            )
        if required_gpu_reserved_headroom_bytes:
            total_gpu_memory_bytes = rank.get("total_gpu_memory_bytes")
            reserved_headroom_bytes = rank.get("reserved_headroom_bytes")
            if not isinstance(total_gpu_memory_bytes, int) or total_gpu_memory_bytes <= 0:
                raise RuntimeError(
                    f"{site_name} rank {rank.get('rank')} has invalid "
                    f"total_gpu_memory_bytes={total_gpu_memory_bytes!r}"
                )
            expected_headroom = total_gpu_memory_bytes - rank["peak_gpu_reserved_bytes"]
            if reserved_headroom_bytes != expected_headroom:
                raise RuntimeError(
                    f"{site_name} rank {rank.get('rank')} has inconsistent "
                    f"reserved_headroom_bytes={reserved_headroom_bytes!r}, expected {expected_headroom}"
                )
            if reserved_headroom_bytes < required_gpu_reserved_headroom_bytes:
                raise RuntimeError(
                    f"{site_name} rank {rank.get('rank')} retained {reserved_headroom_bytes} bytes of reserved "
                    f"GPU headroom, below required {required_gpu_reserved_headroom_bytes}"
                )
        if expected_local_steps:
            if rank.get("loss_trajectory") != trajectory:
                raise RuntimeError(f"{site_name} rank {rank.get('rank')} has a mismatched global loss trajectory")
            rank_sample_ids = rank.get("sample_ids")
            if (
                not isinstance(rank_sample_ids, list)
                or len(rank_sample_ids) != expected_local_steps
                or len(set(rank_sample_ids)) != expected_local_steps
                or not all(isinstance(value, str) and value for value in rank_sample_ids)
            ):
                raise RuntimeError(
                    f"{site_name} rank {rank.get('rank')} has invalid sample IDs; "
                    f"expected {expected_local_steps} unique values"
                )

    if expected_local_steps:
        rank_sample_ids = [sample for rank in ranks for sample in rank["sample_ids"]]
        if sorted(rank_sample_ids) != sorted(aggregate_sample_ids):
            raise RuntimeError(f"{site_name} rank sample IDs do not match the round summary")

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


def _require_full_model_training_evidence(
    record: dict[str, Any],
    *,
    site_name: str,
    expected_trainable_parameters: int = 0,
) -> None:
    evidence = record.get("training_evidence")
    if not isinstance(evidence, dict):
        raise RuntimeError(f"{site_name} full-model round is missing training_evidence")
    update = evidence.get("update_probe")
    if not isinstance(update, dict):
        raise RuntimeError(f"{site_name} full-model round is missing update_probe evidence")
    for key in ("parameter_tensor_count", "global_sampled_value_count", "globally_changed_parameter_tensor_count"):
        value = update.get(key)
        if not isinstance(value, int) or value <= 0:
            raise RuntimeError(f"{site_name} full-model update_probe has invalid {key}={value!r}")
    change = update.get("global_max_abs_change")
    if not isinstance(change, (int, float)) or not math.isfinite(change) or change <= 0:
        raise RuntimeError(f"{site_name} full-model update_probe has invalid global_max_abs_change={change!r}")

    gradients = evidence.get("gradient_probes")
    if not isinstance(gradients, list):
        raise RuntimeError(f"{site_name} full-model round is missing gradient_probes")
    positions = {probe.get("position") for probe in gradients if isinstance(probe, dict)}
    if not {"early", "middle", "late"} <= positions:
        raise RuntimeError(f"{site_name} gradient probes do not span early/middle/late decoder layers")
    for probe in gradients:
        if (
            not isinstance(probe, dict)
            or probe.get("finite") is not True
            or probe.get("nonzero") is not True
            or not isinstance(probe.get("global_l2_norm"), (int, float))
            or not math.isfinite(probe["global_l2_norm"])
            or probe["global_l2_norm"] <= 0
        ):
            raise RuntimeError(f"{site_name} has invalid full-model gradient probe: {probe!r}")

    optimizer = evidence.get("optimizer_state")
    if not isinstance(optimizer, dict):
        raise RuntimeError(f"{site_name} full-model round is missing optimizer_state evidence")
    for key in ("global_tensor_count", "global_tensor_numel", "global_tensor_bytes"):
        value = optimizer.get(key)
        if not isinstance(value, int) or value <= 0:
            raise RuntimeError(f"{site_name} optimizer state has invalid {key}={value!r}")
    config = optimizer.get("config")
    if not isinstance(config, dict) or config.get("name") != "AdamW":
        raise RuntimeError(f"{site_name} optimizer state does not identify AdamW")
    if config.get("foreach") is not False or config.get("fused") is not False:
        raise RuntimeError(f"{site_name} optimizer state does not prove bounded foreach/fused settings")
    dtype_histogram = optimizer.get("global_dtype_histogram")
    if not isinstance(dtype_histogram, dict) or not dtype_histogram:
        raise RuntimeError(f"{site_name} optimizer state has no dtype histogram")
    model_evidence = record.get("model_evidence")
    trainable_parameters = model_evidence.get("trainable_parameters") if isinstance(model_evidence, dict) else None
    if not isinstance(trainable_parameters, int) or trainable_parameters <= 0:
        raise RuntimeError(f"{site_name} full-model round has invalid model parameter evidence")
    if (
        model_evidence.get("total_parameters") != trainable_parameters
        or model_evidence.get("frozen_parameters") != 0
        or (expected_trainable_parameters and trainable_parameters != expected_trainable_parameters)
    ):
        raise RuntimeError(
            f"{site_name} full-model round model parameter count mismatch: "
            f"expected {expected_trainable_parameters or trainable_parameters} all-trainable parameters, "
            f"observed {model_evidence!r}"
        )
    expected_moment_values = 2 * trainable_parameters
    expected_moment_bytes = 4 * trainable_parameters
    if optimizer["global_tensor_numel"] < expected_moment_values:
        raise RuntimeError(f"{site_name} optimizer state does not cover two Adam moment values per trainable parameter")
    bf16_moments = dtype_histogram.get("bfloat16")
    if (
        not isinstance(bf16_moments, dict)
        or bf16_moments.get("numel") != expected_moment_values
        or bf16_moments.get("bytes") != expected_moment_bytes
    ):
        raise RuntimeError(
            f"{site_name} optimizer state does not prove exact BF16 AdamW moment coverage: "
            f"expected {expected_moment_values} values/{expected_moment_bytes} bytes, observed {bf16_moments!r}"
        )

    cuda_phases = evidence.get("cuda_phases")
    if not isinstance(cuda_phases, list) or not cuda_phases:
        raise RuntimeError(f"{site_name} full-model round is missing CUDA phase evidence")
    phases = {
        phase.get("phase")
        for rank_record in cuda_phases
        if isinstance(rank_record, dict)
        for phase in rank_record.get("phases", [])
        if isinstance(phase, dict)
    }
    if (
        not {
            "after_state_load",
            "after_optimizer_init",
            "after_first_backward",
            "after_first_optimizer_step",
            "after_final_optimizer_step",
            "after_state_export",
        }
        <= phases
    ):
        raise RuntimeError(f"{site_name} full-model CUDA evidence is missing required phases: {sorted(phases)}")


def _bounded_state_probe(summary: Any, *, context: str) -> tuple[str, int, int, dict[tuple[str, int], float]]:
    if not isinstance(summary, dict) or summary.get("strategy") != "schema-sha256-plus-bounded-values":
        raise RuntimeError(f"{context} is missing bounded full-state probe evidence")
    schema_sha256 = summary.get("schema_sha256")
    if not isinstance(schema_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", schema_sha256):
        raise RuntimeError(f"{context} has invalid schema_sha256={schema_sha256!r}")
    tensor_count = summary.get("tensor_count")
    payload_bytes = summary.get("payload_bytes")
    if not isinstance(tensor_count, int) or tensor_count <= 0:
        raise RuntimeError(f"{context} has invalid tensor_count={tensor_count!r}")
    if not isinstance(payload_bytes, int) or payload_bytes <= 0:
        raise RuntimeError(f"{context} has invalid payload_bytes={payload_bytes!r}")
    values = {}
    for sample in summary.get("samples", []):
        if not isinstance(sample, dict):
            raise RuntimeError(f"{context} contains an invalid bounded sample")
        coordinate = (sample.get("key"), sample.get("index"))
        value = sample.get("value")
        if (
            not isinstance(coordinate[0], str)
            or not isinstance(coordinate[1], int)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise RuntimeError(f"{context} contains an invalid bounded sample: {sample!r}")
        values[coordinate] = float(value)
    if not values:
        raise RuntimeError(f"{context} contains no bounded tensor values")
    return schema_sha256, tensor_count, payload_bytes, values


def _full_state_probe_evidence(records: list[dict[str, Any]], *, site_names: list[str], num_rounds: int) -> dict:
    rounds = []
    for round_index in range(num_rounds):
        by_site = {record["site_name"]: record for record in records if record["current_round"] == round_index}
        inputs = {
            site_name: _bounded_state_probe(
                by_site[site_name].get("input_state"), context=f"{site_name} round {round_index} input state"
            )
            for site_name in site_names
        }
        outputs = {
            site_name: _bounded_state_probe(
                by_site[site_name].get("output_state"), context=f"{site_name} round {round_index} output state"
            )
            for site_name in site_names
        }
        first_input = inputs[site_names[0]]
        if any(value != first_input for value in inputs.values()):
            raise RuntimeError(f"full-state round {round_index} clients did not receive a common global input")
        for site_name, output in outputs.items():
            if output[:3] != first_input[:3]:
                raise RuntimeError(f"{site_name} round {round_index} output changed the full-state tensor schema")
        output_value_maps = [outputs[site_name][3] for site_name in site_names]
        rounds.append(
            {
                "current_round": round_index,
                "schema_sha256": first_input[0],
                "tensor_count": first_input[1],
                "payload_bytes": first_input[2],
                "sample_count": len(first_input[3]),
                "client_output_samples_distinct": len({tuple(sorted(value.items())) for value in output_value_maps})
                == len(site_names),
            }
        )
    return {"status": "PASS", "rounds": rounds}


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
    expected_state_scope: str | None = None,
    expected_trainable_target: str | None = None,
    expected_trainable_parameters: int = 0,
    expected_dataset_sha256: dict[str, str] | None = None,
    expected_local_steps: int = 0,
    expected_max_length: int = 0,
    required_gpu_reserved_headroom_bytes: int = 0,
) -> dict[str, Any]:
    for name, value in (
        ("expected_local_steps", expected_local_steps),
        ("expected_max_length", expected_max_length),
        ("required_gpu_reserved_headroom_bytes", required_gpu_reserved_headroom_bytes),
    ):
        if value < 0:
            raise ValueError(f"{name} must not be negative")
    client_records = []
    client_ready_records = []
    for site_name in site_names:
        site_root = client_roots.get(site_name)
        if site_root is None:
            raise RuntimeError(f"result is missing client root for {site_name}")
        if not site_root.is_dir():
            raise RuntimeError(f"result is missing client directory: {site_root}")
        records = _unique_records(_json_events(_log_files(site_root), _ROUND_EVENT))
        require_ready = any(
            value is not None for value in (expected_state_scope, expected_trainable_target, expected_dataset_sha256)
        ) or bool(expected_trainable_parameters)
        if require_ready:
            ready_records = _unique_records(_json_events(_log_files(site_root), "real_training_client_ready"))
            matching_ready = [
                record
                for record in ready_records
                if record.get("site_name") == site_name
                and (expected_model_path is None or record.get("model_path") == str(expected_model_path))
            ]
            if len(matching_ready) != 1:
                raise RuntimeError(
                    f"{site_name} must have exactly one matching client-ready record, found {len(matching_ready)}"
                )
            ready = matching_ready[0]
            if expected_state_scope is not None and ready.get("state_scope") != expected_state_scope:
                raise RuntimeError(f"{site_name} ready record has wrong state_scope={ready.get('state_scope')!r}")
            if expected_trainable_target is not None and ready.get("trainable_target") != expected_trainable_target:
                raise RuntimeError(
                    f"{site_name} ready record has wrong trainable_target={ready.get('trainable_target')!r}"
                )
            if (
                expected_dataset_sha256 is not None
                and ready.get("dataset_sha256") != expected_dataset_sha256[site_name]
            ):
                raise RuntimeError(f"{site_name} ready record has wrong dataset_sha256")
            if expected_trainable_target == "all":
                total_parameters = ready.get("total_parameters")
                trainable_parameters = ready.get("trainable_parameters")
                if not isinstance(total_parameters, int) or total_parameters <= 0:
                    raise RuntimeError(f"{site_name} ready record has invalid total_parameters={total_parameters!r}")
                if trainable_parameters != total_parameters or ready.get("frozen_parameters") != 0:
                    raise RuntimeError(f"{site_name} ready record does not prove every parameter is trainable")
                if expected_trainable_parameters and trainable_parameters != expected_trainable_parameters:
                    raise RuntimeError(
                        f"{site_name} trainable parameter count mismatch: expected {expected_trainable_parameters}, "
                        f"observed {trainable_parameters}"
                    )
                if ready.get("trainable_tensor_count") != ready.get("total_tensor_count"):
                    raise RuntimeError(f"{site_name} ready record does not prove every parameter tensor is trainable")
                if ready.get("frozen_tensor_count") != 0:
                    raise RuntimeError(f"{site_name} ready record reports frozen parameter tensors")
                if ready.get("gradient_checkpointing_enabled") is not True:
                    raise RuntimeError(f"{site_name} did not enable gradient checkpointing for full-model training")
            client_ready_records.append(ready)
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
                expected_state_scope=expected_state_scope,
                expected_trainable_target=expected_trainable_target,
                expected_local_steps=expected_local_steps,
                expected_max_length=expected_max_length,
                required_gpu_reserved_headroom_bytes=required_gpu_reserved_headroom_bytes,
            )
            if expected_dataset_sha256 is not None:
                if record.get("dataset_sha256") != expected_dataset_sha256[site_name]:
                    raise RuntimeError(f"{site_name} round has wrong dataset_sha256")
                sample_ids = record.get("sample_ids")
                if not isinstance(sample_ids, list) or not sample_ids:
                    raise RuntimeError(f"{site_name} round has no dataset sample IDs")
            if expected_trainable_target == "all":
                _require_full_model_training_evidence(
                    record,
                    site_name=site_name,
                    expected_trainable_parameters=expected_trainable_parameters,
                )
            client_records.append(record)

    per_site_samples = None
    if expected_dataset_sha256 is not None or expected_local_steps:
        if expected_dataset_sha256 is not None and len(set(expected_dataset_sha256.values())) != len(site_names):
            raise RuntimeError("client dataset partitions must have distinct SHA-256 values")
        per_site_samples = {
            site_name: {
                sample
                for record in client_records
                if record.get("site_name") == site_name
                for sample in record.get("sample_ids", [])
            }
            for site_name in site_names
        }
        if expected_local_steps:
            expected_samples_per_site = expected_local_steps * nproc_per_client * num_rounds
            for site_name in site_names:
                if len(per_site_samples[site_name]) != expected_samples_per_site:
                    raise RuntimeError(
                        f"{site_name} produced {len(per_site_samples[site_name])} unique sample IDs, "
                        f"expected {expected_samples_per_site}"
                    )
        for index, site_name in enumerate(site_names):
            for other in site_names[index + 1 :]:
                overlap = per_site_samples[site_name] & per_site_samples[other]
                if overlap:
                    raise RuntimeError(f"client dataset sample IDs overlap between {site_name} and {other}: {overlap}")

    full_state_probes = None
    if expected_state_scope == "full" and expected_trainable_target == "all":
        full_state_probes = _full_state_probe_evidence(
            client_records,
            site_names=site_names,
            num_rounds=num_rounds,
        )

    payloads = {record["payload_bytes"] for record in client_records}
    tensor_counts = {record["tensor_count"] for record in client_records}
    if len(payloads) != 1 or len(tensor_counts) != 1:
        raise RuntimeError("client round records disagree on exchanged-state shape")

    if not server_root.is_dir():
        raise RuntimeError(f"result is missing server directory: {server_root}")
    server_text = "\n".join(
        log_path.read_text(encoding="utf-8", errors="replace") for log_path in _log_files(server_root)
    )
    expected_aggregation = f"Aggregated {len(site_names)}/{len(site_names)} results"
    observed_aggregations = server_text.count(expected_aggregation)
    if observed_aggregations < num_rounds:
        raise RuntimeError(
            f"server log contains {observed_aggregations} {expected_aggregation!r} records, "
            f"expected at least {num_rounds}"
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
                "ranks": record["ranks"],
            }
            for record in client_records
        ],
        "aggregated_results": len(site_names),
        "persisted": True,
        "payload_bytes_per_client": payloads.pop(),
        "tensor_count": tensor_counts.pop(),
        "client_ready": client_ready_records,
        "full_state_probe_evidence": full_state_probes,
        "unique_samples_per_site": (
            {site_name: len(per_site_samples[site_name]) for site_name in site_names}
            if per_site_samples is not None
            else None
        ),
    }


def validate_simulation_evidence(
    run_root: Path,
    *,
    site_names: list[str],
    run_mode: str,
    nproc_per_client: int,
    num_rounds: int = 1,
    expected_gpu_name_substring: str | None = None,
    expected_state_scope: str | None = None,
    expected_trainable_target: str | None = None,
    expected_trainable_parameters: int = 0,
    expected_dataset_sha256: dict[str, str] | None = None,
    expected_local_steps: int = 0,
    expected_max_length: int = 0,
    required_gpu_reserved_headroom_bytes: int = 0,
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
        expected_state_scope=expected_state_scope,
        expected_trainable_target=expected_trainable_target,
        expected_trainable_parameters=expected_trainable_parameters,
        expected_dataset_sha256=expected_dataset_sha256,
        expected_local_steps=expected_local_steps,
        expected_max_length=expected_max_length,
        required_gpu_reserved_headroom_bytes=required_gpu_reserved_headroom_bytes,
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
    expected_state_scope: str | None = None,
    expected_trainable_target: str | None = None,
    expected_trainable_parameters: int = 0,
    expected_dataset_sha256: dict[str, str] | None = None,
    expected_local_steps: int = 0,
    expected_max_length: int = 0,
    required_gpu_reserved_headroom_bytes: int = 0,
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
        expected_state_scope=expected_state_scope,
        expected_trainable_target=expected_trainable_target,
        expected_trainable_parameters=expected_trainable_parameters,
        expected_dataset_sha256=expected_dataset_sha256,
        expected_local_steps=expected_local_steps,
        expected_max_length=expected_max_length,
        required_gpu_reserved_headroom_bytes=required_gpu_reserved_headroom_bytes,
    )


def _state_sample_map(summary: dict[str, Any], *, context: str) -> dict[tuple[str, int], float]:
    sha256 = summary.get("sha256")
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise RuntimeError(f"{context} has invalid sha256={sha256!r}")
    for name in ("tensor_count", "payload_bytes"):
        value = summary.get(name)
        if not isinstance(value, int) or value <= 0:
            raise RuntimeError(f"{context} has invalid {name}={value!r}")
    samples = summary.get("samples")
    if not isinstance(samples, list) or not samples:
        raise RuntimeError(f"{context} has no tensor samples")
    result = {}
    for sample in samples:
        if not isinstance(sample, dict):
            raise RuntimeError(f"{context} contains a non-object tensor sample")
        key = sample.get("key")
        index = sample.get("index")
        value = sample.get("value")
        if (
            not isinstance(key, str)
            or not isinstance(index, int)
            or index < 0
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise RuntimeError(f"{context} contains an invalid tensor sample: {sample!r}")
        coordinate = (key, index)
        if coordinate in result:
            raise RuntimeError(f"{context} contains duplicate tensor sample {coordinate!r}")
        result[coordinate] = float(value)
    return result


def validate_trainable_state_evidence(
    *,
    client_roots: dict[str, Path],
    site_names: list[str],
    model_path: Path,
    num_rounds: int,
    local_steps: int,
    nproc_per_client: int,
    expected_dataset_sha256: dict[str, str],
    persisted_models: list[dict[str, Any]],
    max_payload_bytes: int,
) -> dict[str, Any]:
    """Prove trainable-only exchange, client divergence, FedAvg, and round continuity."""

    by_round: dict[int, dict[str, dict[str, Any]]] = {round_index: {} for round_index in range(num_rounds)}
    all_sample_ids: dict[str, set[str]] = {site_name: set() for site_name in site_names}
    for site_name in site_names:
        root = client_roots[site_name]
        records = _unique_records(_json_events(_log_files(root), _ROUND_EVENT))
        matching = [
            record
            for record in records
            if record.get("site_name") == site_name and record.get("model_path") == str(model_path)
        ]
        if len(matching) != num_rounds:
            raise RuntimeError(
                f"{site_name} trainable-state evidence expected {num_rounds} rounds, found {len(matching)}"
            )
        for record in matching:
            round_index = record.get("current_round")
            if round_index not in by_round or site_name in by_round[round_index]:
                raise RuntimeError(f"{site_name} has invalid or duplicate trainable-state round {round_index!r}")
            if record.get("state_scope") != "trainable":
                raise RuntimeError(f"{site_name} round {round_index} did not use trainable-state exchange")
            if record.get("dataset_sha256") != expected_dataset_sha256.get(site_name):
                raise RuntimeError(f"{site_name} round {round_index} has an unexpected dataset checksum")
            trajectory = record.get("loss_trajectory")
            if (
                not isinstance(trajectory, list)
                or len(trajectory) != local_steps
                or not all(
                    isinstance(value, (int, float)) and math.isfinite(value) and value > 0 for value in trajectory
                )
            ):
                raise RuntimeError(f"{site_name} round {round_index} has invalid loss trajectory {trajectory!r}")
            sample_ids = record.get("sample_ids")
            expected_samples = local_steps * nproc_per_client
            if (
                not isinstance(sample_ids, list)
                or len(sample_ids) != expected_samples
                or len(set(sample_ids)) != expected_samples
                or not all(isinstance(value, str) and value for value in sample_ids)
            ):
                raise RuntimeError(f"{site_name} round {round_index} has invalid sample IDs")
            overlap = all_sample_ids[site_name].intersection(sample_ids)
            if overlap:
                raise RuntimeError(f"{site_name} reused dataset records across rounds: {sorted(overlap)}")
            all_sample_ids[site_name].update(sample_ids)
            rank_records = record.get("ranks")
            if not isinstance(rank_records, list) or len(rank_records) != nproc_per_client:
                raise RuntimeError(f"{site_name} round {round_index} has incomplete rank evidence")
            rank_sample_ids = []
            for rank_record in rank_records:
                if rank_record.get("loss_trajectory") != trajectory:
                    raise RuntimeError(
                        f"{site_name} round {round_index} rank {rank_record.get('rank')} "
                        "has a mismatched global loss trajectory"
                    )
                local_ids = rank_record.get("sample_ids")
                if (
                    not isinstance(local_ids, list)
                    or len(local_ids) != local_steps
                    or len(set(local_ids)) != local_steps
                ):
                    raise RuntimeError(
                        f"{site_name} round {round_index} rank {rank_record.get('rank')} "
                        "has invalid local sample IDs"
                    )
                rank_sample_ids.extend(local_ids)
            if sorted(rank_sample_ids) != sorted(sample_ids):
                raise RuntimeError(f"{site_name} round {round_index} rank sample IDs do not match the summary")

            input_state = record.get("input_state")
            output_state = record.get("output_state")
            if not isinstance(input_state, dict) or not isinstance(output_state, dict):
                raise RuntimeError(f"{site_name} round {round_index} is missing input/output state evidence")
            input_samples = _state_sample_map(input_state, context=f"{site_name} round {round_index} input")
            output_samples = _state_sample_map(output_state, context=f"{site_name} round {round_index} output")
            if input_samples.keys() != output_samples.keys():
                raise RuntimeError(f"{site_name} round {round_index} changed the exchanged tensor schema")
            if input_state["payload_bytes"] > max_payload_bytes:
                raise RuntimeError(
                    f"{site_name} round {round_index} payload {input_state['payload_bytes']} exceeds "
                    f"trainable-only ceiling {max_payload_bytes}"
                )
            if (
                input_state["payload_bytes"] != output_state["payload_bytes"]
                or input_state["tensor_count"] != output_state["tensor_count"]
                or input_state["payload_bytes"] != record.get("payload_bytes")
                or input_state["tensor_count"] != record.get("tensor_count")
            ):
                raise RuntimeError(f"{site_name} round {round_index} has inconsistent exchanged-state shape")
            if input_state["sha256"] == output_state["sha256"]:
                raise RuntimeError(f"{site_name} round {round_index} did not change its trainable state")
            by_round[round_index][site_name] = record

    if len(set(expected_dataset_sha256.values())) != len(site_names):
        raise RuntimeError("qualification client datasets are not distinct")
    if len(persisted_models) != num_rounds:
        raise RuntimeError(f"expected {num_rounds} persisted checkpoints, found {len(persisted_models)}")

    previous_persisted_hash = None
    for round_index in range(num_rounds):
        records = by_round[round_index]
        if set(records) != set(site_names):
            raise RuntimeError(f"round {round_index} is missing trainable-state client evidence")
        input_hashes = {record["input_state"]["sha256"] for record in records.values()}
        output_hashes = {record["output_state"]["sha256"] for record in records.values()}
        if len(input_hashes) != 1:
            raise RuntimeError(f"clients received different global inputs in round {round_index}")
        if len(output_hashes) != len(site_names):
            raise RuntimeError(f"client updates did not diverge in round {round_index}")
        if previous_persisted_hash is not None and input_hashes != {previous_persisted_hash}:
            raise RuntimeError(f"round {round_index} input is not the preceding persisted global state")

        persisted = persisted_models[round_index]
        if persisted.get("reload_status") != "PASS" or not isinstance(persisted.get("state"), dict):
            raise RuntimeError(f"persisted checkpoint {round_index} was not successfully reloaded")
        persisted_state = persisted["state"]
        persisted_samples = _state_sample_map(persisted_state, context=f"persisted round {round_index}")
        client_sample_maps = [
            _state_sample_map(
                records[site_name]["output_state"],
                context=f"{site_name} round {round_index} output",
            )
            for site_name in site_names
        ]
        if any(samples.keys() != persisted_samples.keys() for samples in client_sample_maps):
            raise RuntimeError(f"persisted round {round_index} tensor samples do not match client schemas")
        for coordinate, persisted_value in persisted_samples.items():
            expected_value = sum(samples[coordinate] for samples in client_sample_maps) / len(client_sample_maps)
            if not math.isclose(persisted_value, expected_value, rel_tol=0.01, abs_tol=0.02):
                raise RuntimeError(
                    f"persisted round {round_index} sample {coordinate!r} is not the equal-weight client mean: "
                    f"expected {expected_value}, observed {persisted_value}"
                )
        if (
            persisted_state["payload_bytes"] != records[site_names[0]]["payload_bytes"]
            or persisted_state["tensor_count"] != records[site_names[0]]["tensor_count"]
        ):
            raise RuntimeError(f"persisted round {round_index} has an unexpected state schema")
        if persisted_state["sha256"] in input_hashes:
            raise RuntimeError(f"persisted round {round_index} did not change the global trainable state")
        previous_persisted_hash = persisted_state["sha256"]

    payload_bytes = next(iter(by_round[0].values()))["payload_bytes"]
    return {
        "event": "real_training_trainable_state_evidence",
        "status": "PASS",
        "state_scope": "trainable",
        "num_rounds": num_rounds,
        "local_steps": local_steps,
        "dataset_sha256": expected_dataset_sha256,
        "unique_samples_per_site": {site_name: len(all_sample_ids[site_name]) for site_name in site_names},
        "payload_bytes_per_transfer": payload_bytes,
        "logical_wire_bytes": payload_bytes * len(site_names) * 2 * num_rounds,
        "persisted_checkpoints_reloaded": len(persisted_models),
        "final_persisted_sha256": previous_persisted_hash,
    }
