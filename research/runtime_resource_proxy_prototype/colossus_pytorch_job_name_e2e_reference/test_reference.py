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

"""Verify an immutable live capture made before the slimmer job summary."""

import json
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import pytest

from nvflare.private.fed.resource_stats.contract import ContractError, validate_record

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
CLI = ARTIFACTS / "cli"
JOB_ID = "a624b97e-2eba-4b1c-bb44-765d83dd945b"
JOB_NAME = "hello-pt"
PREFIX = "Connecting to FLARE ...\n"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_historical_live_archive_and_cli_reconcile_with_trusted_job_name():
    job_envelope = _load(CLI / "resources-job.json")
    site_envelope = _load(CLI / "resources-site-1.json")
    study_envelope = _load(CLI / "resources-study.json")
    job_summary = job_envelope["data"]["summary"]
    site_report = site_envelope["data"]["participant"]
    study_summary = study_envelope["data"]["summary"]

    # The live files are preserved exactly as captured. The current closed
    # contract omits stored job totals/timestamps and uses message_traffic.
    assert {"report_cutoff_at", "finalized_at", "totals", "job_name"} <= set(job_summary)
    assert "f3" in site_report
    with pytest.raises(ContractError):
        validate_record(job_summary)
    with pytest.raises(ContractError):
        validate_record(site_report)
    with pytest.raises(ContractError):
        validate_record(study_summary)

    with ZipFile(ARTIFACTS / "job-store" / "workspace") as archive:
        assert json.loads(archive.read("resource_stats/resource_summary.json")) == job_summary
        assert json.loads(archive.read("resource_stats/participants/site-1.json")) == site_report
        for participant_name in ("site-1", "site-2", "server"):
            assert json.loads(archive.read(f"resource_stats/participants/{participant_name}.json")) == _load(
                ARTIFACTS / "extracted-workspace" / "resource_stats" / "participants" / f"{participant_name}.json"
            )
    extracted = ARTIFACTS / "extracted-workspace" / "resource_stats"
    assert _load(extracted / "resource_summary.json") == job_summary

    metadata = _load(ARTIFACTS / "job-store" / "meta")
    assert metadata["job_id"] == JOB_ID
    assert metadata["name"] == JOB_NAME
    assert job_summary["job_id"] == JOB_ID
    assert job_summary["job_name"] == JOB_NAME
    assert site_envelope["data"]["summary"] == job_summary

    accepted = [entry for entry in job_summary["participants"] if entry["status"] == "accepted"]
    assert len(accepted) == 3
    assert Decimal(job_summary["totals"]["resource_time"]["measured_seconds"]) == sum(
        Decimal(entry["resource_time"]["measured_seconds"]) for entry in accepted
    )
    assert int(job_summary["totals"]["retained_content"]["bytes"]) == sum(
        int(entry["retained_content"]["bytes"]) for entry in accepted
    )
    assert int(job_summary["totals"]["f3"]["remote_accepted"]["payload_bytes"]) == sum(
        int(entry["f3"]["remote_accepted"]["payload_bytes"]) for entry in accepted
    )
    assert study_summary["totals"] == job_summary["totals"]
    assert study_summary["jobs"] == [
        {
            "job_id": JOB_ID,
            "job_name": JOB_NAME,
            "job_status": "FINISHED:COMPLETED",
            "resource_data": "included",
            "totals": job_summary["totals"],
        }
    ]

    assert job_summary["totals"]["retained_content"] == {"status": "reported", "bytes": "761986"}
    assert job_summary["totals"]["f3"] == {
        "status": "reported",
        "remote_accepted": {"payload_bytes": "3080186", "messages": "14"},
    }

    assert (CLI / "resources-job.txt").read_text(encoding="utf-8").startswith(
        PREFIX + f"Recorded resources for job {JOB_NAME} (ID: {JOB_ID}).\n"
    )
    assert "selected site: site-1" in (CLI / "resources-site-1.txt").read_text(encoding="utf-8")
    assert "JOB ID" in (CLI / "resources-study.txt").read_text(encoding="utf-8")
    assert JOB_NAME in (CLI / "resources-study.txt").read_text(encoding="utf-8")
