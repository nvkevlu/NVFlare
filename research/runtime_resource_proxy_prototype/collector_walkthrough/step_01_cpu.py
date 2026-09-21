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

"""Show the CPU sources used on the verified, non-limited Colossus host."""

import json
import os
import platform
from pathlib import Path


def cpu_models_by_id() -> dict[int, str]:
    result = {}
    for block in Path("/proc/cpuinfo").read_text(encoding="utf-8").split("\n\n"):
        values = {}
        for line in block.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                values[key.strip()] = value.strip()
        if values.get("processor", "").isdigit() and values.get("model name"):
            result[int(values["processor"])] = values["model name"]
    return result


def main() -> None:
    affinity = sorted(os.sched_getaffinity(0))
    models_by_id = cpu_models_by_id()
    models = {models_by_id.get(cpu_id) for cpu_id in affinity}
    model = next(iter(models)) if len(models) == 1 and None not in models else None
    architecture = platform.machine()
    group = {"units": str(len(affinity)), "architecture": architecture}
    if model:
        group["model"] = model

    print(
        json.dumps(
            {
                "source_calls": [
                    "os.sched_getaffinity(0)",
                    "Path('/proc/cpuinfo').read_text()",
                    "platform.machine()",
                ],
                "raw": {"affinity_cpu_ids": affinity},
                "production_capacity": {"cpu": {"groups": [group]}},
                "maps_to": "CPU units x measured seconds = CPU unit-seconds",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
