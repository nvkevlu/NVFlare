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

"""Show monotonic elapsed time and the three resource-time multiplications."""

import json
import sys
import time
from decimal import Decimal


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit("usage: step_07_resource_time.py CPU_UNITS MEMORY_BYTES GPU_COUNT WAIT_SECONDS")
    cpu_units = Decimal(sys.argv[1])
    memory_bytes = Decimal(sys.argv[2])
    gpu_count = Decimal(sys.argv[3])
    wait_seconds = Decimal(sys.argv[4])

    start_ns = time.monotonic_ns()
    time.sleep(float(wait_seconds))
    end_ns = time.monotonic_ns()
    elapsed = Decimal(end_ns - start_ns) / Decimal(1_000_000_000)

    print(
        json.dumps(
            {
                "source_calls": ["time.monotonic_ns() at start", "time.monotonic_ns() at finish"],
                "raw": {"elapsed_nanoseconds": end_ns - start_ns},
                "resource_time": {
                    "measured_seconds": decimal_text(elapsed),
                    "cpu_unit_seconds": decimal_text(cpu_units * elapsed),
                    "memory_byte_seconds": decimal_text(memory_bytes * elapsed),
                    "gpu_instance_seconds": decimal_text(gpu_count * elapsed),
                },
                "maps_to": {
                    "cpu": f"{cpu_units} x measured_seconds",
                    "memory": f"{memory_bytes} x measured_seconds",
                    "gpu": f"{gpu_count} x measured_seconds",
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
