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

"""Verify immutable pre-job-name CLI examples against their archived data."""

import json
from pathlib import Path

import pytest

from nvflare.private.fed.resource_stats.contract import ContractError, validate_record

ROOT = Path(__file__).resolve().parent
PREFIX = "Connecting to FLARE ...\n"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_revised_job_and_site_views_remain_pre_job_name_snapshots():
    summary = _load(ROOT / "workspace/resource_stats/resource_summary.json")
    revised = ROOT / "cli/revised"

    assert "job_name" not in summary
    with pytest.raises(ContractError, match="missing required fields: job_name"):
        validate_record(summary)

    job_text = (revised / "resources-job.txt").read_text()
    assert job_text.startswith(PREFIX + f'Recorded resources for job {summary["job_id"]}.\n')
    assert "CPU 2.0449 unit h | MEMORY 8.0294 GiB h | FULL GPUs N/A" in job_text
    for participant_name in ("site-1", "site-2", "server"):
        participant = _load(ROOT / f"workspace/resource_stats/participants/{participant_name}.json")
        assert "f3" in participant
        with pytest.raises(ContractError):
            validate_record(participant)
        participant_text = (revised / f"resources-{participant_name}.txt").read_text()
        assert participant_text.startswith(PREFIX + f'Recorded resources for job {summary["job_id"]}.\n')
        assert f"| selected site: {participant_name}" in participant_text


def test_revised_study_view_remains_a_pre_job_name_snapshot():
    envelope = _load(ROOT / "cli/resources-study.json")
    summary = envelope["data"]["summary"]
    assert all("job_name" not in row for row in summary["jobs"])
    with pytest.raises(ContractError, match="missing required fields: job_name"):
        validate_record(summary)

    study_text = (ROOT / "cli/revised/resources-study.txt").read_text()
    assert study_text.startswith(PREFIX + "Resources recorded for finalized jobs in study default.\n")
    for row in summary["jobs"]:
        assert row["job_id"] in study_text
    assert "CPU 2.0449 unit h | MEMORY 8.0294 GiB h" in study_text
