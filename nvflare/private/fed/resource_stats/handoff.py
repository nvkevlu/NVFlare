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

"""Symlink-safe read/write of the private, job-process-owned terminal handoff.

The job process (child) writes this file to hand its own resource_time,
workspace_filesystem, and retained_content observations to the semi-trusted
parent process; the parent (``collector.assemble_participant_summary``) reads
it back, but does not trust anything else the child wrote (notably not
``job_id``/``participant_name``, which the parent asserts itself).
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

from .contract import MAX_PARTICIPANT_SUMMARY_BYTES, ContractError
from .contract import canonical_json_bytes as _contract_json_bytes
from .contract import validate_record

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


class InvalidTerminalHandoff(ValueError):
    """Raised when the child-to-parent handoff is malformed or oversized."""


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Serialize a record deterministically while keeping stored files readable."""

    return _contract_json_bytes(value)


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
