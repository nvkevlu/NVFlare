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

"""Human rendering for ``nvflare job resources``."""

from __future__ import annotations

from decimal import Decimal

from nvflare.private.fed.resource_stats.contract import derive_job_totals

_GIB = Decimal(2**30)
_HOUR = Decimal(3600)


def _number(value, divisor=Decimal(1)) -> str:
    if value is None:
        return "N/A"
    return f"{Decimal(value) / divisor:.4f}"


def _duration(value) -> str:
    if value is None:
        return "—"
    seconds = int(Decimal(value))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours:
        return f"{hours}h{minutes}m{seconds}s"
    if minutes:
        return f"{minutes}m{seconds}s"
    return f"{seconds}s"


def _average(value, measured_seconds, divisor=Decimal(1)) -> str:
    if value is None or measured_seconds is None:
        return "N/A"
    measured = Decimal(measured_seconds)
    if measured <= 0:
        return "N/A"
    return _number(Decimal(value) / measured, divisor)


def _sum_group(resource_time: dict, resource: str, field: str, kind: str | None = None):
    groups = resource_time.get(resource, {}).get("groups", [])
    values = [Decimal(group[field]) for group in groups if kind is None or group.get("kind") == kind]
    return sum(values, Decimal(0)) if values or resource in resource_time else None


def _sent_bytes(value: dict):
    traffic = value.get("message_traffic", {})
    if "sent" in traffic:
        return traffic["sent"]["payload_bytes"]
    if "sent_to" in traffic:
        return str(sum(int(group["payload_bytes"]) for group in traffic["sent_to"]))
    return None


def _incoming_traffic(participants: list[dict]) -> tuple[dict[str, int], bool, set[str]]:
    """Index addressed sends once for the per-site CLI table."""

    sent_to: dict[str, int] = {}
    has_numeric_source = False
    incomplete_sources = set()
    for source in participants:
        traffic = source.get("message_traffic", {}) if source["status"] == "accepted" else {}
        if traffic.get("status") != "reported":
            incomplete_sources.add(source["participant_name"])
        if "sent_to" not in traffic:
            continue
        has_numeric_source = True
        for group in traffic["sent_to"]:
            name = group["participant_name"]
            sent_to[name] = sent_to.get(name, 0) + int(group["payload_bytes"])
    return sent_to, has_numeric_source, incomplete_sources


def _sent_to_site_display(
    sent_to: dict[str, int], has_numeric_source: bool, incomplete_sources: set[str], participant_name: str
) -> str:
    if not has_numeric_source:
        return "N/A"
    complete = not incomplete_sources or incomplete_sources == {participant_name}
    shown = _number(str(sent_to.get(participant_name, 0)), _GIB)
    return shown if complete else f"{shown} (partial)"


def _metrics(value: dict) -> list[str]:
    resource_time = value.get("resource_time", {})
    return [
        resource_time.get("status", "—").upper(),
        _duration(resource_time.get("measured_seconds")),
        _number(_sum_group(resource_time, "gpu", "instance_seconds", "full_gpu"), _HOUR),
        _number(_sum_group(resource_time, "gpu", "instance_seconds", "mig_compute_instance"), _HOUR),
        _number(_sum_group(resource_time, "cpu", "unit_seconds"), _HOUR),
        _number(resource_time.get("memory", {}).get("byte_seconds"), _GIB * _HOUR),
        _number(value.get("retained_content", {}).get("bytes"), _GIB),
        _number(_sent_bytes(value), _GIB),
    ]


def _average_metrics(value: dict) -> list[str]:
    resource_time = value.get("resource_time", {})
    measured = resource_time.get("measured_seconds")
    return [
        resource_time.get("status", "—").upper(),
        _duration(measured),
        _average(_sum_group(resource_time, "cpu", "unit_seconds"), measured),
        _average(resource_time.get("memory", {}).get("byte_seconds"), measured, _GIB),
        _average(_sum_group(resource_time, "gpu", "instance_seconds", "full_gpu"), measured),
        _average(_sum_group(resource_time, "gpu", "instance_seconds", "mig_compute_instance"), measured),
    ]


def _has_retained_content(value: dict) -> bool:
    return value.get("retained_content", {}).get("bytes") is not None


def _has_message_traffic(value: dict) -> bool:
    return _sent_bytes(value) is not None


def _other_metrics(value: dict, show_retained: bool, show_message_traffic: bool) -> list[str]:
    metrics = []
    if show_retained:
        retained = value.get("retained_content", {})
        metrics.extend(
            [
                retained.get("status", "—").upper(),
                _number(retained.get("bytes"), _GIB),
            ]
        )
    if show_message_traffic:
        traffic = value.get("message_traffic", {})
        metrics.extend(
            [
                traffic.get("status", "—").upper(),
                _number(_sent_bytes(value), _GIB),
            ]
        )
    return metrics


def _quantity(label: str, value: str, unit: str) -> str:
    return f"{label} {value}" if value == "N/A" else f"{label} {value} {unit}"


def _has_mig(value: dict) -> bool:
    return any(
        group.get("kind") == "mig_compute_instance"
        for group in value.get("resource_time", {}).get("gpu", {}).get("groups", [])
    )


def _table_metrics(metrics: list[str], show_mig: bool) -> list[str]:
    return metrics if show_mig else metrics[:-1]


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    values = [headers] + [[str(value) for value in row] for row in rows]
    widths = [max(len(row[index]) for row in values) for index in range(len(headers))]
    return ["  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip() for row in values]


def render_job_resources(summary: dict, participant: dict | None = None, *, job_name: str | None = None) -> str:
    participants = summary["participants"]
    sent_to, has_numeric_source, incomplete_sources = _incoming_traffic(participants)
    accepted = sum(entry["status"] == "accepted" for entry in participants)
    quality = "COMPLETE" if accepted == len(participants) else "PARTIAL"
    selected = participant.get("participant_name") if participant else None
    show_mig = (
        _has_mig(participant)
        if participant
        else any(entry["status"] == "accepted" and _has_mig(entry) for entry in participants)
    )
    visible_entries = [entry for entry in participants if not selected or entry["participant_name"] == selected]
    show_retained = any(entry["status"] == "accepted" and _has_retained_content(entry) for entry in visible_entries)
    # An addressed send from another participant remains useful even when the
    # selected participant's own report (and outbound counter) is missing.
    show_message_traffic = has_numeric_source
    title = f"job {job_name} (ID: {summary['job_id']})" if job_name else f"job ID {summary['job_id']}"
    lines = [f"Recorded resources for {title}."]
    coverage = f"Job coverage: {quality} ({accepted} accepted / {len(participants)} expected)"
    if selected:
        coverage += f" | selected site: {selected}"
    lines.extend([coverage, "", "Recorded average visible capacity over each measured interval"])

    rows = []
    for entry in visible_entries:
        if entry["status"] == "accepted":
            metrics = _table_metrics(_average_metrics(entry), show_mig)
        else:
            metrics = ["—", "—", "N/A", "N/A", "N/A"]
            if show_mig:
                metrics.append("N/A")
        rows.append([entry["participant_name"], entry["role"], entry["status"], *metrics])
    metric_headers = [
        "COMPUTE",
        "MEASURED TIME",
        "CPU UNITS",
        "MEM GiB",
        "FULL GPUs",
        "MIG INSTANCES",
    ]
    if not show_mig:
        metric_headers.remove("MIG INSTANCES")
    lines.extend(
        _table(
            ["SITE", "ROLE", "REPORT", *metric_headers],
            rows,
        )
    )
    if show_retained or show_message_traffic:
        other_headers = ["SITE"]
        if show_retained:
            other_headers.extend(["RUN-DIR STATUS", "RUN-DIR FILES GiB"])
        if show_message_traffic:
            other_headers.extend(
                ["MESSAGE TRAFFIC STATUS", "MESSAGE PAYLOAD SENT GiB", "MESSAGE PAYLOAD SENT TO SITE GiB"]
            )
        other_rows = []
        for entry in visible_entries:
            values = []
            if show_retained:
                values.extend(_other_metrics(entry, True, False) if entry["status"] == "accepted" else ["N/A", "N/A"])
            if show_message_traffic:
                values.extend(_other_metrics(entry, False, True) if entry["status"] == "accepted" else ["N/A", "N/A"])
                values.append(
                    _sent_to_site_display(sent_to, has_numeric_source, incomplete_sources, entry["participant_name"])
                )
            other_rows.append([entry["participant_name"], *values])
        lines.extend(["", "Other recorded participant totals", *_table(other_headers, other_rows)])
    if not selected:
        job_totals = derive_job_totals(participants)
        totals = _metrics(job_totals)
        resource_totals = [
            _quantity("CPU", totals[4], "unit h"),
            _quantity("MEMORY", totals[5], "GiB h"),
            _quantity("FULL GPUs", totals[2], "instance h"),
        ]
        if show_mig:
            resource_totals.append(_quantity("MIG INSTANCES", totals[3], "instance h"))
        lines.extend(
            [
                "",
                f"Additive participant resource-time from accepted reports | compute: {totals[0]}",
                f"  Summed measured participant time: {totals[1]}",
                "  " + " | ".join(resource_totals),
            ]
        )
        other_totals = _other_metrics(job_totals, show_retained, show_message_traffic)
        if other_totals:
            labels = []
            index = 0
            if show_retained:
                labels.append(f"RUN-DIR STATUS {other_totals[index]}")
                labels.append(_quantity("RUN-DIR FILES", other_totals[index + 1], "GiB"))
                index += 2
            if show_message_traffic:
                labels.append(f"MESSAGE TRAFFIC STATUS {other_totals[index]}")
                labels.append(_quantity("MESSAGE PAYLOAD SENT", other_totals[index + 1], "GiB"))
            lines.append("  Other additive totals: " + " | ".join(labels))
    lines.extend(
        [
            "",
            "Notes:",
            "  PARTIAL means at least one expected report or observation was incomplete.",
            "  Each average is resource-time divided by that row's measured interval.",
            "  Totals add participant reports; overlapping resources can be counted more than once.",
            "  Message payload sent to a site is sender-confirmed; it is not proof of receipt.",
        ]
    )
    if not selected:
        lines.append("  Use --site SITE or --format json to see hardware model details.")
    elif participant:
        lines.extend(
            [
                "",
                f"Hardware detail for {selected}",
                "Model metadata is optional and does not change numeric totals.",
                "",
            ]
        )
        resource_time = participant.get("resource_time", {})
        measured = resource_time.get("measured_seconds")
        cpu_parts = []
        for group in resource_time.get("cpu", {}).get("groups", []):
            label = group.get("model", "model unavailable")
            if group.get("architecture"):
                label += f" ({group['architecture']})"
            cpu_parts.append(f"{label}; {_average(group['unit_seconds'], measured)} average visible units")
        lines.append("CPU: " + ("; ".join(cpu_parts) if cpu_parts else "unavailable"))
        gpu_parts = []
        for group in resource_time.get("gpu", {}).get("groups", []):
            label = group.get("model", "model unavailable")
            if group.get("kind") == "mig_compute_instance":
                label = f"MIG compute instance: {label}"
                if group.get("mig_profile"):
                    label += f" ({group['mig_profile']})"
            if group.get("memory_bytes"):
                label += f", {_number(group['memory_bytes'], _GIB)} GiB per instance"
            gpu_parts.append(f"{label}; {_average(group['instance_seconds'], measured)} average visible instances")
        if gpu_parts:
            lines.append("GPU: " + "; ".join(gpu_parts))
        workspace = participant.get("workspace_filesystem", {})
        if workspace.get("status") == "reported":
            lines.append(
                "Visible workspace-filesystem capacity at reporting time: "
                f"{_number(workspace['capacity_bytes'], _GIB)} GiB"
            )
    return "\n".join(lines)


def render_study_resources(summary: dict) -> str:
    coverage = summary["coverage"]
    lines = [
        f"Resources recorded for finalized jobs in study {summary['selection']['study_name']}.",
        f"{coverage['selected_jobs']} jobs found | "
        f"{int(coverage['included_jobs']) + int(coverage['unavailable_jobs'])} finalized | "
        f"{coverage['included_jobs']} valid summaries | {coverage['unavailable_jobs']} unavailable | "
        f"{coverage['nonterminal_jobs']} still running (excluded)",
        "",
    ]
    show_mig = any(job["resource_data"] == "included" and _has_mig(job["totals"]) for job in summary["jobs"])
    show_retained = any(
        job["resource_data"] == "included" and _has_retained_content(job["totals"]) for job in summary["jobs"]
    )
    show_message_traffic = any(
        job["resource_data"] == "included" and _has_message_traffic(job["totals"]) for job in summary["jobs"]
    )
    rows = []
    for job in summary["jobs"]:
        if job["resource_data"] == "included":
            metrics = _metrics(job["totals"])
            quality = "COMPLETE" if metrics[0] == "REPORTED" else "PARTIAL"
            row_metrics = [quality, metrics[2]]
            if show_mig:
                row_metrics.append(metrics[3])
            row_metrics.extend(metrics[4:6])
            if show_retained:
                row_metrics.extend([job["totals"]["retained_content"]["status"].upper(), metrics[6]])
            if show_message_traffic:
                row_metrics.extend([job["totals"].get("message_traffic", {}).get("status", "—").upper(), metrics[7]])
        else:
            row_metrics = ["—", "N/A", "N/A", "N/A"]
            if show_mig:
                row_metrics.insert(2, "N/A")
            if show_retained:
                row_metrics.extend(["N/A", "N/A"])
            if show_message_traffic:
                row_metrics.extend(["N/A", "N/A"])
        rows.append([job["job_id"], job["job_name"], job["job_status"], job["resource_data"], *row_metrics])
    metric_headers = ["QUALITY", "FULL GPU h", "MIG h", "CPU unit h", "MEM GiB h"]
    if not show_mig:
        metric_headers.remove("MIG h")
    if show_retained:
        metric_headers.extend(["RUN-DIR STATUS", "RUN-DIR FILES GiB"])
    if show_message_traffic:
        metric_headers.extend(["MESSAGE TRAFFIC STATUS", "MESSAGE PAYLOAD SENT GiB"])
    lines.extend(
        _table(
            ["JOB ID", "NAME", "JOB STATUS", "RESOURCE DATA", *metric_headers],
            rows,
        )
    )
    totals = _metrics(summary["totals"])
    coverage_label = "COMPLETE" if int(coverage["included_jobs"]) == int(coverage["selected_jobs"]) else "PARTIAL"
    resource_totals = [
        _quantity("FULL GPUs", totals[2], "instance h"),
        _quantity("CPU", totals[4], "unit h"),
        _quantity("MEMORY", totals[5], "GiB h"),
    ]
    if show_mig:
        resource_totals.insert(1, _quantity("MIG INSTANCES", totals[3], "instance h"))
    lines.extend(
        [
            "",
            f"Study totals from {coverage['included_jobs']} valid job summaries | coverage: {coverage_label}",
            "  Additive participant resource-time: " + " | ".join(resource_totals),
            "",
            "Notes:",
            "  Totals include only finalized jobs with valid resource summaries.",
            "  This view includes only jobs still retained by the job store.",
        ]
    )
    other_totals = _other_metrics(summary["totals"], show_retained, show_message_traffic)
    if other_totals:
        labels = []
        index = 0
        if show_retained:
            labels.append(f"RUN-DIR STATUS {other_totals[index]}")
            labels.append(_quantity("RUN-DIR FILES", other_totals[index + 1], "GiB"))
            index += 2
        if show_message_traffic:
            labels.append(f"MESSAGE TRAFFIC STATUS {other_totals[index]}")
            labels.append(_quantity("MESSAGE PAYLOAD SENT", other_totals[index + 1], "GiB"))
        lines.insert(-4, "  Other additive totals: " + " | ".join(labels))
    return "\n".join(lines)
