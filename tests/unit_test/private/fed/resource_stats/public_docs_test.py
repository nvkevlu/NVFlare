# Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.
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

"""Keep published resource-statistics examples aligned with production readers."""

import ast
import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from nvflare.private.fed.resource_stats.contract import derive_participant_totals, load_and_validate, validate_record
from nvflare.tool.job.job_resources import render_job_resources, render_study_resources

ROOT = Path(__file__).resolve().parents[5]
PUBLIC = ROOT / "docs/user_guide/admin_guide/resource_statistics"
GOLDEN = ROOT / "research/runtime_resource_proxy_prototype/schema/golden/v3"


@pytest.mark.parametrize(
    "published,golden",
    [
        ("participant_summary.json", "participant_summary.json"),
        ("resource_summary.json", "resource_summary.json"),
        ("job_resources.out", "resource_summary.txt"),
        ("study_resources.out", "study_summary.txt"),
    ],
)
def test_published_examples_match_current_goldens(published, golden):
    assert (PUBLIC / "examples" / published).read_bytes() == (GOLDEN / golden).read_bytes()


def test_published_records_reconcile_without_filesystem_capacity_in_job_summary():
    participant = load_and_validate((PUBLIC / "examples/participant_summary.json").read_bytes())
    summary = load_and_validate((PUBLIC / "examples/resource_summary.json").read_bytes())
    entry = next(
        item for item in summary["participants"] if item["participant_name"] == participant["participant_name"]
    )
    assert summary["job_id"] == participant["job_id"]
    for key, value in derive_participant_totals(participant).items():
        assert entry[key] == value
    assert "workspace_filesystem" in participant
    assert all("workspace_filesystem" not in item for item in summary["participants"])


def test_published_job_output_is_produced_by_current_renderer():
    summary = load_and_validate((PUBLIC / "examples/resource_summary.json").read_bytes())
    actual = render_job_resources(summary, job_name="Synthetic capacity contract example")
    assert actual + "\n" == (PUBLIC / "examples/job_resources.out").read_text()


def test_published_study_output_is_produced_by_current_renderer():
    study = load_and_validate((GOLDEN / "study_summary.json").read_bytes())
    assert render_study_resources(study) + "\n" == (PUBLIC / "examples/study_resources.out").read_text()


def _code_blocks(path, language):
    lines = path.read_text().splitlines()
    for index, line in enumerate(lines):
        if line != f".. code-block:: {language}":
            continue
        start = index + 1
        while start < len(lines) and not lines[start].strip():
            start += 1
        end = start
        while end < len(lines) and (lines[end].startswith("   ") or not lines[end].strip()):
            end += 1
        yield "\n".join(line[3:] for line in lines[start:end])


@pytest.mark.parametrize("page", ["cpu_work", "files", "message_traffic", "reports"])
def test_json_measurement_excerpts_fit_current_record(page):
    participant = load_and_validate((PUBLIC / "examples/participant_summary.json").read_bytes())
    blocks = list(_code_blocks(PUBLIC / f"{page}.rst", "json"))
    assert blocks
    for block in blocks:
        example = deepcopy(participant)
        example.update(json.loads(block))
        validate_record(example)


@pytest.mark.parametrize("page", ["cpu_work", "files"])
def test_diagnostic_python_snippets_are_syntactically_valid(page):
    scripts = []
    for block in _code_blocks(PUBLIC / f"{page}.rst", "shell"):
        scripts.extend(re.findall(r"<<'PY'\n(.*?)\nPY", block, flags=re.DOTALL))
    assert scripts
    for script in scripts:
        ast.parse(script)


def test_public_guide_does_not_ask_users_to_import_private_helpers():
    pages = [PUBLIC.with_suffix(".rst"), *PUBLIC.glob("*.rst")]
    for page in pages:
        assert not re.search(r"^\s*(?:from|import) nvflare\.private\b", page.read_text(), flags=re.MULTILINE), page
