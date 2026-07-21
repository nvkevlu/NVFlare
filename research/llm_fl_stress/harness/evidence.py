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

"""Collect structured marker events and bounded failure evidence from FLARE logs."""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .artifacts import RunArtifacts, write_json


STRESS_EVENT_PREFIX = "[LLM_STRESS_EVENT]"
DIAGNOSTIC_EVENT_PREFIXES = ("[F3_CACHE_METRICS]", "[TENSOR_OFFLOAD_METRICS]")
_AGGREGATION_PATTERN = re.compile(r"aggregating\s+(\d+)\s+update\(s\)\s+at\s+round\s+(\d+)", re.IGNORECASE)
_ROUND_START_PATTERN = re.compile(r"round\s+(\d+)\s+started", re.IGNORECASE)
_IN_TIME_AGGREGATION_PATTERN = re.compile(r"aggregated\s+(\d+)/(\d+)\s+results", re.IGNORECASE)
_FAILURE_PATTERNS = (
    ("CUDA_OOM", ("cuda out of memory", "cuda error: out of memory")),
    ("HOST_OOM", ("memoryerror", "cannot allocate memory", "std::bad_alloc", "oom-kill", "oom_kill")),
    ("DISK_FULL", ("no space left on device", "disk quota exceeded")),
    ("NETWORK_BUFFER_EXHAUSTED", ("no buffer space available",)),
    (
        "TRANSFER_PROGRESS_TIMEOUT",
        ("streaming idle timeout", "download timed out", "transfer timed out", "status=timeout"),
    ),
    (
        "PEER_GONE",
        (
            "peer_gone",
            "target_unreachable",
            "connection reset by peer",
            "cannot forward req: no path",
            "failed to forward req: comm_error",
        ),
    ),
    ("SUBPROCESS_SHUTDOWN", ("cannot schedule new futures after shutdown",)),
    ("SERIALIZATION_ERROR", ("serialization failed", "deserialization failed", "pickle data was truncated")),
    ("CHECKPOINT_ERROR", ("failed to save checkpoint", "checkpoint save failed", "error saving checkpoint")),
)


def _log_files(workspace: Path) -> list[Path]:
    result = set()
    if not workspace.exists():
        return []
    for path in workspace.rglob("*"):
        if path.is_file() and (path.name in {"log.txt", "log.json"} or path.suffix == ".log"):
            result.add(path)
    return sorted(result)


def _load_existing_signatures(artifacts: RunArtifacts) -> tuple[set[str], set[tuple[str, int, int]]]:
    marker_signatures = set()
    aggregation_signatures = set()
    try:
        with artifacts.events_path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                normalized = dict(record)
                normalized.pop("source_log", None)
                marker_signatures.add(json.dumps(normalized, sort_keys=True))
                if record.get("event") == "server_aggregation_log":
                    source_log = record.get("source_log")
                    round_number = record.get("round")
                    contributions = record.get("contributions")
                    if (
                        isinstance(source_log, str)
                        and isinstance(round_number, int)
                        and isinstance(contributions, int)
                    ):
                        aggregation_signatures.add((source_log, round_number, contributions))
    except OSError:
        pass
    return marker_signatures, aggregation_signatures


def _event_window(artifacts: RunArtifacts) -> tuple[datetime | None, datetime | None]:
    started = None
    finished = None
    try:
        with artifacts.events_path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict) or record.get("source") != "harness":
                    continue
                try:
                    timestamp = datetime.fromisoformat(str(record.get("timestamp_utc")))
                except (TypeError, ValueError):
                    continue
                if record.get("event") == "job_started":
                    started = timestamp
                elif record.get("event") == "job_finished":
                    finished = timestamp
    except OSError:
        pass
    return started, finished


def _marker_in_window(record: dict, started: datetime | None, finished: datetime | None) -> bool:
    if started is None or finished is None:
        return True
    try:
        timestamp = datetime.fromisoformat(str(record.get("timestamp_utc")))
    except (TypeError, ValueError):
        return True
    return started <= timestamp <= finished


def collect_workspace_evidence(artifacts: RunArtifacts) -> Dict[str, Any]:
    marker_signatures, aggregation_signatures = _load_existing_signatures(artifacts)
    started, finished = _event_window(artifacts)
    log_marker_signatures = set()
    failure_signatures = set()
    failure_signals = []
    logs_scanned = 0
    marker_events = 0
    diagnostic_events = 0
    aggregation_rounds = set()
    log_paths = sorted(set(_log_files(artifacts.workspace_dir) + _log_files(artifacts.logs_dir)))
    for path in log_paths:
        logs_scanned += 1
        current_round = None
        try:
            relative_path = artifacts.relative_path(path)
            with path.open(encoding="utf-8", errors="replace") as file:
                for line_number, line in enumerate(file, start=1):
                    round_start_match = _ROUND_START_PATTERN.search(line)
                    if round_start_match:
                        current_round = int(round_start_match.group(1))
                    marker_index = line.find(STRESS_EVENT_PREFIX)
                    if marker_index >= 0:
                        payload = line[marker_index + len(STRESS_EVENT_PREFIX) :].strip()
                        try:
                            record = json.loads(payload)
                        except json.JSONDecodeError:
                            record = None
                        if isinstance(record, dict):
                            if not _marker_in_window(record, started, finished):
                                continue
                            signature = json.dumps(record, sort_keys=True)
                            if signature not in log_marker_signatures:
                                log_marker_signatures.add(signature)
                                marker_events += 1
                            if signature not in marker_signatures:
                                marker_signatures.add(signature)
                                record["source_log"] = relative_path
                                artifacts.append_event_record(record)
                    for prefix in DIAGNOSTIC_EVENT_PREFIXES:
                        diagnostic_index = line.find(prefix)
                        if diagnostic_index < 0:
                            continue
                        payload = line[diagnostic_index + len(prefix) :].strip()
                        try:
                            record = json.loads(payload)
                        except json.JSONDecodeError:
                            record = None
                        if not isinstance(record, dict) or not _marker_in_window(record, started, finished):
                            continue
                        signature = json.dumps(record, sort_keys=True)
                        if signature not in log_marker_signatures:
                            log_marker_signatures.add(signature)
                            diagnostic_events += 1
                        if signature not in marker_signatures:
                            marker_signatures.add(signature)
                            record["source_log"] = relative_path
                            artifacts.append_event_record(record)
                    aggregation_match = _AGGREGATION_PATTERN.search(line)
                    if aggregation_match:
                        contributions = int(aggregation_match.group(1))
                        round_number = int(aggregation_match.group(2))
                        aggregation_rounds.add(round_number)
                        signature = (relative_path, round_number, contributions)
                        if signature not in aggregation_signatures:
                            aggregation_signatures.add(signature)
                            artifacts.append_event(
                                "server_aggregation_log",
                                "server_log",
                                round=round_number,
                                contributions=contributions,
                                source_log=relative_path,
                            )
                    in_time_match = _IN_TIME_AGGREGATION_PATTERN.search(line)
                    if in_time_match and current_round is not None:
                        contributions = int(in_time_match.group(1))
                        expected = int(in_time_match.group(2))
                        if contributions == expected:
                            aggregation_rounds.add(current_round)
                            signature = (relative_path, current_round, contributions)
                            if signature not in aggregation_signatures:
                                aggregation_signatures.add(signature)
                                artifacts.append_event(
                                    "server_aggregation_log",
                                    "server_log",
                                    round=current_round,
                                    contributions=contributions,
                                    expected_contributions=expected,
                                    source_log=relative_path,
                                )
                    lowered = line.lower()
                    for category, signals in _FAILURE_PATTERNS:
                        matched_signal = next((signal for signal in signals if signal in lowered), None)
                        if matched_signal is None:
                            continue
                        signature = (category, relative_path, line_number)
                        if signature in failure_signatures:
                            continue
                        failure_signatures.add(signature)
                        failure_signals.append(
                            {
                                "category": category,
                                "source_log": relative_path,
                                "line_number": line_number,
                                "matched_signal": matched_signal,
                                "line_excerpt": line.strip()[:500],
                            }
                        )
        except OSError:
            continue
    evidence = {
        "logs_scanned": logs_scanned,
        "marker_events": marker_events,
        "diagnostic_events": diagnostic_events,
        "aggregation_rounds": sorted(aggregation_rounds),
        "failure_signals": failure_signals,
    }
    write_json(artifacts.report_dir / "evidence.json", evidence)
    return evidence
