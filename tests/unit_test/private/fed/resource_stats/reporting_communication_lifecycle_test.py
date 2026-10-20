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

"""Reporting integration owns communication activation, cutoff and publication."""

import os
import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nvflare.apis.job_def import RunStatus
from nvflare.private.fed.app import job_process_cleanup
from nvflare.private.fed.app.client import worker_process
from nvflare.private.fed.app.server import runner_process
from nvflare.private.fed.resource_stats.f3_counter import F3_DRAIN_TIMEOUT_SECONDS, F3Counter, F3TrafficClass
from nvflare.private.fed.server import job_runner


class _StartupObserved(Exception):
    pass


@pytest.mark.parametrize("module", [worker_process, runner_process])
@pytest.mark.parametrize("counter_fails", [False, True])
def test_counter_start_keeps_existing_workspace_and_import_order(module, counter_fails, tmp_path, monkeypatch):
    events = []
    args = SimpleNamespace(set=[], workspace=str(tmp_path), client_name="site-1", job_id="job-1")
    monkeypatch.setenv("PYTHONPATH", "existing-custom-import-path")
    original_path = sys.path[:]
    monkeypatch.setattr(module, "parse_vars", lambda _: {})
    monkeypatch.setattr(module, "Workspace", MagicMock())
    monkeypatch.setattr(module, "JobResourceCollector", lambda *_, **__: None)
    monkeypatch.setattr(module, "download_workspace", lambda *_: events.append("download"))
    monkeypatch.setattr(module, "refresh_custom_dir_import_path", lambda *_: events.append("refresh"))

    def start_counter():
        events.append("counter")
        if counter_fails:
            raise RuntimeError("optional accounting unavailable")
        return F3Counter()

    def normal_configuration(*_):
        events.append("configuration")
        raise _StartupObserved()

    monkeypatch.setattr(module, "start_job_f3_counter", start_counter)
    monkeypatch.setattr(module, "set_stats_pool_config_for_job", normal_configuration)

    with pytest.raises(_StartupObserved):
        module.main(args)

    assert events == ["download", "refresh", "counter", "configuration"]
    assert sys.path == original_path
    assert os.environ["PYTHONPATH"] == "existing-custom-import-path"


def test_restored_server_child_marks_missing_earlier_traffic(tmp_path, monkeypatch):
    counter = F3Counter()
    args = SimpleNamespace(set=[], workspace=str(tmp_path), job_id="job-1")
    monkeypatch.setattr(runner_process, "parse_vars", lambda _: {"restore_snapshot": "snapshot"})
    for name in ("download_workspace", "Workspace", "refresh_custom_dir_import_path"):
        monkeypatch.setattr(runner_process, name, MagicMock())
    monkeypatch.setattr(runner_process, "start_job_f3_counter", lambda: counter)
    monkeypatch.setattr(runner_process, "JobResourceCollector", lambda *_, **__: None)
    monkeypatch.setattr(runner_process, "set_stats_pool_config_for_job", MagicMock(side_effect=_StartupObserved))

    with pytest.raises(_StartupObserved):
        runner_process.main(args)

    assert counter.snapshot() == {"status": "partial", "issues": ["attribution_incomplete"], "sent_to": []}


@pytest.mark.parametrize("module", [worker_process, runner_process])
@pytest.mark.parametrize("callbacks_drained", [False, True])
def test_job_child_freezes_counter_before_existing_archive(module, callbacks_drained, tmp_path, monkeypatch):
    events = []
    counter = F3Counter()
    close_counter, freeze_counter, mark_gap = counter.close_and_drain, counter.freeze, counter.mark_counter_gap

    def close(timeout):
        events.append("close_counter")
        return close_counter(timeout)

    def freeze():
        events.append("freeze_counter")
        return freeze_counter()

    def gap():
        events.append("gap")
        return mark_gap()

    monkeypatch.setattr(counter, "close_and_drain", MagicMock(side_effect=close))
    monkeypatch.setattr(counter, "freeze", MagicMock(side_effect=freeze))
    monkeypatch.setattr(counter, "mark_counter_gap", gap)
    args = SimpleNamespace(
        set=[],
        workspace=str(tmp_path),
        client_name="site-1",
        job_id="job-1",
        token="token",
        token_signature="signature",
        ssid="session",
        app_root=str(tmp_path),
        root_url="root",
        parent_url="parent",
        host="localhost",
        port="8002",
    )
    workspace = MagicMock()
    workspace.get_file_path_in_root.side_effect = lambda name: str(tmp_path / name)
    app_runner, server, client, config = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(module, "parse_vars", lambda _: {"secure_train": False})
    monkeypatch.setattr(module, "Workspace", lambda *_, **__: workspace)
    monkeypatch.setattr(module, "JobResourceCollector", lambda *_, **__: None)
    monkeypatch.setattr(module.threading, "Thread", MagicMock())
    for name in (
        "download_workspace",
        "refresh_custom_dir_import_path",
        "set_stats_pool_config_for_job",
        "fobs_initialize",
        "security_init_for_job",
        "configure_logging",
        "register_ext_decomposers",
    ):
        monkeypatch.setattr(module, name, MagicMock())
    monkeypatch.setattr(module, "get_script_logger", MagicMock())
    monkeypatch.setattr(module, "start_job_f3_counter", lambda: counter)
    monkeypatch.setattr(module, "get_job_f3_counter", lambda: counter)
    monkeypatch.setattr(module, "create_stats_pool_files_for_job", lambda *_: events.append("stats"))
    monkeypatch.setattr(module, "upload_results_on_shutdown", lambda *_, **__: events.append("upload"))
    monkeypatch.setattr(job_process_cleanup, "shutdown_f3_streaming", lambda: events.append("streams"))
    monkeypatch.setattr(job_process_cleanup, "security_close", lambda: events.append("security"))

    def drain(_):
        events.append("callbacks")
        return callbacks_drained

    if module is worker_process:
        monkeypatch.setattr(module, "remove_restart_file", MagicMock())
        monkeypatch.setattr(module, "FLClientStarterConfiger", lambda **_: config)
        config.base_deployer.create_fed_client.return_value = client
        monkeypatch.setattr(module, "ClientAppRunner", lambda **_: app_runner)
        app_runner.close.side_effect = lambda: events.append("stop_commands")
        app_runner.wait_for_command_callbacks.side_effect = drain
        client.stop_cell.side_effect = lambda: events.append("cell")
    else:
        monkeypatch.setattr(module.os, "chdir", lambda _: None)
        monkeypatch.setattr(module, "FLServerStarterConfiger", lambda **_: config)
        config.deployer.create_fl_server.return_value = ({}, server)
        monkeypatch.setattr(module, "ServerAppRunner", lambda _: app_runner)
        monkeypatch.setattr(module, "set_add_auth_headers_filters", MagicMock())
        server.command_agent.shutdown.side_effect = lambda: events.append("stop_commands")
        server.command_agent.wait_for_callbacks.side_effect = drain
        server.create_job_cell.return_value = server.cell
        server.cell.stop.side_effect = lambda: events.append("cell")

    module.main(args)

    expected = ["stop_commands", "callbacks"]
    if not callbacks_drained:
        expected.append("gap")
    expected += ["close_counter", "freeze_counter", "stats", "upload", "streams", "cell"]
    if not callbacks_drained:
        expected.append("callbacks")
    expected.append("security")
    assert events == expected
    counter.close_and_drain.assert_called_once_with(F3_DRAIN_TIMEOUT_SECONDS)
    counter.freeze.assert_called_once_with()
    assert counter.snapshot() == (
        {"sent_to": []} if callbacks_drained else {"status": "partial", "issues": ["counter_gap"], "sent_to": []}
    )
    assert counter.try_begin(F3TrafficClass.TASK_RESULT, "server") is None


def test_restored_parent_starts_partial_registry_without_changing_restore(tmp_path):
    runner = job_runner.JobRunner(str(tmp_path))
    runner.scheduler = MagicMock()
    runner.log_warning = MagicMock()
    runner.log_error = MagicMock()
    ctx, engine = MagicMock(), MagicMock()
    ctx.get_engine.return_value = engine
    ctx.get_workspace.return_value.get_run_dir.return_value = str(tmp_path)
    engine.start_app_on_server.return_value = ""
    job = SimpleNamespace(job_id="job-1", meta={})
    engine.get_component.return_value.get_job.return_value = job
    clients = {"token": SimpleNamespace(name="site-1")}
    snapshot = object()

    runner.restore_running_job("job-1", clients, snapshot, ctx)

    counter = runner.f3_counters.get("job-1")
    assert counter is not None
    assert counter.snapshot() == {"status": "partial", "issues": ["attribution_incomplete"], "sent_to": []}
    assert runner.running_jobs["job-1"] is job
    engine.start_app_on_server.assert_called_once_with(
        ctx, job=job, job_clients=clients, snapshot=snapshot, restored_attempt=True
    )
    runner.scheduler.restore_scheduled_job.assert_called_once_with("job-1")


@pytest.mark.parametrize("failure_stage", [None, "archive", "status"])
def test_parent_freezes_without_wait_then_forgets_only_after_terminal_publication(failure_stage, tmp_path, monkeypatch):
    events = []
    runner = job_runner.JobRunner(str(tmp_path))
    runner._fire_job_lifecycle_event = MagicMock()
    ctx, engine, manager = MagicMock(), MagicMock(), MagicMock()
    ctx.get_engine.return_value = engine
    ctx.get_peer_context.return_value = None
    ctx.get_workspace.return_value.get_run_dir.return_value = str(tmp_path)
    engine.new_context.side_effect = lambda: nullcontext(ctx)
    engine.get_component.return_value = manager
    engine.run_processes = {}
    engine.exception_run_processes = {}
    runner.running_jobs = {"job-1": SimpleNamespace(job_id="job-1", run_aborted=True)}
    runner.resource_stats.start_job("job-1", [], str(tmp_path))
    counter = runner.f3_counters.start_job("job-1")
    counter.try_begin(F3TrafficClass.JOB_APPLICATION, "site-1")  # Pending work must not hold parent cleanup.
    original_freeze = runner.f3_counters.close_and_freeze
    original_forget = runner.f3_counters.forget_job

    def freeze(job_id, *, drain_timeout_seconds):
        events.append("freeze")
        assert drain_timeout_seconds == 0.0
        return original_freeze(job_id, drain_timeout_seconds=drain_timeout_seconds)

    def archive(*_):
        events.append("archive")
        assert counter.snapshot()["issues"] == ["counter_gap"]
        if failure_stage == "archive" and events.count("archive") == 1:
            raise OSError("archive not ready")

    def publish(*_):
        events.append("status")
        assert runner.f3_counters.get("job-1") is counter
        if failure_stage == "status" and events.count("status") == 1:
            raise OSError("status store not ready")

    def forget(job_id):
        events.append("forget")
        original_forget(job_id)

    passes = []

    def next_pass(_):
        passes.append(None)
        if len(passes) == (2 if failure_stage else 1):
            runner.stop()
        else:
            assert runner.f3_counters.get("job-1") is counter
            assert runner._finished_job_states["job-1"].resource_stats_finalized is True

    monkeypatch.setattr(runner.f3_counters, "close_and_freeze", freeze)
    monkeypatch.setattr(runner.f3_counters, "forget_job", forget)
    monkeypatch.setattr(runner, "_save_workspace", archive)
    manager.set_status.side_effect = publish
    monkeypatch.setattr(job_runner, "time", SimpleNamespace(sleep=next_pass, monotonic=lambda: 0.0))

    runner._job_complete_process(engine)

    expected = {
        None: ["freeze", "archive", "status", "forget"],
        "archive": ["freeze", "archive", "archive", "status", "forget"],
        "status": ["freeze", "archive", "status", "status", "forget"],
    }
    assert events == expected[failure_stage]
    assert runner.f3_counters.get("job-1") is None
    assert "job-1" not in runner.running_jobs
    assert manager.set_status.call_args.args[1] is RunStatus.FINISHED_ABORTED
