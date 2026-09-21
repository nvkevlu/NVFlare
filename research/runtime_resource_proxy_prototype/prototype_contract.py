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

"""Executable pieces of the one-terminal-report resource-statistics design.

ResourceTimeAccumulator is child-process internal state. It accounts for the
time between resource observations, including later acquire/release
notifications, and freezes one private terminal handoff. The parent combines
that handoff with its own job-scoped F3 counters and emits the only public
participant_summary. There are no public start, final, attempt, or environment
records.

WorkspaceResourceStatsReader shows how the CLI can read finalized records from
fixed members of NVFlare's existing archived workspace component. No second
storage component, privilege, or operator configuration is required.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from copy import deepcopy
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from schema.contract_v1 import (
    KIND_PARTICIPANT_SUMMARY,
    KIND_RESOURCE_SUMMARY,
    ContractError,
    load_and_validate,
    validate_record,
)

WORKSPACE_COMPONENT = "workspace"
RESOURCE_STATS_ARCHIVE_DIR = "resource_stats"
RESOURCE_SUMMARY_MEMBER = f"{RESOURCE_STATS_ARCHIVE_DIR}/resource_summary.json"
_RESOURCE_STATS_STRUCTURAL_DIRECTORIES = {
    f"{RESOURCE_STATS_ARCHIVE_DIR}/",
    f"{RESOURCE_STATS_ARCHIVE_DIR}/participants/",
}
MAX_RESOURCE_SUMMARY_BYTES = 64 * 1024 * 1024
MAX_PARTICIPANT_SUMMARY_BYTES = 1 * 1024 * 1024
MAX_TERMINAL_HANDOFF_BYTES = 1 * 1024 * 1024
INTERNAL_HANDOFF_VERSION = "1"
INTERNAL_HANDOFF_KIND = "nvflare.resource_stats.internal.terminal_handoff"

_PARTICIPANT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}$")
_GPU_KINDS = frozenset({"full_gpu", "mig_compute_instance"})
_F3_BUCKETS = ("remote_accepted", "local_delivered", "remote_failed_before_acceptance")
_U128_MAX = 2**128 - 1


class AccumulatorClosedError(RuntimeError):
    """Raised when an observation is added after the terminal report is built."""


class ObservationOrderError(ValueError):
    """Raised when accumulator timestamps move backwards."""


class WorkspaceArchiveError(RuntimeError):
    """Raised when a requested archive member is unsafe or invalid."""


class InvalidTerminalHandoff(ValueError):
    """Raised when a child-process terminal handoff is malformed or oversized."""


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


def _optional_text(value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string when provided")
    return value


class ResourceTimeAccumulator:
    """Accumulate resource-time and freeze one private child-process handoff.

    The caller supplies platform observations and timestamps from one monotonic
    clock. observe closes the preceding interval and starts a new one. The
    current adapter can call it once at startup; a future scheduler can call it
    again whenever CPUs, memory, full GPUs, or MIG instances change.

    An observation has optional cpu, memory, and gpu members. CPU has units
    plus optional model and architecture. Memory has bytes. GPU has groups
    with kind, count, and optional model metadata. An empty GPU group list is
    an observed zero-GPU state.

    A missing member makes the single compute status partial. mark_gap starts
    an interval without a trustworthy capacity observation. The handoff
    contains totals only; internal intervals are not serialized. The parent
    later creates the one public participant report.
    """

    def __init__(self) -> None:
        self._last_at: Decimal | None = None
        self._current: dict[str, Any] | None = None
        self._closed = False
        self._measured_seconds = Decimal(0)
        self._cpu: dict[tuple[str | None, str | None], Decimal] = {}
        self._memory_byte_seconds = Decimal(0)
        self._memory_observed = False
        self._gpu: dict[tuple[str, str | None, str | None, str | None], Decimal] = {}
        self._gpu_observed = False
        self._issues: set[str] = set()

    def observe(self, at_seconds: object, capacity: Mapping[str, Any]) -> None:
        """Close the prior interval and make capacity current."""

        self._ensure_open()
        at = _decimal(at_seconds, "at_seconds")
        self._advance(at)
        self._current = self._normalize_capacity(capacity)

    def mark_gap(self, at_seconds: object) -> None:
        """Close the prior interval and start a period with no observation."""

        self._ensure_open()
        at = _decimal(at_seconds, "at_seconds")
        self._advance(at)
        self._current = None
        self._issues.add("observation_incomplete")

    def finish_measurements(
        self,
        at_seconds: object,
        *,
        workspace_filesystem: Mapping[str, Any],
        retained_content: Mapping[str, Any],
        child_f3: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Close accounting and build the private terminal handoff."""

        self._ensure_open()
        at = _decimal(at_seconds, "at_seconds")
        self._advance(at)
        self._closed = True
        return {
            "internal_version": INTERNAL_HANDOFF_VERSION,
            "kind": INTERNAL_HANDOFF_KIND,
            "resource_time": self.resource_time(),
            "workspace_filesystem": deepcopy(dict(workspace_filesystem)),
            "retained_content": deepcopy(dict(retained_content)),
            "child_f3": deepcopy(dict(child_f3)),
        }

    def resource_time(self) -> dict[str, Any]:
        """Return current totals without exposing interval history."""

        body: dict[str, Any] = {}
        cpu_groups = []
        for (model, architecture), unit_seconds in sorted(
            self._cpu.items(), key=lambda item: ((item[0][0] or ""), (item[0][1] or ""))
        ):
            group: dict[str, str] = {"unit_seconds": _decimal_text(unit_seconds)}
            if model is not None:
                group["model"] = model
            if architecture is not None:
                group["architecture"] = architecture
            cpu_groups.append(group)
        gpu_groups = []
        for (kind, model, memory_bytes, mig_profile), instance_seconds in sorted(
            self._gpu.items(), key=lambda item: tuple(value or "" for value in item[0])
        ):
            group = {"kind": kind, "instance_seconds": _decimal_text(instance_seconds)}
            if model is not None:
                group["model"] = model
            if memory_bytes is not None:
                group["memory_bytes"] = memory_bytes
            if mig_profile is not None:
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

        has_numeric = any(key in body for key in ("measured_seconds", "cpu", "memory", "gpu"))
        if not has_numeric:
            status = "unavailable"
            issues = sorted(self._issues or {"observation_incomplete"})
        elif self._issues:
            status = "partial"
            issues = sorted(self._issues)
        else:
            status = "reported"
            issues = []
        return {"status": status, **({"issues": issues} if issues else {}), **body}

    def _ensure_open(self) -> None:
        if self._closed:
            raise AccumulatorClosedError("the private terminal handoff has already been built")

    def _advance(self, at: Decimal) -> None:
        if self._last_at is None:
            self._last_at = at
            return
        if at < self._last_at:
            raise ObservationOrderError("observation timestamps must not move backwards")
        duration = at - self._last_at
        if duration > 0:
            if self._current is None:
                self._issues.add("observation_incomplete")
            else:
                self._account(duration, self._current)
        self._last_at = at

    def _account(self, duration: Decimal, capacity: Mapping[str, Any]) -> None:
        self._measured_seconds = self._add_product(self._measured_seconds, Decimal(1), duration)
        cpu = capacity.get("cpu")
        if cpu is None:
            self._issues.add("observation_incomplete")
        else:
            key = (cpu.get("model"), cpu.get("architecture"))
            self._cpu[key] = self._add_product(
                self._cpu.get(key, Decimal(0)),
                cpu["units"],
                duration,
            )

        memory = capacity.get("memory")
        if memory is None:
            self._issues.add("observation_incomplete")
        else:
            self._memory_observed = True
            self._memory_byte_seconds = self._add_product(
                self._memory_byte_seconds,
                memory["bytes"],
                duration,
            )

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
                self._gpu[key] = self._add_product(
                    self._gpu.get(key, Decimal(0)),
                    group["count"],
                    duration,
                )

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
        unknown = set(capacity) - {"cpu", "memory", "gpu"}
        if unknown:
            raise ValueError(f"unsupported capacity members: {sorted(unknown)}")
        result: dict[str, Any] = {}
        if "cpu" in capacity and capacity["cpu"] is not None:
            cpu = capacity["cpu"]
            if not isinstance(cpu, Mapping):
                raise TypeError("cpu must be a mapping")
            result["cpu"] = {
                "units": _decimal(cpu.get("units"), "cpu.units", positive=True),
                "model": _optional_text(cpu.get("model"), "cpu.model"),
                "architecture": _optional_text(cpu.get("architecture"), "cpu.architecture"),
            }
        if "memory" in capacity and capacity["memory"] is not None:
            memory = capacity["memory"]
            if not isinstance(memory, Mapping):
                raise TypeError("memory must be a mapping")
            result["memory"] = {"bytes": _decimal(memory.get("bytes"), "memory.bytes", positive=True)}
        if "gpu" in capacity and capacity["gpu"] is not None:
            gpu = capacity["gpu"]
            if not isinstance(gpu, Mapping) or not isinstance(gpu.get("groups"), list):
                raise TypeError("gpu.groups must be a list")
            groups = []
            for index, group in enumerate(gpu["groups"]):
                if not isinstance(group, Mapping):
                    raise TypeError(f"gpu.groups[{index}] must be a mapping")
                kind = group.get("kind")
                if kind not in _GPU_KINDS:
                    raise ValueError(f"gpu.groups[{index}].kind is unsupported")
                normalized = {
                    "kind": kind,
                    "count": _decimal(group.get("count"), f"gpu.groups[{index}].count", positive=True),
                    "model": _optional_text(group.get("model"), f"gpu.groups[{index}].model"),
                    "memory_bytes": (
                        _decimal_text(
                            _decimal(
                                group["memory_bytes"],
                                f"gpu.groups[{index}].memory_bytes",
                                positive=True,
                            )
                        )
                        if "memory_bytes" in group
                        else None
                    ),
                    "mig_profile": _optional_text(
                        group.get("mig_profile"),
                        f"gpu.groups[{index}].mig_profile",
                    ),
                }
                if kind == "full_gpu" and normalized["mig_profile"] is not None:
                    raise ValueError("full_gpu groups cannot have mig_profile")
                groups.append(normalized)
            result["gpu"] = {"groups": groups}
        return result


def _unavailable(issue: str = "observation_incomplete") -> dict[str, Any]:
    return {"status": "unavailable", "issues": [issue]}


def _f3_has_numbers(value: Mapping[str, Any]) -> bool:
    return value.get("status") in {"reported", "partial"} and all(bucket in value for bucket in _F3_BUCKETS)


def _merge_f3(child_f3: Mapping[str, Any], parent_f3: Mapping[str, Any]) -> dict[str, Any]:
    """Merge child- and parent-process sender counters for one participant.

    A complete value requires both process domains to report complete counters.
    If either side is missing, valid counters from the other side remain useful
    but the merged value is explicitly partial.
    """

    if not isinstance(child_f3, Mapping) or not isinstance(parent_f3, Mapping):
        raise TypeError("child_f3 and parent_f3 must be mappings")
    numeric = [value for value in (child_f3, parent_f3) if _f3_has_numbers(value)]
    if not numeric:
        return _unavailable("attribution_incomplete")

    result: dict[str, Any] = {}
    for bucket in _F3_BUCKETS:
        payload_bytes = sum(int(value[bucket]["payload_bytes"]) for value in numeric)
        messages = sum(int(value[bucket]["messages"]) for value in numeric)
        if payload_bytes > _U128_MAX or messages > _U128_MAX:
            raise OverflowError(f"merged F3 {bucket} exceeds the unsigned 128-bit bound")
        result[bucket] = {"payload_bytes": str(payload_bytes), "messages": str(messages)}

    complete = len(numeric) == 2 and all(value.get("status") == "reported" for value in numeric)
    if complete:
        return {"status": "reported", **result}

    issues = {"attribution_incomplete"}
    for value in numeric:
        if value.get("status") == "partial":
            issues.update(
                issue
                for issue in value.get("issues", [])
                if issue in {"attribution_incomplete", "counter_gap", "observation_incomplete"}
            )
    return {"status": "partial", "issues": sorted(issues), **result}


def _validated_child_handoff(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidTerminalHandoff("terminal handoff must be an object")
    required = {
        "internal_version",
        "kind",
        "resource_time",
        "workspace_filesystem",
        "retained_content",
        "child_f3",
    }
    if set(value) != required:
        raise InvalidTerminalHandoff(f"terminal handoff fields must be exactly {sorted(required)}")
    if value["internal_version"] != INTERNAL_HANDOFF_VERSION:
        raise InvalidTerminalHandoff(f"terminal handoff internal_version must equal {INTERNAL_HANDOFF_VERSION}")
    if value["kind"] != INTERNAL_HANDOFF_KIND:
        raise InvalidTerminalHandoff(f"terminal handoff kind must equal {INTERNAL_HANDOFF_KIND}")
    probe_record = {
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
        validate_record(probe_record)
    except ContractError as exc:
        raise InvalidTerminalHandoff(f"terminal handoff is invalid: {exc}") from exc
    return {
        "internal_version": INTERNAL_HANDOFF_VERSION,
        "kind": INTERNAL_HANDOFF_KIND,
        "resource_time": probe_record["resource_time"],
        "workspace_filesystem": probe_record["workspace_filesystem"],
        "retained_content": probe_record["retained_content"],
        "child_f3": probe_record["f3"],
    }


def load_terminal_handoff(
    data: bytes,
    *,
    max_bytes: int = MAX_TERMINAL_HANDOFF_BYTES,
) -> dict[str, Any]:
    """Bound and strictly decode a child-owned terminal handoff."""

    if not isinstance(data, bytes):
        raise InvalidTerminalHandoff("terminal handoff input must be bytes")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    if len(data) > max_bytes:
        raise InvalidTerminalHandoff(f"terminal handoff exceeds the {max_bytes}-byte limit")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise InvalidTerminalHandoff(f"terminal handoff contains duplicate key {key!r}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise InvalidTerminalHandoff(f"terminal handoff contains non-finite number {value!r}")

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite,
        )
    except InvalidTerminalHandoff:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InvalidTerminalHandoff("terminal handoff must be bounded valid UTF-8 JSON") from exc
    return _validated_child_handoff(value)


def assemble_participant_summary(
    *,
    job_id: str,
    participant_name: str,
    reported_at: str,
    child_handoff: Mapping[str, Any] | bytes | None,
    parent_f3: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the only public report after the child has terminated.

    The parent owns identity and final serialization. A missing child handoff
    produces typed unavailable measurements instead of guessed values; useful
    parent-process F3 counters are retained as a partial result.
    """

    if not isinstance(job_id, str) or not job_id:
        raise ValueError("job_id must be a non-empty string")
    if not isinstance(participant_name, str) or not _PARTICIPANT_NAME_PATTERN.fullmatch(participant_name):
        raise ValueError("participant_name must be a safe NVFlare participant name")
    if not isinstance(reported_at, str) or not reported_at:
        raise ValueError("reported_at must be a non-empty timestamp string")
    try:
        if isinstance(child_handoff, bytes):
            validated_handoff = load_terminal_handoff(child_handoff)
        elif child_handoff is None:
            validated_handoff = None
        else:
            validated_handoff = _validated_child_handoff(child_handoff)
    except InvalidTerminalHandoff:
        validated_handoff = None

    if validated_handoff is None:
        resource_time = _unavailable()
        workspace_filesystem = _unavailable()
        retained_content = _unavailable()
        child_f3 = _unavailable("attribution_incomplete")
    else:
        resource_time = validated_handoff["resource_time"]
        workspace_filesystem = validated_handoff["workspace_filesystem"]
        retained_content = validated_handoff["retained_content"]
        child_f3 = validated_handoff["child_f3"]

    report = {
        "schema_version": "1.0",
        "kind": "nvflare.resource_stats.participant_summary",
        "job_id": job_id,
        "participant_name": participant_name,
        "reported_at": reported_at,
        "resource_time": resource_time,
        "workspace_filesystem": workspace_filesystem,
        "retained_content": retained_content,
        "f3": _merge_f3(child_f3, parent_f3),
    }
    validate_record(report)
    return report


class WorkspaceResourceStatsReader:
    """Read fixed resource-statistics members from an existing workspace ZIP.

    The reader never extracts a member and never accepts an arbitrary member
    path. The finalized resource summary is the commit record: its accepted
    participant names determine the exact resource-statistics inventory.
    Existing job-storage authorization remains the security boundary.
    """

    def __init__(
        self,
        workspace_archive: Path,
        *,
        max_resource_summary_bytes: int = MAX_RESOURCE_SUMMARY_BYTES,
        max_participant_summary_bytes: int = MAX_PARTICIPANT_SUMMARY_BYTES,
    ):
        self.workspace_archive = Path(workspace_archive)
        self.max_resource_summary_bytes = self._require_positive_bound(
            max_resource_summary_bytes, "max_resource_summary_bytes"
        )
        self.max_participant_summary_bytes = self._require_positive_bound(
            max_participant_summary_bytes, "max_participant_summary_bytes"
        )

    @staticmethod
    def _require_positive_bound(value: int, label: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{label} must be a positive integer")
        return value

    def _read_exact_member(self, member_name: str, max_bytes: int) -> bytes:
        if not self.workspace_archive.is_file():
            raise WorkspaceArchiveError(f"workspace archive is not a file: {self.workspace_archive}")
        try:
            with ZipFile(self.workspace_archive, "r") as archive:
                matches = [info for info in archive.infolist() if info.filename == member_name]
                if len(matches) != 1:
                    raise WorkspaceArchiveError(
                        f"workspace archive must contain exactly one '{member_name}' member; found {len(matches)}"
                    )
                info = matches[0]
                if info.is_dir():
                    raise WorkspaceArchiveError(f"workspace member is a directory: {member_name}")
                if info.flag_bits & 0x1:
                    raise WorkspaceArchiveError(f"encrypted workspace member is not supported: {member_name}")
                if info.file_size > max_bytes:
                    raise WorkspaceArchiveError(f"workspace member exceeds its {max_bytes}-byte limit: {member_name}")
                with archive.open(info, "r") as stream:
                    data = stream.read(max_bytes + 1)
                if len(data) > max_bytes or len(data) != info.file_size:
                    raise WorkspaceArchiveError(f"workspace member length is inconsistent: {member_name}")
                return data
        except WorkspaceArchiveError:
            raise
        except (BadZipFile, OSError, RuntimeError, EOFError) as exc:
            raise WorkspaceArchiveError(f"cannot read workspace archive: {exc}") from exc

    def _verify_resource_stats_inventory(self, summary: Mapping[str, Any]) -> None:
        expected = {
            RESOURCE_SUMMARY_MEMBER,
            *(
                f"{RESOURCE_STATS_ARCHIVE_DIR}/participants/{participant_name}.json"
                for participant_name in self._accepted_participants(summary)
            ),
        }
        try:
            with ZipFile(self.workspace_archive, "r") as archive:
                resource_infos = [
                    info for info in archive.infolist() if info.filename.startswith(f"{RESOURCE_STATS_ARCHIVE_DIR}/")
                ]
        except (BadZipFile, OSError, RuntimeError, EOFError) as exc:
            raise WorkspaceArchiveError(f"cannot inspect workspace archive: {exc}") from exc
        member_names = [info.filename for info in resource_infos]
        if len(member_names) != len(set(member_names)):
            raise WorkspaceArchiveError("workspace resource_stats members must not contain duplicate names")
        actual = set()
        for info in resource_infos:
            if info.is_dir():
                if info.filename not in _RESOURCE_STATS_STRUCTURAL_DIRECTORIES or info.file_size != 0:
                    raise WorkspaceArchiveError(
                        "workspace resource_stats members must exactly match resource_summary.json "
                        "plus the accepted participant names"
                    )
            else:
                actual.add(info.filename)
        if actual != expected:
            raise WorkspaceArchiveError(
                "workspace resource_stats members must exactly match resource_summary.json "
                "plus the accepted participant names"
            )

    @staticmethod
    def _load_contract_record(data: bytes, label: str, expected_kind: str) -> Mapping[str, Any]:
        try:
            value = load_and_validate(data)
        except ContractError as exc:
            raise WorkspaceArchiveError(f"{label} violates schema v1: {exc}") from exc
        if value["kind"] != expected_kind:
            raise WorkspaceArchiveError(f"{label} has the wrong record kind")
        return value

    @staticmethod
    def _accepted_participants(summary: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
        return {entry["participant_name"]: entry for entry in summary["participants"] if entry["status"] == "accepted"}

    def read_resource_summary_bytes(self) -> bytes:
        data = self._read_exact_member(RESOURCE_SUMMARY_MEMBER, self.max_resource_summary_bytes)
        summary = self._load_contract_record(data, "resource summary", KIND_RESOURCE_SUMMARY)
        self._verify_resource_stats_inventory(summary)
        return data

    def read_participant_summary_bytes(self, participant_name: str) -> bytes:
        if not isinstance(participant_name, str) or not _PARTICIPANT_NAME_PATTERN.fullmatch(participant_name):
            raise ValueError("participant_name must be a safe NVFlare participant name")
        summary_data = self.read_resource_summary_bytes()
        summary = self._load_contract_record(summary_data, "resource summary", KIND_RESOURCE_SUMMARY)
        accepted_entry = self._accepted_participants(summary).get(participant_name)
        if accepted_entry is None:
            raise WorkspaceArchiveError("participant summary has no accepted entry in the resource summary")
        member_name = f"{RESOURCE_STATS_ARCHIVE_DIR}/participants/{participant_name}.json"
        data = self._read_exact_member(member_name, self.max_participant_summary_bytes)
        participant = self._load_contract_record(data, "participant summary", KIND_PARTICIPANT_SUMMARY)
        if participant["job_id"] != summary["job_id"]:
            raise WorkspaceArchiveError("participant summary job_id does not match the resource summary")
        if participant["participant_name"] != participant_name:
            raise WorkspaceArchiveError("participant summary name does not match its archive path")
        for field in ("resource_time", "retained_content", "f3"):
            if accepted_entry[field] != participant[field]:
                raise WorkspaceArchiveError(
                    f"resource summary accepted participant {field} does not match the participant summary"
                )
        return data
