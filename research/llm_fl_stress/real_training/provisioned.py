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

"""One-node production NVFLARE service orchestration for cluster qualification."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Callable, Iterable

ADMIN_NAME = "admin@nvidia.com"
CLIENT_NAMES = ("site-1", "site-2")
SERVER_NAME = "localhost"
_FATAL_JOB_MARKERS = (
    "cannot sync with server Runner",
    "distributed round failed:",
    "do_one_task execute exception:",
    "Client execution failed",
)
_TOKEN_PATTERNS = (
    re.compile(r"(?i)(sent token:\s*)[^\s.]+"),
    re.compile(r"(?i)(token:\s*)[^\s]+"),
    re.compile(r"(?i)(ssid:\s*)[^\s]+"),
)


def _append_no_proxy(environment: dict[str, str]) -> None:
    for name in ("NO_PROXY", "no_proxy"):
        existing = environment.get(name, "")
        values = [value for value in existing.split(",") if value]
        for value in ("localhost", "127.0.0.1"):
            if value not in values:
                values.append(value)
        environment[name] = ",".join(values)


def _json_events(paths: Iterable[Path], event: str) -> list[dict[str, Any]]:
    records = []
    for path in paths:
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                marker = line.find("{")
                if marker < 0:
                    continue
                try:
                    record = json.loads(line[marker:])
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and record.get("event") == event:
                    records.append(record)
    return records


def _tail(path: Path, max_bytes: int = 16_384) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - max_bytes))
        return stream.read().decode("utf-8", errors="replace")


def _matching_lines(path: Path, needle: str) -> str:
    """Read only matching lines without assuming they are near the end of a large service log."""

    if not path.is_file():
        return ""
    matches = []
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            if needle in line:
                matches.append(line.rstrip("\r\n"))
    return "\n".join(matches)


def _redact_log_text(text: str) -> str:
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(r"\1<redacted>", text)
    return text


def _reserve_local_ports(count: int) -> list[socket.socket]:
    reservations = []
    try:
        for _ in range(count):
            reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            reservation.bind(("127.0.0.1", 0))
            reservation.listen(1)
            reservations.append(reservation)
    except Exception:
        for reservation in reservations:
            reservation.close()
        raise
    return reservations


@dataclass
class _Service:
    name: str
    process: subprocess.Popen
    log_path: Path
    log_stream: IO[str]


class PersistedModelWatcher:
    """Capture model persistence metadata before production server cleanup removes the run workspace."""

    def __init__(
        self,
        federation: "LocalProductionFederation",
        job_id: str,
        destination: Path,
        *,
        expected_count: int = 1,
        checkpoint_inspector: Callable[[Path], dict[str, Any]] | None = None,
    ):
        if expected_count <= 0:
            raise ValueError("expected_count must be greater than zero")
        self.federation = federation
        self.job_id = job_id
        self.destination = destination
        self.expected_count = expected_count
        self.checkpoint_inspector = checkpoint_inspector
        self.result: dict[str, Any] | None = None
        self.results: list[dict[str, Any]] = []
        self.error: Exception | None = None
        self._done = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"model-watch-{job_id[:8]}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            service_log = self.federation.services[SERVER_NAME].log_path
            offset = 0
            partial = ""
            while not self._stop.is_set():
                with service_log.open(encoding="utf-8", errors="replace") as stream:
                    stream.seek(offset)
                    chunk = stream.read()
                    offset = stream.tell()
                complete_lines = (partial + chunk).splitlines(keepends=True)
                partial = ""
                if complete_lines and not complete_lines[-1].endswith(("\n", "\r")):
                    partial = complete_lines.pop()
                persisted_count = sum(
                    self.job_id in line and "End persist model on server." in line for line in complete_lines
                )
                for _ in range(persisted_count):
                    model_files = []
                    model_path = None
                    model_deadline = time.monotonic() + 30.0
                    while time.monotonic() < model_deadline and not self._stop.is_set():
                        try:
                            root = self.federation.job_root(SERVER_NAME, self.job_id)
                            model_files = sorted(root.rglob("FL_global_model.pt"))
                            if len(model_files) == 1 and model_files[0].stat().st_size > 0:
                                model_path = model_files[0]
                                break
                        except (OSError, RuntimeError):
                            model_files = []
                        self._stop.wait(0.05)
                    if model_path is None:
                        raise RuntimeError(
                            f"persistence completed but expected one non-empty global model for {self.job_id}; "
                            f"found {[str(path) for path in model_files]}"
                        )
                    model_size = model_path.stat().st_size
                    self.destination.mkdir(parents=True, exist_ok=True)
                    metadata = Path(f"{model_path}.metadata")
                    if metadata.is_file():
                        shutil.copy2(metadata, self.destination / metadata.name)
                    result = {
                        "path": str(model_path),
                        "size_bytes": model_size,
                        "metadata_copied": metadata.is_file(),
                        "sequence": len(self.results),
                    }
                    if self.checkpoint_inspector is not None:
                        result.update(self.checkpoint_inspector(model_path))
                    self.results.append(result)
                    self.result = result
                    result_name = (
                        "persisted_model.json"
                        if self.expected_count == 1
                        else f"persisted_model-{len(self.results) - 1}.json"
                    )
                    (self.destination / result_name).write_text(
                        json.dumps(result, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    if len(self.results) >= self.expected_count:
                        self._done.set()
                        return
                self._stop.wait(0.05)
        except Exception as exc:
            self.error = exc
            self._done.set()

    def wait(self, timeout: float = 10.0) -> dict[str, Any]:
        if not self._done.wait(timeout):
            raise TimeoutError(f"did not capture persisted model metadata for job {self.job_id}")
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise RuntimeError(f"persisted model watcher for {self.job_id} completed without a result")
        return self.result

    def wait_all(self, timeout: float = 30.0) -> list[dict[str, Any]]:
        if not self._done.wait(timeout):
            raise TimeoutError(
                f"captured {len(self.results)}/{self.expected_count} persisted models for job {self.job_id}"
            )
        if self.error is not None:
            raise self.error
        if len(self.results) != self.expected_count:
            raise RuntimeError(
                f"persisted model watcher for {self.job_id} captured "
                f"{len(self.results)}/{self.expected_count} results"
            )
        return list(self.results)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)


class LocalProductionFederation:
    """Provision and supervise real TLS server/client services on one host."""

    def __init__(self, private_root: Path, evidence_root: Path, *, startup_timeout: float = 90.0):
        self.private_root = private_root.resolve()
        self.evidence_root = evidence_root.resolve()
        self.startup_timeout = startup_timeout
        self.kits: dict[str, Path] = {}
        self.services: dict[str, _Service] = {}
        self.admin_kit: Path | None = None

    def _project(self, fed_port: int, admin_port: int) -> dict[str, Any]:
        return {
            "api_version": 3,
            "name": "llm_fsdp2_local",
            "description": "Ephemeral one-node two-client real-training qualification",
            "connection_security": "tls",
            "participants": [
                {
                    "name": SERVER_NAME,
                    "type": "server",
                    "org": "stress_test",
                    "default_host": "localhost",
                    "host_names": ["localhost", "127.0.0.1"],
                    "fed_learn_port": fed_port,
                    "admin_port": admin_port,
                },
                {"name": "site-1", "type": "client", "org": "stress_test"},
                {"name": "site-2", "type": "client", "org": "stress_test"},
                {
                    "name": ADMIN_NAME,
                    "type": "admin",
                    "org": "stress_test",
                    "role": "project_admin",
                },
            ],
            "builders": [
                {"path": "nvflare.lighter.impl.workspace.WorkspaceBuilder"},
                {
                    "path": "nvflare.lighter.impl.static_file.StaticFileBuilder",
                    "args": {
                        "config_folder": "config",
                        "scheme": "grpc",
                    },
                },
                {"path": "nvflare.lighter.impl.cert.CertBuilder"},
                {"path": "nvflare.lighter.impl.signature.SignatureBuilder"},
            ],
        }

    def provision(self) -> dict[str, Path]:
        """Create private startup kits while keeping both selected ports reserved."""

        from nvflare.lighter.provision import provision

        self.private_root.mkdir(parents=True, exist_ok=False)
        (self.private_root / ".nvflare-qualification-private").write_text(
            "ephemeral startup kits and job workspaces\n",
            encoding="utf-8",
        )
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        reservations = _reserve_local_ports(2)
        try:
            fed_port, admin_port = (reservation.getsockname()[1] for reservation in reservations)
            context = provision(
                types.SimpleNamespace(gen_scripts=True),
                self._project(fed_port, admin_port),
                project_full_path="",
                workspace_full_path=str(self.private_root / "provision"),
            )
            production_root = Path(context["current_prod_dir"]).resolve()
            names = (SERVER_NAME, *CLIENT_NAMES, ADMIN_NAME)
            self.kits = {name: production_root / name for name in names}
            for name, kit in self.kits.items():
                if not (kit / "startup" / "sub_start.sh").is_file() and name != ADMIN_NAME:
                    raise RuntimeError(f"provisioned startup kit is incomplete for {name}: {kit}")
            self.admin_kit = self.kits[ADMIN_NAME]
        finally:
            for reservation in reservations:
                reservation.close()
        return dict(self.kits)

    def _start_service(self, name: str, cuda_visible_devices: str) -> None:
        kit = self.kits[name]
        log_path = self.private_root / "service-logs" / f"service-{name}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_stream = log_path.open("w", encoding="utf-8")
        environment = os.environ.copy()
        environment["CUDA_VISIBLE_DEVICES"] = cuda_visible_devices
        environment["NVFLARE_ENABLE_JEMALLOC_PRELOAD"] = "true"
        environment["TMPDIR"] = str(self.private_root / "tmp" / name)
        environment["PATH"] = f"{Path(sys.executable).parent}{os.pathsep}{environment.get('PATH', '')}"
        repo_root = Path(__file__).resolve().parents[3]
        python_path = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = f"{repo_root}{os.pathsep}{python_path}" if python_path else str(repo_root)
        Path(environment["TMPDIR"]).mkdir(parents=True, exist_ok=True)
        _append_no_proxy(environment)
        process = subprocess.Popen(
            ["bash", "startup/sub_start.sh", "--once"],
            cwd=kit,
            env=environment,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        self.services[name] = _Service(
            name=name,
            process=process,
            log_path=log_path,
            log_stream=log_stream,
        )

    def start(self) -> None:
        if not self.kits:
            raise RuntimeError("federation must be provisioned before services are started")
        self._start_service(SERVER_NAME, "")
        self._start_service("site-1", "0,1,2,3")
        self._start_service("site-2", "4,5,6,7")

    def _require_services_alive(self) -> None:
        failed = []
        for name, service in self.services.items():
            return_code = service.process.poll()
            if return_code is not None:
                failed.append(f"{name} exited with status {return_code}: {_tail(service.log_path)}")
        if failed:
            raise RuntimeError("NVFLARE service exited unexpectedly:\n" + "\n".join(failed))

    def wait_for_clients(self) -> list[str]:
        """Require the admin API to observe both exact client names before submission."""

        if self.admin_kit is None:
            raise RuntimeError("admin startup kit is unavailable")
        from nvflare.fuel.flare_api.flare_api import new_secure_session

        deadline = time.monotonic() + self.startup_timeout
        last_error = ""
        while time.monotonic() < deadline:
            self._require_services_alive()
            session = None
            try:
                session = new_secure_session(
                    username=ADMIN_NAME,
                    startup_kit_location=str(self.admin_kit),
                    timeout=min(5.0, max(1.0, deadline - time.monotonic())),
                    command_timeout=5.0,
                    auto_login_max_tries=1,
                )
                connected = sorted(client.name for client in session.get_connected_client_list())
                if connected == list(CLIENT_NAMES):
                    return connected
                last_error = f"connected clients are {connected!r}"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            finally:
                if session is not None:
                    session.close()
            time.sleep(1.0)
        raise TimeoutError(f"both production clients did not register within {self.startup_timeout}s: {last_error}")

    def job_root(self, participant: str, job_id: str) -> Path:
        kit = self.kits[participant]
        direct = kit / job_id
        if direct.is_dir():
            return direct
        matches = sorted(path for path in kit.rglob(job_id) if path.is_dir() and path.name == job_id)
        if len(matches) != 1:
            raise RuntimeError(
                f"expected exactly one {participant} workspace for job {job_id}, found {[str(path) for path in matches]}"
            )
        return matches[0]

    def _existing_job_roots(self, job_id: str) -> dict[str, Path]:
        roots = {}
        for participant in (SERVER_NAME, *CLIENT_NAMES):
            try:
                roots[participant] = self.job_root(participant, job_id)
            except RuntimeError:
                continue
        return roots

    @staticmethod
    def _logs(root: Path) -> list[Path]:
        files = set(root.rglob("*.log"))
        files.update(root.rglob("*.txt"))
        return sorted(files)

    def _fatal_job_error(self, job_id: str) -> str | None:
        for participant, root in self._existing_job_roots(job_id).items():
            for path in self._logs(root):
                text = _tail(path)
                for marker in _FATAL_JOB_MARKERS:
                    if marker in text:
                        return f"{participant} reported {marker!r} in {path}"
        return None

    def _ready_sites(self, job_id: str, model_path: Path) -> set[str]:
        sites = set()
        expected_model_path = str(model_path)
        for participant in CLIENT_NAMES:
            try:
                root = self.job_root(participant, job_id)
            except RuntimeError:
                continue
            for record in _json_events(self._logs(root), "real_training_client_ready"):
                if record.get("model_path") == expected_model_path:
                    sites.add(str(record.get("site_name")))
        return sites

    def job_events(self, participant: str, job_id: str, event: str) -> list[dict[str, Any]]:
        return _json_events(self._logs(self.job_root(participant, job_id)), event)

    def job_text(self, participant: str, job_id: str) -> str:
        return "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in self._logs(self.job_root(participant, job_id))
        )

    def service_job_text(self, participant: str, job_id: str) -> str:
        service = self.services[participant]
        return _matching_lines(service.log_path, job_id)

    def completion_progress(self, job_id: str) -> dict[str, bool]:
        server_text = self.service_job_text(SERVER_NAME, job_id)
        return {
            "aggregated_2_of_2": "Aggregated 2/2 results" in server_text,
            "persistence_started": "Start persist model on server." in server_text,
            "persistence_finished": "End persist model on server." in server_text,
        }

    @staticmethod
    def _abort(run, reason: str) -> dict[str, str]:
        result = {
            "event": "real_training_production_abort",
            "job_id": str(run.get_job_id()),
            "reason": reason,
            "status": "REQUESTED",
        }
        try:
            run.abort()
        except Exception as exc:
            result["status"] = "ERROR"
            result["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(result, sort_keys=True), flush=True)
        return result

    def wait_for_run(
        self,
        run,
        *,
        model_path: Path,
        ready_timeout: float,
        total_timeout: float,
        completion_grace_timeout: float = 0.0,
        poll_interval: float = 5.0,
    ) -> str:
        """Fail closed on missing clients, explicit client errors, or phase deadline."""

        job_id = run.get_job_id()
        started_at = time.monotonic()
        ready_deadline = started_at + ready_timeout
        total_deadline = started_at + total_timeout
        completion_grace_deadline = None
        last_status = "UNKNOWN"
        while True:
            self._require_services_alive()
            fatal_error = self._fatal_job_error(job_id)
            if fatal_error:
                self._abort(run, fatal_error)
                raise RuntimeError(fatal_error)

            ready_sites = self._ready_sites(job_id, model_path)
            now = time.monotonic()
            if now >= ready_deadline and ready_sites != set(CLIENT_NAMES):
                reason = (
                    f"job did not report both client-ready events within {ready_timeout}s; "
                    f"observed {sorted(ready_sites)}"
                )
                self._abort(run, reason)
                raise TimeoutError(
                    f"job {job_id} did not report both client-ready events within {ready_timeout}s; "
                    f"observed {sorted(ready_sites)}"
                )

            last_status = str(run.get_status() or "UNKNOWN")
            progress = self.completion_progress(job_id)
            print(
                json.dumps(
                    {
                        "completion_progress": progress,
                        "event": "real_training_production_progress",
                        "job_id": job_id,
                        "ready_sites": sorted(ready_sites),
                        "status": last_status,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            if last_status.startswith("FINISHED:"):
                if last_status != "FINISHED:COMPLETED":
                    raise RuntimeError(f"production job {job_id} ended with {last_status}")
                return last_status

            now = time.monotonic()
            if completion_grace_deadline is None and now >= total_deadline:
                if completion_grace_timeout > 0.0 and any(progress.values()):
                    completion_grace_deadline = now + completion_grace_timeout
                    print(
                        json.dumps(
                            {
                                "completion_grace_seconds": completion_grace_timeout,
                                "completion_progress": progress,
                                "event": "real_training_production_completion_grace",
                                "job_id": job_id,
                                "status": last_status,
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
                else:
                    reason = (
                        f"job did not finish within {total_timeout}s; "
                        f"status={last_status}; completion_progress={progress}"
                    )
                    self._abort(run, reason)
                    raise TimeoutError(f"production job {job_id} {reason}")
            elif completion_grace_deadline is not None and now >= completion_grace_deadline:
                reason = (
                    f"job did not finish within {total_timeout}s plus {completion_grace_timeout}s "
                    f"completion grace; status={last_status}; completion_progress={progress}"
                )
                self._abort(run, reason)
                raise TimeoutError(f"production job {job_id} {reason}")
            time.sleep(poll_interval)

    def collect_job_logs(self, job_id: str, destination: Path) -> dict[str, Path]:
        """Copy redacted job logs without startup kits or model tensors."""
        destination.mkdir(parents=True, exist_ok=True)
        roots = {}
        for participant in (SERVER_NAME, *CLIENT_NAMES):
            participant_root = destination / participant
            if participant == SERVER_NAME:
                try:
                    root = self.job_root(participant, job_id)
                except RuntimeError:
                    participant_root.mkdir(parents=True, exist_ok=True)
                    (participant_root / "service-job.log").write_text(
                        _redact_log_text(self.service_job_text(participant, job_id)) + "\n",
                        encoding="utf-8",
                    )
                    roots[participant] = participant_root
                    continue
            else:
                root = self.job_root(participant, job_id)
            roots[participant] = root
            for source in self._logs(root):
                relative = source.relative_to(root)
                target = participant_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    _redact_log_text(source.read_text(encoding="utf-8", errors="replace")),
                    encoding="utf-8",
                )
        return roots

    def wait_for_terminal(self, run, *, total_timeout: float, poll_interval: float = 2.0) -> str:
        """Wait for a small production job without model-specific ready events."""

        job_id = run.get_job_id()
        deadline = time.monotonic() + total_timeout
        last_status = "UNKNOWN"
        while time.monotonic() < deadline:
            self._require_services_alive()
            fatal_error = self._fatal_job_error(job_id)
            if fatal_error:
                self._abort(run, fatal_error)
                raise RuntimeError(fatal_error)
            last_status = str(run.get_status() or "UNKNOWN")
            if last_status.startswith("FINISHED:"):
                if last_status != "FINISHED:COMPLETED":
                    raise RuntimeError(f"production job {job_id} ended with {last_status}")
                return last_status
            time.sleep(poll_interval)
        self._abort(run, f"job did not finish within {total_timeout}s; status={last_status}")
        raise TimeoutError(f"production job {job_id} did not finish within {total_timeout}s; status={last_status}")

    def close(self) -> None:
        for kit in self.kits.values():
            try:
                (kit / "shutdown.fl").touch()
            except OSError:
                pass
        deadline = time.monotonic() + 10.0
        for service in self.services.values():
            remaining = max(0.0, deadline - time.monotonic())
            try:
                service.process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(service.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 5.0
        for service in self.services.values():
            remaining = max(0.0, deadline - time.monotonic())
            try:
                service.process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(service.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                service.process.wait(timeout=5.0)
            finally:
                service.log_stream.close()
            sanitized_path = self.evidence_root / f"service-{service.name}.log"
            sanitized_path.write_text(
                _redact_log_text(service.log_path.read_text(encoding="utf-8", errors="replace")),
                encoding="utf-8",
            )

    def __enter__(self) -> "LocalProductionFederation":
        try:
            self.provision()
            self.start()
            return self
        except Exception:
            self.close()
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
