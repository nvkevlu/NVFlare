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

"""Analyze retained real-training telemetry without GPUs, Slurm, Torch, or NVFLARE.

The analyzer deliberately reports sampled statistics.  The NVIDIA SMI source
uses a nominal five-second cadence but does not retain a timezone, so the
result must not be presented as a continuous, time-weighted utilization
measurement or aligned with the Unix-clock allocation samples.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

_GPU_CSV_FIELDS = (
    "timestamp",
    "index",
    "uuid",
    "name",
    "memory.used [MiB]",
    "utilization.gpu [%]",
)
_ALLOCATION_FIELDS = (
    "timestamp_unix",
    "cgroup_memory_current_bytes",
    "cgroup_memory_peak_bytes",
    "cgroup_memory_events",
    "process_tree_rss_bytes",
    "process_tree_pss_bytes",
    "system_available_bytes",
    "scratch_free_bytes",
)
_FATAL_CGROUP_EVENTS = ("max", "oom", "oom_kill")
_HIGH_UTILIZATION_PERCENT = 80
_GPU_SNAPSHOT_TOLERANCE_SECONDS = 1.0
_MIB = 1024 * 1024


class _TelemetryIntegrityError(ValueError):
    """A structurally parseable value that cannot be valid telemetry."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source(path: Path, **counts: Any) -> dict[str, Any]:
    return {
        "path": path.name,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
        **counts,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _parse_manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"{path.name}:{line_number} is not key=value")
        key, value = line.split("=", maxsplit=1)
        if not key or key in result:
            raise ValueError(f"{path.name}:{line_number} has an empty or duplicate key")
        result[key] = value
    return result


def _validate_qualification_outcome(status: Any, errors: list[str]) -> None:
    """Fail closed when a retained qualification explicitly is not successful."""

    if status is None:
        return
    if not isinstance(status, str) or status.strip().upper() != "PASS":
        errors.append(f"qualification.json reports non-success status {status!r}")


def _validate_manifest_outcome(manifest: Mapping[str, str], errors: list[str]) -> None:
    """Treat the wrapper's explicit failure signals as authoritative."""

    status = manifest.get("status")
    if status is not None and status.strip().upper() not in ("PASS", "0"):
        errors.append(f"manifest.txt reports non-success status {status!r}")

    exit_code = manifest.get("exit_code")
    if exit_code is None:
        return
    try:
        parsed_exit_code = int(exit_code)
    except ValueError:
        errors.append(f"manifest.txt exit_code is not an integer: {exit_code!r}")
    else:
        if parsed_exit_code != 0:
            errors.append(f"manifest.txt reports nonzero exit_code {parsed_exit_code}")


def _strict_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be a non-negative integer")
    if value < 0:
        raise _TelemetryIntegrityError(f"{label} must be non-negative, got {value}")
    return value


def _strict_optional_nonnegative_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _strict_nonnegative_int(value, label)


def _parse_unit_integer(value: Any, label: str, unit: str, *, maximum: int | None = None) -> int:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    stripped = value.strip()
    if stripped.startswith("-"):
        raise _TelemetryIntegrityError(f"{label} must be non-negative, got {stripped!r}")
    match = re.fullmatch(rf"([0-9]+)(?:\s*{re.escape(unit)})?", stripped)
    if not match:
        raise ValueError(f"{label} is not an integer measurement: {value!r}")
    result = int(match.group(1))
    if maximum is not None and result > maximum:
        raise _TelemetryIntegrityError(f"{label} exceeds {maximum}: {result}")
    return result


def _parse_gpu_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be text")
    stripped = value.strip()
    for form in ("%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(stripped, form)
        except ValueError:
            pass
    raise ValueError(f"unsupported nvidia-smi timestamp: {value!r}")


def _timestamp_text(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds" if value.microsecond else "seconds")


def _mean(values: Sequence[int | float]) -> float | None:
    return statistics.fmean(values) if values else None


def _quantile(values: Sequence[int | float], probability: float) -> float | None:
    """Return a deterministic type-7 linear-interpolation quantile."""

    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _metric_statistics(
    samples: Sequence[tuple[float, int]],
) -> dict[str, int | float | None]:
    if not samples:
        return {
            "sample_count": 0,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "p50": None,
            "p95": None,
            "minimum_timestamp_unix": None,
            "maximum_timestamp_unix": None,
        }
    values = [value for _, value in samples]
    minimum = min(values)
    maximum = max(values)
    return {
        "sample_count": len(values),
        "minimum": minimum,
        "maximum": maximum,
        "mean": _mean(values),
        "p50": _quantile(values, 0.50),
        "p95": _quantile(values, 0.95),
        "minimum_timestamp_unix": next(timestamp for timestamp, value in samples if value == minimum),
        "maximum_timestamp_unix": next(timestamp for timestamp, value in samples if value == maximum),
    }


def _fraction(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _parse_expected_gpu_indices(configuration: Mapping[str, Any]) -> list[int]:
    mapping = configuration.get("gpu_mapping")
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("configuration.json gpu_mapping must be a non-empty object")
    indices: set[int] = set()
    for site, values in mapping.items():
        if not isinstance(site, str) or not isinstance(values, list) or not values:
            raise ValueError("configuration.json gpu_mapping values must be non-empty arrays")
        for offset, value in enumerate(values):
            indices.add(_strict_nonnegative_int(value, f"gpu_mapping.{site}[{offset}]"))
    return sorted(indices)


def _parse_gpu_samples(
    path: Path,
    expected_indices: Sequence[int],
    *,
    warnings: list[str],
    errors: list[str],
    partial_reasons: list[str],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw_rows = 0
    rejected_rows = 0
    duplicate_rows = 0
    samples: list[dict[str, Any]] = []
    monitor_rows: list[tuple[int, int, int]] = []
    identities: dict[int, tuple[str, str]] = {}
    seen: dict[tuple[datetime, int], tuple[str, str, int, int]] = {}
    previous_timestamp: datetime | None = None

    with path.open(encoding="utf-8", errors="replace", newline="") as stream:
        reader = csv.DictReader(stream, skipinitialspace=True)
        actual_fields = tuple(field.strip() for field in (reader.fieldnames or ()))
        if actual_fields != _GPU_CSV_FIELDS:
            errors.append(f"gpu-samples.csv header mismatch: expected {_GPU_CSV_FIELDS}, observed {actual_fields}")
        for line_number, record in enumerate(reader, start=2):
            raw_rows += 1
            try:
                index_for_monitor = int((record.get("index") or "").strip())
                utilization_for_monitor = int((record.get("utilization.gpu [%]") or "").split()[0])
                memory_for_monitor = int((record.get("memory.used [MiB]") or "").split()[0])
                monitor_rows.append((index_for_monitor, utilization_for_monitor, memory_for_monitor))
            except (TypeError, ValueError):
                pass
            try:
                timestamp = _parse_gpu_timestamp(record.get("timestamp"))
                index = int((record.get("index") or "").strip())
                if index < 0:
                    raise _TelemetryIntegrityError("index must be non-negative")
                uuid = (record.get("uuid") or "").strip()
                name = (record.get("name") or "").strip()
                if not uuid or not name:
                    raise ValueError("uuid and name must be non-empty")
                memory_mib = _parse_unit_integer(record.get("memory.used [MiB]"), "memory.used", "MiB")
                utilization = _parse_unit_integer(
                    record.get("utilization.gpu [%]"), "utilization.gpu", "%", maximum=100
                )
            except _TelemetryIntegrityError as exc:
                rejected_rows += 1
                errors.append(f"gpu-samples.csv:{line_number}: {exc}")
                continue
            except (TypeError, ValueError) as exc:
                rejected_rows += 1
                partial_reasons.append(f"gpu-samples.csv:{line_number} was rejected")
                warnings.append(f"gpu-samples.csv:{line_number}: {exc}")
                continue

            if previous_timestamp is not None and timestamp < previous_timestamp:
                errors.append(
                    f"gpu-samples.csv timestamps decrease at line {line_number}; the artifact may contain appended runs"
                )
            previous_timestamp = timestamp
            identity = (uuid, name)
            if index in identities and identities[index] != identity:
                errors.append(
                    f"GPU index {index} changed identity from {identities[index]!r} to {identity!r} at line {line_number}"
                )
            identities.setdefault(index, identity)
            key = (timestamp, index)
            measurement = (uuid, name, memory_mib, utilization)
            if key in seen:
                if seen[key] != measurement:
                    errors.append(f"conflicting duplicate GPU sample for index {index} at {_timestamp_text(timestamp)}")
                else:
                    duplicate_rows += 1
                    partial_reasons.append("gpu-samples.csv contains duplicate samples")
                    warnings.append(
                        f"duplicate GPU sample for index {index} at {_timestamp_text(timestamp)} was ignored"
                    )
                continue
            seen[key] = measurement
            samples.append(
                {
                    "timestamp": timestamp,
                    "index": index,
                    "uuid": uuid,
                    "name": name,
                    "memory_mib": memory_mib,
                    "utilization_percent": utilization,
                }
            )

    if not samples:
        errors.append("gpu-samples.csv contains no valid unique samples")

    expected = set(expected_indices)
    observed = {sample["index"] for sample in samples}
    if observed != expected:
        partial_reasons.append("observed GPU indices differ from configuration")
        errors.append(f"GPU index mismatch: expected {sorted(expected)}, observed {sorted(observed)}")

    by_gpu: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for sample in samples:
        by_gpu[sample["index"]].append(sample)

    per_gpu = []
    for index in sorted(by_gpu):
        gpu_samples = by_gpu[index]
        utilization = [sample["utilization_percent"] for sample in gpu_samples]
        memory = [sample["memory_mib"] for sample in gpu_samples]
        nonzero = sum(value > 0 and memory[offset] > 0 for offset, value in enumerate(utilization))
        high = sum(
            value >= _HIGH_UTILIZATION_PERCENT and memory[offset] > 0 for offset, value in enumerate(utilization)
        )
        uuid, name = identities[index]
        per_gpu.append(
            {
                "index": index,
                "uuid": uuid,
                "name": name,
                "sample_count": len(gpu_samples),
                "mean_sampled_utilization_percent": _mean(utilization),
                "p50_utilization_percent": _quantile(utilization, 0.50),
                "p95_utilization_percent": _quantile(utilization, 0.95),
                "peak_utilization_percent": max(utilization),
                "nonzero_utilization_sample_count": nonzero,
                "nonzero_utilization_sample_fraction": _fraction(nonzero, len(utilization)),
                "high_utilization_sample_count": high,
                "high_utilization_sample_fraction": _fraction(high, len(utilization)),
                "mean_sampled_memory_mib": _mean(memory),
                "p50_memory_mib": _quantile(memory, 0.50),
                "p95_memory_mib": _quantile(memory, 0.95),
                "peak_memory_mib": max(memory),
            }
        )

    # One nvidia-smi query can stamp the eight rows a few milliseconds apart.
    # Repeated indices or a gap larger than the tolerance delimit query cycles;
    # grouping on exact timestamp text would incorrectly produce eight partial
    # snapshots on drivers that timestamp each row independently.
    snapshots: list[tuple[datetime, dict[int, dict[str, Any]]]] = []
    snapshot_start: datetime | None = None
    snapshot: dict[int, dict[str, Any]] = {}
    for sample in samples:
        timestamp = sample["timestamp"]
        index = sample["index"]
        starts_next = snapshot and (
            index in snapshot
            or snapshot_start is None
            or (timestamp - snapshot_start).total_seconds() > _GPU_SNAPSHOT_TOLERANCE_SECONDS
        )
        if starts_next:
            snapshots.append((snapshot_start, snapshot))
            snapshot_start = None
            snapshot = {}
        if snapshot_start is None:
            snapshot_start = timestamp
        snapshot[index] = sample
    if snapshot:
        snapshots.append((snapshot_start, snapshot))

    snapshot_timestamps = [timestamp for timestamp, _snapshot in snapshots]
    intervals = [
        (later - earlier).total_seconds() for earlier, later in zip(snapshot_timestamps, snapshot_timestamps[1:])
    ]
    complete_snapshots = [snapshot for _timestamp, snapshot in snapshots if set(snapshot) == expected]
    if len(complete_snapshots) != len(snapshots):
        partial_reasons.append("one or more GPU snapshots are incomplete")
        warnings.append(f"only {len(complete_snapshots)}/{len(snapshots)} GPU snapshots contain every configured GPU")

    snapshot_mean_utilization = [
        statistics.fmean(snapshot[index]["utilization_percent"] for index in expected_indices)
        for snapshot in complete_snapshots
    ]
    active_counts = [
        sum(
            snapshot[index]["utilization_percent"] > 0 and snapshot[index]["memory_mib"] > 0
            for index in expected_indices
        )
        for snapshot in complete_snapshots
    ]
    concurrent_memory = [
        sum(snapshot[index]["memory_mib"] for index in expected_indices) for snapshot in complete_snapshots
    ]
    all_active = sum(count == len(expected_indices) for count in active_counts)

    analysis = {
        "timestamp_basis": "node-local-naive",
        "snapshot_grouping_tolerance_seconds": _GPU_SNAPSHOT_TOLERANCE_SECONDS,
        "expected_indices": list(expected_indices),
        "observed_indices": sorted(observed),
        "snapshot_count": len(snapshots),
        "complete_snapshot_count": len(complete_snapshots),
        "first_timestamp": _timestamp_text(samples[0]["timestamp"]) if samples else None,
        "last_timestamp": _timestamp_text(samples[-1]["timestamp"]) if samples else None,
        "observed_span_seconds": (
            (samples[-1]["timestamp"] - samples[0]["timestamp"]).total_seconds() if samples else 0.0
        ),
        "median_snapshot_interval_seconds": statistics.median(intervals) if intervals else None,
        "maximum_snapshot_interval_seconds": max(intervals) if intervals else None,
        "high_utilization_threshold_percent": _HIGH_UTILIZATION_PERCENT,
        "quantile_method": "linear_interpolation_type_7",
        "per_gpu": per_gpu,
        "fleet": {
            "calculation_scope": "complete_snapshots_only",
            "mean_sampled_utilization_percent": _mean(snapshot_mean_utilization),
            "p50_snapshot_mean_utilization_percent": _quantile(snapshot_mean_utilization, 0.50),
            "p95_snapshot_mean_utilization_percent": _quantile(snapshot_mean_utilization, 0.95),
            "mean_active_gpu_count": _mean(active_counts),
            "minimum_active_gpu_count": min(active_counts) if active_counts else None,
            "maximum_active_gpu_count": max(active_counts) if active_counts else None,
            "all_expected_gpus_active_snapshot_fraction": _fraction(all_active, len(active_counts)),
            "mean_concurrent_memory_mib": _mean(concurrent_memory),
            "peak_concurrent_memory_mib": max(concurrent_memory) if concurrent_memory else None,
        },
    }
    source = _source(
        path,
        raw_rows=raw_rows,
        valid_rows=len(samples),
        rejected_rows=rejected_rows,
        duplicate_rows=duplicate_rows,
    )

    monitor_counts: dict[int, int] = defaultdict(int)
    monitor_peak_utilization: dict[int, int] = defaultdict(int)
    monitor_peak_memory: dict[int, int] = defaultdict(int)
    for index, utilization, memory_mib in monitor_rows:
        monitor_counts[index] += 1
        monitor_peak_utilization[index] = max(monitor_peak_utilization[index], utilization)
        monitor_peak_memory[index] = max(monitor_peak_memory[index], memory_mib)
    monitor_projection = {
        "sample_lines": len(monitor_rows),
        "observed_gpu_indices": sorted(monitor_counts),
        "active_gpu_indices": sorted(
            index for index in monitor_counts if monitor_peak_utilization[index] > 0 and monitor_peak_memory[index] > 0
        ),
        "samples_per_gpu": {str(index): monitor_counts[index] for index in sorted(monitor_counts)},
        "peak_utilization_percent": {str(index): monitor_peak_utilization[index] for index in sorted(monitor_counts)},
        "peak_memory_mib": {str(index): monitor_peak_memory[index] for index in sorted(monitor_counts)},
    }
    return analysis, source, monitor_projection


def _parse_allocation_samples(
    path: Path,
    *,
    warnings: list[str],
    errors: list[str],
    partial_reasons: list[str],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    raw_lines = 0
    rejected_lines = 0
    samples: list[dict[str, Any]] = []
    previous_timestamp: float | None = None
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line_number, line in enumerate(stream, start=1):
            raw_lines += 1
            try:
                sample = json.loads(line)
                if not isinstance(sample, dict):
                    raise ValueError("sample must be a JSON object")
                missing = sorted(set(_ALLOCATION_FIELDS) - set(sample))
                if missing:
                    raise ValueError(f"missing fields: {missing}")
                timestamp = sample["timestamp_unix"]
                if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
                    raise ValueError("timestamp_unix must be finite numeric data")
                if not math.isfinite(timestamp):
                    raise _TelemetryIntegrityError("timestamp_unix must be finite numeric data")
                timestamp = float(timestamp)
                normalized = {
                    "timestamp_unix": timestamp,
                    "cgroup_memory_current_bytes": _strict_optional_nonnegative_int(
                        sample["cgroup_memory_current_bytes"], "cgroup_memory_current_bytes"
                    ),
                    "cgroup_memory_peak_bytes": _strict_optional_nonnegative_int(
                        sample["cgroup_memory_peak_bytes"], "cgroup_memory_peak_bytes"
                    ),
                    "process_tree_rss_bytes": _strict_nonnegative_int(
                        sample["process_tree_rss_bytes"], "process_tree_rss_bytes"
                    ),
                    "process_tree_pss_bytes": _strict_nonnegative_int(
                        sample["process_tree_pss_bytes"], "process_tree_pss_bytes"
                    ),
                    "system_available_bytes": _strict_nonnegative_int(
                        sample["system_available_bytes"], "system_available_bytes"
                    ),
                    "scratch_free_bytes": _strict_nonnegative_int(sample["scratch_free_bytes"], "scratch_free_bytes"),
                }
                events = sample["cgroup_memory_events"]
                if not isinstance(events, dict):
                    raise ValueError("cgroup_memory_events must be an object")
                normalized["cgroup_memory_events"] = {
                    key: _strict_nonnegative_int(value, f"cgroup_memory_events.{key}")
                    for key, value in events.items()
                    if isinstance(key, str) and key
                }
                if len(normalized["cgroup_memory_events"]) != len(events):
                    raise ValueError("cgroup_memory_events keys must be non-empty strings")
                if previous_timestamp is not None and timestamp <= previous_timestamp:
                    errors.append(
                        f"allocation-memory.jsonl timestamps are not strictly increasing at line {line_number}; "
                        "the artifact may contain appended runs"
                    )
                previous_timestamp = timestamp
                samples.append(normalized)
            except _TelemetryIntegrityError as exc:
                rejected_lines += 1
                errors.append(f"allocation-memory.jsonl:{line_number}: {exc}")
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                rejected_lines += 1
                partial_reasons.append(f"allocation-memory.jsonl:{line_number} was rejected")
                warnings.append(f"allocation-memory.jsonl:{line_number}: {exc}")

    if not samples:
        errors.append("allocation-memory.jsonl contains no valid samples")
    timestamps = [sample["timestamp_unix"] for sample in samples]
    intervals = [later - earlier for earlier, later in zip(timestamps, timestamps[1:])]
    metrics = {
        field: _metric_statistics([(sample["timestamp_unix"], sample[field]) for sample in samples])
        for field in (
            "process_tree_rss_bytes",
            "process_tree_pss_bytes",
            "system_available_bytes",
            "scratch_free_bytes",
        )
    }
    analysis = {
        "timestamp_basis": "unix",
        "sample_count": len(samples),
        "first_timestamp_unix": timestamps[0] if timestamps else None,
        "last_timestamp_unix": timestamps[-1] if timestamps else None,
        "observed_span_seconds": timestamps[-1] - timestamps[0] if timestamps else 0.0,
        "median_interval_seconds": statistics.median(intervals) if intervals else None,
        "maximum_interval_seconds": max(intervals) if intervals else None,
        "quantile_method": "linear_interpolation_type_7",
        "metrics": metrics,
    }
    source = _source(path, raw_lines=raw_lines, valid_samples=len(samples), rejected_lines=rejected_lines)
    return analysis, source, samples


def _mapping_of_nonnegative_ints(value: Any, label: str) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return {key: _strict_nonnegative_int(item, f"{label}.{key}") for key, item in value.items() if isinstance(key, str)}


def _add_consistency_check(checks: list[dict[str, Any]], errors: list[str], name: str, raw: Any, summary: Any) -> None:
    status = "PASS" if raw == summary else "FAIL"
    checks.append({"name": name, "status": status, "raw": raw, "summary": summary})
    if status == "FAIL":
        errors.append(f"summary reconciliation failed for {name}: raw={raw!r}, summary={summary!r}")


def _reconcile_gpu_summary(
    summary: Mapping[str, Any],
    projection: Mapping[str, Any],
    source: Mapping[str, Any],
    checks: list[dict[str, Any]],
    errors: list[str],
) -> None:
    _add_consistency_check(checks, errors, "gpu.event", "real_training_gpu_monitor", summary.get("event"))
    _add_consistency_check(checks, errors, "gpu.status", "PASS", summary.get("status"))
    _add_consistency_check(
        checks, errors, "gpu.output_size_bytes", source["size_bytes"], summary.get("output_size_bytes")
    )
    for name, raw in projection.items():
        _add_consistency_check(checks, errors, f"gpu.{name}", raw, summary.get(name))
    _add_consistency_check(
        checks, errors, "gpu.return_code_before_shutdown", None, summary.get("return_code_before_shutdown")
    )


def _reconcile_allocation_summary(
    summary: Mapping[str, Any],
    samples: Sequence[Mapping[str, Any]],
    checks: list[dict[str, Any]],
    errors: list[str],
) -> tuple[dict[str, Any], bool]:
    _add_consistency_check(checks, errors, "allocation.event", "real_training_allocation_monitor", summary.get("event"))
    _add_consistency_check(checks, errors, "allocation.status", "PASS", summary.get("status"))
    _add_consistency_check(checks, errors, "allocation.error", None, summary.get("error"))
    _add_consistency_check(checks, errors, "allocation.sample_count", len(samples), summary.get("sample_count"))
    calculations = {
        "peak_cgroup_memory_current_bytes": max(
            ((sample["cgroup_memory_current_bytes"] or 0) for sample in samples), default=0
        ),
        "peak_cgroup_memory_bytes": max(((sample["cgroup_memory_peak_bytes"] or 0) for sample in samples), default=0),
        "peak_process_tree_rss_bytes": max((sample["process_tree_rss_bytes"] for sample in samples), default=0),
        "peak_process_tree_pss_bytes": max((sample["process_tree_pss_bytes"] for sample in samples), default=0),
        "minimum_system_available_bytes": min((sample["system_available_bytes"] for sample in samples), default=0),
        "minimum_scratch_free_bytes": min((sample["scratch_free_bytes"] for sample in samples), default=0),
    }
    for name, raw in calculations.items():
        _add_consistency_check(checks, errors, f"allocation.{name}", raw, summary.get(name))

    cgroup_available = summary.get("allocation_wide_cgroup_metrics_available") is True
    expected_scope = "allocation-cgroup-plus-process-tree" if cgroup_available else "process-tree-plus-system"
    _add_consistency_check(checks, errors, "allocation.telemetry_scope", expected_scope, summary.get("telemetry_scope"))
    if cgroup_available:
        if not samples or any(sample["cgroup_memory_current_bytes"] is None for sample in samples):
            errors.append("allocation summary claims cgroup availability but raw current-memory samples are missing")
    elif any(
        sample["cgroup_memory_current_bytes"] is not None
        or sample["cgroup_memory_peak_bytes"] is not None
        or sample["cgroup_memory_events"]
        for sample in samples
    ):
        errors.append("allocation summary claims no cgroup availability but raw cgroup samples are present")

    try:
        event_deltas = _mapping_of_nonnegative_ints(
            summary.get("cgroup_memory_event_deltas"), "cgroup_memory_event_deltas"
        )
        fatal_deltas = _mapping_of_nonnegative_ints(
            summary.get("fatal_cgroup_event_deltas"), "fatal_cgroup_event_deltas"
        )
    except ValueError as exc:
        errors.append(str(exc))
        event_deltas = {}
        fatal_deltas = {}
    expected_fatal = {key: event_deltas.get(key, 0) for key in _FATAL_CGROUP_EVENTS}
    _add_consistency_check(
        checks,
        errors,
        "allocation.fatal_cgroup_event_deltas",
        expected_fatal,
        fatal_deltas,
    )
    if cgroup_available and any(fatal_deltas.values()):
        errors.append(f"fatal cgroup memory event deltas were observed: {fatal_deltas}")
    return {
        "available": cgroup_available,
        "path": summary.get("cgroup_path") if cgroup_available else None,
        "memory_current_bytes": (
            _metric_statistics(
                [
                    (sample["timestamp_unix"], sample["cgroup_memory_current_bytes"])
                    for sample in samples
                    if sample["cgroup_memory_current_bytes"] is not None
                ]
            )
            if cgroup_available
            else None
        ),
        "memory_peak_bytes": (
            _metric_statistics(
                [
                    (sample["timestamp_unix"], sample["cgroup_memory_peak_bytes"])
                    for sample in samples
                    if sample["cgroup_memory_peak_bytes"] is not None
                ]
            )
            if cgroup_available and any(sample["cgroup_memory_peak_bytes"] is not None for sample in samples)
            else None
        ),
        # The monitor's pre-sample event baseline is not retained in JSONL, so
        # these validated summary deltas are authoritative rather than recomputed.
        "event_deltas": event_deltas if cgroup_available else None,
        "fatal_event_deltas": fatal_deltas if cgroup_available else None,
        "event_observation_supported": cgroup_available,
    }, cgroup_available


def analyze_artifact(artifact_root: str | Path) -> dict[str, Any]:
    """Return a deterministic analysis of one retained qualification artifact."""

    root = Path(artifact_root).resolve()
    warnings: list[str] = []
    errors: list[str] = []
    partial_reasons: list[str] = []
    checks: list[dict[str, Any]] = []
    sources: dict[str, Any] = {}

    required = {
        "gpu_samples": root / "gpu-samples.csv",
        "allocation_samples": root / "allocation-memory.jsonl",
        "gpu_monitor": root / "gpu-monitor.json",
        "allocation_monitor": root / "allocation-monitor.json",
        "configuration": root / "configuration.json",
    }
    missing = [path.name for path in required.values() if not path.is_file()]
    if missing:
        return {
            "event": "real_training_offline_telemetry_analysis",
            "schema_version": 1,
            "status": "FAIL",
            "artifact_root": str(root),
            "qualification_status": None,
            "sources": {},
            "gpu": None,
            "allocation": None,
            "allocation_request": None,
            "consistency_checks": [],
            "claims": {
                "sampled_gpu_average_supported": False,
                "continuous_time_average_supported": False,
                "allocation_wide_memory_supported": False,
                "cgroup_oom_observation_supported": False,
                "server_only_memory_supported": False,
                "phase_attribution_supported": False,
            },
            "warnings": [],
            "errors": [f"missing required artifact files: {sorted(missing)}"],
        }

    configuration = _read_json(required["configuration"])
    gpu_summary = _read_json(required["gpu_monitor"])
    allocation_summary = _read_json(required["allocation_monitor"])
    sources["configuration"] = _source(required["configuration"])
    sources["gpu_monitor"] = _source(required["gpu_monitor"])
    sources["allocation_monitor"] = _source(required["allocation_monitor"])
    try:
        expected_indices = _parse_expected_gpu_indices(configuration)
    except ValueError as exc:
        errors.append(str(exc))
        expected_indices = sorted(
            value for value in gpu_summary.get("observed_gpu_indices", []) if isinstance(value, int) and value >= 0
        )
        partial_reasons.append("expected GPU indices were inferred from gpu-monitor.json")

    gpu, gpu_source, projection = _parse_gpu_samples(
        required["gpu_samples"],
        expected_indices,
        warnings=warnings,
        errors=errors,
        partial_reasons=partial_reasons,
    )
    sources["gpu_samples"] = gpu_source
    _reconcile_gpu_summary(gpu_summary, projection, gpu_source, checks, errors)

    allocation, allocation_source, allocation_samples = _parse_allocation_samples(
        required["allocation_samples"],
        warnings=warnings,
        errors=errors,
        partial_reasons=partial_reasons,
    )
    sources["allocation_samples"] = allocation_source
    cgroup, cgroup_available = _reconcile_allocation_summary(allocation_summary, allocation_samples, checks, errors)
    allocation["telemetry_scope"] = allocation_summary.get("telemetry_scope")
    allocation["cgroup"] = cgroup
    if not cgroup_available:
        warnings.append(
            "allocation-wide cgroup metrics were unavailable; zero-valued summary placeholders are not OOM evidence"
        )
    else:
        warnings.append(
            "cgroup event deltas use the monitor summary because the pre-sample event baseline is not retained in JSONL"
        )

    qualification_path = root / "qualification.json"
    qualification_status = None
    if qualification_path.is_file():
        qualification = _read_json(qualification_path)
        qualification_status = qualification.get("status")
        sources["qualification"] = _source(qualification_path)
        _validate_qualification_outcome(qualification_status, errors)
    else:
        warnings.append("qualification.json is absent; workload qualification status is unknown")

    allocation_request: dict[str, Any] | None = None
    manifest_path = root / "manifest.txt"
    if manifest_path.is_file():
        sources["manifest"] = _source(manifest_path)
        try:
            manifest = _parse_manifest(manifest_path)
            _validate_manifest_outcome(manifest, errors)
            memory_text = manifest.get("slurm_mem_per_node_mib")
            gpu_text = manifest.get("slurm_gpus_on_node")
            memory_mib = int(memory_text) if memory_text is not None and memory_text.isdigit() else None
            gpu_count = int(gpu_text) if gpu_text is not None and gpu_text.isdigit() else None
            peak_rss = allocation["metrics"]["process_tree_rss_bytes"]["maximum"]
            allocation_request = {
                "memory_mib": memory_mib,
                "gpu_count": gpu_count,
                "process_tree_peak_nominal_headroom_bytes": (
                    memory_mib * _MIB - peak_rss if memory_mib is not None and peak_rss is not None else None
                ),
                "claim_scope": "nominal-process-tree-only",
            }
        except (TypeError, ValueError) as exc:
            partial_reasons.append("manifest.txt could not be interpreted")
            warnings.append(str(exc))
    else:
        warnings.append("manifest.txt is absent; nominal allocation headroom cannot be computed")

    status = "FAIL" if errors else "PARTIAL" if partial_reasons else "PASS"
    return {
        "event": "real_training_offline_telemetry_analysis",
        "schema_version": 1,
        "status": status,
        "artifact_root": str(root),
        "qualification_status": qualification_status,
        "sources": sources,
        "gpu": gpu,
        "allocation": allocation,
        "allocation_request": allocation_request,
        "consistency_checks": checks,
        "claims": {
            "sampled_gpu_average_supported": bool(gpu["complete_snapshot_count"]) and not errors,
            "continuous_time_average_supported": False,
            "allocation_wide_memory_supported": cgroup_available and not errors,
            "cgroup_oom_observation_supported": cgroup_available and not errors,
            "server_only_memory_supported": False,
            "phase_attribution_supported": False,
        },
        "warnings": list(dict.fromkeys(warnings)),
        "errors": list(dict.fromkeys(errors)),
    }


def _define_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="Optionally write the same JSON document to this path")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _define_parser().parse_args(argv)
    result = analyze_artifact(args.artifact_root)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] in ("PASS", "PARTIAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
