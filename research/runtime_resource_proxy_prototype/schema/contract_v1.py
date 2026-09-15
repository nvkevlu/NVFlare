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

"""Executable validation for the compact, typed resource-statistics v1 contract.

The JSON Schema closes every record and fixes the wire types.  This module adds
semantic checks that JSON Schema cannot express cleanly: selector
reconciliation, status/issue relationships, deterministic ordering, time
relationships, aggregate sums, and privacy constraints.

Canonical quantities are strings.  Integer quantities use base-10 unsigned
integers.  Fractional quantities use a non-exponent decimal with at most nine
fractional digits and no insignificant trailing zeroes.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "1.0"

KIND_ATTEMPT_START = "nvflare.resource_stats.attempt_start"
KIND_ATTEMPT_FINAL = "nvflare.resource_stats.attempt_final"
KIND_ATTEMPT_END = "nvflare.resource_stats.attempt_end"
KIND_PARTICIPANT_START = "nvflare.resource_stats.participant_start"
KIND_PARTICIPANT_FINAL = "nvflare.resource_stats.participant_final"
KIND_PARTICIPANT_SUMMARY = "nvflare.resource_stats.participant_summary"
KIND_RESOURCE_SUMMARY = "nvflare.resource_stats.resource_summary"
KIND_MANIFEST = "nvflare.resource_stats.manifest"
RECORD_KINDS = frozenset(
    {
        KIND_ATTEMPT_START,
        KIND_ATTEMPT_FINAL,
        KIND_ATTEMPT_END,
        KIND_PARTICIPANT_START,
        KIND_PARTICIPANT_FINAL,
        KIND_PARTICIPANT_SUMMARY,
        KIND_RESOURCE_SUMMARY,
        KIND_MANIFEST,
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

POINT_STATUSES = frozenset({"reported", "unavailable", "error"})
MEASUREMENT_STATUSES = frozenset({"reported", "partial", "unavailable", "error"})
TOTAL_STATUSES = frozenset({"reported", "partial", "unavailable"})
ROSTER_STATUSES = frozenset({"accepted", "missing", "invalid", "disabled"})
ROLES = frozenset({"client", "server"})
ATTEMPT_END_REASONS = frozenset({"released", "failed", "terminated", "launch_failed", "reconfigured"})
GPU_KINDS = frozenset({"full_gpu", "mig_compute_instance"})

# The containing resource supplies the subject of an issue.  A status further
# narrows its meaning, eliminating CPU-, GPU-, F3-, and artifact-specific codes.
STATUS_ISSUES = {
    "reported": frozenset(),
    "partial": frozenset({"counter_gap", "observation_incomplete", "attribution_incomplete"}),
    "unavailable": frozenset(
        {
            "not_bound",
            "observation_incomplete",
            "attribution_incomplete",
            "unsupported",
            "dependency_missing",
        }
    ),
    "error": frozenset({"permission_denied", "malformed_source"}),
}

_CAPACITY_ISSUES = frozenset(
    {
        "observation_incomplete",
        "attribution_incomplete",
        "unsupported",
        "permission_denied",
        "dependency_missing",
        "malformed_source",
    }
)
RESOURCE_ISSUES = {
    "cpu": _CAPACITY_ISSUES,
    "memory": _CAPACITY_ISSUES,
    "storage": _CAPACITY_ISSUES,
    "gpu": _CAPACITY_ISSUES,
    "retained_content": ISSUE_CODES - {"counter_gap"},
    "f3": ISSUE_CODES,
}

MAX_ISSUES = 4
MAX_ATTEMPTS = 4_096
MAX_PARTICIPANTS = 10_000
MAX_GPU_GROUPS = 4_096
MAX_ARTIFACT_ENTRIES = 4_096
MAX_RELATIVE_PATH_BYTES = 512
MAX_JSON_DEPTH = 32
MAX_RECORD_BYTES = {
    KIND_ATTEMPT_START: 1024 * 1024,
    KIND_ATTEMPT_FINAL: 1024 * 1024,
    KIND_ATTEMPT_END: 64 * 1024,
    KIND_PARTICIPANT_START: 64 * 1024,
    KIND_PARTICIPANT_FINAL: 1024 * 1024,
    KIND_PARTICIPANT_SUMMARY: 64 * 1024 * 1024,
    KIND_RESOURCE_SUMMARY: 64 * 1024 * 1024,
    KIND_MANIFEST: 4 * 1024 * 1024,
}

U32_MAX = 2**32 - 1
U64_MAX = 2**64 - 1
U128_MAX = 2**128 - 1
MAX_CPU_UNITS = Decimal("1048576")

INTEGER_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,38})$")
DECIMAL_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,38})(?:\.[0-9]{0,8}[1-9])?$")
ATTEMPT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
HASH_KEY_PATTERN = re.compile(r"^sha256-[0-9a-f]{64}$")
TIMESTAMP_PATTERN = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,9}))?Z$")
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PARTICIPANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+/@-]{0,127}$")
ARCHITECTURE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
MIG_PROFILE_PATTERN = re.compile(r"^[1-9][0-9]*g\.[1-9][0-9]*gb(?:\+me)?$")
RELATIVE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")

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


def _relative_path(value: Any, path: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > MAX_RELATIVE_PATH_BYTES
        or not RELATIVE_PATH_PATTERN.fullmatch(value)
        or value.startswith("/")
        or "//" in value
    ):
        _fail(path, "must be a bounded normalized relative POSIX path")
    pure = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in pure.parts) or str(pure) != value:
        _fail(path, "must not contain empty, current-directory, or parent-directory segments")
    return value


def _issues(value: Any, status: str, resource: str, path: str) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_ISSUES:
        _fail(path, f"must contain 1..{MAX_ISSUES} issue codes")
    if any(not isinstance(item, str) for item in value):
        _fail(path, "must contain strings")
    if value != sorted(value) or len(value) != len(set(value)):
        _fail(path, "must be sorted and unique")
    allowed = STATUS_ISSUES[status] & RESOURCE_ISSUES[resource]
    unknown = set(value) - allowed
    if unknown:
        _fail(path, f"contains issues not valid for {resource}/{status}: {', '.join(sorted(unknown))}")


def _status_shape(
    value: Mapping[str, Any],
    path: str,
    *,
    resource: str,
    statuses: frozenset[str],
    reported_required: set[str],
    reported_optional: set[str] = frozenset(),
) -> str:
    status = _enum(value.get("status"), statuses, f"{path}.status")
    if status == "reported":
        _exact_keys(value, {"status"} | reported_required, set(reported_optional), path)
    elif status == "partial":
        _exact_keys(value, {"status", "issues"} | reported_required, set(reported_optional), path)
        _issues(value["issues"], status, resource, f"{path}.issues")
    else:
        _exact_keys(value, {"status", "issues"}, set(), path)
        _issues(value["issues"], status, resource, f"{path}.issues")
    return status


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


def _json_depth(value: Any, depth: int = 1) -> int:
    if isinstance(value, Mapping):
        return max([depth] + [_json_depth(item, depth + 1) for item in value.values()])
    if isinstance(value, list):
        return max([depth] + [_json_depth(item, depth + 1) for item in value])
    return depth


def _validate_cpu(value: Any, path: str) -> None:
    cpu = _mapping(value, path)
    status = _status_shape(
        cpu,
        path,
        resource="cpu",
        statuses=POINT_STATUSES,
        reported_required={"visible_units", "evidence"},
        reported_optional={"model", "architecture"},
    )
    if status != "reported":
        return

    visible = _decimal(cpu["visible_units"], f"{path}.visible_units", maximum=MAX_CPU_UNITS, positive=True)
    if "model" in cpu:
        _model(cpu["model"], f"{path}.model")
    if "architecture" in cpu:
        _identifier(cpu["architecture"], ARCHITECTURE_PATTERN, f"{path}.architecture")

    evidence = _mapping(cpu["evidence"], f"{path}.evidence")
    names = {"affinity_count", "cpuset_count", "quota_units", "online_count"}
    _exact_keys(evidence, set(), names, f"{path}.evidence")
    if not evidence:
        _fail(f"{path}.evidence", "must contain at least one CPU observation")

    selectors: list[Decimal] = []
    for name in ("affinity_count", "cpuset_count", "online_count"):
        if name in evidence:
            number = _integer(evidence[name], f"{path}.evidence.{name}", maximum=U32_MAX, positive=True)
            if name != "online_count":
                selectors.append(Decimal(number))
    if "quota_units" in evidence:
        selectors.append(
            _decimal(
                evidence["quota_units"],
                f"{path}.evidence.quota_units",
                maximum=MAX_CPU_UNITS,
                positive=True,
            )
        )
    if selectors and "online_count" in evidence:
        _fail(
            f"{path}.evidence.online_count",
            "must be omitted when affinity_count, cpuset_count, or quota_units is available",
        )
    if not selectors:
        if "online_count" not in evidence:
            _fail(f"{path}.evidence", "requires a visibility selector or online_count fallback")
        selectors.append(Decimal(evidence["online_count"]))
    if visible != min(selectors):
        _fail(f"{path}.visible_units", "must equal the minimum applicable CPU evidence value")


def _validate_memory(value: Any, path: str) -> None:
    memory = _mapping(value, path)
    status = _status_shape(
        memory,
        path,
        resource="memory",
        statuses=POINT_STATUSES,
        reported_required={"visible_bytes", "evidence"},
    )
    if status != "reported":
        return

    visible = _integer(memory["visible_bytes"], f"{path}.visible_bytes", maximum=U64_MAX, positive=True)
    evidence = _mapping(memory["evidence"], f"{path}.evidence")
    names = {"physical_bytes", "cgroup_limit_bytes"}
    _exact_keys(evidence, set(), names, f"{path}.evidence")
    if not evidence:
        _fail(f"{path}.evidence", "must contain physical_bytes or cgroup_limit_bytes")
    candidates = [
        _integer(item, f"{path}.evidence.{name}", maximum=U64_MAX, positive=True) for name, item in evidence.items()
    ]
    if visible != min(candidates):
        _fail(f"{path}.visible_bytes", "must equal the minimum memory evidence value")


def _validate_storage(value: Any, path: str) -> None:
    storage = _mapping(value, path)
    status = _status_shape(
        storage,
        path,
        resource="storage",
        statuses=MEASUREMENT_STATUSES,
        reported_required={"capacity_bytes"},
    )
    if status not in {"reported", "partial"}:
        return
    _integer(storage["capacity_bytes"], f"{path}.capacity_bytes", maximum=U64_MAX, positive=True)


def _gpu_group_key(group: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        group["kind"],
        group.get("model", ""),
        group.get("memory_bytes", ""),
        group.get("mig_profile", ""),
    )


def _validate_gpu_group(value: Any, path: str, *, time_value: bool = False) -> None:
    group = _mapping(value, path)
    numeric_name = "instance_seconds" if time_value else "count"
    _exact_keys(
        group,
        {"kind", numeric_name},
        {"model", "memory_bytes", "mig_profile"},
        path,
    )
    kind = _enum(group["kind"], GPU_KINDS, f"{path}.kind")
    if time_value:
        _decimal(group[numeric_name], f"{path}.{numeric_name}")
    else:
        _integer(group[numeric_name], f"{path}.{numeric_name}", maximum=U32_MAX, positive=True)
    if "model" in group:
        _model(group["model"], f"{path}.model")
    if "memory_bytes" in group:
        _integer(group["memory_bytes"], f"{path}.memory_bytes", maximum=U64_MAX, positive=True)
    if "mig_profile" in group:
        _identifier(group["mig_profile"], MIG_PROFILE_PATTERN, f"{path}.mig_profile")
    if kind == "full_gpu" and "mig_profile" in group:
        _fail(f"{path}.mig_profile", "is valid only for a MIG compute-instance group")


def _validate_group_list(value: Any, path: str, *, gpu: bool, time_value: bool = False) -> None:
    if not isinstance(value, list) or len(value) > MAX_GPU_GROUPS:
        _fail(path, f"must be an array with at most {MAX_GPU_GROUPS} groups")
    keys: list[tuple[str, ...]] = []
    for index, group in enumerate(value):
        item_path = f"{path}[{index}]"
        if gpu:
            _validate_gpu_group(group, item_path, time_value=time_value)
            keys.append(_gpu_group_key(group))
        else:
            _validate_cpu_time_group(group, item_path)
            keys.append((group.get("model", ""), group.get("architecture", "")))
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        _fail(path, "groups must be consolidated, unique, and sorted by their identifying fields")


def _validate_gpu(value: Any, path: str) -> None:
    gpu = _mapping(value, path)
    status = _enum(gpu.get("status"), POINT_STATUSES, f"{path}.status")
    if status == "reported":
        _exact_keys(gpu, {"status", "cuda_mask_present", "groups"}, set(), path)
        if not isinstance(gpu["cuda_mask_present"], bool):
            _fail(f"{path}.cuda_mask_present", "must be a boolean")
        _validate_group_list(gpu["groups"], f"{path}.groups", gpu=True)
        if sum(int(group["count"]) for group in gpu["groups"]) > U32_MAX:
            _fail(f"{path}.groups", "the sum of group counts must fit in an unsigned 32-bit integer")
    else:
        _exact_keys(gpu, {"status", "cuda_mask_present", "issues"}, set(), path)
        if not isinstance(gpu["cuda_mask_present"], bool):
            _fail(f"{path}.cuda_mask_present", "must be a boolean")
        _issues(gpu["issues"], status, "gpu", f"{path}.issues")


def _validate_compute_capacity(value: Any, path: str) -> None:
    capacity = _mapping(value, path)
    _exact_keys(capacity, {"cpu", "memory", "gpu"}, set(), path)
    _validate_cpu(capacity["cpu"], f"{path}.cpu")
    _validate_memory(capacity["memory"], f"{path}.memory")
    _validate_gpu(capacity["gpu"], f"{path}.gpu")


def _validate_retained_content(value: Any, path: str) -> None:
    retained = _mapping(value, path)
    status = _status_shape(
        retained,
        path,
        resource="retained_content",
        statuses=MEASUREMENT_STATUSES,
        reported_required={"entries"},
    )
    if status not in {"reported", "partial"}:
        return
    entries = retained["entries"]
    if not isinstance(entries, list) or len(entries) > MAX_ARTIFACT_ENTRIES:
        _fail(f"{path}.entries", f"must be an array with at most {MAX_ARTIFACT_ENTRIES} entries")
    paths: list[str] = []
    for index, entry_value in enumerate(entries):
        item_path = f"{path}.entries[{index}]"
        entry = _mapping(entry_value, item_path)
        _exact_keys(entry, {"relative_path", "size_bytes", "sha256"}, set(), item_path)
        paths.append(_relative_path(entry["relative_path"], f"{item_path}.relative_path"))
        _integer(entry["size_bytes"], f"{item_path}.size_bytes")
        _identifier(entry["sha256"], SHA256_PATTERN, f"{item_path}.sha256")
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        _fail(f"{path}.entries", "entries must have unique relative paths in sorted order")


def _validate_counter(value: Any, path: str) -> None:
    counter = _mapping(value, path)
    _exact_keys(counter, {"payload_bytes", "messages"}, set(), path)
    payload_bytes = _integer(counter["payload_bytes"], f"{path}.payload_bytes")
    messages = _integer(counter["messages"], f"{path}.messages")
    if messages == 0 and payload_bytes != 0:
        _fail(path, "payload_bytes must be zero when messages is zero")


_F3_BUCKETS = (
    "remote_accepted",
    "local_delivered",
    "remote_failed_before_acceptance",
)


def _validate_f3(value: Any, path: str) -> None:
    f3 = _mapping(value, path)
    status = _status_shape(
        f3,
        path,
        resource="f3",
        statuses=MEASUREMENT_STATUSES,
        reported_required=set(_F3_BUCKETS),
    )
    if status not in {"reported", "partial"}:
        return
    for bucket in _F3_BUCKETS:
        _validate_counter(f3[bucket], f"{path}.{bucket}")


def _validate_cpu_time_group(value: Any, path: str) -> None:
    group = _mapping(value, path)
    _exact_keys(group, {"unit_seconds"}, {"model", "architecture"}, path)
    _decimal(group["unit_seconds"], f"{path}.unit_seconds")
    if "model" in group:
        _model(group["model"], f"{path}.model")
    if "architecture" in group:
        _identifier(group["architecture"], ARCHITECTURE_PATTERN, f"{path}.architecture")


def _total_status_shape(value: Mapping[str, Any], path: str, fields: set[str]) -> str:
    """Validate a derived total; explanations are derived, not persisted."""

    status = _enum(value.get("status"), TOTAL_STATUSES, f"{path}.status")
    if status in {"reported", "partial"}:
        _exact_keys(value, {"status"} | fields, set(), path)
    else:
        _exact_keys(value, {"status"}, set(), path)
    return status


def _validate_group_total(value: Any, path: str, *, resource: str, gpu: bool) -> None:
    total = _mapping(value, path)
    status = _total_status_shape(total, path, {"groups"})
    if status in {"reported", "partial"}:
        _validate_group_list(total["groups"], f"{path}.groups", gpu=gpu, time_value=gpu)


def _validate_scalar_total(value: Any, path: str, *, resource: str, field: str) -> None:
    total = _mapping(value, path)
    status = _total_status_shape(total, path, {field})
    if status in {"reported", "partial"}:
        _decimal(total[field], f"{path}.{field}")


def _validate_retained_total(value: Any, path: str) -> None:
    total = _mapping(value, path)
    status = _total_status_shape(total, path, {"bytes"})
    if status in {"reported", "partial"}:
        _integer(total["bytes"], f"{path}.bytes")


def _validate_f3_total(value: Any, path: str) -> None:
    total = _mapping(value, path)
    status = _total_status_shape(total, path, {"remote_accepted"})
    if status in {"reported", "partial"}:
        _validate_counter(total["remote_accepted"], f"{path}.remote_accepted")


_TOTAL_FIELDS = ("cpu", "memory", "storage", "gpu", "retained_content", "f3")


def _validate_totals(value: Any, path: str) -> None:
    totals = _mapping(value, path)
    _exact_keys(totals, set(_TOTAL_FIELDS), set(), path)
    _validate_group_total(totals["cpu"], f"{path}.cpu", resource="cpu", gpu=False)
    _validate_scalar_total(totals["memory"], f"{path}.memory", resource="memory", field="byte_seconds")
    _validate_scalar_total(totals["storage"], f"{path}.storage", resource="storage", field="byte_seconds")
    _validate_group_total(totals["gpu"], f"{path}.gpu", resource="gpu", gpu=True)
    _validate_retained_total(totals["retained_content"], f"{path}.retained_content")
    _validate_f3_total(totals["f3"], f"{path}.f3")


def _canonical_decimal(value: Decimal) -> str:
    if value == value.to_integral():
        return str(value.quantize(Decimal(1)))
    rendered = format(value, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def normalize_quota_units(quota_us: int, period_us: int) -> str:
    """Normalize a finite CPU quota conservatively for the canonical wire format.

    The raw positive microsecond values stay probe-internal.  Division is exact
    Decimal arithmetic followed by floor-to-nine-fractional-digits so a
    repeating ratio cannot overstate the effective CPU limit.
    """

    for name, value in (("quota_us", quota_us), ("period_us", period_us)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > U64_MAX:
            raise ValueError(f"{name} must be a positive unsigned 64-bit integer")
    with localcontext() as context:
        context.prec = 100
        normalized = (Decimal(quota_us) / Decimal(period_us)).quantize(
            Decimal("0.000000001"), rounding=ROUND_FLOOR
        )
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


def _aggregate_status(roster: Sequence[Mapping[str, Any]], accepted: Sequence[Mapping[str, Any]], resource: str) -> str:
    states = [entry["totals"][resource]["status"] for entry in accepted]
    numeric_count = sum(state in {"reported", "partial"} for state in states)
    all_accepted = len(accepted) == len(roster)
    if numeric_count and all_accepted and all(state == "reported" for state in states):
        return "reported"
    return "partial" if numeric_count else "unavailable"


def _expected_group_total(
    roster: Sequence[Mapping[str, Any]],
    accepted: Sequence[Mapping[str, Any]],
    resource: str,
) -> dict[str, Any]:
    status = _aggregate_status(roster, accepted, resource)
    if status == "unavailable":
        return {"status": status}

    value_name = "unit_seconds" if resource == "cpu" else "instance_seconds"
    sums: dict[tuple[str, ...], list[Decimal]] = defaultdict(list)
    templates: dict[tuple[str, ...], dict[str, Any]] = {}
    for entry in accepted:
        source = entry["totals"][resource]
        if source["status"] not in {"reported", "partial"}:
            continue
        for group in source["groups"]:
            if resource == "cpu":
                key = (group.get("model", ""), group.get("architecture", ""))
            else:
                key = _gpu_group_key(group)
            template = {name: item for name, item in group.items() if name != value_name}
            templates[key] = template
            sums[key].append(Decimal(group[value_name]))

    groups = []
    for key in sorted(sums):
        group = dict(templates[key])
        group[value_name] = _canonical_decimal(_sum_decimals(sums[key], f"$.totals.{resource}"))
        groups.append(group)
    result: dict[str, Any] = {"status": status, "groups": groups}
    return result


def _expected_scalar_total(
    roster: Sequence[Mapping[str, Any]],
    accepted: Sequence[Mapping[str, Any]],
    resource: str,
    field: str,
) -> dict[str, Any]:
    status = _aggregate_status(roster, accepted, resource)
    if status == "unavailable":
        return {"status": status}
    values = [
        Decimal(entry["totals"][resource][field])
        for entry in accepted
        if entry["totals"][resource]["status"] in {"reported", "partial"}
    ]
    result: dict[str, Any] = {
        "status": status,
        field: _canonical_decimal(_sum_decimals(values, f"$.totals.{resource}.{field}")),
    }
    return result


def _expected_retained_total(
    roster: Sequence[Mapping[str, Any]], accepted: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    status = _aggregate_status(roster, accepted, "retained_content")
    if status == "unavailable":
        return {"status": status}
    value = sum(
        int(entry["totals"]["retained_content"]["bytes"])
        for entry in accepted
        if entry["totals"]["retained_content"]["status"] in {"reported", "partial"}
    )
    if value > U128_MAX:
        _fail("$.totals.retained_content.bytes", "aggregate exceeds the unsigned 128-bit bound")
    result: dict[str, Any] = {"status": status, "bytes": str(value)}
    return result


def _expected_f3_total(roster: Sequence[Mapping[str, Any]], accepted: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    status = _aggregate_status(roster, accepted, "f3")
    if status == "unavailable":
        return {"status": status}
    numeric = [
        entry["totals"]["f3"]["remote_accepted"]
        for entry in accepted
        if entry["totals"]["f3"]["status"] in {"reported", "partial"}
    ]
    payload = sum(int(counter["payload_bytes"]) for counter in numeric)
    messages = sum(int(counter["messages"]) for counter in numeric)
    if payload > U128_MAX or messages > U128_MAX:
        _fail("$.totals.f3.remote_accepted", "aggregate exceeds the unsigned 128-bit bound")
    result: dict[str, Any] = {
        "status": status,
        "remote_accepted": {"payload_bytes": str(payload), "messages": str(messages)},
    }
    return result


def _expected_job_totals(roster: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    accepted = [entry for entry in roster if entry["status"] == "accepted"]
    return {
        "cpu": _expected_group_total(roster, accepted, "cpu"),
        "memory": _expected_scalar_total(roster, accepted, "memory", "byte_seconds"),
        "storage": _expected_scalar_total(roster, accepted, "storage", "byte_seconds"),
        "gpu": _expected_group_total(roster, accepted, "gpu"),
        "retained_content": _expected_retained_total(roster, accepted),
        "f3": _expected_f3_total(roster, accepted),
    }


_COMMON_ATTEMPT_FIELDS = {
    "schema_version",
    "kind",
    "job_id",
    "participant_id",
    "attempt_id",
    "environment_key",
}

RESOURCE_TIME_FORMULAS = {
    "cpu.unit_seconds": "attempt_start.cpu.visible_units * (closed_at - opened_at)",
    "memory.byte_seconds": "attempt_start.memory.visible_bytes * (closed_at - opened_at)",
    "storage.byte_seconds": "participant_start.storage.capacity_bytes * participant_lifetime_seconds",
    "gpu.instance_seconds": "attempt_start.gpu.groups[].count * (closed_at - opened_at)",
}


def _validate_attempt_identity(record: Mapping[str, Any], path: str) -> None:
    if record.get("schema_version") != SCHEMA_VERSION:
        _fail(f"{path}.schema_version", f"must equal {SCHEMA_VERSION}")
    _identifier(record.get("job_id"), JOB_ID_PATTERN, f"{path}.job_id")
    _identifier(record.get("participant_id"), PARTICIPANT_ID_PATTERN, f"{path}.participant_id")
    _identifier(record.get("attempt_id"), ATTEMPT_ID_PATTERN, f"{path}.attempt_id")
    _identifier(record.get("environment_key"), HASH_KEY_PATTERN, f"{path}.environment_key")


def _validate_attempt_start_body(value: Any, path: str) -> None:
    body = _mapping(value, path)
    _exact_keys(body, {"capacity"}, set(), path)
    _validate_compute_capacity(body["capacity"], f"{path}.capacity")


def _validate_attempt_final_body(value: Any, path: str) -> None:
    body = _mapping(value, path)
    _exact_keys(body, {"capacity"}, set(), path)
    _validate_compute_capacity(body["capacity"], f"{path}.capacity")


def _validate_participant_start_body(value: Any, path: str) -> None:
    body = _mapping(value, path)
    _exact_keys(body, {"observed_at", "storage"}, set(), path)
    _timestamp(body["observed_at"], f"{path}.observed_at")
    _validate_storage(body["storage"], f"{path}.storage")


def _validate_participant_final_body(value: Any, path: str) -> None:
    body = _mapping(value, path)
    _exact_keys(body, {"observed_at", "storage", "retained_content", "f3"}, set(), path)
    _timestamp(body["observed_at"], f"{path}.observed_at")
    _validate_storage(body["storage"], f"{path}.storage")
    _validate_retained_content(body["retained_content"], f"{path}.retained_content")
    _validate_f3(body["f3"], f"{path}.f3")


def _validate_attempt_end_body(value: Any, path: str) -> None:
    body = _mapping(value, path)
    _exact_keys(body, {"closed_at", "reason"}, set(), path)
    _timestamp(body["closed_at"], f"{path}.closed_at")
    _enum(body["reason"], ATTEMPT_END_REASONS, f"{path}.reason")


def _validate_attempt_start(record: Mapping[str, Any], path: str) -> None:
    _exact_keys(record, _COMMON_ATTEMPT_FIELDS | {"opened_at", "capacity"}, set(), path)
    _validate_attempt_identity(record, path)
    _timestamp(record["opened_at"], f"{path}.opened_at")
    _validate_attempt_start_body({"capacity": record["capacity"]}, path)


def _validate_attempt_final(record: Mapping[str, Any], path: str) -> None:
    _exact_keys(
        record,
        _COMMON_ATTEMPT_FIELDS | {"capacity"},
        set(),
        path,
    )
    _validate_attempt_identity(record, path)
    _validate_attempt_final_body({"capacity": record["capacity"]}, path)


def _validate_attempt_end(record: Mapping[str, Any], path: str) -> None:
    _exact_keys(record, _COMMON_ATTEMPT_FIELDS | {"opened_at", "closed_at", "reason"}, set(), path)
    _validate_attempt_identity(record, path)
    opened_at = _timestamp(record["opened_at"], f"{path}.opened_at")
    closed_at = _timestamp(record["closed_at"], f"{path}.closed_at")
    if _timestamp_nanoseconds(closed_at) < _timestamp_nanoseconds(opened_at):
        _fail(f"{path}.closed_at", "must not precede opened_at")
    _validate_attempt_end_body({name: record[name] for name in ("closed_at", "reason")}, path)


def _validate_participant_identity(record: Mapping[str, Any], path: str) -> None:
    if record.get("schema_version") != SCHEMA_VERSION:
        _fail(f"{path}.schema_version", f"must equal {SCHEMA_VERSION}")
    _identifier(record.get("job_id"), JOB_ID_PATTERN, f"{path}.job_id")
    _identifier(record.get("participant_id"), PARTICIPANT_ID_PATTERN, f"{path}.participant_id")


def _validate_participant_start(record: Mapping[str, Any], path: str) -> None:
    required = {"schema_version", "kind", "job_id", "participant_id", "observed_at", "storage"}
    _exact_keys(record, required, set(), path)
    _validate_participant_identity(record, path)
    _validate_participant_start_body({name: record[name] for name in ("observed_at", "storage")}, path)


def _validate_participant_final(record: Mapping[str, Any], path: str) -> None:
    required = {
        "schema_version",
        "kind",
        "job_id",
        "participant_id",
        "observed_at",
        "storage",
        "retained_content",
        "f3",
    }
    _exact_keys(record, required, set(), path)
    _validate_participant_identity(record, path)
    _validate_participant_final_body(
        {name: record[name] for name in ("observed_at", "storage", "retained_content", "f3")}, path
    )


def _validate_attempt_summary(value: Any, path: str) -> tuple[str, int, int]:
    attempt = _mapping(value, path)
    _exact_keys(
        attempt,
        {"attempt_id", "environment_key", "opened_at", "end"},
        {"start", "final"},
        path,
    )
    attempt_id = _identifier(attempt["attempt_id"], ATTEMPT_ID_PATTERN, f"{path}.attempt_id")
    environment_key = _identifier(attempt["environment_key"], HASH_KEY_PATTERN, f"{path}.environment_key")
    opened_at = _timestamp(attempt["opened_at"], f"{path}.opened_at")
    if "start" in attempt:
        _validate_attempt_start_body(attempt["start"], f"{path}.start")
    if "final" in attempt:
        _validate_attempt_final_body(attempt["final"], f"{path}.final")
    _validate_attempt_end_body(attempt["end"], f"{path}.end")

    opened_ns = _timestamp_nanoseconds(opened_at)
    closed_ns = _timestamp_nanoseconds(attempt["end"]["closed_at"])
    if closed_ns < opened_ns:
        _fail(f"{path}.end.closed_at", "must not precede opened_at")
    if attempt["end"]["reason"] == "launch_failed":
        if "start" in attempt or "final" in attempt:
            _fail(path, "a launch_failed attempt cannot contain worker startup or final observations")
    elif "start" not in attempt:
        _fail(f"{path}.start", "is required unless end.reason is launch_failed")
    return environment_key, opened_ns, closed_ns


def _validate_participant_summary(record: Mapping[str, Any], path: str) -> None:
    required = {"schema_version", "kind", "job_id", "participant_key", "start", "final", "attempts"}
    _exact_keys(record, required, set(), path)
    if record["schema_version"] != SCHEMA_VERSION:
        _fail(f"{path}.schema_version", f"must equal {SCHEMA_VERSION}")
    _identifier(record["job_id"], JOB_ID_PATTERN, f"{path}.job_id")
    _identifier(record["participant_key"], HASH_KEY_PATTERN, f"{path}.participant_key")
    _validate_participant_start_body(record["start"], f"{path}.start")
    _validate_participant_final_body(record["final"], f"{path}.final")
    participant_start_ns = _timestamp_nanoseconds(record["start"]["observed_at"])
    participant_final_ns = _timestamp_nanoseconds(record["final"]["observed_at"])
    if participant_final_ns < participant_start_ns:
        _fail(f"{path}.final.observed_at", "must not precede participant startup")
    attempts = record["attempts"]
    if not isinstance(attempts, list) or len(attempts) > MAX_ATTEMPTS:
        _fail(f"{path}.attempts", f"must contain 0..{MAX_ATTEMPTS} attempts")

    attempt_ids: list[str] = []
    intervals: dict[str, list[tuple[int, int, str, Mapping[str, Any]]]] = defaultdict(list)
    for index, attempt in enumerate(attempts):
        item_path = f"{path}.attempts[{index}]"
        environment_key, opened_ns, closed_ns = _validate_attempt_summary(attempt, item_path)
        attempt_ids.append(attempt["attempt_id"])
        if opened_ns < participant_start_ns:
            _fail(f"{item_path}.opened_at", "must not precede participant startup")
        if closed_ns > participant_final_ns:
            _fail(f"{item_path}.end.closed_at", "must not follow participant finalization")
        intervals[environment_key].append((opened_ns, closed_ns, item_path, attempt))
    if attempt_ids != sorted(attempt_ids) or len(attempt_ids) != len(set(attempt_ids)):
        _fail(f"{path}.attempts", "must be sorted by unique attempt_id")

    for environment_intervals in intervals.values():
        environment_intervals.sort()
        previous: tuple[int, int, str, Mapping[str, Any]] | None = None
        for opened_ns, closed_ns, item_path, attempt in environment_intervals:
            if previous is not None and opened_ns < previous[1]:
                _fail(item_path, "overlaps another attempt in the same execution environment")
            if previous is not None:
                previous_closed_ns = previous[1]
                previous_path = previous[2]
                previous_attempt = previous[3]
                if previous_attempt["end"]["reason"] == "reconfigured" and opened_ns != previous_closed_ns:
                    _fail(
                        f"{previous_path}.end.reason",
                        "reconfigured requires a same-environment successor at the exact closure boundary",
                    )
                previous_vector = _compute_capacity_signature(previous_attempt)
                current_vector = _compute_capacity_signature(attempt)
                if (
                    previous_attempt["end"]["reason"] == "reconfigured"
                    and previous_vector is not None
                    and current_vector is not None
                    and previous_vector == current_vector
                ):
                    _fail(
                        f"{previous_path}.end.reason",
                        "reconfigured requires a changed numeric capacity vector when both snapshots are comparable",
                    )
            previous = (opened_ns, closed_ns, item_path, attempt)
        if previous is not None and previous[3]["end"]["reason"] == "reconfigured":
            _fail(
                f"{previous[2]}.end.reason",
                "reconfigured requires a same-environment successor at the exact closure boundary",
            )


def _duration_seconds(start: str, end: str) -> Decimal:
    nanoseconds = _timestamp_nanoseconds(end) - _timestamp_nanoseconds(start)
    assert nanoseconds >= 0
    return Decimal(nanoseconds) / Decimal(1_000_000_000)


def _resource_product(capacity: Decimal, seconds: Decimal, path: str) -> Decimal:
    with localcontext() as context:
        context.prec = 100
        value = (capacity * seconds).quantize(Decimal("0.000000001"), rounding=ROUND_HALF_EVEN)
    if value > Decimal(U128_MAX):
        _fail(path, "derived resource time exceeds the unsigned 128-bit bound")
    return value


def _capacity_signature(resource: str, value: Mapping[str, Any]) -> Any:
    if value["status"] not in {"reported", "partial"}:
        return None
    if resource == "cpu":
        return value["visible_units"]
    if resource == "memory":
        return value["visible_bytes"]
    if resource == "storage":
        return value["capacity_bytes"]
    counts: dict[str, int] = defaultdict(int)
    for group in value["groups"]:
        counts[group["kind"]] += int(group["count"])
    return tuple(sorted(counts.items()))


def _compute_capacity_signature(attempt: Mapping[str, Any]) -> tuple[Any, ...] | None:
    start = attempt.get("start")
    if start is None:
        return None
    capacity = start["capacity"]
    if any(capacity[resource]["status"] != "reported" for resource in ("cpu", "memory", "gpu")):
        return None
    return tuple(_capacity_signature(resource, capacity[resource]) for resource in ("cpu", "memory", "gpu"))


def _derived_status(numeric_seen: bool, degraded: bool) -> str:
    if not numeric_seen:
        return "unavailable"
    return "partial" if degraded else "reported"


def derive_participant_totals(
    participant_record: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Derive resource-window seconds and totals from participant lifecycle facts.

    Transient compute time always ends at the supervisor-confirmed attempt end;
    an attempt final is only stability evidence.  Persistent storage spans the
    participant start-to-final interval.  Retained content and F3 are consumed
    exactly once from participant final.  Each product is rounded half-even to
    nine fractional digits before values are summed.
    """

    validate_record(participant_record)
    if participant_record["kind"] != KIND_PARTICIPANT_SUMMARY:
        _fail("$.kind", f"must equal {KIND_PARTICIPANT_SUMMARY}")

    transient_resources = ("cpu", "memory", "gpu")
    numeric = {name: False for name in _TOTAL_FIELDS}
    degraded = {name: False for name in _TOTAL_FIELDS}
    resource_window_values: list[Decimal] = []
    cpu_values: dict[tuple[str, str], list[Decimal]] = defaultdict(list)
    cpu_templates: dict[tuple[str, str], dict[str, str]] = {}
    gpu_values: dict[tuple[str, str, str, str], list[Decimal]] = defaultdict(list)
    gpu_templates: dict[tuple[str, str, str, str], dict[str, str]] = {}
    memory_values: list[Decimal] = []
    storage_values: list[Decimal] = []

    # A completed participant lifecycle with no attempts authoritatively says
    # that no transient resource window occurred.  This is a reported zero,
    # unlike an end-only launch_failed attempt whose capacity is unobserved.
    if not participant_record["attempts"]:
        for resource in transient_resources:
            numeric[resource] = True

    for index, attempt in enumerate(participant_record["attempts"]):
        attempt_path = f"$.attempts[{index}]"
        start = attempt.get("start")
        final = attempt.get("final")
        seconds = _duration_seconds(attempt["opened_at"], attempt["end"]["closed_at"])
        resource_window_values.append(seconds)
        if start is None:
            for resource in transient_resources:
                degraded[resource] = True
        else:
            for resource in transient_resources:
                startup_resource = start["capacity"][resource]
                if startup_resource["status"] != "reported":
                    degraded[resource] = True
                    continue
                numeric[resource] = True
                final_resource = final["capacity"][resource] if final is not None else None
                if (
                    final_resource is None
                    or final_resource["status"] != "reported"
                    or _capacity_signature(resource, startup_resource) != _capacity_signature(resource, final_resource)
                ):
                    degraded[resource] = True

                if resource == "cpu":
                    key = (
                        startup_resource.get("model", ""),
                        startup_resource.get("architecture", ""),
                    )
                    cpu_templates[key] = {
                        name: startup_resource[name] for name in ("model", "architecture") if name in startup_resource
                    }
                    cpu_values[key].append(
                        _resource_product(
                            Decimal(startup_resource["visible_units"]),
                            seconds,
                            f"{attempt_path}.start.capacity.cpu",
                        )
                    )
                elif resource == "memory":
                    memory_values.append(
                        _resource_product(
                            Decimal(startup_resource["visible_bytes"]),
                            seconds,
                            f"{attempt_path}.start.capacity.memory",
                        )
                    )
                else:
                    for group in startup_resource["groups"]:
                        key = _gpu_group_key(group)
                        gpu_templates[key] = {
                            name: group[name]
                            for name in ("kind", "model", "memory_bytes", "mig_profile")
                            if name in group
                        }
                        gpu_values[key].append(
                            _resource_product(
                                Decimal(group["count"]),
                                seconds,
                                f"{attempt_path}.start.capacity.gpu.groups",
                            )
                        )

    resource_window_seconds = _canonical_decimal(
        _sum_decimals(resource_window_values, "$.resource_window_seconds")
    )

    participant_start = participant_record["start"]
    participant_final = participant_record["final"]
    storage_start = participant_start["storage"]
    storage_final = participant_final["storage"]
    if storage_start["status"] in {"reported", "partial"}:
        numeric["storage"] = True
        participant_seconds = _duration_seconds(participant_start["observed_at"], participant_final["observed_at"])
        storage_values.append(
            _resource_product(
                Decimal(storage_start["capacity_bytes"]),
                participant_seconds,
                "$.start.storage",
            )
        )
        if (
            storage_final["status"] not in {"reported", "partial"}
            or _capacity_signature("storage", storage_start) != _capacity_signature("storage", storage_final)
            or storage_start["status"] == "partial"
            or storage_final["status"] == "partial"
        ):
            degraded["storage"] = True
    else:
        degraded["storage"] = True

    retained = participant_final["retained_content"]
    retained_value = 0
    if retained["status"] in {"reported", "partial"}:
        numeric["retained_content"] = True
        retained_value = sum(int(entry["size_bytes"]) for entry in retained["entries"])
        if retained["status"] == "partial":
            degraded["retained_content"] = True
    else:
        degraded["retained_content"] = True

    f3 = participant_final["f3"]
    f3_payload = 0
    f3_messages = 0
    if f3["status"] in {"reported", "partial"}:
        numeric["f3"] = True
        f3_payload = int(f3["remote_accepted"]["payload_bytes"])
        f3_messages = int(f3["remote_accepted"]["messages"])
        if f3["status"] == "partial":
            degraded["f3"] = True
    else:
        degraded["f3"] = True

    cpu_status = _derived_status(numeric["cpu"], degraded["cpu"])
    if cpu_status == "unavailable":
        cpu_total: dict[str, Any] = {"status": cpu_status}
    else:
        cpu_groups = []
        for key in sorted(cpu_values):
            group = dict(cpu_templates[key])
            group["unit_seconds"] = _canonical_decimal(_sum_decimals(cpu_values[key], "$.totals.cpu.groups"))
            cpu_groups.append(group)
        cpu_total = {"status": cpu_status, "groups": cpu_groups}

    gpu_status = _derived_status(numeric["gpu"], degraded["gpu"])
    if gpu_status == "unavailable":
        gpu_total: dict[str, Any] = {"status": gpu_status}
    else:
        gpu_groups = []
        for key in sorted(gpu_values):
            group = dict(gpu_templates[key])
            group["instance_seconds"] = _canonical_decimal(_sum_decimals(gpu_values[key], "$.totals.gpu.groups"))
            gpu_groups.append(group)
        gpu_total = {"status": gpu_status, "groups": gpu_groups}

    def scalar_resource(resource: str, values: Sequence[Decimal]) -> dict[str, Any]:
        status = _derived_status(numeric[resource], degraded[resource])
        if status == "unavailable":
            return {"status": status}
        return {
            "status": status,
            "byte_seconds": _canonical_decimal(_sum_decimals(values, f"$.totals.{resource}.byte_seconds")),
        }

    retained_status = _derived_status(numeric["retained_content"], degraded["retained_content"])
    if retained_status == "unavailable":
        retained_total: dict[str, Any] = {"status": retained_status}
    else:
        if retained_value > U128_MAX:
            _fail("$.totals.retained_content.bytes", "derived total exceeds unsigned 128-bit bound")
        retained_total = {"status": retained_status, "bytes": str(retained_value)}

    f3_status = _derived_status(numeric["f3"], degraded["f3"])
    if f3_status == "unavailable":
        f3_total: dict[str, Any] = {"status": f3_status}
    else:
        if f3_payload > U128_MAX or f3_messages > U128_MAX:
            _fail("$.totals.f3.remote_accepted", "derived total exceeds unsigned 128-bit bound")
        f3_total = {
            "status": f3_status,
            "remote_accepted": {"payload_bytes": str(f3_payload), "messages": str(f3_messages)},
        }

    totals = {
        "cpu": cpu_total,
        "memory": scalar_resource("memory", memory_values),
        "storage": scalar_resource("storage", storage_values),
        "gpu": gpu_total,
        "retained_content": retained_total,
        "f3": f3_total,
    }
    _validate_totals(totals, "$.totals")
    return resource_window_seconds, totals


def _validate_roster_entry(value: Any, path: str, cutoff_ns: int) -> None:
    entry = _mapping(value, path)
    status = _enum(entry.get("status"), ROSTER_STATUSES, f"{path}.status")
    base = {"participant_id", "participant_key", "role", "status"}
    if status == "accepted":
        _exact_keys(
            entry,
            base | {"received_at", "summary_sha256", "resource_window_seconds", "totals"},
            set(),
            path,
        )
        received_at = _timestamp(entry["received_at"], f"{path}.received_at")
        _identifier(entry["summary_sha256"], SHA256_PATTERN, f"{path}.summary_sha256")
        _decimal(entry["resource_window_seconds"], f"{path}.resource_window_seconds")
        _validate_totals(entry["totals"], f"{path}.totals")
        if _timestamp_nanoseconds(received_at) > cutoff_ns:
            _fail(f"{path}.received_at", "must not be later than report_cutoff_at")
    elif status == "invalid":
        _exact_keys(entry, base | {"received_at", "issues"}, set(), path)
        received_at = _timestamp(entry["received_at"], f"{path}.received_at")
        if _timestamp_nanoseconds(received_at) > cutoff_ns:
            _fail(f"{path}.received_at", "must not be later than report_cutoff_at")
        issues = entry["issues"]
        if (
            not isinstance(issues, list)
            or not 1 <= len(issues) <= MAX_ISSUES
            or issues != sorted(issues)
            or len(issues) != len(set(issues))
            or set(issues) - {"malformed_source", "permission_denied"}
        ):
            _fail(f"{path}.issues", "must be a sorted non-empty invalid-report issue list")
    else:
        _exact_keys(entry, base, set(), path)
    _identifier(entry["participant_key"], HASH_KEY_PATTERN, f"{path}.participant_key")
    _identifier(entry["participant_id"], PARTICIPANT_ID_PATTERN, f"{path}.participant_id")
    _enum(entry["role"], ROLES, f"{path}.role")


def derive_job_totals(roster: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Derive job totals from one complete, fixed expected-participant roster."""

    if not isinstance(roster, list) or not 1 <= len(roster) <= MAX_PARTICIPANTS:
        _fail("roster", f"must contain 1..{MAX_PARTICIPANTS} entries")
    maximum_timestamp = _timestamp_nanoseconds("9999-12-31T23:59:59.999999999Z")
    ordering: list[tuple[str, str, str]] = []
    for index, entry in enumerate(roster):
        _validate_roster_entry(entry, f"roster[{index}]", maximum_timestamp)
        ordering.append((entry["role"], entry["participant_id"], entry["participant_key"]))
    if ordering != sorted(ordering):
        _fail("roster", "must be sorted by role, participant_id, then participant_key")
    if len({item[1] for item in ordering}) != len(ordering):
        _fail("roster", "participant_id values must be unique")
    if len({item[2] for item in ordering}) != len(ordering):
        _fail("roster", "participant_key values must be unique")
    return _expected_job_totals(roster)


def _validate_resource_summary(record: Mapping[str, Any], path: str) -> None:
    _exact_keys(
        record,
        {"schema_version", "kind", "job_id", "report_cutoff_at", "finalized_at", "roster", "totals"},
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
    roster = record["roster"]
    if not isinstance(roster, list) or not 1 <= len(roster) <= MAX_PARTICIPANTS:
        _fail(f"{path}.roster", f"must contain 1..{MAX_PARTICIPANTS} entries")
    ordering: list[tuple[str, str, str]] = []
    for index, entry in enumerate(roster):
        _validate_roster_entry(entry, f"{path}.roster[{index}]", cutoff_ns)
        ordering.append((entry["role"], entry["participant_id"], entry["participant_key"]))
    if ordering != sorted(ordering):
        _fail(f"{path}.roster", "must be sorted by role, participant_id, then participant_key")
    if len({item[1] for item in ordering}) != len(ordering):
        _fail(f"{path}.roster", "participant_id values must be unique")
    if len({item[2] for item in ordering}) != len(ordering):
        _fail(f"{path}.roster", "participant_key values must be unique")
    _validate_totals(record["totals"], f"{path}.totals")
    expected = derive_job_totals(roster)
    if record["totals"] != expected:
        _fail(f"{path}.totals", "must exactly equal the deterministic sum and coverage state of the roster")


_PARTICIPANT_MANIFEST_PATH = re.compile(r"^participants/sha256-[0-9a-f]{64}\.json$")


def _validate_manifest(record: Mapping[str, Any], path: str) -> None:
    _exact_keys(record, {"schema_version", "kind", "job_id", "entries"}, set(), path)
    if record["schema_version"] != SCHEMA_VERSION:
        _fail(f"{path}.schema_version", f"must equal {SCHEMA_VERSION}")
    _identifier(record["job_id"], JOB_ID_PATTERN, f"{path}.job_id")
    entries = record["entries"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_PARTICIPANTS + 1:
        _fail(f"{path}.entries", f"must contain 1..{MAX_PARTICIPANTS + 1} entries")
    paths: list[str] = []
    for index, entry_value in enumerate(entries):
        item_path = f"{path}.entries[{index}]"
        entry = _mapping(entry_value, item_path)
        _exact_keys(entry, {"relative_path", "sha256"}, set(), item_path)
        relative_path = _relative_path(entry["relative_path"], f"{item_path}.relative_path")
        if relative_path != "resource_summary.json" and not _PARTICIPANT_MANIFEST_PATH.fullmatch(relative_path):
            _fail(
                f"{item_path}.relative_path",
                "must identify resource_summary.json or a participant summary by participant_key",
            )
        paths.append(relative_path)
        _identifier(entry["sha256"], SHA256_PATTERN, f"{item_path}.sha256")
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        _fail(f"{path}.entries", "must be sorted by unique relative_path")
    if paths.count("resource_summary.json") != 1:
        _fail(f"{path}.entries", "must contain exactly one resource_summary.json entry")


def validate_record(record: Mapping[str, Any], *, serialized_size: int | None = None) -> None:
    """Validate one already-decoded canonical record.

    ``serialized_size`` should be supplied by callers that received serialized
    bytes.  ``load_and_validate`` supplies it automatically.
    """

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

    validators = {
        KIND_ATTEMPT_START: _validate_attempt_start,
        KIND_ATTEMPT_FINAL: _validate_attempt_final,
        KIND_ATTEMPT_END: _validate_attempt_end,
        KIND_PARTICIPANT_START: _validate_participant_start,
        KIND_PARTICIPANT_FINAL: _validate_participant_final,
        KIND_PARTICIPANT_SUMMARY: _validate_participant_summary,
        KIND_RESOURCE_SUMMARY: _validate_resource_summary,
        KIND_MANIFEST: _validate_manifest,
    }
    validators[kind](record, "$")


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
        record = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except ContractError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise ContractError(f"$: invalid JSON: {exc}") from exc
    if not isinstance(record, dict):
        _fail("$", "record must be a JSON object")
    validate_record(record, serialized_size=len(data))
    return record


def validate_bundle(
    resource_summary: Mapping[str, Any],
    participant_records: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
    file_bytes: Mapping[str, bytes],
) -> None:
    """Validate one finalized archive, including exact-byte digest relationships.

    ``participant_records`` is keyed by participant_key. ``file_bytes`` contains
    the exact archived bytes for ``resource_summary.json`` and every accepted
    ``participants/<participant_key>.json`` file. The manifest itself is not an
    entry in its own digest list.
    """

    validate_record(resource_summary)
    if resource_summary["kind"] != KIND_RESOURCE_SUMMARY:
        _fail("resource_summary.kind", f"must equal {KIND_RESOURCE_SUMMARY}")
    validate_record(manifest)
    if manifest["kind"] != KIND_MANIFEST:
        _fail("manifest.kind", f"must equal {KIND_MANIFEST}")
    if manifest["job_id"] != resource_summary["job_id"]:
        _fail("manifest.job_id", "must equal resource_summary.job_id")
    if not isinstance(participant_records, Mapping):
        _fail("participant_records", "must be a participant_key-to-record mapping")
    if not isinstance(file_bytes, Mapping):
        _fail("file_bytes", "must be a relative-path-to-bytes mapping")

    accepted = {
        entry["participant_key"]: entry for entry in resource_summary["roster"] if entry["status"] == "accepted"
    }
    if set(participant_records) != set(accepted):
        _fail(
            "participant_records",
            "keys must exactly equal the accepted participant keys in the fixed roster",
        )

    expected_paths = {"resource_summary.json"} | {
        f"participants/{participant_key}.json" for participant_key in accepted
    }
    manifest_entries = {entry["relative_path"]: entry["sha256"] for entry in manifest["entries"]}
    if set(manifest_entries) != expected_paths:
        _fail("manifest.entries", "paths must exactly cover the summary and accepted participant records")
    if set(file_bytes) != expected_paths:
        _fail("file_bytes", "paths must exactly match manifest.entries")

    decoded_summary: Mapping[str, Any] | None = None
    decoded_participants: dict[str, Mapping[str, Any]] = {}
    for relative_path in sorted(expected_paths):
        data = file_bytes[relative_path]
        if not isinstance(data, bytes):
            _fail(f"file_bytes[{relative_path!r}]", "must be exact bytes")
        digest = hashlib.sha256(data).hexdigest()
        if digest != manifest_entries[relative_path]:
            _fail(f"manifest.entries[{relative_path!r}].sha256", "does not match archived bytes")
        decoded = load_and_validate(data)
        if relative_path == "resource_summary.json":
            decoded_summary = decoded
        else:
            participant_key = relative_path.removeprefix("participants/").removesuffix(".json")
            decoded_participants[participant_key] = decoded

    if decoded_summary != resource_summary:
        _fail("resource_summary", "does not equal the exact decoded archived record")

    environment_intervals: dict[str, list[tuple[int, int, str, str]]] = defaultdict(list)
    for participant_key, record in participant_records.items():
        _identifier(participant_key, HASH_KEY_PATTERN, f"participant_records[{participant_key!r}]")
        validate_record(record)
        if record["kind"] != KIND_PARTICIPANT_SUMMARY:
            _fail(
                f"participant_records[{participant_key!r}].kind",
                f"must equal {KIND_PARTICIPANT_SUMMARY}",
            )
        if record["participant_key"] != participant_key:
            _fail(
                f"participant_records[{participant_key!r}].participant_key",
                "must equal its mapping key",
            )
        if record["job_id"] != resource_summary["job_id"]:
            _fail(f"participant_records[{participant_key!r}].job_id", "must equal summary job_id")
        if decoded_participants.get(participant_key) != record:
            _fail(
                f"participant_records[{participant_key!r}]",
                "does not equal the exact decoded archived record",
            )
        relative_path = f"participants/{participant_key}.json"
        digest = hashlib.sha256(file_bytes[relative_path]).hexdigest()
        roster_entry = accepted[participant_key]
        if roster_entry["summary_sha256"] != digest:
            _fail(
                f"resource_summary.roster[{participant_key!r}].summary_sha256",
                "does not match the accepted participant bytes",
            )
        resource_window_seconds, totals = derive_participant_totals(record)
        if roster_entry["resource_window_seconds"] != resource_window_seconds:
            _fail(
                f"resource_summary.roster[{participant_key!r}].resource_window_seconds",
                "does not equal the lifecycle-derived resource-window interval sum",
            )
        if roster_entry["totals"] != totals:
            _fail(
                f"resource_summary.roster[{participant_key!r}].totals",
                "does not equal startup capacity multiplied by the derived intervals",
            )
        for attempt in record["attempts"]:
            environment_intervals[attempt["environment_key"]].append(
                (
                    _timestamp_nanoseconds(attempt["opened_at"]),
                    _timestamp_nanoseconds(attempt["end"]["closed_at"]),
                    participant_key,
                    attempt["attempt_id"],
                )
            )

    for environment_key, intervals in environment_intervals.items():
        intervals.sort()
        previous = intervals[0]
        for current in intervals[1:]:
            if current[0] < previous[1]:
                _fail(
                    "participant_records",
                    "overlapping trusted reporters for environment "
                    f"{environment_key}: {previous[2]}/{previous[3]} and {current[2]}/{current[3]}",
                )
            previous = current
