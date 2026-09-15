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

"""Generate realistic, self-contained pre-v1 probe artifacts.

The generator intentionally records what it can actually observe on the local
machine and marks unbound NVFlare-only signals (currently F3 traffic) as
unavailable.  It never fabricates a GPU, server process, or network counter.

Its exploratory record shapes predate the canonical v1
contract and deliberately remain historical probe evidence.  Use
``schema/build_review_artifacts.py`` for normative records and CLI output.
The retained-content probe measures only the one file this script creates and
does not claim to discover a complete NVFlare result set.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import stat
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from prototype_contract import FixedResourceStatsStore
from review_contract_fixtures import write_review_contract_fixtures
from runtime_probe import probe_cpu, probe_gpu, probe_memory, probe_storage


RESOURCE_SCHEMA_VERSION = "prototype-local-0.3"
CLI_SCHEMA_VERSION = "1"
PROTOTYPE_KIND = "runtime_resource_proxy_prototype"


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _write_json(path: Path, value: Any) -> bytes:
    data = _json_bytes(value)
    _write_bytes_atomic(path, data)
    return data


def _metric(
    name: str,
    value: int | float | None,
    unit: str,
    source: str,
    *,
    basis: str,
    scope: str,
    status: str,
    coverage: str,
    observed_at: str,
    caveat_codes: list[str],
    sharing: str = "unknown",
    reason_code: str | None = None,
    dimensions: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "value": value,
        "unit": unit,
        "source": source,
        "basis": basis,
        "scope": scope,
        "sharing": sharing,
        "status": status,
        "observed_at": observed_at,
        "coverage": coverage,
        "caveat_codes": caveat_codes,
    }
    if reason_code:
        result["reason_code"] = reason_code
    if dimensions:
        result["dimensions"] = dimensions
    if evidence:
        result["evidence"] = evidence
    return result


def _record_status(metrics: Iterable[dict[str, Any]]) -> str:
    metric_statuses = {metric["status"] for metric in metrics}
    if not metric_statuses:
        return "unavailable"
    if metric_statuses == {"reported"}:
        return "reported"
    if metric_statuses == {"unavailable"}:
        return "unavailable"
    return "partial"


def _canonical_probe_metric(metric: dict[str, Any], observed_at: str) -> dict[str, Any]:
    """Normalize probe output into the persisted contract without changing values."""

    result = copy.deepcopy(metric)
    result["observed_at"] = observed_at
    if "inputs" in result:
        result["evidence"] = result.pop("inputs")
    return result


def _collect_capacity_snapshot(run_dir: Path, observed_at: str) -> dict[str, Any]:
    metrics = [
        probe_cpu(allow_host_fallback=True),
        probe_memory(allow_host_fallback=True),
        probe_storage(run_dir),
        probe_gpu(),
    ]
    return {
        "observed_at": observed_at,
        "metrics": [_canonical_probe_metric(metric, observed_at) for metric in metrics],
    }


def _metric_by_name(metrics: Iterable[dict[str, Any]], name: str) -> dict[str, Any]:
    for metric in metrics:
        if metric["name"] == name:
            return metric
    raise KeyError(name)


def _capacity_changed(start: dict[str, Any], final: dict[str, Any]) -> bool:
    final_by_name = {metric["name"]: metric for metric in final["metrics"]}
    for metric in start["metrics"]:
        if metric["name"] == "visible_storage_capacity_bytes":
            continue
        final_metric = final_by_name.get(metric["name"])
        if final_metric is None or final_metric["value"] != metric["value"]:
            return True
    return False


def _proxy_rollup(
    start_metric: dict[str, Any],
    duration_seconds: float,
    *,
    name: str,
    unit: str,
    observed_at: str,
) -> dict[str, Any]:
    if start_metric["status"] not in {"reported", "partial"} or start_metric["value"] is None:
        return _metric(
            name,
            None,
            unit,
            f"startup.{start_metric['name']}*interval.duration_seconds",
            basis="runtime_visible_capacity_proxy",
            scope=start_metric["scope"],
            sharing=start_metric["sharing"],
            status="unavailable",
            coverage=start_metric["coverage"],
            observed_at=observed_at,
            caveat_codes=list(start_metric["caveat_codes"]),
            reason_code="STARTUP_CAPACITY_UNAVAILABLE",
        )
    result = _metric(
        name,
        start_metric["value"] * duration_seconds,
        unit,
        f"startup.{start_metric['name']}*interval.duration_seconds",
        basis="runtime_visible_capacity_proxy",
        scope=start_metric["scope"],
        sharing=start_metric["sharing"],
        status=start_metric["status"],
        coverage=start_metric["coverage"],
        observed_at=observed_at,
        caveat_codes=list(start_metric["caveat_codes"]),
    )
    if "dimensions" in start_metric:
        result["dimensions"] = copy.deepcopy(start_metric["dimensions"])
    return result


def _retained_content_metric(result_file: Path, observed_at: str) -> dict[str, Any]:
    if result_file.is_symlink() or not result_file.is_file():
        raise RuntimeError("prototype artifact registry must contain regular files only")
    with result_file.open("rb") as stream:
        result_stat = os.fstat(stream.fileno())
    if not stat.S_ISREG(result_stat.st_mode):
        raise RuntimeError("prototype artifact registry must contain regular files only")
    metric = _metric(
        "retained_content_bytes",
        result_stat.st_size,
        "bytes",
        "prototype_owned_file+fstat.st_size",
        basis="retained_content_bytes",
        scope="prototype_owned_file_only",
        sharing="unknown",
        status="partial",
        coverage="partial",
        observed_at=observed_at,
        caveat_codes=["PROTOTYPE_OWNED_FILE_ONLY", "NOT_COMPLETE_NVFLARE_RESULT_SET"],
    )
    return metric


def _unbound_network(observed_at: str) -> dict[str, Any]:
    unavailable_metric = _metric(
        "f3_payload_bytes_sent",
        None,
        "bytes",
        "cellnet.sender_boundary.after_optional_cell_encryption",
        basis="application_payload_counter",
        scope="outbound_sender_hop",
        sharing="unknown",
        status="unavailable",
        coverage="none",
        observed_at=observed_at,
        caveat_codes=["F3_COUNTER_NOT_BOUND_IN_PROTOTYPE"],
        reason_code="F3_COUNTER_NOT_BOUND",
    )
    message_metric = copy.deepcopy(unavailable_metric)
    message_metric.update({"name": "f3_message_count_sent", "unit": "messages"})
    return {
        "counter_epoch": uuid.uuid4().hex,
        "observed_at": observed_at,
        "frozen_before_summary_publication": True,
        "outcomes": {
            "remote_transport_accepted": {
                "payload_bytes": None,
                "message_count": None,
                "status": "unavailable",
                "coverage": "none",
                "reason_code": "F3_COUNTER_NOT_BOUND",
            },
            "local_delivery": {
                "payload_bytes": None,
                "message_count": None,
                "status": "unavailable",
                "coverage": "none",
                "reason_code": "F3_COUNTER_NOT_BOUND",
            },
            "pre_transport_failure": {
                "payload_bytes": None,
                "message_count": None,
                "status": "unavailable",
                "coverage": "none",
                "reason_code": "F3_COUNTER_NOT_BOUND",
            },
        },
        "metrics": [unavailable_metric, message_metric],
    }


def _summarize_attempt(attempt_final: dict[str, Any]) -> dict[str, Any]:
    return {
        "attempt_id": attempt_final["attempt_id"],
        "execution_scope": copy.deepcopy(attempt_final["execution_scope"]),
        "interval": copy.deepcopy(attempt_final["interval"]),
        "startup_snapshot": copy.deepcopy(attempt_final["startup_snapshot"]),
        "final_snapshot": copy.deepcopy(attempt_final["final_snapshot"]),
        "retained_content": copy.deepcopy(attempt_final["retained_content"]),
        "network": copy.deepcopy(attempt_final["network"]),
        "rollups": copy.deepcopy(attempt_final["rollups"]),
    }


def _qualified_totals(
    participant_summary: dict[str, Any],
    observed_at: str,
    expected_participant_count: int,
    missing_participant_ids: list[str],
) -> dict[str, Any]:
    attempts = participant_summary["attempts"]
    rollups = [metric for attempt in attempts for metric in attempt["rollups"]]
    retained = [metric for attempt in attempts for metric in attempt["retained_content"]["metrics"]]
    network = [metric for attempt in attempts for metric in attempt["network"]["metrics"]]
    metrics: list[dict[str, Any]] = []
    for name in (
        "visible_gpu_seconds",
        "visible_cpu_unit_seconds",
        "visible_memory_byte_seconds",
        "retained_content_bytes",
        "f3_payload_bytes_sent",
        "f3_message_count_sent",
    ):
        candidates = [metric for metric in rollups + retained + network if metric["name"] == name]
        if not candidates:
            continue
        statuses = {metric["status"] for metric in candidates}
        values = [metric["value"] for metric in candidates if metric["value"] is not None]
        exemplar = candidates[0]
        contribution_is_complete = len(values) == len(candidates)
        contributing_participant_count = 1 if contribution_is_complete else 0
        missing_participant_count = expected_participant_count - contributing_participant_count
        noncontributing_participant_ids = list(missing_participant_ids)
        if not contribution_is_complete:
            noncontributing_participant_ids.insert(0, participant_summary["participant_id"])
        if not contribution_is_complete:
            status = "unavailable"
            coverage = "none"
        elif missing_participant_count:
            status = "partial"
            coverage = "partial"
        elif statuses == {"reported"}:
            status = "reported"
            coverage = "complete"
        else:
            status = "partial"
            coverage = "partial"
        metric = _metric(
            name,
            sum(values) if contribution_is_complete else None,
            exemplar["unit"],
            "sum(participant_attempt_metrics)",
            basis=exemplar["basis"],
            scope="all_reported_participants",
            sharing="unknown",
            status=status,
            coverage=coverage,
            observed_at=observed_at,
            caveat_codes=[
                "PARTICIPANT_VISIBLE_PROXY_SUM",
                "SHARED_PHYSICAL_CAPACITY_MAY_BE_REPRESENTED_MORE_THAN_ONCE",
            ],
        )
        metric["contribution_coverage"] = {
            "expected_participant_count": expected_participant_count,
            "contributing_participant_count": contributing_participant_count,
            "missing_participant_count": missing_participant_count,
            "missing_participant_ids": noncontributing_participant_ids if missing_participant_count else [],
        }
        metrics.append(metric)
    return {
        "scope": "all_reported_participants",
        "qualification_codes": [
            "PARTICIPANT_VISIBLE_PROXY_SUM",
            "SHARED_PHYSICAL_CAPACITY_MAY_BE_REPRESENTED_MORE_THAN_ONCE",
        ],
        "metrics": metrics,
    }


def _human_bytes(value: int | float | None) -> str:
    if value is None:
        return "N/A"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(value)
    for unit in units:
        if abs(amount) < 1024 or unit == units[-1]:
            return f"{amount:.2f} {unit}"
        amount /= 1024
    raise AssertionError("unreachable")


def _human_hours(value: int | float | None, divisor: float = 3600.0) -> str:
    return "N/A" if value is None else f"{float(value) / divisor:.4f}"


def _human_duration(value: float) -> str:
    if value < 60:
        return f"{value:.3f}s"
    minutes, seconds = divmod(round(value), 60)
    return f"{minutes}m{seconds:02d}s"


def _find_metric(metrics: Iterable[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((metric for metric in metrics if metric["name"] == name), None)


def _human_row(participant: dict[str, Any]) -> str:
    report_status = participant.get("report_status", participant.get("status"))
    if report_status in {"missing", "invalid", "disabled"}:
        coverage = "missing" if report_status == "missing" else report_status
        return (
            f"{participant['participant_id']:<24} {participant['role']:<7} {report_status:<11} {'—':>10} "
            f"{'N/A':>7} {'N/A':>7} {'N/A':>11} {'N/A':>12} {'N/A':>12} {coverage}"
        )
    attempt = participant["attempts"][0]
    rollups = attempt["rollups"]
    retained = _find_metric(attempt["retained_content"]["metrics"], "retained_content_bytes")
    network = _find_metric(attempt["network"]["metrics"], "f3_payload_bytes_sent")
    gpu = _find_metric(rollups, "visible_gpu_seconds")
    cpu = _find_metric(rollups, "visible_cpu_unit_seconds")
    memory = _find_metric(rollups, "visible_memory_byte_seconds")
    coverage = _record_status(rollups + [retained, network])
    return (
        f"{participant['participant_id']:<24} {participant['role']:<7} "
        f"{participant.get('collection_status', participant['status']):<11} "
        f"{_human_duration(attempt['interval']['duration_seconds']):>10} "
        f"{_human_hours(gpu['value'] if gpu else None):>7} "
        f"{_human_hours(cpu['value'] if cpu else None):>7} "
        f"{_human_hours(memory['value'] if memory else None, 1024**3 * 3600):>11} "
        f"{_human_bytes(retained['value'] if retained else None):>12} "
        f"{_human_bytes(network['value'] if network else None):>12} {coverage}"
    )


def _human_all_sites(summary: dict[str, Any]) -> str:
    coverage = summary["coverage"]
    lines = [
        "Runtime-visible capacity proxies; not allocations, reservations, guarantees, or billable usage.",
        (
            f"Job {summary['job']['id']} | study {summary['job']['study']} | "
            f"resource summary: {coverage['state'].upper()} "
            f"({coverage['reported_participant_count']} reported / {coverage['expected_participant_count']} expected)"
        ),
        "",
        (
            "SITE                     ROLE    STATUS        DURATION   GPU h   CPU h   MEM GiB h "
            "    RETAINED     F3 BYTES COVERAGE"
        ),
    ]
    lines.extend(_human_row(participant) for participant in summary["participants"])
    totals = {metric["name"]: metric for metric in summary["qualified_totals"]["metrics"]}
    memory_hours = _human_hours(totals.get("visible_memory_byte_seconds", {}).get("value"), 1024**3 * 3600)
    lines.extend(
        [
            "",
            "Qualified all-site totals (reported participants only):",
            (
                f"  GPU {_human_hours(totals.get('visible_gpu_seconds', {}).get('value'))} h | "
                f"CPU {_human_hours(totals.get('visible_cpu_unit_seconds', {}).get('value'))} h | "
                f"Memory {memory_hours} GiB h"
            ),
            (
                f"  Retained {_human_bytes(totals.get('retained_content_bytes', {}).get('value'))} | "
                f"F3 {_human_bytes(totals.get('f3_payload_bytes_sent', {}).get('value'))}"
            ),
        ]
    )
    lines.extend(f"Warning: {warning}" for warning in summary["warnings"])
    return "\n".join(lines) + "\n"


def _cli_ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": CLI_SCHEMA_VERSION, "status": "ok", "exit_code": 0, "data": data}


def _cli_error(
    error_code: str,
    message: str,
    hint: str,
    *,
    exit_code: int = 1,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": CLI_SCHEMA_VERSION,
        "status": "error",
        "exit_code": exit_code,
        "error_code": error_code,
        "message": message,
        "hint": hint,
    }
    if data is not None:
        result["data"] = data
    return result


def _human_error(envelope: dict[str, Any]) -> str:
    return f"ERROR [{envelope['error_code']}]: {envelope['message']}\nHint: {envelope['hint']}\n"


def _cli_all_data(summary: dict[str, Any]) -> dict[str, Any]:
    participant_ids = [participant["participant_id"] for participant in summary["participants"]]
    return {
        "kind": "nvflare.job_resources",
        "job_id": summary["job"]["id"],
        "study": summary["job"]["study"],
        "resource_summary_schema_version": summary["schema_version"],
        "selection": {"site": "all", "participant_ids": participant_ids, "is_job_total": True},
        "finalization": copy.deepcopy(summary["finalization"]),
        "collection": copy.deepcopy(summary["collection"]),
        "coverage": copy.deepcopy(summary["coverage"]),
        "participants": copy.deepcopy(summary["participants"]),
        "qualified_totals": copy.deepcopy(summary["qualified_totals"]),
        "warnings": copy.deepcopy(summary["warnings"]),
    }


def _cli_selected_data(summary: dict[str, Any], participant_id: str) -> dict[str, Any]:
    participant = next(item for item in summary["participants"] if item["participant_id"] == participant_id)
    if participant.get("report_status") != "accepted":
        rollup = {"metrics": []}
    else:
        attempt = participant["attempts"][0]
        rollup = {
            "metrics": copy.deepcopy(
                attempt["rollups"] + attempt["retained_content"]["metrics"] + attempt["network"]["metrics"]
            )
        }
    return {
        "kind": "nvflare.job_resources",
        "job_id": summary["job"]["id"],
        "study": summary["job"]["study"],
        "resource_summary_schema_version": summary["schema_version"],
        "selection": {"site": participant_id, "participant_ids": [participant_id], "is_job_total": False},
        "finalization": copy.deepcopy(summary["finalization"]),
        "collection": copy.deepcopy(summary["collection"]),
        "status": participant.get("collection_status", participant.get("status")),
        "coverage": {
            "state": "complete" if participant.get("report_status") == "accepted" else "partial",
            "expected_participant_count": 1,
            "reported_participant_count": 1 if participant.get("report_status") == "accepted" else 0,
            "missing": [] if participant.get("report_status") == "accepted" else [{"participant_id": participant_id}],
            "invalid": [],
            "disabled": [],
        },
        "participant": copy.deepcopy(participant),
        "selected_participant_totals": rollup,
        "warnings": ["Selected-site rollup is not a job total."],
    }


def _write_manifest(resource_dir: Path) -> dict[str, Any]:
    files = sorted(path for path in resource_dir.rglob("*.json") if path.name != "manifest.json")
    entries = []
    for path in files:
        relative_path = path.relative_to(resource_dir).as_posix()
        entries.append(
            {"relative_path": relative_path, "byte_count": path.stat().st_size, "sha256": _sha256_file(path)}
        )
    return {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "kind": "nvflare.resource_stats.manifest",
        "record_type": "resource_stats_manifest",
        "entries": entries,
    }


def generate(output_dir: Path, job_id: str, study: str, observation_seconds: float) -> dict[str, Any]:
    if observation_seconds < 0:
        raise ValueError("observation_seconds must be non-negative")

    client_resource_dir = output_dir / "client_run" / "resource_stats"
    server_resource_dir = output_dir / "server_run" / "resource_stats"
    result_dir = output_dir / "result_artifacts"
    cli_dir = output_dir / "cli"
    job_store_dir = output_dir / "job_store"
    client_resource_dir.mkdir(parents=True, exist_ok=True)
    server_resource_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    cli_dir.mkdir(parents=True, exist_ok=True)
    job_store_dir.mkdir(parents=True, exist_ok=True)

    participant_id = "local-prototype-client"
    role = "client"
    attempt_id = uuid.uuid4().hex
    summary_id = str(uuid.uuid4())
    scope_id = f"scope-{uuid.uuid4().hex[:16]}"
    participant_key = f"sha256:{_sha256(f'{role}:{participant_id}'.encode())}"

    started_at = _utc_now()
    started_monotonic = time.monotonic()
    start_snapshot = _collect_capacity_snapshot(client_resource_dir.parent, started_at)
    start_record = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "kind": "nvflare.resource_stats.attempt_start",
        "record_type": "resource_attempt_start",
        "job_id": job_id,
        "participant_id": participant_id,
        "role": role,
        "attempt_id": attempt_id,
        "execution_scope": {"id": scope_id, "coverage": "current_environment_only"},
        "snapshot": start_snapshot,
        "collection": {"implementation": PROTOTYPE_KIND, "mode": "host_fallback_prototype"},
    }
    start_path = client_resource_dir / "attempts" / attempt_id / "start.json"
    start_bytes = _write_json(start_path, start_record)

    result_payload = {
        "kind": "prototype_owned_result",
        "job_id": job_id,
        "attempt_id": attempt_id,
        "captured_at": started_at,
        "startup_metric_names": [metric["name"] for metric in start_snapshot["metrics"]],
    }
    result_path = result_dir / "probe_payload.json"
    _write_json(result_path, result_payload)

    if observation_seconds:
        time.sleep(observation_seconds)
    ended_at = _utc_now()
    duration_seconds = max(0.0, time.monotonic() - started_monotonic)
    final_snapshot = _collect_capacity_snapshot(client_resource_dir.parent, ended_at)
    retained_metric = _retained_content_metric(result_path, ended_at)
    network = _unbound_network(ended_at)
    rollups = [
        _proxy_rollup(
            _metric_by_name(start_snapshot["metrics"], "visible_gpu_count"),
            duration_seconds,
            name="visible_gpu_seconds",
            unit="gpu_seconds",
            observed_at=ended_at,
        ),
        _proxy_rollup(
            _metric_by_name(start_snapshot["metrics"], "visible_cpu_units"),
            duration_seconds,
            name="visible_cpu_unit_seconds",
            unit="cpu_unit_seconds",
            observed_at=ended_at,
        ),
        _proxy_rollup(
            _metric_by_name(start_snapshot["metrics"], "visible_memory_bytes"),
            duration_seconds,
            name="visible_memory_byte_seconds",
            unit="byte_seconds",
            observed_at=ended_at,
        ),
    ]
    final_compute_metrics = [
        metric for metric in final_snapshot["metrics"] if metric["name"] != "visible_storage_capacity_bytes"
    ]
    attempt_status = _record_status(final_compute_metrics + rollups + [retained_metric] + network["metrics"])
    final_record = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "kind": "nvflare.resource_stats.attempt_final",
        "record_type": "resource_attempt_final",
        "job_id": job_id,
        "participant_id": participant_id,
        "role": role,
        "attempt_id": attempt_id,
        "execution_scope": {"id": scope_id, "coverage": "current_environment_only"},
        "interval": {
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
            "completion_state": "finished_ok",
            "end_basis": "process_reported",
        },
        "startup_snapshot": start_snapshot,
        "final_snapshot": {
            **final_snapshot,
            "capacity_changed": _capacity_changed(start_snapshot, final_snapshot),
        },
        "retained_content": {
            "coverage": "prototype_owned_file_only",
            "frozen_at": ended_at,
            "metrics": [retained_metric],
        },
        "network": network,
        "rollups": rollups,
        "status": attempt_status,
        "warnings": [
            "Host fallback values are prototype-only on non-Linux platforms.",
            "No NVFlare CellNet counter was bound, so F3 metrics remain unavailable.",
        ],
    }
    final_path = client_resource_dir / "attempts" / attempt_id / "final.json"
    final_bytes = _write_json(final_path, final_record)
    parent_exit = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "kind": "nvflare.resource_stats.attempt_parent_exit",
        "record_type": "resource_attempt_parent_exit",
        "job_id": job_id,
        "participant_id": participant_id,
        "role": role,
        "attempt_id": attempt_id,
        "parent_observed_at": ended_at,
        "process_exit_code": 0,
        "process_status": "exited",
        "final_fragment_present": True,
        "final_fragment_sha256": _sha256(final_bytes),
    }
    parent_exit_path = client_resource_dir / "attempts" / attempt_id / "parent_exit.json"
    parent_exit_bytes = _write_json(parent_exit_path, parent_exit)

    participant_summary = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "kind": "nvflare.resource_stats.participant_summary",
        "record_type": "participant_resource_summary",
        "job_id": job_id,
        "participant_id": participant_id,
        "role": role,
        "participant_key": participant_key,
        "summary_id": summary_id,
        "summary_revision": 1,
        "created_at": ended_at,
        "report_status": "accepted",
        "collection_status": attempt_status,
        "coverage": {"state": "partial" if attempt_status != "reported" else "complete"},
        "status": attempt_status,
        "attempts": [_summarize_attempt(final_record)],
        "fragments": {
            "attempts/%s/start.json" % attempt_id: _sha256(start_bytes),
            "attempts/%s/final.json" % attempt_id: _sha256(final_bytes),
            "attempts/%s/parent_exit.json" % attempt_id: _sha256(parent_exit_bytes),
        },
    }
    participant_summary_path = client_resource_dir / "participant_summary.json"
    participant_summary_bytes = _write_json(participant_summary_path, participant_summary)

    server_participant_path = server_resource_dir / "participants" / f"sha256-{participant_key.split(':', 1)[1]}.json"
    _write_bytes_atomic(server_participant_path, participant_summary_bytes)
    server_missing_participant = {
        "participant_id": "server",
        "role": "server",
        "report_status": "missing",
        "collection_status": "not_observed",
        "reason_codes": ["PROTOTYPE_NO_SEPARATE_SERVER_PROCESS"],
    }
    qualified_totals = _qualified_totals(
        participant_summary,
        ended_at,
        expected_participant_count=2,
        missing_participant_ids=["server"],
    )
    resource_summary = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "kind": "nvflare.resource_stats.resource_summary",
        "record_type": "job_resource_summary",
        "job": {"id": job_id, "study": study, "finalized_at": ended_at},
        "finalization": {"state": "finalized", "finalized_at": ended_at},
        "collection": {"state": "enabled", "implementation": PROTOTYPE_KIND},
        "coverage": {
            "state": "partial",
            "expected_participant_count": 2,
            "reported_participant_count": 1,
            "missing": [server_missing_participant],
            "invalid": [],
            "disabled": [],
        },
        "participants": [participant_summary, server_missing_participant],
        "qualified_totals": qualified_totals,
        "warnings": [
            "The server role was not executed by this one-process local prototype.",
            "GPU and F3 values are unavailable rather than fabricated.",
            "Non-Linux host fallback values are partial and are not a Phase 1 platform-support claim.",
        ],
    }
    resource_summary_path = server_resource_dir / "resource_summary.json"
    resource_summary_bytes = _write_json(resource_summary_path, resource_summary)
    manifest = _write_manifest(server_resource_dir)
    manifest_path = server_resource_dir / "manifest.json"
    manifest_bytes = _write_json(manifest_path, manifest)

    # The query copy has one exact RESOURCE_STATS component name.  Do not model
    # it as a generic DataTypes prefix or caller-chosen filename.
    query_store = FixedResourceStatsStore(job_store_dir)
    query_copy_receipt = query_store.save_resource_stats(job_id, resource_summary_bytes)
    query_copy_path = query_copy_receipt.path
    descriptor = {
        "schema_version": RESOURCE_SCHEMA_VERSION,
        "kind": "nvflare.resource_stats.job_metadata_descriptor",
        "record_type": "resource_stats_job_metadata_descriptor",
        "state": "finalized_partial",
        "finalized_at": ended_at,
        "resource_summary_sha256": _sha256(resource_summary_bytes),
        "manifest_sha256": _sha256(manifest_bytes),
        "expected_participant_count": 2,
        "reported_participant_count": 1,
        "missing_participant_count": 1,
    }
    descriptor_path = job_store_dir / "job_metadata_descriptor.json"
    _write_json(descriptor_path, descriptor)

    all_data = _cli_all_data(resource_summary)
    selected_data = _cli_selected_data(resource_summary, participant_id)
    _write_json(cli_dir / "resources-all.json", _cli_ok(all_data))
    _write_bytes_atomic(cli_dir / "resources-all.txt", _human_all_sites(resource_summary).encode("utf-8"))
    _write_json(cli_dir / f"resources-{participant_id}.json", _cli_ok(selected_data))
    selected_text = (
        "Runtime-visible capacity proxies; this is a selected-site rollup, not a job total.\n"
        f"Site: {participant_id}\n\n" + _human_row(participant_summary) + "\n"
    )
    _write_bytes_atomic(cli_dir / f"resources-{participant_id}.txt", selected_text.encode("utf-8"))
    error_fixtures = {
        "resources-not-ready": _cli_error(
            "RESOURCE_SUMMARY_NOT_READY",
            f"Resource summary for job '{job_id}-running' is not ready.",
            f"Wait for the job to reach a terminal state and retry 'nvflare job resources {job_id}-running'.",
            data={
                "job_id": f"{job_id}-running",
                "study": study,
                "job_status": "RUNNING",
                "resource_summary_state": "collecting",
                "retryable": True,
            },
        ),
        "resources-not-available": _cli_error(
            "RESOURCE_SUMMARY_NOT_AVAILABLE",
            f"Resource summary is not available for job '{job_id}-legacy'.",
            "The job may predate resource collection or no terminal summary was recorded.",
            data={
                "job_id": f"{job_id}-legacy",
                "study": study,
                "job_status": "FINISHED:COMPLETED",
                "resource_summary_state": "absent",
                "retryable": False,
            },
        ),
        "resources-corrupt": _cli_error(
            "RESOURCE_SUMMARY_CORRUPT",
            f"Resource summary for job '{job_id}-corrupt' failed integrity validation.",
            "Do not treat the resource values as valid; retain the job artifacts for investigation.",
            exit_code=5,
            data={
                "job_id": f"{job_id}-corrupt",
                "study": study,
                "resource_summary_state": "invalid",
                "validation_code": "MANIFEST_DIGEST_MISMATCH",
                "retryable": False,
            },
        ),
        "resources-site-not-found": _cli_error(
            "SITE_NOT_FOUND",
            "Site 'not-a-participant' is not in this job's expected participant set.",
            "Use --site all to inspect expected and reported participants.",
            data={"job_id": job_id, "study": study, "site": "not-a-participant", "retryable": False},
        ),
    }
    for fixture_name, envelope in error_fixtures.items():
        _write_json(cli_dir / f"{fixture_name}.json", envelope)
        _write_bytes_atomic(cli_dir / f"{fixture_name}.stderr.txt", _human_error(envelope).encode("utf-8"))
    disabled_data = {
        "kind": "nvflare.job_resources",
        "job_id": job_id,
        "study": study,
        "resource_summary_schema_version": RESOURCE_SCHEMA_VERSION,
        "selection": {"site": "all", "participant_ids": [], "is_job_total": True},
        "finalization": {"state": "finalized"},
        "collection": {"state": "disabled", "reason_code": "RESOURCE_COLLECTION_DISABLED"},
        "coverage": {
            "state": "not_collected",
            "expected_participant_count": 0,
            "reported_participant_count": 0,
            "missing": [],
            "invalid": [],
            "disabled": [{"reason_code": "RESOURCE_COLLECTION_DISABLED"}],
        },
        "participants": [],
        "qualified_totals": {"scope": "all_reported_participants", "metrics": []},
        "warnings": ["This is a behavioral fixture; collection was disabled before job launch."],
    }
    _write_json(cli_dir / "resources-disabled.json", _cli_ok(disabled_data))
    _write_bytes_atomic(
        cli_dir / "resources-disabled.txt",
        (
            "Runtime-visible capacity proxies; not allocations, reservations, guarantees, or billable usage.\n"
            "Collection: DISABLED (RESOURCE_COLLECTION_DISABLED). No resource summary was collected for this job.\n"
        ).encode("utf-8"),
    )
    review_contract_fixtures = write_review_contract_fixtures(output_dir, job_id, resource_summary_bytes)

    receipt = {
        "schema_version": "prototype-0.3",
        "record_type": "artifact_generation_receipt",
        "generated_at": _utc_now(),
        "job_id": job_id,
        "study": study,
        "actual_local_observations": [
            "CPU/memory host fallback (partial on non-Linux)",
            "filesystem capacity for client_run",
            "exact byte size of result_artifacts/probe_payload.json",
            "actual measured generator observation interval",
        ],
        "intentionally_unavailable": [
            "CUDA runtime GPU inventory unless present and bound",
            "F3/CellNet sender counters",
            "separate server-role process summary",
        ],
        "integrity": {
            "resource_summary_sha256": _sha256(resource_summary_bytes),
            "query_copy_matches_resource_summary": query_copy_path.read_bytes() == resource_summary_bytes,
            "query_copy_component": query_copy_path.name,
        },
        "review_contract_fixtures": review_contract_fixtures,
    }
    _write_json(output_dir / "generation_receipt.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "generated" / "actual_local",
        help="directory to receive generated artifacts",
    )
    parser.add_argument("--job-id", default="prototype-local-resource-proxy", help="safe synthetic job identifier")
    parser.add_argument("--study", default="prototype", help="safe synthetic study identifier")
    parser.add_argument(
        "--observation-seconds",
        type=float,
        default=0.25,
        help="real local observation interval to measure before finalization",
    )
    args = parser.parse_args()
    receipt = generate(args.output, args.job_id, args.study, args.observation_seconds)
    print(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
