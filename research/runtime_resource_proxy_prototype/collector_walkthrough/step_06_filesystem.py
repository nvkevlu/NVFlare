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

"""Show the one statvfs observation used for workspace-filesystem capacity."""

import json
import os
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: step_06_filesystem.py EXISTING_JOB_WORKSPACE")
    workspace = Path(sys.argv[1]).resolve()
    stats = os.statvfs(workspace)
    capacity_bytes = stats.f_blocks * stats.f_frsize

    print(
        json.dumps(
            {
                "source_calls": [f"os.statvfs({str(workspace)!r})"],
                "raw": {"f_blocks": stats.f_blocks, "f_frsize": stats.f_frsize},
                "calculation": f"{stats.f_blocks} x {stats.f_frsize} = {capacity_bytes}",
                "production_value": {
                    "workspace_filesystem": {"status": "reported", "capacity_bytes": str(capacity_bytes)}
                },
                "maps_to": "visible capacity of the filesystem containing this path; not job usage",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
