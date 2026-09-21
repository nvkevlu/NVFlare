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

"""Collect one final resource-statistics report in an NVFlare job process.

The public record contains seconds, not raw clock readings.  A monotonic
nanosecond clock is used only inside the process so elapsed intervals can be
subtracted exactly without depending on wall-clock adjustments.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import datetime
import importlib.metadata as importlib_metadata
import json
import os
import platform
import re
import stat
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any, Optional

from .contract import MAX_PARTICIPANT_SUMMARY_BYTES, ContractError
from .contract import canonical_json_bytes as _contract_json_bytes
from .contract import normalize_quota_units, validate_record

INTERNAL_HANDOFF_VERSION = "1"
INTERNAL_HANDOFF_KIND = "nvflare.resource_stats.internal.terminal_handoff"
MAX_TERMINAL_HANDOFF_BYTES = MAX_PARTICIPANT_SUMMARY_BYTES

RESOURCE_STATS_DIR = "resource_stats"
STAGING_DIR = "staging"
TERMINAL_HANDOFF_FILE = "terminal_handoff.json"
_DIRECTORY_OPEN_FLAGS = (
    os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
)
_SECURE_HANDOFF_DIR_FD = (
    hasattr(os, "O_NOFOLLOW")
    and bool(getattr(os, "O_DIRECTORY", 0))
    and os.open in os.supports_dir_fd
    and os.unlink in os.supports_dir_fd
    and os.rmdir in os.supports_dir_fd
)

_GPU_KINDS = frozenset({"full_gpu", "mig_compute_instance"})
_SLURM_NODE_COUNT_ENV = "NVFL_NNODES"
_MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+/@-]{0,127}$")
_ARCH_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
_CGROUP_FILE_MISSING = object()
_CGROUP_FILE_UNREADABLE = object()
_V1_MEMORY_UNLIMITED_MIN = 1 << 60
_CUDA_RUNTIME_DISTRIBUTION_PATTERN = re.compile(r"^nvidia-cuda-runtime(?:-cu\d+)?$")
_LINUX_CUDA_RUNTIME_FILE_PATTERN = re.compile(r"^libcudart\.so(?:\.\d+)*$")
_WINDOWS_CUDA_RUNTIME_FILE_PATTERN = re.compile(r"^cudart64_\d+\.dll$", re.IGNORECASE)


def _freeze_distribution_roots() -> tuple[str, ...]:
    """Capture the official launcher's import roots before job paths are enabled."""

    roots = []
    for value in sys.path:
        if not value or not os.path.isabs(value):
            continue
        try:
            path = Path(value).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if path.is_dir() and str(path) not in roots:
            roots.append(str(path))
    return tuple(roots)


_FROZEN_DISTRIBUTION_ROOTS = _freeze_distribution_roots()

CapacitySnapshot = Mapping[str, Any]
CapacityProbe = Callable[[], CapacitySnapshot]


class CollectorClosedError(RuntimeError):
    """Raised when a closed collector receives another observation."""


class ClockOrderError(RuntimeError):
    """Raised when an injected monotonic clock moves backwards."""


class InvalidTerminalHandoff(ValueError):
    """Raised when the child-to-parent handoff is malformed or oversized."""


def utc_now() -> str:
    """Return a schema-compatible UTC wall-clock timestamp."""

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Serialize a record deterministically while keeping stored files readable."""

    return _contract_json_bytes(value)


def _decimal(value: object, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a decimal value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be a decimal value") from exc
    if not result.is_finite() or result < 0 or (positive and result <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{label} must be a finite {qualifier} decimal value")
    return result


def _decimal_text(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = 100
        if value.as_tuple().exponent < -9:
            value = value.quantize(Decimal("0.000000001"), rounding=ROUND_HALF_EVEN)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _seconds_from_ns(value: int) -> Decimal:
    with localcontext() as context:
        context.prec = 100
        return Decimal(value) / Decimal(1_000_000_000)


def _normalize_model(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.encode("ascii", errors="ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9 ._()+/@-]+", " ", value)
    value = " ".join(value.split())[:128].rstrip()
    if value and _MODEL_PATTERN.fullmatch(value):
        return value
    return None


def _normalize_architecture(value: object) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if _ARCH_PATTERN.fullmatch(value) else None


class ResourceTimeAccumulator:
    """Integrate runtime-visible capacity using private monotonic readings.

    ``observe`` closes the preceding interval and starts a new one.  Current
    NVFlare launchers call it once at process startup.  A scheduler that later
    changes resources can call it again at each confirmed change; the public
    schema does not need to change.
    """

    def __init__(self, clock_ns: Callable[[], int] = time.monotonic_ns):
        if not callable(clock_ns):
            raise TypeError("clock_ns must be callable")
        self._clock_ns = clock_ns
        self._last_ns: Optional[int] = None
        self._capacity: Optional[dict[str, Any]] = None
        self._closed = False
        self._measured_seconds = Decimal(0)
        self._cpu: dict[tuple[Optional[str], Optional[str]], Decimal] = {}
        self._memory_byte_seconds = Decimal(0)
        self._memory_observed = False
        self._gpu: dict[tuple[str, Optional[str], Optional[str], Optional[str]], Decimal] = {}
        self._gpu_observed = False
        self._issues: set[str] = set()

    def observe(self, capacity: Mapping[str, Any]) -> None:
        """Record the current capacity at the collector's monotonic time."""

        self._ensure_open()
        now_ns = self._read_clock()
        self._advance(now_ns)
        self._capacity = self._normalize_capacity(capacity)

    def mark_gap(self) -> None:
        """Close the prior interval and mark later capacity as unknown."""

        self._ensure_open()
        self._advance(self._read_clock())
        self._capacity = None
        self._issues.add("observation_incomplete")

    def mark_prior_observation_incomplete(self) -> None:
        """Record that this process cannot account for an earlier job interval."""

        self._ensure_open()
        self._issues.add("observation_incomplete")

    def finish(self) -> dict[str, Any]:
        """Close the final interval and return the public resource-time object."""

        self._ensure_open()
        self._advance(self._read_clock())
        self._closed = True
        return self.resource_time()

    def resource_time(self) -> dict[str, Any]:
        body: dict[str, Any] = {}
        cpu_groups = []
        for (model, architecture), unit_seconds in sorted(
            self._cpu.items(), key=lambda item: ((item[0][0] or ""), (item[0][1] or ""))
        ):
            group = {"unit_seconds": _decimal_text(unit_seconds)}
            if model:
                group["model"] = model
            if architecture:
                group["architecture"] = architecture
            cpu_groups.append(group)

        gpu_groups = []
        for (kind, model, memory_bytes, mig_profile), instance_seconds in sorted(
            self._gpu.items(), key=lambda item: tuple(value or "" for value in item[0])
        ):
            group = {"kind": kind, "instance_seconds": _decimal_text(instance_seconds)}
            if model:
                group["model"] = model
            if memory_bytes:
                group["memory_bytes"] = memory_bytes
            if mig_profile:
                group["mig_profile"] = mig_profile
            gpu_groups.append(group)

        if self._measured_seconds > 0:
            body["measured_seconds"] = _decimal_text(self._measured_seconds)
        if cpu_groups:
            body["cpu"] = {"groups": cpu_groups}
        if self._memory_observed:
            body["memory"] = {"byte_seconds": _decimal_text(self._memory_byte_seconds)}
        if self._gpu_observed:
            body["gpu"] = {"groups": gpu_groups}

        has_numeric = any(name in body for name in ("measured_seconds", "cpu", "memory", "gpu"))
        if not has_numeric:
            return {"status": "unavailable", "issues": sorted(self._issues or {"observation_incomplete"})}
        if self._issues:
            return {"status": "partial", "issues": sorted(self._issues), **body}
        return {"status": "reported", **body}

    def _read_clock(self) -> int:
        value = self._clock_ns()
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise TypeError("clock_ns must return a non-negative integer")
        return value

    def _ensure_open(self) -> None:
        if self._closed:
            raise CollectorClosedError("resource accounting is already closed")

    def _advance(self, now_ns: int) -> None:
        if self._last_ns is None:
            self._last_ns = now_ns
            return
        if now_ns < self._last_ns:
            raise ClockOrderError("the monotonic clock moved backwards")
        elapsed_ns = now_ns - self._last_ns
        if elapsed_ns:
            duration = _seconds_from_ns(elapsed_ns)
            if self._capacity is None:
                self._issues.add("observation_incomplete")
            else:
                self._account(duration, self._capacity)
        self._last_ns = now_ns

    def _account(self, duration: Decimal, capacity: Mapping[str, Any]) -> None:
        self._measured_seconds = self._add_product(self._measured_seconds, Decimal(1), duration)
        cpu = capacity.get("cpu")
        if cpu is None:
            self._issues.add("observation_incomplete")
        else:
            for group in cpu["groups"]:
                key = (group.get("model"), group.get("architecture"))
                self._cpu[key] = self._add_product(self._cpu.get(key, Decimal(0)), group["units"], duration)

        memory = capacity.get("memory")
        if memory is None:
            self._issues.add("observation_incomplete")
        else:
            self._memory_observed = True
            self._memory_byte_seconds = self._add_product(self._memory_byte_seconds, memory["bytes"], duration)

        gpu = capacity.get("gpu")
        if gpu is None:
            self._issues.add("observation_incomplete")
        else:
            self._gpu_observed = True
            for group in gpu["groups"]:
                key = (
                    group["kind"],
                    group.get("model"),
                    group.get("memory_bytes"),
                    group.get("mig_profile"),
                )
                self._gpu[key] = self._add_product(self._gpu.get(key, Decimal(0)), group["count"], duration)

    @staticmethod
    def _add_product(current: Decimal, capacity: Decimal, duration: Decimal) -> Decimal:
        with localcontext() as context:
            context.prec = 100
            product = capacity * duration
            if product.as_tuple().exponent < -9:
                product = product.quantize(Decimal("0.000000001"), rounding=ROUND_HALF_EVEN)
            return current + product

    @staticmethod
    def _normalize_capacity(capacity: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(capacity, Mapping):
            raise TypeError("capacity must be a mapping")
        if set(capacity) - {"cpu", "memory", "gpu"}:
            raise ValueError("capacity has unsupported fields")
        result: dict[str, Any] = {}
        if capacity.get("cpu") is not None:
            cpu = capacity["cpu"]
            if not isinstance(cpu, Mapping):
                raise TypeError("cpu capacity must be an object")
            raw_groups = cpu.get("groups")
            if raw_groups is None:
                raw_groups = [cpu]
            if not isinstance(raw_groups, list) or not raw_groups:
                raise TypeError("cpu.groups must be a non-empty list")
            groups = []
            for index, raw in enumerate(raw_groups):
                if not isinstance(raw, Mapping):
                    raise TypeError(f"cpu.groups[{index}] must be an object")
                group = {
                    "units": _decimal(raw.get("units"), f"cpu.groups[{index}].units", positive=True),
                    "model": _normalize_model(raw.get("model")),
                    "architecture": _normalize_architecture(raw.get("architecture")),
                }
                groups.append(group)
            result["cpu"] = {"groups": groups}
        if capacity.get("memory") is not None:
            memory = capacity["memory"]
            if not isinstance(memory, Mapping):
                raise TypeError("memory capacity must be an object")
            result["memory"] = {"bytes": _decimal(memory.get("bytes"), "memory.bytes", positive=True)}
        if capacity.get("gpu") is not None:
            gpu = capacity["gpu"]
            if not isinstance(gpu, Mapping) or not isinstance(gpu.get("groups"), list):
                raise TypeError("gpu.groups must be a list")
            groups = []
            for index, raw in enumerate(gpu["groups"]):
                if not isinstance(raw, Mapping) or raw.get("kind") not in _GPU_KINDS:
                    raise ValueError(f"gpu.groups[{index}] has an unsupported kind")
                group: dict[str, Any] = {
                    "kind": raw["kind"],
                    "count": _decimal(raw.get("count"), f"gpu.groups[{index}].count", positive=True),
                }
                model = _normalize_model(raw.get("model"))
                if model:
                    group["model"] = model
                if raw.get("memory_bytes") is not None:
                    group["memory_bytes"] = _decimal_text(
                        _decimal(raw["memory_bytes"], f"gpu.groups[{index}].memory_bytes", positive=True)
                    )
                mig_profile = raw.get("mig_profile")
                if isinstance(mig_profile, str) and mig_profile:
                    group["mig_profile"] = mig_profile
                groups.append(group)
            result["gpu"] = {"groups": groups}
        return result


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _read_cgroup_file(path: Path) -> str | object:
    """Read a cgroup file without conflating absence and unreadability."""

    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return _CGROUP_FILE_MISSING
    except (OSError, UnicodeError):
        return _CGROUP_FILE_UNREADABLE


def _is_v1_memory_unlimited(limit: int, page_size: int) -> bool:
    """Recognize the page-aligned LONG_MAX sentinel emitted by cgroup v1."""

    if page_size <= 0:
        return False
    long_max = (1 << (ctypes.sizeof(ctypes.c_long) * 8 - 1)) - 1
    return limit == (long_max // page_size) * page_size


def _decode_mountinfo(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def _mount_entries() -> list[dict[str, str]]:
    text = _read_text(Path("/proc/self/mountinfo"))
    if text is None:
        return []
    entries = []
    for line in text.splitlines():
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        left = before.split()
        right = after.split()
        if len(left) >= 5 and len(right) >= 3:
            entries.append(
                {
                    "root": _decode_mountinfo(left[3]),
                    "mount_point": _decode_mountinfo(left[4]),
                    "fs_type": right[0],
                    "super_options": right[2],
                }
            )
    return entries


def _cgroup_records() -> list[tuple[list[str], str]]:
    text = _read_text(Path("/proc/self/cgroup"))
    if text is None:
        return []
    records = []
    for line in text.splitlines():
        _hierarchy, separator, remainder = line.partition(":")
        if not separator:
            continue
        controllers, separator, relative_path = remainder.partition(":")
        if separator:
            records.append((controllers.split(",") if controllers else [], relative_path))
    return records


def _path_under_mount(mount: Mapping[str, str], cgroup_path: str) -> Optional[Path]:
    root = mount["root"].rstrip("/") or "/"
    relative = cgroup_path
    if root != "/":
        if relative == root:
            relative = ""
        elif relative.startswith(root + "/"):
            relative = relative[len(root) :]
        else:
            return None
    return Path(mount["mount_point"]) / relative.lstrip("/")


def _cgroup_location(controller: Optional[str]) -> tuple[Optional[Path], Optional[Path], str]:
    records = _cgroup_records()
    mounts = _mount_entries()
    if controller is None:
        path = next((value for controllers, value in records if not controllers), None)
        mount = next((value for value in mounts if value["fs_type"] == "cgroup2"), None)
        if path is not None and mount is not None:
            return Path(mount["mount_point"]), _path_under_mount(mount, path), "v2"
        return None, None, "none"

    path = next((value for controllers, value in records if controller in controllers), None)
    if path is not None:
        for mount in mounts:
            if mount["fs_type"] == "cgroup" and controller in set(mount["super_options"].split(",")):
                return Path(mount["mount_point"]), _path_under_mount(mount, path), "v1"
    return None, None, "none"


def _ancestors(directory: Path, mount_point: Path) -> list[Path]:
    if directory != mount_point and mount_point not in directory.parents:
        return []
    result = []
    current = directory
    while True:
        result.append(current)
        if current == mount_point:
            return result
        if current.parent == current:
            return []
        current = current.parent


def _parse_cpu_list(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    intervals = []
    for token in value.split(","):
        match = re.fullmatch(r"\s*([0-9]+)(?:-([0-9]+))?\s*", token)
        if not match:
            return None
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        if end < start:
            return None
        intervals.append((start, end))
    intervals.sort()
    merged: list[list[int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1] + 1:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    count = sum(end - start + 1 for start, end in merged)
    return count if 0 < count <= 2**32 - 1 else None


def _cpu_identity(affinity: Optional[set[int]]) -> dict[str, str]:
    result = {}
    architecture = _normalize_architecture(platform.machine())
    if architecture:
        result["architecture"] = architecture
    if not affinity:
        return result
    text = _read_text(Path("/proc/cpuinfo"))
    if not text:
        return result
    models_by_cpu: dict[int, set[str]] = {}
    for block in re.split(r"\n\s*\n", text):
        processor_id = None
        model = None
        for line in block.splitlines():
            key, separator, raw_value = line.partition(":")
            if not separator:
                continue
            key = key.strip().lower()
            raw_value = raw_value.strip()
            if key == "processor" and raw_value.isdigit():
                processor_id = int(raw_value)
            elif key in ("model name", "cpu model"):
                model = _normalize_model(raw_value)
        if processor_id is not None and model:
            models_by_cpu.setdefault(processor_id, set()).add(model)
    selected = []
    for cpu_id in affinity:
        models = models_by_cpu.get(cpu_id)
        if not models or len(models) != 1:
            return result
        selected.append(next(iter(models)))
    if len(set(selected)) == 1:
        result["model"] = selected[0]
    return result


def _heterogeneous_cpu_groups(affinity: Optional[set[int]]) -> Optional[list[dict[str, Any]]]:
    """Group affinity-visible logical CPUs only when every model is known."""

    if not affinity:
        return None
    text = _read_text(Path("/proc/cpuinfo"))
    if not text:
        return None
    architecture = _normalize_architecture(platform.machine())
    model_by_cpu = {}
    for block in re.split(r"\n\s*\n", text):
        processor_id = None
        model = None
        for line in block.splitlines():
            key, separator, raw_value = line.partition(":")
            if not separator:
                continue
            key = key.strip().lower()
            raw_value = raw_value.strip()
            if key == "processor" and raw_value.isdigit():
                processor_id = int(raw_value)
            elif key in ("model name", "cpu model"):
                model = _normalize_model(raw_value)
        if processor_id is not None and model:
            model_by_cpu[processor_id] = model
    if any(cpu_id not in model_by_cpu for cpu_id in affinity):
        return None
    counts: dict[str, int] = {}
    for cpu_id in affinity:
        model = model_by_cpu[cpu_id]
        counts[model] = counts.get(model, 0) + 1
    return [
        {
            "units": str(counts[model]),
            "model": model,
            **({"architecture": architecture} if architecture else {}),
        }
        for model in sorted(counts)
    ]


def probe_cpu() -> Optional[dict[str, Any]]:
    """Return the narrowest runtime-visible CPU capacity on Linux."""

    if platform.system() != "Linux":
        return None
    try:
        affinity = set(os.sched_getaffinity(0))
        affinity_count = len(affinity) or None
    except (AttributeError, OSError):
        affinity = None
        affinity_count = None

    candidates: list[Decimal] = []
    if affinity_count:
        candidates.append(Decimal(affinity_count))

    mount, directory, version = _cgroup_location(None)
    if directory is not None and mount is not None:
        for path in _ancestors(directory, mount):
            value = _read_cgroup_file(path / "cpuset.cpus.effective")
            if value is _CGROUP_FILE_UNREADABLE:
                return None
            if value is not _CGROUP_FILE_MISSING:
                count = _parse_cpu_list(value)
                if count is None:
                    return None
                candidates.append(Decimal(count))
        for path in _ancestors(directory, mount):
            value = _read_cgroup_file(path / "cpu.max")
            if value is _CGROUP_FILE_UNREADABLE:
                return None
            if value is _CGROUP_FILE_MISSING:
                continue
            tokens = value.split()
            if len(tokens) != 2:
                return None
            try:
                period = int(tokens[1])
            except ValueError:
                return None
            if period <= 0:
                return None
            if tokens[0] != "max":
                try:
                    quota = int(tokens[0])
                except ValueError:
                    return None
                if quota <= 0:
                    return None
                try:
                    candidates.append(Decimal(normalize_quota_units(quota, period)))
                except ValueError:
                    return None
    else:
        mount, directory, version = _cgroup_location("cpuset")
        if directory is not None and mount is not None:
            for path in _ancestors(directory, mount):
                effective = _read_cgroup_file(path / "cpuset.effective_cpus")
                if effective is _CGROUP_FILE_UNREADABLE:
                    return None
                value = effective
                if effective is _CGROUP_FILE_MISSING:
                    value = _read_cgroup_file(path / "cpuset.cpus")
                    if value is _CGROUP_FILE_UNREADABLE:
                        return None
                if value is not _CGROUP_FILE_MISSING:
                    count = _parse_cpu_list(value)
                    if count is None:
                        return None
                    candidates.append(Decimal(count))
        quota_mount, quota_dir, _ = _cgroup_location("cpu")
        if quota_dir is not None and quota_mount is not None:
            for path in _ancestors(quota_dir, quota_mount):
                quota_value = _read_cgroup_file(path / "cpu.cfs_quota_us")
                period_value = _read_cgroup_file(path / "cpu.cfs_period_us")
                if _CGROUP_FILE_UNREADABLE in (quota_value, period_value):
                    return None
                if quota_value is _CGROUP_FILE_MISSING and period_value is _CGROUP_FILE_MISSING:
                    continue
                if _CGROUP_FILE_MISSING in (quota_value, period_value):
                    return None
                try:
                    quota = int(quota_value)
                    period = int(period_value)
                except ValueError:
                    return None
                if period <= 0 or quota == 0 or quota < -1:
                    return None
                if quota == -1:
                    continue
                try:
                    candidates.append(Decimal(normalize_quota_units(quota, period)))
                except ValueError:
                    return None

    if not candidates:
        try:
            online = os.sysconf("SC_NPROCESSORS_ONLN")
        except (AttributeError, OSError, ValueError):
            online = os.cpu_count()
        if isinstance(online, int) and online > 0:
            candidates.append(Decimal(online))
    if not candidates:
        return None

    selected = min(candidates)
    if affinity_count is not None and selected == Decimal(affinity_count):
        groups = _heterogeneous_cpu_groups(affinity)
        if groups:
            return {"groups": groups}
    group: dict[str, Any] = {"units": _decimal_text(selected)}
    group.update(_cpu_identity(affinity))
    return {"groups": [group]}


def probe_memory() -> Optional[dict[str, str]]:
    """Return the narrowest positive physical/cgroup memory capacity."""

    if platform.system() != "Linux":
        return None
    candidates = []
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        physical = page_size * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        page_size = 0
        physical = 0
    if isinstance(physical, int) and physical > 0:
        candidates.append(physical)

    mount, directory, _version = _cgroup_location(None)
    if directory is not None and mount is not None:
        for path in _ancestors(directory, mount):
            value = _read_cgroup_file(path / "memory.max")
            if value is _CGROUP_FILE_UNREADABLE:
                return None
            if value is _CGROUP_FILE_MISSING or value == "max":
                continue
            try:
                limit = int(value)
            except ValueError:
                return None
            if limit <= 0:
                return None
            candidates.append(limit)
    else:
        mount, directory, _version = _cgroup_location("memory")
        if directory is not None and mount is not None:
            for path in _ancestors(directory, mount):
                value = _read_cgroup_file(path / "memory.limit_in_bytes")
                if value is _CGROUP_FILE_UNREADABLE:
                    return None
                if value is _CGROUP_FILE_MISSING:
                    continue
                try:
                    limit = int(value)
                except ValueError:
                    return None
                if limit <= 0:
                    return None
                if _is_v1_memory_unlimited(limit, page_size):
                    continue
                if limit >= _V1_MEMORY_UNLIMITED_MIN:
                    return None
                candidates.append(limit)
    return {"bytes": str(min(candidates))} if candidates else None


class _CudaUuid(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_ubyte * 16)]


class _NvmlMemory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


def _load_library(candidates: list[str]):
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ctypes.CDLL(candidate)
        except OSError:
            continue
    return None


def _normalize_distribution_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[-_.]+", "-", value).lower()


def _is_bundled_cuda_runtime_file(name: str) -> bool:
    if platform.system() == "Linux":
        return bool(_LINUX_CUDA_RUNTIME_FILE_PATTERN.fullmatch(name))
    if platform.system() == "Windows":
        return bool(_WINDOWS_CUDA_RUNTIME_FILE_PATTERN.fullmatch(name))
    return False


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _find_bundled_cuda_runtime_path(
    distribution_roots: tuple[str, ...] = _FROZEN_DISTRIBUTION_ROOTS,
) -> Optional[Path]:
    """Find one CUDA Runtime file owned by an installed NVIDIA package.

    Distribution roots are frozen when this trusted module is imported.  This
    deliberately avoids importing a framework package or searching job paths.
    Multiple distinct candidates are ambiguous and fail closed.
    """

    if not distribution_roots:
        return None
    trusted_roots = []
    for value in distribution_roots:
        try:
            root = Path(value).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if root.is_dir():
            trusted_roots.append(root)
    if not trusted_roots:
        return None

    candidates = {}
    try:
        distributions = importlib_metadata.distributions(path=[str(root) for root in trusted_roots])
        for distribution in distributions:
            name = _normalize_distribution_name(distribution.metadata.get("Name", ""))
            if not _CUDA_RUNTIME_DISTRIBUTION_PATTERN.fullmatch(name):
                continue
            try:
                install_root = Path(distribution.locate_file("")).resolve(strict=True)
            except (OSError, RuntimeError, TypeError, ValueError):
                return None
            if not any(install_root == root for root in trusted_roots):
                return None
            for owned_file in distribution.files or ():
                if not _is_bundled_cuda_runtime_file(Path(owned_file).name):
                    continue
                candidate = Path(distribution.locate_file(owned_file))
                try:
                    candidate = candidate.resolve(strict=True)
                    if not _is_within(candidate, install_root):
                        return None
                    candidate_stat = candidate.stat()
                except (OSError, RuntimeError):
                    return None
                if not stat.S_ISREG(candidate_stat.st_mode) or candidate_stat.st_size <= 0:
                    return None
                identity = (candidate_stat.st_dev, candidate_stat.st_ino)
                candidates.setdefault(identity, candidate)
                if len(candidates) > 1:
                    return None
    except Exception:
        return None
    return next(iter(candidates.values())) if len(candidates) == 1 else None


def _load_bundled_cuda_runtime():
    path = _find_bundled_cuda_runtime_path()
    if path is None:
        return None
    try:
        if platform.system() == "Windows" and hasattr(os, "add_dll_directory"):
            directory_handle = os.add_dll_directory(str(path.parent))
            try:
                library = ctypes.CDLL(str(path))
                setattr(library, "_nvflare_dll_directory_handle", directory_handle)
                return library
            except Exception:
                directory_handle.close()
                raise
        mode = getattr(os, "RTLD_LOCAL", 0) | getattr(os, "RTLD_NOW", 0)
        return ctypes.CDLL(str(path), mode=mode)
    except (OSError, TypeError, ValueError):
        return None


def _cuda_runtime_device_count(cudart: Any) -> Optional[int]:
    if cudart is None:
        return None
    try:
        cuda_get_count = cudart.cudaGetDeviceCount
        cuda_get_count.argtypes = [ctypes.POINTER(ctypes.c_int)]
        cuda_get_count.restype = ctypes.c_int
        count = ctypes.c_int()
        if cuda_get_count(ctypes.byref(count)) != 0 or count.value < 0:
            return None
        return count.value
    except (AttributeError, ctypes.ArgumentError, OSError, TypeError, ValueError):
        return None


def _uuid_text(value: _CudaUuid) -> str:
    raw = bytes(value.bytes).hex()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def _cuda_uuid_reader(expected_count: int) -> Optional[Callable[[Any, int], int]]:
    """Return a CUDA UUID reader for the runtime-visible device ordinals.

    Use the Driver API v2 UUID lookup after confirming that it sees the same
    device count.  The successful Runtime API count remains the authority for
    numeric capacity.  Requiring v2 prevents a visible MIG instance from being
    identified by its parent GPU UUID on older drivers.
    """

    cuda_driver = _load_library(
        [
            ctypes.util.find_library("cuda") or "",
            "libcuda.so.1",
            "libcuda.so",
            "nvcuda.dll",
        ]
    )
    if cuda_driver is None:
        return None
    try:
        cu_init = cuda_driver.cuInit
        cu_init.argtypes = [ctypes.c_uint]
        cu_init.restype = ctypes.c_int
        cu_get_count = cuda_driver.cuDeviceGetCount
        cu_get_count.argtypes = [ctypes.POINTER(ctypes.c_int)]
        cu_get_count.restype = ctypes.c_int
        cu_get_device = cuda_driver.cuDeviceGet
        cu_get_device.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        cu_get_device.restype = ctypes.c_int
        cu_get_uuid = getattr(cuda_driver, "cuDeviceGetUuid_v2", None)
        if cu_get_uuid is None:
            return None
        cu_get_uuid.argtypes = [ctypes.POINTER(_CudaUuid), ctypes.c_int]
        cu_get_uuid.restype = ctypes.c_int
    except (AttributeError, TypeError, ValueError):
        return None

    driver_count = ctypes.c_int()
    try:
        counts_match = (
            cu_init(0) == 0 and cu_get_count(ctypes.byref(driver_count)) == 0 and driver_count.value == expected_count
        )
    except (ctypes.ArgumentError, OSError, TypeError, ValueError):
        return None
    if not counts_match:
        return None

    def read_uuid(uuid_pointer: Any, ordinal: int) -> int:
        device = ctypes.c_int()
        result = cu_get_device(ctypes.byref(device), ordinal)
        if result != 0:
            return result
        return cu_get_uuid(uuid_pointer, device.value)

    return read_uuid


def probe_gpu() -> Optional[dict[str, list[dict[str, Any]]]]:
    """Enumerate with CUDA Runtime, then classify/enrich only those devices.

    ``CUDA_VISIBLE_DEVICES`` is intentionally never parsed.  A numeric zero is
    returned only after ``cudaGetDeviceCount`` succeeds.  For a positive count,
    NVML must match every CUDA UUID so full GPUs and MIG compute instances can
    be kept in separate schema groups.  If that match cannot be established,
    the GPU member is omitted and the enclosing resource-time value is partial.
    """

    cudart = _load_library(
        [
            ctypes.util.find_library("cudart") or "",
            "libcudart.so",
            "libcudart.so.13",
            "libcudart.so.12",
            "libcudart.so.11.0",
            "cudart64_13.dll",
            "cudart64_12.dll",
            "cudart64_110.dll",
        ]
    )
    count = _cuda_runtime_device_count(cudart)
    if count is None:
        count = _cuda_runtime_device_count(_load_bundled_cuda_runtime())
    if count is None:
        return None
    if count == 0:
        return {"groups": []}

    nvml = _load_library([ctypes.util.find_library("nvidia-ml") or "", "libnvidia-ml.so.1", "nvml.dll"])
    if nvml is None:
        return None
    try:
        cuda_get_uuid = _cuda_uuid_reader(count)
        if cuda_get_uuid is None:
            return None
        nvml_init = getattr(nvml, "nvmlInit_v2", None) or getattr(nvml, "nvmlInit", None)
        if nvml_init is None:
            return None
        nvml_init.restype = ctypes.c_int
        nvml_shutdown = nvml.nvmlShutdown
        nvml_shutdown.restype = ctypes.c_int
        get_handle = nvml.nvmlDeviceGetHandleByUUID
        get_handle.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        get_handle.restype = ctypes.c_int
        is_mig = nvml.nvmlDeviceIsMigDeviceHandle
        is_mig.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
        is_mig.restype = ctypes.c_int
        get_name = nvml.nvmlDeviceGetName
        get_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint]
        get_name.restype = ctypes.c_int
        get_memory = nvml.nvmlDeviceGetMemoryInfo
        get_memory.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NvmlMemory)]
        get_memory.restype = ctypes.c_int
    except AttributeError:
        return None
    if nvml_init() != 0:
        return None

    devices = []
    try:
        for index in range(count):
            uuid_value = _CudaUuid()
            if cuda_get_uuid(ctypes.byref(uuid_value), index) != 0:
                return None
            uuid = _uuid_text(uuid_value)
            handle = ctypes.c_void_p()
            matched = False
            for prefix in ("GPU-", "MIG-"):
                if get_handle((prefix + uuid).encode("ascii"), ctypes.byref(handle)) == 0:
                    matched = True
                    break
            if not matched:
                return None
            mig_value = ctypes.c_uint()
            if is_mig(handle, ctypes.byref(mig_value)) != 0:
                return None
            name_buffer = ctypes.create_string_buffer(128)
            model = None
            if get_name(handle, name_buffer, len(name_buffer)) == 0:
                model = _normalize_model(name_buffer.value.decode("utf-8", errors="replace"))
            memory = _NvmlMemory()
            memory_bytes = str(memory.total) if get_memory(handle, ctypes.byref(memory)) == 0 and memory.total else None
            devices.append(
                {
                    "kind": "mig_compute_instance" if mig_value.value else "full_gpu",
                    "model": model,
                    "memory_bytes": memory_bytes,
                }
            )
    finally:
        nvml_shutdown()

    groups: dict[tuple[str, Optional[str], Optional[str]], dict[str, Any]] = {}
    for device in devices:
        key = (device["kind"], device["model"], device["memory_bytes"])
        group = groups.setdefault(
            key,
            {
                "kind": device["kind"],
                "count": 0,
                **({"model": device["model"]} if device["model"] else {}),
                **({"memory_bytes": device["memory_bytes"]} if device["memory_bytes"] else {}),
            },
        )
        group["count"] += 1
    return {"groups": [groups[key] for key in sorted(groups, key=lambda item: tuple(value or "" for value in item))]}


def probe_capacity() -> dict[str, Any]:
    """Return only capacity members that can be established from this process."""

    capacity = {}
    cpu = probe_cpu()
    if cpu is not None:
        capacity["cpu"] = cpu
    memory = probe_memory()
    if memory is not None:
        capacity["memory"] = memory
    gpu = probe_gpu()
    if gpu is not None:
        capacity["gpu"] = gpu
    return capacity


def observe_workspace_filesystem(workspace_path: str | Path) -> dict[str, Any]:
    """Observe only the filesystem containing the existing job workspace."""

    try:
        stats = os.statvfs(os.fspath(workspace_path))
        capacity = stats.f_blocks * stats.f_frsize
    except (OSError, TypeError, ValueError):
        return {"status": "unavailable", "issues": ["observation_incomplete"]}
    if stats.f_frsize <= 0 or stats.f_blocks <= 0 or capacity <= 0:
        return {"status": "unavailable", "issues": ["observation_incomplete"]}
    return {"status": "reported", "capacity_bytes": str(capacity)}


def _unavailable(issue: str) -> dict[str, Any]:
    return {"status": "unavailable", "issues": [issue]}


class JobResourceCollector:
    """Own one job-process accumulator and produce its terminal handoff."""

    def __init__(
        self,
        run_dir: str | Path,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        capacity_probe: CapacityProbe = probe_capacity,
        prior_observation_incomplete: bool = False,
    ):
        self.run_dir = Path(run_dir)
        raw_node_count = os.environ.get(_SLURM_NODE_COUNT_ENV)
        try:
            self._multi_node_incomplete = raw_node_count is not None and int(raw_node_count) != 1
        except ValueError:
            # This is launcher-owned evidence.  If it is malformed, do not
            # present the rank-zero observation as complete.
            self._multi_node_incomplete = _SLURM_NODE_COUNT_ENV in os.environ
        self._accumulator = ResourceTimeAccumulator(clock_ns=clock_ns)
        try:
            capacity = capacity_probe()
            if not isinstance(capacity, Mapping):
                raise TypeError("capacity probe must return a mapping")
            self._accumulator.observe(capacity)
            if prior_observation_incomplete:
                self._accumulator.mark_prior_observation_incomplete()
        except Exception:
            self._accumulator.mark_gap()

    def observe_capacity_change(self, capacity: Mapping[str, Any]) -> None:
        """Record a confirmed runtime resource change for future schedulers."""

        self._accumulator.observe(capacity)

    def finish(self) -> dict[str, Any]:
        """Build the one private child handoff at process finalization."""

        resource_time = self._accumulator.finish()
        if self._multi_node_incomplete:
            # The current Slurm worker runs the collector on rank zero only.
            # Rank-zero cgroup/CUDA values do not describe the other allocated
            # nodes, so publishing those numbers would understate the site.
            resource_time = _unavailable("unsupported")
        return {
            "internal_version": INTERNAL_HANDOFF_VERSION,
            "kind": INTERNAL_HANDOFF_KIND,
            "resource_time": resource_time,
            "workspace_filesystem": observe_workspace_filesystem(self.run_dir),
            "retained_content": _unavailable("not_bound"),
            "child_f3": _unavailable("not_bound"),
        }


def terminal_handoff_path(run_dir: str | Path) -> Path:
    return Path(run_dir) / RESOURCE_STATS_DIR / STAGING_DIR / TERMINAL_HANDOFF_FILE


def _open_handoff_directory(run_dir: str | Path, *, include_staging: bool) -> tuple[int | None, Path]:
    """Open every parent component without following an untrusted symlink."""

    root = Path(run_dir)
    components = (RESOURCE_STATS_DIR, STAGING_DIR) if include_staging else (RESOURCE_STATS_DIR,)
    target = root.joinpath(*components)
    if not _SECURE_HANDOFF_DIR_FD:
        current = root
        for component in (None, *components):
            if component is not None:
                current /= component
            mode = current.lstat().st_mode
            if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
                raise OSError(f"resource handoff path is not a plain directory: {current}")
        return None, target

    opened = []
    try:
        current_fd = os.open(root, _DIRECTORY_OPEN_FLAGS)
        opened.append(current_fd)
        for component in components:
            next_fd = os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=current_fd)
            opened.append(next_fd)
            current_fd = next_fd
        result_fd = opened.pop()
        return result_fd, target
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _validate_handoff(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "internal_version",
        "kind",
        "resource_time",
        "workspace_filesystem",
        "retained_content",
        "child_f3",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise InvalidTerminalHandoff(f"terminal handoff fields must be exactly {sorted(required)}")
    if value["internal_version"] != INTERNAL_HANDOFF_VERSION or value["kind"] != INTERNAL_HANDOFF_KIND:
        raise InvalidTerminalHandoff("terminal handoff has an unsupported version or kind")
    probe = {
        "schema_version": "1.0",
        "kind": "nvflare.resource_stats.participant_summary",
        "job_id": "handoff-validation",
        "participant_name": "handoff-validation",
        "reported_at": "1970-01-01T00:00:00Z",
        "resource_time": deepcopy(value["resource_time"]),
        "workspace_filesystem": deepcopy(value["workspace_filesystem"]),
        "retained_content": deepcopy(value["retained_content"]),
        "f3": deepcopy(value["child_f3"]),
    }
    try:
        validate_record(probe)
    except ContractError as exc:
        raise InvalidTerminalHandoff(f"terminal handoff is invalid: {exc}") from exc
    return {name: deepcopy(value[name]) for name in required}


def write_terminal_handoff(run_dir: str | Path, handoff: Mapping[str, Any]) -> Path:
    """Atomically write the child handoff under its existing job workspace."""

    validated = _validate_handoff(handoff)
    data = canonical_json_bytes(validated)
    if len(data) > MAX_TERMINAL_HANDOFF_BYTES:
        raise InvalidTerminalHandoff("terminal handoff exceeds its size limit")
    path = terminal_handoff_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".terminal-", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        return path
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def read_terminal_handoff(run_dir: str | Path) -> Optional[dict[str, Any]]:
    """Read and validate the fixed child handoff; return ``None`` if absent/bad."""

    directory_fd = None
    fd = None
    try:
        directory_fd, directory_path = _open_handoff_directory(run_dir, include_staging=True)
        # The job process owns this self-report, so treat the path as untrusted:
        # do not follow any path-component symlink and do not let a FIFO/device
        # block the parent.
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        if directory_fd is None:
            path = directory_path / TERMINAL_HANDOFF_FILE
            if not hasattr(os, "O_NOFOLLOW") and path.is_symlink():
                return None
            fd = os.open(path, flags)
        else:
            fd = os.open(TERMINAL_HANDOFF_FILE, flags, dir_fd=directory_fd)
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_TERMINAL_HANDOFF_BYTES:
            return None
        with os.fdopen(fd, "rb") as stream:
            fd = None
            data = stream.read(MAX_TERMINAL_HANDOFF_BYTES + 1)
    except OSError:
        return None
    finally:
        if fd is not None:
            os.close(fd)
        if directory_fd is not None:
            os.close(directory_fd)
    if len(data) > MAX_TERMINAL_HANDOFF_BYTES:
        return None

    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise InvalidTerminalHandoff(f"duplicate terminal handoff key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(InvalidTerminalHandoff(value)),
        )
        return _validate_handoff(value)
    except (UnicodeDecodeError, json.JSONDecodeError, InvalidTerminalHandoff, RecursionError, TypeError):
        return None


def remove_terminal_handoff(run_dir: str | Path) -> None:
    """Remove private staging data before the finalized workspace is archived."""

    directory_fd = None
    try:
        directory_fd, directory_path = _open_handoff_directory(run_dir, include_staging=True)
        if directory_fd is None:
            (directory_path / TERMINAL_HANDOFF_FILE).unlink()
        else:
            os.unlink(TERMINAL_HANDOFF_FILE, dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    except OSError:
        # Unsafe job-owned paths are left untouched.  The server's
        # final inventory check will reject any remaining staging entry.
        return
    finally:
        if directory_fd is not None:
            os.close(directory_fd)

    stats_fd = None
    try:
        stats_fd, stats_path = _open_handoff_directory(run_dir, include_staging=False)
        if stats_fd is None:
            (stats_path / STAGING_DIR).rmdir()
        else:
            os.rmdir(STAGING_DIR, dir_fd=stats_fd)
    except OSError:
        pass
    finally:
        if stats_fd is not None:
            os.close(stats_fd)


def assemble_participant_summary(
    *,
    job_id: str,
    participant_name: str,
    child_handoff: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    """Create the sole public report, binding identity in the parent process."""

    if child_handoff is None:
        resource_time = _unavailable("observation_incomplete")
        workspace_filesystem = _unavailable("observation_incomplete")
        retained_content = _unavailable("observation_incomplete")
    else:
        try:
            validated = _validate_handoff(child_handoff)
        except InvalidTerminalHandoff:
            validated = None
        if validated is None:
            resource_time = _unavailable("observation_incomplete")
            workspace_filesystem = _unavailable("observation_incomplete")
            retained_content = _unavailable("observation_incomplete")
        else:
            resource_time = validated["resource_time"]
            workspace_filesystem = validated["workspace_filesystem"]
            retained_content = validated["retained_content"]

    # Job-scoped F3 accounting is deliberately unavailable until the sender
    # hook has authoritative job attribution and summary-message exclusion.
    f3 = _unavailable("not_bound")
    report = {
        "schema_version": "1.0",
        "kind": "nvflare.resource_stats.participant_summary",
        "job_id": job_id,
        "participant_name": participant_name,
        "reported_at": utc_now(),
        "resource_time": resource_time,
        "workspace_filesystem": workspace_filesystem,
        "retained_content": retained_content,
        "f3": f3,
    }
    validate_record(report)
    return report
