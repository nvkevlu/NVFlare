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

import unicodedata
from decimal import Decimal

from nvflare.private.fed.resource_stats.contract import SCHEMA_VERSION, derive_job_totals

_GIB = Decimal(2**30)
_HOUR = Decimal(3600)
_MISSING = "—"

_ISSUE_LABELS = {
    "counter_gap": "some messages may be missing",
    "observation_incomplete": "part of the measurement could not be collected",
    "attribution_incomplete": "some work could not be assigned to this participant",
    "unsupported": "not supported here",
    "malformed_source": "measurement contained invalid values",
}

_MEASUREMENT_LABELS = {
    "resource_capacity": "visible capacity",
    "cpu_consumed": "CPU time used",
    "retained_content": "run-dir files",
    "message_traffic": "message traffic",
}
_TOTAL_MEASUREMENT_LABELS = {
    "resource_time": "visible capacity",
    **{key: label for key, label in _MEASUREMENT_LABELS.items() if key != "resource_capacity"},
}


def _terminal_label(value: str) -> str:
    """Show metadata literally without letting controls alter terminal output."""

    escaped = []
    for char in value:
        code = ord(char)
        if unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}:
            if char in {"\n", "\r", "\t"}:
                escaped.append({"\n": r"\n", "\r": r"\r", "\t": r"\t"}[char])
            elif code <= 0xFF:
                escaped.append(f"\\x{code:02x}")
            elif code <= 0xFFFF:
                escaped.append(f"\\u{code:04x}")
            else:
                escaped.append(f"\\U{code:08x}")
        else:
            escaped.append(char)
    return "".join(escaped)


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
        return str(sum(int(Decimal(group["payload_bytes"])) for group in traffic["sent_to"]))
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
            sent_to[name] = sent_to.get(name, 0) + int(Decimal(group["payload_bytes"]))
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


def _resource_measurement(value: dict) -> dict:
    """Select participant capacity or transient query-derived capacity-time."""

    return value.get("resource_capacity", value.get("resource_time", {}))


def _capacity_observations(value: dict) -> list[dict]:
    measurement = _resource_measurement(value)
    return measurement.get("intervals", [measurement])


def _observed_capacity(value: dict, resource: str, kind: str | None = None) -> str:
    capacities = []
    for observation in _capacity_observations(value):
        capacity = (
            observation.get("memory", {}).get("bytes")
            if resource == "memory"
            else _sum_group(observation, resource, "units" if resource == "cpu" else "count", kind)
        )
        if capacity is None:
            return _MISSING
        capacities.append(Decimal(capacity))
    if not capacities:
        return _MISSING
    if len(set(capacities)) > 1:
        return "varies"
    return _number(capacities[0], _GIB if resource == "memory" else Decimal(1))


def _capacity_row(value: dict, show_mig: bool, show_unclassified: bool) -> list[str]:
    measurement = _resource_measurement(value)
    measured = measurement.get("measured_seconds")
    status = _metric_status(measurement)
    consumed = value.get("cpu_consumed", {})
    # CPU consumption has its own clock. A capacity/GPU collection failure
    # cannot invalidate that clock or supply a replacement duration.
    cpu_measured = consumed.get("measured_seconds")
    used = (
        _average(consumed.get("seconds"), cpu_measured)
        if _metric_status(consumed) in {"reported", "partial"} and "seconds" in consumed
        else _MISSING
    )
    row = [
        _marked(_duration(measured), status),
        _marked(_observed_capacity(value, "cpu"), status),
        _marked(used, _metric_status(consumed)),
        _marked(_observed_capacity(value, "memory"), status),
        _marked(_observed_capacity(value, "gpu"), status),
        _marked(_observed_capacity(value, "gpu", "full_gpu"), status),
    ]
    if show_mig:
        row.append(_marked(_observed_capacity(value, "gpu", "mig_compute_instance"), status))
    if show_unclassified:
        row.append(_marked(_observed_capacity(value, "gpu", "cuda_device_unclassified"), status))
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
        for observation in _capacity_observations(value)
        for group in observation.get("gpu", {}).get("groups", [])
    )


def _has_unclassified(value: dict) -> bool:
    return any(
        group.get("kind") == "cuda_device_unclassified"
        for observation in _capacity_observations(value)
        for group in observation.get("gpu", {}).get("groups", [])
    )


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    values = [headers] + [[str(value) for value in row] for row in rows]
    widths = [max(len(row[index]) for row in values) for index in range(len(headers))]
    return ["  ".join(value.ljust(widths[index]) for index, value in enumerate(row)).rstrip() for row in values]


def _issue_detail(value: dict, field: str) -> str:
    issues = value.get("issues", [])
    labels = dict(_ISSUE_LABELS)
    if field == "resource_capacity":
        observations = value.get("intervals", [value])
        missing = [
            label
            for resource, label in (("cpu", "CPU"), ("memory", "RAM"), ("gpu", "GPU"))
            if any(resource not in observation for observation in observations)
        ]
        labels["observation_incomplete"] = (
            f"{', '.join(missing)} capacity could not be observed for the whole interval"
            if missing
            else "some limits or earlier observations could not be checked; capacity may be overstated"
        )
        labels["attribution_incomplete"] = "some capacity observations could not be assigned to this participant"
    elif field == "cpu_consumed":
        labels["observation_incomplete"] = "part of the CPU measurement interval is missing"
        labels["attribution_incomplete"] = "some child-process CPU time may be missing"
    elif field == "retained_content":
        labels["observation_incomplete"] = "the file scan stopped early or could not read every file"
        labels["attribution_incomplete"] = "some files could not be assigned to this participant"
    elif field == "message_traffic":
        labels["observation_incomplete"] = "some message counters were unavailable"
        labels["attribution_incomplete"] = "some message traffic could not be assigned to this participant"
        labels["counter_gap"] = "some accepted messages or tensor bytes may be missing"
    elif field == "workspace_filesystem":
        labels["observation_incomplete"] = "the workspace filesystem capacity could not be read"
    return "; ".join(labels.get(issue, issue.replace("_", " ")) for issue in issues)


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
            detail = _issue_detail(value, field)
            if status == "partial":
                gaps.append(f"{label}: {detail or 'some values may be missing'}")
            else:
                gaps.append(f"{label} unavailable" + (f" ({detail})" if detail else ""))
        if gaps:
            lines.append(f"  {name}: " + "; ".join(gaps))
    return lines


def _total_resource_quantities(totals: dict, show_mig: bool, show_unclassified: bool) -> list[str]:
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
            "CUDA devices available",
            _marked(_number(_sum_group(resource_time, "gpu", "instance_seconds"), _HOUR), status),
            "device-h",
        ),
        _quantity(
            "Verified full GPUs",
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
    if show_unclassified:
        quantities.append(
            _quantity(
                "Type-unverified CUDA devices",
                _marked(
                    _number(_sum_group(resource_time, "gpu", "instance_seconds", "cuda_device_unclassified"), _HOUR),
                    status,
                ),
                "device-h",
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


def _hardware_detail(participant: dict) -> list[str]:
    measurement = _resource_measurement(participant)
    if "intervals" in measurement:
        return [
            f"Capacity observations span {len(measurement['intervals'])} recorded intervals.",
            "See --format json for each interval's capacity and hardware details.",
        ]
    cpu_parts = []
    for group in measurement.get("cpu", {}).get("groups", []):
        label = group.get("model", "model unavailable")
        if group.get("architecture"):
            label += f" ({group['architecture']})"
        cpu_parts.append(f"{label}; {_number(group['units'])} visible units")
    lines = ["CPU: " + ("; ".join(cpu_parts) if cpu_parts else "unavailable")]
    gpu_parts = []
    for group in measurement.get("gpu", {}).get("groups", []):
        label = group.get("model", "model unavailable")
        if group.get("kind") == "mig_compute_instance":
            label = f"MIG compute instance: {label}"
            if group.get("mig_profile"):
                label += f" ({group['mig_profile']})"
        elif group.get("kind") == "cuda_device_unclassified":
            label = f"CUDA device, type unverified: {label}"
        if group.get("memory_bytes"):
            label += f", {_number(group['memory_bytes'], _GIB)} GiB per instance"
        gpu_parts.append(f"{label}; {_number(group['count'])} visible instances")
    if gpu_parts:
        lines.append("GPU: " + "; ".join(gpu_parts))
    return lines


def render_job_resources(summary: dict, participant: dict | None = None, *, job_name: str | None = None) -> str:
    participants = sorted(summary["participants"], key=lambda entry: (entry["role"], entry["participant_name"]))
    sent_to, has_numeric_source, incomplete_sources = _incoming_traffic(participants)
    accepted = sum(_accepted(entry) for entry in participants)
    selected = participant.get("participant_name") if participant else None
    show_mig = (
        _has_mig(participant) if participant else any(_accepted(entry) and _has_mig(entry) for entry in participants)
    )
    show_unclassified = (
        _has_unclassified(participant)
        if participant
        else any(_accepted(entry) and _has_unclassified(entry) for entry in participants)
    )
    visible_entries = [entry for entry in participants if not selected or entry["participant_name"] == selected]
    show_retained = any(_accepted(entry) and _has_retained_content(entry) for entry in visible_entries)
    # An addressed send from another participant remains useful even when the
    # selected participant's own report (and outbound counter) is missing.
    show_message_traffic = has_numeric_source
    title = f"job {_terminal_label(job_name)} (ID: {summary['job_id']})" if job_name else f"job ID {summary['job_id']}"
    lines = [f"Recorded resources for {title}.", f"GPU count basis: CUDA Driver (schema {SCHEMA_VERSION})."]
    coverage = f"Participants with data: {accepted}/{len(participants)}"
    if selected:
        coverage += f" | showing {selected}"
    lines.extend([coverage, "", "Observed resources per participant (CPU in cores)"])

    rows = []
    for entry in visible_entries:
        metrics = (
            _capacity_row(entry, show_mig, show_unclassified)
            if _accepted(entry)
            else [_MISSING] * (6 + int(show_mig) + int(show_unclassified))
        )
        rows.append([entry["participant_name"], *metrics])
    metric_headers = [
        "TIME",
        "CPU VISIBLE (cores)",
        "AVG CPU USED (cores)",
        "MEM GiB",
        "CUDA DEVICES",
        "VERIFIED FULL GPUs",
    ]
    if show_mig:
        metric_headers.append("MIG INSTANCES")
    if show_unclassified:
        metric_headers.append("TYPE-UNVERIFIED")
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
                "Derived capacity-time totals",
                "  " + " | ".join(_total_resource_quantities(job_totals, show_mig, show_unclassified)),
                "  " + " | ".join(_total_other_quantities(job_totals, show_retained, show_message_traffic)),
            ]
        )
    gaps = _data_gaps(visible_entries)
    if selected and participant and "status" in participant.get("workspace_filesystem", {}):
        workspace = participant["workspace_filesystem"]
        detail = _issue_detail(workspace, "workspace_filesystem")
        gaps.append(f"  {selected}: workspace-filesystem capacity unavailable" + (f" ({detail})" if detail else ""))
    if gaps:
        lines.extend(["", "Data gaps:", *gaps])
    show_legend = any("*" in line or _MISSING in line for line in lines)
    if show_legend:
        lines.extend(["", "* = incomplete; — = unavailable."])
    if any("varies" in cell for row in rows for cell in row[1:]):
        lines.extend(["", "varies = capacity changed; see --format json."])
    if selected and participant:
        lines.extend(
            [
                "",
                f"Hardware detail for {selected}",
                "",
            ]
        )
        lines.extend(_hardware_detail(participant))
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
        f"{coverage['unavailable_jobs']} without | {coverage['nonterminal_jobs']} not finalized (excluded)",
        "",
    ]
    show_mig = any(job["resource_data"] == "included" and _has_mig(job["totals"]) for job in summary["jobs"])
    show_unclassified = any(
        job["resource_data"] == "included" and _has_unclassified(job["totals"]) for job in summary["jobs"]
    )
    show_retained = any(
        job["resource_data"] == "included" and _has_retained_content(job["totals"]) for job in summary["jobs"]
    )
    show_message_traffic = any(
        job["resource_data"] == "included" and _has_message_traffic(job["totals"]) for job in summary["jobs"]
    )
    rows = []
    gaps = []
    for job in sorted(summary["jobs"], key=lambda job: job["job_id"]):
        if job["resource_data"] == "included":
            totals = job["totals"]
            resource_time = totals["resource_time"]
            status = _metric_status(resource_time)
            row_metrics = [
                _marked(_number(_sum_group(resource_time, "gpu", "instance_seconds"), _HOUR), status),
                _marked(_number(_sum_group(resource_time, "gpu", "instance_seconds", "full_gpu"), _HOUR), status),
            ]
            if show_mig:
                row_metrics.append(
                    _marked(
                        _number(_sum_group(resource_time, "gpu", "instance_seconds", "mig_compute_instance"), _HOUR),
                        status,
                    )
                )
            if show_unclassified:
                row_metrics.append(
                    _marked(
                        _number(
                            _sum_group(resource_time, "gpu", "instance_seconds", "cuda_device_unclassified"),
                            _HOUR,
                        ),
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
                for field, label in _TOTAL_MEASUREMENT_LABELS.items()
                if _metric_status(totals[field]) != "reported"
            ]
            if incomplete:
                gaps.append(f"  {job['job_id']}: " + ", ".join(incomplete))
        else:
            row_metrics = [_MISSING] * (
                5 + int(show_mig) + int(show_unclassified) + int(show_retained) + int(show_message_traffic)
            )
            reason = (
                "no valid resource summary" if job["resource_data"] == "unavailable" else "not finalized (excluded)"
            )
            gaps.append(f"  {job['job_id']}: {reason}")
        rows.append([job["job_id"], _terminal_label(job["job_name"]), job["job_status"], *row_metrics])
    metric_headers = [
        "CUDA DEVICE-h",
        "FULL GPU-h",
        "MIG instance-h",
        "TYPE-UNVERIFIED device-h",
        "CPU VISIBLE core-h",
        "MEM VISIBLE GiB-h",
        "CPU USED core-h",
    ]
    if not show_mig:
        metric_headers.remove("MIG instance-h")
    if not show_unclassified:
        metric_headers.remove("TYPE-UNVERIFIED device-h")
    if show_retained:
        metric_headers.append("RUN-DIR GiB")
    if show_message_traffic:
        metric_headers.append("PAYLOAD SENT GiB")
    lines.extend(_table(["JOB ID", "NAME", "JOB STATUS", *metric_headers], rows))
    lines.extend(["", "Derived capacity-time totals"])
    if any(job["resource_data"] == "included" for job in summary["jobs"]):
        totals = summary["totals"]
        lines.extend(
            [
                "  " + " | ".join(_total_resource_quantities(totals, _has_mig(totals), _has_unclassified(totals))),
                "  "
                + " | ".join(
                    _total_other_quantities(totals, _has_retained_content(totals), _has_message_traffic(totals))
                ),
            ]
        )
    else:
        lines.append("  No jobs with resource data")
    if gaps:
        lines.extend(["", "Data gaps:", *gaps])
    show_legend = any("*" in line or _MISSING in line for line in lines)
    if show_legend:
        lines.extend(["", "* = incomplete; — = unavailable."])
    return "\n".join(lines)
