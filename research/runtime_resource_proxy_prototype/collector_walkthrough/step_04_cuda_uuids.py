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

"""Map CUDA-visible ordinals to temporary Driver API UUID join keys."""

import ctypes
import ctypes.util
import json
import sys


class CudaUuid(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_ubyte * 16)]


def uuid_text(value: CudaUuid) -> str:
    raw = bytes(value.bytes).hex()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: step_04_cuda_uuids.py CUDA_RUNTIME_COUNT")
    expected_count = int(sys.argv[1])

    library_name = ctypes.util.find_library("cuda") or "libcuda.so.1"
    driver = ctypes.CDLL(library_name)
    driver.cuInit.argtypes = [ctypes.c_uint]
    driver.cuInit.restype = ctypes.c_int
    driver.cuDeviceGetCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
    driver.cuDeviceGetCount.restype = ctypes.c_int
    driver.cuDeviceGet.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
    driver.cuDeviceGet.restype = ctypes.c_int
    driver.cuDeviceGetUuid_v2.argtypes = [ctypes.POINTER(CudaUuid), ctypes.c_int]
    driver.cuDeviceGetUuid_v2.restype = ctypes.c_int

    if driver.cuInit(0) != 0:
        raise SystemExit("cuInit(0) failed")
    driver_count = ctypes.c_int()
    if driver.cuDeviceGetCount(ctypes.byref(driver_count)) != 0:
        raise SystemExit("cuDeviceGetCount failed")
    if driver_count.value != expected_count:
        raise SystemExit(f"Driver count {driver_count.value} does not match Runtime count {expected_count}")

    uuids = []
    for ordinal in range(expected_count):
        device = ctypes.c_int()
        value = CudaUuid()
        if driver.cuDeviceGet(ctypes.byref(device), ordinal) != 0:
            raise SystemExit(f"cuDeviceGet failed for ordinal {ordinal}")
        if driver.cuDeviceGetUuid_v2(ctypes.byref(value), device.value) != 0:
            raise SystemExit(f"cuDeviceGetUuid_v2 failed for ordinal {ordinal}")
        uuids.append({"ordinal": ordinal, "bare_uuid": uuid_text(value)})

    print(
        json.dumps(
            {
                "source_calls": [
                    "cuInit(0)",
                    "cuDeviceGetCount(&count)",
                    "cuDeviceGet(&device, ordinal)",
                    "cuDeviceGetUuid_v2(&uuid, device)",
                ],
                "raw": {"driver_count": driver_count.value, "devices": uuids},
                "production_value": {"counts_match": True},
                "maps_to": "temporary CUDA-to-NVML join only; UUID is not stored",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
