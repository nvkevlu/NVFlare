"""SSH orchestration for production host telemetry."""

import json
import re
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

from .artifacts import RunArtifacts
from .config import Scenario
from .preflight import assess_distributed_capacity


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_REMOTE_PATH = re.compile(r"^/?[A-Za-z0-9][A-Za-z0-9._/-]*$")


@dataclass(frozen=True)
class RemoteHost:
    label: str
    ssh_alias: str
    role: str
    process_pattern: str

    @property
    def process_search_pattern(self) -> str:
        return f"[{self.process_pattern[0]}]{self.process_pattern[1:]}"


@dataclass(frozen=True)
class ManagedCgroup:
    host_label: str
    root: str
    original_root: str
    service_pid: int
    memory_max_bytes: Optional[int]
    memory_high_bytes: Optional[int]


class ArtifactCheckpointWorker:
    def __init__(
        self,
        telemetry: "RemoteTelemetry",
        artifacts: RunArtifacts,
        interval_seconds: float,
        lease_expiry_utc: Optional[datetime] = None,
        final_checkpoint_lead_seconds: float = 900.0,
    ):
        if interval_seconds < 0:
            raise ValueError("artifact checkpoint interval cannot be negative")
        if final_checkpoint_lead_seconds < 0:
            raise ValueError("lease checkpoint lead cannot be negative")
        if lease_expiry_utc is not None and lease_expiry_utc.tzinfo is None:
            raise ValueError("lease expiry must include a timezone")
        self.telemetry = telemetry
        self.artifacts = artifacts
        self.interval_seconds = interval_seconds
        self.lease_expiry_utc = lease_expiry_utc
        self.final_checkpoint_lead_seconds = final_checkpoint_lead_seconds
        self.records: list[dict] = []
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lease_checkpoint_done = False

    def start(self) -> None:
        if self.interval_seconds == 0 and self.lease_expiry_utc is None:
            return
        self._thread = threading.Thread(target=self._run, name="artifact-checkpoint", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join()

    def _seconds_until_lease_checkpoint(self) -> Optional[float]:
        if self.lease_expiry_utc is None or self._lease_checkpoint_done:
            return None
        checkpoint_at = self.lease_expiry_utc.timestamp() - self.final_checkpoint_lead_seconds
        return checkpoint_at - datetime.now(timezone.utc).timestamp()

    def _record_checkpoint(self, reason: str) -> None:
        started_at = time.monotonic()
        started_at_utc = datetime.now(timezone.utc).isoformat()
        try:
            errors = self.telemetry.checkpoint_collect(self.artifacts)
        except Exception as error:
            errors = [f"checkpoint failed: {type(error).__name__}: {error}"]
        record = {
            "reason": reason,
            "started_at_utc": started_at_utc,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.monotonic() - started_at,
            "errors": errors,
        }
        self.records.append(record)
        self.artifacts.append_event("artifact_checkpoint", "harness", **record)

    def _run(self) -> None:
        next_periodic = time.monotonic() + self.interval_seconds if self.interval_seconds > 0 else None
        while not self._stop_event.is_set():
            lease_wait = self._seconds_until_lease_checkpoint()
            periodic_wait = None if next_periodic is None else next_periodic - time.monotonic()
            waits = [max(0.0, wait) for wait in (lease_wait, periodic_wait) if wait is not None]
            if not waits:
                return
            if self._stop_event.wait(min(waits)):
                return
            lease_wait = self._seconds_until_lease_checkpoint()
            lease_checkpointed = False
            if lease_wait is not None and lease_wait <= 0:
                self._lease_checkpoint_done = True
                self._record_checkpoint("lease_expiry_guard")
                lease_checkpointed = True
            if next_periodic is not None and time.monotonic() >= next_periodic:
                if not lease_checkpointed:
                    self._record_checkpoint("periodic")
                next_periodic = time.monotonic() + self.interval_seconds


def build_remote_hosts(
    scenario: Scenario,
    server_alias: str,
    client_alias_entries: Iterable[str] | None = None,
) -> list[RemoteHost]:
    client_aliases: Dict[str, str] = {}
    for entry in client_alias_entries or []:
        site, separator, ssh_alias = entry.partition("=")
        if not separator or not site or not ssh_alias:
            raise ValueError(f"invalid client SSH alias mapping: {entry!r}; expected site=ssh-alias")
        if site in client_aliases:
            raise ValueError(f"duplicate client SSH alias mapping: {site}")
        client_aliases[site] = ssh_alias
    unknown_sites = sorted(set(client_aliases) - set(scenario.federation.clients))
    if unknown_sites:
        raise ValueError(f"SSH aliases provided for unknown clients: {unknown_sites}")

    hosts = [
        RemoteHost(
            label="server",
            ssh_alias=server_alias,
            role="server",
            process_pattern="nvflare.private.fed.app.server.server_train",
        )
    ]
    for site in scenario.federation.clients:
        hosts.append(
            RemoteHost(
                label=site,
                ssh_alias=client_aliases.get(site, f"flare-{site}"),
                role="client",
                process_pattern="nvflare.private.fed.app.client.client_train",
            )
        )
    for host in hosts:
        if not _SAFE_NAME.fullmatch(host.label) or not _SAFE_NAME.fullmatch(host.ssh_alias):
            raise ValueError(f"unsafe remote host label or SSH alias: {host}")
    return hosts


class RemoteTelemetry:
    def __init__(
        self,
        ssh_config: Path,
        hosts: list[RemoteHost],
        source_root: str,
        service_root: str,
        output_root: str,
        run_id: str,
        sample_interval_seconds: float,
        gpu_sample_interval_seconds: float,
        memory_max_by_host: Dict[str, int] | None = None,
        memory_high_by_host: Dict[str, int] | None = None,
        expected_oom_hosts: Iterable[str] | None = None,
        memory_high_ratio: float = 0.9,
    ):
        self.ssh_config = ssh_config.resolve()
        self.hosts = hosts
        self.source_root = self._validate_remote_path(source_root, "source root")
        self.service_root = self._validate_remote_path(service_root, "service root")
        self.output_root = self._validate_remote_path(output_root, "output root")
        self.run_id = self._validate_name(run_id, "run ID")
        self.sample_interval_seconds = sample_interval_seconds
        self.gpu_sample_interval_seconds = gpu_sample_interval_seconds
        self.memory_max_by_host = dict(memory_max_by_host or {})
        self.memory_high_by_host = dict(memory_high_by_host or {})
        self.expected_oom_hosts = set(expected_oom_hosts or [])
        self.memory_high_ratio = memory_high_ratio
        self._managed_cgroups: Dict[str, ManagedCgroup] = {}
        self._collection_lock = threading.Lock()
        if not self.ssh_config.is_file():
            raise ValueError(f"SSH config does not exist: {self.ssh_config}")
        host_labels = {host.label for host in hosts}
        unknown_limits = sorted((set(self.memory_max_by_host) | set(self.memory_high_by_host)) - host_labels)
        unknown_expectations = sorted(self.expected_oom_hosts - host_labels)
        if unknown_limits or unknown_expectations:
            raise ValueError(
                f"unknown fault-injection hosts: limits={unknown_limits}, expectations={unknown_expectations}"
            )
        if not self.expected_oom_hosts.issubset(self.memory_max_by_host):
            raise ValueError("every expected OOM host must have a cgroup memory limit")
        if any(limit <= 0 for limit in self.memory_max_by_host.values()):
            raise ValueError("cgroup memory limits must be positive")
        if any(limit <= 0 for limit in self.memory_high_by_host.values()):
            raise ValueError("cgroup memory high thresholds must be positive")
        invalid_high_limits = sorted(
            label
            for label in set(self.memory_max_by_host) & set(self.memory_high_by_host)
            if self.memory_high_by_host[label] > self.memory_max_by_host[label]
        )
        if invalid_high_limits:
            raise ValueError(f"cgroup memory.high exceeds memory.max for: {invalid_high_limits}")
        if not 0 < self.memory_high_ratio <= 1:
            raise ValueError("cgroup memory high ratio must be in (0, 1]")

    @staticmethod
    def _validate_name(value: str, description: str) -> str:
        if not _SAFE_NAME.fullmatch(value):
            raise ValueError(f"unsafe {description}: {value!r}")
        return value

    @staticmethod
    def _validate_remote_path(value: str, description: str) -> str:
        if not _SAFE_REMOTE_PATH.fullmatch(value) or ".." in Path(value).parts or value == "/":
            raise ValueError(f"unsafe {description}: {value!r}")
        return value.rstrip("/")

    @staticmethod
    def _shell_path(value: str) -> str:
        return value if Path(value).is_absolute() else f"$HOME/{value}"

    @staticmethod
    def _rsync_path(value: str) -> str:
        return value if Path(value).is_absolute() else f"~/{value}"

    def _ssh(self, host: RemoteHost, command: str, timeout: float = 30.0) -> str:
        result = subprocess.run(
            ["ssh", "-F", str(self.ssh_config), host.ssh_alias, command],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()

    def _remote_run_suffix(self, host: RemoteHost) -> str:
        return f"{self.output_root}/{self.run_id}/{host.label}"

    def _service_pid(self, host: RemoteHost) -> int:
        output = self._ssh(host, f"pgrep -fo -- {shlex.quote(host.process_search_pattern)} || true")
        if not output.isdigit():
            raise RuntimeError(f"could not find {host.role} service process on {host.ssh_alias}")
        return int(output)

    def _configure_cgroup(self, host: RemoteHost, service_pid: int) -> ManagedCgroup:
        cgroup_line = self._ssh(host, f"cat /proc/{service_pid}/cgroup")
        original_relative = None
        for line in cgroup_line.splitlines():
            parts = line.split(":", 2)
            if len(parts) == 3 and parts[0] == "0" and parts[1] == "":
                original_relative = parts[2]
                break
        if original_relative is None or not original_relative.startswith("/"):
            raise RuntimeError(f"could not resolve cgroup for {host.label} PID {service_pid}")
        cgroup_name = f"llm-stress-{self.run_id[-8:]}-{host.label}"
        cgroup_root = f"/sys/fs/cgroup/{cgroup_name}"
        memory_max_bytes = self.memory_max_by_host.get(host.label)
        memory_high_bytes = self.memory_high_by_host.get(host.label)
        if memory_high_bytes is None and memory_max_bytes is not None:
            memory_high_bytes = int(memory_max_bytes * self.memory_high_ratio)
        commands = [f"sudo mkdir {shlex.quote(cgroup_root)}"]
        if memory_high_bytes is not None:
            commands.append(
                f"printf '%s\\n' {memory_high_bytes} | "
                f"sudo tee {shlex.quote(cgroup_root + '/memory.high')} >/dev/null"
            )
        if memory_max_bytes is not None:
            commands.append(
                f"printf '%s\\n' {memory_max_bytes} | "
                f"sudo tee {shlex.quote(cgroup_root + '/memory.max')} >/dev/null"
            )
        commands.extend(
            [
                f"printf '%s\\n' 0 | sudo tee {shlex.quote(cgroup_root + '/memory.swap.max')} >/dev/null",
                f"printf '%s\\n' 1 | sudo tee {shlex.quote(cgroup_root + '/memory.oom.group')} >/dev/null",
                f"printf '%s\\n' {service_pid} | sudo tee {shlex.quote(cgroup_root + '/cgroup.procs')} >/dev/null",
            ]
        )
        command = "; ".join(commands)
        self._ssh(host, command)
        managed = ManagedCgroup(
            host_label=host.label,
            root=cgroup_root,
            original_root=f"/sys/fs/cgroup{original_relative.rstrip('/')}",
            service_pid=service_pid,
            memory_max_bytes=memory_max_bytes,
            memory_high_bytes=memory_high_bytes,
        )
        self._managed_cgroups[host.label] = managed
        return managed

    def capacity_preflight(self, scenario: Scenario) -> dict:
        snapshots = {}
        snapshot_code = (
            "import json, psutil, shutil; "
            "m=psutil.virtual_memory(); d=shutil.disk_usage(str(__import__('pathlib').Path.home())); "
            "print(json.dumps({'available_memory_bytes':m.available,'total_memory_bytes':m.total,"
            "'free_disk_bytes':d.free,'total_disk_bytes':d.total}))"
        )
        python_path = self._shell_path(f"{self.source_root}/.venv/bin/python")
        for host in self.hosts:
            output = self._ssh(host, f"{python_path} -c {shlex.quote(snapshot_code)}")
            snapshots[host.label] = json.loads(output)
        client_labels = [host.label for host in self.hosts if host.role == "client"]
        return assess_distributed_capacity(scenario, snapshots, "server", client_labels)

    def check_service_environment(self, expected: Dict[str, str]) -> dict:
        expected = dict(expected)
        if not expected:
            return {"passed": True, "expected": {}, "hosts": {}, "mismatches": []}

        observed_by_host = {}
        mismatches = []
        for host in self.hosts:
            pid = self._service_pid(host)
            output = self._ssh(host, f"tr '\\0' '\\n' < /proc/{pid}/environ")
            environment = {}
            for line in output.splitlines():
                name, separator, value = line.partition("=")
                if separator and name in expected:
                    environment[name] = value
            observed_by_host[host.label] = environment
            for name, expected_value in expected.items():
                observed_value = environment.get(name)
                if observed_value != expected_value:
                    mismatches.append(
                        {
                            "host": host.label,
                            "name": name,
                            "expected": expected_value,
                            "observed": observed_value,
                        }
                    )
        return {
            "passed": not mismatches,
            "expected": expected,
            "hosts": observed_by_host,
            "mismatches": mismatches,
        }

    def _monitor_session_name(self, host: RemoteHost) -> str:
        return f"llm-{self.run_id[-8:]}-{host.label}"[:80]

    def start(self) -> None:
        for host in self.hosts:
            service_log = self._shell_path(f"{self.service_root}.service.log")
            self._ssh(host, f": > {service_log}")
            pid = self._service_pid(host)
            managed = (
                self._configure_cgroup(host, pid)
                if host.label in self.memory_max_by_host or host.label in self.memory_high_by_host
                else None
            )
            session_name = self._monitor_session_name(host)
            run_suffix = self._remote_run_suffix(host)
            run_root = self._shell_path(run_suffix)
            source_root = self._shell_path(self.source_root)
            cgroup_argument = f" --cgroup-root {shlex.quote(managed.root)}" if managed else ""
            monitor_command = (
                f"cd {source_root}/research/llm_fl_stress && "
                f"PYTHONPATH={source_root}/research/llm_fl_stress "
                f"{source_root}/.venv/bin/python -m harness.monitor "
                f"--pid {pid} --output-dir {run_root} "
                f"--interval {self.sample_interval_seconds} --gpu-interval {self.gpu_sample_interval_seconds} "
                f"--host-label {shlex.quote(host.label)}{cgroup_argument} "
                f"--stop-file {run_root}/monitor.stop "
                f">{run_root}/monitor.log 2>&1"
            )
            start_command = (
                f"tmux kill-session -t {shlex.quote(session_name)} 2>/dev/null || true; "
                f"mkdir -p {run_root}; rm -f {run_root}/monitor.stop; "
                f"tmux new-session -d -s {shlex.quote(session_name)} {shlex.quote(monitor_command)}"
            )
            self._ssh(host, start_command)
        self._wait_until_ready()

    @staticmethod
    def _parse_memory_events(output: str) -> Dict[str, int]:
        result = {}
        for line in output.splitlines():
            try:
                key, value = line.split()
                result[key] = int(value)
            except ValueError:
                continue
        return result

    def managed_memory_events(self) -> Dict[str, Dict[str, int]]:
        observed = {}
        hosts_by_label = {host.label: host for host in self.hosts}
        for label, managed in sorted(self._managed_cgroups.items()):
            output = self._ssh(hosts_by_label[label], f"cat {shlex.quote(managed.root + '/memory.events')}")
            observed[label] = self._parse_memory_events(output)
        return observed

    def expected_oom_events(self) -> Dict[str, Dict[str, int]]:
        observed = self.managed_memory_events()
        return {label: observed[label] for label in sorted(self.expected_oom_hosts) if label in observed}

    def expected_ooms_observed(self) -> tuple[bool, Dict[str, Dict[str, int]]]:
        observed = self.expected_oom_events()
        passed = bool(self.expected_oom_hosts) and all(
            observed.get(label, {}).get("oom_kill", 0) > 0 for label in self.expected_oom_hosts
        )
        return passed, observed

    def cgroup_metadata(self) -> Dict[str, dict]:
        return {
            label: {
                "root": managed.root,
                "original_root": managed.original_root,
                "service_pid": managed.service_pid,
                "memory_max_bytes": managed.memory_max_bytes,
                "memory_high_bytes": managed.memory_high_bytes,
            }
            for label, managed in sorted(self._managed_cgroups.items())
        }

    def _wait_until_ready(self, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        pending = {host.label: host for host in self.hosts}
        while pending and time.monotonic() < deadline:
            for label, host in list(pending.items()):
                run_suffix = self._remote_run_suffix(host)
                process_samples = self._shell_path(f"{run_suffix}/process_samples.csv")
                ready = self._ssh(
                    host,
                    f"test -s {process_samples} && echo ready || true",
                )
                if ready == "ready":
                    pending.pop(label)
            if pending:
                time.sleep(0.25)
        if pending:
            raise TimeoutError(f"remote telemetry did not become ready: {sorted(pending)}")

    def _snapshot_cgroups(self, suffix: str) -> list[str]:
        errors = []
        hosts_by_label = {host.label: host for host in self.hosts}
        for label, managed in self._managed_cgroups.items():
            host = hosts_by_label[label]
            run_suffix = self._remote_run_suffix(host)
            run_root = self._shell_path(run_suffix)
            snapshot_command = "; ".join(
                f"test ! -r {shlex.quote(managed.root + '/' + name)} || "
                f"cat {shlex.quote(managed.root + '/' + name)} > "
                f'{run_root}/cgroup-{name.replace(".", "-")}-{suffix}.txt'
                for name in (
                    "memory.current",
                    "memory.peak",
                    "memory.max",
                    "memory.high",
                    "memory.events",
                    "memory.stat",
                    "memory.pressure",
                )
            )
            try:
                self._ssh(host, snapshot_command)
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(f"snapshot cgroup {label}: {error}")
        return errors

    def _collect_artifacts(self, artifacts: RunArtifacts) -> list[str]:
        errors = []
        host_metrics_root = artifacts.metrics_dir / "hosts"
        host_metrics_root.mkdir(parents=True, exist_ok=True)
        for host in self.hosts:
            destination = host_metrics_root / host.label
            destination.mkdir(parents=True, exist_ok=True)
            remote_source = f"{host.ssh_alias}:{self._rsync_path(self._remote_run_suffix(host))}/"
            try:
                subprocess.run(
                    [
                        "rsync",
                        "-az",
                        "-e",
                        f"ssh -F {shlex.quote(str(self.ssh_config))}",
                        remote_source,
                        f"{destination}/",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                monitor_log = destination / "monitor.log"
                if monitor_log.is_file():
                    shutil.copy2(monitor_log, artifacts.logs_dir / f"remote-monitor-{host.label}.log")
                if host.role == "server":
                    for file_name in (
                        "process_samples.csv",
                        "gpu_samples.csv",
                        "cgroup_samples.csv",
                        "monitor_errors.jsonl",
                    ):
                        source = destination / file_name
                        if source.is_file():
                            shutil.copy2(source, artifacts.metrics_dir / file_name)
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(f"collect {host.label}: {error}")
            service_log = artifacts.logs_dir / f"service-{host.label}.log"
            try:
                subprocess.run(
                    [
                        "rsync",
                        "-az",
                        "-e",
                        f"ssh -F {shlex.quote(str(self.ssh_config))}",
                        f"{host.ssh_alias}:{self._rsync_path(self.service_root)}.service.log",
                        str(service_log),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(f"collect service log {host.label}: {error}")
        return errors

    def checkpoint_collect(self, artifacts: RunArtifacts) -> list[str]:
        with self._collection_lock:
            errors = self._snapshot_cgroups("checkpoint")
            errors.extend(self._collect_artifacts(artifacts))
            return errors

    def stop_and_collect(self, artifacts: RunArtifacts) -> list[str]:
        with self._collection_lock:
            return self._stop_and_collect(artifacts)

    def _stop_and_collect(self, artifacts: RunArtifacts) -> list[str]:
        errors = self._snapshot_cgroups("final")
        hosts_by_label = {host.label: host for host in self.hosts}
        for host in self.hosts:
            run_suffix = self._remote_run_suffix(host)
            monitor_stop = self._shell_path(f"{run_suffix}/monitor.stop")
            try:
                self._ssh(host, f"touch {monitor_stop}")
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(f"stop {host.label}: {error}")
        time.sleep(max(1.0, self.sample_interval_seconds * 2))
        errors.extend(self._collect_artifacts(artifacts))
        for label, managed in self._managed_cgroups.items():
            host = hosts_by_label[label]
            move_script = (
                f"if test -d {shlex.quote(managed.root)}; then "
                f"for pid in $(cat {shlex.quote(managed.root + '/cgroup.procs')}); do "
                f"printf '%s\\n' \"$pid\" > {shlex.quote(managed.original_root + '/cgroup.procs')}; "
                "done; fi"
            )
            try:
                self._ssh(
                    host,
                    f"sudo sh -c {shlex.quote(move_script)}; sudo rmdir {shlex.quote(managed.root)}",
                )
                if not self._ssh(host, f"pgrep -fo -- {shlex.quote(host.process_search_pattern)} || true"):
                    self._restart_service(host)
            except (OSError, subprocess.SubprocessError, TimeoutError) as error:
                errors.append(f"restore cgroup/service {label}: {error}")
        return errors

    def _restart_service(self, host: RemoteHost) -> None:
        source_root = self._shell_path(self.source_root)
        service_root = self._shell_path(self.service_root)
        tmp_root = self._shell_path(f"{str(Path(self.service_root).parent)}/tmp")
        service_log = f"{service_root}.service.log"
        command = (
            "tmux kill-session -t flare-service 2>/dev/null || true; "
            f"rm -f {service_root}/shutdown.fl; mkdir -p {tmp_root}; "
            f"tmux new-session -d -s flare-service -c {service_root} "
            f'"env PATH={source_root}/.venv/bin:$PATH '
            f"PYTHONPATH={source_root} TMPDIR={tmp_root} "
            f"bash -c 'ulimit -Sn 65535; exec ./startup/sub_start.sh --once >> {service_log} 2>&1'\""
        )
        self._ssh(host, command)
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if self._ssh(host, f"pgrep -fo -- {shlex.quote(host.process_search_pattern)} || true"):
                return
            time.sleep(0.5)
        raise TimeoutError(f"restored {host.role} service did not become ready on {host.ssh_alias}")
