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

import json
from pathlib import Path

import pytest

from research.llm_fl_stress.real_training import telemetry_analysis

GPU_HEADER = "timestamp, index, uuid, name, memory.used [MiB], utilization.gpu [%]\n"


def _write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _gpu_row(timestamp, index, memory_mib, utilization):
    return f"{timestamp}, {index}, GPU-{index}, NVIDIA A100-SXM4-80GB, " f"{memory_mib} MiB, {utilization} %\n"


def _gpu_summary(path, rows, *, status="PASS", return_code=None):
    counts = {}
    peak_utilization = {}
    peak_memory = {}
    for _timestamp, index, memory_mib, utilization in rows:
        counts[index] = counts.get(index, 0) + 1
        peak_utilization[index] = max(peak_utilization.get(index, 0), utilization)
        peak_memory[index] = max(peak_memory.get(index, 0), memory_mib)
    observed = sorted(counts)
    return {
        "event": "real_training_gpu_monitor",
        "status": status,
        "output_path": str(path),
        "output_size_bytes": path.stat().st_size,
        "sample_lines": len(rows),
        "observed_gpu_indices": observed,
        "active_gpu_indices": [index for index in observed if peak_utilization[index] > 0 and peak_memory[index] > 0],
        "samples_per_gpu": {str(index): counts[index] for index in observed},
        "peak_utilization_percent": {str(index): peak_utilization[index] for index in observed},
        "peak_memory_mib": {str(index): peak_memory[index] for index in observed},
        "return_code_before_shutdown": return_code,
    }


def _allocation_sample(timestamp, rss, pss, available, scratch, *, current=None, peak=None, events=None):
    return {
        "timestamp_unix": timestamp,
        "cgroup_memory_current_bytes": current,
        "cgroup_memory_peak_bytes": peak,
        "cgroup_memory_events": events or {},
        "process_tree_rss_bytes": rss,
        "process_tree_pss_bytes": pss,
        "system_available_bytes": available,
        "scratch_free_bytes": scratch,
    }


def _allocation_summary(path, samples, *, cgroup=False, event_deltas=None, status="PASS"):
    event_deltas = event_deltas or {}
    return {
        "event": "real_training_allocation_monitor",
        "status": status,
        "output_path": str(path),
        "cgroup_path": "/sys/fs/cgroup/job" if cgroup else None,
        "allocation_wide_cgroup_metrics_available": cgroup,
        "telemetry_scope": "allocation-cgroup-plus-process-tree" if cgroup else "process-tree-plus-system",
        "sample_count": len(samples),
        "peak_cgroup_memory_current_bytes": max(
            (sample["cgroup_memory_current_bytes"] or 0 for sample in samples), default=0
        ),
        "peak_cgroup_memory_bytes": max((sample["cgroup_memory_peak_bytes"] or 0 for sample in samples), default=0),
        "peak_process_tree_rss_bytes": max(sample["process_tree_rss_bytes"] for sample in samples),
        "peak_process_tree_pss_bytes": max(sample["process_tree_pss_bytes"] for sample in samples),
        "minimum_system_available_bytes": min(sample["system_available_bytes"] for sample in samples),
        "minimum_scratch_free_bytes": min(sample["scratch_free_bytes"] for sample in samples),
        "cgroup_memory_event_deltas": event_deltas,
        "fatal_cgroup_event_deltas": {key: event_deltas.get(key, 0) for key in ("max", "oom", "oom_kill")},
        "error": None,
    }


def _artifact(tmp_path, *, gpu_rows=None, allocation_samples=None, cgroup=False, event_deltas=None):
    root = tmp_path / "artifact"
    root.mkdir()
    if gpu_rows is None:
        gpu_rows = [
            (timestamp, index, 1000 + step * 100 + index, utilization)
            for step, (timestamp, utilization) in enumerate(
                (
                    ("2026/07/31 12:00:00", 0),
                    ("2026/07/31 12:00:05.000", 80),
                    ("2026/07/31 12:00:10", 100),
                )
            )
            for index in range(8)
        ]
    gpu_path = root / "gpu-samples.csv"
    gpu_path.write_text(
        GPU_HEADER
        + "".join(
            _gpu_row(timestamp, index, memory_mib, utilization)
            for timestamp, index, memory_mib, utilization in gpu_rows
        ),
        encoding="utf-8",
    )
    _write_json(root / "gpu-monitor.json", _gpu_summary(gpu_path, gpu_rows))

    if allocation_samples is None:
        allocation_samples = [
            _allocation_sample(1000.0, 100, 80, 1000, 2000),
            _allocation_sample(1005.0, 200, 160, 900, 1900),
            _allocation_sample(1010.0, 150, 120, 950, 1950),
        ]
    allocation_path = root / "allocation-memory.jsonl"
    allocation_path.write_text(
        "".join(json.dumps(sample, sort_keys=True) + "\n" for sample in allocation_samples), encoding="utf-8"
    )
    _write_json(
        root / "allocation-monitor.json",
        _allocation_summary(
            allocation_path,
            allocation_samples,
            cgroup=cgroup,
            event_deltas=event_deltas,
        ),
    )
    _write_json(
        root / "configuration.json",
        {
            "event": "real_training_production_configuration",
            "gpu_mapping": {"site-1": [0, 1, 2, 3], "site-2": [4, 5, 6, 7]},
        },
    )
    _write_json(root / "qualification.json", {"status": "PASS"})
    (root / "manifest.txt").write_text(
        "job_id=123\nstatus=PASS\nexit_code=0\nslurm_mem_per_node_mib=1\nslurm_gpus_on_node=8\n",
        encoding="utf-8",
    )
    return root


def test_analyzer_reports_sampled_gpu_and_allocation_statistics(tmp_path):
    root = _artifact(tmp_path)

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "PASS"
    assert result["qualification_status"] == "PASS"
    assert result["sources"]["gpu_samples"] == {
        "path": "gpu-samples.csv",
        "sha256": result["sources"]["gpu_samples"]["sha256"],
        "size_bytes": (root / "gpu-samples.csv").stat().st_size,
        "raw_rows": 24,
        "valid_rows": 24,
        "rejected_rows": 0,
        "duplicate_rows": 0,
    }
    gpu = result["gpu"]
    assert gpu["timestamp_basis"] == "node-local-naive"
    assert gpu["snapshot_count"] == 3
    assert gpu["complete_snapshot_count"] == 3
    assert gpu["median_snapshot_interval_seconds"] == 5.0
    assert gpu["maximum_snapshot_interval_seconds"] == 5.0
    assert gpu["per_gpu"][0]["mean_sampled_utilization_percent"] == 60.0
    assert gpu["per_gpu"][0]["p50_utilization_percent"] == 80.0
    assert gpu["per_gpu"][0]["p95_utilization_percent"] == 98.0
    assert gpu["per_gpu"][0]["nonzero_utilization_sample_fraction"] == pytest.approx(2 / 3)
    assert gpu["per_gpu"][0]["high_utilization_sample_fraction"] == pytest.approx(2 / 3)
    assert gpu["fleet"]["mean_sampled_utilization_percent"] == 60.0
    assert gpu["fleet"]["mean_active_gpu_count"] == pytest.approx(16 / 3)
    assert gpu["fleet"]["all_expected_gpus_active_snapshot_fraction"] == pytest.approx(2 / 3)
    assert gpu["fleet"]["mean_concurrent_memory_mib"] == 8828.0
    assert gpu["fleet"]["peak_concurrent_memory_mib"] == 9628

    allocation = result["allocation"]
    assert allocation["sample_count"] == 3
    assert allocation["median_interval_seconds"] == 5.0
    assert allocation["metrics"]["process_tree_rss_bytes"] == {
        "sample_count": 3,
        "minimum": 100,
        "maximum": 200,
        "mean": 150.0,
        "p50": 150.0,
        "p95": 195.0,
        "minimum_timestamp_unix": 1000.0,
        "maximum_timestamp_unix": 1005.0,
    }
    assert allocation["cgroup"] == {
        "available": False,
        "path": None,
        "memory_current_bytes": None,
        "memory_peak_bytes": None,
        "event_deltas": None,
        "fatal_event_deltas": None,
        "event_observation_supported": False,
    }
    assert result["allocation_request"] == {
        "memory_mib": 1,
        "gpu_count": 8,
        "process_tree_peak_nominal_headroom_bytes": 1024 * 1024 - 200,
        "claim_scope": "nominal-process-tree-only",
    }
    assert all(check["status"] == "PASS" for check in result["consistency_checks"])
    assert result["claims"] == {
        "sampled_gpu_average_supported": True,
        "continuous_time_average_supported": False,
        "allocation_wide_memory_supported": False,
        "cgroup_oom_observation_supported": False,
        "server_only_memory_supported": False,
        "phase_attribution_supported": False,
    }
    assert any("not OOM evidence" in warning for warning in result["warnings"])


def test_concurrent_peak_memory_does_not_sum_per_gpu_peaks_from_different_snapshots(tmp_path):
    rows = []
    for step in range(8):
        timestamp = f"2026/07/31 12:00:{step * 5:02d}"
        for index in range(8):
            rows.append((timestamp, index, 100 if index == step else 1, 100))
    root = _artifact(tmp_path, gpu_rows=rows)

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "PASS"
    assert sum(gpu["peak_memory_mib"] for gpu in result["gpu"]["per_gpu"]) == 800
    assert result["gpu"]["fleet"]["peak_concurrent_memory_mib"] == 107


def test_snapshot_grouping_accepts_per_gpu_timestamp_jitter(tmp_path):
    rows = []
    for second in (0, 5):
        for index in range(8):
            timestamp = f"2026/07/31 12:00:{second:02d}.{index * 10:03d}"
            rows.append((timestamp, index, 1000 + index, 90))
    root = _artifact(tmp_path, gpu_rows=rows)

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "PASS"
    assert result["gpu"]["snapshot_grouping_tolerance_seconds"] == 1.0
    assert result["gpu"]["snapshot_count"] == 2
    assert result["gpu"]["complete_snapshot_count"] == 2
    assert result["gpu"]["median_snapshot_interval_seconds"] == 5.0


def test_cgroup_metrics_and_event_deltas_are_supported_when_retained(tmp_path):
    samples = [
        _allocation_sample(
            1000.0,
            100,
            80,
            1000,
            2000,
            current=50,
            peak=50,
            events={"high": 0, "max": 0, "oom": 0, "oom_kill": 0},
        ),
        _allocation_sample(
            1005.0,
            200,
            160,
            900,
            1900,
            current=100,
            peak=100,
            events={"high": 1, "max": 0, "oom": 0, "oom_kill": 0},
        ),
    ]
    root = _artifact(
        tmp_path,
        allocation_samples=samples,
        cgroup=True,
        event_deltas={"high": 1, "max": 0, "oom": 0, "oom_kill": 0},
    )

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "PASS"
    assert result["allocation"]["cgroup"]["available"] is True
    assert result["allocation"]["cgroup"]["memory_current_bytes"]["maximum"] == 100
    assert result["allocation"]["cgroup"]["event_deltas"] == {
        "high": 1,
        "max": 0,
        "oom": 0,
        "oom_kill": 0,
    }
    assert result["claims"]["allocation_wide_memory_supported"] is True
    assert result["claims"]["cgroup_oom_observation_supported"] is True


def test_fatal_cgroup_event_fails_analysis(tmp_path):
    samples = [
        _allocation_sample(
            1000.0,
            100,
            80,
            1000,
            2000,
            current=50,
            peak=50,
            events={"max": 1, "oom": 0, "oom_kill": 0},
        )
    ]
    root = _artifact(
        tmp_path,
        allocation_samples=samples,
        cgroup=True,
        event_deltas={"max": 1, "oom": 0, "oom_kill": 0},
    )
    summary_path = root / "allocation-monitor.json"
    summary = json.loads(summary_path.read_text())
    summary["status"] = "FAIL"
    _write_json(summary_path, summary)

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "FAIL"
    assert any("fatal cgroup memory event" in error for error in result["errors"])


def test_malformed_tail_records_are_reported_as_partial_without_changing_valid_statistics(tmp_path):
    root = _artifact(tmp_path)
    gpu_path = root / "gpu-samples.csv"
    with gpu_path.open("a", encoding="utf-8") as stream:
        stream.write("not-a-time, 0, GPU-0, NVIDIA A100-SXM4-80GB, N/A, N/A\n")
    gpu_summary = json.loads((root / "gpu-monitor.json").read_text())
    gpu_summary["output_size_bytes"] = gpu_path.stat().st_size
    _write_json(root / "gpu-monitor.json", gpu_summary)
    with (root / "allocation-memory.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("{truncated\n")

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "PARTIAL"
    assert result["sources"]["gpu_samples"]["rejected_rows"] == 1
    assert result["sources"]["allocation_samples"]["rejected_lines"] == 1
    assert result["gpu"]["fleet"]["mean_sampled_utilization_percent"] == 60.0
    assert all(check["status"] == "PASS" for check in result["consistency_checks"])


def test_conflicting_duplicate_gpu_sample_fails_closed(tmp_path):
    root = _artifact(tmp_path)
    gpu_path = root / "gpu-samples.csv"
    lines = gpu_path.read_text().splitlines(keepends=True)
    lines.insert(2, _gpu_row("2026/07/31 12:00:00", 0, 9999, 100))
    gpu_path.write_text("".join(lines), encoding="utf-8")
    summary = json.loads((root / "gpu-monitor.json").read_text())
    summary["output_size_bytes"] = gpu_path.stat().st_size
    summary["sample_lines"] += 1
    summary["samples_per_gpu"]["0"] += 1
    summary["peak_memory_mib"]["0"] = 9999
    summary["peak_utilization_percent"]["0"] = 100
    _write_json(root / "gpu-monitor.json", summary)

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "FAIL"
    assert any("conflicting duplicate GPU sample" in error for error in result["errors"])


def test_raw_summary_peak_mismatch_fails_reconciliation(tmp_path):
    root = _artifact(tmp_path)
    summary_path = root / "gpu-monitor.json"
    summary = json.loads(summary_path.read_text())
    summary["peak_memory_mib"]["0"] += 1
    _write_json(summary_path, summary)

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "FAIL"
    check = next(check for check in result["consistency_checks"] if check["name"] == "gpu.peak_memory_mib")
    assert check["status"] == "FAIL"
    assert result["claims"]["sampled_gpu_average_supported"] is False


def test_missing_gpu_and_changed_identity_fail_closed(tmp_path):
    rows = [
        (timestamp, index, 1000, 90)
        for timestamp in ("2026/07/31 12:00:00", "2026/07/31 12:00:05")
        for index in range(7)
    ]
    root = _artifact(tmp_path, gpu_rows=rows)
    gpu_path = root / "gpu-samples.csv"
    text = gpu_path.read_text().replace("GPU-0, NVIDIA", "GPU-other, NVIDIA", 1)
    gpu_path.write_text(text, encoding="utf-8")
    summary = _gpu_summary(gpu_path, rows, status="FAIL")
    _write_json(root / "gpu-monitor.json", summary)

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "FAIL"
    assert any("GPU index mismatch" in error for error in result["errors"])
    assert any("changed identity" in error for error in result["errors"])
    assert result["gpu"]["complete_snapshot_count"] == 0
    assert result["claims"]["sampled_gpu_average_supported"] is False


def test_impossible_gpu_utilization_fails_instead_of_becoming_a_partial_claim(tmp_path):
    root = _artifact(tmp_path)
    gpu_path = root / "gpu-samples.csv"
    text = gpu_path.read_text().replace("100 %", "101 %", 1)
    gpu_path.write_text(text, encoding="utf-8")
    summary = json.loads((root / "gpu-monitor.json").read_text())
    summary["output_size_bytes"] = gpu_path.stat().st_size
    summary["peak_utilization_percent"]["0"] = 101
    _write_json(root / "gpu-monitor.json", summary)

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "FAIL"
    assert any("utilization.gpu exceeds 100" in error for error in result["errors"])


def test_allocation_timestamp_restart_is_rejected(tmp_path):
    root = _artifact(tmp_path)
    stale = _allocation_sample(999.0, 50, 40, 1100, 2100)
    with (root / "allocation-memory.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(stale) + "\n")

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "FAIL"
    assert any("timestamps are not strictly increasing" in error for error in result["errors"])
    assert any(
        check["name"] == "allocation.sample_count" and check["status"] == "FAIL"
        for check in result["consistency_checks"]
    )


def test_failed_qualification_overrides_otherwise_partial_telemetry(tmp_path):
    root = _artifact(tmp_path)
    _write_json(root / "qualification.json", {"status": "FAIL"})
    with (root / "allocation-memory.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("{truncated\n")

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "FAIL"
    assert result["qualification_status"] == "FAIL"
    assert "qualification.json reports non-success status 'FAIL'" in result["errors"]


@pytest.mark.parametrize(
    ("manifest_status", "exit_code", "expected_error"),
    (
        ("FAIL", "0", "manifest.txt reports non-success status 'FAIL'"),
        ("PASS", "17", "manifest.txt reports nonzero exit_code 17"),
    ),
)
def test_explicit_manifest_failure_overrides_healthy_telemetry(tmp_path, manifest_status, exit_code, expected_error):
    root = _artifact(tmp_path)
    (root / "manifest.txt").write_text(
        "job_id=123\n"
        f"status={manifest_status}\n"
        f"exit_code={exit_code}\n"
        "slurm_mem_per_node_mib=1\n"
        "slurm_gpus_on_node=8\n",
        encoding="utf-8",
    )

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "FAIL"
    assert expected_error in result["errors"]


def test_cli_writes_the_same_deterministic_json_without_gpu_dependencies(tmp_path, capsys, monkeypatch):
    root = _artifact(tmp_path)
    output = tmp_path / "analysis.json"
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")

    status = telemetry_analysis.main(["--artifact-root", str(root), "--output", str(output)])

    assert status == 0
    printed = json.loads(capsys.readouterr().out)
    written = json.loads(output.read_text())
    assert printed == written
    assert printed["status"] == "PASS"


def test_missing_required_file_returns_structured_failure(tmp_path):
    root = tmp_path / "artifact"
    root.mkdir()

    result = telemetry_analysis.analyze_artifact(root)

    assert result["status"] == "FAIL"
    assert "missing required artifact files" in result["errors"][0]
    assert result["claims"]["sampled_gpu_average_supported"] is False
