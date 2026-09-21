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

"""Write deterministic, review-only artifacts for the prototype contracts.

The normal generator deliberately captures only what the local process can
actually observe. These fixtures exercise proposed runtime boundaries that
cannot be honestly installed in this standalone process yet: a CUDA runtime
adapter, an NVFlare-only F3 sender hook, changing resource observations, and
archived workspace access. Every file declares itself a synthetic contract
fixture; none is a local observation or production evidence.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from f3_finalization import F3FinalizationCounter, JobTrafficClass, JobTrafficEvent
from prototype_contract import (
    RESOURCE_SUMMARY_MEMBER,
    WORKSPACE_COMPONENT,
    ResourceTimeAccumulator,
    WorkspaceResourceStatsReader,
    assemble_participant_summary,
)
from runtime_probe import probe_gpu_records

_FIXTURE_PARTICIPANT_NAME = "site-1"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _json_bytes(value)
    path.write_bytes(data)
    return data


class _FixtureCudaRuntime:
    """A successful CUDA-runtime result; identities must never be exported."""

    def enumerate_visible_devices(self):
        return [
            {"cuda_identity": "runtime-full-0", "device_kind": "full_gpu"},
            {"cuda_identity": "runtime-mig-0", "device_kind": "mig_compute_instance"},
            {"cuda_identity": "runtime-mig-1", "device_kind": "mig_compute_instance"},
        ]


class _FixtureNvml:
    """Normal-user metadata supplied only for CUDA-validated identities."""

    def enrich_cuda_device(self, cuda_identity: str):
        return {
            "cuda_identity": cuda_identity,
            "vendor": "nvidia",
            "model": "NVIDIA A100-SXM4-40GB",
            "memory_bytes": 5 * 1024**3 if "mig" in cuda_identity else 40 * 1024**3,
            "mig_profile": "1g.5gb" if "mig" in cuda_identity else None,
        }


def _gpu_fixture() -> dict[str, Any]:
    """Exercise a visible mask without exporting or interpreting its raw value."""

    original = os.environ.get("CUDA_VISIBLE_DEVICES")
    was_present = "CUDA_VISIBLE_DEVICES" in os.environ
    try:
        # The value is intentionally a non-meaningful fixture string.  The
        # probe records only its presence; the validated runtime supplies count.
        os.environ["CUDA_VISIBLE_DEVICES"] = "fixture-mask-never-exported"
        metrics = probe_gpu_records(_FixtureCudaRuntime(), _FixtureNvml())
    finally:
        if was_present:
            assert original is not None
            os.environ["CUDA_VISIBLE_DEVICES"] = original
        else:
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
    return {
        "schema_version": "prototype-0.3",
        "kind": "nvflare.resource_stats.gpu_authority_fixture",
        "provenance": "synthetic_contract_fixture",
        "rule": (
            "numeric GPU records require successful CUDA-runtime enumeration; " "NVML only enriches matched identities"
        ),
        "metrics": metrics,
        "raw_cuda_visible_devices": "not_emitted",
    }


def _f3_fixture() -> dict[str, Any]:
    counter = F3FinalizationCounter()
    counter.send_remote(JobTrafficEvent(JobTrafficClass.TASK_REQUEST, 1536), lambda: None)
    counter.send_remote(JobTrafficEvent(JobTrafficClass.TASK_RESULT, 4096), lambda: None)
    counter.deliver_direct(JobTrafficEvent(JobTrafficClass.JOB_APPLICATION, 256), lambda: None)
    counter.send_remote(JobTrafficEvent(JobTrafficClass.PLATFORM_CONTROL, 64), lambda: None)
    frozen = counter.freeze()
    counter.send_resource_summary(JobTrafficEvent(JobTrafficClass.JOB_APPLICATION, 1024), lambda: None)
    counter.send_remote(JobTrafficEvent(JobTrafficClass.TASK_RESULT, 512), lambda: None)
    post_cutoff = counter.snapshot()

    def canonical_counter(bucket: dict[str, int]) -> dict[str, str]:
        return {"payload_bytes": str(bucket["payload_bytes"]), "messages": str(bucket["message_count"])}

    canonical_f3 = {
        "status": "reported",
        "remote_accepted": canonical_counter(frozen["outcomes"]["remote_transport_accepted"]),
        "local_delivered": canonical_counter(frozen["outcomes"]["local_delivery"]),
        "remote_failed_before_acceptance": {
            "payload_bytes": str(
                frozen["diagnostics"]["before_transport_acceptance_failed"]["attempted_payload_bytes"]
            ),
            "messages": str(frozen["diagnostics"]["before_transport_acceptance_failed"]["attempted_message_count"]),
        },
    }
    return {
        "schema_version": "prototype-0.3",
        "kind": "nvflare.resource_stats.f3_finalization_fixture",
        "provenance": "synthetic_contract_fixture",
        "primary_metrics": [
            {
                "name": "f3_payload_bytes_sent",
                "value": canonical_f3["remote_accepted"]["payload_bytes"],
                "unit": "bytes",
                "scope": "outbound_sender_hop",
                "status": "reported",
            },
            {
                "name": "f3_message_count_sent",
                "value": canonical_f3["remote_accepted"]["messages"],
                "unit": "messages",
                "scope": "outbound_sender_hop",
                "status": "reported",
            },
        ],
        "canonical_f3": canonical_f3,
        "included_traffic_classes": frozen["included_traffic_classes"],
        "post_cutoff_diagnostics_not_embedded_in_summary": post_cutoff["diagnostics"],
    }


def _accumulator_fixture(job_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    accumulator = ResourceTimeAccumulator()
    accumulator.observe(
        0,
        {
            "cpu": {"units": "16", "model": "AMD EPYC 9654", "architecture": "x86_64"},
            "memory": {"bytes": "137438953472"},
            "gpu": {"groups": []},
        },
    )
    accumulator.observe(
        300,
        {
            "cpu": {"units": "16", "model": "AMD EPYC 9654", "architecture": "x86_64"},
            "memory": {"bytes": "137438953472"},
            "gpu": {
                "groups": [
                    {
                        "kind": "full_gpu",
                        "count": "2",
                        "model": "NVIDIA A100-SXM4-80GB",
                        "memory_bytes": "85899345920",
                    }
                ]
            },
        },
    )
    handoff = accumulator.finish_measurements(
        900,
        workspace_filesystem={"status": "reported", "capacity_bytes": "1099511627776"},
        retained_content={"status": "reported", "bytes": "0"},
        child_f3={
            "status": "reported",
            "remote_accepted": {"payload_bytes": "0", "messages": "0"},
            "local_delivered": {"payload_bytes": "0", "messages": "0"},
            "remote_failed_before_acceptance": {"payload_bytes": "0", "messages": "0"},
        },
    )
    report = assemble_participant_summary(
        job_id=job_id,
        participant_name=_FIXTURE_PARTICIPANT_NAME,
        reported_at="2026-09-04T12:15:00Z",
        child_handoff=handoff,
        parent_f3={
            "status": "reported",
            "remote_accepted": {"payload_bytes": "0", "messages": "0"},
            "local_delivered": {"payload_bytes": "0", "messages": "0"},
            "remote_failed_before_acceptance": {"payload_bytes": "0", "messages": "0"},
        },
    )
    return (
        {
            "schema_version": "prototype-0.3",
            "kind": "nvflare.resource_stats.resource_time_accumulator_fixture",
            "provenance": "synthetic_contract_fixture",
            "observation_events": 2,
            "private_terminal_handoffs": 1,
            "persisted_terminal_reports": 1,
            "public_interval_records": 0,
            "terminal_handoff_file": "terminal_handoff.json",
            "participant_summary": report,
            "rule": "observe changes internally and persist or transmit only the terminal participant summary",
        },
        handoff,
    )


def _write_archive(path: Path, members: dict[str, bytes]) -> None:
    """Write a deterministic ZIP shaped like the existing WORKSPACE component."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_STORED) as archive:
        ordered = sorted(members.items(), key=lambda item: (item[0] == RESOURCE_SUMMARY_MEMBER, item[0]))
        for name, data in ordered:
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)


def _workspace_archive_fixture(
    root: Path,
    job_id: str,
    resource_summary_bytes: bytes,
    participant_summary_bytes_by_name: Mapping[str, bytes],
) -> dict[str, Any]:
    archive_members: dict[str, bytes] = {}
    participant_members: list[str] = []
    for participant_name, participant_bytes in sorted(participant_summary_bytes_by_name.items()):
        participant_relative_path = f"participants/{participant_name}.json"
        participant_member = f"resource_stats/{participant_relative_path}"
        participant_members.append(participant_member)
        archive_members[participant_member] = participant_bytes
    archive_members[RESOURCE_SUMMARY_MEMBER] = resource_summary_bytes
    archive_path = root / "server_job_store" / "jobs" / job_id / WORKSPACE_COMPONENT
    _write_archive(archive_path, archive_members)
    reader = WorkspaceResourceStatsReader(archive_path)
    summary_matches = reader.read_resource_summary_bytes() == resource_summary_bytes
    participants_match = all(
        reader.read_participant_summary_bytes(participant_name) == participant_bytes
        for participant_name, participant_bytes in sorted(participant_summary_bytes_by_name.items())
    )
    return {
        "schema_version": "prototype-0.3",
        "kind": "nvflare.resource_stats.workspace_archive_reader_fixture",
        "provenance": "synthetic_contract_fixture",
        "component": WORKSPACE_COMPONENT,
        "relative_path": archive_path.resolve().relative_to(root.resolve()).as_posix(),
        "summary_member": RESOURCE_SUMMARY_MEMBER,
        "participant_members": participant_members,
        "summary_matches_canonical": summary_matches,
        "participants_match": participants_match,
        "separate_query_component_created": False,
    }


def write_review_contract_fixtures(
    output_dir: Path,
    job_id: str,
    resource_summary_bytes: bytes,
    participant_summary_bytes_by_name: Mapping[str, bytes],
) -> dict[str, Any]:
    """Write review fixtures and return their path-only receipt index."""

    if not isinstance(resource_summary_bytes, bytes):
        raise TypeError("resource_summary_bytes must be bytes")
    if not isinstance(participant_summary_bytes_by_name, Mapping):
        raise TypeError("participant_summary_bytes_by_name must be a mapping")
    participant_summary_bytes_by_name = dict(participant_summary_bytes_by_name)
    for participant_name, participant_bytes in participant_summary_bytes_by_name.items():
        if not isinstance(participant_name, str):
            raise TypeError("participant summary names must be strings")
        if not isinstance(participant_bytes, bytes):
            raise TypeError("participant summary values must be bytes")
    root = Path(output_dir) / "review_contracts"
    root.mkdir(parents=True, exist_ok=True)
    accumulator_fixture, terminal_handoff = _accumulator_fixture(job_id)
    files = {
        "gpu_cuda_runtime_validated.json": _gpu_fixture(),
        "f3_finalization.json": _f3_fixture(),
        "resource_time_accumulator.json": accumulator_fixture,
        "terminal_handoff.json": terminal_handoff,
    }
    for name, contents in files.items():
        _write_json(root / name, contents)
    _write_json(
        root / "workspace_archive_reader.json",
        _workspace_archive_fixture(
            root,
            job_id,
            resource_summary_bytes,
            participant_summary_bytes_by_name,
        ),
    )
    entries = [f"review_contracts/{path.name}" for path in sorted(root.glob("*.json"))]
    return {
        "kind": "nvflare.resource_stats.review_contract_fixtures",
        "provenance": "synthetic_contract_fixture",
        "entry_count": len(entries),
        "entries": entries,
    }
