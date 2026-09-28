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
from decimal import Decimal
from pathlib import Path

import pytest

from nvflare.private.fed.resource_stats.contract import ContractError, validate_record

_FIXED_RUN = Path(__file__).parent / "colossus_pytorch_e2e_reference" / "fixed_run" / "cli"


def _read_envelope(name: str) -> dict:
    value = json.loads((_FIXED_RUN / name).read_text(encoding="utf-8"))
    assert value["schema_version"] == "1"
    assert value["status"] == "ok"
    assert value["exit_code"] == 0
    return value["data"]


def test_fixed_colossus_run_reconciles_as_a_pre_job_name_capture():
    job_data = _read_envelope("resources-job.json")
    site_data = _read_envelope("resources-site-1.json")
    study_data = _read_envelope("resources-study.json")

    job_summary = job_data["summary"]
    site_report = site_data["participant"]
    study_summary = study_data["summary"]
    assert "f3" in site_report
    with pytest.raises(ContractError):
        validate_record(site_report)

    # This immutable September 21 capture predates the required v1 job_name
    # field. It remains useful measurement evidence, but it must not be
    # mistaken for a record produced by the current contract or renderer.
    assert "job_name" not in job_summary
    assert all("job_name" not in row for row in study_summary["jobs"])
    with pytest.raises(ContractError, match="missing required fields: job_name"):
        validate_record(job_summary)
    with pytest.raises(ContractError, match="missing required fields: job_name"):
        validate_record(study_summary)

    assert Decimal(job_summary["totals"]["resource_time"]["measured_seconds"]) == sum(
        Decimal(entry["resource_time"]["measured_seconds"])
        for entry in job_summary["participants"]
        if entry["status"] == "accepted"
    )
    assert Decimal(study_summary["totals"]["resource_time"]["measured_seconds"]) == sum(
        Decimal(row["totals"]["resource_time"]["measured_seconds"])
        for row in study_summary["jobs"]
        if row["resource_data"] == "included"
    )
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

    job_text = (_FIXED_RUN / "resources-job.txt").read_text(encoding="utf-8")
    site_text = (_FIXED_RUN / "resources-site-1.txt").read_text(encoding="utf-8")
    study_text = (_FIXED_RUN / "resources-study.txt").read_text(encoding="utf-8")
    assert f'Recorded resources for job {job_summary["job_id"]}.' in job_text
    assert "CPU 2.0314 unit h | MEMORY 7.9765 GiB h | FULL GPUs 0.0635 instance h" in job_text
    assert "| selected site: site-1" in site_text
    assert "NVIDIA L40" in site_text
    for row in study_summary["jobs"]:
        assert row["job_id"] in study_text
