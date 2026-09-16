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
* finalized records are read from fixed members of the existing archived
  ``workspace`` component.

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
from zipfile import BadZipFile, ZipFile


WORKSPACE_COMPONENT = "workspace"
RESOURCE_STATS_ARCHIVE_DIR = "resource_stats"
RESOURCE_SUMMARY_MEMBER = f"{RESOURCE_STATS_ARCHIVE_DIR}/resource_summary.json"
RESOURCE_MANIFEST_MEMBER = f"{RESOURCE_STATS_ARCHIVE_DIR}/manifest.json"
MAX_RESOURCE_SUMMARY_BYTES = 64 * 1024 * 1024
MAX_RESOURCE_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_PARTICIPANT_SUMMARY_BYTES = 64 * 1024 * 1024

_ATTEMPT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SAFE_PATH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PARTICIPANT_KEY_PATTERN = re.compile(r"^sha256-[0-9a-f]{64}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_OBSERVATION_FRAGMENT_NAMES = frozenset({"start.json", "final.json"})
_ALL_FRAGMENT_NAMES = _OBSERVATION_FRAGMENT_NAMES | {"end.json"}
_ATTEMPT_END_REASONS = frozenset({"released", "reconfigured", "failed", "terminated", "launch_failed"})


class ReporterLeaseConflict(RuntimeError):
    """Raised when a second reporter claims an already-owned boundary."""


class WriteOnceRecordConflict(RuntimeError):
    """Raised when this API finds different bytes at an existing record path."""


class WorkspaceArchiveError(RuntimeError):
    """Raised when a requested resource-statistics archive member is unsafe or invalid."""


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


class WorkspaceResourceStatsReader:
    """Read fixed resource-statistics members from an existing workspace ZIP.

    This reader never extracts an archive member to disk and never accepts a
    caller-provided member name.  The manifest checks bundle consistency; it is
    not a signature or site-authentication mechanism. Normal job-storage
    authorization remains the outer security boundary.
    """

    def __init__(
        self,
        workspace_archive: Path,
        *,
        max_resource_summary_bytes: int = MAX_RESOURCE_SUMMARY_BYTES,
        max_manifest_bytes: int = MAX_RESOURCE_MANIFEST_BYTES,
        max_participant_summary_bytes: int = MAX_PARTICIPANT_SUMMARY_BYTES,
    ):
        self.workspace_archive = Path(workspace_archive)
        self.max_resource_summary_bytes = self._require_positive_bound(
            max_resource_summary_bytes, "max_resource_summary_bytes"
        )
        self.max_manifest_bytes = self._require_positive_bound(max_manifest_bytes, "max_manifest_bytes")
        self.max_participant_summary_bytes = self._require_positive_bound(
            max_participant_summary_bytes, "max_participant_summary_bytes"
        )

    @staticmethod
    def _require_positive_bound(value: int, label: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{label} must be a positive integer")
        return value

    def _read_exact_member(self, member_name: str, max_bytes: int) -> bytes:
        """Return one fixed member after duplicate, encryption, and size checks."""

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
                    raise WorkspaceArchiveError(
                        f"workspace member exceeds its {max_bytes}-byte limit: {member_name}"
                    )
                with archive.open(info, "r") as stream:
                    data = stream.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise WorkspaceArchiveError(
                        f"workspace member exceeds its {max_bytes}-byte limit: {member_name}"
                    )
                if len(data) != info.file_size:
                    raise WorkspaceArchiveError(f"workspace member length is inconsistent: {member_name}")
                return data
        except WorkspaceArchiveError:
            raise
        except (BadZipFile, OSError, RuntimeError, EOFError) as exc:
            raise WorkspaceArchiveError(f"cannot read workspace archive: {exc}") from exc

    def _read_manifest(self) -> tuple[bytes, dict[str, Mapping[str, Any]]]:
        data = self._read_exact_member(RESOURCE_MANIFEST_MEMBER, self.max_manifest_bytes)
        manifest = self._load_json_object(data, "resource statistics manifest")
        if not isinstance(manifest.get("entries"), list):
            raise WorkspaceArchiveError("resource statistics manifest must contain an entries array")
        entries: dict[str, Mapping[str, Any]] = {}
        for entry in manifest["entries"]:
            if not isinstance(entry, Mapping):
                raise WorkspaceArchiveError("resource statistics manifest entries must be objects")
            relative_path = entry.get("relative_path")
            digest = entry.get("sha256")
            if (
                not isinstance(relative_path, str)
                or not isinstance(digest, str)
                or not _SHA256_PATTERN.fullmatch(digest)
            ):
                raise WorkspaceArchiveError("resource statistics manifest entry is invalid")
            if relative_path in entries:
                raise WorkspaceArchiveError(f"duplicate resource statistics manifest entry: {relative_path}")
            byte_count = entry.get("byte_count")
            if byte_count is not None and (
                not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0
            ):
                raise WorkspaceArchiveError("resource statistics manifest byte_count must be a non-negative integer")
            entries[relative_path] = entry
        return data, entries

    @staticmethod
    def _load_json_object(data: bytes, label: str) -> Mapping[str, Any]:
        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise WorkspaceArchiveError(f"{label} contains duplicate object key '{key}'")
                result[key] = value
            return result

        try:
            value = json.loads(data, object_pairs_hook=reject_duplicate_keys)
        except WorkspaceArchiveError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkspaceArchiveError(f"{label} is not valid UTF-8 JSON") from exc
        if not isinstance(value, Mapping):
            raise WorkspaceArchiveError(f"{label} must be a JSON object")
        return value

    @staticmethod
    def _verify_manifest_entry(data: bytes, relative_path: str, entries: Mapping[str, Mapping[str, Any]]) -> None:
        entry = entries.get(relative_path)
        if entry is None:
            raise WorkspaceArchiveError(f"resource statistics manifest does not list '{relative_path}'")
        if entry["sha256"] != hashlib.sha256(data).hexdigest():
            raise WorkspaceArchiveError(f"resource statistics manifest digest mismatch for '{relative_path}'")
        if entry.get("byte_count") is not None and entry["byte_count"] != len(data):
            raise WorkspaceArchiveError(f"resource statistics manifest byte count mismatch for '{relative_path}'")

    def read_manifest_bytes(self) -> bytes:
        """Return the one fixed resource-statistics manifest member."""

        data, _ = self._read_manifest()
        return data

    def read_resource_summary_bytes(self) -> bytes:
        """Return the finalized job summary after checking its manifest entry."""

        data = self._read_exact_member(RESOURCE_SUMMARY_MEMBER, self.max_resource_summary_bytes)
        self._load_json_object(data, "resource summary")
        _, entries = self._read_manifest()
        self._verify_manifest_entry(data, "resource_summary.json", entries)
        return data

    def read_participant_summary_bytes(self, participant_key: str) -> bytes:
        """Return one manifest-listed participant selected by its validated key."""

        if not isinstance(participant_key, str) or not _PARTICIPANT_KEY_PATTERN.fullmatch(participant_key):
            raise ValueError("participant_key must be 'sha256-' followed by 64 lowercase hexadecimal characters")
        relative_path = f"participants/{participant_key}.json"
        member_name = f"{RESOURCE_STATS_ARCHIVE_DIR}/{relative_path}"
        data = self._read_exact_member(member_name, self.max_participant_summary_bytes)
        self._load_json_object(data, "participant summary")
        _, entries = self._read_manifest()
        self._verify_manifest_entry(data, relative_path, entries)
        return data
