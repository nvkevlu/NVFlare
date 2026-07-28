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
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.llm_fl_stress.real_training import provisioned
from research.llm_fl_stress.real_training.provisioned import (
    ADMIN_NAME,
    CLIENT_NAMES,
    SERVER_NAME,
    LocalProductionFederation,
    PersistedModelWatcher,
    _redact_log_text,
)


def _federation(tmp_path: Path) -> LocalProductionFederation:
    return LocalProductionFederation(tmp_path / "private", tmp_path / "evidence")


def test_project_is_real_tls_server_and_two_client_topology(tmp_path):
    project = _federation(tmp_path)._project(17002, 17003)

    participants = {participant["name"]: participant for participant in project["participants"]}
    assert project["connection_security"] == "tls"
    assert participants[SERVER_NAME]["fed_learn_port"] == 17002
    assert participants[SERVER_NAME]["admin_port"] == 17003
    assert set(CLIENT_NAMES).issubset(participants)
    assert participants[ADMIN_NAME]["type"] == "admin"
    assert all("poc" not in builder["path"].lower() for builder in project["builders"])
    assert all("sim" not in builder["path"].lower() for builder in project["builders"])


def test_job_root_resolves_exact_participant_workspace(tmp_path):
    federation = _federation(tmp_path)
    kit = tmp_path / "site-1"
    expected = kit / "workspace" / "job-123"
    expected.mkdir(parents=True)
    federation.kits = {"site-1": kit}

    assert federation.job_root("site-1", "job-123") == expected


def test_context_entry_closes_partial_services_when_start_fails(tmp_path, monkeypatch):
    federation = _federation(tmp_path)
    closed = False

    monkeypatch.setattr(federation, "provision", lambda: {})

    def fail_start():
        raise RuntimeError("start failed")

    def close():
        nonlocal closed
        closed = True

    monkeypatch.setattr(federation, "start", fail_start)
    monkeypatch.setattr(federation, "close", close)

    with pytest.raises(RuntimeError, match="start failed"):
        federation.__enter__()
    assert closed is True


def test_wait_for_run_aborts_immediately_on_runner_sync_failure(tmp_path):
    federation = _federation(tmp_path)
    job_id = "job-123"
    federation.kits = {}
    for participant in (SERVER_NAME, *CLIENT_NAMES):
        kit = tmp_path / participant
        (kit / job_id).mkdir(parents=True)
        federation.kits[participant] = kit
    (federation.kits["site-2"] / job_id / "log.txt").write_text(
        "RuntimeError: cannot sync with server Runner after 60.0 seconds\n"
    )

    class FakeRun:
        aborted = False

        @staticmethod
        def get_job_id():
            return job_id

        @staticmethod
        def get_status():
            return "RUNNING"

        def abort(self):
            self.aborted = True

    run = FakeRun()
    with pytest.raises(RuntimeError, match="cannot sync with server Runner"):
        federation.wait_for_run(
            run,
            model_path=Path("/models/qwen"),
            ready_timeout=120.0,
            total_timeout=300.0,
            poll_interval=0.01,
        )
    assert run.aborted is True


def test_abort_reports_the_abort_api_error_instead_of_hiding_it(tmp_path, capsys):
    federation = _federation(tmp_path)

    class FakeRun:
        @staticmethod
        def get_job_id():
            return "job-123"

        @staticmethod
        def abort():
            raise RuntimeError("admin connection lost")

    result = federation._abort(FakeRun(), "phase deadline")

    assert result["status"] == "ERROR"
    assert result["error"] == "RuntimeError: admin connection lost"
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["event"] == "real_training_production_abort"
    assert emitted["reason"] == "phase deadline"


def test_service_job_text_scans_complete_log_not_only_tail(tmp_path):
    federation = _federation(tmp_path)
    service_log = tmp_path / "service-server.log"
    service_log.write_text(
        "job-123 Aggregated 2/2 results\n" + ("unrelated transport metric\n" * 30_000) + "job-456 unrelated run\n"
    )
    federation.services[SERVER_NAME] = SimpleNamespace(log_path=service_log)

    result = federation.service_job_text(SERVER_NAME, "job-123")

    assert result == "job-123 Aggregated 2/2 results"


def test_wait_for_run_grants_bounded_grace_after_two_of_two_aggregation(tmp_path, monkeypatch, capsys):
    federation = _federation(tmp_path)
    clock = {"seconds": 0.0}

    monkeypatch.setattr(provisioned.time, "monotonic", lambda: clock["seconds"])
    monkeypatch.setattr(
        provisioned.time,
        "sleep",
        lambda seconds: clock.__setitem__("seconds", clock["seconds"] + seconds),
    )
    monkeypatch.setattr(federation, "_require_services_alive", lambda: None)
    monkeypatch.setattr(federation, "_fatal_job_error", lambda _job_id: None)
    monkeypatch.setattr(
        federation,
        "_ready_sites",
        lambda _job_id, _model_path: set(CLIENT_NAMES),
    )
    monkeypatch.setattr(
        federation,
        "completion_progress",
        lambda _job_id: {
            "aggregated_2_of_2": clock["seconds"] >= 9.0,
            "persistence_started": clock["seconds"] >= 10.0,
            "persistence_finished": False,
        },
    )

    class FakeRun:
        aborted = False

        @staticmethod
        def get_job_id():
            return "job-123"

        @staticmethod
        def get_status():
            return "FINISHED:COMPLETED" if clock["seconds"] >= 12.0 else "RUNNING"

        def abort(self):
            self.aborted = True

    run = FakeRun()
    status = federation.wait_for_run(
        run,
        model_path=Path("/models/qwen"),
        ready_timeout=5.0,
        total_timeout=10.0,
        completion_grace_timeout=5.0,
        poll_interval=1.0,
    )

    assert status == "FINISHED:COMPLETED"
    assert run.aborted is False
    assert '"event": "real_training_production_completion_grace"' in capsys.readouterr().out


def test_wait_for_run_does_not_grant_grace_without_completion_progress(tmp_path, monkeypatch):
    federation = _federation(tmp_path)
    clock = {"seconds": 0.0}

    monkeypatch.setattr(provisioned.time, "monotonic", lambda: clock["seconds"])
    monkeypatch.setattr(
        provisioned.time,
        "sleep",
        lambda seconds: clock.__setitem__("seconds", clock["seconds"] + seconds),
    )
    monkeypatch.setattr(federation, "_require_services_alive", lambda: None)
    monkeypatch.setattr(federation, "_fatal_job_error", lambda _job_id: None)
    monkeypatch.setattr(
        federation,
        "_ready_sites",
        lambda _job_id, _model_path: set(CLIENT_NAMES),
    )
    monkeypatch.setattr(
        federation,
        "completion_progress",
        lambda _job_id: {
            "aggregated_2_of_2": False,
            "persistence_started": False,
            "persistence_finished": False,
        },
    )

    class FakeRun:
        aborted = False

        @staticmethod
        def get_job_id():
            return "job-123"

        @staticmethod
        def get_status():
            return "RUNNING"

        def abort(self):
            self.aborted = True

    run = FakeRun()
    with pytest.raises(TimeoutError, match="completion_progress"):
        federation.wait_for_run(
            run,
            model_path=Path("/models/qwen"),
            ready_timeout=5.0,
            total_timeout=10.0,
            completion_grace_timeout=5.0,
            poll_interval=1.0,
        )

    assert run.aborted is True


def test_wait_for_run_aborts_when_bounded_completion_grace_expires(tmp_path, monkeypatch):
    federation = _federation(tmp_path)
    clock = {"seconds": 0.0}

    monkeypatch.setattr(provisioned.time, "monotonic", lambda: clock["seconds"])
    monkeypatch.setattr(
        provisioned.time,
        "sleep",
        lambda seconds: clock.__setitem__("seconds", clock["seconds"] + seconds),
    )
    monkeypatch.setattr(federation, "_require_services_alive", lambda: None)
    monkeypatch.setattr(federation, "_fatal_job_error", lambda _job_id: None)
    monkeypatch.setattr(
        federation,
        "_ready_sites",
        lambda _job_id, _model_path: set(CLIENT_NAMES),
    )
    monkeypatch.setattr(
        federation,
        "completion_progress",
        lambda _job_id: {
            "aggregated_2_of_2": True,
            "persistence_started": True,
            "persistence_finished": False,
        },
    )

    class FakeRun:
        aborted = False

        @staticmethod
        def get_job_id():
            return "job-123"

        @staticmethod
        def get_status():
            return "RUNNING"

        def abort(self):
            self.aborted = True

    run = FakeRun()
    with pytest.raises(TimeoutError, match=r"plus 5\.0s completion grace"):
        federation.wait_for_run(
            run,
            model_path=Path("/models/qwen"),
            ready_timeout=5.0,
            total_timeout=10.0,
            completion_grace_timeout=5.0,
            poll_interval=1.0,
        )

    assert run.aborted is True
    assert clock["seconds"] == 15.0


def test_collect_job_logs_keeps_redacted_logs_but_not_full_model(tmp_path):
    federation = _federation(tmp_path)
    job_id = "job-123"
    for participant in (SERVER_NAME, *CLIENT_NAMES):
        kit = tmp_path / participant
        root = kit / job_id
        root.mkdir(parents=True)
        (root / "log.txt").write_text(f"{participant} Sent token: private-value\n")
        federation.kits[participant] = kit
    model = federation.kits[SERVER_NAME] / job_id / "app_server" / "FL_global_model.pt"
    model.parent.mkdir()
    model.write_bytes(b"model-state")
    destination = tmp_path / "collected"

    result = federation.collect_job_logs(job_id, destination)

    assert set(result) == {SERVER_NAME, *CLIENT_NAMES}
    assert (destination / SERVER_NAME / "log.txt").is_file()
    assert "private-value" not in (destination / SERVER_NAME / "log.txt").read_text()
    assert not (destination / "FL_global_model.pt").exists()


def test_persisted_model_watcher_captures_stat_and_small_metadata(tmp_path):
    server_root = tmp_path / "server" / "job-123"
    model = server_root / "app_server" / "FL_global_model.pt"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model-state")
    Path(f"{model}.metadata").write_text(json.dumps({"tensor_count": 1}))
    service_log = tmp_path / "server-service.log"
    service_log.write_text("run=job-123 End persist model on server.\n")

    class FakeFederation:
        services = {SERVER_NAME: SimpleNamespace(log_path=service_log)}

        @staticmethod
        def job_root(_participant, _job_id):
            return server_root

    destination = tmp_path / "persistence"
    watcher = PersistedModelWatcher(FakeFederation(), "job-123", destination)
    watcher.start()
    try:
        result = watcher.wait()
    finally:
        watcher.close()

    assert result["size_bytes"] == len(b"model-state")
    assert (destination / "FL_global_model.pt.metadata").is_file()
    assert not (destination / "FL_global_model.pt").exists()


def test_service_log_redaction_removes_transient_auth_values():
    redacted = _redact_log_text("Sent token: abc-123. Token: def-456 SSID:ghi-789\n")

    assert "abc-123" not in redacted
    assert "def-456" not in redacted
    assert "ghi-789" not in redacted
    assert redacted.count("<redacted>") == 3
