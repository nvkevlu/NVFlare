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

"""CUDA Runtime / Driver / NVML ctypes probing.

Numeric GPU count authority is CUDA Runtime enumeration only; NVML may enrich
a CUDA-confirmed device but can never add one, and ``CUDA_VISIBLE_DEVICES`` is
never parsed. ``_FROZEN_DISTRIBUTION_ROOTS`` is captured once, at this
module's own first import, on the assumption that the platform-owned job
bootstrap (``job_process_bootstrap.py``) is the first and only thing that
imports the resource-stats collector, before any job/site custom path is
added to ``sys.path``.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import importlib.metadata as importlib_metadata
import os
import platform
import re
import stat
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from ._shared import _normalize_model

_CUDA_RUNTIME_DISTRIBUTION_PATTERN = re.compile(r"^nvidia-cuda-runtime(?:-cu\d+)?$")
_LINUX_CUDA_RUNTIME_FILE_PATTERN = re.compile(r"^libcudart\.so(?:\.\d+)*$")
_WINDOWS_CUDA_RUNTIME_FILE_PATTERN = re.compile(r"^cudart64_\d+\.dll$", re.IGNORECASE)


def _freeze_distribution_roots() -> tuple[str, ...]:
    """Capture the official launcher's import roots before job paths are enabled."""

    roots = []
    for value in sys.path:
        if not value or not os.path.isabs(value):
            continue
        try:
            path = Path(value).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if path.is_dir() and str(path) not in roots:
            roots.append(str(path))
    return tuple(roots)


_FROZEN_DISTRIBUTION_ROOTS = _freeze_distribution_roots()


class _CudaUuid(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_ubyte * 16)]


class _NvmlMemory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


def _load_library(candidates: list[str]):
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ctypes.CDLL(candidate)
        except OSError:
            continue
    return None


def _normalize_distribution_name(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[-_.]+", "-", value).lower()


def _is_bundled_cuda_runtime_file(name: str) -> bool:
    if platform.system() == "Linux":
        return bool(_LINUX_CUDA_RUNTIME_FILE_PATTERN.fullmatch(name))
    if platform.system() == "Windows":
        return bool(_WINDOWS_CUDA_RUNTIME_FILE_PATTERN.fullmatch(name))
    return False


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _find_bundled_cuda_runtime_path(
    distribution_roots: tuple[str, ...] = _FROZEN_DISTRIBUTION_ROOTS,
) -> Optional[Path]:
    """Find one CUDA Runtime file owned by an installed NVIDIA package.

    Distribution roots are frozen when this trusted module is imported.  This
    deliberately avoids importing a framework package or searching job paths.
    Multiple distinct candidates are ambiguous and fail closed.
    """

    if not distribution_roots:
        return None
    trusted_roots = []
    for value in distribution_roots:
        try:
            root = Path(value).resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if root.is_dir():
            trusted_roots.append(root)
    if not trusted_roots:
        return None

    candidates = {}
    try:
        distributions = importlib_metadata.distributions(path=[str(root) for root in trusted_roots])
        for distribution in distributions:
            name = _normalize_distribution_name(distribution.metadata.get("Name", ""))
            if not _CUDA_RUNTIME_DISTRIBUTION_PATTERN.fullmatch(name):
                continue
            try:
                install_root = Path(distribution.locate_file("")).resolve(strict=True)
            except (OSError, RuntimeError, TypeError, ValueError):
                return None
            if not any(install_root == root for root in trusted_roots):
                return None
            for owned_file in distribution.files or ():
                if not _is_bundled_cuda_runtime_file(Path(owned_file).name):
                    continue
                candidate = Path(distribution.locate_file(owned_file))
                try:
                    candidate = candidate.resolve(strict=True)
                    if not _is_within(candidate, install_root):
                        return None
                    candidate_stat = candidate.stat()
                except (OSError, RuntimeError):
                    return None
                if not stat.S_ISREG(candidate_stat.st_mode) or candidate_stat.st_size <= 0:
                    return None
                identity = (candidate_stat.st_dev, candidate_stat.st_ino)
                candidates.setdefault(identity, candidate)
                if len(candidates) > 1:
                    return None
    except Exception:
        return None
    return next(iter(candidates.values())) if len(candidates) == 1 else None


def _load_bundled_cuda_runtime():
    path = _find_bundled_cuda_runtime_path()
    if path is None:
        return None
    try:
        if platform.system() == "Windows" and hasattr(os, "add_dll_directory"):
            directory_handle = os.add_dll_directory(str(path.parent))
            try:
                library = ctypes.CDLL(str(path))
                setattr(library, "_nvflare_dll_directory_handle", directory_handle)
                return library
            except Exception:
                directory_handle.close()
                raise
        mode = getattr(os, "RTLD_LOCAL", 0) | getattr(os, "RTLD_NOW", 0)
        return ctypes.CDLL(str(path), mode=mode)
    except (OSError, TypeError, ValueError):
        return None


def _cuda_runtime_device_count(cudart: Any) -> Optional[int]:
    if cudart is None:
        return None
    try:
        cuda_get_count = cudart.cudaGetDeviceCount
        cuda_get_count.argtypes = [ctypes.POINTER(ctypes.c_int)]
        cuda_get_count.restype = ctypes.c_int
        count = ctypes.c_int()
        if cuda_get_count(ctypes.byref(count)) != 0 or count.value < 0:
            return None
        return count.value
    except (AttributeError, ctypes.ArgumentError, OSError, TypeError, ValueError):
        return None


def _uuid_text(value: _CudaUuid) -> str:
    raw = bytes(value.bytes).hex()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def _cuda_uuid_reader(expected_count: int) -> Optional[Callable[[Any, int], int]]:
    """Return a CUDA UUID reader for the runtime-visible device ordinals.

    Use the Driver API v2 UUID lookup after confirming that it sees the same
    device count.  The successful Runtime API count remains the authority for
    numeric capacity.  Requiring v2 prevents a visible MIG instance from being
    identified by its parent GPU UUID on older drivers.
    """

    cuda_driver = _load_library(
        [
            ctypes.util.find_library("cuda") or "",
            "libcuda.so.1",
            "libcuda.so",
            "nvcuda.dll",
        ]
    )
    if cuda_driver is None:
        return None
    try:
        cu_init = cuda_driver.cuInit
        cu_init.argtypes = [ctypes.c_uint]
        cu_init.restype = ctypes.c_int
        cu_get_count = cuda_driver.cuDeviceGetCount
        cu_get_count.argtypes = [ctypes.POINTER(ctypes.c_int)]
        cu_get_count.restype = ctypes.c_int
        cu_get_device = cuda_driver.cuDeviceGet
        cu_get_device.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        cu_get_device.restype = ctypes.c_int
        cu_get_uuid = getattr(cuda_driver, "cuDeviceGetUuid_v2", None)
        if cu_get_uuid is None:
            return None
        cu_get_uuid.argtypes = [ctypes.POINTER(_CudaUuid), ctypes.c_int]
        cu_get_uuid.restype = ctypes.c_int
    except (AttributeError, TypeError, ValueError):
        return None

    driver_count = ctypes.c_int()
    try:
        counts_match = (
            cu_init(0) == 0 and cu_get_count(ctypes.byref(driver_count)) == 0 and driver_count.value == expected_count
        )
    except (ctypes.ArgumentError, OSError, TypeError, ValueError):
        return None
    if not counts_match:
        return None

    def read_uuid(uuid_pointer: Any, ordinal: int) -> int:
        device = ctypes.c_int()
        result = cu_get_device(ctypes.byref(device), ordinal)
        if result != 0:
            return result
        return cu_get_uuid(uuid_pointer, device.value)

    return read_uuid


def probe_gpu() -> Optional[dict[str, list[dict[str, Any]]]]:
    """Enumerate with CUDA Runtime, then classify/enrich only those devices.

    ``CUDA_VISIBLE_DEVICES`` is intentionally never parsed.  A numeric zero is
    returned whenever ``cudaGetDeviceCount`` succeeds, or whenever no CUDA
    Runtime library can be loaded at all (neither via the system loader nor an
    allowlisted bundled distribution) -- a host with no CUDA Runtime present
    anywhere provably cannot expose a GPU to this process, so that case is an
    authoritative empty GPU set rather than an unavailable/partial observation.
    A loaded runtime whose device-count call itself fails is a genuinely
    ambiguous result and is still reported as unavailable.  For a positive
    count, NVML must match every CUDA UUID so full GPUs and MIG compute
    instances can be kept in separate schema groups.  If that match cannot be
    established, the GPU member is omitted and the enclosing resource-time
    value is partial.
    """

    cudart = _load_library(
        [
            ctypes.util.find_library("cudart") or "",
            "libcudart.so",
            "libcudart.so.13",
            "libcudart.so.12",
            "libcudart.so.11.0",
            "cudart64_13.dll",
            "cudart64_12.dll",
            "cudart64_110.dll",
        ]
    )
    count = _cuda_runtime_device_count(cudart)
    bundled_cudart = None
    if count is None:
        bundled_cudart = _load_bundled_cuda_runtime()
        count = _cuda_runtime_device_count(bundled_cudart)
    if count is None:
        if cudart is None and bundled_cudart is None:
            return {"groups": []}
        return None
    if count == 0:
        return {"groups": []}

    nvml = _load_library([ctypes.util.find_library("nvidia-ml") or "", "libnvidia-ml.so.1", "nvml.dll"])
    if nvml is None:
        return None
    try:
        cuda_get_uuid = _cuda_uuid_reader(count)
        if cuda_get_uuid is None:
            return None
        nvml_init = getattr(nvml, "nvmlInit_v2", None) or getattr(nvml, "nvmlInit", None)
        if nvml_init is None:
            return None
        nvml_init.restype = ctypes.c_int
        nvml_shutdown = nvml.nvmlShutdown
        nvml_shutdown.restype = ctypes.c_int
        get_handle = nvml.nvmlDeviceGetHandleByUUID
        get_handle.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
        get_handle.restype = ctypes.c_int
        is_mig = nvml.nvmlDeviceIsMigDeviceHandle
        is_mig.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
        is_mig.restype = ctypes.c_int
        get_name = nvml.nvmlDeviceGetName
        get_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint]
        get_name.restype = ctypes.c_int
        get_memory = nvml.nvmlDeviceGetMemoryInfo
        get_memory.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NvmlMemory)]
        get_memory.restype = ctypes.c_int
    except AttributeError:
        return None
    if nvml_init() != 0:
        return None

    devices = []
    try:
        for index in range(count):
            uuid_value = _CudaUuid()
            if cuda_get_uuid(ctypes.byref(uuid_value), index) != 0:
                return None
            uuid = _uuid_text(uuid_value)
            handle = ctypes.c_void_p()
            matched = False
            for prefix in ("GPU-", "MIG-"):
                if get_handle((prefix + uuid).encode("ascii"), ctypes.byref(handle)) == 0:
                    matched = True
                    break
            if not matched:
                return None
            mig_value = ctypes.c_uint()
            if is_mig(handle, ctypes.byref(mig_value)) != 0:
                return None
            name_buffer = ctypes.create_string_buffer(128)
            model = None
            if get_name(handle, name_buffer, len(name_buffer)) == 0:
                model = _normalize_model(name_buffer.value.decode("utf-8", errors="replace"))
            memory = _NvmlMemory()
            memory_bytes = str(memory.total) if get_memory(handle, ctypes.byref(memory)) == 0 and memory.total else None
            devices.append(
                {
                    "kind": "mig_compute_instance" if mig_value.value else "full_gpu",
                    "model": model,
                    "memory_bytes": memory_bytes,
                }
            )
    finally:
        nvml_shutdown()

    groups: dict[tuple[str, Optional[str], Optional[str]], dict[str, Any]] = {}
    for device in devices:
        key = (device["kind"], device["model"], device["memory_bytes"])
        group = groups.setdefault(
            key,
            {
                "kind": device["kind"],
                "count": 0,
                **({"model": device["model"]} if device["model"] else {}),
                **({"memory_bytes": device["memory_bytes"]} if device["memory_bytes"] else {}),
            },
        )
        group["count"] += 1
    return {"groups": [groups[key] for key in sorted(groups, key=lambda item: tuple(value or "" for value in item))]}
