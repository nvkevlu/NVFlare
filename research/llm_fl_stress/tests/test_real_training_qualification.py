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
    assert args.timeout_seconds == 10800


def test_lifecycle_defaults_cover_large_model_startup_and_persistence():
    parser = qualification._define_parser()
    service_startup = next(action for action in parser._actions if action.dest == "service_startup_timeout")

    assert service_startup.default == 300.0
    assert qualification._CLIENT_OPERATION_TIMEOUT_SECONDS == 10800
    assert qualification._PERSISTENCE_TIMEOUT_SECONDS == 7200.0


def test_transport_timeout_environment_requires_exact_operation_envelope(monkeypatch):
    for name, value in qualification._TRANSPORT_TIMEOUT_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)

    assert qualification._require_transport_timeout_environment() == {
        name: 10800 for name in qualification._TRANSPORT_TIMEOUT_ENVIRONMENT
    }


@pytest.mark.parametrize("invalid", [None, "0", "300", "inf", "bad"])
def test_transport_timeout_environment_rejects_missing_or_short_values(monkeypatch, invalid):
    for name, value in qualification._TRANSPORT_TIMEOUT_ENVIRONMENT.items():
        monkeypatch.setenv(name, value)
    target = "NVFLARE_STREAMING_READ_TIMEOUT"
    if invalid is None:
        monkeypatch.delenv(target)
    else:
        monkeypatch.setenv(target, invalid)

    with pytest.raises(RuntimeError, match=target):
        qualification._require_transport_timeout_environment()


def test_scratch_capacity_uses_existing_parent_and_requires_bytes_and_inodes(tmp_path, monkeypatch):
    usage = type("Usage", (), {"free": 60 * qualification._ONE_GIB})()
    filesystem = type("Filesystem", (), {"f_favail": 200_000})()
    monkeypatch.setattr(qualification.shutil, "disk_usage", lambda _path: usage)
    monkeypatch.setattr(qualification.os, "statvfs", lambda _path: filesystem)
    private_root = tmp_path / "job" / "private"

    result = qualification._require_scratch_capacity(private_root)

    assert result["status"] == "PASS"
    assert result["scratch_root"] == str(private_root)
    assert result["probed_path"] == str(tmp_path)
    assert result["required_free_bytes"] == 50 * qualification._ONE_GIB
    assert result["required_free_inodes"] == 100_000


@pytest.mark.parametrize(
    ("free_bytes", "free_inodes", "message"),
    [
        (49 * 1024**3, 200_000, "free bytes"),
        (60 * 1024**3, 99_999, "free inodes"),
    ],
)
def test_scratch_capacity_rejects_insufficient_space(tmp_path, monkeypatch, free_bytes, free_inodes, message):
    usage = type("Usage", (), {"free": free_bytes})()
    filesystem = type("Filesystem", (), {"f_favail": free_inodes})()
    monkeypatch.setattr(qualification.shutil, "disk_usage", lambda _path: usage)
    monkeypatch.setattr(qualification.os, "statvfs", lambda _path: filesystem)

    with pytest.raises(RuntimeError, match=message):
        qualification._require_scratch_capacity(tmp_path / "job" / "private")


def test_full_model_scratch_capacity_uses_profile_specific_threshold(tmp_path, monkeypatch):
    usage = type("Usage", (), {"free": 199 * qualification._ONE_GIB})()
    filesystem = type("Filesystem", (), {"f_favail": 200_000})()
    monkeypatch.setattr(qualification.shutil, "disk_usage", lambda _path: usage)
    monkeypatch.setattr(qualification.os, "statvfs", lambda _path: filesystem)

    with pytest.raises(RuntimeError, match="at least"):
        qualification._require_scratch_capacity(
            tmp_path / "job" / "private",
            required_free_bytes=200 * qualification._ONE_GIB,
        )


def test_32b_profile_is_bounded_real_training_not_full_state():
    settings = qualification._profile_settings("trainable-32b")

    assert settings == {
        "gate_rounds": 2,
        "target_rounds": 1,
        "local_steps": 2,
        "state_scope": "trainable",
        "target_name": "target-32b",
        "max_payload_bytes": 1024 * 1024 * 1024,
    }


def test_72b_profile_is_bounded_last_layer_training_with_two_gib_payload_ceiling():
    settings = qualification._profile_settings("trainable-72b")

    assert settings == {
        "gate_rounds": 2,
        "target_rounds": 1,
        "local_steps": 2,
        "state_scope": "trainable",
        "target_name": "target-72b",
        "max_payload_bytes": 2 * 1024 * 1024 * 1024,
    }


def test_full_model_14b_profile_is_all_parameter_full_state_and_amortizes_transfer():
    settings = qualification._profile_settings("full-model-14b")

    assert settings == {
        "gate_rounds": 1,
        "target_rounds": 1,
        "gate_local_steps": 2,
        "target_local_steps": 8,
        "gate_max_length": 128,
        "target_max_length": 512,
        "gate_trainable_target": "all",
        "target_trainable_target": "all",
        "state_scope": "full",
        "target_name": "target-14b-full-model",
        "max_payload_bytes": 0,
        "minimum_scratch_free_bytes": 200 * qualification._ONE_GIB,
        "required_gpu_reserved_headroom_bytes": 16 * qualification._ONE_GIB,
    }


def test_full_model_14b_multiround_profile_runs_only_five_round_target():
    settings = qualification._profile_settings("full-model-14b-multiround")

    assert settings == {
        "run_gate": False,
        "gate_rounds": 0,
        "target_rounds": 5,
        "target_local_steps": 2,
        "target_max_length": 512,
        "target_trainable_target": "all",
        "state_scope": "full",
        "target_name": "target-14b-full-model-multiround",
        "max_payload_bytes": 0,
        "minimum_scratch_free_bytes": 200 * qualification._ONE_GIB,
        "required_gpu_reserved_headroom_bytes": 16 * qualification._ONE_GIB,
    }


def test_full_model_phase_args_propagate_all_and_sequence_length(tmp_path):
    args = qualification._phase_args(
        tmp_path / "model",
        "revision",
        tmp_path / "phase",
        local_steps=8,
        max_length=512,
        trainable_target="all",
        state_scope="full",
    )

    assert args.local_steps == 8
    assert args.max_length == 512
    assert args.trainable_target == "all"
    assert args.state_scope == "full"


@pytest.mark.parametrize(
    "profile,ready_timeout,stall_timeout",
    [
        ("trainable-32b", 1800.0, 900.0),
        ("trainable-72b", 7200.0, 1800.0),
        ("full-model-14b", 1800.0, 1800.0),
        ("full-model-14b-multiround", 3600.0, 3600.0),
    ],
)
def test_large_model_profiles_reject_short_ready_or_stall_watchdogs(profile, ready_timeout, stall_timeout):
    qualification._validate_profile_timeouts(
        profile,
        target_ready_timeout=ready_timeout,
        target_stall_timeout=stall_timeout,
    )

    with pytest.raises(ValueError, match=f"target_ready_timeout must be at least {ready_timeout}s"):
        qualification._validate_profile_timeouts(
            profile,
            target_ready_timeout=300.0,
            target_stall_timeout=stall_timeout,
        )
    with pytest.raises(ValueError, match=f"target_stall_timeout must be at least {stall_timeout}s"):
        qualification._validate_profile_timeouts(
            profile,
            target_ready_timeout=ready_timeout,
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


def test_target_identity_requires_exact_indexed_tensor_bytes(tmp_path):
    model_path = tmp_path / "Qwen2.5-72B"
    model_path.mkdir()
    (model_path / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["Qwen2ForCausalLM"],
                "hidden_size": 8192,
                "model_type": "qwen2",
                "num_hidden_layers": 80,
                "torch_dtype": "bfloat16",
            }
        )
    )
    (model_path / "model-00001-of-00001.safetensors").write_bytes(b"weights")
    (model_path / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {"total_size": 145_412_407_294}, "weight_map": {}})
    )

    with pytest.raises(RuntimeError, match="logical tensor bytes mismatch"):
        qualification._require_target_identity(
            model_path,
            expected_hidden_size=8192,
            expected_num_hidden_layers=80,
            expected_min_weight_bytes=0,
            expected_safetensor_files=1,
            expected_tensor_bytes=145_412_407_296,
        )


def test_32b_payload_must_match_exact_last_layer_size():
    qualification._require_payload_bytes("target-32b", 975_210_496, 975_210_496)

    with pytest.raises(RuntimeError, match="target-32b exchanged payload mismatch"):
        qualification._require_payload_bytes("target-32b", 975_210_494, 975_210_496)


def test_72b_payload_must_match_exact_last_layer_size():
    qualification._require_payload_bytes("target-72b", 1_755_369_472, 1_755_369_472)

    with pytest.raises(RuntimeError, match="target-72b exchanged payload mismatch"):
        qualification._require_payload_bytes("target-72b", 1_755_369_470, 1_755_369_472)


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


def test_allocation_monitor_fails_closed_on_cgroup_oom_or_limit_event(tmp_path):
    monitor = qualification._AllocationMonitor(tmp_path / "memory.jsonl", tmp_path)
    monitor.initial_events = {"max": 0, "oom": 0, "oom_kill": 0}
    monitor.samples = [
        {
            "cgroup_memory_current_bytes": 100,
            "cgroup_memory_peak_bytes": 100,
            "cgroup_memory_events": {"max": 1, "oom": 1, "oom_kill": 0},
            "process_tree_rss_bytes": 80,
            "process_tree_pss_bytes": 60,
            "system_available_bytes": 1000,
            "scratch_free_bytes": 2000,
        }
    ]

    summary = monitor.close()

    assert summary["status"] == "FAIL"
    assert summary["fatal_cgroup_event_deltas"] == {"max": 1, "oom": 1, "oom_kill": 0}


def test_allocation_monitor_falls_back_when_cgroup_v2_is_unavailable(tmp_path, monkeypatch):
    usage = type("Usage", (), {"free": 300 * qualification._ONE_GIB})()
    monkeypatch.setattr(qualification, "_current_cgroup_v2_path", lambda: None)
    monkeypatch.setattr(qualification._AllocationMonitor, "_process_tree_memory", lambda _self: (100, 80))
    monkeypatch.setattr(qualification._AllocationMonitor, "_system_available_bytes", lambda _self: 1000)
    monkeypatch.setattr(qualification.shutil, "disk_usage", lambda _path: usage)
    monitor = qualification._AllocationMonitor(
        tmp_path / "memory.jsonl",
        tmp_path / "job" / "private",
        interval_seconds=60.0,
    )

    monitor.start()
    summary = monitor.close()

    assert summary["status"] == "PASS"
    assert summary["allocation_wide_cgroup_metrics_available"] is False
    assert summary["telemetry_scope"] == "process-tree-plus-system"
    assert summary["peak_process_tree_rss_bytes"] == 100
    assert summary["minimum_scratch_free_bytes"] == 300 * qualification._ONE_GIB


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

    watcher_args = {}

    class FakeWatcher:
        def __init__(self, _federation, _job_id, _destination, **_kwargs):
            self.closed = False
            watcher_args.update(_kwargs)

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
    prod_env_args = {}

    def fake_prod_env(**kwargs):
        prod_env_args.update(kwargs)
        return object()

    monkeypatch.setattr(prod_env, "ProdEnv", fake_prod_env)
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
    assert prod_env_args["login_timeout"] == 60.0
    assert watcher_args["model_file_timeout"] == 7200.0


def test_control_plane_job_uses_bounded_but_nonfragile_lifecycle_timeouts(tmp_path, monkeypatch):
    from nvflare.recipe import prod_env

    class FakeRun:
        @staticmethod
        def get_job_id():
            return "control-job"

    class FakeRecipe:
        @staticmethod
        def run(_environment):
            return FakeRun()

    class FakeFederation:
        admin_kit = tmp_path / "admin"

        @staticmethod
        def wait_for_terminal(run, *, total_timeout):
            assert run.get_job_id() == "control-job"
            assert total_timeout == 180.0
            return "FINISHED:COMPLETED"

        @staticmethod
        def job_events(site_name, job_id, event):
            assert job_id == "control-job"
            assert event == "real_training_control_plane_round"
            return [{"event": event, "site_name": site_name, "status": "PASS"}]

        @staticmethod
        def service_job_text(participant, job_id):
            assert participant == qualification.SERVER_NAME
            assert job_id == "control-job"
            return "Aggregated 2/2 results"

        @staticmethod
        def collect_job_logs(job_id, destination):
            assert job_id == "control-job"
            destination.mkdir(parents=True, exist_ok=True)
            return {}

    prod_env_args = {}

    def fake_prod_env(**kwargs):
        prod_env_args.update(kwargs)
        return object()

    monkeypatch.setattr(qualification, "_build_control_plane_recipe", lambda _sequence: FakeRecipe())
    monkeypatch.setattr(prod_env, "ProdEnv", fake_prod_env)

    summary = qualification._run_control_plane_job(FakeFederation(), tmp_path / "evidence", sequence=1)

    assert summary["status"] == "PASS"
    assert prod_env_args["login_timeout"] == 60.0
