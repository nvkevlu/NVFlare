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

"""Pure capacity-observation recording: no I/O or platform knowledge.

The public record contains seconds, not raw clock readings.  A monotonic
nanosecond clock is used only inside the process so elapsed intervals can be
subtracted exactly without depending on wall-clock adjustments.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from decimal import Decimal, localcontext
from typing import Any, Optional

from .contract import GPU_KINDS, MAX_CAPACITY_INTERVALS, MAX_GPU_GROUPS, capacity_to_resource_time
from .probes._shared import _decimal, _decimal_text, _normalize_architecture, _normalize_model


def _seconds_from_ns(value: int) -> Decimal:
    with localcontext() as context:
        context.prec = 100
        return Decimal(value) / Decimal(1_000_000_000)


class CollectorClosedError(RuntimeError):
    """Raised when a closed collector receives another observation."""


class ClockOrderError(RuntimeError):
    """Raised when an injected monotonic clock moves backwards."""


class ResourceCapacityRecorder:
    """Keep raw capacity and its covered duration until the final report.

    Normal launchers observe once. Capacity-change hooks close an interval
    only when capacity changes; unknown gaps are excluded and marked partial.
    """

    def __init__(self, clock_ns: Callable[[], int] = time.monotonic_ns):
        if not callable(clock_ns):
            raise TypeError("clock_ns must be callable")
        self._clock_ns = clock_ns
        self._last_ns: Optional[int] = None
        self._capacity: Optional[dict[str, Any]] = None
        self._closed = False
        self._intervals: list[dict[str, Any]] = []
        self._issues: set[str] = set()

    def observe(self, capacity: Mapping[str, Any]) -> None:
        self._ensure_open()
        if not isinstance(capacity, Mapping):
            raise TypeError("capacity must be a mapping")
        if set(capacity) - {"cpu", "memory", "gpu", "status", "issues"}:
            raise ValueError("capacity has unsupported fields")
        dimensions = {name: capacity[name] for name in ("cpu", "memory", "gpu") if name in capacity}
        normalized = self._public_capacity(self._normalize_capacity(dimensions))
        probe = {"measured_seconds": "0", **normalized}
        if "status" in capacity or "issues" in capacity:
            probe.update({name: capacity[name] for name in ("status", "issues") if name in capacity})
        elif not all(name in normalized for name in ("cpu", "memory", "gpu")):
            probe.update(status="partial", issues=["observation_incomplete"])
        capacity_to_resource_time(probe)
        self._advance(self._read_clock())
        self._capacity = normalized
        self._issues.update(probe.get("issues", []))

    def mark_gap(self) -> None:
        self._ensure_open()
        self._advance(self._read_clock())
        self._capacity = None
        self._issues.add("observation_incomplete")

    def mark_prior_observation_incomplete(self) -> None:
        self._ensure_open()
        self._issues.add("observation_incomplete")

    def finish(self) -> dict[str, Any]:
        self._ensure_open()
        self._advance(self._read_clock())
        self._closed = True
        return self.resource_capacity()

    def resource_capacity(self) -> dict[str, Any]:
        intervals = self._intervals
        if not intervals:
            if self._capacity is None:
                return {"status": "unavailable", "issues": sorted(self._issues or {"observation_incomplete"})}
            intervals = [{"measured_seconds": "0", **self._capacity}]
        with localcontext() as context:
            context.prec = 100
            duration = sum((Decimal(item["measured_seconds"]) for item in intervals), Decimal(0))
        body = {"measured_seconds": _decimal_text(duration)}
        if len(intervals) == 1:
            body.update(intervals[0])
        else:
            body["intervals"] = intervals
        if any(not all(name in item for name in ("cpu", "memory", "gpu")) for item in intervals):
            self._issues.add("observation_incomplete")
        if self._issues:
            body.update(status="partial", issues=sorted(self._issues))
        return deepcopy(body)

    def _read_clock(self) -> int:
        value = self._clock_ns()
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise TypeError("clock_ns must return a non-negative integer")
        return value

    def _ensure_open(self) -> None:
        if self._closed:
            raise CollectorClosedError("resource accounting is already closed")

    def _advance(self, now_ns: int) -> None:
        if self._last_ns is not None:
            if now_ns < self._last_ns:
                raise ClockOrderError("the monotonic clock moved backwards")
            if now_ns > self._last_ns:
                if self._capacity is None:
                    self._issues.add("observation_incomplete")
                else:
                    self._record(_seconds_from_ns(now_ns - self._last_ns))
        self._last_ns = now_ns

    def _record(self, duration: Decimal) -> None:
        previous = self._intervals[-1] if self._intervals else None
        if (
            previous is not None
            and {key: item for key, item in previous.items() if key != "measured_seconds"} == self._capacity
        ):
            with localcontext() as context:
                context.prec = 100
                previous["measured_seconds"] = _decimal_text(Decimal(previous["measured_seconds"]) + duration)
        elif len(self._intervals) < MAX_CAPACITY_INTERVALS:
            self._intervals.append({"measured_seconds": _decimal_text(duration), **deepcopy(self._capacity)})
        else:
            self._issues.add("observation_incomplete")

    @staticmethod
    def _public_capacity(capacity: Mapping[str, Any]) -> dict[str, Any]:
        result = {}
        for resource, value in capacity.items():
            if resource == "memory":
                result[resource] = {"bytes": _decimal_text(value["bytes"])}
                continue
            field = "units" if resource == "cpu" else "count"
            consolidated = {}
            for group in value["groups"]:
                metadata = {key: item for key, item in group.items() if key != field and item is not None}
                key = tuple(sorted(metadata.items()))
                if key not in consolidated:
                    consolidated[key] = {**metadata, field: Decimal(0)}
                with localcontext() as context:
                    context.prec = 100
                    consolidated[key][field] += group[field]
            result[resource] = {
                "groups": [{**group, field: _decimal_text(group[field])} for _, group in sorted(consolidated.items())]
            }
        return result

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
            if len(gpu["groups"]) > MAX_GPU_GROUPS:
                raise ValueError("gpu.groups exceeds the supported device limit")
            groups = []
            total_count = Decimal(0)
            for index, raw in enumerate(gpu["groups"]):
                if not isinstance(raw, Mapping) or raw.get("kind") not in GPU_KINDS:
                    raise ValueError(f"gpu.groups[{index}] has an unsupported kind")
                count = _decimal(raw.get("count"), f"gpu.groups[{index}].count", positive=True)
                if count != count.to_integral_value():
                    raise ValueError(f"gpu.groups[{index}].count must be an integer")
                total_count += count
                group: dict[str, Any] = {
                    "kind": raw["kind"],
                    "count": count,
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
                    if raw["kind"] != "mig_compute_instance":
                        raise ValueError(f"gpu.groups[{index}].mig_profile requires a confirmed MIG instance")
                    group["mig_profile"] = mig_profile
                groups.append(group)
            if total_count > MAX_GPU_GROUPS:
                raise ValueError("gpu.groups exceeds the supported device limit")
            result["gpu"] = {"groups": groups}
        return result
