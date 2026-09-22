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

"""Generate deterministic schema-v1 records, archives, and CLI examples.

The records model one moderately sized 14B-model job and one additional
completed job used by the study view. Each participant has exactly one terminal
report. The resource-time values are final accumulator outputs; private
observation intervals are intentionally absent.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from contract_v1 import (
    KIND_PARTICIPANT_SUMMARY,
    KIND_RESOURCE_SUMMARY,
    KIND_STUDY_SUMMARY,
    derive_job_totals,
    derive_study_totals,
    load_and_validate,
    validate_bundle,
)

SCHEMA_ROOT = Path(__file__).resolve().parent
GOLDEN_ROOT = SCHEMA_ROOT / "golden" / "v1"
DEFAULT_OUTPUT = GOLDEN_ROOT / "finalized_job"
JOB_ID = "job-20260909-001"
STUDY_JOB_ID = "job-20260910-002"
STUDY_NAME = "cancer-research"
SITE_1_NAME = "site-1"
SITE_2_NAME = "site-2"
SITE_3_NAME = "site-3"
SERVER_NAME = "server"
STUDY_SITE_NAME = "site-4"
CLIENT_F3_BYTES = "147700336640"
SERVER_F3_BYTES = "295400673280"
SAVED_RESULT_BYTES = "29540266113"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_workspace_archive(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_STORED) as archive:
        ordered = sorted(members.items(), key=lambda item: (item[0].endswith("/resource_summary.json"), item[0]))
        for member_name, data in ordered:
            info = ZipInfo(member_name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)


def _counter(payload_bytes: str = "0", messages: str = "0") -> dict[str, str]:
    return {"payload_bytes": payload_bytes, "messages": messages}


def _f3(
    *,
    remote_payload_bytes: str = "0",
    remote_messages: str = "0",
) -> dict[str, Any]:
    return {
        "status": "reported",
        "remote_accepted": _counter(remote_payload_bytes, remote_messages),
    }


def _participant(
    *,
    job_id: str,
    participant_name: str,
    reported_at: str,
    resource_time: dict[str, Any],
    workspace_capacity_bytes: str,
    retained_content: dict[str, Any],
    f3: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "kind": KIND_PARTICIPANT_SUMMARY,
        "job_id": job_id,
        "participant_name": participant_name,
        "reported_at": reported_at,
        "resource_time": resource_time,
        "workspace_filesystem": {
            "status": "reported",
            "capacity_bytes": workspace_capacity_bytes,
        },
        "retained_content": retained_content,
        "f3": f3,
    }


def _main_participant() -> dict[str, Any]:
    return _participant(
        job_id=JOB_ID,
        participant_name=SITE_1_NAME,
        reported_at="2026-09-09T14:37:03Z",
        resource_time={
            "status": "reported",
            "measured_seconds": "2223",
            "cpu": {
                "groups": [
                    {
                        "unit_seconds": "71136",
                        "model": "AMD EPYC 9654",
                        "architecture": "x86_64",
                    }
                ]
            },
            "memory": {"byte_seconds": "458290190352384"},
            "gpu": {
                "groups": [
                    {
                        "kind": "full_gpu",
                        "instance_seconds": "8892",
                        "model": "NVIDIA A100 80GB",
                        "memory_bytes": "85899345920",
                    }
                ]
            },
        },
        workspace_capacity_bytes="1099511627776",
        retained_content={"status": "reported", "bytes": "0"},
        f3=_f3(remote_payload_bytes=CLIENT_F3_BYTES, remote_messages="5"),
    )


def _partial_participant() -> dict[str, Any]:
    return _participant(
        job_id=JOB_ID,
        participant_name=SITE_2_NAME,
        reported_at="2026-09-09T14:37:03Z",
        resource_time={
            "status": "partial",
            "issues": ["observation_incomplete"],
            "measured_seconds": "1923",
            "cpu": {
                "groups": [
                    {
                        "unit_seconds": "56736",
                        "model": "Intel Xeon Platinum 8480+",
                        "architecture": "x86_64",
                    }
                ]
            },
            "memory": {"byte_seconds": "375826818269184"},
            "gpu": {
                "groups": [
                    {
                        "kind": "full_gpu",
                        "instance_seconds": "7092",
                        "model": "NVIDIA A100 80GB",
                        "memory_bytes": "85899345920",
                    }
                ]
            },
        },
        workspace_capacity_bytes="2199023255552",
        retained_content={
            "status": "unavailable",
            "issues": ["not_bound"],
        },
        f3=_f3(remote_payload_bytes=CLIENT_F3_BYTES, remote_messages="5"),
    )


def _server_participant() -> dict[str, Any]:
    return _participant(
        job_id=JOB_ID,
        participant_name=SERVER_NAME,
        reported_at="2026-09-09T14:37:03Z",
        resource_time={
            "status": "reported",
            "measured_seconds": "2223",
            "cpu": {
                "groups": [
                    {
                        "unit_seconds": "17784",
                        "model": "AMD EPYC 9654",
                        "architecture": "x86_64",
                    }
                ]
            },
            "memory": {"byte_seconds": "152763396784128"},
            "gpu": {"groups": []},
        },
        workspace_capacity_bytes="1099511627776",
        retained_content={"status": "reported", "bytes": SAVED_RESULT_BYTES},
        f3=_f3(remote_payload_bytes=SERVER_F3_BYTES, remote_messages="10"),
    )


def _study_job_participant() -> dict[str, Any]:
    return _participant(
        job_id=STUDY_JOB_ID,
        participant_name=STUDY_SITE_NAME,
        reported_at="2026-09-10T18:00:00Z",
        resource_time={
            "status": "reported",
            "measured_seconds": "14400",
            "cpu": {
                "groups": [
                    {
                        "unit_seconds": "1843200",
                        "model": "AMD EPYC 9654",
                        "architecture": "x86_64",
                    }
                ]
            },
            "memory": {"byte_seconds": "7916483719987200"},
            "gpu": {
                "groups": [
                    {
                        "kind": "full_gpu",
                        "instance_seconds": "115200",
                        "model": "NVIDIA H100 80GB HBM3",
                        "memory_bytes": "85899345920",
                    }
                ]
            },
        },
        workspace_capacity_bytes="4398046511104",
        retained_content={"status": "reported", "bytes": "59080532226"},
        f3=_f3(remote_payload_bytes="2363205386240", remote_messages="40"),
    )


def _large_participant() -> dict[str, Any]:
    return _participant(
        job_id="job-large-exactness",
        participant_name="site-large",
        reported_at="2026-09-09T00:15:01Z",
        resource_time={
            "status": "reported",
            "measured_seconds": "901",
            "cpu": {
                "groups": [
                    {
                        "unit_seconds": "901",
                        "model": "AMD EPYC 9654",
                        "architecture": "x86_64",
                    }
                ]
            },
            "memory": {"byte_seconds": "9010000000000901"},
            "gpu": {"groups": []},
        },
        workspace_capacity_bytes="10000000000001",
        retained_content={"status": "reported", "bytes": "0"},
        f3=_f3(),
    )


def _accepted_entry(
    participant: dict[str, Any],
    *,
    participant_name: str,
    role: str,
    received_at: str,
) -> dict[str, Any]:
    return {
        "participant_name": participant_name,
        "role": role,
        "status": "accepted",
        "received_at": received_at,
        "resource_time": deepcopy(participant["resource_time"]),
        "retained_content": deepcopy(participant["retained_content"]),
        "f3": deepcopy(participant["f3"]),
    }


def _resource_summary(
    job_id: str,
    participants: list[dict[str, Any]],
    *,
    cutoff: str,
    finalized: str,
) -> dict[str, Any]:
    participants.sort(key=lambda item: (item["role"], item["participant_name"]))
    return {
        "schema_version": "1.0",
        "kind": KIND_RESOURCE_SUMMARY,
        "job_id": job_id,
        "report_cutoff_at": cutoff,
        "finalized_at": finalized,
        "participants": participants,
        "totals": derive_job_totals(participants),
    }


def _decimal_sum(groups: list[dict[str, Any]], field: str) -> Decimal:
    return sum((Decimal(group[field]) for group in groups), Decimal(0))


def _hours(value: Decimal | None, divisor: Decimal = Decimal(3600)) -> str:
    return "N/A" if value is None else f"{value / divisor:.4f}"


def _duration(value: str) -> str:
    seconds = Decimal(value)
    hours = int(seconds // Decimal(3600))
    after_hours = seconds - Decimal(hours * 3600)
    minutes = int(after_hours // Decimal(60))
    remainder = after_hours - Decimal(minutes * 60)
    text = format(remainder, "f").rstrip("0").rstrip(".")
    prefix = f"{hours}h" if hours else ""
    return f"{prefix}{minutes}m{text or '0'}s"


def _gpu_time(resource_time: dict[str, Any], kind: str) -> Decimal | None:
    if "gpu" not in resource_time:
        return None
    return sum(
        (Decimal(group["instance_seconds"]) for group in resource_time["gpu"]["groups"] if group["kind"] == kind),
        Decimal(0),
    )


def _cpu_time(resource_time: dict[str, Any]) -> Decimal | None:
    if "cpu" not in resource_time:
        return None
    return _decimal_sum(resource_time["cpu"]["groups"], "unit_seconds")


def _memory_time(resource_time: dict[str, Any]) -> Decimal | None:
    if "memory" not in resource_time:
        return None
    return Decimal(resource_time["memory"]["byte_seconds"])


def _retained_bytes(value: dict[str, Any]) -> Decimal | None:
    return Decimal(value["bytes"]) if "bytes" in value else None


def _f3_bytes(value: dict[str, Any]) -> Decimal | None:
    return Decimal(value["remote_accepted"]["payload_bytes"]) if "remote_accepted" in value else None


def _average(value: Decimal | None, measured_seconds: str | None, divisor: Decimal = Decimal(1)) -> str:
    if value is None or measured_seconds is None:
        return "N/A"
    measured = Decimal(measured_seconds)
    if measured <= 0:
        return "N/A"
    return f"{value / measured / divisor:.4f}"


def _has_retained_content(value: dict[str, Any]) -> bool:
    return _retained_bytes(value["retained_content"]) is not None


def _has_f3(value: dict[str, Any]) -> bool:
    return _f3_bytes(value["f3"]) is not None


def _quantity(label: str, value: str, unit: str) -> str:
    return f"{label} {value}" if value == "N/A" else f"{label} {value} {unit}"


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    values = [headers] + rows
    widths = [max(len(row[index]) for row in values) for index in range(len(headers))]
    return ["  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip() for row in values]


def _show_mig(entries: list[dict[str, Any]]) -> bool:
    return any(
        entry["status"] == "accepted"
        and any(
            group["kind"] == "mig_compute_instance" for group in entry["resource_time"].get("gpu", {}).get("groups", [])
        )
        for entry in entries
    )


def _human_cli(summary: dict[str, Any], selected_site: str | None = None) -> str:
    accepted = sum(entry["status"] == "accepted" for entry in summary["participants"])
    expected = len(summary["participants"])
    coverage = "COMPLETE" if accepted == expected else "PARTIAL"
    entries = (
        summary["participants"]
        if selected_site is None
        else [entry for entry in summary["participants"] if entry["participant_name"] == selected_site]
    )
    if not entries:
        raise ValueError(f"unknown site '{selected_site}'")
    show_mig = _show_mig(entries)
    show_retained = any(entry["status"] == "accepted" and _has_retained_content(entry) for entry in entries)
    show_f3 = any(entry["status"] == "accepted" and _has_f3(entry) for entry in entries)
    selection = "" if selected_site is None else f" | selected site: {selected_site}"
    lines = [
        f"Recorded resources for job {summary['job_id']}.",
        f"Job coverage: {coverage} ({accepted} accepted / {expected} expected){selection}",
        "",
        "Recorded average visible capacity over each measured interval",
    ]
    rows = []
    for entry in entries:
        if entry["status"] != "accepted":
            metrics = ["—", "—", "N/A", "N/A", "N/A"]
            if show_mig:
                metrics.append("N/A")
            rows.append([entry["participant_name"], entry["role"], entry["status"], *metrics])
            continue
        resource_time = entry["resource_time"]
        measured = resource_time.get("measured_seconds")
        metrics = [
            resource_time["status"].upper(),
            _duration(measured) if measured is not None else "N/A",
            _average(_cpu_time(resource_time), measured),
            _average(_memory_time(resource_time), measured, Decimal(2**30)),
            _average(_gpu_time(resource_time, "full_gpu"), measured),
        ]
        if show_mig:
            metrics.append(_average(_gpu_time(resource_time, "mig_compute_instance"), measured))
        rows.append([entry["participant_name"], entry["role"], entry["status"], *metrics])
    headers = ["SITE", "ROLE", "REPORT", "COMPUTE", "MEASURED TIME", "CPU UNITS", "MEM GiB", "FULL GPUs"]
    if show_mig:
        headers.append("MIG INSTANCES")
    lines.extend(_table(headers, rows))
    if show_retained or show_f3:
        other_headers = ["SITE"]
        if show_retained:
            other_headers.append("SAVED CONTENT GiB")
        if show_f3:
            other_headers.extend(["F3 STATUS", "F3 REMOTE ACCEPTED GiB"])
        other_rows = []
        for entry in entries:
            if entry["status"] != "accepted":
                values = ["N/A"] * (len(other_headers) - 1)
            else:
                values = []
                if show_retained:
                    values.append(_hours(_retained_bytes(entry["retained_content"]), Decimal(2**30)))
                if show_f3:
                    values.extend([entry["f3"]["status"].upper(), _hours(_f3_bytes(entry["f3"]), Decimal(2**30))])
            other_rows.append([entry["participant_name"], *values])
        lines.extend(["", "Other recorded participant totals", *_table(other_headers, other_rows)])
    if selected_site is None:
        totals = summary["totals"]
        resource_time = totals["resource_time"]
        measured_time = _duration(resource_time["measured_seconds"]) if "measured_seconds" in resource_time else "N/A"
        resource_totals = [
            _quantity("CPU", _hours(_cpu_time(resource_time)), "unit h"),
            _quantity("MEMORY", _hours(_memory_time(resource_time), Decimal(2**30 * 3600)), "GiB h"),
            _quantity("FULL GPUs", _hours(_gpu_time(resource_time, "full_gpu")), "instance h"),
        ]
        if show_mig:
            resource_totals.append(
                _quantity("MIG INSTANCES", _hours(_gpu_time(resource_time, "mig_compute_instance")), "instance h")
            )
        lines.extend(
            [
                "",
                f"Additive participant resource-time from accepted reports | compute: {resource_time['status'].upper()}",
                f"  Summed measured participant time: {measured_time}",
                "  " + " | ".join(resource_totals),
            ]
        )
        other_totals = []
        if show_retained:
            other_totals.append(
                _quantity("SAVED CONTENT", _hours(_retained_bytes(totals["retained_content"]), Decimal(2**30)), "GiB")
            )
        if show_f3:
            other_totals.extend(
                [
                    f"F3 STATUS {totals['f3']['status'].upper()}",
                    _quantity("F3 REMOTE ACCEPTED", _hours(_f3_bytes(totals["f3"]), Decimal(2**30)), "GiB"),
                ]
            )
        if other_totals:
            lines.append("  Other additive totals: " + " | ".join(other_totals))
    lines.extend(
        [
            "",
            "Notes:",
            "  PARTIAL means at least one expected report or observation was incomplete.",
            "  Each average is resource-time divided by that row's measured interval.",
            "  Totals add participant reports; overlapping resources can be counted more than once.",
        ]
    )
    if selected_site is None:
        lines.append("  Use --site SITE or --format json to see hardware model details.")
    lines.append("")
    return "\n".join(lines)


def _hardware_details(
    summary: dict[str, Any],
    participant_name: str,
    participant_records: dict[str, dict[str, Any]] | None = None,
) -> str:
    entry = next(item for item in summary["participants"] if item["participant_name"] == participant_name)
    if entry["status"] != "accepted":
        return f"No accepted resource report for {participant_name}.\n"
    resource_time = entry["resource_time"]
    lines = [
        f"Hardware detail for {participant_name}",
        "Model metadata is optional and does not change numeric totals.",
        "",
    ]
    for group in resource_time.get("cpu", {}).get("groups", []):
        model = group.get("model", "model not reported")
        architecture = f" ({group['architecture']})" if "architecture" in group else ""
        lines.append(
            f"CPU: {model}{architecture}; "
            f"{_average(Decimal(group['unit_seconds']), resource_time.get('measured_seconds'))} average visible units"
        )
    for group in resource_time.get("gpu", {}).get("groups", []):
        label = "full GPU" if group["kind"] == "full_gpu" else "MIG compute instance"
        model = group.get("model", "model not reported")
        memory = (
            f", {Decimal(group['memory_bytes']) / Decimal(2**30):.0f} GiB per instance"
            if "memory_bytes" in group
            else ""
        )
        lines.append(
            f"GPU ({label}): {model}{memory}; "
            f"{_average(Decimal(group['instance_seconds']), resource_time.get('measured_seconds'))} "
            "average visible instances"
        )
    if participant_records is not None:
        participant = participant_records[entry["participant_name"]]
        workspace = participant["workspace_filesystem"]
        if workspace["status"] == "reported":
            gib = Decimal(workspace["capacity_bytes"]) / Decimal(2**30)
            lines.append(f"Visible workspace-filesystem capacity at reporting time: {gib:.4f} GiB")
    lines.append("")
    return "\n".join(lines)


def _study_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows.sort(key=lambda row: row["job_id"])
    return {
        "schema_version": "1.0",
        "kind": KIND_STUDY_SUMMARY,
        "selection": {"study_name": STUDY_NAME},
        "generated_at": "2026-09-12T20:00:00Z",
        "coverage": {
            "selected_jobs": str(len(rows)),
            "included_jobs": str(sum(row["resource_data"] == "included" for row in rows)),
            "unavailable_jobs": str(sum(row["resource_data"] == "unavailable" for row in rows)),
            "nonterminal_jobs": str(sum(row["resource_data"] == "nonterminal" for row in rows)),
        },
        "jobs": rows,
        "totals": derive_study_totals(rows),
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


def _human_study_cli(summary: dict[str, Any]) -> str:
    coverage = summary["coverage"]
    show_mig = any(
        row["resource_data"] == "included"
        and any(
            group["kind"] == "mig_compute_instance"
            for group in row["totals"]["resource_time"].get("gpu", {}).get("groups", [])
        )
        for row in summary["jobs"]
    )
    show_retained = any(
        row["resource_data"] == "included" and _has_retained_content(row["totals"]) for row in summary["jobs"]
    )
    show_f3 = any(row["resource_data"] == "included" and _has_f3(row["totals"]) for row in summary["jobs"])
    lines = [
        f"Resources recorded for finalized jobs in study {summary['selection']['study_name']}.",
        (
            f"{coverage['selected_jobs']} jobs found | "
            f"{int(coverage['included_jobs']) + int(coverage['unavailable_jobs'])} finalized | "
            f"{coverage['included_jobs']} valid summaries | "
            f"{coverage['unavailable_jobs']} unavailable | "
            f"{coverage['nonterminal_jobs']} still running (excluded)"
        ),
        "",
    ]
    rows = []
    for row in summary["jobs"]:
        if row["resource_data"] != "included":
            metrics = ["—", "N/A", "N/A", "N/A"]
            if show_mig:
                metrics.insert(2, "N/A")
            if show_retained:
                metrics.append("N/A")
            if show_f3:
                metrics.extend(["N/A", "N/A"])
            rows.append([row["job_id"], row["job_status"], row["resource_data"], *metrics])
            continue
        totals = row["totals"]
        resource_time = totals["resource_time"]
        quality = _aggregate_quality(totals)
        metrics = [quality, _hours(_gpu_time(resource_time, "full_gpu"))]
        if show_mig:
            metrics.append(_hours(_gpu_time(resource_time, "mig_compute_instance")))
        metrics.extend(
            [
                _hours(_cpu_time(resource_time)),
                _hours(_memory_time(resource_time), Decimal(2**30 * 3600)),
            ]
        )
        if show_retained:
            metrics.append(_hours(_retained_bytes(totals["retained_content"]), Decimal(2**30)))
        if show_f3:
            metrics.extend([totals["f3"]["status"].upper(), _hours(_f3_bytes(totals["f3"]), Decimal(2**30))])
        rows.append([row["job_id"], row["job_status"], row["resource_data"], *metrics])
    headers = ["JOB", "JOB STATUS", "RESOURCE DATA", "QUALITY", "FULL GPU h"]
    if show_mig:
        headers.append("MIG h")
    headers.extend(["CPU unit h", "MEM GiB h"])
    if show_retained:
        headers.append("SAVED CONTENT GiB")
    if show_f3:
        headers.extend(["F3 STATUS", "F3 REMOTE ACCEPTED GiB"])
    lines.extend(_table(headers, rows))
    totals = summary["totals"]
    resource_time = totals["resource_time"]
    total_quality = _aggregate_quality(totals)
    if total_quality == "UNAVAILABLE":
        coverage_label = "UNAVAILABLE"
    elif coverage["unavailable_jobs"] == "0" and coverage["nonterminal_jobs"] == "0" and total_quality == "COMPLETE":
        coverage_label = "COMPLETE"
    else:
        coverage_label = "PARTIAL"
    resource_totals = [
        _quantity("FULL GPUs", _hours(_gpu_time(resource_time, "full_gpu")), "instance h"),
        _quantity("CPU", _hours(_cpu_time(resource_time)), "unit h"),
        _quantity("MEMORY", _hours(_memory_time(resource_time), Decimal(2**30 * 3600)), "GiB h"),
    ]
    if show_mig:
        resource_totals.insert(
            1,
            _quantity("MIG INSTANCES", _hours(_gpu_time(resource_time, "mig_compute_instance")), "instance h"),
        )
    lines.extend(
        [
            "",
            f"Study totals from {coverage['included_jobs']} valid job summaries | coverage: {coverage_label}",
            "  Additive participant resource-time: " + " | ".join(resource_totals),
        ]
    )
    other_totals = []
    if show_retained:
        other_totals.append(
            _quantity("SAVED CONTENT", _hours(_retained_bytes(totals["retained_content"]), Decimal(2**30)), "GiB")
        )
    if show_f3:
        other_totals.extend(
            [
                f"F3 STATUS {totals['f3']['status'].upper()}",
                _quantity("F3 REMOTE ACCEPTED", _hours(_f3_bytes(totals["f3"]), Decimal(2**30)), "GiB"),
            ]
        )
    if other_totals:
        lines.append("  Other additive totals: " + " | ".join(other_totals))
    lines.extend(
        [
            "",
            "Notes:",
            "  Totals include only finalized jobs with valid resource summaries.",
            "  This view includes only jobs still retained by the job store.",
            "",
        ]
    )
    return "\n".join(lines)


def _workspace_members(
    summary_bytes: bytes,
    participant_files: dict[str, bytes],
) -> dict[str, bytes]:
    return {
        **{
            f"resource_stats/participants/{participant_name}.json": participant_bytes
            for participant_name, participant_bytes in participant_files.items()
        },
        "resource_stats/resource_summary.json": summary_bytes,
    }


def build(output_root: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    site_1 = _main_participant()
    site_2 = _partial_participant()
    server = _server_participant()
    accepted_records = {
        SITE_1_NAME: site_1,
        SITE_2_NAME: site_2,
        SERVER_NAME: server,
    }
    accepted_bytes = {key: _json_bytes(record) for key, record in accepted_records.items()}
    participants = [
        _accepted_entry(
            site_1,
            participant_name=SITE_1_NAME,
            role="client",
            received_at="2026-09-09T14:37:03.1Z",
        ),
        _accepted_entry(
            site_2,
            participant_name=SITE_2_NAME,
            role="client",
            received_at="2026-09-09T14:37:03.2Z",
        ),
        {
            "participant_name": SITE_3_NAME,
            "role": "client",
            "status": "missing",
        },
        _accepted_entry(
            server,
            participant_name=SERVER_NAME,
            role="server",
            received_at="2026-09-09T14:37:03.3Z",
        ),
    ]
    summary = _resource_summary(
        JOB_ID,
        participants,
        cutoff="2026-09-09T14:37:04Z",
        finalized="2026-09-09T14:37:04.1Z",
    )
    summary_bytes = _json_bytes(summary)

    study_participant = _study_job_participant()
    study_participant_bytes = _json_bytes(study_participant)
    study_entry = _accepted_entry(
        study_participant,
        participant_name=STUDY_SITE_NAME,
        role="client",
        received_at="2026-09-10T18:00:00.1Z",
    )
    study_job_summary = _resource_summary(
        STUDY_JOB_ID,
        [study_entry],
        cutoff="2026-09-10T18:00:01Z",
        finalized="2026-09-10T18:00:01.1Z",
    )
    study_job_summary_bytes = _json_bytes(study_job_summary)
    study_participant_files = {STUDY_SITE_NAME: study_participant_bytes}

    study = _study_summary(
        [
            {
                "job_id": JOB_ID,
                "job_status": "FINISHED:COMPLETED",
                "resource_data": "included",
                "totals": deepcopy(summary["totals"]),
            },
            {
                "job_id": STUDY_JOB_ID,
                "job_status": "FINISHED:COMPLETED",
                "resource_data": "included",
                "totals": deepcopy(study_job_summary["totals"]),
            },
            {
                "job_id": "job-20260911-003",
                "job_status": "FINISHED:COMPLETED",
                "resource_data": "unavailable",
            },
            {
                "job_id": "job-20260912-004",
                "job_status": "RUNNING",
                "resource_data": "nonterminal",
            },
        ]
    )

    large_participant = _large_participant()
    large_entry = _accepted_entry(
        large_participant,
        participant_name="site-large",
        role="client",
        received_at="2026-09-09T00:15:01.2Z",
    )
    large_summary = _resource_summary(
        large_participant["job_id"],
        [large_entry],
        cutoff="2026-09-09T00:15:02Z",
        finalized="2026-09-09T00:15:02.1Z",
    )

    records = {
        "participant_summary.json": site_1,
        "participant_summary_partial.json": site_2,
        "participant_summary_server.json": server,
        "participant_summary_study_job.json": study_participant,
        "participant_summary_large_value.json": large_participant,
        "resource_summary.json": summary,
        "resource_summary_study_job.json": study_job_summary,
        "resource_summary_large_value.json": large_summary,
        "study_summary.json": study,
    }
    encoded = {name: _json_bytes(record) for name, record in records.items()}
    for data in encoded.values():
        load_and_validate(data)
    validate_bundle(
        summary,
        accepted_records,
        {
            "resource_summary.json": summary_bytes,
            **{
                f"participants/{participant_name}.json": participant_bytes
                for participant_name, participant_bytes in accepted_bytes.items()
            },
        },
    )
    validate_bundle(
        study_job_summary,
        {STUDY_SITE_NAME: study_participant},
        {
            "resource_summary.json": study_job_summary_bytes,
            f"participants/{STUDY_SITE_NAME}.json": study_participant_bytes,
        },
    )
    for name, data in encoded.items():
        _write(GOLDEN_ROOT / name, data)

    resource_root = output_root / "server_run" / "resource_stats"
    for participant_name, participant_bytes in accepted_bytes.items():
        _write(resource_root / "participants" / f"{participant_name}.json", participant_bytes)
    _write(resource_root / "resource_summary.json", summary_bytes)

    workspace_archive = output_root / "job_store" / "jobs" / JOB_ID / "workspace"
    workspace_members = _workspace_members(summary_bytes, accepted_bytes)
    _write_workspace_archive(workspace_archive, workspace_members)

    study_workspace_archive = output_root / "job_store" / "jobs" / STUDY_JOB_ID / "workspace"
    study_workspace_members = _workspace_members(
        study_job_summary_bytes,
        study_participant_files,
    )
    _write_workspace_archive(study_workspace_archive, study_workspace_members)

    cli_json = {
        "schema_version": "1",
        "status": "ok",
        "exit_code": 0,
        "data": {
            "selection": {"job_id": JOB_ID, "site": "all"},
            "summary": summary,
        },
    }
    site_records = {
        SITE_1_NAME: site_1,
        SITE_2_NAME: site_2,
        SERVER_NAME: server,
    }
    _write(output_root / "cli" / "resources-all.json", _json_bytes(cli_json))
    _write(output_root / "cli" / "resources-all.txt", _human_cli(summary).encode("utf-8"))
    _write(
        output_root / "cli" / "resources-site-1-details.txt",
        (_human_cli(summary, "site-1") + "\n" + _hardware_details(summary, "site-1", site_records)).encode("utf-8"),
    )
    _write(
        output_root / "cli" / "resources-site-2-details.txt",
        (_human_cli(summary, "site-2") + "\n" + _hardware_details(summary, "site-2", site_records)).encode("utf-8"),
    )
    study_cli_json = {
        "schema_version": "1",
        "status": "ok",
        "exit_code": 0,
        "data": {
            "selection": {"study": STUDY_NAME},
            "summary": study,
        },
    }
    _write(output_root / "cli" / "resources-study.json", _json_bytes(study_cli_json))
    _write(output_root / "cli" / "resources-study.txt", _human_study_cli(study).encode("utf-8"))

    with ZipFile(workspace_archive, "r") as archive:
        workspace_summary_matches = archive.read("resource_stats/resource_summary.json") == summary_bytes
    with ZipFile(study_workspace_archive, "r") as archive:
        study_workspace_summary_matches = (
            archive.read("resource_stats/resource_summary.json") == study_job_summary_bytes
        )

    receipt = {
        "generator": Path(__file__).name,
        "schema_version": "1.0",
        "job_id": JOB_ID,
        "study": STUDY_NAME,
        "public_participant_reports": len(accepted_records),
        "public_start_or_final_fragments": 0,
        "workspace_component": workspace_archive.name,
        "workspace_resource_summary_member": "resource_stats/resource_summary.json",
        "workspace_resource_summary_matches": workspace_summary_matches,
        "study_job_workspace_resource_summary_matches": study_workspace_summary_matches,
        "scenario_basis": {
            "description": "Illustrative values scaled to completed Qwen2.5-14B qualification jobs.",
            "reference_label": "Five-round 14B full-model qualification, 2026-07-31",
            "scope_note": (
                "The A100 model, four-GPU baseline, runtime scale, model-state size, and saved-result size "
                "are evidence-based; CPU, memory, workspace-filesystem capacity, and observation changes "
                "are illustrative."
            ),
            "reference_runtime_seconds": "2223",
            "reference_model_state_bytes": "29540067328",
            "reference_logical_state_directions": "20",
            "reference_logical_state_bytes": "590801346560",
            "reference_saved_result_bytes": SAVED_RESULT_BYTES,
            "f3_note": (
                "The historical run recorded model-state size; its logical volume was derived, and it did "
                "not measure the proposed post-encoding F3 counter."
            ),
        },
        "derived_examples": {
            "site_1_measured_seconds": site_1["resource_time"]["measured_seconds"],
            "site_2_measured_seconds": site_2["resource_time"]["measured_seconds"],
            "server_measured_seconds": server["resource_time"]["measured_seconds"],
            "accepted_measured_seconds": summary["totals"]["resource_time"]["measured_seconds"],
            "job_cpu_unit_seconds": str(
                _decimal_sum(summary["totals"]["resource_time"]["cpu"]["groups"], "unit_seconds")
            ),
            "job_gpu_instance_seconds": str(
                _decimal_sum(summary["totals"]["resource_time"]["gpu"]["groups"], "instance_seconds")
            ),
            "study_cpu_unit_seconds": str(
                _decimal_sum(study["totals"]["resource_time"]["cpu"]["groups"], "unit_seconds")
            ),
            "study_gpu_instance_seconds": str(
                _decimal_sum(study["totals"]["resource_time"]["gpu"]["groups"], "instance_seconds")
            ),
            "large_memory_byte_seconds": large_summary["totals"]["resource_time"]["memory"]["byte_seconds"],
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
