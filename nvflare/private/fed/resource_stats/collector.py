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

"""Collect one final resource-statistics report in an NVFlare job process.

This module is the thin orchestration facade for the resource-stats feature:
it composes the per-dimension capacity probes (``probes/``), the pure
capacity-recording core (``accumulator.py``), and the private
child-to-parent handoff file I/O (``handoff.py``) into the two entry points
the rest of NVFlare actually calls -- ``JobResourceCollector`` (runs inside
the job process) and ``assemble_participant_summary`` (runs in the semi-
trusted parent, which asserts identity rather than trusting anything else the
child wrote).  Names that used to live directly in this file (probe
internals, ``ResourceCapacityRecorder``, terminal-handoff read/write/remove)
are re-exported here unchanged so existing imports of
``nvflare.private.fed.resource_stats.collector`` keep working.
"""

from __future__ import annotations

import datetime
import os
import stat
import time
from collections.abc import Callable, Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

from .accumulator import ClockOrderError, CollectorClosedError, ResourceCapacityRecorder
from .contract import SCHEMA_VERSION, U128_MAX, ContractError, normalize_message_traffic, validate_record
from .cpu_consumed import CpuConsumedAccountant, install_cpu_accountant
from .f3_counter import MAX_F3_SENT_TO_GROUPS
from .handoff import (
    INTERNAL_HANDOFF_KIND,
    INTERNAL_HANDOFF_VERSION,
    MAX_TERMINAL_HANDOFF_BYTES,
    RESOURCE_STATS_DIR,
    STAGING_DIR,
    TERMINAL_HANDOFF_FILE,
    InvalidTerminalHandoff,
    _validate_handoff,
    canonical_json_bytes,
    read_terminal_handoff,
    remove_terminal_handoff,
    terminal_handoff_path,
    write_terminal_handoff,
)
from .probes.cgroup_linux import discover_cgroups, probe_cpu, probe_memory
from .probes.gpu_nvidia import probe_gpu

__all__ = [
    "ClockOrderError",
    "CollectorClosedError",
    "ResourceCapacityRecorder",
    "InvalidTerminalHandoff",
    "INTERNAL_HANDOFF_KIND",
    "INTERNAL_HANDOFF_VERSION",
    "MAX_TERMINAL_HANDOFF_BYTES",
    "RESOURCE_STATS_DIR",
    "STAGING_DIR",
    "TERMINAL_HANDOFF_FILE",
    "canonical_json_bytes",
    "terminal_handoff_path",
    "write_terminal_handoff",
    "read_terminal_handoff",
    "remove_terminal_handoff",
    "probe_cpu",
    "probe_memory",
    "probe_gpu",
    "probe_capacity",
    "observe_workspace_filesystem",
    "observe_retained_content",
    "JobResourceCollector",
    "assemble_participant_summary",
    "merge_f3_snapshots",
    "CapacitySnapshot",
    "CapacityProbe",
]

_SLURM_NODE_COUNT_ENV = "NVFL_NNODES"

# Fixed collection budgets, not operator settings. Time is checked between
# entries; Python cannot interrupt a blocked filesystem syscall.
_MAX_RETAINED_ENTRIES = 100_000
_MAX_RETAINED_DEPTH = 64
_MAX_RETAINED_SCAN_SECONDS = 1.0

CapacitySnapshot = Mapping[str, Any]
CapacityProbe = Callable[[], CapacitySnapshot]


def utc_now() -> str:
    """Return a schema-compatible UTC wall-clock timestamp."""

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def probe_capacity() -> dict[str, Any]:
    """Return only capacity members that can be established from this process."""

    capacity = {}
    discovery = discover_cgroups()
    cpu = probe_cpu(discovery)
    if cpu is not None:
        capacity["cpu"] = cpu
    memory = probe_memory(discovery)
    if memory is not None:
        capacity["memory"] = memory
    gpu = probe_gpu()
    if gpu is not None:
        capacity["gpu"] = gpu
    return capacity


def observe_workspace_filesystem(workspace_path: str | Path) -> dict[str, Any]:
    """Observe only the filesystem containing the existing job workspace."""

    try:
        stats = os.statvfs(os.fspath(workspace_path))
        capacity = stats.f_blocks * stats.f_frsize
    except (OSError, TypeError, ValueError):
        return {"status": "unavailable", "issues": ["observation_incomplete"]}
    if stats.f_frsize <= 0 or stats.f_blocks <= 0 or capacity <= 0:
        return {"status": "unavailable", "issues": ["observation_incomplete"]}
    return {"capacity_bytes": str(capacity)}


def observe_retained_content(run_dir: str | Path) -> dict[str, Any]:
    """Observe the logical size of regular files in one job run directory.

    Includes logs, configuration, and inputs; excludes the top-level
    resource_stats directory. Symlinks and non-regular entries are skipped.
    Depth-first streaming avoids materializing a large directory's entries.
    A budget or traversal error yields an honest partial subtotal; failure
    before any directory entry or empty directory can be observed is unavailable.
    This remains a non-atomic self-report, including ordinary mounted subtrees.
    """

    root = Path(run_dir)
    deadline = time.monotonic() + _MAX_RETAINED_SCAN_SECONDS
    try:
        if not stat.S_ISDIR(root.lstat().st_mode):
            return {"status": "unavailable", "issues": ["observation_incomplete"]}
        root_entries = os.scandir(root)
    except OSError:
        return {"status": "unavailable", "issues": ["observation_incomplete"]}

    total = 0
    entries_seen = 0
    incomplete = False
    observed = False
    stack = [(root_entries, 0)]
    try:
        while stack:
            if time.monotonic() >= deadline:
                incomplete = True
                break
            iterator, depth = stack[-1]
            try:
                entry = next(iterator)
            except StopIteration:
                observed = True
                iterator.close()
                stack.pop()
                continue
            except OSError:
                incomplete = True
                iterator.close()
                stack.pop()
                continue

            if entries_seen >= _MAX_RETAINED_ENTRIES:
                incomplete = True
                break
            entries_seen += 1
            observed = True
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError:
                incomplete = True
                continue

            if stat.S_ISREG(entry_stat.st_mode):
                if entry_stat.st_size < 0 or entry_stat.st_size > U128_MAX - total:
                    incomplete = True
                    break
                total += entry_stat.st_size
            elif stat.S_ISDIR(entry_stat.st_mode):
                if depth == 0 and entry.name == RESOURCE_STATS_DIR:
                    continue
                if depth >= _MAX_RETAINED_DEPTH:
                    incomplete = True
                    continue
                try:
                    stack.append((os.scandir(entry.path), depth + 1))
                except OSError:
                    incomplete = True
    finally:
        for iterator, _depth in stack:
            iterator.close()

    if incomplete:
        if not observed:
            return {"status": "unavailable", "issues": ["observation_incomplete"]}
        return {"status": "partial", "issues": ["observation_incomplete"], "bytes": str(total)}
    return {"bytes": str(total)}


def _unavailable(issue: str) -> dict[str, Any]:
    return {"status": "unavailable", "issues": [issue]}


class JobResourceCollector:
    """Own one job-process accumulator and produce its terminal handoff.

    Runs inside the job process itself (the untrusted self-report producer):
    constructed by worker_process.py/runner_process.py after their existing
    workspace download and custom-path refresh, before application construction.
    Python startup imports may already have executed. Collection does not
    change the launcher's import behavior. Measurements are site self-reports,
    not tamper-proof data.
    """

    def __init__(
        self,
        run_dir: str | Path,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
        cpu_clock_ns: Callable[[], int] = time.monotonic_ns,
        capacity_probe: CapacityProbe = probe_capacity,
        prior_observation_incomplete: bool = False,
    ):
        self.run_dir = Path(run_dir)
        raw_node_count = os.environ.get(_SLURM_NODE_COUNT_ENV)
        try:
            self._multi_node_incomplete = raw_node_count is not None and int(raw_node_count) != 1
        except ValueError:
            # This is launcher-owned evidence.  If it is malformed, do not
            # present the rank-zero observation as complete.
            self._multi_node_incomplete = _SLURM_NODE_COUNT_ENV in os.environ
        self._accumulator = ResourceCapacityRecorder(clock_ns=clock_ns)
        try:
            capacity = capacity_probe()
            if not isinstance(capacity, Mapping):
                raise TypeError("capacity probe must return a mapping")
            self._accumulator.observe(capacity)
            if prior_observation_incomplete:
                self._accumulator.mark_prior_observation_incomplete()
        except Exception:
            self._accumulator.mark_gap()
        # Align the CPU baseline with the start of the capacity-observation window.
        # Probe work is platform setup, not job execution CPU.
        self._cpu_consumed = CpuConsumedAccountant(
            clock_ns=cpu_clock_ns,
            prior_observation_incomplete=prior_observation_incomplete,
            known_attribution_incomplete=self._multi_node_incomplete,
        )
        install_cpu_accountant(self._cpu_consumed)

    def observe_capacity_change(self, capacity: Mapping[str, Any]) -> None:
        """Record a confirmed runtime resource change for future schedulers."""

        self._accumulator.observe(capacity)

    def mark_cpu_consumption_incomplete(self) -> None:
        """Mark an unfinished job callback as a CPU accounting coverage gap."""

        self._cpu_consumed.mark_attribution_incomplete()

    def finish(self, *, child_f3: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        """Build the one private child handoff at process finalization."""

        cpu_consumed = self._cpu_consumed.finish()
        resource_capacity = self._accumulator.finish()
        if self._multi_node_incomplete:
            # The current Slurm worker runs the collector on rank zero only.
            # Rank-zero cgroup/CUDA values do not describe the other allocated
            # nodes, so publishing those numbers would understate the site.
            resource_capacity = _unavailable("unsupported")
        return {
            "internal_version": INTERNAL_HANDOFF_VERSION,
            "kind": INTERNAL_HANDOFF_KIND,
            "resource_capacity": resource_capacity,
            "cpu_consumed": cpu_consumed,
            "workspace_filesystem": observe_workspace_filesystem(self.run_dir),
            "retained_content": observe_retained_content(self.run_dir),
            "child_f3": deepcopy(child_f3) if child_f3 is not None else _unavailable("observation_incomplete"),
        }


def merge_f3_snapshots(
    child_f3: Optional[Mapping[str, Any]],
    parent_f3: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    """Merge the child and parent execution-environment F3 contributions.

    A participant spans two processes today: its short-lived job process and
    its long-lived parent.  Both are required for complete attribution.  A
    missing side therefore produces a partial result when the other side has
    numeric data, rather than silently presenting that subtotal as complete.
    """

    sent_to: dict[str, tuple[int, int]] = {}
    numeric_count = 0
    issues = set()
    missing_contribution = False
    for value in (child_f3, parent_f3):
        if not isinstance(value, Mapping):
            missing_contribution = True
            continue
        try:
            value = normalize_message_traffic(value)
        except ContractError:
            return {"status": "unavailable", "issues": ["malformed_source"]}
        status = value.get("status", "reported")
        if status in {"reported", "partial"}:
            for group in value["sent_to"]:
                name = group["participant_name"]
                payload_bytes = int(group["payload_bytes"])
                messages = int(group["messages"])
                if name not in sent_to and len(sent_to) >= MAX_F3_SENT_TO_GROUPS:
                    issues.add("counter_gap")
                    continue
                old_payload, old_messages = sent_to.get(name, (0, 0))
                if old_payload > U128_MAX - payload_bytes or old_messages > U128_MAX - messages:
                    return {"status": "unavailable", "issues": ["malformed_source"]}
                sent_to[name] = (old_payload + payload_bytes, old_messages + messages)
            numeric_count += 1
            if status == "partial":
                issues.update(value["issues"])
        else:
            missing_contribution = True
            if set(value["issues"]) & {"observation_incomplete", "malformed_source"}:
                issues.add("observation_incomplete")
            else:
                issues.add("attribution_incomplete")

    if not numeric_count:
        issue = "observation_incomplete" if "observation_incomplete" in issues else "attribution_incomplete"
        return {"status": "unavailable", "issues": [issue]}

    payload_bytes = sum(value[0] for value in sent_to.values())
    messages = sum(value[1] for value in sent_to.values())
    if payload_bytes > U128_MAX or messages > U128_MAX:
        return {"status": "unavailable", "issues": ["malformed_source"]}

    result = {
        "sent_to": [
            {"participant_name": name, "payload_bytes": str(sent_to[name][0]), "messages": str(sent_to[name][1])}
            for name in sorted(sent_to)
        ],
    }
    if missing_contribution or issues:
        if missing_contribution:
            issues.add("attribution_incomplete")
        result["status"] = "partial"
        result["issues"] = sorted(issues)
    return result


def assemble_participant_summary(
    *,
    job_id: str,
    participant_name: str,
    child_handoff: Optional[Mapping[str, Any]],
    parent_f3: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Create the sole public report, binding identity in the parent process.

    Runs in the semi-trusted parent (client_executor.py on the client side;
    the server's own equivalent call on the server side): ``job_id`` and
    ``participant_name`` are asserted by the caller, not read from anything
    the child wrote, and the result degrades to "observation_incomplete"
    whenever the child handoff is missing or fails validation.
    """

    if child_handoff is None:
        resource_capacity = _unavailable("observation_incomplete")
        cpu_consumed = _unavailable("observation_incomplete")
        workspace_filesystem = _unavailable("observation_incomplete")
        retained_content = _unavailable("observation_incomplete")
        child_f3 = None
    else:
        try:
            validated = _validate_handoff(child_handoff)
        except InvalidTerminalHandoff:
            validated = None
        if validated is None:
            resource_capacity = _unavailable("observation_incomplete")
            cpu_consumed = _unavailable("observation_incomplete")
            workspace_filesystem = _unavailable("observation_incomplete")
            retained_content = _unavailable("observation_incomplete")
            child_f3 = None
        else:
            resource_capacity = validated["resource_capacity"]
            cpu_consumed = validated["cpu_consumed"]
            workspace_filesystem = validated["workspace_filesystem"]
            retained_content = validated["retained_content"]
            child_f3 = validated["child_f3"]

    message_traffic = merge_f3_snapshots(child_f3, parent_f3)
    report = {
        "schema_version": SCHEMA_VERSION,
        "kind": "nvflare.resource_stats.participant_summary",
        "job_id": job_id,
        "participant_name": participant_name,
        "reported_at": utc_now(),
        "resource_capacity": resource_capacity,
        "cpu_consumed": cpu_consumed,
        "workspace_filesystem": workspace_filesystem,
        "retained_content": retained_content,
        "message_traffic": message_traffic,
    }
    validate_record(report)
    return report
