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

from nvflare.private.fed.resource_stats.contract import derive_job_totals, derive_study_totals, validate_record
from nvflare.tool.job.job_resources import render_job_resources, render_study_resources

_FIXED_RUN = Path(__file__).parent / "colossus_pytorch_e2e_reference" / "fixed_run" / "cli"


def _read_envelope(name: str) -> dict:
    value = json.loads((_FIXED_RUN / name).read_text(encoding="utf-8"))
    assert value["schema_version"] == "1"
    assert value["status"] == "ok"
    assert value["exit_code"] == 0
    return value["data"]


def test_fixed_colossus_run_reconciles_and_matches_current_human_renderer():
    job_data = _read_envelope("resources-job.json")
    site_data = _read_envelope("resources-site-1.json")
    study_data = _read_envelope("resources-study.json")

    job_summary = job_data["summary"]
    site_report = site_data["participant"]
    study_summary = study_data["summary"]
    validate_record(job_summary)
    validate_record(site_report)
    validate_record(study_summary)

    assert job_summary["totals"] == derive_job_totals(job_summary["participants"])
    assert study_summary["totals"] == derive_study_totals(study_summary["jobs"])
    assert site_data["summary"] == job_summary
    assert site_report["participant_name"] == "site-1"
    assert site_report["workspace_filesystem"] == {
        "status": "reported",
        "capacity_bytes": "1889447919616",
    }

    for entry in job_summary["participants"]:
        assert entry["status"] == "accepted"
        assert entry["resource_time"]["status"] == "reported"
        assert entry["resource_time"]["gpu"]["groups"] == [
            {
                "kind": "full_gpu",
                "instance_seconds": entry["resource_time"]["measured_seconds"],
                "model": "NVIDIA L40",
                "memory_bytes": "48305799168",
            }
        ]
        assert entry["retained_content"] == {"status": "unavailable", "issues": ["not_bound"]}
        assert entry["f3"] == {"status": "unavailable", "issues": ["not_bound"]}

    connection_prefix = "Connecting to FLARE ...\n"
    assert (_FIXED_RUN / "resources-job.txt").read_text(encoding="utf-8") == (
        connection_prefix + render_job_resources(job_summary) + "\n"
    )
    assert (_FIXED_RUN / "resources-site-1.txt").read_text(encoding="utf-8") == (
        connection_prefix + render_job_resources(job_summary, site_report) + "\n"
    )
    assert (_FIXED_RUN / "resources-study.txt").read_text(encoding="utf-8") == (
        connection_prefix + render_study_resources(study_summary) + "\n"
    )
