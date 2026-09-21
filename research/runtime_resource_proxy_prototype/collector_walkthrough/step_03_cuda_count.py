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

"""Call CUDA Runtime directly to obtain the only authoritative GPU count."""

import ctypes
import ctypes.util
import json


def main() -> None:
    library_name = ctypes.util.find_library("cudart") or "libcudart.so.13"
    cudart = ctypes.CDLL(library_name)
    get_count = cudart.cudaGetDeviceCount
    get_count.argtypes = [ctypes.POINTER(ctypes.c_int)]
    get_count.restype = ctypes.c_int

    count = ctypes.c_int(-1)
    return_code = get_count(ctypes.byref(count))
    if return_code != 0:
        raise SystemExit(f"cudaGetDeviceCount failed with CUDA return code {return_code}")

    print(
        json.dumps(
            {
                "source_calls": [
                    f"ctypes.CDLL({library_name!r})",
                    "cudaGetDeviceCount(&count)",
                ],
                "raw": {"return_code": return_code, "count": count.value},
                "production_value": {"cuda_visible_gpu_count": count.value},
                "maps_to": "GPU count x measured seconds = GPU instance-seconds",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
