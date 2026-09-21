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

"""Pure resource-time accounting: no I/O, no process/platform knowledge.

The public record contains seconds, not raw clock readings.  A monotonic
nanosecond clock is used only inside the process so elapsed intervals can be
subtracted exactly without depending on wall-clock adjustments.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any, Optional

from .contract import GPU_KINDS
from .probes._shared import _decimal, _decimal_text, _normalize_architecture, _normalize_model


def _seconds_from_ns(value: int) -> Decimal:
    with localcontext() as context:
        context.prec = 100
        return Decimal(value) / Decimal(1_000_000_000)


class CollectorClosedError(RuntimeError):
    """Raised when a closed collector receives another observation."""


class ClockOrderError(RuntimeError):
    """Raised when an injected monotonic clock moves backwards."""


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
                if not isinstance(raw, Mapping) or raw.get("kind") not in GPU_KINDS:
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
