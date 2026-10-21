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

import os
from pathlib import Path

import pytest

from nvflare.private.fed.resource_stats import collector
from nvflare.private.fed.resource_stats.accumulator import ClockOrderError, ResourceCapacityRecorder
from nvflare.private.fed.resource_stats.collector import (
    JobResourceCollector,
    assemble_participant_summary,
    observe_retained_content,
)
from nvflare.private.fed.resource_stats.contract import (
    canonical_json_bytes,
    capacity_to_resource_time,
    load_and_validate,
)
from nvflare.private.fed.resource_stats.handoff import (
    INTERNAL_HANDOFF_KIND,
    INTERNAL_HANDOFF_VERSION,
    RESOURCE_STATS_DIR,
    STAGING_DIR,
    InvalidTerminalHandoff,
    read_terminal_handoff,
    remove_terminal_handoff,
    terminal_handoff_path,
    write_terminal_handoff,
)
from nvflare.private.fed.resource_stats.probes import cgroup_linux, gpu_nvidia


def test_monotonic_ns_is_private_and_output_is_compact_seconds():
    ticks = iter([9_000_000_000_000_000_001, 9_000_000_002_000_126_790])
    accumulator = ResourceCapacityRecorder(clock_ns=lambda: next(ticks))

    accumulator.observe(
        {
            "cpu": {"groups": [{"units": "8", "model": "AMD EPYC 9654", "architecture": "x86_64"}]},
            "memory": {"bytes": "68719476736"},
            "gpu": {"groups": [{"kind": "full_gpu", "count": 2, "model": "NVIDIA H100 80GB HBM3"}]},
        }
    )
    result = accumulator.finish()

    assert result["measured_seconds"] == "2.000126789"
    assert result["cpu"]["groups"][0]["units"] == "8"
    assert result["gpu"]["groups"][0]["count"] == "2"
    assert "9000000000000000001" not in str(result)


def test_unclassified_cuda_device_capacity_accumulates_without_relabeling():
    ticks = iter([0, 2_000_000_000])
    accumulator = ResourceCapacityRecorder(clock_ns=lambda: next(ticks))
    accumulator.observe(
        {
            "cpu": {"groups": [{"units": "4"}]},
            "memory": {"bytes": "1024"},
            "gpu": {"groups": [{"kind": "cuda_device_unclassified", "count": 2, "model": "NVIDIA H100"}]},
        }
    )

    result = accumulator.finish()

    assert result["gpu"] == {"groups": [{"kind": "cuda_device_unclassified", "model": "NVIDIA H100", "count": "2"}]}
    assert "status" not in result


@pytest.mark.parametrize(
    "group",
    [
        {"kind": "cuda_device_unclassified", "count": "1.5"},
        {"kind": "cuda_device_unclassified", "count": 4097},
        {"kind": "cuda_device_unclassified", "count": 1, "mig_profile": "1g.10gb"},
        {"kind": "full_gpu", "count": 1, "mig_profile": "1g.10gb"},
    ],
)
def test_gpu_capacity_rejects_fractional_excessive_or_unverified_profile(group):
    accumulator = ResourceCapacityRecorder(clock_ns=lambda: 0)

    with pytest.raises(ValueError):
        accumulator.observe({"gpu": {"groups": [group]}})


def test_capacity_change_closes_one_interval_and_starts_the_next():
    ticks = iter([10, 1_000_000_010, 2_000_000_010])
    accumulator = ResourceCapacityRecorder(clock_ns=lambda: next(ticks))
    common = {"memory": {"bytes": 1024}, "gpu": {"groups": []}}

    accumulator.observe({"cpu": {"groups": [{"units": 8}]}, **common})
    accumulator.observe({"cpu": {"groups": [{"units": 4}]}, **common})
    result = accumulator.finish()

    assert result["measured_seconds"] == "2"
    assert [item["cpu"]["groups"] for item in result["intervals"]] == [[{"units": "8"}], [{"units": "4"}]]
    totals = capacity_to_resource_time(result)
    assert totals["cpu"]["groups"] == [{"unit_seconds": "12"}]
    assert totals["memory"]["byte_seconds"] == "2048"
    assert totals["gpu"] == {"groups": []}


def test_unchanged_capacity_observations_stay_one_flat_record():
    ticks = iter([0, 1_000_000_000, 4_000_000_000])
    recorder = ResourceCapacityRecorder(clock_ns=lambda: next(ticks))
    capacity = {"cpu": {"groups": [{"units": "8"}]}, "memory": {"bytes": "4096"}, "gpu": {"groups": []}}
    recorder.observe(capacity)
    recorder.observe(capacity)
    record = recorder.finish()
    assert record["measured_seconds"] == "4"
    assert record["cpu"]["groups"] == [{"units": "8"}]
    assert "intervals" not in record


def test_unknown_capacity_gap_excludes_elapsed_time_from_derived_products():
    ticks = iter([0, 2_000_000_000, 5_000_000_000, 7_000_000_000])
    recorder = ResourceCapacityRecorder(clock_ns=lambda: next(ticks))
    capacity = {"cpu": {"groups": [{"units": "8"}]}, "memory": {"bytes": "4096"}, "gpu": {"groups": []}}
    recorder.observe(capacity)
    recorder.mark_gap()
    recorder.observe(capacity)
    record = recorder.finish()
    assert record["measured_seconds"] == "4"
    assert record["status"] == "partial"
    assert capacity_to_resource_time(record)["cpu"]["groups"] == [{"unit_seconds": "32"}]


def test_zero_elapsed_preserves_observed_capacity_not_an_unavailable_record():
    recorder = ResourceCapacityRecorder(clock_ns=lambda: 1)
    recorder.observe({"cpu": {"groups": [{"units": "8"}]}, "memory": {"bytes": "4096"}, "gpu": {"groups": []}})
    record = recorder.finish()
    assert record["measured_seconds"] == "0"
    assert record["cpu"]["groups"] == [{"units": "8"}]
    assert "status" not in record
    assert capacity_to_resource_time(record)["cpu"]["groups"] == [{"unit_seconds": "0"}]


def test_fallback_capacity_keeps_numeric_values_and_full_observed_duration():
    ticks = iter([0, 10_000_000_000])
    recorder = ResourceCapacityRecorder(clock_ns=lambda: next(ticks))
    recorder.observe(
        {
            "status": "partial",
            "issues": ["observation_incomplete"],
            "cpu": {"groups": [{"units": "8"}]},
            "memory": {"bytes": "4096"},
            "gpu": {"groups": []},
        }
    )

    result = recorder.finish()

    assert result == {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "measured_seconds": "10",
        "cpu": {"groups": [{"units": "8"}]},
        "memory": {"bytes": "4096"},
        "gpu": {"groups": []},
    }
    assert capacity_to_resource_time(result)["cpu"]["groups"] == [{"unit_seconds": "80"}]


def test_scalar_cpu_shape_is_not_an_alternate_capacity_format():
    recorder = ResourceCapacityRecorder(clock_ns=lambda: 0)

    with pytest.raises((TypeError, ValueError)):
        recorder.observe({"cpu": {"units": "8"}})


def test_clock_must_not_move_backwards():
    ticks = iter([20, 19])
    accumulator = ResourceCapacityRecorder(clock_ns=lambda: next(ticks))
    accumulator.observe({"cpu": {"groups": [{"units": 1}]}})

    with pytest.raises(ClockOrderError):
        accumulator.finish()


def test_v2_cpu_quota_is_conservatively_floored(monkeypatch):
    mount = Path("/sys/fs/cgroup")
    leaf = mount / "job"
    values = {
        leaf / "cpuset.cpus.effective": "0-7",
        mount / "cpuset.cpus.effective": "0-15",
        leaf / "cpu.max": "2 3",
        mount / "cpu.max": "max 100000",
    }
    monkeypatch.setattr(cgroup_linux.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cgroup_linux.os, "sched_getaffinity", lambda _pid: set(range(8)), raising=False)
    monkeypatch.setattr(
        cgroup_linux,
        "_cgroup_location",
        lambda controller, _discovery: (mount, leaf, "v2") if controller is None else (None, None, "none"),
    )
    monkeypatch.setattr(cgroup_linux, "_ancestors", lambda _directory, _mount: [leaf, mount])
    monkeypatch.setattr(
        cgroup_linux,
        "_read_cgroup_file",
        lambda path: values.get(path, cgroup_linux._CGROUP_FILE_MISSING),
    )
    monkeypatch.setattr(cgroup_linux, "_cpu_identity", lambda _affinity, _models: {})
    monkeypatch.setattr(cgroup_linux, "_cpu_models", lambda _affinity: {})

    assert cgroup_linux.probe_cpu() == {"groups": [{"units": "0.666666666"}]}


def test_v1_cpu_quota_is_conservatively_floored(monkeypatch):
    cpuset_mount = Path("/sys/fs/cgroup/cpuset")
    cpu_mount = Path("/sys/fs/cgroup/cpu")
    cpuset_leaf = cpuset_mount / "job"
    cpu_leaf = cpu_mount / "job"
    values = {
        cpuset_leaf / "cpuset.effective_cpus": "0-7",
        cpuset_mount / "cpuset.effective_cpus": "0-15",
        cpu_leaf / "cpu.cfs_quota_us": "2",
        cpu_leaf / "cpu.cfs_period_us": "3",
        cpu_mount / "cpu.cfs_quota_us": "-1",
        cpu_mount / "cpu.cfs_period_us": "100000",
    }

    def location(controller, _discovery):
        if controller is None:
            return None, None, "none"
        if controller == "cpuset":
            return cpuset_mount, cpuset_leaf, "v1"
        if controller == "cpu":
            return cpu_mount, cpu_leaf, "v1"
        return None, None, "none"

    def ancestors(directory, mount):
        return [directory, mount]

    monkeypatch.setattr(cgroup_linux.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cgroup_linux.os, "sched_getaffinity", lambda _pid: set(range(8)), raising=False)
    monkeypatch.setattr(cgroup_linux, "_cgroup_location", location)
    monkeypatch.setattr(cgroup_linux, "_ancestors", ancestors)
    monkeypatch.setattr(
        cgroup_linux,
        "_read_cgroup_file",
        lambda path: values.get(path, cgroup_linux._CGROUP_FILE_MISSING),
    )
    monkeypatch.setattr(cgroup_linux, "_cpu_identity", lambda _affinity, _models: {})
    monkeypatch.setattr(cgroup_linux, "_cpu_models", lambda _affinity: {})

    assert cgroup_linux.probe_cpu() == {"groups": [{"units": "0.666666666"}]}


@pytest.mark.parametrize("bad_value", ["garbage", cgroup_linux._CGROUP_FILE_UNREADABLE])
def test_v2_cpu_keeps_affinity_when_applicable_quota_is_invalid(monkeypatch, bad_value):
    mount = Path("/sys/fs/cgroup")
    leaf = mount / "job"
    values = {
        leaf / "cpuset.cpus.effective": "0-7",
        leaf / "cpu.max": bad_value,
        mount / "cpu.max": "max 100000",
    }
    monkeypatch.setattr(cgroup_linux.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cgroup_linux.os, "sched_getaffinity", lambda _pid: set(range(8)), raising=False)
    monkeypatch.setattr(
        cgroup_linux,
        "_cgroup_location",
        lambda controller, _discovery: (mount, leaf, "v2") if controller is None else (None, None, "none"),
    )
    monkeypatch.setattr(cgroup_linux, "_ancestors", lambda _directory, _mount: [leaf, mount])
    monkeypatch.setattr(
        cgroup_linux,
        "_read_cgroup_file",
        lambda path: values.get(path, cgroup_linux._CGROUP_FILE_MISSING),
    )
    monkeypatch.setattr(cgroup_linux, "_cpu_identity", lambda _affinity, _models: {})
    monkeypatch.setattr(cgroup_linux, "_cpu_models", lambda _affinity: {})

    issues = set()
    assert cgroup_linux.probe_cpu(issues=issues) == {"groups": [{"units": "8"}]}
    assert issues == {"observation_incomplete"}


def test_v2_cpu_accepts_explicit_unlimited_quota(monkeypatch):
    mount = Path("/sys/fs/cgroup")
    leaf = mount / "job"
    values = {
        leaf / "cpuset.cpus.effective": "0-3",
        leaf / "cpu.max": "max 100000",
        mount / "cpu.max": "max 100000",
    }
    monkeypatch.setattr(cgroup_linux.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cgroup_linux.os, "sched_getaffinity", lambda _pid: set(range(8)), raising=False)
    monkeypatch.setattr(
        cgroup_linux,
        "_cgroup_location",
        lambda controller, _discovery: (mount, leaf, "v2") if controller is None else (None, None, "none"),
    )
    monkeypatch.setattr(cgroup_linux, "_ancestors", lambda _directory, _mount: [leaf, mount])
    monkeypatch.setattr(
        cgroup_linux,
        "_read_cgroup_file",
        lambda path: values.get(path, cgroup_linux._CGROUP_FILE_MISSING),
    )
    monkeypatch.setattr(cgroup_linux, "_cpu_identity", lambda _affinity, _models: {})
    monkeypatch.setattr(cgroup_linux, "_cpu_models", lambda _affinity: {})

    assert cgroup_linux.probe_cpu() == {"groups": [{"units": "4"}]}


def test_v1_cpu_keeps_affinity_when_applicable_quota_is_malformed(monkeypatch):
    cpu_mount = Path("/sys/fs/cgroup/cpu")
    cpu_leaf = cpu_mount / "job"
    values = {
        cpu_leaf / "cpu.cfs_quota_us": "bad",
        cpu_leaf / "cpu.cfs_period_us": "100000",
    }

    def location(controller, _discovery):
        if controller == "cpu":
            return cpu_mount, cpu_leaf, "v1"
        return None, None, "none"

    monkeypatch.setattr(cgroup_linux.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cgroup_linux.os, "sched_getaffinity", lambda _pid: set(range(8)), raising=False)
    monkeypatch.setattr(cgroup_linux, "_cgroup_location", location)
    monkeypatch.setattr(cgroup_linux, "_ancestors", lambda _directory, _mount: [cpu_leaf])
    monkeypatch.setattr(
        cgroup_linux,
        "_read_cgroup_file",
        lambda path: values.get(path, cgroup_linux._CGROUP_FILE_MISSING),
    )
    monkeypatch.setattr(cgroup_linux, "_cpu_identity", lambda _affinity, _models: {})
    monkeypatch.setattr(cgroup_linux, "_cpu_models", lambda _affinity: {})

    issues = set()
    assert cgroup_linux.probe_cpu(issues=issues) == {"groups": [{"units": "8"}]}
    assert issues == {"observation_incomplete"}


@pytest.mark.parametrize("bad_value", ["garbage", cgroup_linux._CGROUP_FILE_UNREADABLE])
def test_v2_memory_keeps_physical_ram_when_applicable_limit_is_invalid(monkeypatch, bad_value):
    mount = Path("/sys/fs/cgroup")
    leaf = mount / "job"
    values = {
        leaf / "memory.max": bad_value,
        mount / "memory.max": "max",
    }
    monkeypatch.setattr(cgroup_linux.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cgroup_linux.os, "sysconf", lambda key: {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 1024}[key])
    monkeypatch.setattr(
        cgroup_linux,
        "_cgroup_location",
        lambda controller, _discovery: (mount, leaf, "v2") if controller is None else (None, None, "none"),
    )
    monkeypatch.setattr(cgroup_linux, "_ancestors", lambda _directory, _mount: [leaf, mount])
    monkeypatch.setattr(
        cgroup_linux,
        "_read_cgroup_file",
        lambda path: values.get(path, cgroup_linux._CGROUP_FILE_MISSING),
    )

    issues = set()
    assert cgroup_linux.probe_memory(issues=issues) == {"bytes": str(4096 * 1024)}
    assert issues == {"observation_incomplete"}


def test_v2_memory_accepts_explicit_unlimited_limit(monkeypatch):
    mount = Path("/sys/fs/cgroup")
    leaf = mount / "job"
    values = {
        leaf / "memory.max": "max",
        mount / "memory.max": "max",
    }
    monkeypatch.setattr(cgroup_linux.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cgroup_linux.os, "sysconf", lambda key: {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 1024}[key])
    monkeypatch.setattr(
        cgroup_linux,
        "_cgroup_location",
        lambda controller, _discovery: (mount, leaf, "v2") if controller is None else (None, None, "none"),
    )
    monkeypatch.setattr(cgroup_linux, "_ancestors", lambda _directory, _mount: [leaf, mount])
    monkeypatch.setattr(
        cgroup_linux,
        "_read_cgroup_file",
        lambda path: values.get(path, cgroup_linux._CGROUP_FILE_MISSING),
    )

    assert cgroup_linux.probe_memory() == {"bytes": str(4096 * 1024)}


@pytest.mark.parametrize("bad_value", ["garbage", cgroup_linux._CGROUP_FILE_UNREADABLE])
def test_v1_memory_keeps_physical_ram_when_applicable_limit_is_invalid(monkeypatch, bad_value):
    mount = Path("/sys/fs/cgroup/memory")
    leaf = mount / "job"
    values = {leaf / "memory.limit_in_bytes": bad_value}
    monkeypatch.setattr(cgroup_linux.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cgroup_linux.os, "sysconf", lambda key: {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 1024}[key])
    monkeypatch.setattr(
        cgroup_linux,
        "_cgroup_location",
        lambda controller, _discovery: (mount, leaf, "v1") if controller == "memory" else (None, None, "none"),
    )
    monkeypatch.setattr(cgroup_linux, "_ancestors", lambda _directory, _mount: [leaf])
    monkeypatch.setattr(
        cgroup_linux,
        "_read_cgroup_file",
        lambda path: values.get(path, cgroup_linux._CGROUP_FILE_MISSING),
    )

    issues = set()
    assert cgroup_linux.probe_memory(issues=issues) == {"bytes": str(4096 * 1024)}
    assert issues == {"observation_incomplete"}


def test_v1_memory_accepts_kernel_unlimited_sentinel(monkeypatch):
    mount = Path("/sys/fs/cgroup/memory")
    leaf = mount / "job"
    values = {leaf / "memory.limit_in_bytes": "9223372036854771712"}
    monkeypatch.setattr(cgroup_linux.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cgroup_linux.os, "sysconf", lambda key: {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 1024}[key])
    monkeypatch.setattr(
        cgroup_linux,
        "_cgroup_location",
        lambda controller, _discovery: (mount, leaf, "v1") if controller == "memory" else (None, None, "none"),
    )
    monkeypatch.setattr(cgroup_linux, "_ancestors", lambda _directory, _mount: [leaf])
    monkeypatch.setattr(
        cgroup_linux,
        "_read_cgroup_file",
        lambda path: values.get(path, cgroup_linux._CGROUP_FILE_MISSING),
    )

    assert cgroup_linux.probe_memory() == {"bytes": str(4096 * 1024)}


def test_cpu_only_host_without_loadable_driver_has_partial_resource_capacity(monkeypatch):
    # A missing Driver does not prove zero CUDA devices, even on a CPU-only host.
    monkeypatch.setattr(gpu_nvidia, "_load_driver", lambda: None)
    monkeypatch.setattr(
        cgroup_linux,
        "probe_cpu",
        lambda _discovery, *, issues: {"groups": [{"units": "4", "model": "AMD EPYC 9654", "architecture": "x86_64"}]},
    )
    monkeypatch.setattr(cgroup_linux, "probe_memory", lambda _discovery, *, issues: {"bytes": "1073741824"})

    capacity = collector.probe_capacity()
    assert "gpu" not in capacity

    ticks = iter([0, 1_000_000_000])
    accumulator = ResourceCapacityRecorder(clock_ns=lambda: next(ticks))
    accumulator.observe(capacity)
    result = accumulator.finish()

    assert result["status"] == "partial"
    assert result["issues"] == ["observation_incomplete"]
    assert result["measured_seconds"] == "1"
    assert "gpu" not in result


@pytest.mark.parametrize("failed_resource", ["cpu", "memory", "gpu"])
def test_probe_failure_does_not_erase_independent_capacity(monkeypatch, failed_resource):
    expected = {
        "cpu": {"groups": [{"units": "4"}]},
        "memory": {"bytes": "4096"},
        "gpu": {"groups": []},
    }
    monkeypatch.setattr(cgroup_linux, "discover_cgroups", lambda: ([], []))
    for resource, value in expected.items():
        module = gpu_nvidia if resource == "gpu" else cgroup_linux
        monkeypatch.setattr(module, f"probe_{resource}", lambda *args, value=value, **kwargs: value)

    def fail_probe(*args, **kwargs):
        raise RuntimeError("simulated probe failure")

    module = gpu_nvidia if failed_resource == "gpu" else cgroup_linux
    monkeypatch.setattr(module, f"probe_{failed_resource}", fail_probe)

    capacity = collector.probe_capacity()

    assert capacity == {
        **{resource: value for resource, value in expected.items() if resource != failed_resource},
        "status": "partial",
        "issues": ["observation_incomplete"],
    }


def test_probe_fallback_remains_partial_through_handoff_and_public_summary(monkeypatch, tmp_path):
    def cpu_fallback(_discovery, *, issues):
        issues.add("observation_incomplete")
        return {"groups": [{"units": "8"}]}

    monkeypatch.setattr(cgroup_linux, "probe_cpu", cpu_fallback)
    monkeypatch.setattr(cgroup_linux, "probe_memory", lambda _discovery, *, issues: {"bytes": "4096"})
    monkeypatch.setattr(gpu_nvidia, "probe_gpu", lambda: {"groups": []})
    ticks = iter([0, 10_000_000_000])
    job_collector = JobResourceCollector(tmp_path, clock_ns=lambda: next(ticks))
    write_terminal_handoff(tmp_path, job_collector.finish(message_traffic={"sent_bytes": "0", "received_bytes": "0"}))

    report = assemble_participant_summary(
        job_id="job-1",
        participant_name="site-1",
        child_handoff=read_terminal_handoff(tmp_path),
    )

    assert report["resource_capacity"] == {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "measured_seconds": "10",
        "cpu": {"groups": [{"units": "8"}]},
        "memory": {"bytes": "4096"},
        "gpu": {"groups": []},
    }
    assert report["message_traffic"] == {"sent_bytes": "0", "received_bytes": "0"}


def test_handoff_to_public_report_round_trip(tmp_path):
    ticks = iter([1_000_000_000, 3_000_000_000])
    job_collector = JobResourceCollector(
        tmp_path,
        clock_ns=lambda: next(ticks),
        capacity_probe=lambda: {
            "cpu": {"groups": [{"units": 2, "model": "AMD EPYC 9654", "architecture": "x86_64"}]},
            "memory": {"bytes": 4096},
            "gpu": {"groups": []},
        },
    )

    path = write_terminal_handoff(
        tmp_path,
        job_collector.finish(message_traffic={"sent_bytes": "1200", "received_bytes": "700"}),
    )
    assert path == terminal_handoff_path(tmp_path)
    handoff = read_terminal_handoff(tmp_path)
    report = assemble_participant_summary(
        job_id="job-1",
        participant_name="site-1",
        child_handoff=handoff,
    )
    encoded = canonical_json_bytes(report)

    assert load_and_validate(encoded)["participant_name"] == "site-1"
    assert report["resource_capacity"]["measured_seconds"] == "2"
    assert "status" not in report["workspace_filesystem"]
    assert report["retained_content"] == {"bytes": "0"}
    assert report["message_traffic"] == {"sent_bytes": "1200", "received_bytes": "700"}
    assert "participant_key" not in encoded.decode()


def test_observe_retained_content_sums_regular_files_under_the_run_dir(tmp_path):
    (tmp_path / "output.bin").write_bytes(b"x" * 100)
    nested = tmp_path / "app" / "checkpoints"
    nested.mkdir(parents=True)
    (nested / "model.pt").write_bytes(b"y" * 250)

    assert observe_retained_content(tmp_path) == {"bytes": "350"}


def test_observe_retained_content_excludes_only_the_resource_stats_directory(tmp_path):
    (tmp_path / "output.bin").write_bytes(b"x" * 100)
    stats_dir = tmp_path / "resource_stats" / "participants"
    stats_dir.mkdir(parents=True)
    (stats_dir / "site-1.json").write_bytes(b"z" * 900)

    assert observe_retained_content(tmp_path) == {"bytes": "100"}


def test_observe_retained_content_does_not_exclude_a_nested_directory_of_the_same_name(tmp_path):
    # Only the top-level resource_stats directory is platform bookkeeping; a
    # job-produced directory that happens to share that name deeper in the
    # tree is ordinary job output and must still be counted.
    nested_same_name = tmp_path / "app" / "resource_stats"
    nested_same_name.mkdir(parents=True)
    (nested_same_name / "custom_output.bin").write_bytes(b"w" * 40)

    assert observe_retained_content(tmp_path) == {"bytes": "40"}


def test_observe_retained_content_is_reported_zero_for_an_empty_directory(tmp_path):
    assert observe_retained_content(tmp_path) == {"bytes": "0"}


def test_observe_retained_content_is_unavailable_when_run_dir_does_not_exist(tmp_path):
    assert observe_retained_content(tmp_path / "never-created") == {
        "status": "unavailable",
        "issues": ["observation_incomplete"],
    }


def test_observe_retained_content_is_unavailable_when_run_dir_is_a_file(tmp_path):
    run_dir = tmp_path / "not-a-directory"
    run_dir.write_bytes(b"")

    assert observe_retained_content(run_dir) == {"status": "unavailable", "issues": ["observation_incomplete"]}


def test_observe_retained_content_ignores_a_symlinked_file_without_following_it(tmp_path):
    outside = tmp_path.parent / "outside_the_run_dir.bin"
    outside.write_bytes(b"o" * 10_000)
    try:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        link = run_dir / "linked.bin"
        link.symlink_to(outside)

        result = observe_retained_content(run_dir)

        assert result == {"bytes": "0"}
    finally:
        outside.unlink()


def test_observe_retained_content_ignores_a_symlinked_directory_without_following_it(tmp_path):
    outside = tmp_path.parent / "outside_the_run_dir"
    outside.mkdir()
    (outside / "large.bin").write_bytes(b"o" * 10_000)
    try:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "linked-directory").symlink_to(outside, target_is_directory=True)

        assert observe_retained_content(run_dir) == {"bytes": "0"}
    finally:
        (outside / "large.bin").unlink()
        outside.rmdir()


def test_observe_retained_content_rejects_a_symlinked_run_directory(tmp_path):
    actual_run_dir = tmp_path / "actual"
    actual_run_dir.mkdir()
    (actual_run_dir / "output.bin").write_bytes(b"x" * 100)
    linked_run_dir = tmp_path / "linked"
    linked_run_dir.symlink_to(actual_run_dir, target_is_directory=True)

    assert observe_retained_content(linked_run_dir) == {
        "status": "unavailable",
        "issues": ["observation_incomplete"],
    }


def test_observe_retained_content_marks_a_disappearing_file_partial(tmp_path, monkeypatch):
    (tmp_path / "kept.bin").write_bytes(b"k" * 60)
    (tmp_path / "removed.bin").write_bytes(b"r" * 40)

    real_scandir = os.scandir

    def flaky_scandir(top):
        with real_scandir(top) as entries:
            for entry in entries:
                if entry.name == "removed.bin":
                    Path(entry.path).unlink()
                yield entry

    monkeypatch.setattr(collector.os, "scandir", flaky_scandir)

    assert observe_retained_content(tmp_path) == {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "bytes": "60",
    }


def test_observe_retained_content_marks_an_iteration_error_partial(tmp_path, monkeypatch):
    (tmp_path / "kept.bin").write_bytes(b"k" * 60)
    real_scandir = os.scandir

    def flaky_scandir(top):
        with real_scandir(top) as entries:
            yield from entries
        raise PermissionError("simulated traversal failure")

    monkeypatch.setattr(collector.os, "scandir", flaky_scandir)

    assert observe_retained_content(tmp_path) == {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "bytes": "60",
    }


def test_observe_retained_content_is_unavailable_when_root_cannot_be_opened(tmp_path, monkeypatch):
    def fail_before_yield(_root):
        raise PermissionError("denied")

    monkeypatch.setattr(collector.os, "scandir", fail_before_yield)

    assert observe_retained_content(tmp_path) == {
        "status": "unavailable",
        "issues": ["observation_incomplete"],
    }


@pytest.mark.parametrize("file_count", [3, 30])
def test_retained_entry_budget_returns_subtotal_and_closes_iterator(tmp_path, monkeypatch, file_count):
    for number in range(file_count):
        (tmp_path / f"{number}.bin").write_bytes(b"x")
    real_scandir = os.scandir
    closed = []

    def tracked_scandir(path):
        with real_scandir(path) as entries:
            try:
                yield from entries
            finally:
                closed.append(path)

    monkeypatch.setattr(collector, "_MAX_RETAINED_ENTRIES", 3)
    monkeypatch.setattr(collector.os, "scandir", tracked_scandir)

    result = observe_retained_content(tmp_path)
    assert result == (
        {"bytes": "3"} if file_count == 3 else {"status": "partial", "issues": ["observation_incomplete"], "bytes": "3"}
    )
    assert closed == [tmp_path]


def test_retained_depth_budget_keeps_shallower_files(tmp_path, monkeypatch):
    (tmp_path / "root.bin").write_bytes(b"xx")
    first = tmp_path / "first"
    second = first / "second"
    second.mkdir(parents=True)
    (first / "first.bin").write_bytes(b"xxx")
    (second / "omitted.bin").write_bytes(b"xxxxx")
    monkeypatch.setattr(collector, "_MAX_RETAINED_DEPTH", 1)

    assert observe_retained_content(tmp_path) == {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "bytes": "5",
    }


@pytest.mark.parametrize("observed_entries", [0, 2])
def test_retained_deadline_stops_between_entries(tmp_path, monkeypatch, observed_entries):
    for number in range(5):
        (tmp_path / f"{number}.bin").write_bytes(b"x")
    ticks = iter([0] + [0] * observed_entries + [1])
    monkeypatch.setattr(collector.time, "monotonic", lambda: next(ticks))

    result = observe_retained_content(tmp_path)

    assert result == (
        {"status": "partial", "issues": ["observation_incomplete"], "bytes": "2"}
        if observed_entries
        else {"status": "unavailable", "issues": ["observation_incomplete"]}
    )


def test_retained_unreadable_subdirectory_keeps_known_files(tmp_path, monkeypatch):
    (tmp_path / "kept.bin").write_bytes(b"xxx")
    inaccessible = tmp_path / "inaccessible"
    inaccessible.mkdir()
    real_scandir = os.scandir

    def limited_scandir(path):
        if Path(path) == inaccessible:
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr(collector.os, "scandir", limited_scandir)

    assert observe_retained_content(tmp_path) == {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "bytes": "3",
    }


def test_retained_overflow_keeps_a_schema_valid_subtotal(tmp_path, monkeypatch):
    (tmp_path / "first.bin").write_bytes(b"x" * 7)
    (tmp_path / "second.bin").write_bytes(b"x" * 7)
    monkeypatch.setattr(collector, "U128_MAX", 10)

    assert observe_retained_content(tmp_path) == {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "bytes": "7",
    }


def test_restored_collector_keeps_new_totals_but_marks_prior_interval_incomplete(tmp_path):
    ticks = iter([1_000_000_000, 3_000_000_000])
    job_collector = JobResourceCollector(
        tmp_path,
        clock_ns=lambda: next(ticks),
        capacity_probe=lambda: {
            "cpu": {"groups": [{"units": 2}]},
            "memory": {"bytes": 4096},
            "gpu": {"groups": []},
        },
        prior_observation_incomplete=True,
    )

    resource_capacity = job_collector.finish()["resource_capacity"]

    assert resource_capacity == {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "measured_seconds": "2",
        "cpu": {"groups": [{"units": "2"}]},
        "memory": {"bytes": "4096"},
        "gpu": {"groups": []},
    }


def test_cpu_duration_is_independent_of_missing_gpu_capacity(monkeypatch, tmp_path):
    from decimal import Decimal

    resource_ticks = iter((0, 10_000_000_000))
    cpu_ticks = iter((0, 10_000_000_000))
    usages = iter(((Decimal(0), Decimal(0)), (Decimal(2), Decimal(0))))
    # Inject the OS counter through the accountant constructor without changing
    # the collector's production wiring or the resource clock's two reads.
    original = collector.CpuConsumedAccountant
    monkeypatch.setattr(
        collector, "CpuConsumedAccountant", lambda **kwargs: original(usage_reader=lambda: next(usages), **kwargs)
    )
    job_collector = JobResourceCollector(
        tmp_path,
        clock_ns=lambda: next(resource_ticks),
        cpu_clock_ns=lambda: next(cpu_ticks),
        capacity_probe=lambda: {"cpu": {"groups": [{"units": 8}]}, "memory": {"bytes": 4096}},
    )

    handoff = job_collector.finish()

    assert handoff["resource_capacity"]["status"] == "partial"
    assert "gpu" not in handoff["resource_capacity"]
    assert handoff["cpu_consumed"] == {"seconds": "2", "measured_seconds": "10"}


def test_multinode_slurm_rank_zero_measurement_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("NVFL_NNODES", "4")
    ticks = iter([1_000_000_000, 3_000_000_000])
    job_collector = JobResourceCollector(
        tmp_path,
        clock_ns=lambda: next(ticks),
        capacity_probe=lambda: {
            "cpu": {"groups": [{"units": 8}]},
            "memory": {"bytes": 4096},
            "gpu": {"groups": []},
        },
    )

    resource_capacity = job_collector.finish()["resource_capacity"]

    assert resource_capacity == {"status": "unavailable", "issues": ["unsupported"]}


def test_missing_handoff_is_explicitly_unavailable():
    report = assemble_participant_summary(
        job_id="job-1",
        participant_name="site-1",
        child_handoff=None,
    )

    assert report["resource_capacity"] == {
        "status": "unavailable",
        "issues": ["observation_incomplete"],
    }
    assert report["message_traffic"] == {
        "status": "unavailable",
        "issues": ["observation_incomplete"],
    }


def test_final_handoff_preserves_partial_traffic_without_merging_parent_values(tmp_path):
    handoff = _minimal_handoff()
    handoff["message_traffic"] = {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "sent_bytes": "005.0",
        "received_bytes": "9.00",
    }
    write_terminal_handoff(tmp_path, handoff)
    report = assemble_participant_summary(
        job_id="job-1", participant_name="site-1", child_handoff=read_terminal_handoff(tmp_path)
    )
    assert report["message_traffic"] == {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "sent_bytes": "5",
        "received_bytes": "9",
    }


@pytest.mark.parametrize("field", ["sent_bytes", "received_bytes"])
def test_invalid_traffic_is_isolated_from_other_handoff_measurements(tmp_path, field):
    handoff = _minimal_handoff()
    handoff["workspace_filesystem"] = {"capacity_bytes": "1024"}
    handoff["message_traffic"] = {"sent_bytes": "5", "received_bytes": "7"}
    handoff["message_traffic"][field] = str(2**128)
    write_terminal_handoff(tmp_path, handoff)
    report = assemble_participant_summary(
        job_id="job-1", participant_name="site-1", child_handoff=read_terminal_handoff(tmp_path)
    )
    assert report["message_traffic"] == {"status": "unavailable", "issues": ["malformed_source"]}
    assert report["workspace_filesystem"] == {"capacity_bytes": "1024"}


def _minimal_handoff():
    return {
        "internal_version": INTERNAL_HANDOFF_VERSION,
        "kind": INTERNAL_HANDOFF_KIND,
        "resource_capacity": {"status": "unavailable", "issues": ["observation_incomplete"]},
        "cpu_consumed": {"status": "unavailable", "issues": ["observation_incomplete"]},
        "workspace_filesystem": {"status": "unavailable", "issues": ["observation_incomplete"]},
        "retained_content": {"status": "unavailable", "issues": ["unsupported"]},
        "message_traffic": {"status": "unavailable", "issues": ["observation_incomplete"]},
    }


def test_bad_cpu_consumed_handoff_does_not_erase_other_dimensions(tmp_path):
    handoff = _minimal_handoff()
    handoff["workspace_filesystem"] = {"capacity_bytes": "1024"}
    handoff["cpu_consumed"] = {"seconds": "NaN"}
    write_terminal_handoff(tmp_path, handoff)
    report = assemble_participant_summary(
        job_id="job-1", participant_name="site-1", child_handoff=read_terminal_handoff(tmp_path)
    )
    assert report["cpu_consumed"] == {"status": "unavailable", "issues": ["malformed_source"]}
    assert report["workspace_filesystem"] == {"capacity_bytes": "1024"}


def test_terminal_handoff_requires_cpu_consumed(tmp_path):
    handoff = _minimal_handoff()
    del handoff["cpu_consumed"]

    with pytest.raises(InvalidTerminalHandoff, match="terminal handoff fields"):
        write_terminal_handoff(tmp_path, handoff)


def test_terminal_handoff_rejects_old_runtime_count_basis(tmp_path):
    old_handoff = _minimal_handoff()
    old_handoff["internal_version"] = "1"

    with pytest.raises(InvalidTerminalHandoff, match="unsupported version"):
        write_terminal_handoff(tmp_path, old_handoff)


def test_handoff_reader_rejects_symlink(tmp_path):
    target_run = tmp_path / "target"
    target = write_terminal_handoff(target_run, _minimal_handoff())
    link_run = tmp_path / "link"
    link = terminal_handoff_path(link_run)
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this platform")

    assert read_terminal_handoff(link_run) is None


def test_handoff_parent_does_not_follow_intermediate_staging_symlink(tmp_path):
    outside_run = tmp_path / "outside"
    outside_handoff = write_terminal_handoff(outside_run, _minimal_handoff())
    run_dir = tmp_path / "run"
    stats_dir = run_dir / RESOURCE_STATS_DIR
    stats_dir.mkdir(parents=True)
    try:
        (stats_dir / STAGING_DIR).symlink_to(outside_handoff.parent, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symlinks are unavailable on this platform")

    assert read_terminal_handoff(run_dir) is None
    remove_terminal_handoff(run_dir)

    assert outside_handoff.exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable on this platform")
def test_handoff_reader_rejects_fifo_without_blocking(tmp_path):
    run_dir = tmp_path / "fifo"
    path = terminal_handoff_path(run_dir)
    path.parent.mkdir(parents=True)
    os.mkfifo(path)

    assert read_terminal_handoff(run_dir) is None
