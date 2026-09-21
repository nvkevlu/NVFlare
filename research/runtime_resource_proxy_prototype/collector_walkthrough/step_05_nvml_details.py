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

"""Use NVML to enrich one CUDA-validated UUID; never create a GPU count."""

import ctypes
import ctypes.util
import json
import sys


class NvmlMemory(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: step_05_nvml_details.py BARE_CUDA_UUID")
    bare_uuid = sys.argv[1]

    library_name = ctypes.util.find_library("nvidia-ml") or "libnvidia-ml.so.1"
    nvml = ctypes.CDLL(library_name)
    nvml.nvmlInit_v2.restype = ctypes.c_int
    nvml.nvmlShutdown.restype = ctypes.c_int
    nvml.nvmlDeviceGetHandleByUUID.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
    nvml.nvmlDeviceGetHandleByUUID.restype = ctypes.c_int
    nvml.nvmlDeviceIsMigDeviceHandle.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
    nvml.nvmlDeviceIsMigDeviceHandle.restype = ctypes.c_int
    nvml.nvmlDeviceGetName.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint]
    nvml.nvmlDeviceGetName.restype = ctypes.c_int
    nvml.nvmlDeviceGetMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(NvmlMemory)]
    nvml.nvmlDeviceGetMemoryInfo.restype = ctypes.c_int

    if nvml.nvmlInit_v2() != 0:
        raise SystemExit("nvmlInit_v2 failed")
    attempts = []
    try:
        handle = ctypes.c_void_p()
        matched_id = None
        for prefix in ("GPU-", "MIG-"):
            candidate = prefix + bare_uuid
            return_code = nvml.nvmlDeviceGetHandleByUUID(candidate.encode("ascii"), ctypes.byref(handle))
            attempts.append({"candidate": candidate, "return_code": return_code})
            if return_code == 0:
                matched_id = candidate
                break
        if matched_id is None:
            raise SystemExit("NVML did not match the CUDA UUID")

        mig = ctypes.c_uint()
        name = ctypes.create_string_buffer(128)
        memory = NvmlMemory()
        if nvml.nvmlDeviceIsMigDeviceHandle(handle, ctypes.byref(mig)) != 0:
            raise SystemExit("nvmlDeviceIsMigDeviceHandle failed")
        if nvml.nvmlDeviceGetName(handle, name, len(name)) != 0:
            raise SystemExit("nvmlDeviceGetName failed")
        if nvml.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(memory)) != 0:
            raise SystemExit("nvmlDeviceGetMemoryInfo failed")

        group = {
            "kind": "mig_compute_instance" if mig.value else "full_gpu",
            "count": 1,
            "model": name.value.decode("utf-8", errors="replace"),
            "memory_bytes": str(memory.total),
        }
        print(
            json.dumps(
                {
                    "source_calls": [
                        "nvmlInit_v2()",
                        "nvmlDeviceGetHandleByUUID(...) for GPU- then MIG-",
                        "nvmlDeviceIsMigDeviceHandle(handle, &is_mig)",
                        "nvmlDeviceGetName(handle, name, size)",
                        "nvmlDeviceGetMemoryInfo(handle, &memory)",
                        "nvmlShutdown()",
                    ],
                    "raw": {"uuid_lookup_attempts": attempts, "matched": True},
                    "production_capacity": {"gpu": {"groups": [group]}},
                    "maps_to": "kind/model/memory copy through; count x elapsed = instance-seconds",
                },
                indent=2,
            )
        )
    finally:
        nvml.nvmlShutdown()


if __name__ == "__main__":
    main()
