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

* launchers start an absolute platform-owned bootstrap in Python isolated mode,
  from a platform-owned working directory and with a fixed environment allowlist,
  and carry supervisor-issued attempt identity and handoff locator only through a
  fixed argument allowlist;
* one reporter owns a ``(job_id, execution_environment_id)`` observation
  boundary, without trying to infer exclusive physical-resource ownership;
* worker observations are copied into supervisor-owned write-once storage, while
  their content origin remains explicitly self-reported; and
* the final query copy uses the one exact ``RESOURCE_STATS`` component rather
  than a generic prefix convention.

The module is a behavioral prototype, not a production implementation.  In
particular, ``persist_worker_fragment`` models the supervisor side after an
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
HANDOFF_LOCATOR_ARGUMENT = "--resource-stats-handoff"
RESOURCE_STATS_COMPONENT = "RESOURCE_STATS"

# The value is intentionally fixed in each launcher path.  A caller cannot add
# an alternate resource-stats argument or choose a different flag spelling.
LAUNCHER_ATTEMPT_ARG_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "process": (ATTEMPT_ID_ARGUMENT, HANDOFF_LOCATOR_ARGUMENT),
    "docker": (ATTEMPT_ID_ARGUMENT, HANDOFF_LOCATOR_ARGUMENT),
    "k8s": (ATTEMPT_ID_ARGUMENT, HANDOFF_LOCATOR_ARGUMENT),
    "slurm": (ATTEMPT_ID_ARGUMENT, HANDOFF_LOCATOR_ARGUMENT),
}

_ATTEMPT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SAFE_PATH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WORKER_FRAGMENT_NAMES = frozenset({"start.json", "final.json"})
_ALL_FRAGMENT_NAMES = _WORKER_FRAGMENT_NAMES | {"end.json"}
_ATTEMPT_END_REASONS = frozenset({"released", "reconfigured", "failed", "terminated", "launch_failed"})
_PRE_PYTHON_ENV_ALLOWLIST = frozenset({"CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES"})


class ReporterLeaseConflict(RuntimeError):
    """Raised when a second reporter claims an already-owned boundary."""


class WriteOnceRecordConflict(RuntimeError):
    """Raised when an accepted supervisor-owned record conflicts with existing bytes."""


def _require_attempt_id(attempt_id: str) -> str:
    if not isinstance(attempt_id, str) or not _ATTEMPT_ID_PATTERN.fullmatch(attempt_id):
        raise ValueError("attempt_id must be exactly 32 lowercase hexadecimal characters")
    return attempt_id


def _require_handoff_locator(handoff_locator: str) -> str:
    if not isinstance(handoff_locator, str) or not _ATTEMPT_ID_PATTERN.fullmatch(handoff_locator):
        raise ValueError("handoff_locator must be exactly 32 lowercase hexadecimal characters")
    return handoff_locator


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
    handoff_locator: str
    platform_owned_cwd: str
    trusted_bootstrap_path: str
    argv: tuple[str, ...]
    pre_python_environment: dict[str, str]
    post_snapshot_custom_import_paths: tuple[str, ...]
    bootstrap_steps: tuple[str, ...]


def build_sanitized_launch_plan(
    launcher: str,
    python_executable: str,
    trusted_bootstrap_path: str,
    platform_args: Sequence[str],
    environment: Mapping[str, str],
    attempt_id: str,
    handoff_locator: str,
    custom_import_paths: Sequence[str] = (),
    *,
    platform_owned_cwd: str,
) -> SanitizedLaunchPlan:
    """Build the proposed launcher-independent pre-Python contract.

    ``-I -S`` prevents the caller's working directory, Python environment
    variables, user site, and automatic site initialization from influencing
    startup.  The bootstrap is an absolute file under a platform-owned working
    directory; it is not imported by module name.  The real product still needs
    to package and permission this artifact in every launcher image.
    """

    allowed_args = LAUNCHER_ATTEMPT_ARG_ALLOWLIST.get(launcher)
    if allowed_args is None:
        raise ValueError(f"unsupported launcher '{launcher}'")
    if ATTEMPT_ID_ARGUMENT not in allowed_args:
        raise ValueError(f"launcher '{launcher}' is not allowed to propagate the resource-stats attempt ID")
    if HANDOFF_LOCATOR_ARGUMENT not in allowed_args:
        raise ValueError(f"launcher '{launcher}' is not allowed to propagate the resource-stats handoff locator")
    if not isinstance(python_executable, str) or not Path(python_executable).is_absolute():
        raise ValueError("python_executable must be an absolute path")
    if not isinstance(platform_owned_cwd, str) or not Path(platform_owned_cwd).is_absolute():
        raise ValueError("platform_owned_cwd must be an absolute path")
    if not isinstance(trusted_bootstrap_path, str) or not Path(trusted_bootstrap_path).is_absolute():
        raise ValueError("trusted_bootstrap_path must be an absolute path")
    normalized_cwd = Path(platform_owned_cwd).resolve()
    normalized_bootstrap = Path(trusted_bootstrap_path).resolve()
    try:
        normalized_bootstrap.relative_to(normalized_cwd)
    except ValueError as exc:
        raise ValueError("trusted_bootstrap_path must be inside platform_owned_cwd") from exc

    attempt_id = _require_attempt_id(attempt_id)
    handoff_locator = _require_handoff_locator(handoff_locator)
    platform_args = tuple(str(arg) for arg in platform_args)
    if any(
        _contains_attempt_argument(arg)
        or arg == HANDOFF_LOCATOR_ARGUMENT
        or arg.startswith(f"{HANDOFF_LOCATOR_ARGUMENT}=")
        for arg in platform_args
    ):
        raise ValueError(
            "resource-stats identity and handoff arguments are injected only by the fixed launcher allowlist"
        )

    custom_import_paths = tuple(str(path) for path in custom_import_paths)
    if any(not path for path in custom_import_paths):
        raise ValueError("custom import paths must be non-empty")
    for custom_path in custom_import_paths:
        if any(custom_path in arg for arg in platform_args):
            raise ValueError("custom import paths may not be present in pre-Python platform arguments")

    # The original mapping is not modified.  That makes the plan safe to reuse
    # for each launcher and proves the caller cannot retain a stale custom path.
    pre_python_environment = {
        str(name): str(value) for name, value in environment.items() if str(name) in _PRE_PYTHON_ENV_ALLOWLIST
    }
    argv = (
        python_executable,
        "-I",
        "-S",
        "-u",
        str(normalized_bootstrap),
        *platform_args,
        ATTEMPT_ID_ARGUMENT,
        attempt_id,
        HANDOFF_LOCATOR_ARGUMENT,
        handoff_locator,
    )
    return SanitizedLaunchPlan(
        launcher=launcher,
        attempt_id=attempt_id,
        handoff_locator=handoff_locator,
        platform_owned_cwd=str(normalized_cwd),
        trusted_bootstrap_path=str(normalized_bootstrap),
        argv=argv,
        pre_python_environment=pre_python_environment,
        post_snapshot_custom_import_paths=custom_import_paths,
        bootstrap_steps=(
            "chdir_to_platform_owned_directory",
            "start_isolated_python_without_site_initialization",
            "capture_platform_owned_start_snapshot",
            "persist_start_fragment_to_supervisor_owned_store",
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


class SupervisorOwnedAttemptStore:
    """Supervisor-side durable, write-once attempt records outside the worker workspace."""

    def __init__(self, supervisor_owned_root: Path, job_writable_root: Path):
        self.supervisor_owned_root = Path(supervisor_owned_root).resolve()
        self.job_writable_root = Path(job_writable_root).resolve()
        if _path_is_within(self.supervisor_owned_root, self.job_writable_root) or _path_is_within(
            self.job_writable_root, self.supervisor_owned_root
        ):
            raise ValueError("supervisor-owned fragment storage must not overlap job-writable storage")
        self.supervisor_owned_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def fragment_path(self, job_id: str, attempt_id: str, fragment_name: str) -> Path:
        job_id = _require_path_id(job_id, "job_id")
        attempt_id = _require_attempt_id(attempt_id)
        if fragment_name not in _ALL_FRAGMENT_NAMES:
            raise ValueError(f"unsupported fragment name '{fragment_name}'")
        return self.supervisor_owned_root / "resource_stats" / "attempts" / job_id / attempt_id / fragment_name

    def persist_worker_fragment(
        self, job_id: str, attempt_id: str, fragment_name: str, worker_record: Mapping[str, Any]
    ) -> FragmentReceipt:
        """Persist a worker-produced start/final fragment after supervisor receipt.

        Supervisor-owned storage prevents a worker from changing accepted bytes
        later, but the values remain a worker self-report.  The trust labels make
        that distinction explicit rather than calling worker files immutable.
        """

        if fragment_name not in _WORKER_FRAGMENT_NAMES:
            raise ValueError("only start.json and final.json may be worker-produced fragments")
        job_id = _require_path_id(job_id, "job_id")
        attempt_id = _require_attempt_id(attempt_id)
        if worker_record.get("job_id") != job_id or worker_record.get("attempt_id") != attempt_id:
            raise ValueError("worker fragment identity must match the supervisor-issued job and attempt identity")
        record = copy.deepcopy(dict(worker_record))
        record["trust"] = {
            "storage_owner": "site_supervisor",
            "storage_scope": "outside_job_writable_workspace",
            "content_origin": "worker_self_reported",
            "integrity": "write_once_after_supervisor_receipt",
            "authenticated_handoff_required": True,
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
        """Close a resource window whose worker final is absent, without inventing one."""

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
            "worker_final": {"state": "absent"},
            "resource_window": {
                "clock_owner": "site_supervisor",
                "basis": "supervisor_confirmed_acquire_release",
            },
            "resource_observations": {"state": "not_invented", "coverage": "partial"},
            "trust": {
                "storage_owner": "site_supervisor",
                "storage_scope": "outside_job_writable_workspace",
                "content_origin": "supervisor_observed_lifecycle",
                "integrity": "write_once_supervisor_owned",
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
