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

"""Recover evidence and a report after abrupt launcher termination."""

import argparse
import json
from pathlib import Path

from .artifacts import RunArtifacts, utc_now
from .evidence import collect_workspace_evidence
from .progress import RunProgressReporter
from .report import generate_summary


def finalize_run(run_dir: Path) -> dict:
    artifacts = RunArtifacts.open_existing(run_dir)
    if not artifacts.result_path.exists():
        artifacts.write_result(
            {
                "mode": "simulation",
                "status": "FINISHED:FAILED",
                "finished_at": utc_now(),
                "workspace_path": str(artifacts.workspace_dir),
                "job_config_path": str(artifacts.job_config_dir),
                "error": {
                    "type": "AbruptTermination",
                    "message": "The launcher stopped before writing result.json; inspect scheduler and kernel logs.",
                },
            }
        )
    collect_workspace_evidence(artifacts)
    summary = generate_summary(artifacts.root)
    result = json.loads(artifacts.result_path.read_text(encoding="utf-8"))
    duration = summary.get("metrics", {}).get("events", {}).get("job_duration_seconds")
    RunProgressReporter(artifacts).finish(
        summary["status"],
        result.get("status", "FINISHED:FAILED"),
        job_id=result.get("job_id"),
        error=result.get("error"),
        elapsed_seconds=duration,
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize an interrupted LLM FL stress run.")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    summary = finalize_run(args.run_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
