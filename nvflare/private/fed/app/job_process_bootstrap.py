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

"""Start an NVFlare job process without importing job-controlled Python code first."""

import runpy
import sys
from pathlib import Path

_PROCESS_MODULES = {
    "client": "nvflare.private.fed.app.client.worker_process",
    "server": "nvflare.private.fed.app.server.runner_process",
}


def main() -> None:
    if not sys.flags.isolated:
        raise SystemExit("the NVFlare job-process bootstrap requires Python isolated mode (-I)")

    if len(sys.argv) < 2 or sys.argv[1] not in _PROCESS_MODULES:
        raise SystemExit("expected one of the fixed NVFlare job-process types: client or server")

    process_type = sys.argv.pop(1)

    # ``-I`` deliberately excludes the script directory, PYTHONPATH, and the
    # user site. Add only the package root derived from this trusted script so
    # source, editable, and user-site NVFlare installations remain importable.
    package_parent = str(Path(__file__).resolve().parents[4])
    sys.path.insert(0, package_parent)

    runpy.run_module(_PROCESS_MODULES[process_type], run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
