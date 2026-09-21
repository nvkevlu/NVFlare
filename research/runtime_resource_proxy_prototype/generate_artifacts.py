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

"""Capture real local observations and emit the proposed terminal artifacts.

This remains a research prototype, not an NVFlare integration. It uses the
same public shape as schema v1: one participant summary, one job summary, and
one transient study response. Resource observations remain internal to the
accumulator and are never written as public start or final fragments.
"""

from __future__ import annotations

import argparse
import datetime
import json
import time
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from prototype_contract import ResourceTimeAccumulator, assemble_participant_summary
from review_contract_fixtures import write_review_contract_fixtures
from runtime_probe import probe_cpu, probe_gpu_records, probe_memory, probe_storage

from nvflare.tool.job.job_resources import render_job_resources, render_study_resources

PARTICIPANT_KIND = "nvflare.resource_stats.participant_summary"
RESOURCE_SUMMARY_KIND = "nvflare.resource_stats.resource_summary"
STUDY_SUMMARY_KIND = "nvflare.resource_stats.study_summary"


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _probe_has_usable_value(metric: dict[str, Any]) -> bool:
    return metric.get("value") is not None and metric.get("status") in {"reported", "partial"}


def _probe_is_complete(metric: dict[str, Any]) -> bool:
    return metric.get("status") == "reported" and metric.get("coverage") == "complete"


def _capacity_from_real_probes() -> tuple[dict[str, Any], dict[str, Any]]:
    cpu_metric = probe_cpu()
    memory_metric = probe_memory()
    gpu_metrics = probe_gpu_records()

    capacity: dict[str, Any] = {}
    if _probe_has_usable_value(cpu_metric):
        cpu = {"units": str(cpu_metric["value"])}
        dimensions = cpu_metric.get("dimensions", {})
        if dimensions.get("model"):
            cpu["model"] = dimensions["model"]
        if dimensions.get("architecture"):
            cpu["architecture"] = dimensions["architecture"]
        capacity["cpu"] = cpu
    if _probe_has_usable_value(memory_metric):
        capacity["memory"] = {"bytes": str(memory_metric["value"])}

    if gpu_metrics and all(_probe_has_usable_value(metric) for metric in gpu_metrics):
        groups = []
        for metric in gpu_metrics:
            value = Decimal(str(metric["value"]))
            if value == 0:
                continue
            dimensions = metric.get("dimensions", {})
            group = {
                "kind": dimensions["device_kind"],
                "count": str(metric["value"]),
            }
            for key in ("model", "memory_bytes", "mig_profile"):
                if dimensions.get(key) is not None:
                    group[key] = str(dimensions[key])
            groups.append(group)
        capacity["gpu"] = {"groups": groups}

    evidence = {
        "cpu_probe": cpu_metric,
        "memory_probe": memory_metric,
        "gpu_probes": gpu_metrics,
    }
    return capacity, evidence


def _compute_probe_coverage_complete(evidence: dict[str, Any]) -> bool:
    gpu_metrics = evidence["gpu_probes"]
    return (
        _probe_is_complete(evidence["cpu_probe"])
        and _probe_is_complete(evidence["memory_probe"])
        and bool(gpu_metrics)
        and all(_probe_is_complete(metric) for metric in gpu_metrics)
    )


def _zero_counter() -> dict[str, str]:
    return {"payload_bytes": "0", "messages": "0"}


def _finish_local_report(
    job_id: str,
    participant_name: str,
    workspace: Path,
    observation_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if observation_seconds < 0:
        raise ValueError("observation_seconds must be non-negative")
    capacity, evidence = _capacity_from_real_probes()
    accumulator = ResourceTimeAccumulator()
    start = Decimal(time.monotonic_ns()) / Decimal(1_000_000_000)
    if capacity:
        accumulator.observe(start, capacity)
    else:
        accumulator.mark_gap(start)
    if observation_seconds:
        time.sleep(observation_seconds)
    finished = Decimal(time.monotonic_ns()) / Decimal(1_000_000_000)
    storage_metric = probe_storage(workspace)
    evidence["workspace_filesystem_probe"] = storage_metric
    if not _probe_has_usable_value(storage_metric) or not _probe_is_complete(storage_metric):
        workspace_filesystem = {
            "status": "unavailable",
            "issues": ["observation_incomplete"],
        }
    else:
        workspace_filesystem = {
            "status": "reported",
            "capacity_bytes": str(storage_metric["value"]),
        }
    handoff = accumulator.finish_measurements(
        finished,
        workspace_filesystem=workspace_filesystem,
        retained_content={"status": "unavailable", "issues": ["not_bound"]},
        child_f3={
            "status": "unavailable",
            "issues": ["observation_incomplete"],
        },
    )
    resource_time = handoff["resource_time"]
    if resource_time["status"] == "reported" and not _compute_probe_coverage_complete(evidence):
        # Keep useful numeric totals from partial probes, but do not promote
        # their coverage to a fully reported terminal measurement.
        resource_time["status"] = "partial"
        resource_time["issues"] = ["observation_incomplete"]
    report = assemble_participant_summary(
        job_id=job_id,
        participant_name=participant_name,
        reported_at=_utc_now(),
        child_handoff=handoff,
        parent_f3={
            "status": "unavailable",
            "issues": ["observation_incomplete"],
        },
    )
    return report, evidence, handoff


def _accepted_entry(
    participant_name: str,
    role: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    return {
        "participant_name": participant_name,
        "role": role,
        "status": "accepted",
        "received_at": report["reported_at"],
        "resource_time": deepcopy(report["resource_time"]),
        "retained_content": deepcopy(report["retained_content"]),
        "f3": deepcopy(report["f3"]),
    }


def _resource_summary(
    job_id: str,
    accepted_entry: dict[str, Any],
    finalized_at: str,
) -> dict[str, Any]:
    retained = accepted_entry["retained_content"]
    retained_total = (
        {"status": retained["status"], "bytes": retained["bytes"]}
        if retained["status"] in {"reported", "partial"}
        else {"status": "unavailable"}
    )
    f3 = accepted_entry["f3"]
    f3_total = (
        {
            "status": f3["status"],
            "remote_accepted": deepcopy(f3["remote_accepted"]),
        }
        if f3["status"] in {"reported", "partial"}
        else {"status": "unavailable"}
    )
    return {
        "schema_version": "1.0",
        "kind": RESOURCE_SUMMARY_KIND,
        "job_id": job_id,
        "report_cutoff_at": finalized_at,
        "finalized_at": finalized_at,
        "participants": [accepted_entry],
        "totals": {
            "resource_time": deepcopy(accepted_entry["resource_time"]),
            "retained_content": retained_total,
            "f3": f3_total,
        },
    }


def _write_workspace_archive(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_STORED) as archive:
        ordered = sorted(members.items(), key=lambda item: (item[0].endswith("/resource_summary.json"), item[0]))
        for name, data in ordered:
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)


def _sum_groups(resource_time: dict[str, Any], resource: str, field: str, kind: str | None = None) -> Decimal | None:
    if resource not in resource_time:
        return None
    groups = resource_time[resource]["groups"]
    return sum(
        (Decimal(group[field]) for group in groups if kind is None or group.get("kind") == kind),
        Decimal(0),
    )


def _hours(value: Decimal | None, divisor: Decimal = Decimal(3600)) -> str:
    return "N/A" if value is None else f"{value / divisor:.4f}"


def _memory_time(resource_time: dict[str, Any]) -> Decimal | None:
    return Decimal(resource_time["memory"]["byte_seconds"]) if "memory" in resource_time else None


def _retained_bytes(value: dict[str, Any]) -> Decimal | None:
    return Decimal(value["bytes"]) if "bytes" in value else None


def _f3_bytes(value: dict[str, Any]) -> Decimal | None:
    return Decimal(value["remote_accepted"]["payload_bytes"]) if "remote_accepted" in value else None


def _human_job(summary: dict[str, Any]) -> str:
    entry = summary["participants"][0]
    totals = entry["resource_time"]
    cpu = _sum_groups(totals, "cpu", "unit_seconds")
    gpu = _sum_groups(totals, "gpu", "instance_seconds", "full_gpu")
    memory = Decimal(totals["memory"]["byte_seconds"]) if "memory" in totals else None
    retained = (
        Decimal(entry["retained_content"]["bytes"]) if entry["retained_content"]["status"] != "unavailable" else None
    )
    f3 = Decimal(entry["f3"]["remote_accepted"]["payload_bytes"]) if entry["f3"]["status"] != "unavailable" else None
    return "\n".join(
        [
            f"Resources recorded for job {summary['job_id']}.",
            "The participant sent one terminal report; resource-time was accumulated while it ran.",
            "",
            "SITE                    STATUS    QUALITY       FULL GPU h   CPU h   "
            "MEM GiB h   SAVED GiB   F3 REMOTE GiB",
            (
                f"{entry['participant_name']:<23} {entry['status']:<9} {totals['status'].upper():<13} "
                f"{_hours(gpu):>10} {_hours(cpu):>8} "
                f"{_hours(memory, Decimal(2**30 * 3600)):>11} "
                f"{_hours(retained, Decimal(2**30)):>11} "
                f"{_hours(f3, Decimal(2**30)):>8}"
            ),
            "",
        ]
    )


def _study_summary(study: str, job_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "kind": STUDY_SUMMARY_KIND,
        "selection": {"study_name": study},
        "generated_at": _utc_now(),
        "coverage": {
            "selected_jobs": "1",
            "included_jobs": "1",
            "unavailable_jobs": "0",
            "nonterminal_jobs": "0",
        },
        "jobs": [
            {
                "job_id": job_summary["job_id"],
                "job_status": "FINISHED:COMPLETED",
                "resource_data": "included",
                "totals": deepcopy(job_summary["totals"]),
            }
        ],
        "totals": deepcopy(job_summary["totals"]),
    }


def _aggregate_quality(totals: dict[str, Any]) -> str:
    statuses = {
        totals["resource_time"]["status"],
        totals["retained_content"]["status"],
        totals["f3"]["status"],
    }
    if statuses == {"reported"}:
        return "COMPLETE"
    if statuses == {"unavailable"}:
        return "UNAVAILABLE"
    return "PARTIAL"


def _human_study(study_summary: dict[str, Any]) -> str:
    coverage = study_summary["coverage"]
    show_mig = any(
        row["resource_data"] == "included"
        and (
            _sum_groups(
                row["totals"]["resource_time"],
                "gpu",
                "instance_seconds",
                "mig_compute_instance",
            )
            or Decimal(0)
        )
        > Decimal(0)
        for row in study_summary["jobs"]
    )
    header = "JOB                  JOB STATUS           RESOURCE DATA  QUALITY       FULL GPU h"
    if show_mig:
        header += "  MIG CI h"
    header += "      CPU h      MEM GiB h  SAVED GiB  F3 REMOTE GiB"
    lines = [
        f"Resources recorded for finalized jobs in study {study_summary['selection']['study_name']}.",
        (
            f"{coverage['selected_jobs']} jobs found | "
            f"{int(coverage['included_jobs']) + int(coverage['unavailable_jobs'])} finalized | "
            f"{coverage['included_jobs']} valid summaries | "
            f"{coverage['unavailable_jobs']} unavailable | "
            f"{coverage['nonterminal_jobs']} still running (excluded)"
        ),
        "",
        header,
    ]
    for row in study_summary["jobs"]:
        if row["resource_data"] != "included":
            mig = f"{'N/A':>8} " if show_mig else ""
            lines.append(
                f"{row['job_id']:<20} {row['job_status']:<20} {row['resource_data']:<14} "
                f"{'—':<13} {'N/A':>10} {mig}{'N/A':>10} {'N/A':>12} {'N/A':>10} {'N/A':>7}"
            )
            continue
        totals = row["totals"]
        resource_time = totals["resource_time"]
        retained = totals["retained_content"]
        f3 = totals["f3"]
        quality = _aggregate_quality(totals)
        mig = (
            f"{_hours(_sum_groups(resource_time, 'gpu', 'instance_seconds', 'mig_compute_instance')):>8} "
            if show_mig
            else ""
        )
        lines.append(
            f"{row['job_id']:<20} {row['job_status']:<20} {row['resource_data']:<14} "
            f"{quality:<13} "
            f"{_hours(_sum_groups(resource_time, 'gpu', 'instance_seconds', 'full_gpu')):>10} {mig}"
            f"{_hours(_sum_groups(resource_time, 'cpu', 'unit_seconds')):>10} "
            f"{_hours(_memory_time(resource_time), Decimal(2**30 * 3600)):>12} "
            f"{_hours(_retained_bytes(retained), Decimal(2**30)):>10} "
            f"{_hours(_f3_bytes(f3), Decimal(2**30)):>7}"
        )
    totals = study_summary["totals"]
    resource_time = totals["resource_time"]
    retained = totals["retained_content"]
    f3 = totals["f3"]
    total_quality = _aggregate_quality(totals)
    if total_quality == "UNAVAILABLE":
        coverage_label = "UNAVAILABLE"
    elif coverage["unavailable_jobs"] == "0" and coverage["nonterminal_jobs"] == "0" and total_quality == "COMPLETE":
        coverage_label = "COMPLETE"
    else:
        coverage_label = "PARTIAL"
    lines.extend(
        [
            "",
            f"Study totals from {coverage['included_jobs']} valid job summaries | coverage: {coverage_label}",
            (
                f"  FULL GPU {_hours(_sum_groups(resource_time, 'gpu', 'instance_seconds', 'full_gpu'))} h | "
                + (
                    "MIG CI "
                    f"{_hours(_sum_groups(resource_time, 'gpu', 'instance_seconds', 'mig_compute_instance'))} h | "
                    if show_mig
                    else ""
                )
                + f"CPU {_hours(_sum_groups(resource_time, 'cpu', 'unit_seconds'))} h | "
                f"MEM {_hours(_memory_time(resource_time), Decimal(2**30 * 3600))} GiB h | "
                f"SAVED {_hours(_retained_bytes(retained), Decimal(2**30))} GiB | "
                f"F3 REMOTE {_hours(_f3_bytes(f3), Decimal(2**30))} GiB"
            ),
            "",
            "Notes:",
            "  Totals include only finalized jobs with valid resource summaries.",
            "  This view includes only jobs still retained by the job store.",
            "",
        ]
    )
    return "\n".join(lines)


def _cli_envelope(selection: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "status": "ok",
        "exit_code": 0,
        "data": {"selection": selection, "summary": summary},
    }


def generate(output_dir: Path, job_id: str, study: str, observation_seconds: float) -> dict[str, Any]:
    output_dir = Path(output_dir)
    participant_name = "local-prototype-client"
    child_staging_dir = output_dir / "client_child" / "resource_stats" / "staging"
    parent_resource_dir = output_dir / "client_parent" / "resource_stats"
    child_staging_dir.mkdir(parents=True, exist_ok=True)
    parent_resource_dir.mkdir(parents=True, exist_ok=True)
    participant, evidence, handoff = _finish_local_report(
        job_id,
        participant_name,
        parent_resource_dir.parent,
        observation_seconds,
    )
    participant_bytes = _json_bytes(participant)
    _write(child_staging_dir / "terminal_handoff.json", _json_bytes(handoff))
    _write(output_dir / "prototype_diagnostics" / "probe_evidence.json", _json_bytes(evidence))
    _write(parent_resource_dir / "participant_summary.json", participant_bytes)

    accepted = _accepted_entry(participant_name, "client", participant)
    finalized_at = _utc_now()
    summary = _resource_summary(job_id, accepted, finalized_at)
    summary_bytes = _json_bytes(summary)

    server_resource_dir = output_dir / "server_run" / "resource_stats"
    server_participant_path = server_resource_dir / "participants" / f"{participant_name}.json"
    _write(server_participant_path, participant_bytes)
    _write(server_resource_dir / "resource_summary.json", summary_bytes)

    workspace_archive = output_dir / "job_store" / "jobs" / job_id / "workspace"
    members = {
        f"resource_stats/participants/{participant_name}.json": participant_bytes,
        "resource_stats/resource_summary.json": summary_bytes,
    }
    _write_workspace_archive(workspace_archive, members)

    cli_dir = output_dir / "cli"
    _write(
        cli_dir / "resources-all.json",
        _json_bytes(_cli_envelope({"job_id": job_id, "site": "all"}, summary)),
    )
    _write(cli_dir / "resources-all.txt", (render_job_resources(summary) + "\n").encode("utf-8"))
    study_summary = _study_summary(study, summary)
    _write(
        cli_dir / "resources-study.json",
        _json_bytes(_cli_envelope({"study": study}, study_summary)),
    )
    _write(cli_dir / "resources-study.txt", (render_study_resources(study_summary) + "\n").encode("utf-8"))

    fixtures = write_review_contract_fixtures(
        output_dir,
        job_id,
        summary_bytes,
        {participant_name: participant_bytes},
    )
    with ZipFile(workspace_archive, "r") as archive:
        workspace_summary_matches = archive.read("resource_stats/resource_summary.json") == summary_bytes
        workspace_participant_matches = (
            archive.read(f"resource_stats/participants/{participant_name}.json") == participant_bytes
        )
    receipt = {
        "schema_version": "prototype-0.4",
        "job_id": job_id,
        "study": study,
        "public_participant_reports": 1,
        "public_start_or_final_fragments": 0,
        "private_terminal_handoffs": 1,
        "private_terminal_handoff_path": "client_child/resource_stats/staging/terminal_handoff.json",
        "integrity": {
            "workspace_component": "workspace",
            "workspace_resource_summary_matches": workspace_summary_matches,
            "workspace_participant_matches": workspace_participant_matches,
        },
        "review_contract_fixtures": fixtures,
    }
    _write(output_dir / "generation_receipt.json", _json_bytes(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", "--output-dir", dest="output_dir", type=Path, default=Path("generated"))
    parser.add_argument("--job-id", default="prototype-job")
    parser.add_argument("--study", default="prototype-study")
    parser.add_argument(
        "--observation-seconds",
        type=float,
        default=0.1,
        help="time for which the first real resource observation remains active",
    )
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir, args.job_id, args.study, args.observation_seconds), indent=2))


if __name__ == "__main__":
    main()
