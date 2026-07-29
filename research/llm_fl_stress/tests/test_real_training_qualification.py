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

import pytest

from research.llm_fl_stress.real_training import qualification


def test_trainable_phase_args_pin_rounds_steps_and_state_scope(tmp_path):
    args = qualification._phase_args(
        tmp_path / "model",
        "revision",
        tmp_path / "phase",
        num_rounds=3,
        local_steps=4,
        state_scope="trainable",
    )

    assert args.num_clients == 2
    assert args.nproc_per_node == 4
    assert args.num_rounds == 3
    assert args.local_steps == 4
    assert args.state_scope == "trainable"
    assert args.trainable_target == "last-layer"


def test_32b_profile_is_bounded_real_training_not_full_state():
    settings = qualification._profile_settings("trainable-32b")

    assert settings == {
        "gate_rounds": 2,
        "target_rounds": 1,
        "local_steps": 2,
        "state_scope": "trainable",
        "target_name": "target-32b",
    }


def test_32b_profile_rejects_short_ready_or_stall_watchdogs():
    qualification._validate_profile_timeouts(
        "trainable-32b",
        target_ready_timeout=1800.0,
        target_stall_timeout=900.0,
    )

    with pytest.raises(ValueError, match="target_ready_timeout must be at least 1800.0s"):
        qualification._validate_profile_timeouts(
            "trainable-32b",
            target_ready_timeout=300.0,
            target_stall_timeout=900.0,
        )
    with pytest.raises(ValueError, match="target_stall_timeout must be at least 900.0s"):
        qualification._validate_profile_timeouts(
            "trainable-32b",
            target_ready_timeout=1800.0,
            target_stall_timeout=300.0,
        )


def test_target_identity_requires_pinned_architecture_and_weight_size(tmp_path):
    model_path = tmp_path / "Qwen2.5-32B"
    model_path.mkdir()
    (model_path / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["Qwen2ForCausalLM"],
                "hidden_size": 5120,
                "model_type": "qwen2",
                "num_hidden_layers": 64,
                "torch_dtype": "bfloat16",
            }
        )
    )
    (model_path / "model-00001-of-00002.safetensors").write_bytes(b"1234")
    (model_path / "model-00002-of-00002.safetensors").write_bytes(b"5678")

    identity = qualification._require_target_identity(
        model_path,
        expected_hidden_size=5120,
        expected_num_hidden_layers=64,
        expected_min_weight_bytes=8,
        expected_safetensor_files=2,
    )

    assert identity["hidden_size"] == 5120
    assert identity["num_hidden_layers"] == 64
    assert identity["safetensor_file_count"] == 2
    assert identity["safetensor_bytes"] == 8


def test_target_identity_rejects_wrong_model_before_gpu_work(tmp_path):
    model_path = tmp_path / "wrong-model"
    model_path.mkdir()
    (model_path / "config.json").write_text(
        json.dumps(
            {
                "hidden_size": 5120,
                "model_type": "qwen2",
                "num_hidden_layers": 48,
                "torch_dtype": "bfloat16",
            }
        )
    )

    with pytest.raises(RuntimeError, match="num_hidden_layers mismatch"):
        qualification._require_target_identity(
            model_path,
            expected_hidden_size=5120,
            expected_num_hidden_layers=64,
            expected_min_weight_bytes=0,
            expected_safetensor_files=0,
        )


def test_target_identity_rejects_incomplete_weight_shards(tmp_path):
    model_path = tmp_path / "incomplete-model"
    model_path.mkdir()
    (model_path / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["Qwen2ForCausalLM"],
                "hidden_size": 5120,
                "model_type": "qwen2",
                "num_hidden_layers": 64,
                "torch_dtype": "bfloat16",
            }
        )
    )
    (model_path / "model-00001-of-00017.safetensors").write_bytes(b"weights")

    with pytest.raises(RuntimeError, match="safetensor file-count mismatch"):
        qualification._require_target_identity(
            model_path,
            expected_hidden_size=5120,
            expected_num_hidden_layers=64,
            expected_min_weight_bytes=0,
            expected_safetensor_files=17,
        )


def test_32b_payload_must_match_exact_last_layer_size():
    qualification._require_payload_bytes("target-32b", 975_210_496, 975_210_496)

    with pytest.raises(RuntimeError, match="target-32b trainable payload mismatch"):
        qualification._require_payload_bytes("target-32b", 975_210_494, 975_210_496)


class _RunningMonitorProcess:
    def __init__(self, output):
        self.output = output
        self.terminated = False
        self.output.write("timestamp, index, uuid, name, memory.used [MiB], utilization.gpu [%]\n")
        for index in range(8):
            self.output.write(f"2026/07/27 12:00:00, {index}, GPU-{index}, " "NVIDIA A100-SXM4-80GB, 1024 MiB, 95 %\n")
        self.output.flush()

    def poll(self):
        return -15 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True

    def wait(self, timeout):
        return -15


def test_gpu_monitor_requires_and_records_a_real_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(qualification.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        qualification.subprocess,
        "Popen",
        lambda *args, **kwargs: _RunningMonitorProcess(kwargs["stdout"]),
    )
    monitor = qualification._GpuMonitor(tmp_path / "gpu-samples.csv")

    monitor.start()
    summary = monitor.close()

    assert summary["status"] == "PASS"
    assert summary["sample_lines"] == 8
    assert summary["observed_gpu_indices"] == list(range(8))
    assert summary["active_gpu_indices"] == list(range(8))
    assert summary["samples_per_gpu"] == {str(index): 1 for index in range(8)}
    assert summary["peak_utilization_percent"] == {str(index): 95 for index in range(8)}
    assert summary["peak_memory_mib"] == {str(index): 1024 for index in range(8)}
    assert summary["return_code_before_shutdown"] is None


def test_gpu_monitor_fails_fast_when_nvidia_smi_exits(tmp_path, monkeypatch):
    class ExitedMonitorProcess(_RunningMonitorProcess):
        def poll(self):
            return 7

    monkeypatch.setattr(qualification.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        qualification.subprocess,
        "Popen",
        lambda *args, **kwargs: ExitedMonitorProcess(kwargs["stdout"]),
    )
    monitor = qualification._GpuMonitor(tmp_path / "gpu-samples.csv")

    with pytest.raises(RuntimeError, match="exited with 7"):
        monitor.start()

    summary = monitor.close()
    assert summary["status"] == "FAIL"
    assert summary["return_code_before_shutdown"] == 7


def test_gpu_monitor_fails_when_any_allocated_gpu_is_missing(tmp_path, monkeypatch):
    class SevenGpuMonitorProcess(_RunningMonitorProcess):
        def __init__(self, output):
            self.output = output
            self.terminated = False
            self.output.write("timestamp, index, uuid, name, memory.used [MiB], utilization.gpu [%]\n")
            for index in range(7):
                self.output.write(
                    f"2026/07/27 12:00:00, {index}, GPU-{index}, " "NVIDIA A100-SXM4-80GB, 1024 MiB, 95 %\n"
                )
            self.output.flush()

    monkeypatch.setattr(qualification.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        qualification.subprocess,
        "Popen",
        lambda *args, **kwargs: SevenGpuMonitorProcess(kwargs["stdout"]),
    )
    monitor = qualification._GpuMonitor(tmp_path / "gpu-samples.csv")

    monitor.start()
    summary = monitor.close()

    assert summary["status"] == "FAIL"
    assert summary["observed_gpu_indices"] == list(range(7))


def test_gpu_monitor_fails_when_one_allocated_gpu_never_becomes_active(tmp_path, monkeypatch):
    class IdleGpuMonitorProcess(_RunningMonitorProcess):
        def __init__(self, output):
            self.output = output
            self.terminated = False
            self.output.write("timestamp, index, uuid, name, memory.used [MiB], utilization.gpu [%]\n")
            for index in range(8):
                utilization = 0 if index == 0 else 95
                self.output.write(
                    f"2026/07/27 12:00:00, {index}, GPU-{index}, " f"NVIDIA A100-SXM4-80GB, 1024 MiB, {utilization} %\n"
                )
            self.output.flush()

    monkeypatch.setattr(qualification.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        qualification.subprocess,
        "Popen",
        lambda *args, **kwargs: IdleGpuMonitorProcess(kwargs["stdout"]),
    )
    monitor = qualification._GpuMonitor(tmp_path / "gpu-samples.csv")

    monitor.start()
    summary = monitor.close()

    assert summary["status"] == "FAIL"
    assert summary["active_gpu_indices"] == list(range(1, 8))


def test_phase_failure_retains_job_id_and_best_effort_logs(tmp_path, monkeypatch):
    from nvflare.recipe import prod_env

    class FakeRun:
        @staticmethod
        def get_job_id():
            return "job-123"

    class FakeRecipe:
        @staticmethod
        def run(_environment):
            return FakeRun()

    class FakeWatcher:
        def __init__(self, _federation, _job_id, _destination, **_kwargs):
            self.closed = False

        @staticmethod
        def start():
            return None

        def close(self):
            self.closed = True

    class FakeFederation:
        admin_kit = tmp_path / "admin"

        @staticmethod
        def wait_for_run(*_args, **_kwargs):
            raise TimeoutError("site-2 never became ready")

        @staticmethod
        def collect_job_logs(job_id, destination):
            assert job_id == "job-123"
            destination.mkdir(parents=True)
            return {}

    monkeypatch.setattr(qualification, "_build_recipe", lambda _args: FakeRecipe())
    monkeypatch.setattr(qualification, "PersistedModelWatcher", FakeWatcher)
    monkeypatch.setattr(prod_env, "ProdEnv", lambda **_kwargs: object())
    evidence_root = tmp_path / "evidence"

    with pytest.raises(TimeoutError, match="site-2 never became ready"):
        qualification._run_phase(
            FakeFederation(),
            name="gate-1.5b",
            model_path=tmp_path / "model",
            model_revision="revision",
            evidence_root=evidence_root,
            expected_gpu_name_substring="A100-SXM4-80GB",
            ready_timeout=120.0,
            stall_timeout=300.0,
        )

    failure = json.loads((evidence_root / "gate-1.5b" / "failure.json").read_text())
    assert failure["status"] == "FAIL"
    assert failure["job_id"] == "job-123"
    assert failure["failure_logs_collected"] is True
    assert failure["error"] == {
        "type": "TimeoutError",
        "message": "site-2 never became ready",
    }
