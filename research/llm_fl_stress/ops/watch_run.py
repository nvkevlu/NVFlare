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

"""Watch a local stress-run heartbeat and exit when artifact collection finishes."""

import argparse
import json
import sys
import time
from pathlib import Path


def _status_line(status: dict) -> str:
    elapsed = float(status.get("elapsed_seconds") or 0.0)
    return (
        f"[{status.get('updated_at', 'unknown')}][{status.get('state', 'UNKNOWN')}] "
        f"phase={status.get('phase', 'unknown')} flare={status.get('flare_status', 'unknown')} "
        f"elapsed={elapsed / 60.0:.1f}m job={status.get('job_id') or '-'}"
    )


def watch_run(run_dir: Path, poll_interval_seconds: float, stale_after_seconds: float, once: bool = False) -> int:
    status_path = run_dir.resolve() / "live_status.json"
    last_updated_at = None
    while True:
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"waiting for {status_path}", flush=True)
            if once:
                return 3
            time.sleep(poll_interval_seconds)
            continue
        except (OSError, json.JSONDecodeError) as error:
            print(f"could not read {status_path}: {error}", file=sys.stderr, flush=True)
            return 3

        updated_at = status.get("updated_at")
        if updated_at != last_updated_at:
            print(_status_line(status), flush=True)
            last_updated_at = updated_at

        state = status.get("state")
        if state == "COMPLETED":
            print("\aRun artifacts are complete.", flush=True)
            return 0
        if state == "FAILED":
            print("\aRun failed; inspect live_status.json and result.json.", file=sys.stderr, flush=True)
            return 1

        try:
            stale_seconds = time.time() - status_path.stat().st_mtime
        except OSError:
            stale_seconds = 0.0
        if stale_seconds > stale_after_seconds:
            print(
                f"STALE: heartbeat has not changed for {stale_seconds:.0f}s; check launcher and lease state.",
                file=sys.stderr,
                flush=True,
            )
            return 2
        if once:
            return 0
        time.sleep(poll_interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--stale-after-seconds", type=float, default=180.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.poll_interval_seconds <= 0 or args.stale_after_seconds <= 0:
        parser.error("intervals must be positive")
    return watch_run(args.run_dir, args.poll_interval_seconds, args.stale_after_seconds, args.once)


if __name__ == "__main__":
    raise SystemExit(main())
