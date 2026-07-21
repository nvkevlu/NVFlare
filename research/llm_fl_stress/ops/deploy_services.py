#!/usr/bin/env python3
"""Deploy generated startup kits and manage fixed FLARE service processes."""

import argparse
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_REMOTE_PATH = re.compile(r"^/?[A-Za-z0-9][A-Za-z0-9._/-]*$")


@dataclass(frozen=True)
class Participant:
    ssh_alias: str
    kit_name: str
    role: str

    @property
    def process_pattern(self) -> str:
        if self.role == "server":
            return "nvflare.private.fed.app.server.server_train"
        return "nvflare.private.fed.app.client.client_train"

    @property
    def process_search_pattern(self) -> str:
        return f"[{self.process_pattern[0]}]{self.process_pattern[1:]}"


def _parse_participant(value: str, role: str) -> Participant:
    ssh_alias, separator, kit_name = value.partition("=")
    if not separator or not _SAFE_NAME.fullmatch(ssh_alias) or not _SAFE_NAME.fullmatch(kit_name):
        raise argparse.ArgumentTypeError(f"expected safe SSH_ALIAS=KIT_NAME, got {value!r}")
    return Participant(ssh_alias=ssh_alias, kit_name=kit_name, role=role)


def _validate_remote_path(value: str, description: str) -> str:
    path = Path(value)
    if not _SAFE_REMOTE_PATH.fullmatch(value) or ".." in path.parts or value == "/":
        raise ValueError(f"unsafe {description}: {value!r}")
    return value.rstrip("/")


def _shell_path(value: str) -> str:
    return value if Path(value).is_absolute() else f"$HOME/{value}"


def _rsync_path(value: str) -> str:
    return value if Path(value).is_absolute() else f"~/{value}"


class ServiceDeployer:
    def __init__(
        self,
        ssh_config: Path,
        kit_root: Path,
        remote_source_root: str,
        remote_kit_root: str,
        participants: list[Participant],
        service_environment: dict[str, str] | None = None,
    ):
        self.ssh_config = ssh_config.resolve()
        self.kit_root = kit_root.resolve()
        self.remote_source_root = _validate_remote_path(remote_source_root, "remote source root")
        self.remote_kit_root = _validate_remote_path(remote_kit_root, "remote kit root")
        if Path(self.remote_kit_root).is_absolute():
            self.remote_tmp_root = str(Path(self.remote_kit_root).parent / "tmp")
        else:
            self.remote_tmp_root = "nvflare-stress-tmp"
        self.participants = participants
        self.service_environment = dict(service_environment or {})
        if not self.ssh_config.is_file():
            raise ValueError(f"SSH config does not exist: {self.ssh_config}")
        if not self.kit_root.is_dir():
            raise ValueError(f"kit root does not exist: {self.kit_root}")
        if len([participant for participant in participants if participant.role == "server"]) != 1:
            raise ValueError("exactly one server participant is required")
        for participant in participants:
            startup_dir = self.kit_root / participant.kit_name / "startup"
            if not startup_dir.is_dir():
                raise ValueError(f"startup kit is missing for {participant.kit_name}: {startup_dir}")

    def _ssh(self, participant: Participant, command: str, timeout: float = 30.0) -> str:
        result = subprocess.run(
            ["ssh", "-F", str(self.ssh_config), participant.ssh_alias, command],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()

    def _stop(self, participant: Participant) -> None:
        self._ssh(participant, "tmux kill-session -t flare-service 2>/dev/null || true")
        remote_kit_root = _shell_path(self.remote_kit_root)
        self._ssh(
            participant,
            f"test ! -d {remote_kit_root} || touch {remote_kit_root}/shutdown.fl",
        )
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            remaining = self._ssh(
                participant,
                f"pgrep -f -- {shlex.quote(participant.process_search_pattern)} || true",
            )
            if not remaining:
                return
            time.sleep(0.5)
        raise RuntimeError(f"old {participant.role} process remains on {participant.ssh_alias}: {remaining}")

    def _rotate_kit(self, participant: Participant, backup_suffix: str) -> None:
        destination = _shell_path(self.remote_kit_root)
        backup = f"{destination}.{backup_suffix}"
        self._ssh(
            participant,
            f"if test -d {destination}; then mv {destination} {backup}; fi; mkdir -p {destination}",
        )
        subprocess.run(
            [
                "rsync",
                "-az",
                "-e",
                f"ssh -F {self.ssh_config}",
                f"{self.kit_root / participant.kit_name}/",
                f"{participant.ssh_alias}:{_rsync_path(self.remote_kit_root)}/",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def _start(self, participant: Participant) -> None:
        remote_source_root = _shell_path(self.remote_source_root)
        remote_kit_root = _shell_path(self.remote_kit_root)
        remote_tmp_root = _shell_path(self.remote_tmp_root)
        service_log = f"{remote_kit_root}.service.log"
        service_environment = " ".join(
            f"{name}={shlex.quote(value)}" for name, value in sorted(self.service_environment.items())
        )
        if service_environment:
            service_environment += " "
        command = (
            f"mkdir -p {remote_tmp_root}; : > {service_log}; "
            f"tmux new-session -d -s flare-service -c {remote_kit_root} "
            f'"env PATH={remote_source_root}/.venv/bin:$PATH '
            f"PYTHONPATH={remote_source_root} TMPDIR={remote_tmp_root} "
            f"{service_environment}"
            f"bash -c \'ulimit -Sn 65535; exec ./startup/sub_start.sh --once >> {service_log} 2>&1\'\""
        )
        self._ssh(participant, command)

    def _wait_ready(self, participant: Participant, timeout: float = 30.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            process = self._ssh(
                participant,
                f"pgrep -fa -- {shlex.quote(participant.process_search_pattern)} | head -n 1 || true",
            )
            if process:
                return process
            time.sleep(0.5)
        raise TimeoutError(f"{participant.role} did not become ready on {participant.ssh_alias}")

    def deploy(self) -> dict:
        backup_suffix = "pre-endpoint-fix-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for participant in self.participants:
            self._stop(participant)
        for participant in self.participants:
            self._rotate_kit(participant, backup_suffix)

        server = next(participant for participant in self.participants if participant.role == "server")
        clients = [participant for participant in self.participants if participant.role == "client"]
        process_lines = {}
        self._start(server)
        process_lines[server.ssh_alias] = self._wait_ready(server)
        for participant in clients:
            self._start(participant)
        for participant in clients:
            process_lines[participant.ssh_alias] = self._wait_ready(participant)
        return {
            "status": "ready",
            "participants": [
                {
                    "ssh_alias": participant.ssh_alias,
                    "kit_name": participant.kit_name,
                    "role": participant.role,
                    "process": process_lines[participant.ssh_alias],
                }
                for participant in self.participants
            ],
            "service_environment": self.service_environment,
        }


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a positive integer")
    return parsed


def build_streaming_environment(
    chunk_size: int | None,
    window_size: int | None,
    ack_interval: int | None,
    max_out_seq_chunks: int | None,
) -> dict:
    values = {
        "NVFLARE_STREAMING_CHUNK_SIZE": chunk_size,
        "NVFLARE_STREAMING_WINDOW_SIZE": window_size,
        "NVFLARE_STREAMING_ACK_INTERVAL": ack_interval,
        "NVFLARE_STREAMING_MAX_OUT_SEQ_CHUNKS": max_out_seq_chunks,
    }
    return {name: str(value) for name, value in values.items() if value is not None}


def main() -> int:
    invocation_directory = Path.cwd()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-config", type=Path, required=True)
    parser.add_argument("--kit-root", type=Path, required=True)
    parser.add_argument("--server", required=True, help="SSH_ALIAS=KIT_NAME")
    parser.add_argument("--client", action="append", default=[], help="SSH_ALIAS=KIT_NAME")
    parser.add_argument("--remote-source-root", default="nvflare-stress-src")
    parser.add_argument("--remote-kit-root", default="nvflare-stress-kit")
    parser.add_argument("--streaming-chunk-size", type=_positive_int)
    parser.add_argument("--streaming-window-size", type=_positive_int)
    parser.add_argument("--streaming-ack-interval", type=_positive_int)
    parser.add_argument("--streaming-max-out-seq-chunks", type=_positive_int)
    args = parser.parse_args()
    participants = [_parse_participant(args.server, "server")]
    participants.extend(_parse_participant(value, "client") for value in args.client)
    deployer = ServiceDeployer(
        ssh_config=(invocation_directory / args.ssh_config).resolve(),
        kit_root=(invocation_directory / args.kit_root).resolve(),
        remote_source_root=args.remote_source_root,
        remote_kit_root=args.remote_kit_root,
        participants=participants,
        service_environment=build_streaming_environment(
            args.streaming_chunk_size,
            args.streaming_window_size,
            args.streaming_ack_interval,
            args.streaming_max_out_seq_chunks,
        ),
    )
    print(json.dumps(deployer.deploy(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
