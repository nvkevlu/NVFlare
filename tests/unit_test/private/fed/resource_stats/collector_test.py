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

import ctypes
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from nvflare.private.fed.resource_stats import collector
from nvflare.private.fed.resource_stats.collector import (
    ClockOrderError,
    JobResourceCollector,
    ResourceTimeAccumulator,
    assemble_participant_summary,
    canonical_json_bytes,
    probe_gpu,
    read_terminal_handoff,
    remove_terminal_handoff,
    terminal_handoff_path,
    write_terminal_handoff,
)
from nvflare.private.fed.resource_stats.contract import load_and_validate


def test_monotonic_ns_is_private_and_output_is_compact_seconds():
    ticks = iter([9_000_000_000_000_000_001, 9_000_000_002_000_126_790])
    accumulator = ResourceTimeAccumulator(clock_ns=lambda: next(ticks))

    accumulator.observe(
        {
            "cpu": {"units": "8", "model": "AMD EPYC 9654", "architecture": "x86_64"},
            "memory": {"bytes": "68719476736"},
            "gpu": {"groups": [{"kind": "full_gpu", "count": 2, "model": "NVIDIA H100 80GB HBM3"}]},
        }
    )
    result = accumulator.finish()

    assert result["measured_seconds"] == "2.000126789"
    assert result["cpu"]["groups"][0]["unit_seconds"] == "16.001014312"
    assert result["gpu"]["groups"][0]["instance_seconds"] == "4.000253578"
    assert "9000000000000000001" not in str(result)


def test_capacity_change_closes_one_interval_and_starts_the_next():
    ticks = iter([10, 1_000_000_010, 2_000_000_010])
    accumulator = ResourceTimeAccumulator(clock_ns=lambda: next(ticks))
    common = {"memory": {"bytes": 1024}, "gpu": {"groups": []}}

    accumulator.observe({"cpu": {"units": 8}, **common})
    accumulator.observe({"cpu": {"units": 4}, **common})
    result = accumulator.finish()

    assert result["measured_seconds"] == "2"
    assert result["cpu"]["groups"] == [{"unit_seconds": "12"}]
    assert result["memory"]["byte_seconds"] == "2048"
    assert result["gpu"] == {"groups": []}


def test_clock_must_not_move_backwards():
    ticks = iter([20, 19])
    accumulator = ResourceTimeAccumulator(clock_ns=lambda: next(ticks))
    accumulator.observe({"cpu": {"units": 1}})

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
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.os, "sched_getaffinity", lambda _pid: set(range(8)), raising=False)
    monkeypatch.setattr(
        collector,
        "_cgroup_location",
        lambda controller: (mount, leaf, "v2") if controller is None else (None, None, "none"),
    )
    monkeypatch.setattr(collector, "_ancestors", lambda _directory, _mount: [leaf, mount])
    monkeypatch.setattr(
        collector,
        "_read_cgroup_file",
        lambda path: values.get(path, collector._CGROUP_FILE_MISSING),
    )
    monkeypatch.setattr(collector, "_cpu_identity", lambda _affinity: {})

    assert collector.probe_cpu() == {"groups": [{"units": "0.666666666"}]}


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

    def location(controller):
        if controller is None:
            return None, None, "none"
        if controller == "cpuset":
            return cpuset_mount, cpuset_leaf, "v1"
        if controller == "cpu":
            return cpu_mount, cpu_leaf, "v1"
        return None, None, "none"

    def ancestors(directory, mount):
        return [directory, mount]

    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.os, "sched_getaffinity", lambda _pid: set(range(8)), raising=False)
    monkeypatch.setattr(collector, "_cgroup_location", location)
    monkeypatch.setattr(collector, "_ancestors", ancestors)
    monkeypatch.setattr(
        collector,
        "_read_cgroup_file",
        lambda path: values.get(path, collector._CGROUP_FILE_MISSING),
    )
    monkeypatch.setattr(collector, "_cpu_identity", lambda _affinity: {})

    assert collector.probe_cpu() == {"groups": [{"units": "0.666666666"}]}


@pytest.mark.parametrize("bad_value", ["garbage", collector._CGROUP_FILE_UNREADABLE])
def test_v2_cpu_does_not_fall_back_when_applicable_quota_is_invalid(monkeypatch, bad_value):
    mount = Path("/sys/fs/cgroup")
    leaf = mount / "job"
    values = {
        leaf / "cpuset.cpus.effective": "0-7",
        leaf / "cpu.max": bad_value,
        mount / "cpu.max": "max 100000",
    }
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.os, "sched_getaffinity", lambda _pid: set(range(8)), raising=False)
    monkeypatch.setattr(
        collector,
        "_cgroup_location",
        lambda controller: (mount, leaf, "v2") if controller is None else (None, None, "none"),
    )
    monkeypatch.setattr(collector, "_ancestors", lambda _directory, _mount: [leaf, mount])
    monkeypatch.setattr(
        collector,
        "_read_cgroup_file",
        lambda path: values.get(path, collector._CGROUP_FILE_MISSING),
    )

    assert collector.probe_cpu() is None


def test_v2_cpu_accepts_explicit_unlimited_quota(monkeypatch):
    mount = Path("/sys/fs/cgroup")
    leaf = mount / "job"
    values = {
        leaf / "cpuset.cpus.effective": "0-3",
        leaf / "cpu.max": "max 100000",
        mount / "cpu.max": "max 100000",
    }
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.os, "sched_getaffinity", lambda _pid: set(range(8)), raising=False)
    monkeypatch.setattr(
        collector,
        "_cgroup_location",
        lambda controller: (mount, leaf, "v2") if controller is None else (None, None, "none"),
    )
    monkeypatch.setattr(collector, "_ancestors", lambda _directory, _mount: [leaf, mount])
    monkeypatch.setattr(
        collector,
        "_read_cgroup_file",
        lambda path: values.get(path, collector._CGROUP_FILE_MISSING),
    )
    monkeypatch.setattr(collector, "_cpu_identity", lambda _affinity: {})

    assert collector.probe_cpu() == {"groups": [{"units": "4"}]}


def test_v1_cpu_does_not_fall_back_when_applicable_quota_is_malformed(monkeypatch):
    cpu_mount = Path("/sys/fs/cgroup/cpu")
    cpu_leaf = cpu_mount / "job"
    values = {
        cpu_leaf / "cpu.cfs_quota_us": "bad",
        cpu_leaf / "cpu.cfs_period_us": "100000",
    }

    def location(controller):
        if controller == "cpu":
            return cpu_mount, cpu_leaf, "v1"
        return None, None, "none"

    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.os, "sched_getaffinity", lambda _pid: set(range(8)), raising=False)
    monkeypatch.setattr(collector, "_cgroup_location", location)
    monkeypatch.setattr(collector, "_ancestors", lambda _directory, _mount: [cpu_leaf])
    monkeypatch.setattr(
        collector,
        "_read_cgroup_file",
        lambda path: values.get(path, collector._CGROUP_FILE_MISSING),
    )

    assert collector.probe_cpu() is None


@pytest.mark.parametrize("bad_value", ["garbage", collector._CGROUP_FILE_UNREADABLE])
def test_v2_memory_does_not_fall_back_when_applicable_limit_is_invalid(monkeypatch, bad_value):
    mount = Path("/sys/fs/cgroup")
    leaf = mount / "job"
    values = {
        leaf / "memory.max": bad_value,
        mount / "memory.max": "max",
    }
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.os, "sysconf", lambda key: {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 1024}[key])
    monkeypatch.setattr(
        collector,
        "_cgroup_location",
        lambda controller: (mount, leaf, "v2") if controller is None else (None, None, "none"),
    )
    monkeypatch.setattr(collector, "_ancestors", lambda _directory, _mount: [leaf, mount])
    monkeypatch.setattr(
        collector,
        "_read_cgroup_file",
        lambda path: values.get(path, collector._CGROUP_FILE_MISSING),
    )

    assert collector.probe_memory() is None


def test_v2_memory_accepts_explicit_unlimited_limit(monkeypatch):
    mount = Path("/sys/fs/cgroup")
    leaf = mount / "job"
    values = {
        leaf / "memory.max": "max",
        mount / "memory.max": "max",
    }
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.os, "sysconf", lambda key: {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 1024}[key])
    monkeypatch.setattr(
        collector,
        "_cgroup_location",
        lambda controller: (mount, leaf, "v2") if controller is None else (None, None, "none"),
    )
    monkeypatch.setattr(collector, "_ancestors", lambda _directory, _mount: [leaf, mount])
    monkeypatch.setattr(
        collector,
        "_read_cgroup_file",
        lambda path: values.get(path, collector._CGROUP_FILE_MISSING),
    )

    assert collector.probe_memory() == {"bytes": str(4096 * 1024)}


@pytest.mark.parametrize("bad_value", ["garbage", collector._CGROUP_FILE_UNREADABLE])
def test_v1_memory_does_not_fall_back_when_applicable_limit_is_invalid(monkeypatch, bad_value):
    mount = Path("/sys/fs/cgroup/memory")
    leaf = mount / "job"
    values = {leaf / "memory.limit_in_bytes": bad_value}
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.os, "sysconf", lambda key: {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 1024}[key])
    monkeypatch.setattr(
        collector,
        "_cgroup_location",
        lambda controller: (mount, leaf, "v1") if controller == "memory" else (None, None, "none"),
    )
    monkeypatch.setattr(collector, "_ancestors", lambda _directory, _mount: [leaf])
    monkeypatch.setattr(
        collector,
        "_read_cgroup_file",
        lambda path: values.get(path, collector._CGROUP_FILE_MISSING),
    )

    assert collector.probe_memory() is None


def test_v1_memory_accepts_kernel_unlimited_sentinel(monkeypatch):
    mount = Path("/sys/fs/cgroup/memory")
    leaf = mount / "job"
    values = {leaf / "memory.limit_in_bytes": "9223372036854771712"}
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    monkeypatch.setattr(collector.os, "sysconf", lambda key: {"SC_PAGE_SIZE": 4096, "SC_PHYS_PAGES": 1024}[key])
    monkeypatch.setattr(
        collector,
        "_cgroup_location",
        lambda controller: (mount, leaf, "v1") if controller == "memory" else (None, None, "none"),
    )
    monkeypatch.setattr(collector, "_ancestors", lambda _directory, _mount: [leaf])
    monkeypatch.setattr(
        collector,
        "_read_cgroup_file",
        lambda path: values.get(path, collector._CGROUP_FILE_MISSING),
    )

    assert collector.probe_memory() == {"bytes": str(4096 * 1024)}


def test_raw_cuda_visible_devices_is_not_numeric_authority(monkeypatch):
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0,1")
    monkeypatch.setattr(collector, "_load_library", lambda candidates: None)
    monkeypatch.setattr(collector, "_load_bundled_cuda_runtime", lambda: None)

    assert probe_gpu() is None


class _FakeFunction:
    def __init__(self, implementation):
        self.implementation = implementation

    def __call__(self, *args):
        return self.implementation(*args)


def _make_cuda_runtime_distribution(root: Path, name: str, runtime_paths: list[str]) -> list[Path]:
    distribution_dir = root / (name.replace("-", "_") + "-13.0.dist-info")
    distribution_dir.mkdir(parents=True)
    (distribution_dir / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: 13.0\n",
        encoding="utf-8",
    )
    files = []
    for relative_path in runtime_paths:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not-a-real-library")
        files.append(path)
    (distribution_dir / "RECORD").write_text(
        "".join(f"{relative_path},,\n" for relative_path in runtime_paths),
        encoding="utf-8",
    )
    return files


def test_bundled_cuda_runtime_is_resolved_from_allowlisted_distribution(monkeypatch, tmp_path):
    runtime = _make_cuda_runtime_distribution(
        tmp_path,
        "nvidia-cuda-runtime-cu13",
        ["nvidia/cu13/lib/libcudart.so.13"],
    )[0]
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")

    assert collector._find_bundled_cuda_runtime_path((str(tmp_path),)) == runtime.resolve()


def test_bundled_cuda_runtime_rejects_unowned_and_ambiguous_files(monkeypatch, tmp_path):
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    unowned_root = tmp_path / "unowned"
    _make_cuda_runtime_distribution(
        unowned_root,
        "some-framework",
        ["framework/lib/libcudart.so.13"],
    )
    assert collector._find_bundled_cuda_runtime_path((str(unowned_root),)) is None

    ambiguous_root = tmp_path / "ambiguous"
    _make_cuda_runtime_distribution(
        ambiguous_root,
        "nvidia-cuda-runtime",
        ["nvidia/cu13/lib/libcudart.so.13", "nvidia/cu13/lib/libcudart.so.13.0"],
    )
    assert collector._find_bundled_cuda_runtime_path((str(ambiguous_root),)) is None


def test_bundled_cuda_runtime_accepts_contained_aliases_of_one_file(monkeypatch, tmp_path):
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    target = _make_cuda_runtime_distribution(
        tmp_path,
        "nvidia-cuda-runtime",
        ["nvidia/cu13/lib/libcudart.so.13.0"],
    )[0]
    alias = target.with_name("libcudart.so.13")
    alias.symlink_to(target.name)
    distribution_dir = tmp_path / "nvidia_cuda_runtime-13.0.dist-info"
    (distribution_dir / "RECORD").write_text(
        "nvidia/cu13/lib/libcudart.so.13.0,,\nnvidia/cu13/lib/libcudart.so.13,,\n",
        encoding="utf-8",
    )

    assert collector._find_bundled_cuda_runtime_path((str(tmp_path),)) == target.resolve()


def test_bundled_cuda_runtime_rejects_distribution_path_escape(monkeypatch, tmp_path):
    monkeypatch.setattr(collector.platform, "system", lambda: "Linux")
    root = tmp_path / "site-packages"
    outside = tmp_path / "outside" / "libcudart.so.13"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"not-a-real-library")
    distribution_dir = root / "nvidia_cuda_runtime-13.0.dist-info"
    distribution_dir.mkdir(parents=True)
    (distribution_dir / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: nvidia-cuda-runtime\nVersion: 13.0\n",
        encoding="utf-8",
    )
    (distribution_dir / "RECORD").write_text("../outside/libcudart.so.13,,\n", encoding="utf-8")

    assert collector._find_bundled_cuda_runtime_path((str(root),)) is None


def test_probe_gpu_uses_bundled_runtime_only_after_loader_lookup_fails(monkeypatch):
    def get_count(pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int))[0] = 0
        return 0

    bundled_runtime = SimpleNamespace(cudaGetDeviceCount=_FakeFunction(get_count))
    monkeypatch.setattr(collector, "_load_library", lambda candidates: None)
    monkeypatch.setattr(collector, "_load_bundled_cuda_runtime", lambda: bundled_runtime)

    assert probe_gpu() == {"groups": []}


def test_probe_gpu_uses_bundled_runtime_when_loader_runtime_cannot_enumerate(monkeypatch):
    def get_count(pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int))[0] = 0
        return 0

    loader_runtime = SimpleNamespace(cudaGetDeviceCount=_FakeFunction(lambda _pointer: 100))
    bundled_runtime = SimpleNamespace(cudaGetDeviceCount=_FakeFunction(get_count))
    monkeypatch.setattr(collector, "_load_library", lambda candidates: loader_runtime)
    monkeypatch.setattr(collector, "_load_bundled_cuda_runtime", lambda: bundled_runtime)

    assert probe_gpu() == {"groups": []}


def test_successful_cuda_runtime_zero_is_authoritative(monkeypatch):
    def get_count(pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int))[0] = 0
        return 0

    cudart = SimpleNamespace(cudaGetDeviceCount=_FakeFunction(get_count))
    monkeypatch.setattr(collector, "_load_library", lambda candidates: cudart)

    assert probe_gpu() == {"groups": []}


def test_cuda_no_device_error_is_unavailable_not_numeric_zero(monkeypatch):
    cudart = SimpleNamespace(cudaGetDeviceCount=_FakeFunction(lambda _pointer: 100))
    monkeypatch.setattr(collector, "_load_library", lambda candidates: cudart)
    monkeypatch.setattr(collector, "_load_bundled_cuda_runtime", lambda: None)

    assert probe_gpu() is None


def test_positive_cuda_devices_are_grouped_only_after_driver_and_nvml_uuid_match(monkeypatch):
    uuids = (bytes(range(16)), bytes(range(16, 32)))

    def get_count(pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int))[0] = 2
        return 0

    def get_driver_count(pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int))[0] = 2
        return 0

    def get_device(pointer, ordinal):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int))[0] = ordinal
        return 0

    def get_uuid(pointer, device):
        target = ctypes.cast(pointer, ctypes.POINTER(collector._CudaUuid)).contents
        for offset, value in enumerate(uuids[device]):
            target.bytes[offset] = value
        return 0

    cudart = SimpleNamespace(cudaGetDeviceCount=_FakeFunction(get_count))
    cuda_driver = SimpleNamespace(
        cuInit=_FakeFunction(lambda _flags: 0),
        cuDeviceGetCount=_FakeFunction(get_driver_count),
        cuDeviceGet=_FakeFunction(get_device),
        cuDeviceGetUuid_v2=_FakeFunction(get_uuid),
    )
    handles = {}
    for index, value in enumerate(uuids):
        bare = collector._uuid_text(collector._CudaUuid((ctypes.c_ubyte * 16)(*value)))
        prefix = "GPU-" if index == 0 else "MIG-"
        handles[(prefix + bare).encode()] = 100 + index

    def get_handle(uuid, pointer):
        value = handles.get(uuid)
        if value is None:
            return 1
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_void_p))[0] = value
        return 0

    def is_mig(handle, pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint))[0] = int(handle.value == 101)
        return 0

    def get_name(handle, buffer, _size):
        buffer.value = b"NVIDIA A100 80GB" if handle.value == 100 else b"NVIDIA A100 MIG 1g.10gb"
        return 0

    def get_memory(handle, pointer):
        value = 80 * 2**30 if handle.value == 100 else 10 * 2**30
        ctypes.cast(pointer, ctypes.POINTER(collector._NvmlMemory)).contents.total = value
        return 0

    nvml = SimpleNamespace(
        nvmlInit_v2=_FakeFunction(lambda: 0),
        nvmlShutdown=_FakeFunction(lambda: 0),
        nvmlDeviceGetHandleByUUID=_FakeFunction(get_handle),
        nvmlDeviceIsMigDeviceHandle=_FakeFunction(is_mig),
        nvmlDeviceGetName=_FakeFunction(get_name),
        nvmlDeviceGetMemoryInfo=_FakeFunction(get_memory),
    )
    libraries = iter((cudart, nvml, cuda_driver))
    monkeypatch.setattr(collector, "_load_library", lambda candidates: next(libraries))

    assert probe_gpu() == {
        "groups": [
            {
                "kind": "full_gpu",
                "count": 1,
                "model": "NVIDIA A100 80GB",
                "memory_bytes": str(80 * 2**30),
            },
            {
                "kind": "mig_compute_instance",
                "count": 1,
                "model": "NVIDIA A100 MIG 1g.10gb",
                "memory_bytes": str(10 * 2**30),
            },
        ]
    }


def test_cuda_driver_uuid_fallback_requires_matching_runtime_count(monkeypatch):
    def get_driver_count(pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int))[0] = 2
        return 0

    cuda_driver = SimpleNamespace(
        cuInit=_FakeFunction(lambda _flags: 0),
        cuDeviceGetCount=_FakeFunction(get_driver_count),
        cuDeviceGet=_FakeFunction(lambda _pointer, _ordinal: 0),
        cuDeviceGetUuid_v2=_FakeFunction(lambda _pointer, _device: 0),
    )
    monkeypatch.setattr(collector, "_load_library", lambda candidates: cuda_driver)

    assert collector._cuda_uuid_reader(expected_count=1) is None


def test_cuda_driver_uuid_reader_rejects_legacy_uuid_api(monkeypatch):
    cuda_driver = SimpleNamespace(
        cuInit=_FakeFunction(lambda _flags: 0),
        cuDeviceGetCount=_FakeFunction(lambda _pointer: 0),
        cuDeviceGet=_FakeFunction(lambda _pointer, _ordinal: 0),
        cuDeviceGetUuid=_FakeFunction(lambda _pointer, _device: 0),
    )
    monkeypatch.setattr(collector, "_load_library", lambda candidates: cuda_driver)

    assert collector._cuda_uuid_reader(expected_count=1) is None


def test_positive_cuda_count_without_nvml_is_not_reported(monkeypatch):
    def get_count(pointer):
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int))[0] = 1
        return 0

    cudart = SimpleNamespace(cudaGetDeviceCount=_FakeFunction(get_count))
    libraries = iter((cudart, None))
    monkeypatch.setattr(collector, "_load_library", lambda candidates: next(libraries))

    assert probe_gpu() is None


def test_handoff_to_public_report_round_trip(tmp_path):
    ticks = iter([1_000_000_000, 3_000_000_000])
    job_collector = JobResourceCollector(
        tmp_path,
        clock_ns=lambda: next(ticks),
        capacity_probe=lambda: {
            "cpu": {"units": 2, "model": "AMD EPYC 9654", "architecture": "x86_64"},
            "memory": {"bytes": 4096},
            "gpu": {"groups": []},
        },
    )

    path = write_terminal_handoff(tmp_path, job_collector.finish())
    assert path == terminal_handoff_path(tmp_path)
    handoff = read_terminal_handoff(tmp_path)
    report = assemble_participant_summary(job_id="job-1", participant_name="site-1", child_handoff=handoff)
    encoded = canonical_json_bytes(report)

    assert load_and_validate(encoded)["participant_name"] == "site-1"
    assert report["resource_time"]["measured_seconds"] == "2"
    assert report["workspace_filesystem"]["status"] == "reported"
    assert report["retained_content"] == {"status": "unavailable", "issues": ["not_bound"]}
    assert report["f3"] == {"status": "unavailable", "issues": ["not_bound"]}
    assert "participant_key" not in encoded.decode()


def test_restored_collector_keeps_new_totals_but_marks_prior_interval_incomplete(tmp_path):
    ticks = iter([1_000_000_000, 3_000_000_000])
    job_collector = JobResourceCollector(
        tmp_path,
        clock_ns=lambda: next(ticks),
        capacity_probe=lambda: {
            "cpu": {"units": 2},
            "memory": {"bytes": 4096},
            "gpu": {"groups": []},
        },
        prior_observation_incomplete=True,
    )

    resource_time = job_collector.finish()["resource_time"]

    assert resource_time == {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "measured_seconds": "2",
        "cpu": {"groups": [{"unit_seconds": "4"}]},
        "memory": {"byte_seconds": "8192"},
        "gpu": {"groups": []},
    }


def test_multinode_slurm_rank_zero_measurement_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("NVFL_NNODES", "4")
    ticks = iter([1_000_000_000, 3_000_000_000])
    job_collector = JobResourceCollector(
        tmp_path,
        clock_ns=lambda: next(ticks),
        capacity_probe=lambda: {
            "cpu": {"units": 8},
            "memory": {"bytes": 4096},
            "gpu": {"groups": []},
        },
    )

    resource_time = job_collector.finish()["resource_time"]

    assert resource_time == {"status": "unavailable", "issues": ["unsupported"]}


def test_missing_handoff_is_explicitly_unavailable():
    report = assemble_participant_summary(job_id="job-1", participant_name="site-1", child_handoff=None)

    assert report["resource_time"] == {
        "status": "unavailable",
        "issues": ["observation_incomplete"],
    }


def _minimal_handoff():
    return {
        "internal_version": collector.INTERNAL_HANDOFF_VERSION,
        "kind": collector.INTERNAL_HANDOFF_KIND,
        "resource_time": {"status": "unavailable", "issues": ["observation_incomplete"]},
        "workspace_filesystem": {"status": "unavailable", "issues": ["observation_incomplete"]},
        "retained_content": {"status": "unavailable", "issues": ["not_bound"]},
        "child_f3": {"status": "unavailable", "issues": ["not_bound"]},
    }


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
    stats_dir = run_dir / collector.RESOURCE_STATS_DIR
    stats_dir.mkdir(parents=True)
    try:
        (stats_dir / collector.STAGING_DIR).symlink_to(outside_handoff.parent, target_is_directory=True)
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
