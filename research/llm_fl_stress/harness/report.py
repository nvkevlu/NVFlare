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

"""Generate a machine-readable stress-run summary."""

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .artifacts import write_json
from .config import Scenario, load_scenario


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


def _read_events(path: Path) -> list[Dict[str, Any]]:
    events = []
    try:
        with path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    events.append(record)
    except OSError:
        pass
    return events


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _event_roles_by_pid(events: list[Dict[str, Any]]) -> Dict[int, str]:
    result = {}
    for event in events:
        source = event.get("source")
        pid = event.get("pid")
        if source in {"server", "client"} and isinstance(pid, int):
            result[pid] = source
    return result


def _process_metrics(path: Path, event_roles_by_pid: Dict[int, str] | None = None) -> Dict[str, Any]:
    event_roles_by_pid = event_roles_by_pid or {}
    tree_rss_by_sample: Dict[int, int] = defaultdict(int)
    role_rss_by_sample: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
    sample_indexes = set()
    elapsed_by_sample: Dict[int, float] = {}
    cgroup_peak = 0
    cgroup_current_peak = 0
    cgroup_memory_max = None
    cgroup_oom_values = []
    cgroup_oom_kill_values = []
    maximum_swap_used = 0
    minimum_disk_free = None
    maximum_disk_used = 0
    row_count = 0
    try:
        with path.open(encoding="utf-8", newline="") as file:
            for row in csv.DictReader(file):
                row_count += 1
                sample_index = int(row["sample_index"])
                rss_bytes = int(row["rss_bytes"])
                pid = int(row.get("pid", 0))
                role = event_roles_by_pid.get(pid, row["role"])
                sample_indexes.add(sample_index)
                elapsed_value = row.get("elapsed_seconds")
                if elapsed_value not in (None, ""):
                    elapsed_by_sample[sample_index] = float(elapsed_value)
                tree_rss_by_sample[sample_index] += rss_bytes
                role_rss_by_sample[role][sample_index] += rss_bytes
                disk_free = row.get("disk_free_bytes")
                if disk_free not in (None, ""):
                    parsed_disk_free = int(disk_free)
                    minimum_disk_free = (
                        parsed_disk_free if minimum_disk_free is None else min(minimum_disk_free, parsed_disk_free)
                    )
                disk_used = row.get("disk_used_bytes")
                if disk_used not in (None, ""):
                    maximum_disk_used = max(maximum_disk_used, int(disk_used))
                swap_used = row.get("swap_used_bytes")
                if swap_used not in (None, ""):
                    maximum_swap_used = max(maximum_swap_used, int(swap_used))
                cgroup_value = row.get("cgroup_memory_current_bytes")
                if cgroup_value not in (None, ""):
                    cgroup_current_peak = max(cgroup_current_peak, int(cgroup_value))
                cgroup_value = row.get("cgroup_memory_peak_bytes")
                if cgroup_value not in (None, ""):
                    cgroup_peak = max(cgroup_peak, int(cgroup_value))
                cgroup_value = row.get("cgroup_memory_max_bytes")
                if cgroup_value not in (None, ""):
                    parsed_limit = int(cgroup_value)
                    cgroup_memory_max = (
                        parsed_limit if cgroup_memory_max is None else min(cgroup_memory_max, parsed_limit)
                    )
                cgroup_value = row.get("cgroup_oom_events")
                if cgroup_value not in (None, ""):
                    cgroup_oom_values.append(int(cgroup_value))
                cgroup_value = row.get("cgroup_oom_kill_events")
                if cgroup_value not in (None, ""):
                    cgroup_oom_kill_values.append(int(cgroup_value))
    except (OSError, ValueError, KeyError):
        pass
    return {
        "row_count": row_count,
        "sample_count": len(sample_indexes),
        "sample_span_seconds": (
            max(elapsed_by_sample.values()) - min(elapsed_by_sample.values()) if elapsed_by_sample else None
        ),
        "peak_process_tree_rss_bytes": max(tree_rss_by_sample.values(), default=0),
        "peak_rss_bytes_by_role": {
            role: max(samples.values(), default=0) for role, samples in sorted(role_rss_by_sample.items())
        },
        "maximum_swap_used_bytes": maximum_swap_used,
        "cgroup_memory_current_peak_bytes": cgroup_current_peak,
        "cgroup_memory_peak_bytes": cgroup_peak,
        "cgroup_memory_max_bytes": cgroup_memory_max,
        "cgroup_oom_events": max(cgroup_oom_values, default=0),
        "cgroup_oom_kill_events": max(cgroup_oom_kill_values, default=0),
        "cgroup_oom_event_delta": (
            max(cgroup_oom_values) - min(cgroup_oom_values) if cgroup_oom_values else 0
        ),
        "cgroup_oom_kill_event_delta": (
            max(cgroup_oom_kill_values) - min(cgroup_oom_kill_values) if cgroup_oom_kill_values else 0
        ),
        "minimum_disk_free_bytes": minimum_disk_free,
        "maximum_disk_used_bytes": maximum_disk_used,
    }


def _gpu_metrics(path: Path) -> Dict[str, Any]:
    peak_by_gpu: Dict[str, float] = defaultdict(float)
    row_count = 0
    try:
        with path.open(encoding="utf-8", newline="") as file:
            for row in csv.DictReader(file):
                row_count += 1
                peak_by_gpu[row["gpu_index"]] = max(peak_by_gpu[row["gpu_index"]], float(row["memory_used_mib"]))
    except (OSError, ValueError, KeyError):
        pass
    return {"row_count": row_count, "peak_memory_used_mib_by_gpu": dict(sorted(peak_by_gpu.items()))}


def _process_metrics_by_host(metrics_dir: Path) -> Dict[str, Dict[str, Any]]:
    host_root = metrics_dir / "hosts"
    if not host_root.is_dir():
        return {}
    return {
        host_dir.name: _process_metrics(host_dir / "process_samples.csv")
        for host_dir in sorted(host_root.iterdir())
        if host_dir.is_dir()
    }


def _cgroup_metrics(path: Path) -> Dict[str, Any]:
    peak_fields = (
        "memory_current_bytes",
        "memory_peak_bytes",
        "memory_stat_anon_bytes",
        "memory_stat_file_bytes",
        "memory_stat_kernel_bytes",
        "memory_stat_sock_bytes",
        "memory_stat_shmem_bytes",
        "memory_stat_file_mapped_bytes",
        "memory_stat_file_dirty_bytes",
        "memory_stat_file_writeback_bytes",
        "memory_stat_inactive_file_bytes",
        "memory_stat_active_file_bytes",
        "memory_stat_kernel_stack_bytes",
        "memory_stat_pagetables_bytes",
        "memory_stat_slab_bytes",
        "memory_stat_slab_reclaimable_bytes",
        "memory_stat_slab_unreclaimable_bytes",
    )
    counter_fields = (
        "memory_events_low",
        "memory_events_high",
        "memory_events_max",
        "memory_events_oom",
        "memory_events_oom_kill",
        "memory_events_oom_group_kill",
        "memory_stat_pgfault",
        "memory_stat_pgmajfault",
        "pressure_some_total_usec",
        "pressure_full_total_usec",
    )
    peaks = {field: 0 for field in peak_fields}
    counters: Dict[str, list[int]] = {field: [] for field in counter_fields}
    sample_indexes = set()
    elapsed_values = []
    cgroup_paths = set()
    memory_max_values = []
    memory_high_values = []
    row_count = 0
    try:
        with path.open(encoding="utf-8", newline="") as file:
            for row in csv.DictReader(file):
                row_count += 1
                sample_indexes.add(int(row["sample_index"]))
                if row.get("elapsed_seconds") not in (None, ""):
                    elapsed_values.append(float(row["elapsed_seconds"]))
                if row.get("cgroup_path"):
                    cgroup_paths.add(row["cgroup_path"])
                for field in peak_fields:
                    if row.get(field) not in (None, ""):
                        peaks[field] = max(peaks[field], int(row[field]))
                for field in counter_fields:
                    if row.get(field) not in (None, ""):
                        counters[field].append(int(row[field]))
                if row.get("memory_max_bytes") not in (None, ""):
                    memory_max_values.append(int(row["memory_max_bytes"]))
                if row.get("memory_high_bytes") not in (None, ""):
                    memory_high_values.append(int(row["memory_high_bytes"]))
    except (OSError, ValueError, KeyError):
        pass
    return {
        "row_count": row_count,
        "sample_count": len(sample_indexes),
        "sample_span_seconds": max(elapsed_values) - min(elapsed_values) if elapsed_values else None,
        "cgroup_paths": sorted(cgroup_paths),
        "memory_max_bytes": min(memory_max_values) if memory_max_values else None,
        "memory_high_bytes": min(memory_high_values) if memory_high_values else None,
        "peaks": peaks,
        "counter_deltas": {
            field: max(values) - min(values) if values else 0 for field, values in counters.items()
        },
    }


def _cgroup_metrics_by_host(metrics_dir: Path) -> Dict[str, Dict[str, Any]]:
    host_root = metrics_dir / "hosts"
    if not host_root.is_dir():
        return {}
    return {
        host_dir.name: _cgroup_metrics(host_dir / "cgroup_samples.csv")
        for host_dir in sorted(host_root.iterdir())
        if host_dir.is_dir()
    }


def _monitor_coverage(process_metrics: Dict[str, Any], duration_seconds: float, interval_seconds: float) -> float:
    sample_span_seconds = process_metrics["sample_span_seconds"]
    sampled_seconds = (
        sample_span_seconds + interval_seconds
        if sample_span_seconds is not None
        else process_metrics["sample_count"] * interval_seconds
    )
    return min(1.0, sampled_seconds / duration_seconds)


def _workspace_metrics(path: Path) -> Dict[str, Any]:
    total_bytes = 0
    file_count = 0
    checkpoints = []
    if path.exists():
        for file_path in path.rglob("*"):
            if not file_path.is_file():
                continue
            try:
                size_bytes = file_path.stat().st_size
            except OSError:
                continue
            file_count += 1
            total_bytes += size_bytes
            if file_path.suffix.lower() in {".ckpt", ".pt", ".pth"}:
                checkpoints.append({"path": str(file_path.relative_to(path)), "size_bytes": size_bytes})
    checkpoints.sort(key=lambda item: item["size_bytes"], reverse=True)
    return {
        "file_count": file_count,
        "total_bytes": total_bytes,
        "checkpoint_count": len(checkpoints),
        "checkpoints": checkpoints[:20],
    }


def _phase_duration_metrics(events: list[Dict[str, Any]]) -> Dict[str, list[Dict[str, Any]]]:
    starts = {}
    durations: Dict[str, list[Dict[str, Any]]] = defaultdict(list)
    phase_events = {
        "server_before_aggregation": ("server_aggregation", "start"),
        "server_after_aggregation": ("server_aggregation", "end"),
        "server_before_persist": ("server_persistence", "start"),
        "server_after_persist": ("server_persistence", "end"),
        "client_receive_start": ("client_receive", "start"),
        "client_receive_end": ("client_receive", "end"),
        "client_send_start": ("client_send", "start"),
        "client_send_end": ("client_send", "end"),
    }
    for event in events:
        definition = phase_events.get(event.get("event"))
        timestamp = _parse_time(event.get("timestamp_utc"))
        if definition is None or timestamp is None:
            continue
        phase, boundary = definition
        round_number = event.get("round")
        site = event.get("site") if phase.startswith("client_") else None
        key = (phase, site, round_number)
        if boundary == "start":
            starts[key] = timestamp
            continue
        started = starts.pop(key, None)
        if started is None:
            continue
        durations[phase].append(
            {
                "site": site,
                "round": round_number,
                "duration_seconds": max(0.0, (timestamp - started).total_seconds()),
            }
        )
    return {phase: records for phase, records in sorted(durations.items())}


def _event_metrics(events: list[Dict[str, Any]], scenario: Scenario) -> Dict[str, Any]:
    rounds_by_client: Dict[str, set[int]] = defaultdict(set)
    sentinel_events = []
    aggregation_round_rss = {}
    persistence_round_rss = {}
    aggregated_clients_by_round = {}
    allocator_trim_probes = []
    harness_started = None
    harness_finished = None
    for event in events:
        event_name = event.get("event")
        if event_name == "client_receive_end" and isinstance(event.get("round"), int):
            rounds_by_client[str(event.get("site", "unknown"))].add(event["round"])
        if event_name == "client_receive_end":
            sentinel_events.append(event)
        if event_name == "server_after_aggregation" and isinstance(event.get("rss_bytes"), int):
            aggregation_round_rss[event.get("round")] = event["rss_bytes"]
            if isinstance(event.get("round"), int) and isinstance(event.get("aggregated_clients"), int):
                aggregated_clients_by_round[event["round"]] = event["aggregated_clients"]
        if event_name == "server_after_persist" and isinstance(event.get("rss_bytes"), int):
            persistence_round_rss[event.get("round")] = event["rss_bytes"]
        if event_name == "server_allocator_trim_probe":
            allocator_trim_probes.append(
                {
                    "round": event.get("round"),
                    "trigger": event.get("trigger"),
                    "rss_before_trim_bytes": event.get("rss_before_trim_bytes"),
                    "rss_after_trim_bytes": event.get("rss_bytes"),
                    "rss_released_by_trim_bytes": event.get("rss_released_by_trim_bytes"),
                    "cgroup_before_trim_bytes": event.get("cgroup_before_trim_bytes"),
                    "cgroup_after_trim_bytes": event.get("cgroup_memory_current_bytes"),
                    "tensor_storage_before_trim_bytes": event.get("tensor_storage_before_trim_bytes"),
                    "tensor_storage_after_trim_bytes": event.get("unique_tensor_storage_bytes"),
                    "tensor_storage_bytes_by_owner": event.get("tensor_storage_bytes_by_owner", {}),
                }
            )
        if event_name == "job_started":
            harness_started = _parse_time(event.get("timestamp_utc"))
        if event_name == "job_finished":
            harness_finished = _parse_time(event.get("timestamp_utc"))
    duration_seconds = None
    if harness_started and harness_finished:
        duration_seconds = max(0.0, (harness_finished - harness_started).total_seconds())
    sentinel_passes = sum(1 for event in sentinel_events if event.get("sentinel_ok") is True)
    expected_sentinel_events = len(scenario.federation.clients) * scenario.federation.rounds
    selected_round_rss = persistence_round_rss or aggregation_round_rss
    selected_event = "server_after_persist" if persistence_round_rss else "server_after_aggregation"
    server_round_rss = sorted(
        (
            (round_number, rss_bytes, selected_event)
            for round_number, rss_bytes in selected_round_rss.items()
            if isinstance(round_number, int)
        ),
        key=lambda item: item[0],
    )
    growth_percent = None
    if len(server_round_rss) >= 2 and server_round_rss[0][1] > 0:
        growth_percent = (server_round_rss[-1][1] - server_round_rss[0][1]) * 100.0 / server_round_rss[0][1]
    return {
        "job_duration_seconds": duration_seconds,
        "rounds_by_client": {client: sorted(rounds) for client, rounds in sorted(rounds_by_client.items())},
        "sentinel_event_count": len(sentinel_events),
        "sentinel_pass_count": sentinel_passes,
        "expected_sentinel_event_count": expected_sentinel_events,
        "server_round_rss": [
            {"round": round_number, "rss_bytes": rss_bytes, "event": event_name}
            for round_number, rss_bytes, event_name in server_round_rss
        ],
        "server_round_end_growth_percent": growth_percent,
        "aggregated_clients_by_round": {
            str(round_number): count for round_number, count in sorted(aggregated_clients_by_round.items())
        },
        "allocator_trim_probes": allocator_trim_probes,
        "phase_durations": _phase_duration_metrics(events),
    }


def _events_in_run_window(events: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    started = None
    finished = None
    for event in events:
        if event.get("source") != "harness":
            continue
        if event.get("event") == "job_started":
            started = _parse_time(event.get("timestamp_utc"))
        elif event.get("event") == "job_finished":
            finished = _parse_time(event.get("timestamp_utc"))
    if started is None or finished is None:
        return events

    filtered = []
    for event in events:
        if event.get("source") not in {"client", "server"}:
            filtered.append(event)
            continue
        timestamp = _parse_time(event.get("timestamp_utc"))
        if timestamp is None or started <= timestamp <= finished:
            filtered.append(event)
    return filtered


def _check(name: str, passed: bool, observed: Any, expected: Any, required: bool = True) -> Dict[str, Any]:
    return {"name": name, "passed": bool(passed), "observed": observed, "expected": expected, "required": required}


def generate_summary(run_dir: Path) -> Dict[str, Any]:
    scenario = load_scenario(run_dir / "scenario.json")
    result = _read_json(run_dir / "result.json", {})
    evidence = _read_json(run_dir / "report" / "evidence.json", {"failure_signals": []})
    events = _events_in_run_window(_read_events(run_dir / "events.jsonl"))
    mode = result.get("mode", "unknown")
    process_metrics = _process_metrics(
        run_dir / "metrics" / "process_samples.csv",
        event_roles_by_pid={} if mode == "production" else _event_roles_by_pid(events),
    )
    process_metrics_by_host = _process_metrics_by_host(run_dir / "metrics")
    cgroup_metrics = _cgroup_metrics(run_dir / "metrics" / "cgroup_samples.csv")
    cgroup_metrics_by_host = _cgroup_metrics_by_host(run_dir / "metrics")
    derived_failure_signals = []
    for label, metrics in cgroup_metrics_by_host.items():
        deltas = metrics.get("counter_deltas", {})
        oom_kill_delta = deltas.get("memory_events_oom_kill", 0)
        if oom_kill_delta > 0:
            derived_failure_signals.append(
                {"category": "CGROUP_OOM", "host": label, "oom_kill_delta": oom_kill_delta}
            )
    if (result.get("error") or {}).get("type") == "TimeoutError":
        for label, metrics in cgroup_metrics_by_host.items():
            full_pressure_usec = metrics.get("counter_deltas", {}).get("pressure_full_total_usec", 0)
            if full_pressure_usec > 0:
                derived_failure_signals.append(
                    {
                        "category": "MEMORY_PRESSURE_TIMEOUT",
                        "host": label,
                        "pressure_full_total_usec": full_pressure_usec,
                    }
                )
    evidence = dict(evidence)
    evidence["derived_failure_signals"] = derived_failure_signals
    write_json(run_dir / "report" / "evidence.json", evidence)
    gpu_metrics = _gpu_metrics(run_dir / "metrics" / "gpu_samples.csv")
    workspace_metrics = _workspace_metrics(run_dir / "flare_workspace")
    event_metrics = _event_metrics(events, scenario)
    terminal_status = result.get("status", "UNKNOWN")
    if mode in {"validate", "export"}:
        expected_terminal_status = "VALIDATED" if mode == "validate" else "EXPORTED"
        mode_passed = terminal_status == expected_terminal_status
        summary = {
            "schema_version": 1,
            "status": ("PLANNED" if mode == "validate" else "EXPORTED") if mode_passed else "FAIL",
            "mode": mode,
            "terminal_status": terminal_status,
            "metrics": {
                "process": process_metrics,
                "process_by_host": process_metrics_by_host,
                "cgroup": cgroup_metrics,
                "cgroup_by_host": cgroup_metrics_by_host,
                "gpu": gpu_metrics,
                "workspace": workspace_metrics,
                "events": event_metrics,
            },
            "evidence": evidence,
            "checks": [_check("mode_status", mode_passed, terminal_status, expected_terminal_status)],
        }
        write_json(run_dir / "report" / "summary.json", summary)
        return summary

    expected_oom_hosts = set(result.get("fault_injection", {}).get("expected_cgroup_oom_hosts", []))
    expected_failure_run = bool(expected_oom_hosts)
    baseline_required = not expected_failure_run
    checks = []
    criteria = scenario.success_criteria
    missing_artifacts = [artifact for artifact in criteria.required_artifacts if not (run_dir / artifact).exists()]
    checks.append(_check("required_artifacts", not missing_artifacts, missing_artifacts, []))
    if criteria.require_monitor_samples:
        checks.append(
            _check("monitor_samples", process_metrics["sample_count"] > 0, process_metrics["sample_count"], "> 0")
        )
        if mode == "production":
            expected_hosts = [
                host.get("label")
                for host in result.get("remote_telemetry", {}).get("hosts", [])
                if isinstance(host, dict) and isinstance(host.get("label"), str)
            ]
            missing_host_samples = {
                label: process_metrics_by_host.get(label, {}).get("sample_count", 0)
                for label in expected_hosts
                if process_metrics_by_host.get(label, {}).get("sample_count", 0) <= 0
            }
            checks.append(_check("remote_monitor_samples", not missing_host_samples, missing_host_samples, {}))
    if criteria.require_job_success:
        if expected_failure_run:
            checks.append(
                _check(
                    "expected_terminal_failure",
                    terminal_status != "FINISHED:COMPLETED",
                    terminal_status,
                    "not FINISHED:COMPLETED",
                )
            )
        else:
            checks.append(
                _check("job_status", terminal_status == "FINISHED:COMPLETED", terminal_status, "FINISHED:COMPLETED")
            )
    expected_rounds = set(range(scenario.federation.rounds))
    incomplete_clients = {
        client: sorted(expected_rounds - set(event_metrics["rounds_by_client"].get(client, [])))
        for client in scenario.federation.clients
        if set(event_metrics["rounds_by_client"].get(client, [])) != expected_rounds
    }
    checks.append(_check("client_rounds", not incomplete_clients, incomplete_clients, {}, required=baseline_required))
    expected_aggregation_counts = {
        str(round_number): len(scenario.federation.clients) for round_number in range(scenario.federation.rounds)
    }
    checks.append(
        _check(
            "server_aggregation_counts",
            event_metrics["aggregated_clients_by_round"] == expected_aggregation_counts,
            event_metrics["aggregated_clients_by_round"],
            expected_aggregation_counts,
            required=baseline_required,
        )
    )
    if criteria.require_sentinel_checks:
        sentinel_ok = (
            event_metrics["sentinel_event_count"] == event_metrics["expected_sentinel_event_count"]
            and event_metrics["sentinel_pass_count"] == event_metrics["expected_sentinel_event_count"]
        )
        checks.append(
            _check(
                "sentinel_checks",
                sentinel_ok,
                {
                    "events": event_metrics["sentinel_event_count"],
                    "passed": event_metrics["sentinel_pass_count"],
                },
                {"events": event_metrics["expected_sentinel_event_count"], "passed": "all"},
                required=baseline_required,
            )
        )
    duration_seconds = event_metrics["job_duration_seconds"]
    monitor_coverage = None
    monitor_coverage_by_host = {}
    if duration_seconds and duration_seconds > 0:
        monitor_coverage = _monitor_coverage(
            process_metrics, duration_seconds, scenario.monitoring.sample_interval_seconds
        )
        checks.append(
            _check(
                "monitor_coverage",
                monitor_coverage >= criteria.minimum_monitor_coverage,
                monitor_coverage,
                f">= {criteria.minimum_monitor_coverage}",
            )
        )
        if mode == "production":
            monitor_coverage_by_host = {
                label: _monitor_coverage(metrics, duration_seconds, scenario.monitoring.sample_interval_seconds)
                for label, metrics in process_metrics_by_host.items()
            }
            insufficient_host_coverage = {
                label: coverage
                for label, coverage in monitor_coverage_by_host.items()
                if coverage < criteria.minimum_monitor_coverage
            }
            checks.append(
                _check(
                    "remote_monitor_coverage",
                    not insufficient_host_coverage,
                    insufficient_host_coverage,
                    f"all >= {criteria.minimum_monitor_coverage}",
                )
            )
    if criteria.max_peak_process_tree_rss_gib is not None:
        peak_gib = process_metrics["peak_process_tree_rss_bytes"] / (1024**3)
        checks.append(
            _check(
                "peak_process_tree_rss",
                peak_gib <= criteria.max_peak_process_tree_rss_gib,
                peak_gib,
                f"<= {criteria.max_peak_process_tree_rss_gib} GiB",
            )
        )
    if scenario.federation.rounds >= 2:
        growth_percent = event_metrics["server_round_end_growth_percent"]
        growth_ok = growth_percent is not None and growth_percent <= criteria.max_server_round_end_growth_percent
        checks.append(
            _check(
                "server_round_end_growth",
                growth_ok,
                growth_percent,
                f"<= {criteria.max_server_round_end_growth_percent}%",
                required=scenario.federation.rounds >= 3,
            )
        )
    failure_signals = evidence.get("failure_signals", [])
    checks.append(_check("failure_signals", not failure_signals, failure_signals, [], required=baseline_required))
    oom_metrics = process_metrics_by_host if mode == "production" else {"local": process_metrics}
    cgroup_oom_deltas = {
        label: {
            "oom_delta": metrics["cgroup_oom_event_delta"],
            "oom_kill_delta": metrics["cgroup_oom_kill_event_delta"],
        }
        for label, metrics in oom_metrics.items()
    }
    if expected_failure_run:
        expected_oom_observations = {}
        for label in sorted(expected_oom_hosts):
            process_delta = cgroup_oom_deltas.get(label, {}).get("oom_kill_delta", 0)
            cgroup_delta = (
                cgroup_metrics_by_host.get(label, {}).get("counter_deltas", {}).get("memory_events_oom_kill", 0)
            )
            expected_oom_observations[label] = {
                "process_sample_oom_kill_delta": process_delta,
                "cgroup_sample_oom_kill_delta": cgroup_delta,
            }
        expected_oom_passed = all(
            max(values.values()) > 0 for values in expected_oom_observations.values()
        )
        checks.append(
            _check(
                "expected_cgroup_oom",
                expected_oom_passed,
                expected_oom_observations,
                "each expected host has oom_kill delta > 0",
            )
        )
    else:
        cgroup_oom_passed = all(
            values["oom_delta"] == 0 and values["oom_kill_delta"] == 0 for values in cgroup_oom_deltas.values()
        )
        checks.append(
            _check(
                "cgroup_oom_events",
                cgroup_oom_passed,
                cgroup_oom_deltas,
                "all host deltas = 0",
            )
        )
    if mode == "production":
        telemetry_errors = result.get("remote_telemetry", {}).get("errors", [])
        checks.append(_check("remote_telemetry_errors", not telemetry_errors, telemetry_errors, []))
    required_failures = [check for check in checks if check["required"] and not check["passed"]]
    summary = {
        "schema_version": 1,
        "status": ("EXPECTED_FAILURE" if expected_failure_run else "PASS") if not required_failures else "FAIL",
        "mode": mode,
        "terminal_status": terminal_status,
        "metrics": {
            "process": process_metrics,
            "process_by_host": process_metrics_by_host,
            "cgroup": cgroup_metrics,
            "cgroup_by_host": cgroup_metrics_by_host,
            "gpu": gpu_metrics,
            "workspace": workspace_metrics,
            "events": event_metrics,
            "monitor_coverage": monitor_coverage,
            "monitor_coverage_by_host": monitor_coverage_by_host,
        },
        "evidence": evidence,
        "failure_expectation": {
            "kind": "CGROUP_OOM" if expected_failure_run else None,
            "hosts": sorted(expected_oom_hosts),
        },
        "checks": checks,
    }
    write_json(run_dir / "report" / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a report for an LLM FL stress run.")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    summary = generate_summary(args.run_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] in {"PASS", "EXPECTED_FAILURE", "PLANNED", "EXPORTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
