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

"""Generate the typed v1 goldens and coherent finalized-job review tree.

The executable contract derives every duration and total from lifecycle facts.
This generator then computes real file digests and renders the proposed CLI, so
the checked-in artifacts are mutually consistent rather than hand-written
mockups.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any

from contract_v1 import (
    KIND_ATTEMPT_FINAL,
    KIND_ATTEMPT_PARENT_EXIT,
    KIND_ATTEMPT_START,
    KIND_MANIFEST,
    KIND_PARTICIPANT_SUMMARY,
    KIND_RESOURCE_SUMMARY,
    derive_job_totals,
    derive_participant_totals,
    load_and_validate,
    validate_bundle,
)


SCHEMA_ROOT = Path(__file__).resolve().parent
GOLDEN_ROOT = SCHEMA_ROOT / "golden" / "v1"
DEFAULT_OUTPUT = GOLDEN_ROOT / "finalized_job"
JOB_ID = "job-20260909-001"
PARTICIPANT_KEY = "sha256-" + "a" * 64
PARTICIPANT_PATH = f"participants/{PARTICIPANT_KEY}.json"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _capacity(
    *,
    cpu_units: str = "1.5",
    storage_bytes: str = "1099511627776",
    gpu_groups: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    if gpu_groups is None:
        gpu_groups = [
            {
                "kind": "full_gpu",
                "count": "1",
                "model": "NVIDIA H100 80GB HBM3",
                "memory_bytes": "85899345920",
            }
        ]
    cpu = {
        "status": "reported",
        "visible_units": cpu_units,
        "model": "AMD EPYC 9654",
        "architecture": "x86_64",
        "evidence": {"affinity_count": "4", "cpuset_count": "4", "quota_units": cpu_units},
    }
    return {
        "cpu": cpu,
        "memory": {
            "status": "reported",
            "visible_bytes": "8589934592",
            "evidence": {"physical_bytes": "68719476736", "cgroup_limit_bytes": "8589934592"},
        },
        "storage": {"status": "reported", "capacity_bytes": storage_bytes},
        "gpu": {"status": "reported", "cuda_mask_present": True, "groups": gpu_groups},
    }


def _counter(payload_bytes: str = "0", messages: str = "0") -> dict[str, str]:
    return {"payload_bytes": payload_bytes, "messages": messages}


def _f3(*, nonzero: bool) -> dict[str, Any]:
    if not nonzero:
        return {
            "status": "reported",
            "cutoff_sequence": "0",
            "remote_accepted": _counter(),
            "local_delivered": _counter(),
            "remote_failed_before_acceptance": _counter(),
            "late_after_cutoff": _counter(),
            "summary_excluded": _counter(),
        }
    return {
        "status": "reported",
        "cutoff_sequence": "5",
        "remote_accepted": _counter("5632", "2"),
        "local_delivered": _counter("256", "1"),
        "remote_failed_before_acceptance": _counter(),
        "late_after_cutoff": _counter("512", "1"),
        "summary_excluded": _counter("1024", "1"),
    }


def _attempt(
    *,
    attempt_id: str,
    environment_key: str,
    start_at: str,
    final_at: str,
    exit_at: str,
    capacity: dict[str, Any],
    retained: bool,
    nonzero_f3: bool,
) -> dict[str, Any]:
    entries = []
    if retained:
        entries.append({"relative_path": "result/model.pt", "size_bytes": "18874368", "sha256": "d" * 64})
    return {
        "attempt_id": attempt_id,
        "environment_key": environment_key,
        "start": {"observed_at": start_at, "collection_state": "enabled", "capacity": deepcopy(capacity)},
        "final": {
            "observed_at": final_at,
            "capacity": deepcopy(capacity),
            "retained_content": {"status": "reported", "entries": entries},
            "f3": _f3(nonzero=nonzero_f3),
        },
        "exit": {"observed_at": exit_at, "outcome": "finished_ok", "return_code": 0},
    }


def _main_participant() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "kind": KIND_PARTICIPANT_SUMMARY,
        "job_id": JOB_ID,
        "participant_key": PARTICIPANT_KEY,
        "attempts": [
            _attempt(
                attempt_id="1" * 32,
                environment_key="sha256-" + "b" * 64,
                start_at="2026-09-09T14:00:00Z",
                final_at="2026-09-09T14:05:42.5Z",
                exit_at="2026-09-09T14:05:42.6Z",
                capacity=_capacity(),
                retained=True,
                nonzero_f3=True,
            )
        ],
    }


def _large_participant() -> dict[str, Any]:
    capacity = _capacity(cpu_units="1", storage_bytes="10000000000001", gpu_groups=[])
    capacity["cpu"] = {
        "status": "reported",
        "visible_units": "1",
        "architecture": "x86_64",
        "evidence": {"online_count": "1"},
    }
    capacity["memory"] = {
        "status": "reported",
        "visible_bytes": "1073741824",
        "evidence": {"physical_bytes": "1073741824"},
    }
    return {
        "schema_version": "1.0",
        "kind": KIND_PARTICIPANT_SUMMARY,
        "job_id": "job-large-exactness",
        "participant_key": "sha256-" + "f" * 64,
        "attempts": [
            _attempt(
                attempt_id="9" * 32,
                environment_key="sha256-" + "9" * 64,
                start_at="2026-09-09T00:00:00Z",
                final_at="2026-09-09T00:15:01Z",
                exit_at="2026-09-09T00:15:01.1Z",
                capacity=capacity,
                retained=False,
                nonzero_f3=False,
            )
        ],
    }


def _attempt_start(participant_id: str, participant: dict[str, Any]) -> dict[str, Any]:
    attempt = participant["attempts"][0]
    start = attempt["start"]
    return {
        "schema_version": "1.0",
        "kind": KIND_ATTEMPT_START,
        "job_id": participant["job_id"],
        "participant_id": participant_id,
        "attempt_id": attempt["attempt_id"],
        "environment_key": attempt["environment_key"],
        **deepcopy(start),
    }


def _attempt_final(participant_id: str, participant: dict[str, Any]) -> dict[str, Any]:
    attempt = participant["attempts"][0]
    return {
        "schema_version": "1.0",
        "kind": KIND_ATTEMPT_FINAL,
        "job_id": participant["job_id"],
        "participant_id": participant_id,
        "attempt_id": attempt["attempt_id"],
        "environment_key": attempt["environment_key"],
        **deepcopy(attempt["final"]),
    }


def _resource_summary(
    participant: dict[str, Any],
    participant_bytes: bytes,
    *,
    participant_id: str,
    received: str,
    cutoff: str,
    finalized: str,
    missing_server: bool,
) -> dict[str, Any]:
    observation_seconds, totals = derive_participant_totals(participant)
    roster = [
        {
            "participant_id": participant_id,
            "participant_key": participant["participant_key"],
            "role": "client",
            "status": "accepted",
            "received_at": received,
            "summary_sha256": _digest(participant_bytes),
            "observation_seconds": observation_seconds,
            "totals": totals,
        }
    ]
    if missing_server:
        roster.append(
            {
                "participant_id": "server",
                "participant_key": "sha256-" + "c" * 64,
                "role": "server",
                "status": "missing",
            }
        )
    roster.sort(key=lambda item: (item["role"], item["participant_id"], item["participant_key"]))
    return {
        "schema_version": "1.0",
        "kind": KIND_RESOURCE_SUMMARY,
        "job_id": participant["job_id"],
        "report_cutoff_at": cutoff,
        "finalized_at": finalized,
        "roster": roster,
        "totals": derive_job_totals(roster),
    }


def _manifest(job_id: str, summary_bytes: bytes, participant_bytes: bytes, participant_key: str) -> dict[str, Any]:
    entries = [
        {"relative_path": f"participants/{participant_key}.json", "sha256": _digest(participant_bytes)},
        {"relative_path": "resource_summary.json", "sha256": _digest(summary_bytes)},
    ]
    entries.sort(key=lambda item: item["relative_path"])
    return {"schema_version": "1.0", "kind": KIND_MANIFEST, "job_id": job_id, "entries": entries}


def _decimal_sum(groups: list[dict[str, Any]], field: str) -> Decimal:
    return sum((Decimal(group[field]) for group in groups), Decimal(0))


def _hours(value: Decimal | None, divisor: Decimal = Decimal(3600)) -> str:
    return "N/A" if value is None else f"{value / divisor:.4f}"


def _duration(value: str) -> str:
    seconds = Decimal(value)
    minutes = int(seconds // Decimal(60))
    remainder = seconds - Decimal(minutes * 60)
    text = format(remainder, "f").rstrip("0").rstrip(".")
    return f"{minutes}m{text or '0'}s"


def _gpu_time(totals: dict[str, Any], kind: str) -> Decimal | None:
    resource = totals["gpu"]
    if resource["status"] == "unavailable":
        return None
    return sum(
        (Decimal(group["instance_seconds"]) for group in resource["groups"] if group["kind"] == kind),
        Decimal(0),
    )


def _scalar(totals: dict[str, Any], resource: str, field: str) -> Decimal | None:
    item = totals[resource]
    return None if item["status"] == "unavailable" else Decimal(item[field])


def _show_mig(summary: dict[str, Any]) -> bool:
    return any(
        member["status"] == "accepted" and (_gpu_time(member["totals"], "mig_compute_instance") or Decimal(0)) > 0
        for member in summary["roster"]
    )


def _human_cli(summary: dict[str, Any]) -> str:
    accepted = sum(member["status"] == "accepted" for member in summary["roster"])
    coverage = "COMPLETE" if accepted == len(summary["roster"]) else "PARTIAL"
    show_mig = _show_mig(summary)
    header = "SITE     ROLE    STATUS    OBSERVED   FULL GPU h"
    if show_mig:
        header += "  MIG CI h"
    header += "  CPU h   MEM GiB h  STORAGE GiB h  RETAINED  F3 BYTES"
    lines = [
        "Runtime-visible capacity proxies; not allocations, reservations, guarantees, or billable usage.",
        f"Job {summary['job_id']} | coverage: {coverage} ({accepted} accepted / {len(summary['roster'])} expected)",
        "",
        header,
    ]
    for member in summary["roster"]:
        if member["status"] != "accepted":
            mig = f"{'N/A':>8} " if show_mig else ""
            lines.append(
                f"{member['participant_id']:<8} {member['role']:<7} {member['status']:<9} {'—':>10} "
                f"{'N/A':>12} {mig}{'N/A':>7} {'N/A':>11} {'N/A':>14} {'N/A':>9} {'N/A':>9}"
            )
            continue
        totals = member["totals"]
        cpu = (
            None if totals["cpu"]["status"] == "unavailable" else _decimal_sum(totals["cpu"]["groups"], "unit_seconds")
        )
        retained = _scalar(totals, "retained_content", "bytes")
        f3 = (
            None
            if totals["f3"]["status"] == "unavailable"
            else Decimal(totals["f3"]["remote_accepted"]["payload_bytes"])
        )
        mig = f"{_hours(_gpu_time(totals, 'mig_compute_instance')):>8} " if show_mig else ""
        lines.append(
            f"{member['participant_id']:<8} {member['role']:<7} {member['status']:<9} "
            f"{_duration(member['observation_seconds']):>10} {_hours(_gpu_time(totals, 'full_gpu')):>12} {mig}"
            f"{_hours(cpu):>7} {_hours(_scalar(totals, 'memory', 'byte_seconds'), Decimal(2**30 * 3600)):>11} "
            f"{_hours(_scalar(totals, 'storage', 'byte_seconds'), Decimal(2**30 * 3600)):>14} "
            f"{_hours(retained, Decimal(2**20)):>5} MiB {_hours(f3, Decimal(1024)):>5} KiB"
        )
    lines.extend(
        [
            "",
            "Notices:",
            "  Participant-visible proxies may overlap; this is not physical capacity.",
            "  Totals cover accepted reports only; roster gaps make them partial.",
            "  Participant observations are self-reported; accepted bytes are preserved by the parent.",
            "",
        ]
    )
    return "\n".join(lines)


def _hardware_details(summary: dict[str, Any], participant_id: str) -> str:
    member = next(entry for entry in summary["roster"] if entry["participant_id"] == participant_id)
    lines = [
        f"Hardware detail for {participant_id}",
        "Model metadata is optional and may be suppressed by site policy.",
        "",
    ]
    for group in member["totals"]["cpu"].get("groups", []):
        model = group.get("model", "model not reported")
        architecture = f" ({group['architecture']})" if "architecture" in group else ""
        lines.append(f"CPU: {model}{architecture}; {_hours(Decimal(group['unit_seconds']))} CPU h")
    for group in member["totals"]["gpu"].get("groups", []):
        label = "full GPU" if group["kind"] == "full_gpu" else "MIG compute instance"
        model = group.get("model", "model not reported")
        memory = ""
        if "memory_bytes" in group:
            memory = f", {Decimal(group['memory_bytes']) / Decimal(2**30):.0f} GiB per instance"
        lines.append(f"GPU ({label}): {model}{memory}; {_hours(Decimal(group['instance_seconds']))} instance h")
    lines.append("")
    return "\n".join(lines)


def build(output_root: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    participant = _main_participant()
    participant_bytes = _json_bytes(participant)
    summary = _resource_summary(
        participant,
        participant_bytes,
        participant_id="site-1",
        received="2026-09-09T14:05:43Z",
        cutoff="2026-09-09T14:06:00Z",
        finalized="2026-09-09T14:06:00.1Z",
        missing_server=True,
    )
    summary_bytes = _json_bytes(summary)
    manifest = _manifest(JOB_ID, summary_bytes, participant_bytes, PARTICIPANT_KEY)
    manifest_bytes = _json_bytes(manifest)

    main_start = _attempt_start("site-1", participant)
    main_final = _attempt_final("site-1", participant)
    zero_gpu = deepcopy(main_start)
    zero_gpu.update(
        participant_id="site-zero",
        attempt_id="2" * 32,
        environment_key="sha256-" + "2" * 64,
        observed_at="2026-09-09T15:00:00Z",
    )
    zero_gpu["capacity"]["gpu"]["groups"] = []
    cuda_unavailable = deepcopy(zero_gpu)
    cuda_unavailable.update(
        participant_id="site-mask-only",
        attempt_id="3" * 32,
        environment_key="sha256-" + "3" * 64,
        observed_at="2026-09-09T15:01:00Z",
    )
    cuda_unavailable["capacity"]["gpu"] = {
        "status": "unavailable",
        "cuda_mask_present": True,
        "issues": ["dependency_missing"],
    }
    disabled = {
        "schema_version": "1.0",
        "kind": KIND_ATTEMPT_START,
        "job_id": JOB_ID,
        "participant_id": "site-disabled",
        "attempt_id": "4" * 32,
        "environment_key": "sha256-" + "4" * 64,
        "observed_at": "2026-09-09T15:02:00Z",
        "collection_state": "disabled",
    }
    crash = {
        "schema_version": "1.0",
        "kind": KIND_ATTEMPT_PARENT_EXIT,
        "job_id": JOB_ID,
        "participant_id": "site-1",
        "attempt_id": "5" * 32,
        "environment_key": "sha256-" + "5" * 64,
        "observed_at": "2026-09-09T14:10:00Z",
        "outcome": "terminated",
        "return_code": -9,
    }

    large_participant = _large_participant()
    large_participant_bytes = _json_bytes(large_participant)
    large_summary = _resource_summary(
        large_participant,
        large_participant_bytes,
        participant_id="site-large",
        received="2026-09-09T00:15:01.2Z",
        cutoff="2026-09-09T00:15:02Z",
        finalized="2026-09-09T00:15:02.1Z",
        missing_server=False,
    )
    records = {
        "attempt_start.json": main_start,
        "attempt_start_zero_gpu.json": zero_gpu,
        "attempt_start_cuda_unavailable.json": cuda_unavailable,
        "attempt_start_disabled.json": disabled,
        "attempt_final.json": main_final,
        "attempt_final_large_value.json": _attempt_final("site-large", large_participant),
        "parent_exit_crash.json": crash,
        "participant_summary.json": participant,
        "participant_summary_large_value.json": large_participant,
        "resource_summary.json": summary,
        "resource_summary_large_value.json": large_summary,
        "manifest.json": manifest,
    }
    encoded = {name: _json_bytes(record) for name, record in records.items()}
    for data in encoded.values():
        load_and_validate(data)
    validate_bundle(
        summary,
        {PARTICIPANT_KEY: participant},
        manifest,
        {"resource_summary.json": summary_bytes, PARTICIPANT_PATH: participant_bytes},
    )
    for name, data in encoded.items():
        _write(GOLDEN_ROOT / name, data)

    resource_root = output_root / "server_run" / "resource_stats"
    _write(resource_root / "resource_summary.json", summary_bytes)
    _write(resource_root / PARTICIPANT_PATH, participant_bytes)
    _write(resource_root / "manifest.json", manifest_bytes)
    query_copy = output_root / "job_store" / "jobs" / JOB_ID / "RESOURCE_STATS"
    _write(query_copy, summary_bytes)

    cli_json = {
        "schema_version": "1",
        "status": "ok",
        "exit_code": 0,
        "data": {"selection": {"job_id": JOB_ID, "site": "all"}, "summary": summary},
    }
    cli_json_bytes = _json_bytes(cli_json)
    cli_text_bytes = _human_cli(summary).encode("utf-8")
    detail_bytes = _hardware_details(summary, "site-1").encode("utf-8")
    _write(output_root / "cli" / "resources-all.json", cli_json_bytes)
    _write(output_root / "cli" / "resources-all.txt", cli_text_bytes)
    _write(output_root / "cli" / "resources-site-1-details.txt", detail_bytes)

    receipt = {
        "generator": Path(__file__).name,
        "schema_version": "1.0",
        "job_id": JOB_ID,
        "participant_summary_sha256": _digest(participant_bytes),
        "resource_summary_sha256": _digest(summary_bytes),
        "manifest_sha256": _digest(manifest_bytes),
        "query_copy_matches_resource_summary": query_copy.read_bytes() == summary_bytes,
        "derived_examples": {
            "observation_seconds": summary["roster"][0]["observation_seconds"],
            "cpu_unit_seconds": summary["roster"][0]["totals"]["cpu"]["groups"][0]["unit_seconds"],
            "large_storage_byte_seconds": large_summary["totals"]["storage"]["byte_seconds"],
        },
    }
    _write(output_root / "generation_receipt.json", _json_bytes(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))


if __name__ == "__main__":
    main()
