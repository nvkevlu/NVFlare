#!/usr/bin/env python3
"""Show a read-only snapshot of an active distributed stress run."""

import argparse
import csv
import io
import json
import re
import shlex
import subprocess
from pathlib import Path


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_REMOTE_PATH = re.compile(r"^/?[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _parse_host(value: str) -> tuple[str, str]:
    label, separator, ssh_alias = value.partition("=")
    if not separator or not _SAFE_NAME.fullmatch(label) or not _SAFE_NAME.fullmatch(ssh_alias):
        raise argparse.ArgumentTypeError(f"expected safe LABEL=SSH_ALIAS, got {value!r}")
    return label, ssh_alias


def _validate_remote_path(value: str) -> str:
    path = Path(value)
    if not _SAFE_REMOTE_PATH.fullmatch(value) or ".." in path.parts or value == "/":
        raise ValueError(f"unsafe remote path: {value!r}")
    return value.rstrip("/")


def _shell_path(value: str) -> str:
    return value if Path(value).is_absolute() else f"$HOME/{value}"


def _ssh(ssh_config: Path, ssh_alias: str, command: str) -> str:
    result = subprocess.run(
        ["ssh", "-F", str(ssh_config), ssh_alias, command],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout


def _latest_metrics(csv_text: str) -> dict:
    rows = [
        row
        for row in csv.DictReader(io.StringIO(csv_text))
        if str(row.get("sample_index", "")).isdigit()
    ]
    if not rows:
        return {"sample_index": None, "elapsed_seconds": None, "roles_rss_gib": {}}
    sample_index = max(int(row["sample_index"]) for row in rows)
    current_rows = [row for row in rows if int(row["sample_index"]) == sample_index]
    roles = {}
    for row in current_rows:
        role = row.get("role") or "unknown"
        roles[role] = roles.get(role, 0) + int(row.get("rss_bytes") or 0)
    last = current_rows[-1]
    return {
        "sample_index": sample_index,
        "elapsed_seconds": float(last["elapsed_seconds"]),
        "roles_rss_gib": {role: round(value / 1024**3, 3) for role, value in sorted(roles.items())},
        "system_available_gib": round(int(last["system_available_bytes"]) / 1024**3, 3),
        "disk_free_gib": round(int(last["disk_free_bytes"]) / 1024**3, 3),
    }


def _service_snapshot(ssh_config: Path, ssh_alias: str, label: str) -> dict:
    if label == "server":
        pattern = "[n]vflare.private.fed.app.server.server_train"
    else:
        pattern = "[n]vflare.private.fed.app.client.client_train"
    output = _ssh(
        ssh_config,
        ssh_alias,
        f"pid=$(pgrep -fo -- {shlex.quote(pattern)} || true); "
        'test -z "$pid" || { printf "%s\\n" "$pid"; cat "/proc/$pid/cgroup"; }',
    ).splitlines()
    return {
        "running": bool(output),
        "pid": int(output[0]) if output and output[0].isdigit() else None,
        "cgroup": output[1].split(":", 2)[-1] if len(output) > 1 else None,
    }


def main() -> int:
    invocation_directory = Path.cwd()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-config", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--host", action="append", required=True, help="LABEL=SSH_ALIAS")
    parser.add_argument("--remote-output-root", default="nvflare-stress-runs")
    parser.add_argument("--remote-service-root", default="nvflare-stress-kit")
    args = parser.parse_args()
    if not _SAFE_NAME.fullmatch(args.run_id):
        parser.error("--run-id contains unsafe characters")
    hosts = [_parse_host(value) for value in args.host]
    output_root = _validate_remote_path(args.remote_output_root)
    service_root = _validate_remote_path(args.remote_service_root)
    ssh_config = (invocation_directory / args.ssh_config).resolve()
    if not ssh_config.is_file():
        parser.error(f"SSH config does not exist: {ssh_config}")

    snapshots = {}
    status_pattern = "Round [0-9]+|download|upload|persist|Finished FedAvg|EXECUTION_EXCEPTION|Traceback"
    for label, ssh_alias in hosts:
        remote_metrics = _shell_path(f"{output_root}/{args.run_id}/{label}/process_samples.csv")
        metrics_text = _ssh(
            ssh_config,
            ssh_alias,
            f"head -n 1 {remote_metrics}; tail -n 250 {remote_metrics}",
        )
        service_log = _shell_path(f"{service_root}.service.log")
        status_text = _ssh(
            ssh_config,
            ssh_alias,
            f"grep -E {shlex.quote(status_pattern)} {service_log} | tail -n 12 || true",
        )
        snapshots[label] = {
            **_latest_metrics(metrics_text),
            "service": _service_snapshot(ssh_config, ssh_alias, label),
            "recent_status": [line for line in status_text.splitlines() if line],
        }
    print(json.dumps({"run_id": args.run_id, "hosts": snapshots}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
