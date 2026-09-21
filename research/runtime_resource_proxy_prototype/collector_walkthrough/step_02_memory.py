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

"""Show the physical-memory source used on the non-limited Colossus host."""

import json
import os


def main() -> None:
    page_size = os.sysconf("SC_PAGE_SIZE")
    page_count = os.sysconf("SC_PHYS_PAGES")
    memory_bytes = page_size * page_count

    print(
        json.dumps(
            {
                "source_calls": [
                    "os.sysconf('SC_PAGE_SIZE')",
                    "os.sysconf('SC_PHYS_PAGES')",
                ],
                "raw": {"page_size": page_size, "page_count": page_count},
                "calculation": f"{page_size} x {page_count} = {memory_bytes}",
                "production_capacity": {"memory": {"bytes": str(memory_bytes)}},
                "maps_to": "memory bytes x measured seconds = memory byte-seconds",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
