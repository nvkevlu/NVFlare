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

import csv
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from research.llm_fl_stress.harness.artifacts import RunArtifacts, write_json
from research.llm_fl_stress.harness.config import load_scenario
from research.llm_fl_stress.harness.evidence import (
    DIAGNOSTIC_EVENT_PREFIXES,
    STRESS_EVENT_PREFIX,
    collect_workspace_evidence,
)
from research.llm_fl_stress.harness.finalize import finalize_run
from research.llm_fl_stress.harness.report import _cgroup_metrics, generate_summary

PROJECT_DIR = Path(__file__).resolve().parents[1]


class ReportingTest(unittest.TestCase):
    def _artifacts(self, root: Path) -> RunArtifacts:
        artifacts = RunArtifacts(
            root=root,
            manifest_path=root / "manifest.json",
            scenario_path=root / "scenario.json",
            events_path=root / "events.jsonl",
            result_path=root / "result.json",
            job_config_dir=root / "job_config",
            workspace_dir=root / "flare_workspace",
            logs_dir=root / "logs",
            metrics_dir=root / "metrics",
            report_dir=root / "report",
            _event_lock=threading.Lock(),
        )
        for directory in (
            root,
            artifacts.job_config_dir,
            artifacts.workspace_dir,
            artifacts.logs_dir,
            artifacts.metrics_dir,
            artifacts.report_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        artifacts.events_path.touch()
        return artifacts

    def _write_process_metrics(self, path: Path, oom_kill_values=None):
        oom_kill_values = oom_kill_values or [None, None]
        fieldnames = [
            "sample_index",
            "elapsed_seconds",
            "pid",
            "rss_bytes",
            "role",
            "disk_free_bytes",
            "disk_used_bytes",
            "cgroup_memory_peak_bytes",
            "cgroup_oom_events",
            "cgroup_oom_kill_events",
        ]
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerow(
                {
                    "sample_index": 0,
                    "elapsed_seconds": 0.0,
                    "pid": 42,
                    "rss_bytes": 100,
                    "role": "other",
                    "disk_free_bytes": 1000,
                    "disk_used_bytes": 500,
                    "cgroup_oom_events": oom_kill_values[0],
                    "cgroup_oom_kill_events": oom_kill_values[0],
                }
            )
            writer.writerow(
                {
                    "sample_index": 1,
                    "elapsed_seconds": 0.25,
                    "pid": 42,
                    "rss_bytes": 105,
                    "role": "other",
                    "disk_free_bytes": 900,
                    "disk_used_bytes": 600,
                    "cgroup_oom_events": oom_kill_values[1],
                    "cgroup_oom_kill_events": oom_kill_values[1],
                }
            )

    def test_cgroup_metrics_separate_gauge_peaks_and_counter_deltas(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "cgroup_samples.csv"
            fieldnames = [
                "sample_index",
                "elapsed_seconds",
                "memory_stat_file_dirty_bytes",
                "memory_stat_slab_reclaimable_bytes",
                "memory_stat_pgfault",
                "memory_stat_pgmajfault",
            ]
            with path.open("w", encoding="utf-8", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(
                    {
                        "sample_index": 0,
                        "elapsed_seconds": 0,
                        "memory_stat_file_dirty_bytes": 10,
                        "memory_stat_slab_reclaimable_bytes": 20,
                        "memory_stat_pgfault": 100,
                        "memory_stat_pgmajfault": 3,
                    }
                )
                writer.writerow(
                    {
                        "sample_index": 1,
                        "elapsed_seconds": 1,
                        "memory_stat_file_dirty_bytes": 15,
                        "memory_stat_slab_reclaimable_bytes": 18,
                        "memory_stat_pgfault": 140,
                        "memory_stat_pgmajfault": 5,
                    }
                )

            metrics = _cgroup_metrics(path)

            self.assertEqual(15, metrics["peaks"]["memory_stat_file_dirty_bytes"])
            self.assertEqual(20, metrics["peaks"]["memory_stat_slab_reclaimable_bytes"])
            self.assertEqual(40, metrics["counter_deltas"]["memory_stat_pgfault"])
            self.assertEqual(2, metrics["counter_deltas"]["memory_stat_pgmajfault"])

    def test_evidence_collector_imports_markers_and_failure_details(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifacts = self._artifacts(Path(temporary_directory))
            log_path = artifacts.workspace_dir / "server" / "log.txt"
            log_path.parent.mkdir(parents=True)
            marker = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "event": "server_after_aggregation",
                "source": "server",
                "round": 0,
                "rss_bytes": 100,
            }
            log_path.write_text(
                f"{STRESS_EVENT_PREFIX}{json.dumps(marker)}\n"
                "aggregating 2 update(s) at round 0\n"
                "OSError: No space left on device\n",
                encoding="utf-8",
            )

            evidence = collect_workspace_evidence(artifacts)

            self.assertEqual(1, evidence["marker_events"])
            self.assertEqual([0], evidence["aggregation_rounds"])
            self.assertEqual("DISK_FULL", evidence["failure_signals"][0]["category"])
            self.assertIn("No space left", evidence["failure_signals"][0]["line_excerpt"])

    def test_evidence_collector_classifies_network_buffer_exhaustion(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifacts = self._artifacts(Path(temporary_directory))
            log_path = artifacts.workspace_dir / "server" / "log.txt"
            log_path.parent.mkdir(parents=True)
            log_path.write_text("OSError: [Errno 55] No buffer space available\n", encoding="utf-8")

            evidence = collect_workspace_evidence(artifacts)

            self.assertEqual("NETWORK_BUFFER_EXHAUSTED", evidence["failure_signals"][0]["category"])

    def test_evidence_collector_imports_transport_diagnostics(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifacts = self._artifacts(Path(temporary_directory))
            record = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "event": "f3_cache_metrics",
                "source": "f3_cache",
                "duplicate_productions": 3,
            }
            log_path = artifacts.logs_dir / "service-server.log"
            log_path.write_text(f"{DIAGNOSTIC_EVENT_PREFIXES[0]}{json.dumps(record)}\n", encoding="utf-8")

            evidence = collect_workspace_evidence(artifacts)

            self.assertEqual(1, evidence["diagnostic_events"])
            events = [json.loads(line) for line in artifacts.events_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(event.get("duplicate_productions") == 3 for event in events))

    def test_evidence_collector_ignores_markers_outside_run_window(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifacts = self._artifacts(Path(temporary_directory))
            started = datetime.now(timezone.utc)
            artifacts.append_event_record(
                {"timestamp_utc": started.isoformat(), "event": "job_started", "source": "harness"}
            )
            artifacts.append_event_record(
                {
                    "timestamp_utc": (started + timedelta(seconds=10)).isoformat(),
                    "event": "job_finished",
                    "source": "harness",
                }
            )
            stale = {
                "timestamp_utc": (started - timedelta(seconds=1)).isoformat(),
                "event": "client_receive_end",
                "source": "client",
                "site": "site-1",
                "round": 0,
                "sentinel_ok": True,
            }
            current = dict(stale, timestamp_utc=(started + timedelta(seconds=1)).isoformat())
            log_path = artifacts.logs_dir / "service-site-1.log"
            log_path.write_text(
                f"{STRESS_EVENT_PREFIX}{json.dumps(stale)}\n{STRESS_EVENT_PREFIX}{json.dumps(current)}\n",
                encoding="utf-8",
            )

            evidence = collect_workspace_evidence(artifacts)

            self.assertEqual(1, evidence["marker_events"])

    def test_manifest_tolerates_unavailable_swap_metrics(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            scenario_path = PROJECT_DIR / "configs" / "smoke.json"
            scenario = load_scenario(scenario_path)
            with patch("psutil.swap_memory", side_effect=OSError):
                artifacts = RunArtifacts.create(
                    output_root=Path(temporary_directory),
                    scenario=scenario,
                    source_scenario_path=scenario_path,
                    repo_root=PROJECT_DIR.parents[1],
                    command=["validate"],
                )

            manifest = json.loads(artifacts.manifest_path.read_text(encoding="utf-8"))
            self.assertIsNone(manifest["host"]["swap_total_bytes"])

    def test_complete_run_passes_report_gates(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifacts = self._artifacts(Path(temporary_directory))
            scenario = load_scenario(PROJECT_DIR / "configs" / "smoke.json")
            write_json(artifacts.scenario_path, scenario.to_dict())
            write_json(artifacts.manifest_path, {"schema_version": 1})
            artifacts.write_result({"mode": "simulation", "status": "FINISHED:COMPLETED"})
            write_json(artifacts.report_dir / "evidence.json", {"failure_signals": []})
            self._write_process_metrics(artifacts.metrics_dir / "process_samples.csv")

            started = datetime.now(timezone.utc)
            artifacts.append_event_record(
                {
                    "timestamp_utc": (started - timedelta(seconds=1)).isoformat(),
                    "event": "client_receive_end",
                    "source": "client",
                    "site": "site-1",
                    "round": 0,
                    "sentinel_ok": True,
                }
            )
            artifacts.append_event_record(
                {"timestamp_utc": started.isoformat(), "event": "job_started", "source": "harness"}
            )
            for round_number in range(2):
                for site in ("site-1", "site-2"):
                    phase_start = started + timedelta(seconds=round_number * 0.1)
                    artifacts.append_event_record(
                        {
                            "timestamp_utc": phase_start.isoformat(),
                            "event": "client_receive_start",
                            "source": "client",
                            "site": site,
                            "round": round_number,
                        }
                    )
                    artifacts.append_event_record(
                        {
                            "timestamp_utc": (phase_start + timedelta(seconds=0.01)).isoformat(),
                            "event": "client_receive_end",
                            "source": "client",
                            "site": site,
                            "round": round_number,
                            "sentinel_ok": True,
                        }
                    )
                    artifacts.append_event_record(
                        {
                            "timestamp_utc": (phase_start + timedelta(seconds=0.02)).isoformat(),
                            "event": "client_send_end",
                            "source": "client",
                            "site": site,
                            "round": round_number,
                        }
                    )
                artifacts.append_event_record(
                    {
                        "timestamp_utc": (started + timedelta(seconds=round_number * 0.1 + 0.025)).isoformat(),
                        "event": "server_after_aggregation",
                        "source": "server",
                        "pid": 42,
                        "round": round_number,
                        "rss_bytes": 95 + round_number * 20,
                        "aggregated_clients": 2,
                    }
                )
                artifacts.append_event_record(
                    {
                        "timestamp_utc": (started + timedelta(seconds=round_number * 0.1 + 0.03)).isoformat(),
                        "event": "server_after_persist",
                        "source": "server",
                        "pid": 42,
                        "round": round_number,
                        "rss_bytes": 100 + round_number * 20,
                    }
                )
            artifacts.append_event_record(
                {
                    "timestamp_utc": (started + timedelta(seconds=0.5)).isoformat(),
                    "event": "job_finished",
                    "source": "harness",
                }
            )

            summary = generate_summary(artifacts.root)

            self.assertEqual("PASS", summary["status"])
            self.assertEqual(20.0, summary["metrics"]["events"]["server_round_end_growth_percent"])
            self.assertEqual(105, summary["metrics"]["process"]["peak_rss_bytes_by_role"]["server"])
            growth_check = next(check for check in summary["checks"] if check["name"] == "server_round_end_growth")
            self.assertFalse(growth_check["passed"])
            self.assertFalse(growth_check["required"])
            self.assertEqual(900, summary["metrics"]["process"]["minimum_disk_free_bytes"])

    def test_finalize_recovers_missing_result(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifacts = self._artifacts(Path(temporary_directory))
            scenario = load_scenario(PROJECT_DIR / "configs" / "smoke.json")
            write_json(artifacts.scenario_path, scenario.to_dict())
            write_json(artifacts.manifest_path, {"schema_version": 1})
            self._write_process_metrics(artifacts.metrics_dir / "process_samples.csv")

            summary = finalize_run(artifacts.root)

            result = json.loads(artifacts.result_path.read_text(encoding="utf-8"))
            self.assertEqual("FAIL", summary["status"])
            self.assertEqual("AbruptTermination", result["error"]["type"])

    def test_production_report_keeps_host_metrics_separate(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifacts = self._artifacts(Path(temporary_directory))
            scenario = load_scenario(PROJECT_DIR / "configs" / "smoke.json")
            write_json(artifacts.scenario_path, scenario.to_dict())
            write_json(artifacts.manifest_path, {"schema_version": 1})
            artifacts.write_result(
                {
                    "mode": "production",
                    "status": "FINISHED:FAILED",
                    "remote_telemetry": {
                        "hosts": [
                            {"label": "server", "role": "server"},
                            {"label": "site-1", "role": "client"},
                            {"label": "site-2", "role": "client"},
                        ],
                        "errors": [],
                    },
                }
            )
            write_json(artifacts.report_dir / "evidence.json", {"failure_signals": []})
            host_root = artifacts.metrics_dir / "hosts"
            for label in ("server", "site-1", "site-2"):
                host_dir = host_root / label
                host_dir.mkdir(parents=True)
                self._write_process_metrics(host_dir / "process_samples.csv")
            self._write_process_metrics(artifacts.metrics_dir / "process_samples.csv")

            summary = generate_summary(artifacts.root)

            self.assertEqual({"server", "site-1", "site-2"}, set(summary["metrics"]["process_by_host"]))
            monitor_check = next(check for check in summary["checks"] if check["name"] == "remote_monitor_samples")
            telemetry_check = next(
                check for check in summary["checks"] if check["name"] == "remote_telemetry_errors"
            )
            self.assertTrue(monitor_check["passed"])
            self.assertTrue(telemetry_check["passed"])

    def test_expected_cgroup_oom_is_a_successful_failure_test(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifacts = self._artifacts(Path(temporary_directory))
            scenario = load_scenario(PROJECT_DIR / "configs" / "smoke.json")
            write_json(artifacts.scenario_path, scenario.to_dict())
            write_json(artifacts.manifest_path, {"schema_version": 1})
            artifacts.write_result(
                {
                    "mode": "production",
                    "status": "EXPECTED:CGROUP_OOM",
                    "fault_injection": {"expected_cgroup_oom_hosts": ["server"]},
                    "remote_telemetry": {
                        "hosts": [
                            {"label": "server", "role": "server"},
                            {"label": "site-1", "role": "client"},
                            {"label": "site-2", "role": "client"},
                        ],
                        "errors": [],
                    },
                }
            )
            write_json(artifacts.report_dir / "evidence.json", {"failure_signals": []})
            host_root = artifacts.metrics_dir / "hosts"
            for label in ("server", "site-1", "site-2"):
                host_dir = host_root / label
                host_dir.mkdir(parents=True)
                values = [0, 1] if label == "server" else [0, 0]
                self._write_process_metrics(host_dir / "process_samples.csv", values)
            self._write_process_metrics(artifacts.metrics_dir / "process_samples.csv", [0, 1])
            started = datetime.now(timezone.utc)
            artifacts.append_event_record(
                {"timestamp_utc": started.isoformat(), "event": "job_started", "source": "harness"}
            )
            artifacts.append_event_record(
                {
                    "timestamp_utc": (started + timedelta(seconds=0.5)).isoformat(),
                    "event": "job_finished",
                    "source": "harness",
                }
            )

            summary = generate_summary(artifacts.root)

            self.assertEqual("EXPECTED_FAILURE", summary["status"])
            expected_check = next(check for check in summary["checks"] if check["name"] == "expected_cgroup_oom")
            client_check = next(check for check in summary["checks"] if check["name"] == "client_rounds")
            self.assertTrue(expected_check["passed"])
            self.assertFalse(client_check["required"])

    def test_failed_export_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifacts = self._artifacts(Path(temporary_directory))
            scenario = load_scenario(PROJECT_DIR / "configs" / "smoke.json")
            write_json(artifacts.scenario_path, scenario.to_dict())
            write_json(artifacts.manifest_path, {"schema_version": 1})
            artifacts.write_result({"mode": "export", "status": "FINISHED:FAILED"})
            write_json(artifacts.report_dir / "evidence.json", {"failure_signals": []})

            summary = generate_summary(artifacts.root)

            self.assertEqual("FAIL", summary["status"])

    def test_evidence_collection_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            artifacts = self._artifacts(Path(temporary_directory))
            log_path = artifacts.workspace_dir / "server" / "log.txt"
            log_path.parent.mkdir(parents=True)
            marker = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "event": "server_after_aggregation",
                "source": "server",
                "round": 0,
                "rss_bytes": 100,
            }
            log_path.write_text(f"{STRESS_EVENT_PREFIX}{json.dumps(marker)}\n", encoding="utf-8")

            collect_workspace_evidence(artifacts)
            first_lines = artifacts.events_path.read_text(encoding="utf-8").splitlines()
            collect_workspace_evidence(artifacts)
            second_lines = artifacts.events_path.read_text(encoding="utf-8").splitlines()

            self.assertEqual(first_lines, second_lines)


if __name__ == "__main__":
    unittest.main()
