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

"""Executable prototype contracts for trusted resource-statistics boundaries.

This module is deliberately independent of NVFlare production code.  It makes
four proposed Phase 1 safeguards concrete enough to test before an integration
chooses its final internal APIs:

* launchers start Python with a sanitized environment and carry a parent-issued
  attempt ID only through a fixed allowlist;
* one reporter owns a ``(job_id, execution_environment_id)`` observation
  boundary, without trying to infer exclusive physical-resource ownership;
* child observations are copied into parent-owned write-once storage, while
  their content origin remains explicitly self-reported; and
* the final query copy uses the one exact ``RESOURCE_STATS`` component rather
  than a generic prefix convention.

The module is a behavioral prototype, not a production implementation.  In
particular, ``persist_child_fragment`` models the parent side after an
authenticated handoff; it does not claim that the handoff protocol exists.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


ATTEMPT_ID_ARGUMENT = "--resource-stats-attempt-id"
RESOURCE_STATS_COMPONENT = "RESOURCE_STATS"

# The value is intentionally fixed in each launcher path.  A caller cannot add
# an alternate resource-stats argument or choose a different flag spelling.
LAUNCHER_ATTEMPT_ARG_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "process": (ATTEMPT_ID_ARGUMENT,),
    "docker": (ATTEMPT_ID_ARGUMENT,),
    "k8s": (ATTEMPT_ID_ARGUMENT,),
    "slurm": (ATTEMPT_ID_ARGUMENT,),
}

_ATTEMPT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SAFE_PATH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CHILD_FRAGMENT_NAMES = frozenset({"start.json", "final.json"})
_ALL_FRAGMENT_NAMES = _CHILD_FRAGMENT_NAMES | {"parent_exit.json"}


class ReporterLeaseConflict(RuntimeError):
    """Raised when a second reporter claims an already-owned boundary."""


class WriteOnceRecordConflict(RuntimeError):
    """Raised when an accepted parent-owned record conflicts with existing bytes."""


def _require_attempt_id(attempt_id: str) -> str:
    if not isinstance(attempt_id, str) or not _ATTEMPT_ID_PATTERN.fullmatch(attempt_id):
        raise ValueError("attempt_id must be exactly 32 lowercase hexadecimal characters")
    return attempt_id


def _require_path_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_PATH_ID_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a bounded path-safe identifier")
    return value


def _contains_attempt_argument(value: str) -> bool:
    return value == ATTEMPT_ID_ARGUMENT or value.startswith(f"{ATTEMPT_ID_ARGUMENT}=")


@dataclass(frozen=True)
class SanitizedLaunchPlan:
    """A pre-Python launcher contract.

    ``post_snapshot_custom_import_paths`` are deliberately absent from argv and
    the pre-Python environment.  The platform bootstrap enables them only after
    the startup fragment is written.
    """

    launcher: str
    attempt_id: str
    argv: tuple[str, ...]
    pre_python_environment: dict[str, str]
    post_snapshot_custom_import_paths: tuple[str, ...]
    bootstrap_steps: tuple[str, ...]


def build_sanitized_launch_plan(
    launcher: str,
    python_executable: str,
    module: str,
    platform_args: Sequence[str],
    environment: Mapping[str, str],
    attempt_id: str,
    custom_import_paths: Sequence[str] = (),
) -> SanitizedLaunchPlan:
    """Build the proposed launcher-independent pre-Python contract.

    ``-S`` prevents Python's automatic site initialization before the
    platform-owned bootstrap.  Removing ``PYTHONPATH`` prevents a job custom
    ``sitecustomize`` module from being imported before that bootstrap.  The
    real product still needs to select how platform packages remain importable
    under this mode; this prototype captures only the security boundary.
    """

    allowed_args = LAUNCHER_ATTEMPT_ARG_ALLOWLIST.get(launcher)
    if allowed_args is None:
        raise ValueError(f"unsupported launcher '{launcher}'")
    if ATTEMPT_ID_ARGUMENT not in allowed_args:
        raise ValueError(f"launcher '{launcher}' is not allowed to propagate the resource-stats attempt ID")
    if not isinstance(python_executable, str) or not python_executable:
        raise ValueError("python_executable must be a non-empty string")
    if not isinstance(module, str) or not module:
        raise ValueError("module must be a non-empty string")

    attempt_id = _require_attempt_id(attempt_id)
    platform_args = tuple(str(arg) for arg in platform_args)
    if any(_contains_attempt_argument(arg) for arg in platform_args):
        raise ValueError("resource-stats attempt ID is injected only by the fixed launcher allowlist")

    custom_import_paths = tuple(str(path) for path in custom_import_paths)
    if any(not path for path in custom_import_paths):
        raise ValueError("custom import paths must be non-empty")
    for custom_path in custom_import_paths:
        if any(custom_path in arg for arg in platform_args):
            raise ValueError("custom import paths may not be present in pre-Python platform arguments")

    # The original mapping is not modified.  That makes the plan safe to reuse
    # for each launcher and proves the caller cannot retain a stale custom path.
    pre_python_environment = {str(name): str(value) for name, value in environment.items() if str(name) != "PYTHONPATH"}
    argv = (python_executable, "-S", "-u", "-m", module, *platform_args, ATTEMPT_ID_ARGUMENT, attempt_id)
    return SanitizedLaunchPlan(
        launcher=launcher,
        attempt_id=attempt_id,
        argv=argv,
        pre_python_environment=pre_python_environment,
        post_snapshot_custom_import_paths=custom_import_paths,
        bootstrap_steps=(
            "start_python_without_site_initialization",
            "capture_platform_owned_start_snapshot",
            "persist_start_fragment_to_parent_owned_store",
            "enable_custom_import_paths",
        ),
    )


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


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


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


class ParentOwnedAttemptStore:
    """Parent-side durable, write-once attempt records outside the job workspace."""

    def __init__(self, parent_owned_root: Path, job_writable_root: Path):
        self.parent_owned_root = Path(parent_owned_root).resolve()
        self.job_writable_root = Path(job_writable_root).resolve()
        if _path_is_within(self.parent_owned_root, self.job_writable_root) or _path_is_within(
            self.job_writable_root, self.parent_owned_root
        ):
            raise ValueError("parent-owned fragment storage must not overlap job-writable storage")
        self.parent_owned_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def fragment_path(self, job_id: str, attempt_id: str, fragment_name: str) -> Path:
        job_id = _require_path_id(job_id, "job_id")
        attempt_id = _require_attempt_id(attempt_id)
        if fragment_name not in _ALL_FRAGMENT_NAMES:
            raise ValueError(f"unsupported fragment name '{fragment_name}'")
        return self.parent_owned_root / "resource_stats" / "attempts" / job_id / attempt_id / fragment_name

    def persist_child_fragment(
        self, job_id: str, attempt_id: str, fragment_name: str, child_record: Mapping[str, Any]
    ) -> FragmentReceipt:
        """Persist a child-produced start/final fragment after parent receipt.

        Parent-owned storage prevents a job from changing the accepted bytes
        later, but the values remain a child self-report.  The trust labels make
        that distinction explicit rather than calling child files immutable.
        """

        if fragment_name not in _CHILD_FRAGMENT_NAMES:
            raise ValueError("only start.json and final.json may be child-produced fragments")
        job_id = _require_path_id(job_id, "job_id")
        attempt_id = _require_attempt_id(attempt_id)
        if child_record.get("job_id") != job_id or child_record.get("attempt_id") != attempt_id:
            raise ValueError("child fragment identity must match the parent-issued job and attempt identity")
        record = copy.deepcopy(dict(child_record))
        record["trust"] = {
            "storage_owner": "platform_parent",
            "storage_scope": "outside_job_writable_workspace",
            "content_origin": "child_self_reported",
            "integrity": "write_once_after_parent_receipt",
            "authenticated_handoff_required": True,
        }
        return _write_once(self.fragment_path(job_id, attempt_id, fragment_name), _json_bytes(record))

    def record_crash_parent_exit(
        self,
        job_id: str,
        attempt_id: str,
        observed_at: str,
        return_code: int,
    ) -> FragmentReceipt:
        """Write lifecycle facts after a child crash without inventing a final sample."""

        job_id = _require_path_id(job_id, "job_id")
        attempt_id = _require_attempt_id(attempt_id)
        if not isinstance(observed_at, str) or not observed_at:
            raise ValueError("observed_at must be a non-empty timestamp string")
        if isinstance(return_code, bool) or not isinstance(return_code, int):
            raise ValueError("return_code must be an integer")
        record = {
            "schema_version": "prototype-0.3",
            "kind": "nvflare.resource_stats.attempt_parent_exit",
            "job_id": job_id,
            "attempt_id": attempt_id,
            "recorded_at": observed_at,
            "process_exit": {"return_code": return_code, "classification": "child_crashed"},
            "child_final": {"state": "absent"},
            "observation_end": {"basis": "parent_observed_exit", "ended_at": observed_at},
            "resource_observations": {"state": "not_invented", "coverage": "partial"},
            "trust": {
                "storage_owner": "platform_parent",
                "storage_scope": "outside_job_writable_workspace",
                "content_origin": "parent_observed_lifecycle",
                "integrity": "write_once_parent_owned",
            },
        }
        return _write_once(self.fragment_path(job_id, attempt_id, "parent_exit.json"), _json_bytes(record))


class FixedResourceStatsStore:
    """Prototype of a narrow final-summary API with one exact component name."""

    def __init__(self, parent_owned_root: Path):
        self.parent_owned_root = Path(parent_owned_root).resolve()
        self.parent_owned_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @staticmethod
    def is_allowed_component(component_name: str) -> bool:
        return component_name == RESOURCE_STATS_COMPONENT

    def save_resource_stats(self, job_id: str, resource_summary: bytes) -> FragmentReceipt:
        """Persist the byte-exact finalized summary without a caller-selected component."""

        job_id = _require_path_id(job_id, "job_id")
        if not isinstance(resource_summary, bytes):
            raise TypeError("resource_summary must be bytes")
        path = self.parent_owned_root / "jobs" / job_id / RESOURCE_STATS_COMPONENT
        return _write_once(path, resource_summary)

    def get_resource_stats(self, job_id: str) -> bytes | None:
        """Return the one exact final-summary component, or ``None`` if absent."""

        job_id = _require_path_id(job_id, "job_id")
        path = self.parent_owned_root / "jobs" / job_id / RESOURCE_STATS_COMPONENT
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise WriteOnceRecordConflict(f"resource-stats component is not a regular file: {path}")
        return path.read_bytes()
