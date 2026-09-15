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

"""Small executable contracts for the resource-statistics prototype.

The schema does not choose which NVFlare component collects the data.  These
helpers test three rules that are independent of that choice:

* only one reporter covers the same job and measurement scope at a time;
* local fragments are self-reports stored in the existing job workspace; and
* the server uses the exact ``RESOURCE_STATS`` component name.

Nothing here requires a new launcher argument, mount, service, privilege, or
operator setting.  The local write-once helper prevents accidental replacement
through this API.  It is not a security boundary: job code with workspace access
can still change or remove a local fragment before the server receives it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


RESOURCE_STATS_COMPONENT = "RESOURCE_STATS"

_ATTEMPT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SAFE_PATH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_OBSERVATION_FRAGMENT_NAMES = frozenset({"start.json", "final.json"})
_ALL_FRAGMENT_NAMES = _OBSERVATION_FRAGMENT_NAMES | {"end.json"}
_ATTEMPT_END_REASONS = frozenset({"released", "reconfigured", "failed", "terminated", "launch_failed"})


class ReporterLeaseConflict(RuntimeError):
    """Raised when a second reporter claims an already-owned boundary."""


class WriteOnceRecordConflict(RuntimeError):
    """Raised when this API finds different bytes at an existing record path."""


def _require_attempt_id(attempt_id: str) -> str:
    if not isinstance(attempt_id, str) or not _ATTEMPT_ID_PATTERN.fullmatch(attempt_id):
        raise ValueError("attempt_id must be exactly 32 lowercase hexadecimal characters")
    return attempt_id


def _require_path_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_PATH_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a bounded path-safe identifier")
    return value


@dataclass(frozen=True)
class ReporterLease:
    """The sole reporter lease for one job/environment measurement boundary."""

    job_id: str
    execution_environment_id: str
    reporter_id: str

    def as_record(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "execution_environment_id": self.execution_environment_id,
            "reporter_id": self.reporter_id,
            "scope": "execution_environment",
            "cross_job_overlap": "allowed",
            "participant_total_is_capacity": False,
        }


class ReporterLeaseRegistry:
    """In-memory prototype of platform-owned reporter-boundary selection."""

    def __init__(self):
        self._leases: dict[tuple[str, str], ReporterLease] = {}
        self._lock = threading.Lock()

    def acquire(self, job_id: str, execution_environment_id: str, reporter_id: str) -> ReporterLease:
        job_id = _require_path_id(job_id, "job_id")
        execution_environment_id = _require_path_id(execution_environment_id, "execution_environment_id")
        reporter_id = _require_path_id(reporter_id, "reporter_id")
        key = (job_id, execution_environment_id)
        with self._lock:
            existing = self._leases.get(key)
            if existing is not None:
                if existing.reporter_id == reporter_id:
                    return existing
                raise ReporterLeaseConflict(
                    "a reporter already owns the job/execution-environment measurement boundary"
                )
            lease = ReporterLease(job_id, execution_environment_id, reporter_id)
            self._leases[key] = lease
            return lease

    def release(self, lease: ReporterLease) -> None:
        key = (lease.job_id, lease.execution_environment_id)
        with self._lock:
            if self._leases.get(key) == lease:
                self._leases.pop(key)


@dataclass(frozen=True)
class FragmentReceipt:
    path: Path
    sha256: str
    created: bool


def _json_bytes(record: Mapping[str, Any]) -> bytes:
    return (json.dumps(record, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _write_once(path: Path, data: bytes) -> FragmentReceipt:
    """Atomically create *path*, accepting only byte-identical replay.

    A temporary file plus ``link`` avoids ``os.replace``: a concurrent writer
    cannot overwrite a pre-existing accepted record.
    """

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp_path, path)
            created = True
        except FileExistsError:
            if path.is_symlink() or not path.is_file():
                raise WriteOnceRecordConflict(f"write-once record path is not a regular file: {path}")
            if path.read_bytes() != data:
                raise WriteOnceRecordConflict(f"conflicting accepted record already exists: {path}")
            created = False
        if created:
            os.chmod(path, 0o600)
        return FragmentReceipt(path=path, sha256=hashlib.sha256(data).hexdigest(), created=created)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


class WorkspaceAttemptStore:
    """Best-effort attempt records in an existing NVFlare job workspace.

    This class requires no special path or permission.  Its write-once behavior
    protects callers from accidental conflicting writes through this API only.
    The records remain self-reported and may be lost or changed by job code.
    """

    def __init__(self, workspace_root: Path):
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def fragment_path(self, job_id: str, attempt_id: str, fragment_name: str) -> Path:
        job_id = _require_path_id(job_id, "job_id")
        attempt_id = _require_attempt_id(attempt_id)
        if fragment_name not in _ALL_FRAGMENT_NAMES:
            raise ValueError(f"unsupported fragment name '{fragment_name}'")
        return self.workspace_root / "resource_stats" / "attempts" / job_id / attempt_id / fragment_name

    def persist_observation(
        self, job_id: str, attempt_id: str, fragment_name: str, observation: Mapping[str, Any]
    ) -> FragmentReceipt:
        """Write a start or final observation without claiming trusted storage."""

        if fragment_name not in _OBSERVATION_FRAGMENT_NAMES:
            raise ValueError("only start.json and final.json may contain resource observations")
        job_id = _require_path_id(job_id, "job_id")
        attempt_id = _require_attempt_id(attempt_id)
        if observation.get("job_id") != job_id or observation.get("attempt_id") != attempt_id:
            raise ValueError("observation identity must match the requested job and attempt")
        record = dict(observation)
        record["trust"] = {
            "content_origin": "self_reported",
            "storage_scope": "existing_job_workspace",
            "protected_from_job_code": False,
        }
        return _write_once(self.fragment_path(job_id, attempt_id, fragment_name), _json_bytes(record))

    def record_attempt_end_without_final(
        self,
        job_id: str,
        attempt_id: str,
        opened_at: str,
        closed_at: str,
        reason: str,
    ) -> FragmentReceipt:
        """Record a known end without inventing a missing final observation."""

        job_id = _require_path_id(job_id, "job_id")
        attempt_id = _require_attempt_id(attempt_id)
        if not isinstance(opened_at, str) or not opened_at:
            raise ValueError("opened_at must be a non-empty timestamp string")
        if not isinstance(closed_at, str) or not closed_at:
            raise ValueError("closed_at must be a non-empty timestamp string")
        if reason not in _ATTEMPT_END_REASONS:
            raise ValueError("reason must be released, reconfigured, failed, terminated, or launch_failed")
        record = {
            "schema_version": "prototype-0.3",
            "kind": "nvflare.resource_stats.attempt_end",
            "job_id": job_id,
            "attempt_id": attempt_id,
            "opened_at": opened_at,
            "closed_at": closed_at,
            "reason": reason,
            "final_observation": {"state": "absent"},
            "resource_window": {
                "clock_rule": "opened_at_and_closed_at_use_one_nvflare_clock",
                "basis": "integration_supplied",
            },
            "resource_observations": {"state": "not_invented", "coverage": "partial"},
            "trust": {
                "content_origin": "integration_supplied",
                "storage_scope": "existing_job_workspace",
                "protected_from_job_code": False,
            },
        }
        return _write_once(self.fragment_path(job_id, attempt_id, "end.json"), _json_bytes(record))


class FixedResourceStatsStore:
    """Prototype of a narrow final-summary API with one exact component name."""

    def __init__(self, job_store_root: Path):
        self.job_store_root = Path(job_store_root).resolve()
        self.job_store_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @staticmethod
    def is_allowed_component(component_name: str) -> bool:
        return component_name == RESOURCE_STATS_COMPONENT

    def save_resource_stats(self, job_id: str, resource_summary: bytes) -> FragmentReceipt:
        """Persist the byte-exact finalized summary without a caller-selected component."""

        job_id = _require_path_id(job_id, "job_id")
        if not isinstance(resource_summary, bytes):
            raise TypeError("resource_summary must be bytes")
        path = self.job_store_root / "jobs" / job_id / RESOURCE_STATS_COMPONENT
        return _write_once(path, resource_summary)

    def get_resource_stats(self, job_id: str) -> bytes | None:
        """Return the one exact final-summary component, or ``None`` if absent."""

        job_id = _require_path_id(job_id, "job_id")
        path = self.job_store_root / "jobs" / job_id / RESOURCE_STATS_COMPONENT
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise WriteOnceRecordConflict(f"resource-stats component is not a regular file: {path}")
        return path.read_bytes()
