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

"""Write deterministic, review-only artifacts for the hardened prototype contracts.

The normal generator deliberately captures only what the local process can
actually observe.  These fixtures exercise proposed runtime boundaries that
cannot be honestly installed in this standalone process yet: a CUDA runtime
adapter, a trusted F3 sender hook, a parent/child handoff, and platform-owned
launcher preparation.  Every file emitted here declares itself a synthetic
contract fixture; none is a local resource observation or production evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from f3_finalization import F3FinalizationCounter, JobTrafficClass, JobTrafficEvent
from prototype_contract import (
    FixedResourceStatsStore,
    ParentOwnedAttemptStore,
    ReporterLeaseConflict,
    ReporterLeaseRegistry,
    RESOURCE_STATS_COMPONENT,
    build_sanitized_launch_plan,
)
from runtime_probe import probe_gpu_records


_FIXTURE_ATTEMPT_ID = "1" * 32
_CRASH_FIXTURE_ATTEMPT_ID = "2" * 32


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
    counter.summary_publisher().send_remote(JobTrafficEvent(JobTrafficClass.JOB_APPLICATION, 1024), lambda: None)
    counter.freeze()
    counter.send_remote(JobTrafficEvent(JobTrafficClass.TASK_RESULT, 512), lambda: None)
    snapshot = counter.snapshot()
    return {
        "schema_version": "prototype-0.3",
        "kind": "nvflare.resource_stats.f3_finalization_fixture",
        "provenance": "synthetic_contract_fixture",
        "primary_metrics": [
            {
                "name": "f3_payload_bytes_sent",
                "value": snapshot["outcomes"]["remote_transport_accepted"]["payload_bytes"],
                "unit": "bytes",
                "scope": "outbound_sender_hop",
                "status": "reported",
            },
            {
                "name": "f3_message_count_sent",
                "value": snapshot["outcomes"]["remote_transport_accepted"]["message_count"],
                "unit": "messages",
                "scope": "outbound_sender_hop",
                "status": "reported",
            },
        ],
        "counter": snapshot,
    }


def _bootstrap_fixture() -> dict[str, Any]:
    plans = []
    for launcher in ("process", "docker", "k8s", "slurm"):
        plan = build_sanitized_launch_plan(
            launcher=launcher,
            python_executable="/opt/nvflare/python",
            module="nvflare.private.fed.app.resource_bootstrap",
            platform_args=("--workspace", "/workspace"),
            environment={"PYTHONPATH": "/job/custom:/site/custom", "NVFLARE_PLATFORM": "fixture"},
            attempt_id=_FIXTURE_ATTEMPT_ID,
            custom_import_paths=("/job/custom", "/site/custom"),
        )
        plans.append(
            {
                "launcher": plan.launcher,
                "attempt_id": plan.attempt_id,
                "argv": list(plan.argv),
                "pre_python_environment": plan.pre_python_environment,
                "post_snapshot_custom_import_paths": list(plan.post_snapshot_custom_import_paths),
                "bootstrap_steps": list(plan.bootstrap_steps),
            }
        )
    return {
        "schema_version": "prototype-0.3",
        "kind": "nvflare.resource_stats.trusted_bootstrap_fixture",
        "provenance": "synthetic_contract_fixture",
        "plans": plans,
        "production_gap": (
            "Every real launcher must still invoke the platform bootstrap and preserve this exact argument."
        ),
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
    job_writable_root = root / "simulated_job_writable"
    parent_owned_root = root / "parent_owned_fragments"
    store = ParentOwnedAttemptStore(parent_owned_root, job_writable_root)
    start = store.persist_child_fragment(
        job_id,
        _FIXTURE_ATTEMPT_ID,
        "start.json",
        {
            "schema_version": "prototype-0.3",
            "kind": "nvflare.resource_stats.attempt_start",
            "job_id": job_id,
            "attempt_id": _FIXTURE_ATTEMPT_ID,
            "snapshot": {"provenance": "synthetic_contract_fixture", "metric_count": 4},
        },
    )
    final = store.persist_child_fragment(
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
    crash = store.record_crash_parent_exit(
        job_id,
        _CRASH_FIXTURE_ATTEMPT_ID,
        "2026-09-04T12:00:00Z",
        137,
    )
    records = [_relative_record(receipt.path, root) for receipt in (start, final, crash)]
    return {
        "schema_version": "prototype-0.3",
        "kind": "nvflare.resource_stats.parent_owned_fragment_fixture",
        "provenance": "synthetic_contract_fixture",
        "job_writable_root": "simulated_job_writable",
        "parent_owned_root": "parent_owned_fragments",
        "records": records,
        "kubernetes_note": (
            "A production Kubernetes parent-owned root must be durable outside a child-only emptyDir; "
            "this local fixture cannot prove that deployment property."
        ),
    }


def _fixed_component_fixture(root: Path, job_id: str, resource_summary_bytes: bytes) -> dict[str, Any]:
    store = FixedResourceStatsStore(root / "parent_owned_job_store")
    receipt = store.save_resource_stats(job_id, resource_summary_bytes)
    return {
        "schema_version": "prototype-0.3",
        "kind": "nvflare.resource_stats.fixed_component_fixture",
        "provenance": "synthetic_contract_fixture",
        "component": RESOURCE_STATS_COMPONENT,
        "exact_component_allowed": FixedResourceStatsStore.is_allowed_component(RESOURCE_STATS_COMPONENT),
        "prefix_variant_allowed": FixedResourceStatsStore.is_allowed_component(f"{RESOURCE_STATS_COMPONENT}_site-1"),
        "relative_path": receipt.path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": receipt.sha256,
        "byte_identical_to_canonical_summary": store.get_resource_stats(job_id) == resource_summary_bytes,
    }


def write_review_contract_fixtures(output_dir: Path, job_id: str, resource_summary_bytes: bytes) -> dict[str, Any]:
    """Write review fixtures and return a path-free manifest for the generator receipt."""

    if not isinstance(resource_summary_bytes, bytes):
        raise TypeError("resource_summary_bytes must be bytes")
    root = Path(output_dir) / "review_contracts"
    root.mkdir(parents=True, exist_ok=True)
    files = {
        "trusted_bootstrap_plans.json": _bootstrap_fixture(),
        "gpu_cuda_runtime_validated.json": _gpu_fixture(),
        "f3_finalization.json": _f3_fixture(),
        "reporter_lease.json": _lease_fixture(job_id),
    }
    for name, contents in files.items():
        _write_json(root / name, contents)
    _write_json(root / "parent_owned_fragments.json", _fragment_fixture(root, job_id))
    _write_json(
        root / "fixed_resource_stats_component.json",
        _fixed_component_fixture(root, job_id, resource_summary_bytes),
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
