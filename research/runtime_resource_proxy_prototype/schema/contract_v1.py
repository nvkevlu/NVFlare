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

"""Executable validation for the final-only resource-statistics v1 contract.

Canonical quantities are strings. Integer quantities use base-10 unsigned
integers. Fractional quantities use non-exponent decimals with at most nine
fractional digits and no insignificant trailing zeroes.

A participant report contains one terminal resource-time total. The server
validates and copies that value; it does not recreate it from start/end
observations. Only job and transient study sums are derived here.
"""

from __future__ import annotations

import calendar
import json
import re
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal, InvalidOperation, localcontext
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "1.0"

KIND_PARTICIPANT_SUMMARY = "nvflare.resource_stats.participant_summary"
KIND_RESOURCE_SUMMARY = "nvflare.resource_stats.resource_summary"
KIND_STUDY_SUMMARY = "nvflare.resource_stats.study_summary"
RECORD_KINDS = frozenset(
    {
        KIND_PARTICIPANT_SUMMARY,
        KIND_RESOURCE_SUMMARY,
        KIND_STUDY_SUMMARY,
    }
)

ISSUE_CODES = frozenset(
    {
        "not_bound",
        "counter_gap",
        "observation_incomplete",
        "attribution_incomplete",
        "unsupported",
        "permission_denied",
        "dependency_missing",
        "malformed_source",
    }
)
RESOURCE_TIME_PARTIAL_ISSUES = frozenset({"attribution_incomplete", "observation_incomplete"})
RESOURCE_TIME_UNAVAILABLE_ISSUES = frozenset(
    {
        "attribution_incomplete",
        "dependency_missing",
        "malformed_source",
        "not_bound",
        "observation_incomplete",
        "permission_denied",
        "unsupported",
    }
)
SOURCE_UNAVAILABLE_ISSUES = frozenset(
    {"attribution_incomplete", "dependency_missing", "not_bound", "observation_incomplete", "unsupported"}
)
SOURCE_ERROR_ISSUES = frozenset({"malformed_source", "permission_denied"})
INVALID_REPORT_ISSUES = frozenset({"malformed_source"})
CAPACITY_UNAVAILABLE_ISSUES = SOURCE_UNAVAILABLE_ISSUES - {"not_bound"}
PARTIAL_ISSUES = frozenset({"attribution_incomplete", "counter_gap", "observation_incomplete"})

RESOURCE_TIME_STATUSES = frozenset({"reported", "partial", "unavailable"})
MEASUREMENT_STATUSES = frozenset({"reported", "partial", "unavailable", "error"})
TOTAL_STATUSES = frozenset({"reported", "partial", "unavailable"})
PARTICIPANT_STATUSES = frozenset({"accepted", "missing", "invalid", "disabled"})
ROLES = frozenset({"client", "server"})
GPU_KINDS = frozenset({"full_gpu", "mig_compute_instance"})
RESOURCE_DATA_STATES = frozenset({"included", "unavailable", "nonterminal"})
LEGACY_TERMINAL_JOB_STATES = frozenset({"FINISHED_OK", "FINISHED_EXCEPTION", "ABORTED", "ABANDONED", "FAILED"})

MAX_ISSUES = 4
MAX_PARTICIPANTS = 10_000
MAX_STUDY_JOBS = 10_000
MAX_GPU_GROUPS = 4_096
MAX_JSON_DEPTH = 32
MAX_RECORD_BYTES = {
    KIND_PARTICIPANT_SUMMARY: 1 * 1024 * 1024,
    KIND_RESOURCE_SUMMARY: 64 * 1024 * 1024,
    KIND_STUDY_SUMMARY: 64 * 1024 * 1024,
}

U32_MAX = 2**32 - 1
U64_MAX = 2**64 - 1
U128_MAX = 2**128 - 1
MAX_CPU_UNITS = Decimal("1048576")

INTEGER_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,38})$")
DECIMAL_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,38})(?:\.[0-9]{0,8}[1-9])?$")
TIMESTAMP_PATTERN = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,9}))?Z$")
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PARTICIPANT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}$")
MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+/@-]{0,127}$")
ARCHITECTURE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
MIG_PROFILE_PATTERN = re.compile(r"^[1-9][0-9]*g\.[1-9][0-9]*gb(?:\+me)?$")
STUDY_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?$")
JOB_STATUS_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/+-]{0,63}$")

_FORBIDDEN_MODEL_PATTERNS = (
    re.compile(r"(?:GPU|MIG|MIG-GPU)-[0-9A-Fa-f-]{16,}", re.IGNORECASE),
    re.compile(r"(?:[0-9A-Fa-f]{4}:)?[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}\.[0-7]"),
    re.compile(r"\b(?:serial|uuid|cuda_visible_devices|pci_bus_id|hostname)\b", re.IGNORECASE),
)
_FORBIDDEN_KEYS = frozenset(
    {
        "hostname",
        "host_id",
        "ip_address",
        "mac_address",
        "serial",
        "serial_number",
        "uuid",
        "gpu_uuid",
        "pci_bus_id",
        "bdf",
        "cuda_visible_devices",
        "raw_cpuinfo",
        "cpu_flags",
        "cpu_topology",
    }
)


class ContractError(ValueError):
    """Raised when a record violates the canonical v1 contract."""


def _fail(path: str, message: str) -> None:
    raise ContractError(f"{path}: {message}")


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(path, "must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], required: set[str], optional: set[str], path: str) -> None:
    keys = set(value)
    missing = required - keys
    extra = keys - required - optional
    if missing:
        _fail(path, f"missing required fields: {', '.join(sorted(missing))}")
    if extra:
        _fail(path, f"unexpected fields: {', '.join(sorted(extra))}")


def _enum(value: Any, allowed: frozenset[str] | set[str], path: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        _fail(path, f"must be one of {', '.join(sorted(allowed))}")
    return value


def _identifier(value: Any, pattern: re.Pattern[str], path: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        _fail(path, "has invalid syntax")
    return value


def _timestamp(value: Any, path: str) -> str:
    if not isinstance(value, str):
        _fail(path, "must be a UTC timestamp string")
    match = TIMESTAMP_PATTERN.fullmatch(value)
    if not match:
        _fail(path, "must be RFC 3339 UTC with at most nanosecond precision")
    try:
        datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        _fail(path, "is not a valid calendar timestamp")
    return value


def _timestamp_nanoseconds(value: str) -> int:
    match = TIMESTAMP_PATTERN.fullmatch(value)
    assert match
    parsed = datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
    fractional = (match.group(2) or "").ljust(9, "0")
    return calendar.timegm(parsed.timetuple()) * 1_000_000_000 + int(fractional or "0")


def _decimal(value: Any, path: str, *, maximum: int | Decimal = U128_MAX, positive: bool = False) -> Decimal:
    if not isinstance(value, str) or not DECIMAL_PATTERN.fullmatch(value):
        _fail(path, "must be a canonical non-negative decimal string with at most 9 fractional digits")
    try:
        number = Decimal(value)
    except InvalidOperation:
        _fail(path, "must be a decimal")
    if number > Decimal(maximum) or (positive and number <= 0):
        qualifier = "positive and " if positive else ""
        _fail(path, f"must be {qualifier}no greater than {maximum}")
    return number


def _integer(value: Any, path: str, *, maximum: int = U128_MAX, positive: bool = False) -> int:
    if not isinstance(value, str) or not INTEGER_PATTERN.fullmatch(value):
        _fail(path, "must be a canonical non-negative integer string")
    number = int(value)
    if number > maximum or (positive and number == 0):
        qualifier = "positive and " if positive else ""
        _fail(path, f"must be {qualifier}no greater than {maximum}")
    return number


def _model(value: Any, path: str) -> str:
    if not isinstance(value, str) or not MODEL_PATTERN.fullmatch(value):
        _fail(path, "must be a controlled hardware-model label of at most 128 ASCII characters")
    if any(pattern.search(value) for pattern in _FORBIDDEN_MODEL_PATTERNS):
        _fail(path, "must not contain a serial, UUID, PCI address, host identifier, or raw mask")
    return value


def _issues(value: Any, allowed: frozenset[str] | set[str], path: str) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_ISSUES:
        _fail(path, f"must contain 1..{MAX_ISSUES} issue codes")
    if any(not isinstance(item, str) for item in value):
        _fail(path, "must contain strings")
    if value != sorted(value) or len(value) != len(set(value)):
        _fail(path, "must be sorted and unique")
    unknown = set(value) - allowed
    if unknown:
        _fail(path, f"contains unsupported issues: {', '.join(sorted(unknown))}")
    return value


def _privacy_walk(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                _fail(path, "object keys must be strings")
            if key.lower() in _FORBIDDEN_KEYS:
                _fail(f"{path}.{key}", "field is forbidden by the v1 privacy policy")
            _privacy_walk(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _privacy_walk(nested, f"{path}[{index}]")


def _json_depth(value: Any) -> int:
    """Return enough depth information without using the Python call stack."""

    stack: list[tuple[Any, int]] = [(value, 1)]
    maximum = 0
    while stack:
        item, depth = stack.pop()
        maximum = max(maximum, depth)
        # Validation only needs to know that the fixed bound was exceeded.
        # Stopping here also makes cyclic already-decoded inputs terminate.
        if depth > MAX_JSON_DEPTH:
            return depth
        if isinstance(item, Mapping):
            stack.extend((nested, depth + 1) for nested in item.values())
        elif isinstance(item, list):
            stack.extend((nested, depth + 1) for nested in item)
    return maximum


def _validate_cpu_time_group(value: Any, path: str) -> None:
    group = _mapping(value, path)
    _exact_keys(group, {"unit_seconds"}, {"model", "architecture"}, path)
    _decimal(group["unit_seconds"], f"{path}.unit_seconds")
    if "model" in group:
        _model(group["model"], f"{path}.model")
    if "architecture" in group:
        _identifier(group["architecture"], ARCHITECTURE_PATTERN, f"{path}.architecture")


def _gpu_group_key(group: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        group["kind"],
        group.get("model", ""),
        group.get("memory_bytes", ""),
        group.get("mig_profile", ""),
    )


def _validate_gpu_time_group(value: Any, path: str) -> None:
    group = _mapping(value, path)
    _exact_keys(group, {"kind", "instance_seconds"}, {"model", "memory_bytes", "mig_profile"}, path)
    kind = _enum(group["kind"], GPU_KINDS, f"{path}.kind")
    _decimal(group["instance_seconds"], f"{path}.instance_seconds", positive=True)
    if "model" in group:
        _model(group["model"], f"{path}.model")
    if "memory_bytes" in group:
        _integer(group["memory_bytes"], f"{path}.memory_bytes", maximum=U64_MAX, positive=True)
    if "mig_profile" in group:
        _identifier(group["mig_profile"], MIG_PROFILE_PATTERN, f"{path}.mig_profile")
    if kind == "full_gpu" and "mig_profile" in group:
        _fail(f"{path}.mig_profile", "is valid only for a MIG compute-instance group")


def _validate_group_list(value: Any, path: str, *, gpu: bool) -> None:
    if not isinstance(value, list) or len(value) > MAX_GPU_GROUPS or (not gpu and not value):
        minimum = "1" if not gpu else "0"
        _fail(path, f"must contain {minimum}..{MAX_GPU_GROUPS} consolidated groups")
    keys: list[tuple[str, ...]] = []
    for index, group in enumerate(value):
        item_path = f"{path}[{index}]"
        if gpu:
            _validate_gpu_time_group(group, item_path)
            keys.append(_gpu_group_key(group))
        else:
            _validate_cpu_time_group(group, item_path)
            keys.append((group.get("model", ""), group.get("architecture", "")))
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        _fail(path, "groups must be consolidated, unique, and sorted by identifying fields")


def _validate_cpu_time(value: Any, path: str) -> None:
    cpu = _mapping(value, path)
    _exact_keys(cpu, {"groups"}, set(), path)
    _validate_group_list(cpu["groups"], f"{path}.groups", gpu=False)


def _validate_memory_time(value: Any, path: str) -> None:
    memory = _mapping(value, path)
    _exact_keys(memory, {"byte_seconds"}, set(), path)
    _decimal(memory["byte_seconds"], f"{path}.byte_seconds")


def _validate_gpu_time(value: Any, path: str) -> None:
    gpu = _mapping(value, path)
    _exact_keys(gpu, {"groups"}, set(), path)
    _validate_group_list(gpu["groups"], f"{path}.groups", gpu=True)


_RESOURCE_TIME_NUMERIC_FIELDS = frozenset({"measured_seconds", "cpu", "memory", "gpu"})


def _validate_resource_time(value: Any, path: str) -> None:
    resource_time = _mapping(value, path)
    status = _enum(resource_time.get("status"), RESOURCE_TIME_STATUSES, f"{path}.status")
    if status == "reported":
        _exact_keys(resource_time, {"status"} | set(_RESOURCE_TIME_NUMERIC_FIELDS), set(), path)
    elif status == "partial":
        _exact_keys(resource_time, {"status", "issues"}, set(_RESOURCE_TIME_NUMERIC_FIELDS), path)
        _issues(resource_time["issues"], RESOURCE_TIME_PARTIAL_ISSUES, f"{path}.issues")
        if not set(resource_time) & _RESOURCE_TIME_NUMERIC_FIELDS:
            _fail(path, "partial resource_time must contain at least one numeric member")
    else:
        _exact_keys(resource_time, {"status", "issues"}, set(), path)
        _issues(resource_time["issues"], RESOURCE_TIME_UNAVAILABLE_ISSUES, f"{path}.issues")

    if "measured_seconds" in resource_time:
        _decimal(resource_time["measured_seconds"], f"{path}.measured_seconds")
    if "cpu" in resource_time:
        _validate_cpu_time(resource_time["cpu"], f"{path}.cpu")
    if "memory" in resource_time:
        _validate_memory_time(resource_time["memory"], f"{path}.memory")
    if "gpu" in resource_time:
        _validate_gpu_time(resource_time["gpu"], f"{path}.gpu")


def _validate_workspace_filesystem(value: Any, path: str) -> None:
    workspace = _mapping(value, path)
    status = _enum(workspace.get("status"), frozenset({"reported", "unavailable", "error"}), f"{path}.status")
    if status == "reported":
        _exact_keys(workspace, {"status", "capacity_bytes"}, set(), path)
        _integer(workspace["capacity_bytes"], f"{path}.capacity_bytes", maximum=U64_MAX, positive=True)
    else:
        _exact_keys(workspace, {"status", "issues"}, set(), path)
        allowed = CAPACITY_UNAVAILABLE_ISSUES if status == "unavailable" else SOURCE_ERROR_ISSUES
        _issues(workspace["issues"], allowed, f"{path}.issues")


def _validate_retained_content(value: Any, path: str, *, aggregate: bool = False) -> None:
    retained = _mapping(value, path)
    statuses = TOTAL_STATUSES if aggregate else MEASUREMENT_STATUSES
    status = _enum(retained.get("status"), statuses, f"{path}.status")
    if status == "reported":
        _exact_keys(retained, {"status", "bytes"}, set(), path)
        _integer(retained["bytes"], f"{path}.bytes")
    elif status == "partial":
        if aggregate:
            _exact_keys(retained, {"status", "bytes"}, set(), path)
        else:
            _exact_keys(retained, {"status", "issues", "bytes"}, set(), path)
            _issues(
                retained["issues"],
                frozenset({"attribution_incomplete", "observation_incomplete"}),
                f"{path}.issues",
            )
        _integer(retained["bytes"], f"{path}.bytes")
    elif status == "unavailable":
        required = {"status"} if aggregate else {"status", "issues"}
        _exact_keys(retained, required, set(), path)
        if not aggregate:
            _issues(retained["issues"], SOURCE_UNAVAILABLE_ISSUES, f"{path}.issues")
    else:
        _exact_keys(retained, {"status", "issues"}, set(), path)
        _issues(retained["issues"], SOURCE_ERROR_ISSUES, f"{path}.issues")


def _validate_counter(value: Any, path: str) -> None:
    counter = _mapping(value, path)
    _exact_keys(counter, {"payload_bytes", "messages"}, set(), path)
    payload_bytes = _integer(counter["payload_bytes"], f"{path}.payload_bytes")
    messages = _integer(counter["messages"], f"{path}.messages")
    if messages == 0 and payload_bytes != 0:
        _fail(path, "payload_bytes must be zero when messages is zero")


def _validate_f3(value: Any, path: str, *, aggregate: bool = False) -> None:
    f3 = _mapping(value, path)
    statuses = TOTAL_STATUSES if aggregate else MEASUREMENT_STATUSES
    status = _enum(f3.get("status"), statuses, f"{path}.status")
    if aggregate:
        if status in {"reported", "partial"}:
            _exact_keys(f3, {"status", "remote_accepted"}, set(), path)
            _validate_counter(f3["remote_accepted"], f"{path}.remote_accepted")
        else:
            _exact_keys(f3, {"status"}, set(), path)
        return

    if status in {"reported", "partial"}:
        required = {"status", "remote_accepted"}
        if status == "partial":
            required.add("issues")
        _exact_keys(f3, required, set(), path)
        if status == "partial":
            _issues(f3["issues"], PARTIAL_ISSUES, f"{path}.issues")
        _validate_counter(f3["remote_accepted"], f"{path}.remote_accepted")
    else:
        _exact_keys(f3, {"status", "issues"}, set(), path)
        allowed = SOURCE_UNAVAILABLE_ISSUES if status == "unavailable" else SOURCE_ERROR_ISSUES
        _issues(f3["issues"], allowed, f"{path}.issues")


def _validate_totals(value: Any, path: str) -> None:
    totals = _mapping(value, path)
    _exact_keys(totals, {"resource_time", "retained_content", "f3"}, set(), path)
    _validate_resource_time(totals["resource_time"], f"{path}.resource_time")
    _validate_retained_content(totals["retained_content"], f"{path}.retained_content", aggregate=True)
    _validate_f3(totals["f3"], f"{path}.f3", aggregate=True)


def _canonical_decimal(value: Decimal) -> str:
    if value == value.to_integral():
        # Decimal.quantize(Decimal(1)) uses the ambient precision and raises
        # InvalidOperation for otherwise valid 29..39 digit totals. Fixed-point
        # rendering is exact and independent of that context.
        return format(value, "f").partition(".")[0]
    return format(value, "f").rstrip("0").rstrip(".") or "0"


def normalize_quota_units(quota_us: int, period_us: int) -> str:
    """Return an exact quota ratio conservatively floored to nine digits."""

    for name, value in (("quota_us", quota_us), ("period_us", period_us)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > U64_MAX:
            raise ValueError(f"{name} must be a positive unsigned 64-bit integer")
    with localcontext() as context:
        context.prec = 100
        normalized = (Decimal(quota_us) / Decimal(period_us)).quantize(Decimal("0.000000001"), rounding=ROUND_FLOOR)
    if normalized <= 0:
        raise ValueError("CPU quota ratio is below the v1 nine-decimal precision")
    if normalized > MAX_CPU_UNITS:
        raise ValueError("normalized CPU quota exceeds the v1 visible-unit bound")
    return _canonical_decimal(normalized)


def _sum_decimals(values: Sequence[Decimal], path: str) -> Decimal:
    with localcontext() as context:
        context.prec = 100
        result = sum(values, Decimal(0))
    if result > Decimal(U128_MAX):
        _fail(path, "aggregate exceeds the unsigned 128-bit bound")
    return result


def _resource_time_aggregate(
    values: Sequence[Mapping[str, Any]],
    *,
    complete: bool,
    path: str,
) -> dict[str, Any]:
    numeric_seen = {name: any(name in value for value in values) for name in _RESOURCE_TIME_NUMERIC_FIELDS}
    fully_reported = complete and bool(values) and all(value["status"] == "reported" for value in values)

    result: dict[str, Any] = {}
    if numeric_seen["measured_seconds"]:
        measured = [Decimal(value["measured_seconds"]) for value in values if "measured_seconds" in value]
        result["measured_seconds"] = _canonical_decimal(_sum_decimals(measured, f"{path}.measured_seconds"))

    if numeric_seen["cpu"]:
        sums: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
        templates: dict[tuple[str, str], dict[str, Any]] = {}
        for value in values:
            if "cpu" not in value:
                continue
            for group in value["cpu"]["groups"]:
                key = (group.get("model", ""), group.get("architecture", ""))
                templates[key] = {name: item for name, item in group.items() if name != "unit_seconds"}
                sums[key].append(Decimal(group["unit_seconds"]))
        result["cpu"] = {
            "groups": [
                {
                    **templates[key],
                    "unit_seconds": _canonical_decimal(_sum_decimals(sums[key], f"{path}.cpu.groups")),
                }
                for key in sorted(sums)
            ]
        }

    if numeric_seen["memory"]:
        values_to_sum = [Decimal(value["memory"]["byte_seconds"]) for value in values if "memory" in value]
        result["memory"] = {
            "byte_seconds": _canonical_decimal(_sum_decimals(values_to_sum, f"{path}.memory.byte_seconds"))
        }

    if numeric_seen["gpu"]:
        gpu_sums: dict[tuple[str, str, str, str], list[Decimal]] = defaultdict(list)
        gpu_templates: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for value in values:
            if "gpu" not in value:
                continue
            for group in value["gpu"]["groups"]:
                key = _gpu_group_key(group)
                gpu_templates[key] = {name: item for name, item in group.items() if name != "instance_seconds"}
                gpu_sums[key].append(Decimal(group["instance_seconds"]))
        result["gpu"] = {
            "groups": [
                {
                    **gpu_templates[key],
                    "instance_seconds": _canonical_decimal(_sum_decimals(gpu_sums[key], f"{path}.gpu.groups")),
                }
                for key in sorted(gpu_sums)
            ]
        }

    if fully_reported:
        result["status"] = "reported"
    elif any(numeric_seen.values()):
        issues: set[str] = set()
        if not complete:
            issues.add("observation_incomplete")
        for value in values:
            if value["status"] == "partial":
                issues.update(value["issues"])
            elif value["status"] == "unavailable":
                if value["issues"] == ["attribution_incomplete"]:
                    issues.add("attribution_incomplete")
                else:
                    issues.add("observation_incomplete")
        if not issues:
            issues.add("observation_incomplete")
        result["status"] = "partial"
        result["issues"] = sorted(issues)
    else:
        result = {"status": "unavailable", "issues": ["observation_incomplete"]}

    ordered = {"status": result.pop("status")}
    if "issues" in result:
        ordered["issues"] = result.pop("issues")
    ordered.update(result)
    _validate_resource_time(ordered, path)
    return ordered


def _aggregate_retained(
    values: Sequence[Mapping[str, Any]],
    *,
    complete: bool,
    path: str,
) -> dict[str, Any]:
    numeric = [value for value in values if value["status"] in {"reported", "partial"}]
    if not numeric:
        return {"status": "unavailable"}
    amount = sum(int(value["bytes"]) for value in numeric)
    if amount > U128_MAX:
        _fail(f"{path}.bytes", "aggregate exceeds the unsigned 128-bit bound")
    reported = complete and len(numeric) == len(values) and all(value["status"] == "reported" for value in values)
    return {"status": "reported" if reported else "partial", "bytes": str(amount)}


def _aggregate_f3(
    values: Sequence[Mapping[str, Any]],
    *,
    complete: bool,
    path: str,
) -> dict[str, Any]:
    numeric = [value for value in values if value["status"] in {"reported", "partial"}]
    if not numeric:
        return {"status": "unavailable"}
    payload = sum(int(value["remote_accepted"]["payload_bytes"]) for value in numeric)
    messages = sum(int(value["remote_accepted"]["messages"]) for value in numeric)
    if payload > U128_MAX or messages > U128_MAX:
        _fail(f"{path}.remote_accepted", "aggregate exceeds the unsigned 128-bit bound")
    reported = complete and len(numeric) == len(values) and all(value["status"] == "reported" for value in values)
    return {
        "status": "reported" if reported else "partial",
        "remote_accepted": {"payload_bytes": str(payload), "messages": str(messages)},
    }


def _aggregate_totals(
    resource_times: Sequence[Mapping[str, Any]],
    retained_values: Sequence[Mapping[str, Any]],
    f3_values: Sequence[Mapping[str, Any]],
    *,
    complete: bool,
    path: str,
) -> dict[str, Any]:
    totals = {
        "resource_time": _resource_time_aggregate(resource_times, complete=complete, path=f"{path}.resource_time"),
        "retained_content": _aggregate_retained(retained_values, complete=complete, path=f"{path}.retained_content"),
        "f3": _aggregate_f3(f3_values, complete=complete, path=f"{path}.f3"),
    }
    _validate_totals(totals, path)
    return totals


def _validate_participant_summary(record: Mapping[str, Any], path: str) -> None:
    _exact_keys(
        record,
        {
            "schema_version",
            "kind",
            "job_id",
            "participant_name",
            "reported_at",
            "resource_time",
            "workspace_filesystem",
            "retained_content",
            "f3",
        },
        set(),
        path,
    )
    if record["schema_version"] != SCHEMA_VERSION:
        _fail(f"{path}.schema_version", f"must equal {SCHEMA_VERSION}")
    _identifier(record["job_id"], JOB_ID_PATTERN, f"{path}.job_id")
    _identifier(record["participant_name"], PARTICIPANT_NAME_PATTERN, f"{path}.participant_name")
    _timestamp(record["reported_at"], f"{path}.reported_at")
    _validate_resource_time(record["resource_time"], f"{path}.resource_time")
    _validate_workspace_filesystem(record["workspace_filesystem"], f"{path}.workspace_filesystem")
    _validate_retained_content(record["retained_content"], f"{path}.retained_content")
    _validate_f3(record["f3"], f"{path}.f3")


def derive_participant_totals(participant_record: Mapping[str, Any]) -> dict[str, Any]:
    """Copy the three accepted values from one validated terminal report."""

    validate_record(participant_record)
    if participant_record["kind"] != KIND_PARTICIPANT_SUMMARY:
        _fail("$.kind", f"must equal {KIND_PARTICIPANT_SUMMARY}")
    return {
        "resource_time": deepcopy(participant_record["resource_time"]),
        "retained_content": deepcopy(participant_record["retained_content"]),
        "f3": deepcopy(participant_record["f3"]),
    }


def _validate_participant_entry(value: Any, path: str, cutoff_ns: int) -> None:
    entry = _mapping(value, path)
    status = _enum(entry.get("status"), PARTICIPANT_STATUSES, f"{path}.status")
    base = {"participant_name", "role", "status"}
    if status == "accepted":
        _exact_keys(
            entry,
            base
            | {
                "received_at",
                "resource_time",
                "retained_content",
                "f3",
            },
            set(),
            path,
        )
        received_at = _timestamp(entry["received_at"], f"{path}.received_at")
        if _timestamp_nanoseconds(received_at) > cutoff_ns:
            _fail(f"{path}.received_at", "must not be later than report_cutoff_at")
        _validate_resource_time(entry["resource_time"], f"{path}.resource_time")
        _validate_retained_content(entry["retained_content"], f"{path}.retained_content")
        _validate_f3(entry["f3"], f"{path}.f3")
    elif status == "invalid":
        _exact_keys(entry, base | {"received_at", "issues"}, set(), path)
        received_at = _timestamp(entry["received_at"], f"{path}.received_at")
        if _timestamp_nanoseconds(received_at) > cutoff_ns:
            _fail(f"{path}.received_at", "must not be later than report_cutoff_at")
        _issues(entry["issues"], INVALID_REPORT_ISSUES, f"{path}.issues")
    else:
        _exact_keys(entry, base, set(), path)
    _identifier(entry["participant_name"], PARTICIPANT_NAME_PATTERN, f"{path}.participant_name")
    _enum(entry["role"], ROLES, f"{path}.role")


def _validate_participant_list(
    participants: Sequence[Mapping[str, Any]],
    *,
    cutoff_ns: int,
    path: str,
) -> None:
    if not isinstance(participants, list) or not 1 <= len(participants) <= MAX_PARTICIPANTS:
        _fail(path, f"must contain 1..{MAX_PARTICIPANTS} entries")
    ordering: list[tuple[str, str]] = []
    for index, entry in enumerate(participants):
        _validate_participant_entry(entry, f"{path}[{index}]", cutoff_ns)
        ordering.append((entry["role"], entry["participant_name"]))
    if ordering != sorted(ordering):
        _fail(path, "must be sorted by role, then participant_name")
    if len({item[1] for item in ordering}) != len(ordering):
        _fail(path, "participant_name values must be unique")


def derive_job_totals(participants: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Derive job totals from one complete expected-participant list."""

    maximum_timestamp = _timestamp_nanoseconds("9999-12-31T23:59:59.999999999Z")
    _validate_participant_list(participants, cutoff_ns=maximum_timestamp, path="participants")
    accepted = [entry for entry in participants if entry["status"] == "accepted"]
    return _aggregate_totals(
        [entry["resource_time"] for entry in accepted],
        [entry["retained_content"] for entry in accepted],
        [entry["f3"] for entry in accepted],
        complete=len(accepted) == len(participants),
        path="totals",
    )


def _validate_resource_summary(record: Mapping[str, Any], path: str) -> None:
    _exact_keys(
        record,
        {"schema_version", "kind", "job_id", "report_cutoff_at", "finalized_at", "participants", "totals"},
        set(),
        path,
    )
    if record["schema_version"] != SCHEMA_VERSION:
        _fail(f"{path}.schema_version", f"must equal {SCHEMA_VERSION}")
    _identifier(record["job_id"], JOB_ID_PATTERN, f"{path}.job_id")
    cutoff = _timestamp(record["report_cutoff_at"], f"{path}.report_cutoff_at")
    finalized = _timestamp(record["finalized_at"], f"{path}.finalized_at")
    cutoff_ns = _timestamp_nanoseconds(cutoff)
    if _timestamp_nanoseconds(finalized) < cutoff_ns:
        _fail(f"{path}.finalized_at", "must not precede report_cutoff_at")
    _validate_participant_list(record["participants"], cutoff_ns=cutoff_ns, path=f"{path}.participants")
    _validate_totals(record["totals"], f"{path}.totals")
    expected = derive_job_totals(record["participants"])
    if record["totals"] != expected:
        _fail(f"{path}.totals", "must exactly equal the deterministic sum and coverage of participants")


def _validate_study_job(value: Any, path: str) -> None:
    job = _mapping(value, path)
    resource_data = _enum(job.get("resource_data"), RESOURCE_DATA_STATES, f"{path}.resource_data")
    if resource_data == "included":
        _exact_keys(
            job,
            {"job_id", "job_status", "resource_data", "totals"},
            set(),
            path,
        )
        _validate_totals(job["totals"], f"{path}.totals")
    else:
        _exact_keys(job, {"job_id", "job_status", "resource_data"}, set(), path)
    _identifier(job["job_id"], JOB_ID_PATTERN, f"{path}.job_id")
    job_status = _identifier(job["job_status"], JOB_STATUS_PATTERN, f"{path}.job_status")
    terminal = job_status.startswith("FINISHED:") or job_status in LEGACY_TERMINAL_JOB_STATES
    if resource_data in {"included", "unavailable"} and not terminal:
        _fail(f"{path}.job_status", f"must be a terminal job status when resource_data is {resource_data}")
    if resource_data == "nonterminal" and terminal:
        _fail(f"{path}.job_status", "must not be a terminal job status when resource_data is nonterminal")


def _validate_study_jobs(jobs: Sequence[Mapping[str, Any]], path: str) -> None:
    if not isinstance(jobs, list) or len(jobs) > MAX_STUDY_JOBS:
        _fail(path, f"must contain 0..{MAX_STUDY_JOBS} entries")
    job_ids: list[str] = []
    for index, job in enumerate(jobs):
        _validate_study_job(job, f"{path}[{index}]")
        job_ids.append(job["job_id"])
    if job_ids != sorted(job_ids) or len(job_ids) != len(set(job_ids)):
        _fail(path, "must be sorted by unique job_id")


def derive_study_totals(job_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Derive transient study totals from the bounded selected-job rows."""

    _validate_study_jobs(job_rows, "jobs")
    included = [job for job in job_rows if job["resource_data"] == "included"]
    return _aggregate_totals(
        [job["totals"]["resource_time"] for job in included],
        [job["totals"]["retained_content"] for job in included],
        [job["totals"]["f3"] for job in included],
        complete=len(included) == len(job_rows),
        path="totals",
    )


def _validate_study_summary(record: Mapping[str, Any], path: str) -> None:
    _exact_keys(
        record,
        {"schema_version", "kind", "selection", "generated_at", "coverage", "jobs", "totals"},
        set(),
        path,
    )
    if record["schema_version"] != SCHEMA_VERSION:
        _fail(f"{path}.schema_version", f"must equal {SCHEMA_VERSION}")
    selection = _mapping(record["selection"], f"{path}.selection")
    _exact_keys(selection, {"study_name"}, set(), f"{path}.selection")
    _identifier(selection["study_name"], STUDY_NAME_PATTERN, f"{path}.selection.study_name")
    _timestamp(record["generated_at"], f"{path}.generated_at")
    _validate_study_jobs(record["jobs"], f"{path}.jobs")

    coverage = _mapping(record["coverage"], f"{path}.coverage")
    coverage_names = {"selected_jobs", "included_jobs", "unavailable_jobs", "nonterminal_jobs"}
    _exact_keys(coverage, coverage_names, set(), f"{path}.coverage")
    actual = {
        "selected_jobs": len(record["jobs"]),
        "included_jobs": sum(job["resource_data"] == "included" for job in record["jobs"]),
        "unavailable_jobs": sum(job["resource_data"] == "unavailable" for job in record["jobs"]),
        "nonterminal_jobs": sum(job["resource_data"] == "nonterminal" for job in record["jobs"]),
    }
    for name in sorted(coverage_names):
        reported = _integer(coverage[name], f"{path}.coverage.{name}", maximum=MAX_STUDY_JOBS)
        if reported != actual[name]:
            _fail(f"{path}.coverage.{name}", f"must equal {actual[name]} from jobs")

    _validate_totals(record["totals"], f"{path}.totals")
    expected = derive_study_totals(record["jobs"])
    if record["totals"] != expected:
        _fail(f"{path}.totals", "must exactly equal the deterministic sum and coverage of included jobs")


def validate_record(record: Mapping[str, Any], *, serialized_size: int | None = None) -> None:
    """Validate one already-decoded canonical record."""

    record = _mapping(record, "$")
    kind = _enum(record.get("kind"), RECORD_KINDS, "$.kind")
    if serialized_size is not None:
        if not isinstance(serialized_size, int) or isinstance(serialized_size, bool) or serialized_size < 0:
            _fail("$", "serialized_size must be a non-negative integer")
        if serialized_size > MAX_RECORD_BYTES[kind]:
            _fail("$", f"record exceeds the {MAX_RECORD_BYTES[kind]}-byte limit")
    if _json_depth(record) > MAX_JSON_DEPTH:
        _fail("$", f"record exceeds maximum JSON depth {MAX_JSON_DEPTH}")
    _privacy_walk(record)
    {
        KIND_PARTICIPANT_SUMMARY: _validate_participant_summary,
        KIND_RESOURCE_SUMMARY: _validate_resource_summary,
        KIND_STUDY_SUMMARY: _validate_study_summary,
    }[kind](record, "$")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"$: duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ContractError(f"$: non-finite JSON number {value!r} is forbidden")


def load_and_validate(data: bytes) -> dict[str, Any]:
    """Decode UTF-8 JSON with duplicate-key rejection, then validate it."""

    if not isinstance(data, bytes):
        _fail("$", "input must be bytes")
    absolute_limit = max(MAX_RECORD_BYTES.values())
    if len(data) > absolute_limit:
        _fail("$", f"record exceeds the absolute {absolute_limit}-byte input limit")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractError("$: input must be valid UTF-8") from exc
    try:
        record = json.loads(text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_nonfinite)
    except ContractError:
        raise
    except RecursionError as exc:
        raise ContractError(f"$: JSON nesting exceeds maximum depth {MAX_JSON_DEPTH}") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise ContractError(f"$: invalid JSON: {exc}") from exc
    if not isinstance(record, dict):
        _fail("$", "record must be a JSON object")
    validate_record(record, serialized_size=len(data))
    return record


def validate_bundle(
    resource_summary: Mapping[str, Any],
    participant_records: Mapping[str, Mapping[str, Any]],
    file_bytes: Mapping[str, bytes],
) -> None:
    """Validate the exact inventory and content of a finalized archive bundle.

    The resource summary is the commit record: its accepted participant names
    determine every participant member, and it is written last by producers.
    """

    validate_record(resource_summary)
    if resource_summary["kind"] != KIND_RESOURCE_SUMMARY:
        _fail("resource_summary.kind", f"must equal {KIND_RESOURCE_SUMMARY}")
    if not isinstance(participant_records, Mapping):
        _fail("participant_records", "must be a participant_name-to-record mapping")
    if not isinstance(file_bytes, Mapping):
        _fail("file_bytes", "must be a relative-path-to-bytes mapping")

    accepted = {
        entry["participant_name"]: entry for entry in resource_summary["participants"] if entry["status"] == "accepted"
    }
    if set(participant_records) != set(accepted):
        _fail("participant_records", "keys must exactly equal the accepted participant names")

    expected_paths = {"resource_summary.json"} | {
        f"participants/{participant_name}.json" for participant_name in accepted
    }
    if set(file_bytes) != expected_paths:
        _fail("file_bytes", "paths must exactly match the summary and accepted participant records")

    decoded_summary: Mapping[str, Any] | None = None
    decoded_participants: dict[str, Mapping[str, Any]] = {}
    for relative_path in sorted(expected_paths):
        data = file_bytes[relative_path]
        if not isinstance(data, bytes):
            _fail(f"file_bytes[{relative_path!r}]", "must be exact bytes")
        decoded = load_and_validate(data)
        if relative_path == "resource_summary.json":
            decoded_summary = decoded
        else:
            participant_name = relative_path.removeprefix("participants/").removesuffix(".json")
            decoded_participants[participant_name] = decoded

    if decoded_summary != resource_summary:
        _fail("resource_summary", "does not equal the exact decoded archived record")

    for participant_name, record in participant_records.items():
        _identifier(participant_name, PARTICIPANT_NAME_PATTERN, f"participant_records[{participant_name!r}]")
        validate_record(record)
        if record["kind"] != KIND_PARTICIPANT_SUMMARY:
            _fail(f"participant_records[{participant_name!r}].kind", f"must equal {KIND_PARTICIPANT_SUMMARY}")
        if record["participant_name"] != participant_name:
            _fail(f"participant_records[{participant_name!r}].participant_name", "must equal its mapping key")
        if record["job_id"] != resource_summary["job_id"]:
            _fail(f"participant_records[{participant_name!r}].job_id", "must equal summary job_id")
        if decoded_participants.get(participant_name) != record:
            _fail(f"participant_records[{participant_name!r}]", "does not equal the decoded archived record")

        relative_path = f"participants/{participant_name}.json"
        entry = accepted[participant_name]
        copied = derive_participant_totals(record)
        for field in ("resource_time", "retained_content", "f3"):
            if entry[field] != copied[field]:
                _fail(
                    f"resource_summary.participants[{participant_name!r}].{field}",
                    "must exactly copy the accepted terminal participant report",
                )
