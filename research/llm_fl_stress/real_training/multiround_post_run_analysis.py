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

"""Analyze retained evidence from a full-state, two-client multiround run.

This is deliberately a post-run, CPU-only analysis.  It reads the compact
bounded state probes already present in client logs; it never loads a model or
one of the large persisted checkpoints.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

_EVENT = "real_training_round"
_PHASE_NAME = "target-14b-full-model-multiround"
_SITE_NAMES = ("site-1", "site-2")
_LOG_PATTERNS = ("*.log", "*.txt")
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}")


class AnalysisError(RuntimeError):
    """Raised when retained evidence cannot support the requested claim."""


@dataclass(frozen=True)
class _Probe:
    schema_sha256: str
    tensor_count: int
    payload_bytes: int
    values: dict[tuple[str, int], float]

    @property
    def coordinates(self) -> frozenset[tuple[str, int]]:
        return frozenset(self.values)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AnalysisError(message)


def _read_json(path: Path, *, context: str) -> dict[str, Any]:
    _require(path.is_file(), f"{context} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"cannot read {context} {path}: {exc}") from exc
    _require(isinstance(value, dict), f"{context} must be a JSON object: {path}")
    return value


def _read_manifest(path: Path) -> dict[str, str]:
    _require(path.is_file(), f"manifest does not exist: {path}")
    result = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        _require("=" in line, f"manifest line {line_number} is not key=value")
        key, value = line.split("=", maxsplit=1)
        _require(bool(key) and key not in result, f"manifest contains invalid or duplicate key {key!r}")
        result[key] = value
    return result


def _log_files(root: Path) -> list[Path]:
    _require(root.is_dir(), f"retained log directory does not exist: {root}")
    files: set[Path] = set()
    for pattern in _LOG_PATTERNS:
        files.update(root.rglob(pattern))
    result = sorted(path for path in files if path.is_file())
    _require(bool(result), f"retained log directory contains no logs: {root}")
    return result


def _json_events(paths: Iterable[Path], event: str) -> list[dict[str, Any]]:
    records = []
    for path in paths:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                marker = line.find("{")
                if marker < 0:
                    continue
                try:
                    value = json.loads(line[marker:])
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and value.get("event") == event:
                    records.append(value)
    return records


def _unique_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {}
    for record in records:
        unique[json.dumps(record, sort_keys=True)] = record
    return list(unique.values())


def _parse_probe(
    value: Any,
    *,
    context: str,
    expected_tensor_count: int,
    expected_payload_bytes: int,
    samples_per_tensor_bound: int,
) -> _Probe:
    _require(isinstance(value, dict), f"{context} is not a state-probe object")
    _require(
        value.get("strategy") == "schema-sha256-plus-bounded-values",
        f"{context} does not use the bounded full-state probe strategy",
    )
    schema_sha256 = value.get("schema_sha256")
    _require(
        isinstance(schema_sha256, str) and _HEX_SHA256.fullmatch(schema_sha256) is not None,
        f"{context} has invalid schema_sha256={schema_sha256!r}",
    )
    tensor_count = value.get("tensor_count")
    payload_bytes = value.get("payload_bytes")
    _require(
        type(tensor_count) is int and tensor_count == expected_tensor_count,
        f"{context} tensor_count={tensor_count!r}, expected {expected_tensor_count}",
    )
    _require(
        type(payload_bytes) is int and payload_bytes == expected_payload_bytes,
        f"{context} payload_bytes={payload_bytes!r}, expected {expected_payload_bytes}",
    )
    samples = value.get("samples")
    _require(isinstance(samples, list) and samples, f"{context} has no bounded samples")
    bound = tensor_count * samples_per_tensor_bound
    _require(len(samples) <= bound, f"{context} has {len(samples)} samples, above the bound of {bound}")

    values = {}
    for position, sample in enumerate(samples):
        _require(isinstance(sample, dict), f"{context} sample {position} is not an object")
        key = sample.get("key")
        index = sample.get("index")
        observed = sample.get("value")
        _require(isinstance(key, str) and key, f"{context} sample {position} has invalid key={key!r}")
        _require(type(index) is int and index >= 0, f"{context} sample {position} has invalid index={index!r}")
        _require(
            isinstance(observed, (int, float)) and not isinstance(observed, bool) and math.isfinite(float(observed)),
            f"{context} sample {position} has non-finite value={observed!r}",
        )
        coordinate = (key, index)
        _require(coordinate not in values, f"{context} repeats bounded sample coordinate {coordinate!r}")
        values[coordinate] = float(observed)
    return _Probe(
        schema_sha256=schema_sha256,
        tensor_count=tensor_count,
        payload_bytes=payload_bytes,
        values=values,
    )


def _bf16_round(value: float) -> float:
    """Round a finite value to IEEE bfloat16, returning a Python float."""

    _require(math.isfinite(value), f"cannot bfloat16-round non-finite value {value!r}")
    try:
        bits = struct.unpack(">I", struct.pack(">f", value))[0]
    except OverflowError as exc:
        raise AnalysisError(f"value is outside finite float32 range: {value!r}") from exc
    upper = bits >> 16
    rounded_bits = (bits + 0x7FFF + (upper & 1)) & 0xFFFF0000
    result = struct.unpack(">f", struct.pack(">I", rounded_bits))[0]
    _require(math.isfinite(result), f"bfloat16 rounding overflowed for {value!r}")
    return result


def _bf16_ulp(value: float) -> float:
    rounded = _bf16_round(value)
    bits = struct.unpack(">I", struct.pack(">f", rounded))[0] & 0x7FFFFFFF
    exponent = (bits >> 23) & 0xFF
    _require(exponent != 0xFF, f"cannot calculate bfloat16 ULP for {value!r}")
    if exponent == 0:
        return math.ldexp(1.0, -133)
    return math.ldexp(1.0, exponent - 127 - 7)


def _same_probe_metadata(left: _Probe, right: _Probe) -> bool:
    return (
        left.schema_sha256 == right.schema_sha256
        and left.tensor_count == right.tensor_count
        and left.payload_bytes == right.payload_bytes
        and left.coordinates == right.coordinates
    )


def _round_records(
    phase_root: Path,
    *,
    model_path: str,
    expected_rounds: int,
) -> dict[str, list[dict[str, Any]]]:
    result = {}
    for site_name in _SITE_NAMES:
        records = _unique_records(_json_events(_log_files(phase_root / "logs" / site_name), _EVENT))
        records = [record for record in records if record.get("model_path") == model_path]
        _require(
            len(records) == expected_rounds,
            f"{site_name} has {len(records)} unique matching round records, expected exactly {expected_rounds}",
        )
        by_round = {}
        for record in records:
            _require(
                record.get("site_name") == site_name,
                f"{site_name} log contains round evidence for site_name={record.get('site_name')!r}",
            )
            current_round = record.get("current_round")
            _require(
                type(current_round) is int and 0 <= current_round < expected_rounds,
                f"{site_name} has invalid current_round={current_round!r}",
            )
            _require(current_round not in by_round, f"{site_name} has multiple records for round {current_round}")
            by_round[current_round] = record
        _require(
            set(by_round) == set(range(expected_rounds)),
            f"{site_name} has incomplete round indices {sorted(by_round)}",
        )
        result[site_name] = [by_round[index] for index in range(expected_rounds)]
    return result


def _validate_sample_ids(
    records: dict[str, list[dict[str, Any]]],
    *,
    expected_rounds: int,
    local_steps: int,
    nproc_per_client: int,
) -> dict[str, Any]:
    expected_per_round = local_steps * nproc_per_client
    all_samples = {}
    for site_name in _SITE_NAMES:
        observed = []
        for round_index, record in enumerate(records[site_name]):
            sample_ids = record.get("sample_ids")
            _require(
                isinstance(sample_ids, list)
                and len(sample_ids) == expected_per_round
                and all(isinstance(sample_id, str) and sample_id for sample_id in sample_ids),
                f"{site_name} round {round_index} does not contain {expected_per_round} valid sample IDs",
            )
            _require(
                len(set(sample_ids)) == expected_per_round,
                f"{site_name} round {round_index} contains duplicate sample IDs",
            )
            observed.extend(sample_ids)
        expected_total = expected_rounds * expected_per_round
        _require(
            len(observed) == expected_total and len(set(observed)) == expected_total,
            f"{site_name} did not use exactly {expected_total} unique samples across all rounds",
        )
        all_samples[site_name] = set(observed)
    overlap = all_samples["site-1"] & all_samples["site-2"]
    _require(not overlap, f"client sample IDs overlap: {sorted(overlap)[:10]}")
    return {
        "status": "PASS",
        "expected_per_round": expected_per_round,
        "unique_samples_per_site": {site_name: len(all_samples[site_name]) for site_name in _SITE_NAMES},
        "cross_site_overlap": 0,
    }


def _parse_round_probes(
    records: dict[str, list[dict[str, Any]]],
    *,
    expected_rounds: int,
    expected_tensor_count: int,
    expected_payload_bytes: int,
    samples_per_tensor_bound: int,
) -> tuple[dict[str, list[_Probe]], dict[str, list[_Probe]], list[dict[str, Any]]]:
    inputs = {site_name: [] for site_name in _SITE_NAMES}
    outputs = {site_name: [] for site_name in _SITE_NAMES}
    round_reports = []
    reference_coordinates: frozenset[tuple[str, int]] | None = None
    reference_schema = None

    for round_index in range(expected_rounds):
        for site_name in _SITE_NAMES:
            record = records[site_name][round_index]
            for field in ("state_scope", "trainable_target", "status"):
                expected = {"state_scope": "full", "trainable_target": "all", "status": "PASS"}[field]
                _require(
                    record.get(field) == expected,
                    f"{site_name} round {round_index} has {field}={record.get(field)!r}, expected {expected!r}",
                )
            inputs[site_name].append(
                _parse_probe(
                    record.get("input_state"),
                    context=f"{site_name} round {round_index} input_state",
                    expected_tensor_count=expected_tensor_count,
                    expected_payload_bytes=expected_payload_bytes,
                    samples_per_tensor_bound=samples_per_tensor_bound,
                )
            )
            outputs[site_name].append(
                _parse_probe(
                    record.get("output_state"),
                    context=f"{site_name} round {round_index} output_state",
                    expected_tensor_count=expected_tensor_count,
                    expected_payload_bytes=expected_payload_bytes,
                    samples_per_tensor_bound=samples_per_tensor_bound,
                )
            )

        first_input = inputs["site-1"][round_index]
        second_input = inputs["site-2"][round_index]
        _require(
            _same_probe_metadata(first_input, second_input) and first_input.values == second_input.values,
            f"round {round_index} clients did not receive an identical bounded global input",
        )
        for site_name in _SITE_NAMES:
            _require(
                _same_probe_metadata(first_input, outputs[site_name][round_index]),
                f"{site_name} round {round_index} output changed schema or bounded sample coordinates",
            )
        if reference_coordinates is None:
            reference_coordinates = first_input.coordinates
            reference_schema = first_input.schema_sha256
        else:
            _require(
                first_input.coordinates == reference_coordinates and first_input.schema_sha256 == reference_schema,
                f"round {round_index} changed the bounded sample coordinate set or schema",
            )

        divergent = sum(
            outputs["site-1"][round_index].values[coordinate] != outputs["site-2"][round_index].values[coordinate]
            for coordinate in first_input.coordinates
        )
        round_reports.append(
            {
                "current_round": round_index,
                "common_client_input": True,
                "bounded_sample_count": len(first_input.values),
                "unique_bounded_sample_coordinates": len(first_input.values),
                "bounded_sample_limit": expected_tensor_count * samples_per_tensor_bound,
                "client_output_divergence": ("OBSERVED" if divergent else "NOT_OBSERVED_IN_BOUNDED_SAMPLES"),
                "divergent_output_sample_count": divergent,
            }
        )
    return inputs, outputs, round_reports


def _validate_continuity(
    inputs: dict[str, list[_Probe]],
    outputs: dict[str, list[_Probe]],
    *,
    expected_rounds: int,
    absolute_tolerance: float,
    relative_tolerance: float,
    bf16_ulp_tolerance: float,
) -> list[dict[str, Any]]:
    reports = []
    for round_index in range(expected_rounds - 1):
        actual_probe = inputs["site-1"][round_index + 1]
        first_output = outputs["site-1"][round_index]
        second_output = outputs["site-2"][round_index]
        _require(
            _same_probe_metadata(actual_probe, first_output) and _same_probe_metadata(actual_probe, second_output),
            f"round {round_index} output and round {round_index + 1} input probes are not comparable",
        )
        mismatch_count = 0
        max_abs_error = 0.0
        max_allowed_error = 0.0
        worst = None
        for coordinate in sorted(actual_probe.coordinates):
            left = first_output.values[coordinate]
            right = second_output.values[coordinate]
            actual = actual_probe.values[coordinate]
            expected = _bf16_round((left + right) / 2.0)
            allowed = absolute_tolerance + relative_tolerance * abs(expected) + bf16_ulp_tolerance * _bf16_ulp(expected)
            error = abs(actual - expected)
            max_allowed_error = max(max_allowed_error, allowed)
            if error > max_abs_error:
                max_abs_error = error
                worst = {
                    "key": coordinate[0],
                    "index": coordinate[1],
                    "client_values": [left, right],
                    "expected_bf16_mean": expected,
                    "actual_next_input": actual,
                    "absolute_error": error,
                    "allowed_error": allowed,
                }
            if error > allowed:
                mismatch_count += 1
        _require(
            mismatch_count == 0,
            f"round {round_index}->{round_index + 1} has {mismatch_count} bounded samples outside "
            f"equal-weight BF16 FedAvg tolerance; worst={worst!r}",
        )
        reports.append(
            {
                "from_round": round_index,
                "to_round": round_index + 1,
                "status": "PASS",
                "checked_sample_count": len(actual_probe.values),
                "mismatch_count": mismatch_count,
                "max_absolute_error": max_abs_error,
                "max_allowed_error": max_allowed_error,
                "worst_sample": worst,
            }
        )
    return reports


def _validate_server_lifecycle(phase_root: Path, *, expected_rounds: int) -> dict[str, Any]:
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in _log_files(phase_root / "logs" / "localhost")
    )
    markers = {
        "aggregation_events": "Aggregated 2/2 results",
        "persistence_start_events": "Start persist model on server.",
        "persistence_end_events": "End persist model on server.",
    }
    counts = {name: text.count(marker) for name, marker in markers.items()}
    for name, count in counts.items():
        _require(count == expected_rounds, f"server has {count} {name}, expected exactly {expected_rounds}")
    return {"status": "PASS", **counts}


def _validate_persistence(
    phase_root: Path,
    *,
    expected_rounds: int,
    minimum_size_bytes: int,
) -> dict[str, Any]:
    persistence_root = phase_root / "persistence"
    _require(persistence_root.is_dir(), f"persistence metadata directory does not exist: {persistence_root}")
    paths = sorted(persistence_root.glob("persisted_model-*.json"))
    _require(
        len(paths) == expected_rounds,
        f"found {len(paths)} persisted-model metadata files, expected exactly {expected_rounds}",
    )
    records = [_read_json(path, context="persisted-model metadata") for path in paths]
    by_sequence = {}
    for path, record in zip(paths, records):
        sequence = record.get("sequence")
        size_bytes = record.get("size_bytes")
        _require(
            type(sequence) is int and 0 <= sequence < expected_rounds and sequence not in by_sequence,
            f"{path} has invalid or duplicate sequence={sequence!r}",
        )
        _require(
            type(size_bytes) is int and size_bytes >= minimum_size_bytes,
            f"persisted checkpoint sequence {sequence} size={size_bytes!r}, below {minimum_size_bytes}",
        )
        by_sequence[sequence] = record
    _require(
        set(by_sequence) == set(range(expected_rounds)),
        f"persisted checkpoint sequences are incomplete: {sorted(by_sequence)}",
    )
    ordered = [by_sequence[index] for index in range(expected_rounds)]
    return {
        "status": "PASS",
        "persistence_observation_count": expected_rounds,
        "checkpoint_sizes_bytes": [record["size_bytes"] for record in ordered],
        "distinct_recorded_checkpoint_paths": len(
            {record.get("path") for record in ordered if isinstance(record.get("path"), str)}
        ),
        "minimum_checkpoint_size_bytes": minimum_size_bytes,
        "validation_scope": "SIZE_ONLY",
        "checkpoint_content_loaded": False,
        "full_checkpoint_values_validated": False,
        "limitation": (
            "The retained artifact contains checkpoint metadata, not checkpoint tensors. "
            "This proves that five persistence observations recorded a full-checkpoint path meeting the size floor; "
            "it does not validate checkpoint tensor contents or reloadability."
        ),
    }


def analyze_artifact(
    artifact_root: Path,
    *,
    expected_rounds: int = 5,
    local_steps: int = 2,
    nproc_per_client: int = 4,
    expected_tensor_count: int = 579,
    expected_payload_bytes: int = 29_540_067_328,
    samples_per_tensor_bound: int = 4,
    minimum_persisted_size_bytes: int = 29_540_067_328,
    absolute_tolerance: float = 0.0,
    relative_tolerance: float = 1.0e-6,
    bf16_ulp_tolerance: float = 0.5,
) -> dict[str, Any]:
    """Validate the retained five-round artifact without loading model tensors."""

    artifact_root = artifact_root.resolve()
    for name, value in (
        ("expected_rounds", expected_rounds),
        ("local_steps", local_steps),
        ("nproc_per_client", nproc_per_client),
        ("expected_tensor_count", expected_tensor_count),
        ("expected_payload_bytes", expected_payload_bytes),
        ("samples_per_tensor_bound", samples_per_tensor_bound),
        ("minimum_persisted_size_bytes", minimum_persisted_size_bytes),
    ):
        _require(type(value) is int and value > 0, f"{name} must be a positive integer")
    for name, value in (
        ("absolute_tolerance", absolute_tolerance),
        ("relative_tolerance", relative_tolerance),
        ("bf16_ulp_tolerance", bf16_ulp_tolerance),
    ):
        _require(math.isfinite(value) and value >= 0, f"{name} must be finite and non-negative")

    _require(artifact_root.is_dir(), f"artifact root does not exist: {artifact_root}")
    manifest = _read_manifest(artifact_root / "manifest.txt")
    _require(manifest.get("status") == "0", f"manifest status is {manifest.get('status')!r}, expected '0'")
    _require(
        manifest.get("qualification_profile") == "full-model-14b-multiround",
        f"unexpected qualification profile {manifest.get('qualification_profile')!r}",
    )
    _require(manifest.get("num_rounds") == str(expected_rounds), "manifest round count does not match")
    _require(manifest.get("local_steps") == str(local_steps), "manifest local-step count does not match")
    _require(manifest.get("nproc_per_client") == str(nproc_per_client), "manifest process count does not match")

    qualification = _read_json(artifact_root / "qualification.json", context="qualification result")
    _require(qualification.get("status") == "PASS", "qualification result is not PASS")
    _require(
        qualification.get("profile") == "full-model-14b-multiround",
        f"qualification has unexpected profile={qualification.get('profile')!r}",
    )

    phase_root = artifact_root / _PHASE_NAME
    configuration = _read_json(phase_root / "configuration.json", context="phase configuration")
    summary = _read_json(phase_root / "summary.json", context="phase summary")
    model_path = configuration.get("model_path")
    _require(isinstance(model_path, str) and model_path, "phase configuration has no model_path")
    expected_configuration = {
        "num_clients": 2,
        "nproc_per_client": nproc_per_client,
        "num_rounds": expected_rounds,
        "local_steps": local_steps,
        "state_scope": "full",
        "trainable_target": "all",
        "expected_payload_bytes": expected_payload_bytes,
        "expected_tensor_count": expected_tensor_count,
    }
    for key, expected in expected_configuration.items():
        _require(
            configuration.get(key) == expected,
            f"phase configuration {key}={configuration.get(key)!r}, expected {expected!r}",
        )
    _require(summary.get("status") == "PASS", "phase summary is not PASS")
    _require(summary.get("job_status") == "FINISHED:COMPLETED", "NVFLARE job did not finish COMPLETED")

    records = _round_records(
        phase_root,
        model_path=model_path,
        expected_rounds=expected_rounds,
    )
    sample_ids = _validate_sample_ids(
        records,
        expected_rounds=expected_rounds,
        local_steps=local_steps,
        nproc_per_client=nproc_per_client,
    )
    inputs, outputs, round_reports = _parse_round_probes(
        records,
        expected_rounds=expected_rounds,
        expected_tensor_count=expected_tensor_count,
        expected_payload_bytes=expected_payload_bytes,
        samples_per_tensor_bound=samples_per_tensor_bound,
    )
    continuity = _validate_continuity(
        inputs,
        outputs,
        expected_rounds=expected_rounds,
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
        bf16_ulp_tolerance=bf16_ulp_tolerance,
    )
    lifecycle = _validate_server_lifecycle(phase_root, expected_rounds=expected_rounds)
    persistence = _validate_persistence(
        phase_root,
        expected_rounds=expected_rounds,
        minimum_size_bytes=minimum_persisted_size_bytes,
    )
    divergence_rounds = sum(report["client_output_divergence"] == "OBSERVED" for report in round_reports)
    return {
        "event": "real_training_multiround_post_run_analysis",
        "status": "PASS",
        "artifact_root": str(artifact_root),
        "source_job_id": manifest.get("job_id"),
        "source_git_commit": manifest.get("git_commit"),
        "profile": "full-model-14b-multiround",
        "num_clients": 2,
        "num_rounds": expected_rounds,
        "round_records_per_site": {site_name: len(records[site_name]) for site_name in _SITE_NAMES},
        "sample_ids": sample_ids,
        "state_probe_rounds": round_reports,
        "client_output_divergence": {
            "status": "OBSERVED" if divergence_rounds else "NOT_OBSERVED_IN_BOUNDED_SAMPLES",
            "rounds_observed": divergence_rounds,
            "rounds_checked": expected_rounds,
            "limitation": (
                "Divergence is assessed only at retained bounded coordinates; matching sampled values "
                "do not prove that complete client outputs were identical."
            ),
        },
        "fedavg_continuity": {
            "status": "PASS",
            "formula": "next_input = bfloat16_round((site_1_output + site_2_output) / 2)",
            "transitions_checked": len(continuity),
            "tolerances": {
                "absolute": absolute_tolerance,
                "relative": relative_tolerance,
                "bf16_ulp_multiplier": bf16_ulp_tolerance,
                "acceptance": "abs(actual-expected) <= absolute + relative*abs(expected) + multiplier*bf16_ulp(expected)",
            },
            "transitions": continuity,
        },
        "server_lifecycle": lifecycle,
        "persistence": persistence,
        "claims": {
            "validated": [
                "exactly five unique round records per client",
                "unique non-overlapping dataset sample IDs across all five rounds",
                "stable unique bounded full-state coordinates",
                "common client input at every retained bounded coordinate",
                "equal-weight BF16 FedAvg continuity across four round transitions",
                "exactly five aggregation and five persistence start/end events",
                "five persisted full-checkpoint size observations at or above the payload floor",
            ],
            "not_validated": [
                "unsampled full-state tensor values",
                "persisted full-checkpoint tensor contents",
                "persisted full-checkpoint reloadability",
            ],
        },
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _define_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--expected-rounds", type=int, default=5)
    parser.add_argument("--local-steps", type=int, default=2)
    parser.add_argument("--nproc-per-client", type=int, default=4)
    parser.add_argument("--expected-tensor-count", type=int, default=579)
    parser.add_argument("--expected-payload-bytes", type=int, default=29_540_067_328)
    parser.add_argument("--samples-per-tensor-bound", type=int, default=4)
    parser.add_argument("--minimum-persisted-size-bytes", type=int, default=29_540_067_328)
    parser.add_argument("--absolute-tolerance", type=float, default=0.0)
    parser.add_argument("--relative-tolerance", type=float, default=1.0e-6)
    parser.add_argument("--bf16-ulp-tolerance", type=float, default=0.5)
    return parser


def main() -> int:
    args = _define_parser().parse_args()
    try:
        result = analyze_artifact(
            args.artifact_root,
            expected_rounds=args.expected_rounds,
            local_steps=args.local_steps,
            nproc_per_client=args.nproc_per_client,
            expected_tensor_count=args.expected_tensor_count,
            expected_payload_bytes=args.expected_payload_bytes,
            samples_per_tensor_bound=args.samples_per_tensor_bound,
            minimum_persisted_size_bytes=args.minimum_persisted_size_bytes,
            absolute_tolerance=args.absolute_tolerance,
            relative_tolerance=args.relative_tolerance,
            bf16_ulp_tolerance=args.bf16_ulp_tolerance,
        )
    except (AnalysisError, OSError) as exc:
        result = {
            "event": "real_training_multiround_post_run_analysis",
            "status": "FAIL",
            "artifact_root": str(args.artifact_root.resolve()),
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        if args.output:
            _write_json(args.output, result)
        print(json.dumps(result, sort_keys=True), file=sys.stderr, flush=True)
        return 1
    if args.output:
        _write_json(args.output, result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
