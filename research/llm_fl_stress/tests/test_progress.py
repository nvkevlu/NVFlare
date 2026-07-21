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

import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from research.llm_fl_stress.harness.artifacts import RunArtifacts, write_json
from research.llm_fl_stress.harness.progress import RunProgressReporter
from research.llm_fl_stress.ops.watch_run import watch_run


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value

    def advance(self, seconds: float):
        self.value += seconds


class ProgressTest(unittest.TestCase):
    def _artifacts(self, root: Path) -> RunArtifacts:
        artifacts = RunArtifacts(
            root=root,
            manifest_path=root / "manifest.json",
            scenario_path=root / "scenario.json",
            events_path=root / "events.jsonl",
            result_path=root / "result.json",
            job_config_dir=root / "job_config",
            workspace_dir=root / "flare_workspace",
            logs_dir=root / "logs",
            metrics_dir=root / "metrics",
            report_dir=root / "report",
            _event_lock=threading.Lock(),
        )
        root.mkdir(parents=True)
        artifacts.events_path.touch()
        return artifacts

    def test_heartbeat_is_immediate_on_change_and_rate_limited_when_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts = self._artifacts(Path(temp_dir) / "run-1")
            clock = FakeClock()
            messages = []
            reporter = RunProgressReporter(artifacts, report_interval_seconds=60, clock=clock, emit=messages.append)

            self.assertTrue(reporter.update("FEDERATED_RUN", "RUNNING", job_id="job-1"))
            clock.advance(30)
            self.assertFalse(reporter.update("FEDERATED_RUN", "RUNNING", job_id="job-1"))
            clock.advance(31)
            self.assertTrue(reporter.update("FEDERATED_RUN", "RUNNING", job_id="job-1"))
            self.assertTrue(reporter.update("COLLECTING_ARTIFACTS", "FINISHED:COMPLETED", job_id="job-1"))

            status = json.loads(reporter.status_path.read_text(encoding="utf-8"))
            self.assertEqual("RUNNING", status["state"])
            self.assertEqual("COLLECTING_ARTIFACTS", status["phase"])
            self.assertEqual(3, len(messages))
            self.assertEqual(3, len(artifacts.events_path.read_text(encoding="utf-8").splitlines()))

    def test_finish_writes_terminal_status_and_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts = self._artifacts(Path(temp_dir) / "run-2")
            clock = FakeClock()
            messages = []
            reporter = RunProgressReporter(artifacts, clock=clock, emit=messages.append)
            reporter.update("FEDERATED_RUN", "RUNNING", job_id="job-2")
            clock.advance(125)

            terminal = reporter.finish("PASS", "FINISHED:COMPLETED", job_id="job-2")

            self.assertEqual("COMPLETED", terminal["state"])
            self.assertTrue((artifacts.root / "RUN_COMPLETE").is_file())
            self.assertFalse((artifacts.root / "RUN_FAILED").exists())
            self.assertIn("RUN COMPLETE", messages[-1])
            self.assertEqual(0, watch_run(artifacts.root, 0.01, 180, once=True))

    def test_watcher_reports_stale_running_heartbeat(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run-3"
            run_dir.mkdir()
            status_path = run_dir / "live_status.json"
            write_json(
                status_path,
                {
                    "state": "RUNNING",
                    "phase": "FEDERATED_RUN",
                    "flare_status": "RUNNING",
                    "updated_at": "2026-07-17T00:00:00+00:00",
                    "elapsed_seconds": 60,
                },
            )
            stale_time = time.time() - 300
            os.utime(status_path, (stale_time, stale_time))

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = watch_run(run_dir, 0.01, 180, once=True)

            self.assertEqual(2, result)


if __name__ == "__main__":
    unittest.main()
