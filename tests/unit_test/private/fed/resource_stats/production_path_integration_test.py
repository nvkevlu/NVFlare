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

"""Focused integration coverage for the production resource-statistics path.

This test deliberately stops at deterministic in-process boundaries.  It uses
the real authenticated server request handler, coordinator, final workspace
bundle, admin command reader, and human renderer.  CellNet serialization and a
live job-store backend are covered by their own subsystem tests rather than by
opening a network connection here.
"""

import io
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from zipfile import ZIP_DEFLATED, ZipFile

from nvflare.apis.job_def import JobMetaKey, RunStatus
from nvflare.apis.job_def_manager_spec import JobDefManagerSpec
from nvflare.fuel.f3.cellnet.defs import MessageHeaderKey
from nvflare.private.defs import CellMessageHeaderKeys, JobFailureMsgKey, new_cell_message
from nvflare.private.fed.resource_stats.collector import (
    JobResourceCollector,
    assemble_participant_summary,
    canonical_json_bytes,
    read_terminal_handoff,
    write_terminal_handoff,
)
from nvflare.private.fed.resource_stats.coordinator import ResourceStatsCoordinator
from nvflare.private.fed.server.fed_server import FederatedServer
from nvflare.private.fed.server.job_cmds import JobCommandModule
from nvflare.private.fed.server.job_runner import JobRunner
from nvflare.tool.job.job_resources import render_job_resources


class _Connection:
    def __init__(self, engine, job_id):
        self.app_ctx = engine
        self._props = {
            JobCommandModule.JOB_ID: job_id,
            JobCommandModule.JOB: SimpleNamespace(meta={JobMetaKey.STATUS.value: RunStatus.FINISHED_COMPLETED}),
        }
        self.dicts = []
        self.errors = []

    def get_prop(self, key, default=None):
        return self._props.get(key, default)

    def append_dict(self, value, meta=None):
        self.dicts.append((value, meta))

    def append_error(self, value, meta=None):
        self.errors.append((value, meta))


def _workspace_zip(run_dir):
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for path in sorted(run_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(run_dir).as_posix())
    return stream.getvalue()


def _terminal_handoff(run_dir, *, seconds, cpu_units, memory_bytes, gpu_count):
    start_ns = 8_000_000_000_000_000_000
    elapsed_ns = int(seconds * 1_000_000_000)
    ticks = iter((start_ns, start_ns + elapsed_ns))
    collector = JobResourceCollector(
        run_dir,
        clock_ns=lambda: next(ticks),
        capacity_probe=lambda: {
            "cpu": {
                "units": cpu_units,
                "model": "AMD EPYC 9654",
                "architecture": "x86_64",
            },
            "memory": {"bytes": memory_bytes},
            "gpu": {
                "groups": (
                    [
                        {
                            "kind": "full_gpu",
                            "count": gpu_count,
                            "model": "NVIDIA A100 80GB",
                            "memory_bytes": 80 * 2**30,
                        }
                    ]
                    if gpu_count
                    else []
                )
            },
        },
    )
    write_terminal_handoff(run_dir, collector.finish())
    return read_terminal_handoff(run_dir)


def test_authenticated_report_to_workspace_query_and_human_output(tmp_path):
    job_id = "job-20260917-001"
    participant_name = "site-1"
    run_dir = tmp_path / job_id
    coordinator = ResourceStatsCoordinator()
    coordinator.start_job(job_id, [participant_name], run_dir)

    client_report = assemble_participant_summary(
        job_id=job_id,
        participant_name=participant_name,
        child_handoff=_terminal_handoff(
            run_dir,
            seconds=2223.5,
            cpu_units=8,
            memory_bytes=64 * 2**30,
            gpu_count=2,
        ),
    )
    participant_bytes = canonical_json_bytes(client_report)

    # Drive the existing authenticated terminal-outcome request handler.  The
    # untrusted ORIGIN says something else; the token-owned registration binds
    # these bytes to the readable participant name "site-1".
    job_runner = JobRunner(str(tmp_path))
    job_runner.resource_stats = coordinator
    job_runner._pending_client_outcomes = {job_id: {participant_name}}
    server = object.__new__(FederatedServer)
    server.logger = MagicMock()
    server.client_manager = MagicMock()
    server.client_manager.is_from_authorized_client.return_value = True
    registered_client = MagicMock()
    registered_client.name = participant_name
    server.client_manager.clients = {"token-1": registered_client}
    server.engine = SimpleNamespace(job_runner=job_runner)
    request = new_cell_message(
        {
            CellMessageHeaderKeys.TOKEN: "token-1",
            MessageHeaderKey.ORIGIN: "spoofed-participant",
        },
        {
            JobFailureMsgKey.JOB_ID: job_id,
            JobFailureMsgKey.CODE: 0,
            JobFailureMsgKey.REASON: "",
            JobFailureMsgKey.RESOURCE_REPORT: {
                JobFailureMsgKey.PARTICIPANT_SUMMARY: participant_bytes,
            },
        },
    )

    reply = FederatedServer.process_job_failure(server, request)

    assert reply.payload == {JobFailureMsgKey.RESOURCE_REPORT_STATUS: "accepted"}
    assert not job_runner.is_client_outcome_pending(job_id, participant_name)

    # Exercise the real server-parent handoff assembly path for the second
    # expected participant so final coverage is complete.
    _terminal_handoff(
        run_dir,
        seconds=2240,
        cpu_units=2,
        memory_bytes=16 * 2**30,
        gpu_count=0,
    )
    fl_ctx = MagicMock()
    fl_ctx.get_workspace.return_value.get_run_dir.return_value = str(run_dir)
    JobRunner._accept_server_resource_report(job_runner, job_id, fl_ctx)

    finalized = coordinator.finalize_job(job_id)
    workspace_zip = _workspace_zip(run_dir)

    # Read through the production admin command exactly as the public Session
    # API does.  The mocked manager represents only the durable job-store I/O;
    # summary validation, inventory verification, participant selection, and response
    # construction are all production code.
    staged_paths = []
    stored_workspace_path = tmp_path / "stored-workspace"
    stored_workspace_path.write_bytes(workspace_zip)

    def _stage_workspace(jid, download_dir, component, download_file, fl_ctx):
        archive_path = Path(download_dir) / jid / download_file
        archive_path.parent.mkdir(parents=True)
        archive_path.symlink_to(stored_workspace_path)
        staged_paths.append(archive_path)

    manager = MagicMock(spec=JobDefManagerSpec)
    manager.get_storage_for_download.side_effect = _stage_workspace
    manager.get_storage_component.side_effect = AssertionError("resource query must not materialize workspace bytes")
    engine = SimpleNamespace(job_def_manager=manager, new_context=lambda: nullcontext(None))
    connection = _Connection(engine, job_id)
    JobCommandModule().get_job_resources(
        connection,
        ["get_job_resources", job_id, "--site", participant_name],
    )

    assert connection.errors == []
    manager.get_storage_for_download.assert_called_once()
    manager.get_storage_component.assert_not_called()
    assert len(staged_paths) == 1
    assert not staged_paths[0].exists()
    assert stored_workspace_path.exists()
    result, _meta = connection.dicts[0]
    assert result["resource_summary"] == finalized
    assert result["participant_summary"] == client_report
    assert [item["participant_name"] for item in finalized["participants"]] == [participant_name, "server"]
    assert finalized["totals"]["resource_time"]["measured_seconds"] == "4463.5"

    output = render_job_resources(finalized, result["participant_summary"])
    assert "selected site: site-1" in output
    assert "AMD EPYC 9654 (x86_64)" in output
    assert "NVIDIA A100 80GB" in output
    assert "8000000000000000000" not in participant_bytes.decode()
    assert client_report["resource_time"]["measured_seconds"] == "2223.5"
