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
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Optional

from .accumulator import ClockOrderError, CollectorClosedError, ResourceTimeAccumulator
from .contract import validate_record
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
    "JobResourceCollector",
    "assemble_participant_summary",
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

    def finish(self) -> dict[str, Any]:
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
            "retained_content": _unavailable("not_bound"),
            "child_f3": _unavailable("not_bound"),
        }


def assemble_participant_summary(
    *,
    job_id: str,
    participant_name: str,
    child_handoff: Optional[Mapping[str, Any]],
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
    else:
        try:
            validated = _validate_handoff(child_handoff)
        except InvalidTerminalHandoff:
            validated = None
        if validated is None:
            resource_time = _unavailable("observation_incomplete")
            workspace_filesystem = _unavailable("observation_incomplete")
            retained_content = _unavailable("observation_incomplete")
        else:
            resource_time = validated["resource_time"]
            workspace_filesystem = validated["workspace_filesystem"]
            retained_content = validated["retained_content"]

    # Job-scoped F3 accounting is deliberately unavailable until the sender
    # hook has authoritative job attribution and summary-message exclusion.
    f3 = _unavailable("not_bound")
    report = {
        "schema_version": "1.0",
        "kind": "nvflare.resource_stats.participant_summary",
        "job_id": job_id,
        "participant_name": participant_name,
        "reported_at": utc_now(),
        "resource_time": resource_time,
        "workspace_filesystem": workspace_filesystem,
        "retained_content": retained_content,
        "f3": f3,
    }
    validate_record(report)
    return report
