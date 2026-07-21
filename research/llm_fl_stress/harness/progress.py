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

"""Local heartbeat and completion markers for long-running stress tests."""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .artifacts import RunArtifacts, utc_now, write_json


def _print_flushed(message: str) -> None:
    print(message, flush=True)


def _format_elapsed(seconds: float) -> str:
    rounded = max(0, int(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:d}h{minutes:02d}m{seconds:02d}s"
    return f"{minutes:d}m{seconds:02d}s"


@dataclass
class RunProgressReporter:
    artifacts: RunArtifacts
    report_interval_seconds: float = 60.0
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    emit: Callable[[str], None] = field(default=_print_flushed, repr=False)
    _started_at: float = field(init=False, repr=False)
    _last_report_at: Optional[float] = field(default=None, init=False, repr=False)
    _last_signature: Optional[tuple] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.report_interval_seconds <= 0:
            raise ValueError("report_interval_seconds must be positive")
        self._started_at = self.clock()

    @property
    def status_path(self) -> Path:
        return self.artifacts.root / "live_status.json"

    def update(
        self,
        phase: str,
        flare_status: str,
        job_id: Optional[str] = None,
        force: bool = False,
        **details,
    ) -> bool:
        now = self.clock()
        signature = (phase, flare_status, job_id)
        should_report = (
            force
            or signature != self._last_signature
            or self._last_report_at is None
            or now - self._last_report_at >= self.report_interval_seconds
        )
        if not should_report:
            return False

        elapsed_seconds = now - self._started_at
        record = {
            "schema_version": 1,
            "run_id": self.artifacts.root.name,
            "state": "RUNNING",
            "phase": phase,
            "flare_status": flare_status,
            "job_id": job_id,
            "updated_at": utc_now(),
            "elapsed_seconds": round(elapsed_seconds, 3),
            "artifacts": str(self.artifacts.root),
            **details,
        }
        write_json(self.status_path, record)
        self.artifacts.append_event(
            "run_heartbeat",
            "harness",
            phase=phase,
            status=flare_status,
            job_id=job_id,
            elapsed_seconds=round(elapsed_seconds, 3),
            **details,
        )
        self.emit(
            f"[{record['updated_at']}][RUN] id={record['run_id']} phase={phase} "
            f"status={flare_status} elapsed={_format_elapsed(elapsed_seconds)} job={job_id or '-'}"
        )
        self._last_report_at = now
        self._last_signature = signature
        return True

    def finish(
        self,
        outcome: str,
        flare_status: str,
        job_id: Optional[str] = None,
        error: Optional[dict] = None,
        elapsed_seconds: Optional[float] = None,
    ) -> dict:
        if elapsed_seconds is None:
            elapsed_seconds = self.clock() - self._started_at
        passed = outcome in {"PASS", "EXPECTED_FAILURE"}
        record = {
            "schema_version": 1,
            "run_id": self.artifacts.root.name,
            "state": "COMPLETED" if passed else "FAILED",
            "phase": "COMPLETE",
            "outcome": outcome,
            "flare_status": flare_status,
            "job_id": job_id,
            "updated_at": utc_now(),
            "elapsed_seconds": round(elapsed_seconds, 3),
            "artifacts": str(self.artifacts.root),
            "error": error,
        }
        write_json(self.status_path, record)
        marker_path = self.artifacts.root / ("RUN_COMPLETE" if passed else "RUN_FAILED")
        marker_path.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
        self.artifacts.append_event(
            "run_completed",
            "harness",
            outcome=outcome,
            status=flare_status,
            job_id=job_id,
            elapsed_seconds=round(elapsed_seconds, 3),
        )
        label = "RUN COMPLETE" if passed else "RUN FAILED"
        self.emit(
            f"[{record['updated_at']}][{label}] id={record['run_id']} outcome={outcome} "
            f"status={flare_status} elapsed={_format_elapsed(elapsed_seconds)} artifacts={self.artifacts.root}"
        )
        return record
