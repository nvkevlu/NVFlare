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

"""Run directory creation and manifest writing."""

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

from .config import Scenario


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, sort_keys=True)
        file.write("\n")
    temporary_path.replace(path)


def _run_git(repo_root: Path, arguments: Iterable[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _swap_total_bytes() -> int | None:
    import psutil

    try:
        return psutil.swap_memory().total
    except (OSError, RuntimeError):
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class RunArtifacts:
    root: Path
    manifest_path: Path
    scenario_path: Path
    events_path: Path
    result_path: Path
    job_config_dir: Path
    workspace_dir: Path
    logs_dir: Path
    metrics_dir: Path
    report_dir: Path
    _event_lock: threading.Lock

    @classmethod
    def open_existing(cls, root: Path) -> "RunArtifacts":
        root = root.resolve()
        if not (root / "scenario.json").is_file():
            raise ValueError(f"not an LLM stress run directory: {root}")
        return cls(
            root=root,
            manifest_path=root / "manifest.json",
            scenario_path=root / "scenario.json",
            events_path=root / "events.jsonl",
            result_path=root / "result.json",
            job_config_dir=root / "job_config",
            workspace_dir=root / "flare_workspace",
            logs_dir=root / "logs",
            metrics_dir=root / "metrics",
            report_dir=root / "report",
            _event_lock=threading.Lock(),
        )

    @classmethod
    def create(
        cls,
        output_root: Path,
        scenario: Scenario,
        source_scenario_path: Path,
        repo_root: Path,
        command: list[str],
    ) -> "RunArtifacts":
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = "".join(
            character if character.isalnum() or character == "-" else "-" for character in scenario.name
        )
        run_id = f"{timestamp}-{safe_name}-{uuid.uuid4().hex[:8]}"
        root = output_root / run_id
        artifacts = cls(
            root=root,
            manifest_path=root / "manifest.json",
            scenario_path=root / "scenario.json",
            events_path=root / "events.jsonl",
            result_path=root / "result.json",
            job_config_dir=root / "job_config",
            workspace_dir=root / "flare_workspace",
            logs_dir=root / "logs",
            metrics_dir=root / "metrics",
            report_dir=root / "report",
            _event_lock=threading.Lock(),
        )
        for directory in (
            artifacts.root,
            artifacts.job_config_dir,
            artifacts.workspace_dir,
            artifacts.logs_dir,
            artifacts.metrics_dir,
            artifacts.report_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        write_json(artifacts.scenario_path, scenario.to_dict())
        artifacts.events_path.touch()
        artifacts._write_manifest(run_id, scenario, source_scenario_path, repo_root, command)
        return artifacts

    def _write_manifest(
        self,
        run_id: str,
        scenario: Scenario,
        source_scenario_path: Path,
        repo_root: Path,
        command: list[str],
    ) -> None:
        import psutil

        virtual_memory = psutil.virtual_memory()
        git_status = _run_git(repo_root, ["status", "--short"])
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "created_at": utc_now(),
            "command": command,
            "source": {
                "scenario_path": str(source_scenario_path.resolve()),
                "scenario_sha256": _sha256(source_scenario_path),
                "repo_root": str(repo_root.resolve()),
                "git_commit": _run_git(repo_root, ["rev-parse", "HEAD"]),
                "git_dirty": bool(git_status),
            },
            "host": {
                "hostname": platform.node(),
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": sys.version,
                "cpu_logical": psutil.cpu_count(logical=True),
                "cpu_physical": psutil.cpu_count(logical=False),
                "memory_total_bytes": virtual_memory.total,
                "swap_total_bytes": _swap_total_bytes(),
            },
            "software": {
                "nvflare": _package_version("nvflare") or _package_version("nvflare-nightly"),
                "torch": _package_version("torch"),
                "psutil": _package_version("psutil"),
            },
            "expected": {
                "parameter_count": scenario.model.parameter_count,
                "dtype": scenario.model.dtype,
                "payload_bytes": scenario.payload_bytes,
                "payload_gib": scenario.payload_gib,
                "wire_bytes_per_round": scenario.expected_wire_bytes_per_round,
                "planned_server_capacity_bytes": scenario.planned_server_capacity_bytes,
                "planned_client_capacity_bytes": scenario.planned_client_capacity_bytes,
                "planned_simulation_capacity_bytes": scenario.planned_simulation_capacity_bytes,
                "planned_disk_capacity_bytes": scenario.planned_disk_capacity_bytes,
            },
        }
        write_json(self.manifest_path, manifest)

    def append_event(self, event: str, source: str, **data: Any) -> None:
        record = {"timestamp_utc": utc_now(), "event": event, "source": source, **data}
        self.append_event_record(record)

    def append_event_record(self, record: Dict[str, Any]) -> None:
        with self._event_lock:
            with self.events_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, sort_keys=True) + "\n")

    def write_result(self, data: Dict[str, Any]) -> None:
        write_json(self.result_path, data)

    def relative_path(self, path: Path) -> str:
        return os.path.relpath(path, self.root)
