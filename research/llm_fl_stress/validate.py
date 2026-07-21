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

"""Validate scenario schemas and print sizing without FLARE dependencies."""

import argparse
import json
from pathlib import Path

from harness.config import load_scenario


PROJECT_DIR = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate LLM FL stress scenarios and print calculated sizing.")
    parser.add_argument("scenarios", type=Path, nargs="*")
    args = parser.parse_args()
    paths = args.scenarios or sorted((PROJECT_DIR / "configs").glob("*.json"))
    results = []
    for path in paths:
        scenario = load_scenario(path)
        results.append(
            {
                "path": str(path),
                "name": scenario.name,
                "parameter_count": scenario.model.parameter_count,
                "dtype": scenario.model.dtype,
                "payload_bytes": scenario.payload_bytes,
                "payload_gib": scenario.payload_gib,
                "wire_bytes_per_round": scenario.expected_wire_bytes_per_round,
                "planned_server_capacity_bytes": scenario.planned_server_capacity_bytes,
                "planned_client_capacity_bytes": scenario.planned_client_capacity_bytes,
                "planned_simulation_capacity_bytes": scenario.planned_simulation_capacity_bytes,
                "planned_disk_capacity_bytes": scenario.planned_disk_capacity_bytes,
            }
        )
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
