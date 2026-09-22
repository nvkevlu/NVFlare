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

import io
import json
from zipfile import ZIP_DEFLATED, ZipFile

from nvflare.private.fed.resource_stats.archive_reader import WorkspaceResourceStatsReader
from nvflare.private.fed.resource_stats.contract import (
    KIND_RESOURCE_SUMMARY,
    KIND_STUDY_SUMMARY,
    derive_job_totals,
    derive_study_totals,
    load_and_validate,
)
from nvflare.tool.job.job_resources import render_job_resources, render_study_resources
from research.runtime_resource_proxy_prototype.production_reference.generate_reference import (
    ARTIFACTS_DIR,
    build_artifacts,
    check_artifacts,
)


def _workspace_zip(artifacts):
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for path, data in sorted(artifacts.items()):
            if path.startswith("workspace/"):
                archive.writestr(path.removeprefix("workspace/"), data)
    return stream.getvalue()


def _keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _keys(nested)


def test_checked_in_outputs_are_exact_production_regeneration_and_reconcile():
    artifacts = build_artifacts()

    assert check_artifacts(ARTIFACTS_DIR) == []

    reader = WorkspaceResourceStatsReader(_workspace_zip(artifacts))
    job_summary = reader.read_resource_summary()
    site_report = reader.read_participant_summary("site-1")
    server_report = reader.read_participant_summary("server")

    assert (
        load_and_validate(
            artifacts["workspace/resource_stats/resource_summary.json"],
            KIND_RESOURCE_SUMMARY,
        )
        == job_summary
    )
    assert job_summary["totals"] == derive_job_totals(job_summary["participants"])
    assert {entry["participant_name"] for entry in job_summary["participants"]} == {"server", "site-1"}
    assert site_report["participant_name"] == "site-1"
    assert server_report["participant_name"] == "server"

    for report in (site_report, server_report):
        assert report["retained_content"] == {"status": "unavailable", "issues": ["not_bound"]}
        assert report["f3"]["status"] == "reported"
        assert int(report["f3"]["remote_accepted"]["payload_bytes"]) > 0
    assert site_report["f3"]["remote_accepted"]["messages"] == "3"
    assert server_report["f3"]["remote_accepted"]["messages"] == "4"

    study_summary = load_and_validate(
        artifacts["query/resources-study.json"],
        KIND_STUDY_SUMMARY,
    )
    assert study_summary["totals"] == derive_study_totals(study_summary["jobs"])

    assert artifacts["cli/resources-job.txt"].decode() == render_job_resources(job_summary) + "\n"
    assert artifacts["cli/resources-site-1.txt"].decode() == (render_job_resources(job_summary, site_report) + "\n")
    assert artifacts["cli/resources-study.txt"].decode() == render_study_resources(study_summary) + "\n"

    job_cli = json.loads(artifacts["cli/resources-job.json"])
    site_cli = json.loads(artifacts["cli/resources-site-1.json"])
    study_cli = json.loads(artifacts["cli/resources-study.json"])
    for envelope in (job_cli, site_cli, study_cli):
        assert set(envelope) == {"schema_version", "status", "exit_code", "data"}
        assert envelope["schema_version"] == "1"
        assert envelope["status"] == "ok"
        assert envelope["exit_code"] == 0
        assert not any(key.endswith("_ns") for key in _keys(envelope))
    assert {entry["participant_name"] for entry in job_cli["data"]["summary"]["participants"]} == {
        "server",
        "site-1",
    }
    assert site_cli["data"]["participant"]["participant_name"] == "site-1"
    assert study_cli["data"]["selection"] == {"study": "cancer-research"}

    accepted_names = {
        entry["participant_name"] for entry in job_summary["participants"] if entry["status"] == "accepted"
    }
    assert {path for path in artifacts if path.startswith("workspace/resource_stats/")} == {
        "workspace/resource_stats/resource_summary.json",
        *(f"workspace/resource_stats/participants/{name}.json" for name in accepted_names),
    }
    for path, data in artifacts.items():
        if path.endswith(".json"):
            value = json.loads(data)
            assert "participant_key" not in json.dumps(value)
            assert not any(key.endswith("_ns") for key in _keys(value))
