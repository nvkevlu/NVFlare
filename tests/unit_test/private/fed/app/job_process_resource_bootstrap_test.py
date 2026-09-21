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

from types import SimpleNamespace

import pytest

from nvflare.private.fed.app.client import worker_process
from nvflare.private.fed.app.server import runner_process


class _StopAfterBootstrap(Exception):
    pass


class _Workspace:
    def __init__(self, *_args, **_kwargs):
        pass

    def get_run_dir(self, job_id):
        return f"/workspace/{job_id}"

    def get_app_custom_dir(self, job_id):
        return f"/workspace/{job_id}/app/custom"

    def get_site_custom_dir(self):
        return "/workspace/local/custom"


@pytest.mark.parametrize(
    "module,args",
    [
        (
            worker_process,
            SimpleNamespace(set=[], workspace="/workspace", client_name="site-1", job_id="job-1"),
        ),
        (
            runner_process,
            SimpleNamespace(set=[], workspace="/workspace", job_id="job-1"),
        ),
    ],
)
def test_initial_snapshot_precedes_workspace_download_and_custom_imports(monkeypatch, module, args):
    events = []
    monkeypatch.setattr(module, "parse_vars", lambda _values: {})
    monkeypatch.setattr(module, "Workspace", _Workspace)
    monkeypatch.setattr(module, "JobResourceCollector", lambda run_dir, **_kwargs: events.append(("snapshot", run_dir)))
    monkeypatch.setattr(module, "download_workspace", lambda *_args, **_kwargs: events.append(("download", None)))
    monkeypatch.setattr(
        module,
        "activate_job_python_path",
        lambda paths: events.append(("activate", tuple(paths))),
    )

    def stop_after_bootstrap(*_args, **_kwargs):
        raise _StopAfterBootstrap

    monkeypatch.setattr(module, "set_stats_pool_config_for_job", stop_after_bootstrap)

    with pytest.raises(_StopAfterBootstrap):
        module.main(args)

    assert [name for name, _value in events] == ["snapshot", "download", "activate"]
    assert events[2][1] == ("/workspace/job-1/app/custom", "/workspace/local/custom")


def test_restored_server_marks_pre_restart_observation_incomplete(monkeypatch):
    collector_args = []
    args = SimpleNamespace(set=[], workspace="/workspace", job_id="job-1")
    monkeypatch.setattr(runner_process, "parse_vars", lambda _values: {"restore_snapshot": "snapshot-id"})
    monkeypatch.setattr(runner_process, "Workspace", _Workspace)
    monkeypatch.setattr(
        runner_process,
        "JobResourceCollector",
        lambda run_dir, **kwargs: collector_args.append((run_dir, kwargs)),
    )
    monkeypatch.setattr(runner_process, "download_workspace", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner_process, "activate_job_python_path", lambda _paths: None)

    def stop_after_bootstrap(*_args, **_kwargs):
        raise _StopAfterBootstrap

    monkeypatch.setattr(runner_process, "set_stats_pool_config_for_job", stop_after_bootstrap)

    with pytest.raises(_StopAfterBootstrap):
        runner_process.main(args)

    assert collector_args == [
        (
            "/workspace/job-1",
            {"prior_observation_incomplete": True},
        )
    ]
