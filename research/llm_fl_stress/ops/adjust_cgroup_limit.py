#!/usr/bin/env python3

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

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def main() -> int:
    invocation_directory = Path.cwd()
    parser = argparse.ArgumentParser(description="Adjust and audit an active stress-test cgroup memory limit.")
    parser.add_argument("--ssh-config", type=Path, required=True)
    parser.add_argument("--ssh-alias", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--host-label", required=True)
    parser.add_argument("--memory-max-gib", type=float, required=True)
    parser.add_argument("--memory-high-gib", type=float)
    parser.add_argument("--output-root", type=Path, default=Path("research/llm_fl_stress/runs"))
    args = parser.parse_args()
    for value, description in (
        (args.ssh_alias, "SSH alias"),
        (args.run_id, "run ID"),
        (args.host_label, "host label"),
    ):
        if not _SAFE_NAME.fullmatch(value):
            parser.error(f"unsafe {description}: {value!r}")
    if args.memory_max_gib <= 0:
        parser.error("--memory-max-gib must be positive")
    if args.memory_high_gib is not None and args.memory_high_gib <= 0:
        parser.error("--memory-high-gib must be positive")
    if args.memory_high_gib is not None and args.memory_high_gib > args.memory_max_gib:
        parser.error("--memory-high-gib must not exceed --memory-max-gib")

    memory_max_bytes = int(args.memory_max_gib * (1024**3))
    memory_high_bytes = int(args.memory_high_gib * (1024**3)) if args.memory_high_gib is not None else None
    cgroup_root = f"/sys/fs/cgroup/llm-stress-{args.run_id[-8:]}-{args.host_label}"
    command = (
        f"printf '%s\\n' {memory_max_bytes} | sudo tee {cgroup_root}/memory.max >/dev/null; "
        f"cat {cgroup_root}/memory.current; cat {cgroup_root}/memory.max; cat {cgroup_root}/memory.events"
    )
    result = subprocess.run(
        ["ssh", "-F", str((invocation_directory / args.ssh_config).resolve()), args.ssh_alias, command],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    lines = result.stdout.splitlines()
    observed_memory_high_bytes = None
    if memory_high_bytes is not None:
        high_command = (
            f"printf '%s\\n' {memory_high_bytes} | sudo tee {cgroup_root}/memory.high >/dev/null; "
            f"cat {cgroup_root}/memory.high"
        )
        high_result = subprocess.run(
            ["ssh", "-F", str((invocation_directory / args.ssh_config).resolve()), args.ssh_alias, high_command],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        observed_memory_high_bytes = int(high_result.stdout.strip())
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event": "fault_injection_limit_adjusted",
        "source": "harness_control",
        "host": args.host_label,
        "cgroup_root": cgroup_root,
        "memory_max_bytes": memory_max_bytes,
        "memory_high_bytes": memory_high_bytes,
        "memory_current_bytes": int(lines[0]),
        "observed_memory_max_bytes": int(lines[1]),
        "observed_memory_high_bytes": observed_memory_high_bytes,
        "memory_events": {
            key: int(value)
            for key, value in (line.split() for line in lines[2:])
        },
    }
    run_root = (invocation_directory / args.output_root / args.run_id).resolve()
    if not run_root.is_dir():
        raise FileNotFoundError(f"run directory does not exist: {run_root}")
    event_line = json.dumps(record, sort_keys=True) + "\n"
    with (run_root / "events.jsonl").open("a", encoding="utf-8") as file:
        file.write(event_line)
    with (run_root / "logs" / "fault-control.jsonl").open("a", encoding="utf-8") as file:
        file.write(event_line)
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
