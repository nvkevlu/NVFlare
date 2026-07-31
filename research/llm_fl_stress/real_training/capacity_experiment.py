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

"""Run one result-producing capacity experiment with allocation telemetry."""

from __future__ import annotations

import argparse
import json
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable

try:
    from .qualification import _AllocationMonitor, _GpuMonitor
except ImportError:
    from qualification import _AllocationMonitor, _GpuMonitor


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _define_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--scratch-root", required=True, type=Path)
    parser.add_argument("--gpu-count", required=True, type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _define_parser().parse_args(argv)
    command = list(args.command)
    if command and command[0] == "--":
        command.pop(0)
    if not command:
        raise ValueError("a child experiment command is required after --")
    if args.gpu_count != 8:
        raise ValueError("this capacity experiment requires exactly eight GPUs")
    if not args.artifact_root.is_absolute() or not args.scratch_root.is_absolute():
        raise ValueError("--artifact-root and --scratch-root must be absolute")

    args.artifact_root.mkdir(parents=True, exist_ok=True)
    args.scratch_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        args.artifact_root / "configuration.json",
        {
            "event": "real_training_capacity_configuration",
            "status": "PASS",
            "experiment_scope": "single-client-fsdp2-capacity",
            "gpu_mapping": {"site-1": list(range(args.gpu_count))},
            "command": command,
        },
    )

    gpu_monitor = _GpuMonitor(args.artifact_root / "gpu-samples.csv")
    allocation_monitor = _AllocationMonitor(
        args.artifact_root / "allocation-memory.jsonl",
        args.scratch_root,
    )
    child: subprocess.Popen | None = None
    received_signal: int | None = None

    def forward_signal(signum: int, _frame: Any) -> None:
        nonlocal received_signal
        received_signal = signum
        if child is not None and child.poll() is None:
            child.send_signal(signum)

    signal.signal(signal.SIGTERM, forward_signal)
    signal.signal(signal.SIGINT, forward_signal)

    started_at = time.monotonic()
    gpu_summary: dict[str, Any] | None = None
    allocation_summary: dict[str, Any] | None = None
    child_return_code: int | None = None
    launch_error: str | None = None
    try:
        gpu_monitor.start()
        allocation_monitor.start()
        child = subprocess.Popen(command)
        child_return_code = child.wait()
    except Exception as exc:
        launch_error = f"{type(exc).__name__}: {exc}"
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child_return_code = child.wait(timeout=30.0)
            except subprocess.TimeoutExpired:
                child.kill()
                child_return_code = child.wait(timeout=30.0)
    finally:
        try:
            allocation_summary = allocation_monitor.close()
        except Exception as exc:
            allocation_summary = {
                "event": "real_training_allocation_monitor",
                "status": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            }
        try:
            gpu_summary = gpu_monitor.close()
        except Exception as exc:
            gpu_summary = {
                "event": "real_training_gpu_monitor",
                "status": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            }
        _write_json(args.artifact_root / "allocation-monitor.json", allocation_summary)
        _write_json(args.artifact_root / "gpu-monitor.json", gpu_summary)

    failures = []
    if launch_error:
        failures.append(launch_error)
    if child_return_code != 0:
        failures.append(f"child experiment exited with {child_return_code}")
    if gpu_summary.get("status") != "PASS":
        failures.append("GPU monitor did not prove activity on every allocated GPU")
    if allocation_summary.get("status") != "PASS":
        failures.append("allocation memory monitor did not pass")
    summary = {
        "event": "real_training_capacity_experiment",
        "status": "FAIL" if failures else "PASS",
        "experiment_scope": "single-client-fsdp2-capacity",
        "child_return_code": child_return_code,
        "received_signal": received_signal,
        "elapsed_seconds": time.monotonic() - started_at,
        "gpu_monitor": gpu_summary,
        "allocation_monitor": allocation_summary,
        "failures": failures,
    }
    _write_json(args.artifact_root / "qualification.json", summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if not failures else child_return_code or 1


if __name__ == "__main__":
    raise SystemExit(main())
