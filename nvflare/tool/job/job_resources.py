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
_MISSING = "—"

_ISSUE_LABELS = {
    "not_bound": "not collected",
    "counter_gap": "some messages may be missing",
    "observation_incomplete": "observation incomplete",
    "attribution_incomplete": "some work could not be attributed",
    "unsupported": "not supported here",
    "permission_denied": "access denied",
    "dependency_missing": "required runtime unavailable",
    "malformed_source": "invalid source data",
}

_MEASUREMENT_LABELS = {
    "resource_time": "visible capacity",
    "cpu_consumed": "CPU time used",
    "retained_content": "run-dir files",
    "message_traffic": "message traffic",
}


def _accepted(entry: dict) -> bool:
    return "status" not in entry


def _metric_status(value: dict) -> str:
    return value.get("status", "reported")


def _number(value, divisor=Decimal(1)) -> str:
    if value is None:
        return _MISSING
    return f"{Decimal(value) / divisor:.4f}"


def _duration(value) -> str:
    if value is None:
        return _MISSING
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
        return _MISSING
    measured = Decimal(measured_seconds)
    if measured <= 0:
        return _MISSING
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
        traffic = source.get("message_traffic", {}) if _accepted(source) else {}
        if not _accepted(source) or _metric_status(traffic) != "reported":
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
        return _MISSING
    complete = not incomplete_sources or incomplete_sources == {participant_name}
    shown = _number(str(sent_to.get(participant_name, 0)), _GIB)
    return shown if complete else f"{shown}*"


def _marked(value: str, status: str | None) -> str:
    return f"{value}*" if value != _MISSING and status == "partial" else value


def _capacity_row(value: dict, show_mig: bool) -> list[str]:
    resource_time = value.get("resource_time", {})
    measured = resource_time.get("measured_seconds")
    status = _metric_status(resource_time)
    consumed = value.get("cpu_consumed", {})
    # A partial capacity observation can cover a different interval from the
    # process CPU counter. Dividing by it would invent an average.
    used = (
        _average(consumed.get("seconds"), measured)
        if status == "reported" and _metric_status(consumed) in {"reported", "partial"} and "seconds" in consumed
        else _MISSING
    )
    row = [
        _marked(_duration(measured), status),
        _marked(_average(_sum_group(resource_time, "cpu", "unit_seconds"), measured), status),
        _marked(used, _metric_status(consumed)),
        _marked(_average(resource_time.get("memory", {}).get("byte_seconds"), measured, _GIB), status),
        _marked(_average(_sum_group(resource_time, "gpu", "instance_seconds", "full_gpu"), measured), status),
    ]
    if show_mig:
        row.append(
            _marked(
                _average(_sum_group(resource_time, "gpu", "instance_seconds", "mig_compute_instance"), measured), status
            )
        )
    return row


def _has_retained_content(value: dict) -> bool:
    return value.get("retained_content", {}).get("bytes") is not None


def _has_message_traffic(value: dict) -> bool:
    return _sent_bytes(value) is not None


def _quantity(label: str, value: str, unit: str) -> str:
    return f"{label} {value}" if value == _MISSING else f"{label} {value} {unit}"


def _has_mig(value: dict) -> bool:
    return any(
        group.get("kind") == "mig_compute_instance"
        for group in value.get("resource_time", {}).get("gpu", {}).get("groups", [])
    )


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    values = [headers] + [[str(value) for value in row] for row in rows]
    widths = [max(len(row[index]) for row in values) for index in range(len(headers))]
    return ["  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip() for row in values]


def _issue_detail(value: dict) -> str:
    issues = value.get("issues", [])
    return "; ".join(_ISSUE_LABELS.get(issue, issue.replace("_", " ")) for issue in issues)


def _data_gaps(participants: list[dict]) -> list[str]:
    lines = []
    for entry in participants:
        name = entry["participant_name"]
        if not _accepted(entry):
            lines.append(f"  {name}: {entry['status']} report")
            continue
        gaps = []
        for field, label in _MEASUREMENT_LABELS.items():
            value = entry.get(field, {"status": "unavailable"})
            status = _metric_status(value)
            if status == "reported":
                continue
            if status == "error":
                status = "unavailable"
            detail = _issue_detail(value)
            gaps.append(f"{label} {status}" + (f" ({detail})" if detail else ""))
        if gaps:
            lines.append(f"  {name}: " + "; ".join(gaps))
    return lines


def _total_resource_quantities(totals: dict, show_mig: bool) -> list[str]:
    resource_time = totals["resource_time"]
    status = _metric_status(resource_time)
    quantities = [
        _quantity(
            "CPU visible", _marked(_number(_sum_group(resource_time, "cpu", "unit_seconds"), _HOUR), status), "core-h"
        ),
        _quantity(
            "Memory visible",
            _marked(_number(resource_time.get("memory", {}).get("byte_seconds"), _GIB * _HOUR), status),
            "GiB-h",
        ),
        _quantity(
            "Full GPUs visible",
            _marked(_number(_sum_group(resource_time, "gpu", "instance_seconds", "full_gpu"), _HOUR), status),
            "GPU-h",
        ),
    ]
    if show_mig:
        quantities.append(
            _quantity(
                "MIG instances visible",
                _marked(
                    _number(_sum_group(resource_time, "gpu", "instance_seconds", "mig_compute_instance"), _HOUR), status
                ),
                "instance-h",
            )
        )
    return quantities


def _total_other_quantities(totals: dict, show_retained: bool, show_message_traffic: bool) -> list[str]:
    consumed = totals["cpu_consumed"]
    quantities = [
        _quantity("CPU time used", _marked(_number(consumed.get("seconds"), _HOUR), _metric_status(consumed)), "core-h")
    ]
    if show_retained:
        retained = totals["retained_content"]
        quantities.append(
            _quantity("Run-dir files", _marked(_number(retained.get("bytes"), _GIB), _metric_status(retained)), "GiB")
        )
    if show_message_traffic:
        traffic = totals["message_traffic"]
        quantities.append(
            _quantity(
                "Message payload sent", _marked(_number(_sent_bytes(totals), _GIB), _metric_status(traffic)), "GiB"
            )
        )
    return quantities


def render_job_resources(summary: dict, participant: dict | None = None, *, job_name: str | None = None) -> str:
    participants = summary["participants"]
    sent_to, has_numeric_source, incomplete_sources = _incoming_traffic(participants)
    accepted = sum(_accepted(entry) for entry in participants)
    selected = participant.get("participant_name") if participant else None
    show_mig = (
        _has_mig(participant) if participant else any(_accepted(entry) and _has_mig(entry) for entry in participants)
    )
    visible_entries = [entry for entry in participants if not selected or entry["participant_name"] == selected]
    show_retained = any(_accepted(entry) and _has_retained_content(entry) for entry in visible_entries)
    # An addressed send from another participant remains useful even when the
    # selected participant's own report (and outbound counter) is missing.
    show_message_traffic = has_numeric_source
    title = f"job {job_name} (ID: {summary['job_id']})" if job_name else f"job ID {summary['job_id']}"
    lines = [f"Recorded resources for {title}."]
    coverage = f"Participants with data: {accepted}/{len(participants)}"
    if selected:
        coverage += f" | showing {selected}"
    lines.extend([coverage, "", "Average resources per participant (CPU in cores)"])

    rows = []
    for entry in visible_entries:
        metrics = _capacity_row(entry, show_mig) if _accepted(entry) else [_MISSING] * (6 if show_mig else 5)
        rows.append([entry["participant_name"], *metrics])
    metric_headers = [
        "TIME",
        "AVG CPU VISIBLE (cores)",
        "AVG CPU USED (cores)",
        "AVG MEM GiB",
        "AVG FULL GPUs",
    ]
    if show_mig:
        metric_headers.append("AVG MIG INSTANCES")
    lines.extend(_table(["SITE", *metric_headers], rows))
    if show_retained or show_message_traffic:
        other_headers = ["SITE"]
        if show_retained:
            other_headers.append("RUN-DIR FILES GiB")
        if show_message_traffic:
            other_headers.extend(["PAYLOAD SENT GiB", "PAYLOAD SENT TO SITE GiB"])
        other_rows = []
        for entry in visible_entries:
            values = []
            if show_retained:
                retained = entry.get("retained_content", {}) if _accepted(entry) else {}
                values.append(_marked(_number(retained.get("bytes"), _GIB), retained.get("status")))
            if show_message_traffic:
                traffic = entry.get("message_traffic", {}) if _accepted(entry) else {}
                values.append(_marked(_number(_sent_bytes(entry) if traffic else None, _GIB), traffic.get("status")))
                values.append(
                    _sent_to_site_display(sent_to, has_numeric_source, incomplete_sources, entry["participant_name"])
                )
            other_rows.append([entry["participant_name"], *values])
        lines.extend(["", "Recorded files and message payload", *_table(other_headers, other_rows)])
    if not selected:
        job_totals = derive_job_totals(participants)
        lines.extend(
            [
                "",
                "Sum of recorded participant values",
                "  " + " | ".join(_total_resource_quantities(job_totals, show_mig)),
                "  " + " | ".join(_total_other_quantities(job_totals, show_retained, show_message_traffic)),
            ]
        )
    gaps = _data_gaps(visible_entries)
    if selected and participant and "status" in participant.get("workspace_filesystem", {}):
        workspace = participant["workspace_filesystem"]
        detail = _issue_detail(workspace)
        gaps.append(f"  {selected}: workspace-filesystem capacity unavailable" + (f" ({detail})" if detail else ""))
    if gaps:
        lines.extend(["", "Data gaps:", *gaps])
    show_legend = any("*" in line or _MISSING in line for line in lines)
    lines.extend(["", "Notes:"])
    if show_legend:
        lines.append("  * = incomplete number; — = no usable value. See --format json for details.")
    lines.extend(
        [
            "  CPU visible is capacity; CPU used is process CPU time divided by a complete measured interval, not host utilization %.",
            "  CPU used may miss child-process work; known gaps are marked *.",
            "  Sums add participant values; physically shared resources may be counted more than once.",
            "  Payload sent to a site is sender-confirmed, not proof of receipt.",
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
        if workspace and "status" not in workspace:
            lines.append(
                "Visible workspace-filesystem capacity at reporting time: "
                f"{_number(workspace['capacity_bytes'], _GIB)} GiB"
            )
    return "\n".join(lines)


def render_study_resources(summary: dict) -> str:
    coverage = summary["coverage"]
    lines = [
        f"Resources recorded for finalized jobs in study {summary['selection']['study_name']}.",
        f"Jobs: {coverage['selected_jobs']} found | {coverage['included_jobs']} with resource data | "
        f"{coverage['unavailable_jobs']} without | {coverage['nonterminal_jobs']} still running (excluded)",
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
    gaps = []
    for job in summary["jobs"]:
        if job["resource_data"] == "included":
            totals = job["totals"]
            resource_time = totals["resource_time"]
            status = _metric_status(resource_time)
            row_metrics = [
                _marked(_number(_sum_group(resource_time, "gpu", "instance_seconds", "full_gpu"), _HOUR), status)
            ]
            if show_mig:
                row_metrics.append(
                    _marked(
                        _number(_sum_group(resource_time, "gpu", "instance_seconds", "mig_compute_instance"), _HOUR),
                        status,
                    )
                )
            row_metrics.extend(
                [
                    _marked(_number(_sum_group(resource_time, "cpu", "unit_seconds"), _HOUR), status),
                    _marked(_number(resource_time.get("memory", {}).get("byte_seconds"), _GIB * _HOUR), status),
                    _marked(
                        _number(totals["cpu_consumed"].get("seconds"), _HOUR), _metric_status(totals["cpu_consumed"])
                    ),
                ]
            )
            if show_retained:
                retained = totals["retained_content"]
                row_metrics.append(_marked(_number(retained.get("bytes"), _GIB), _metric_status(retained)))
            if show_message_traffic:
                traffic = totals["message_traffic"]
                row_metrics.append(_marked(_number(_sent_bytes(totals), _GIB), _metric_status(traffic)))
            incomplete = [
                f"{label} {'incomplete' if _metric_status(totals[field]) == 'partial' else 'unavailable'}"
                for field, label in _MEASUREMENT_LABELS.items()
                if _metric_status(totals[field]) != "reported"
            ]
            if incomplete:
                gaps.append(f"  {job['job_id']}: " + ", ".join(incomplete))
        else:
            row_metrics = [_MISSING] * (4 + int(show_mig) + int(show_retained) + int(show_message_traffic))
            reason = (
                "no valid resource summary" if job["resource_data"] == "unavailable" else "still running (excluded)"
            )
            gaps.append(f"  {job['job_id']}: {reason}")
        rows.append([job["job_id"], job["job_name"], job["job_status"], *row_metrics])
    metric_headers = ["FULL GPU-h", "MIG instance-h", "CPU VISIBLE core-h", "MEM VISIBLE GiB-h", "CPU USED core-h"]
    if not show_mig:
        metric_headers.remove("MIG instance-h")
    if show_retained:
        metric_headers.append("RUN-DIR GiB")
    if show_message_traffic:
        metric_headers.append("PAYLOAD SENT GiB")
    lines.extend(_table(["JOB ID", "NAME", "JOB STATUS", *metric_headers], rows))
    lines.extend(
        [
            "",
            f"Sum from {coverage['included_jobs']} {'job' if coverage['included_jobs'] == '1' else 'jobs'} with resource data",
            "  " + " | ".join(_total_resource_quantities(summary["totals"], show_mig)),
            "  " + " | ".join(_total_other_quantities(summary["totals"], show_retained, show_message_traffic)),
        ]
    )
    if gaps:
        lines.extend(["", "Data gaps:", *gaps])
    show_legend = any("*" in line or _MISSING in line for line in lines)
    lines.extend(["", "Notes:"])
    if show_legend:
        lines.append("  * = incomplete number; — = no usable value. See --format json for details.")
    lines.extend(
        [
            "  Sums include only finalized jobs with valid resource summaries and may count shared resources more than once.",
            "  CPU used is process CPU time, not visible CPU capacity or host utilization %.",
            "  This view includes only jobs still retained by the job store.",
        ]
    )
    return "\n".join(lines)
