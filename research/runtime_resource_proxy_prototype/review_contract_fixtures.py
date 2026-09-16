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
actually observe.  These fixtures exercise proposed runtime boundaries that
cannot be honestly installed in this standalone process yet: a CUDA runtime
adapter, an NVFlare-only F3 sender hook, reporter selection, and archived
workspace access.  Every file emitted here declares itself a synthetic contract
fixture; none is a local resource observation or production evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from f3_finalization import F3FinalizationCounter, JobTrafficClass, JobTrafficEvent
from prototype_contract import (
    RESOURCE_MANIFEST_MEMBER,
    RESOURCE_SUMMARY_MEMBER,
    ReporterLeaseConflict,
    ReporterLeaseRegistry,
    WORKSPACE_COMPONENT,
    WorkspaceAttemptStore,
    WorkspaceResourceStatsReader,
)
from runtime_probe import probe_gpu_records


_FIXTURE_ATTEMPT_ID = "1" * 32
_TERMINATED_FIXTURE_ATTEMPT_ID = "2" * 32
_FIXTURE_PARTICIPANT_KEY = "sha256-" + "a" * 64


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _write_json(path: Path, value: Any) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _json_bytes(value)
    path.write_bytes(data)
    return data


def _relative_record(path: Path, root: Path) -> dict[str, str]:
    data = path.read_bytes()
    return {
        "relative_path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


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
    def canonical_counter(bucket: dict[str, int]) -> dict[str, int]:
        return {"payload_bytes": bucket["payload_bytes"], "messages": bucket["message_count"]}

    canonical_f3 = {
        "status": "reported",
        "remote_accepted": canonical_counter(frozen["outcomes"]["remote_transport_accepted"]),
        "local_delivered": canonical_counter(frozen["outcomes"]["local_delivery"]),
        "remote_failed_before_acceptance": {
            "payload_bytes": frozen["diagnostics"]["before_transport_acceptance_failed"]["attempted_payload_bytes"],
            "messages": frozen["diagnostics"]["before_transport_acceptance_failed"]["attempted_message_count"],
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


def _lease_fixture(job_id: str) -> dict[str, Any]:
    registry = ReporterLeaseRegistry()
    owner = registry.acquire(job_id, "fixture-environment-1", "rank-0")
    duplicate_suppressed = False
    try:
        registry.acquire(job_id, "fixture-environment-1", "rank-1")
    except ReporterLeaseConflict:
        duplicate_suppressed = True
    other_job = registry.acquire(f"{job_id}-other", "fixture-environment-1", "rank-0")
    return {
        "schema_version": "prototype-0.3",
        "kind": "nvflare.resource_stats.reporter_lease_fixture",
        "provenance": "synthetic_contract_fixture",
        "owner": owner.as_record(),
        "same_job_same_environment_second_rank_suppressed": duplicate_suppressed,
        "different_job_same_environment": other_job.as_record(),
    }


def _fragment_fixture(root: Path, job_id: str) -> dict[str, Any]:
    workspace_root = root / "job_workspace"
    store = WorkspaceAttemptStore(workspace_root)
    start = store.persist_observation(
        job_id,
        _FIXTURE_ATTEMPT_ID,
        "start.json",
        {
            "schema_version": "prototype-0.3",
            "kind": "nvflare.resource_stats.attempt_start",
            "job_id": job_id,
            "attempt_id": _FIXTURE_ATTEMPT_ID,
            "snapshot": {
                "provenance": "synthetic_contract_fixture",
                "resource_types": ["cpu", "memory", "gpu"],
            },
        },
    )
    final = store.persist_observation(
        job_id,
        _FIXTURE_ATTEMPT_ID,
        "final.json",
        {
            "schema_version": "prototype-0.3",
            "kind": "nvflare.resource_stats.attempt_final",
            "job_id": job_id,
            "attempt_id": _FIXTURE_ATTEMPT_ID,
            "finalization": {"state": "finished_ok"},
        },
    )
    terminated = store.record_attempt_end_without_final(
        job_id,
        _TERMINATED_FIXTURE_ATTEMPT_ID,
        "2026-09-04T11:59:00Z",
        "2026-09-04T12:00:00Z",
        "terminated",
    )
    records = [_relative_record(receipt.path, root) for receipt in (start, final, terminated)]
    return {
        "schema_version": "prototype-0.3",
        "kind": "nvflare.resource_stats.workspace_fragment_fixture",
        "provenance": "synthetic_contract_fixture",
        "workspace_root": "job_workspace",
        "records": records,
        "trust_note": (
            "These files are self-reported and best-effort until the server receives the final site report. "
            "The prototype requires no extra mount, service, privilege, or configuration."
        ),
    }


def _write_archive(path: Path, members: dict[str, bytes]) -> None:
    """Write a deterministic ZIP shaped like the existing WORKSPACE component."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_STORED) as archive:
        for name, data in sorted(members.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)


def _workspace_archive_fixture(root: Path, job_id: str, resource_summary_bytes: bytes) -> dict[str, Any]:
    participant_relative_path = f"participants/{_FIXTURE_PARTICIPANT_KEY}.json"
    participant_member = f"resource_stats/{participant_relative_path}"
    participant_bytes = _json_bytes(
        {
            "schema_version": "prototype-0.3",
            "kind": "nvflare.resource_stats.participant_summary",
            "job_id": job_id,
            "participant_key": _FIXTURE_PARTICIPANT_KEY,
            "provenance": "synthetic_contract_fixture",
        }
    )
    manifest_bytes = _json_bytes(
        {
            "schema_version": "prototype-0.3",
            "kind": "nvflare.resource_stats.manifest",
            "entries": [
                {
                    "relative_path": "resource_summary.json",
                    "byte_count": len(resource_summary_bytes),
                    "sha256": hashlib.sha256(resource_summary_bytes).hexdigest(),
                },
                {
                    "relative_path": participant_relative_path,
                    "byte_count": len(participant_bytes),
                    "sha256": hashlib.sha256(participant_bytes).hexdigest(),
                },
            ],
        }
    )
    archive_path = root / "server_job_store" / "jobs" / job_id / WORKSPACE_COMPONENT
    _write_archive(
        archive_path,
        {
            RESOURCE_SUMMARY_MEMBER: resource_summary_bytes,
            RESOURCE_MANIFEST_MEMBER: manifest_bytes,
            participant_member: participant_bytes,
        },
    )
    reader = WorkspaceResourceStatsReader(archive_path)
    return {
        "schema_version": "prototype-0.3",
        "kind": "nvflare.resource_stats.workspace_archive_reader_fixture",
        "provenance": "synthetic_contract_fixture",
        "component": WORKSPACE_COMPONENT,
        "relative_path": archive_path.resolve().relative_to(root.resolve()).as_posix(),
        "summary_member": RESOURCE_SUMMARY_MEMBER,
        "manifest_member": RESOURCE_MANIFEST_MEMBER,
        "participant_member": participant_member,
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "summary_matches_canonical": reader.read_resource_summary_bytes() == resource_summary_bytes,
        "manifest_readable": reader.read_manifest_bytes() == manifest_bytes,
        "participant_matches": reader.read_participant_summary_bytes(_FIXTURE_PARTICIPANT_KEY) == participant_bytes,
        "separate_query_component_created": False,
    }


def write_review_contract_fixtures(output_dir: Path, job_id: str, resource_summary_bytes: bytes) -> dict[str, Any]:
    """Write review fixtures and return a path-free manifest for the generator receipt."""

    if not isinstance(resource_summary_bytes, bytes):
        raise TypeError("resource_summary_bytes must be bytes")
    root = Path(output_dir) / "review_contracts"
    root.mkdir(parents=True, exist_ok=True)
    files = {
        "gpu_cuda_runtime_validated.json": _gpu_fixture(),
        "f3_finalization.json": _f3_fixture(),
        "reporter_lease.json": _lease_fixture(job_id),
    }
    for name, contents in files.items():
        _write_json(root / name, contents)
    _write_json(root / "workspace_fragments.json", _fragment_fixture(root, job_id))
    _write_json(
        root / "workspace_archive_reader.json",
        _workspace_archive_fixture(root, job_id, resource_summary_bytes),
    )
    manifest_entries = [_relative_record(path, root) for path in sorted(root.glob("*.json"))]
    manifest = {
        "schema_version": "prototype-0.3",
        "kind": "nvflare.resource_stats.review_contract_fixture_manifest",
        "provenance": "synthetic_contract_fixture",
        "entries": manifest_entries,
    }
    _write_json(root / "manifest.json", manifest)
    return {
        "kind": manifest["kind"],
        "provenance": manifest["provenance"],
        "entry_count": len(manifest_entries),
        "manifest": "review_contracts/manifest.json",
    }
