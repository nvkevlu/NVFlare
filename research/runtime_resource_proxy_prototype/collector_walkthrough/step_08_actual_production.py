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

"""Run the unchanged production collector for comparison with steps 1-7."""

import json
import sys
import time

from nvflare.private.fed.resource_stats.collector import JobResourceCollector, assemble_participant_summary


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: step_08_actual_production.py EXISTING_JOB_WORKSPACE WAIT_SECONDS")
    run_dir = sys.argv[1]
    wait_seconds = float(sys.argv[2])

    collector = JobResourceCollector(run_dir)
    time.sleep(wait_seconds)
    handoff = collector.finish()
    report = assemble_participant_summary(
        job_id="walkthrough-job",
        participant_name="colossus-l40g",
        child_handoff=handoff,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
