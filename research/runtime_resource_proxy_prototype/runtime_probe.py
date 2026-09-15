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

"""Research-only probe for the Phase 1 runtime-visible capacity contract.

This is deliberately outside ``nvflare/``.  It proves the collection rules for
CPU, memory, and the job-run filesystem with no third-party dependencies.  GPU
collection is an explicit adapter seam: a production implementation must use a
CUDA-runtime enumeration first, then optionally use NVML for enrichment.
"""

import argparse
import datetime
import json
import os
import platform
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Optional, Protocol


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _decode_mountinfo(value: str) -> str:
    """Decode the octal escape sequences used by /proc/self/mountinfo."""

    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def _mount_entries() -> list[dict[str, str]]:
    text = _read_text(Path("/proc/self/mountinfo"))
    if text is None:
        return []

    entries = []
    for line in text.splitlines():
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        left = before.split()
        right = after.split()
        if len(left) < 5 or len(right) < 3:
            continue
        entries.append(
            {
                "root": _decode_mountinfo(left[3]),
                "mount_point": _decode_mountinfo(left[4]),
                "fs_type": right[0],
                "super_options": right[2],
            }
        )
    return entries


def _cgroup_records() -> list[tuple[list[str], str]]:
    text = _read_text(Path("/proc/self/cgroup"))
    if text is None:
        return []

    records = []
    for line in text.splitlines():
        _hierarchy, separator, remainder = line.partition(":")
        if not separator:
            continue
        controllers, separator, relative_path = remainder.partition(":")
        if not separator:
            continue
        records.append((controllers.split(",") if controllers else [], relative_path))
    return records


def _path_under_mount(mount: dict[str, str], cgroup_path: str) -> Optional[Path]:
    root = mount["root"].rstrip("/") or "/"
    relative = cgroup_path
    if root != "/":
        if relative == root:
            relative = ""
        elif relative.startswith(root + "/"):
            relative = relative[len(root) :]
        else:
            return None
    return Path(mount["mount_point"]) / relative.lstrip("/")


def _cgroup_v2_location() -> tuple[Optional[Path], Optional[Path]]:
    cgroup_path = next((path for controllers, path in _cgroup_records() if not controllers), None)
    mount = next((entry for entry in _mount_entries() if entry["fs_type"] == "cgroup2"), None)
    if cgroup_path is None or mount is None:
        return None, None
    mount_point = Path(mount["mount_point"])
    return mount_point, _path_under_mount(mount, cgroup_path)


def _cgroup_v1_location(controller: str) -> tuple[Optional[Path], Optional[Path]]:
    cgroup_path = next((path for controllers, path in _cgroup_records() if controller in controllers), None)
    if cgroup_path is None:
        return None, None
    for mount in _mount_entries():
        if mount["fs_type"] != "cgroup":
            continue
        options = set(mount["super_options"].split(","))
        if controller in options:
            mount_point = Path(mount["mount_point"])
            return mount_point, _path_under_mount(mount, cgroup_path)
    return None, None


def _ancestors(cgroup_dir: Path, mount_point: Path) -> list[Path]:
    """Return leaf-to-root cgroup directories without emitting their paths."""

    if cgroup_dir != mount_point and mount_point not in cgroup_dir.parents:
        return []
    dirs = []
    current = cgroup_dir
    while True:
        dirs.append(current)
        if current == mount_point or current.parent == current:
            break
        current = current.parent
    return dirs


def _finite_v2_cpu_quota() -> tuple[Optional[float], list[dict[str, int]]]:
    mount_point, cgroup_dir = _cgroup_v2_location()
    if cgroup_dir is None or mount_point is None:
        return None, []
    quotas = []
    for directory in _ancestors(cgroup_dir, mount_point):
        tokens = (_read_text(directory / "cpu.max") or "").split()
        if len(tokens) != 2 or tokens[0] == "max":
            continue
        try:
            quota_us, period_us = int(tokens[0]), int(tokens[1])
        except ValueError:
            continue
        if quota_us > 0 and period_us > 0:
            quotas.append({"quota_us": quota_us, "period_us": period_us})
    if not quotas:
        return None, []
    return min(item["quota_us"] / item["period_us"] for item in quotas), quotas


def _finite_v1_cpu_quota() -> tuple[Optional[float], list[dict[str, int]]]:
    mount_point, cgroup_dir = _cgroup_v1_location("cpu")
    if cgroup_dir is None or mount_point is None:
        return None, []
    quotas = []
    for directory in _ancestors(cgroup_dir, mount_point):
        quota_text = _read_text(directory / "cpu.cfs_quota_us")
        period_text = _read_text(directory / "cpu.cfs_period_us")
        try:
            quota_us = int(quota_text) if quota_text is not None else -1
            period_us = int(period_text) if period_text is not None else 0
        except ValueError:
            continue
        if quota_us > 0 and period_us > 0:
            quotas.append({"quota_us": quota_us, "period_us": period_us})
    if not quotas:
        return None, []
    return min(item["quota_us"] / item["period_us"] for item in quotas), quotas


def _finite_memory_max() -> tuple[Optional[int], str, list[int]]:
    mount_point, cgroup_dir = _cgroup_v2_location()
    if cgroup_dir is not None and mount_point is not None:
        limits = []
        for directory in _ancestors(cgroup_dir, mount_point):
            value = _read_text(directory / "memory.max")
            if value in (None, "max"):
                continue
            try:
                limit = int(value)
            except ValueError:
                continue
            if limit > 0:
                limits.append(limit)
        return (min(limits), "cgroup_v2", limits) if limits else (None, "cgroup_v2", [])

    mount_point, cgroup_dir = _cgroup_v1_location("memory")
    if cgroup_dir is not None and mount_point is not None:
        limits = []
        for directory in _ancestors(cgroup_dir, mount_point):
            value = _read_text(directory / "memory.limit_in_bytes")
            try:
                limit = int(value) if value is not None else 0
            except ValueError:
                continue
            # cgroup v1 commonly represents unlimited with a near-INT64_MAX value.
            if 0 < limit < (1 << 60):
                limits.append(limit)
        return (min(limits), "cgroup_v1", limits) if limits else (None, "cgroup_v1", [])

    return None, "none", []


def _online_cpu_count() -> Optional[int]:
    try:
        value = os.sysconf("SC_NPROCESSORS_ONLN")
    except (AttributeError, OSError, ValueError):
        value = os.cpu_count()
    return value if isinstance(value, int) and value > 0 else None


def _physical_memory_bytes() -> Optional[int]:
    try:
        value = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None
    return value if isinstance(value, int) and value > 0 else None


def _metric(
    name: str,
    value: Optional[float | int],
    unit: str,
    source: str,
    *,
    status: str = "reported",
    coverage: str = "complete",
    caveats: Optional[list[str]] = None,
    inputs: Optional[dict[str, Any]] = None,
    dimensions: Optional[dict[str, Any]] = None,
    scope: str = "execution_environment",
    sharing: str = "unknown",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": name,
        "value": value,
        "unit": unit,
        "source": source,
        "basis": "runtime_visible_capacity_proxy",
        "scope": scope,
        "sharing": sharing,
        "status": status,
        "observed_at": _utc_now(),
        "coverage": coverage,
        "caveat_codes": caveats or ["CAPACITY_NOT_ALLOCATION_OR_BILLING"],
    }
    if inputs:
        result["inputs"] = inputs
    if dimensions:
        result["dimensions"] = dimensions
    return result


def probe_cpu(allow_host_fallback: bool = False) -> dict[str, Any]:
    if platform.system() != "Linux":
        if allow_host_fallback:
            online_count = _online_cpu_count()
            if online_count is not None:
                return _metric(
                    "visible_cpu_units",
                    online_count,
                    "cpu_units",
                    f"{platform.system().lower()}.sysconf.SC_NPROCESSORS_ONLN",
                    status="partial",
                    coverage="partial",
                    caveats=[
                        "NON_LINUX_HOST_FALLBACK_PROTOTYPE_ONLY",
                        "NO_CGROUP_LIMIT_QUERY",
                        "NO_PROCESS_AFFINITY_QUERY",
                        "LOGICAL_CPU_UNITS_NOT_PERFORMANCE_NORMALIZED",
                        "CPU_CAPACITY_MAY_BE_SHARED",
                    ],
                    inputs={"online_logical_cpu_count": online_count},
                )
        return _metric(
            "visible_cpu_units",
            None,
            "cpu_units",
            "linux.sched_getaffinity+cgroup",
            status="unavailable",
            coverage="none",
            caveats=["UNSUPPORTED_PLATFORM"],
            inputs={"reason": "Phase 1 prototype supports Linux only"},
        )

    try:
        affinity_count = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity_count = None
    online_count = _online_cpu_count()

    quota, quota_inputs = _finite_v2_cpu_quota()
    _mount_point, v2_cgroup_dir = _cgroup_v2_location()
    cgroup_version = "v2" if v2_cgroup_dir is not None else "v1"
    if quota is None and cgroup_version == "v1":
        quota, quota_inputs = _finite_v1_cpu_quota()

    candidates = [value for value in (affinity_count, quota) if value is not None]
    if not candidates and online_count is not None:
        candidates.append(online_count)
    if not candidates:
        return _metric(
            "visible_cpu_units",
            None,
            "cpu_units",
            "linux.sched_getaffinity+cgroup",
            status="unavailable",
            coverage="none",
            caveats=["CPU_VISIBILITY_UNREADABLE"],
        )

    source_parts = []
    if affinity_count is not None:
        source_parts.append("sched_getaffinity")
    if quota is not None:
        source_parts.append(f"cgroup_{cgroup_version}.cpu_quota")
    if not source_parts:
        source_parts.append("SC_NPROCESSORS_ONLN")
    return _metric(
        "visible_cpu_units",
        round(min(candidates), 6),
        "cpu_units",
        "+".join(source_parts),
        coverage="partial" if affinity_count is None else "complete",
        inputs={
            "affinity_logical_cpu_count": affinity_count,
            "online_logical_cpu_count": online_count,
            "cgroup_cpu_quotas": quota_inputs,
        },
    )


def probe_memory(allow_host_fallback: bool = False) -> dict[str, Any]:
    if platform.system() != "Linux":
        if allow_host_fallback:
            physical_bytes = _physical_memory_bytes()
            if physical_bytes is not None:
                return _metric(
                    "visible_memory_bytes",
                    physical_bytes,
                    "bytes",
                    f"{platform.system().lower()}.sysconf",
                    status="partial",
                    coverage="partial",
                    caveats=[
                        "NON_LINUX_HOST_FALLBACK_PROTOTYPE_ONLY",
                        "NO_CGROUP_LIMIT_QUERY",
                        "MEMORY_LIMIT_IS_NOT_RESERVATION",
                    ],
                    inputs={"os_physical_memory_bytes": physical_bytes},
                )
        return _metric(
            "visible_memory_bytes",
            None,
            "bytes",
            "linux.sysconf+cgroup",
            status="unavailable",
            coverage="none",
            caveats=["UNSUPPORTED_PLATFORM"],
            inputs={"reason": "Phase 1 prototype supports Linux only"},
        )

    physical_bytes = _physical_memory_bytes()
    cgroup_limit, cgroup_version, raw_limits = _finite_memory_max()
    candidates = [value for value in (physical_bytes, cgroup_limit) if value is not None]
    if not candidates:
        return _metric(
            "visible_memory_bytes",
            None,
            "bytes",
            "linux.sysconf+cgroup",
            status="unavailable",
            coverage="none",
            caveats=["MEMORY_VISIBILITY_UNREADABLE"],
        )
    return _metric(
        "visible_memory_bytes",
        min(candidates),
        "bytes",
        f"linux.sysconf+{cgroup_version}.memory_max",
        coverage="partial" if physical_bytes is None else "complete",
        inputs={
            "os_physical_memory_bytes": physical_bytes,
            "cgroup_memory_limits_bytes": raw_limits,
        },
    )


def probe_storage(workspace: Path) -> dict[str, Any]:
    try:
        if not workspace.is_dir():
            return _metric(
                "visible_storage_capacity_bytes",
                None,
                "bytes",
                "posix.statvfs",
                status="unavailable",
                coverage="none",
                caveats=["WORKSPACE_PATH_NOT_DIRECTORY"],
            )
        stats = os.statvfs(workspace)
        block_size = stats.f_frsize or stats.f_bsize
        total = block_size * stats.f_blocks
        available = block_size * stats.f_bavail
    except OSError:
        return _metric(
            "visible_storage_capacity_bytes",
            None,
            "bytes",
            "posix.statvfs",
            status="unavailable",
            coverage="none",
            caveats=["WORKSPACE_FILESYSTEM_UNREADABLE"],
        )
    if block_size <= 0 or total <= 0 or available < 0:
        return _metric(
            "visible_storage_capacity_bytes",
            None,
            "bytes",
            "posix.statvfs",
            status="unavailable",
            coverage="none",
            caveats=["WORKSPACE_FILESYSTEM_INVALID_STATVFS"],
        )
    return _metric(
        "visible_storage_capacity_bytes",
        total,
        "bytes",
        "posix.statvfs",
        dimensions={"scope_label": "job_run_filesystem", "available_bytes": available},
        scope="job_run_filesystem",
        caveats=["CAPACITY_NOT_ALLOCATION_OR_BILLING", "FILESYSTEM_MAY_BE_SHARED"],
    )


class CudaRuntimeAdapter(Protocol):
    """Minimal, injectable boundary for validated CUDA-visible devices.

    A production adapter would call the CUDA runtime before it creates these
    records. ``cuda_identity`` is an adapter-local match key: it is never
    emitted in a resource record.
    """

    def enumerate_visible_devices(self) -> Iterable[Mapping[str, Any]]:
        """Return one mapping per CUDA-visible full GPU or MIG compute instance."""


class NvmlEnricher(Protocol):
    """Optional metadata lookup restricted to an already validated CUDA identity."""

    def enrich_cuda_device(self, cuda_identity: str) -> Optional[Mapping[str, Any]]:
        """Return metadata for this CUDA identity, or ``None`` when it cannot be matched."""


_GPU_KIND_FULL = "full_gpu"
_GPU_KIND_MIG = "mig_compute_instance"
_GPU_KIND_DETAILS = {
    _GPU_KIND_FULL: ("visible_full_gpu_count", "full_gpu_instances"),
    _GPU_KIND_MIG: ("visible_mig_compute_instance_count", "mig_compute_instances"),
}
_GPU_METADATA_KEYS = ("vendor", "model", "memory_bytes", "mig_profile")


def _bounded_label(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= 128 else None


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) and value > 0 else None


def _gpu_unavailable_metric(reason: str) -> dict[str, Any]:
    caveats = [reason]
    if "CUDA_VISIBLE_DEVICES" in os.environ:
        # The raw mask is deliberately neither preserved nor parsed. Its
        # presence is diagnostic only and cannot establish a device count.
        caveats.append("CUDA_VISIBLE_DEVICES_SET_DIAGNOSTIC_ONLY")
    return _metric(
        "visible_gpu_count",
        None,
        "gpus",
        "cuda_runtime_adapter",
        status="unavailable",
        coverage="none",
        caveats=caveats,
        inputs={"cuda_visible_devices_set": "CUDA_VISIBLE_DEVICES" in os.environ},
    )


def _normalize_cuda_runtime_device(value: Any) -> Optional[dict[str, Any]]:
    """Validate a device returned by the runtime adapter before it affects a count."""

    if not isinstance(value, Mapping):
        return None
    cuda_identity = _bounded_label(value.get("cuda_identity"))
    device_kind = value.get("device_kind")
    if not cuda_identity or device_kind not in _GPU_KIND_DETAILS:
        return None

    result = {"cuda_identity": cuda_identity, "device_kind": device_kind}
    for key in _GPU_METADATA_KEYS:
        raw = value.get(key)
        if key == "memory_bytes":
            normalized = _positive_int(raw)
        else:
            normalized = _bounded_label(raw)
        if normalized is not None:
            result[key] = normalized
    return result


def _matched_nvml_metadata(nvml_enricher: Optional[NvmlEnricher], cuda_identity: str) -> Optional[dict[str, Any]]:
    """Get optional metadata without allowing NVML inventory to create a device record."""

    if nvml_enricher is None:
        return None
    try:
        value = nvml_enricher.enrich_cuda_device(cuda_identity)
    except Exception:
        return None
    if not isinstance(value, Mapping):
        return None

    returned_identity = _bounded_label(value.get("cuda_identity"))
    if returned_identity != cuda_identity:
        return None

    metadata = {}
    for key in _GPU_METADATA_KEYS:
        raw = value.get(key)
        if key == "memory_bytes":
            normalized = _positive_int(raw)
        else:
            normalized = _bounded_label(raw)
        if normalized is not None:
            metadata[key] = normalized
    return metadata


def probe_gpu_records(
    cuda_runtime: Optional[CudaRuntimeAdapter] = None, nvml_enricher: Optional[NvmlEnricher] = None
) -> list[dict[str, Any]]:
    """Return separate CUDA-validated full-GPU and MIG-instance count records.

    CUDA runtime enumeration is the sole authority for numeric counts. An
    optional NVML adapter may enrich a device that the runtime already
    returned, but cannot add, remove, classify, or count devices.
    """

    if cuda_runtime is None:
        return [_gpu_unavailable_metric("CUDA_RUNTIME_ADAPTER_NOT_EMBEDDED")]

    try:
        raw_devices = cuda_runtime.enumerate_visible_devices()
        if isinstance(raw_devices, (str, bytes)) or not isinstance(raw_devices, Iterable):
            return [_gpu_unavailable_metric("CUDA_RUNTIME_ENUMERATION_INVALID")]
        devices = [_normalize_cuda_runtime_device(value) for value in raw_devices]
    except Exception:
        return [_gpu_unavailable_metric("CUDA_RUNTIME_ENUMERATION_FAILED")]

    if any(device is None for device in devices):
        return [_gpu_unavailable_metric("CUDA_RUNTIME_ENUMERATION_INVALID")]
    devices = [device for device in devices if device is not None]
    identities = [device["cuda_identity"] for device in devices]
    if len(identities) != len(set(identities)):
        return [_gpu_unavailable_metric("CUDA_RUNTIME_ENUMERATION_INVALID")]

    groups: dict[tuple, dict[str, Any]] = {}
    for device in devices:
        nvml_metadata = _matched_nvml_metadata(nvml_enricher, device["cuda_identity"])
        metadata = dict(device)
        if nvml_metadata:
            # NVML enriches only a CUDA-validated device. It cannot override
            # the runtime-provided device kind or alter the numeric count.
            metadata.update(nvml_metadata)
        group_key = (
            metadata["device_kind"],
            metadata.get("vendor"),
            metadata.get("model"),
            metadata.get("memory_bytes"),
            metadata.get("mig_profile"),
        )
        group = groups.setdefault(
            group_key,
            {
                "count": 0,
                "device_kind": metadata["device_kind"],
                "vendor": metadata.get("vendor"),
                "model": metadata.get("model"),
                "memory_bytes": metadata.get("memory_bytes"),
                "mig_profile": metadata.get("mig_profile"),
                "nvml_enriched_count": 0,
            },
        )
        group["count"] += 1
        if nvml_metadata:
            group["nvml_enriched_count"] += 1

    # Keep full GPUs and MIG compute instances separate even when the runtime
    # reports a real zero. A mixed count would imply comparability that this
    # capacity-proxy contract does not claim.
    base_caveats = ["CAPACITY_NOT_ALLOCATION_OR_BILLING", "GPU_VISIBILITY_DOES_NOT_PROVE_EXCLUSIVITY"]
    if "CUDA_VISIBLE_DEVICES" in os.environ:
        base_caveats.append("CUDA_VISIBLE_DEVICES_SET_DIAGNOSTIC_ONLY")
    runtime_inputs = {
        "cuda_runtime_enumeration": "success",
        "cuda_visible_devices_set": "CUDA_VISIBLE_DEVICES" in os.environ,
    }
    records = []
    for device_kind in (_GPU_KIND_FULL, _GPU_KIND_MIG):
        kind_groups = [group for group in groups.values() if group["device_kind"] == device_kind]
        if not kind_groups:
            metric_name, unit = _GPU_KIND_DETAILS[device_kind]
            records.append(
                _metric(
                    metric_name,
                    0,
                    unit,
                    "cuda_runtime_enumeration",
                    dimensions={"device_kind": device_kind},
                    inputs={**runtime_inputs, "nvml_enrichment": "not_applicable"},
                    caveats=list(base_caveats),
                )
            )
            continue

        for group in sorted(
            kind_groups,
            key=lambda item: (
                item.get("model") or "",
                item.get("mig_profile") or "",
                item.get("memory_bytes") or 0,
            ),
        ):
            metric_name, unit = _GPU_KIND_DETAILS[device_kind]
            dimensions = {"device_kind": device_kind}
            for key in ("vendor", "model", "memory_bytes", "mig_profile"):
                if group.get(key) is not None:
                    dimensions[key] = group[key]
            if group["nvml_enriched_count"] == group["count"]:
                enrichment = "complete"
            elif group["nvml_enriched_count"]:
                enrichment = "partial"
            else:
                enrichment = "unavailable"
            caveats = list(base_caveats)
            if enrichment != "complete":
                caveats.append("NVML_ENRICHMENT_%s" % enrichment.upper())
            records.append(
                _metric(
                    metric_name,
                    group["count"],
                    unit,
                    "cuda_runtime_enumeration",
                    dimensions=dimensions,
                    inputs={**runtime_inputs, "nvml_enrichment": enrichment},
                    caveats=caveats,
                )
            )
    return records


def probe_gpu() -> dict[str, Any]:
    """Return the legacy scalar record used by the no-adapter local-capture path.

    Consumers that have a CUDA runtime adapter must use ``probe_gpu_records``
    so a full GPU and a MIG compute instance cannot be merged into one scalar
    count.
    """

    return probe_gpu_records()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("."), help="job run directory filesystem to observe")
    parser.add_argument("--indent", type=int, default=2, help="JSON indentation")
    parser.add_argument(
        "--allow-host-fallback",
        action="store_true",
        help="emit partial non-Linux host values for prototype artifacts; not a Phase 1 support claim",
    )
    args = parser.parse_args()

    result = {
        "schema_version": "prototype-0.1",
        "observed_at": _utc_now(),
        "platform": platform.system().lower(),
        "collection_mode": "host_fallback_prototype" if args.allow_host_fallback else "linux_contract_only",
        "metrics": [
            probe_cpu(allow_host_fallback=args.allow_host_fallback),
            probe_memory(allow_host_fallback=args.allow_host_fallback),
            probe_storage(args.workspace),
            probe_gpu(),
        ],
        "warning": "Research-only; this is not an NVFlare runtime integration or a billing record.",
    }
    print(json.dumps(result, indent=args.indent, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
