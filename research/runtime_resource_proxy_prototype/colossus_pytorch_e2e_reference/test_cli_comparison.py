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

"""Verify that the revised CLI examples render the archived Colossus JSON."""

import json
from pathlib import Path

from nvflare.tool.job.job_resources import render_job_resources, render_study_resources

ROOT = Path(__file__).resolve().parent
PREFIX = "Connecting to FLARE ...\n"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_revised_job_and_site_views_use_the_unchanged_archived_records():
    summary = _load(ROOT / "workspace/resource_stats/resource_summary.json")
    revised = ROOT / "cli/revised"

    assert (revised / "resources-job.txt").read_text() == PREFIX + render_job_resources(summary) + "\n"
    for participant_name in ("site-1", "site-2", "server"):
        participant = _load(ROOT / f"workspace/resource_stats/participants/{participant_name}.json")
        expected = PREFIX + render_job_resources(summary, participant) + "\n"
        assert (revised / f"resources-{participant_name}.txt").read_text() == expected


def test_revised_study_view_uses_the_unchanged_archived_response():
    envelope = _load(ROOT / "cli/resources-study.json")
    expected = PREFIX + render_study_resources(envelope["data"]["summary"]) + "\n"
    assert (ROOT / "cli/revised/resources-study.txt").read_text() == expected
