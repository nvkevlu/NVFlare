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

"""Conservative host-capacity preflight calculations."""

from typing import Any, Dict

from .config import Scenario


def assess_capacity(scenario: Scenario, available_memory_bytes: int, free_disk_bytes: int) -> Dict[str, Any]:
    required_memory = scenario.planned_simulation_capacity_bytes
    required_disk = scenario.planned_disk_capacity_bytes
    checks = {
        "memory": {
            "available_bytes": available_memory_bytes,
            "planned_required_bytes": required_memory,
            "passed": available_memory_bytes >= required_memory,
        },
        "disk": {
            "available_bytes": free_disk_bytes,
            "planned_required_bytes": required_disk,
            "passed": free_disk_bytes >= required_disk,
        },
    }
    risks = [name for name, check in checks.items() if not check["passed"]]
    return {"passed": not risks, "risks": risks, "checks": checks}


def assess_distributed_capacity(
    scenario: Scenario,
    host_snapshots: Dict[str, Dict[str, int]],
    server_label: str,
    client_labels: list[str],
) -> Dict[str, Any]:
    expected_labels = [server_label, *client_labels]
    missing_hosts = [label for label in expected_labels if label not in host_snapshots]
    checks: Dict[str, Dict[str, Any]] = {}
    risks = [f"{label}.missing" for label in missing_hosts]
    client_disk_required = scenario.payload_bytes * 2
    for label in expected_labels:
        snapshot = host_snapshots.get(label)
        if snapshot is None:
            continue
        is_server = label == server_label
        required_memory = (
            scenario.planned_server_capacity_bytes if is_server else scenario.planned_client_capacity_bytes
        )
        required_disk = scenario.planned_disk_capacity_bytes if is_server else client_disk_required
        memory_check = {
            "available_bytes": snapshot["available_memory_bytes"],
            "planned_required_bytes": required_memory,
            "passed": snapshot["available_memory_bytes"] >= required_memory,
        }
        disk_check = {
            "available_bytes": snapshot["free_disk_bytes"],
            "planned_required_bytes": required_disk,
            "passed": snapshot["free_disk_bytes"] >= required_disk,
        }
        checks[label] = {"memory": memory_check, "disk": disk_check}
        if not memory_check["passed"]:
            risks.append(f"{label}.memory")
        if not disk_check["passed"]:
            risks.append(f"{label}.disk")
    return {"passed": not risks, "risks": risks, "checks": checks, "snapshots": host_snapshots}
