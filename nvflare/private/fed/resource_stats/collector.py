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
resource-time accounting core (``accumulator.py``), and the private
child-to-parent handoff file I/O (``handoff.py``) into the two entry points
the rest of NVFlare actually calls -- ``JobResourceCollector`` (runs inside
the job process) and ``assemble_participant_summary`` (runs in the semi-
trusted parent, which asserts identity rather than trusting anything else the
child wrote).  Names that used to live directly in this file (probe
internals, ``ResourceTimeAccumulator``, terminal-handoff read/write/remove)
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

from .accumulator import ClockOrderError, CollectorClosedError, ResourceTimeAccumulator
from .contract import INTEGER_PATTERN, MAX_ISSUES, PARTIAL_ISSUES, PARTICIPANT_NAME_PATTERN, U128_MAX, validate_record
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
from .probes.cgroup_linux import probe_cpu, probe_memory
from .probes.gpu_nvidia import probe_gpu

__all__ = [
    "ClockOrderError",
    "CollectorClosedError",
    "ResourceTimeAccumulator",
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

CapacitySnapshot = Mapping[str, Any]
CapacityProbe = Callable[[], CapacitySnapshot]


def utc_now() -> str:
    """Return a schema-compatible UTC wall-clock timestamp."""

    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def probe_capacity() -> dict[str, Any]:
    """Return only capacity members that can be established from this process."""

    capacity = {}
    cpu = probe_cpu()
    if cpu is not None:
        capacity["cpu"] = cpu
    memory = probe_memory()
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
    return {"status": "reported", "capacity_bytes": str(capacity)}


def observe_retained_content(run_dir: str | Path) -> dict[str, Any]:
    """Observe the logical size of regular files in one job run directory.

    This is a workspace-size measurement, not a curated result-artifact size:
    it also counts logs, config, and job inputs. A precise figure would need
    every built-in and custom workflow component to register which files it
    actually produced as "the result" -- judged not worth that integration
    cost against every workflow implementation, in exchange for a number that
    needs zero workflow-specific wiring. Only the platform's own resource_stats
    bookkeeping directory is excluded, since including it would make this
    figure grow from the act of measuring it rather than from job output.

    Symlinks and other non-regular entries contribute zero bytes and are not
    followed.  If the directory changes or becomes unreadable during the
    scan, the observed subtotal is returned as ``partial`` rather than being
    presented as a complete measurement.
    """

    root = Path(run_dir)
    try:
        if not stat.S_ISDIR(root.lstat().st_mode):
            return {"status": "unavailable", "issues": ["observation_incomplete"]}
    except OSError:
        return {"status": "unavailable", "issues": ["observation_incomplete"]}

    total = 0
    incomplete = False
    observed_directory = False

    def mark_incomplete(_error: OSError) -> None:
        nonlocal incomplete
        incomplete = True

    for current_dir, dir_names, file_names in os.walk(root, followlinks=False, onerror=mark_incomplete):
        observed_directory = True
        current_path = Path(current_dir)
        if current_path == root:
            dir_names[:] = [name for name in dir_names if name != RESOURCE_STATS_DIR]
        for name in file_names:
            try:
                entry_stat = (current_path / name).lstat()
            except OSError:
                incomplete = True
                continue
            if stat.S_ISREG(entry_stat.st_mode):
                total += entry_stat.st_size
    if incomplete:
        if not observed_directory:
            return {"status": "unavailable", "issues": ["observation_incomplete"]}
        return {"status": "partial", "issues": ["observation_incomplete"], "bytes": str(total)}
    return {"status": "reported", "bytes": str(total)}


def _unavailable(issue: str) -> dict[str, Any]:
    return {"status": "unavailable", "issues": [issue]}


class JobResourceCollector:
    """Own one job-process accumulator and produce its terminal handoff.

    Runs inside the job process itself (the untrusted self-report producer):
    constructed by worker_process.py/runner_process.py before any job/site
    custom code can execute, per the isolated-bootstrap trust boundary.
    """

    def __init__(
        self,
        run_dir: str | Path,
        *,
        clock_ns: Callable[[], int] = time.monotonic_ns,
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
        self._accumulator = ResourceTimeAccumulator(clock_ns=clock_ns)
        try:
            capacity = capacity_probe()
            if not isinstance(capacity, Mapping):
                raise TypeError("capacity probe must return a mapping")
            self._accumulator.observe(capacity)
            if prior_observation_incomplete:
                self._accumulator.mark_prior_observation_incomplete()
        except Exception:
            self._accumulator.mark_gap()

    def observe_capacity_change(self, capacity: Mapping[str, Any]) -> None:
        """Record a confirmed runtime resource change for future schedulers."""

        self._accumulator.observe(capacity)

    def finish(self, *, child_f3: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        """Build the one private child handoff at process finalization."""

        resource_time = self._accumulator.finish()
        if self._multi_node_incomplete:
            # The current Slurm worker runs the collector on rank zero only.
            # Rank-zero cgroup/CUDA values do not describe the other allocated
            # nodes, so publishing those numbers would understate the site.
            resource_time = _unavailable("unsupported")
        return {
            "internal_version": INTERNAL_HANDOFF_VERSION,
            "kind": INTERNAL_HANDOFF_KIND,
            "resource_time": resource_time,
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
        status = value.get("status")
        if not isinstance(status, str):
            return {"status": "error", "issues": ["malformed_source"]}
        if status in {"reported", "partial"}:
            groups = value.get("sent_to")
            if not isinstance(groups, list) or len(groups) > MAX_F3_SENT_TO_GROUPS:
                return {"status": "error", "issues": ["malformed_source"]}
            expected_keys = {"status", "sent_to"} if status == "reported" else {"status", "sent_to", "issues"}
            if set(value) != expected_keys:
                return {"status": "error", "issues": ["malformed_source"]}
            prior_name = ""
            for group in groups:
                if not isinstance(group, Mapping) or set(group) != {"participant_name", "payload_bytes", "messages"}:
                    return {"status": "error", "issues": ["malformed_source"]}
                name = group["participant_name"]
                payload_text = group["payload_bytes"]
                messages_text = group["messages"]
                if (
                    not isinstance(name, str)
                    or not PARTICIPANT_NAME_PATTERN.fullmatch(name)
                    or name <= prior_name
                    or not isinstance(payload_text, str)
                    or not INTEGER_PATTERN.fullmatch(payload_text)
                    or not isinstance(messages_text, str)
                    or not INTEGER_PATTERN.fullmatch(messages_text)
                ):
                    return {"status": "error", "issues": ["malformed_source"]}
                prior_name = name
                payload_bytes = int(payload_text)
                messages = int(messages_text)
                if payload_bytes > U128_MAX or not 0 < messages <= U128_MAX:
                    return {"status": "error", "issues": ["malformed_source"]}
                if name not in sent_to and len(sent_to) >= MAX_F3_SENT_TO_GROUPS:
                    issues.add("counter_gap")
                    continue
                old_payload, old_messages = sent_to.get(name, (0, 0))
                if old_payload > U128_MAX - payload_bytes or old_messages > U128_MAX - messages:
                    return {"status": "error", "issues": ["malformed_source"]}
                sent_to[name] = (old_payload + payload_bytes, old_messages + messages)
            numeric_count += 1
            if status == "partial":
                value_issues = value.get("issues")
                if (
                    not isinstance(value_issues, list)
                    or not 1 <= len(value_issues) <= MAX_ISSUES
                    or not all(isinstance(issue, str) for issue in value_issues)
                    or value_issues != sorted(set(value_issues))
                    or not set(value_issues).issubset(PARTIAL_ISSUES)
                ):
                    return {"status": "error", "issues": ["malformed_source"]}
                issues.update(value_issues)
        elif status in {"unavailable", "error"}:
            missing_contribution = True
            value_issues = value.get("issues")
            if status == "error" or not isinstance(value_issues, list):
                issues.add("observation_incomplete")
            elif "observation_incomplete" in value_issues:
                issues.add("observation_incomplete")
            else:
                issues.add("attribution_incomplete")
        else:
            return {"status": "error", "issues": ["malformed_source"]}

    if not numeric_count:
        issue = "observation_incomplete" if "observation_incomplete" in issues else "attribution_incomplete"
        return {"status": "unavailable", "issues": [issue]}

    payload_bytes = sum(value[0] for value in sent_to.values())
    messages = sum(value[1] for value in sent_to.values())
    if payload_bytes > U128_MAX or messages > U128_MAX:
        return {"status": "error", "issues": ["malformed_source"]}

    result = {
        "status": "partial" if missing_contribution or issues else "reported",
        "sent_to": [
            {"participant_name": name, "payload_bytes": str(sent_to[name][0]), "messages": str(sent_to[name][1])}
            for name in sorted(sent_to)
        ],
    }
    if result["status"] == "partial":
        if missing_contribution:
            issues.add("attribution_incomplete")
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
        resource_time = _unavailable("observation_incomplete")
        workspace_filesystem = _unavailable("observation_incomplete")
        retained_content = _unavailable("observation_incomplete")
        child_f3 = None
    else:
        try:
            validated = _validate_handoff(child_handoff)
        except InvalidTerminalHandoff:
            validated = None
        if validated is None:
            resource_time = _unavailable("observation_incomplete")
            workspace_filesystem = _unavailable("observation_incomplete")
            retained_content = _unavailable("observation_incomplete")
            child_f3 = None
        else:
            resource_time = validated["resource_time"]
            workspace_filesystem = validated["workspace_filesystem"]
            retained_content = validated["retained_content"]
            child_f3 = validated["child_f3"]

    message_traffic = merge_f3_snapshots(child_f3, parent_f3)
    report = {
        "schema_version": "1.0",
        "kind": "nvflare.resource_stats.participant_summary",
        "job_id": job_id,
        "participant_name": participant_name,
        "reported_at": utc_now(),
        "resource_time": resource_time,
        "workspace_filesystem": workspace_filesystem,
        "retained_content": retained_content,
        "message_traffic": message_traffic,
    }
    validate_record(report)
    return report
