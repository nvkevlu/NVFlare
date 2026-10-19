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

"""Archive queries validate requested reports, not an exclusive directory."""

import io
import json
from copy import deepcopy
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from nvflare.private.fed.resource_stats import archive_reader
from nvflare.private.fed.resource_stats.archive_reader import WorkspaceResourceStatsError, WorkspaceResourceStatsReader
from nvflare.private.fed.resource_stats.contract import (
    SCHEMA_VERSION,
    canonical_json_bytes,
    normalize_record,
    participant_measurements,
)


def _reports():
    participant = {
        "schema_version": SCHEMA_VERSION,
        "kind": "nvflare.resource_stats.participant_summary",
        "job_id": "job-1",
        "participant_name": "site-1",
        "reported_at": "2026-09-17T12:00:00Z",
        "resource_capacity": {
            "status": "partial",
            "issues": ["attribution_incomplete", "observation_incomplete"],
            "measured_seconds": "10",
            "cpu": {"groups": [{"units": "2", "model": "CPU A"}, {"units": "1", "model": "CPU B"}]},
            "memory": {"bytes": "4096"},
            "gpu": {
                "groups": [
                    {"kind": "cuda_device_unclassified", "count": "1"},
                    {"kind": "full_gpu", "count": "1", "memory_bytes": "4096"},
                ]
            },
        },
        "cpu_consumed": {"seconds": "2"},
        "workspace_filesystem": {"capacity_bytes": "4096"},
        "retained_content": {"bytes": "20"},
        "message_traffic": {"sent_to": []},
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "kind": "nvflare.resource_stats.resource_summary",
        "job_id": "job-1",
        "participants": [
            {
                "participant_name": "site-1",
                "role": "client",
                "received_at": "2026-09-17T12:00:01Z",
                **participant_measurements(participant),
            },
            {"participant_name": "server", "role": "server", "status": "missing"},
        ],
    }
    return normalize_record(summary), participant


def _archive(summary, participant=None, extra=()):
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("resource_stats/resource_summary.json", canonical_json_bytes(summary))
        if participant is not None:
            archive.writestr("resource_stats/participants/site-1.json", canonical_json_bytes(participant))
        for name, data in extra:
            archive.writestr(name, data)
    return stream.getvalue()


def test_summary_does_not_open_unrequested_participant_body():
    summary, _ = _reports()
    reader = WorkspaceResourceStatsReader(
        _archive(summary, extra=[("resource_stats/participants/site-1.json", b"not JSON")])
    )
    assert reader.read_resource_summary() == summary
    with pytest.raises(WorkspaceResourceStatsError, match="participant summary is invalid"):
        reader.read_participant_summary("site-1")


def test_requested_detail_can_use_equivalent_numeric_strings_and_list_order():
    summary, participant = _reports()
    participant["resource_capacity"]["issues"].reverse()
    participant["resource_capacity"]["cpu"]["groups"].reverse()
    participant["resource_capacity"]["gpu"]["groups"].reverse()
    participant["resource_capacity"]["measured_seconds"] = "10.0"
    participant["resource_capacity"]["cpu"]["groups"][0]["units"] = "1.000"
    participant["resource_capacity"]["memory"]["bytes"] = "4096.0"
    participant["resource_capacity"]["gpu"]["groups"][0]["count"] = "1.0"
    participant["cpu_consumed"]["seconds"] = "2.000"
    participant["retained_content"]["bytes"] = "20.0"
    participant["resource_capacity"]["gpu"]["groups"][0]["memory_bytes"] = "4096.0"
    reader = WorkspaceResourceStatsReader(_archive(summary, participant))
    detail = reader.read_participant_summary("site-1")
    assert detail["cpu_consumed"]["seconds"] == "2"
    assert detail["retained_content"]["bytes"] == "20"
    assert detail["resource_capacity"] == summary["participants"][0]["resource_capacity"]


@pytest.mark.parametrize("field,value", [("job_id", "other-job"), ("participant_name", "other-site")])
def test_requested_detail_identity_must_match_summary_and_slot(field, value):
    summary, participant = _reports()
    participant[field] = value
    reader = WorkspaceResourceStatsReader(_archive(summary, participant))
    assert reader.read_resource_summary() == summary
    with pytest.raises(WorkspaceResourceStatsError, match="identity does not match"):
        reader.read_participant_summary("site-1")


def test_requested_detail_size_limit_is_checked_only_for_detail(monkeypatch):
    summary, participant = _reports()
    monkeypatch.setattr(archive_reader, "MAX_PARTICIPANT_SUMMARY_BYTES", 1)
    reader = WorkspaceResourceStatsReader(_archive(summary, participant))
    assert reader.read_resource_summary() == summary
    with pytest.raises(WorkspaceResourceStatsError, match="size limit"):
        reader.read_participant_summary("site-1")


def test_detail_ignores_other_missing_participant_reports():
    summary, participant = _reports()
    other = deepcopy(summary["participants"][0])
    other["participant_name"] = "site-2"
    summary["participants"].append(other)
    reader = WorkspaceResourceStatsReader(_archive(summary, participant))
    assert reader.read_resource_summary() == normalize_record(summary)
    assert reader.read_participant_summary("site-1") == participant
    with pytest.raises(WorkspaceResourceStatsError, match="found 0"):
        reader.read_participant_summary("site-2")


def test_summary_accepts_compact_json():
    summary, _ = _reports()
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        archive.writestr("resource_stats/resource_summary.json", json.dumps(summary, separators=(",", ":")))
    assert WorkspaceResourceStatsReader(stream.getvalue()).read_resource_summary() == summary


@pytest.mark.parametrize("old_version", ["1.0", "2.0"])
def test_summary_rejects_unreleased_prototype_formats(old_version):
    summary, _ = _reports()
    summary["schema_version"] = old_version

    with pytest.raises(WorkspaceResourceStatsError, match="schema_version"):
        WorkspaceResourceStatsReader(_archive(summary)).read_resource_summary()
