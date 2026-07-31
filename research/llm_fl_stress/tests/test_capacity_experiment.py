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

from research.llm_fl_stress.real_training import capacity_experiment


class _Process:
    def __init__(self, command, return_code=0):
        self.command = command
        self.return_code = return_code

    def wait(self, timeout=None):
        return self.return_code

    def poll(self):
        return self.return_code


class _GpuMonitor:
    def __init__(self, path, status="PASS"):
        self.path = path
        self.status = status

    def start(self):
        self.path.write_text("gpu samples\n", encoding="utf-8")

    def close(self):
        return {"event": "real_training_gpu_monitor", "status": self.status}


class _AllocationMonitor:
    def __init__(self, path, _scratch, status="PASS"):
        self.path = path
        self.status = status

    def start(self):
        self.path.write_text("{}\n", encoding="utf-8")

    def close(self):
        return {"event": "real_training_allocation_monitor", "status": self.status}


def test_capacity_experiment_records_passing_child_and_monitors(tmp_path, monkeypatch):
    artifact = tmp_path / "artifact"
    scratch = tmp_path / "scratch"
    commands = []
    monkeypatch.setattr(capacity_experiment, "_GpuMonitor", _GpuMonitor)
    monkeypatch.setattr(capacity_experiment, "_AllocationMonitor", _AllocationMonitor)
    monkeypatch.setattr(
        capacity_experiment.subprocess,
        "Popen",
        lambda command: commands.append(command) or _Process(command),
    )

    status = capacity_experiment.main(
        [
            "--artifact-root",
            str(artifact.resolve()),
            "--scratch-root",
            str(scratch.resolve()),
            "--gpu-count",
            "8",
            "--",
            "python",
            "experiment.py",
        ]
    )

    assert status == 0
    assert commands == [["python", "experiment.py"]]
    assert json.loads((artifact / "qualification.json").read_text())["status"] == "PASS"
    assert json.loads((artifact / "configuration.json").read_text())["gpu_mapping"] == {"site-1": list(range(8))}


def test_capacity_experiment_fails_closed_on_monitor_failure(tmp_path, monkeypatch):
    artifact = tmp_path / "artifact"
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(capacity_experiment, "_GpuMonitor", lambda path: _GpuMonitor(path, status="FAIL"))
    monkeypatch.setattr(capacity_experiment, "_AllocationMonitor", _AllocationMonitor)
    monkeypatch.setattr(capacity_experiment.subprocess, "Popen", lambda command: _Process(command))

    status = capacity_experiment.main(
        [
            "--artifact-root",
            str(artifact.resolve()),
            "--scratch-root",
            str(scratch.resolve()),
            "--gpu-count",
            "8",
            "--",
            "python",
            "experiment.py",
        ]
    )

    assert status == 1
    summary = json.loads((artifact / "qualification.json").read_text())
    assert summary["status"] == "FAIL"
    assert "GPU monitor did not prove activity" in summary["failures"][0]
