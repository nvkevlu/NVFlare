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

"""Regenerate the exact output of the production resource-statistics path.

The fixture controls clocks, capacity probes, wall-clock timestamps, and the
single workspace-filesystem observation.  It does not reimplement collection,
validation, aggregation, archive verification, or CLI rendering.
"""

from __future__ import annotations

import argparse
import io
import tempfile
from collections.abc import Iterable, Mapping
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from nvflare.private.fed.resource_stats import collector as collector_module
from nvflare.private.fed.resource_stats import coordinator as coordinator_module
from nvflare.private.fed.resource_stats.archive_reader import WorkspaceResourceStatsReader
from nvflare.private.fed.resource_stats.collector import (
    JobResourceCollector,
    assemble_participant_summary,
    canonical_json_bytes,
    read_terminal_handoff,
    remove_terminal_handoff,
    write_terminal_handoff,
)
from nvflare.private.fed.resource_stats.contract import (
    KIND_STUDY_SUMMARY,
    SCHEMA_VERSION,
    derive_study_totals,
    validate_record,
)
from nvflare.private.fed.resource_stats.coordinator import RESOURCE_REPORT_ACCEPTED, ResourceStatsCoordinator
from nvflare.tool import cli_output
from nvflare.tool.job.job_resources import render_job_resources, render_study_resources

REFERENCE_JOB_ID = "job-20260917-001"
REFERENCE_STUDY = "cancer-research"
ARTIFACTS_DIR = Path(__file__).with_name("artifacts")

_GIB = 2**30
_TIB = 2**40


def _ticks(start_ns: int, duration_seconds: str) -> Iterable[int]:
    whole, dot, fraction = duration_seconds.partition(".")
    elapsed_ns = int(whole) * 1_000_000_000
    if dot:
        elapsed_ns += int(fraction.ljust(9, "0"))
    return iter((start_ns, start_ns + elapsed_ns))


def _collect_participant(
    *,
    run_dir: Path,
    participant_name: str,
    clock_values: Iterable[int],
    capacity: Mapping[str, Any],
) -> dict[str, Any]:
    """Exercise the production child handoff and parent assembly path."""

    ticks = iter(clock_values)
    collector = JobResourceCollector(
        run_dir,
        clock_ns=lambda: next(ticks),
        capacity_probe=lambda: capacity,
    )
    write_terminal_handoff(run_dir, collector.finish())
    handoff = read_terminal_handoff(run_dir)
    if handoff is None:
        raise RuntimeError(f"production handoff could not be read for {participant_name}")
    report = assemble_participant_summary(
        job_id=REFERENCE_JOB_ID,
        participant_name=participant_name,
        child_handoff=handoff,
    )
    remove_terminal_handoff(run_dir)
    return report


def _workspace_zip(run_dir: Path) -> bytes:
    """Create a deterministic in-memory WORKSPACE ZIP for the real reader."""

    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for path in sorted((run_dir / "resource_stats").rglob("*")):
            if not path.is_file():
                continue
            member = path.relative_to(run_dir).as_posix()
            info = ZipInfo(member, date_time=(2026, 9, 17, 14, 40, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return stream.getvalue()


def _build_study_summary(job_totals: Mapping[str, Any]) -> dict[str, Any]:
    """Mirror the bounded rows built by the production study query."""

    jobs = [
        {
            "job_id": REFERENCE_JOB_ID,
            "job_status": "FINISHED:COMPLETED",
            "resource_data": "included",
            "totals": job_totals,
        },
        {
            "job_id": "job-20260917-002",
            "job_status": "FINISHED:COMPLETED",
            "resource_data": "unavailable",
        },
        {
            "job_id": "job-20260917-003",
            "job_status": "RUNNING",
            "resource_data": "nonterminal",
        },
    ]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND_STUDY_SUMMARY,
        "selection": {"study_name": REFERENCE_STUDY},
        "generated_at": "2026-09-17T14:40:00Z",
        "coverage": {
            "selected_jobs": "3",
            "included_jobs": "1",
            "unavailable_jobs": "1",
            "nonterminal_jobs": "1",
        },
        "jobs": jobs,
        "totals": derive_study_totals(jobs),
    }
    validate_record(summary)
    return summary


def _render_cli_json(data: Mapping[str, Any]) -> bytes:
    """Capture the exact production ``--format json`` success envelope."""

    stream = io.StringIO()
    with patch.object(cli_output, "_output_format", "json"), redirect_stdout(stream):
        cli_output.output_ok(data)
    return stream.getvalue().encode("utf-8")


def build_artifacts() -> dict[str, bytes]:
    """Return every checked-in artifact produced by the production code."""

    with tempfile.TemporaryDirectory(prefix="nvflare-resource-reference-") as temp:
        root = Path(temp)
        site_run = root / "site-1" / "run"
        server_run = root / "server" / "run"
        site_run.mkdir(parents=True)
        server_run.mkdir(parents=True)

        # These values are fixture inputs, not precomputed outputs.  Absolute
        # monotonic readings stay private; the reports contain elapsed seconds.
        with (
            patch.object(
                collector_module,
                "observe_workspace_filesystem",
                side_effect=[
                    {"status": "reported", "capacity_bytes": str(2 * _TIB)},
                    {"status": "reported", "capacity_bytes": str(_TIB)},
                ],
            ),
            patch.object(
                collector_module,
                "utc_now",
                side_effect=[
                    "2026-09-17T14:37:04.500000Z",
                    "2026-09-17T14:37:20.000000Z",
                ],
            ),
            patch.object(
                coordinator_module,
                "utc_timestamp",
                side_effect=[
                    "2026-09-17T14:37:05.000000Z",
                    "2026-09-17T14:37:20.250000Z",
                    "2026-09-17T14:37:21.000000Z",
                    "2026-09-17T14:37:21.005000Z",
                ],
            ),
        ):
            site_report = _collect_participant(
                run_dir=site_run,
                participant_name="site-1",
                clock_values=_ticks(8_000_000_000_000_000_000, "2223.5"),
                capacity={
                    "cpu": {
                        "units": "32",
                        "model": "AMD EPYC 9654",
                        "architecture": "x86_64",
                    },
                    "memory": {"bytes": str(192 * _GIB)},
                    "gpu": {
                        "groups": [
                            {
                                "kind": "full_gpu",
                                "count": "4",
                                "model": "NVIDIA A100 80GB",
                                "memory_bytes": str(80 * _GIB),
                            }
                        ]
                    },
                },
            )

            server_report = _collect_participant(
                run_dir=server_run,
                participant_name="server",
                clock_values=_ticks(9_000_000_000_000_000_000, "2240"),
                capacity={
                    "cpu": {
                        "units": "8",
                        "model": "Intel Xeon Gold 6338",
                        "architecture": "x86_64",
                    },
                    "memory": {"bytes": str(64 * _GIB)},
                    "gpu": {"groups": []},
                },
            )

            coordinator = ResourceStatsCoordinator()
            coordinator.start_job(REFERENCE_JOB_ID, ["site-1"], server_run)
            for participant_name, report in (("site-1", site_report), ("server", server_report)):
                result = coordinator.accept_resource_report(
                    REFERENCE_JOB_ID,
                    participant_name,
                    {"participant_summary": canonical_json_bytes(report)},
                )
                if result != RESOURCE_REPORT_ACCEPTED:
                    raise RuntimeError(f"production coordinator rejected {participant_name}: {result}")
            coordinator.finalize_job(REFERENCE_JOB_ID)

        reader = WorkspaceResourceStatsReader(_workspace_zip(server_run))
        job_summary = reader.read_resource_summary()
        site_report = reader.read_participant_summary("site-1")
        reader.read_participant_summary("server")
        study_summary = _build_study_summary(job_summary["totals"])

        artifacts: dict[str, bytes] = {}
        for path in sorted((server_run / "resource_stats").rglob("*")):
            if path.is_file():
                relative = path.relative_to(server_run).as_posix()
                artifacts[f"workspace/{relative}"] = path.read_bytes()
        artifacts["query/resources-study.json"] = canonical_json_bytes(study_summary)
        artifacts["cli/resources-job.txt"] = (render_job_resources(job_summary) + "\n").encode("utf-8")
        artifacts["cli/resources-site-1.txt"] = (render_job_resources(job_summary, site_report) + "\n").encode("utf-8")
        artifacts["cli/resources-study.txt"] = (render_study_resources(study_summary) + "\n").encode("utf-8")
        artifacts["cli/resources-job.json"] = _render_cli_json(
            {
                "selection": {"job_id": REFERENCE_JOB_ID, "site": "all"},
                "summary": job_summary,
            }
        )
        artifacts["cli/resources-site-1.json"] = _render_cli_json(
            {
                "selection": {"job_id": REFERENCE_JOB_ID, "site": "site-1"},
                "summary": job_summary,
                "participant": site_report,
            }
        )
        artifacts["cli/resources-study.json"] = _render_cli_json(
            {
                "selection": {"study": REFERENCE_STUDY},
                "summary": study_summary,
            }
        )
        return artifacts


def write_artifacts(output_dir: Path = ARTIFACTS_DIR) -> None:
    for relative_path, data in build_artifacts().items():
        path = output_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def check_artifacts(output_dir: Path = ARTIFACTS_DIR) -> list[str]:
    expected = build_artifacts()
    actual_paths = {path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*") if path.is_file()}
    problems = []
    for path in sorted(set(expected) | actual_paths):
        actual = (output_dir / path).read_bytes() if path in actual_paths else None
        if actual != expected.get(path):
            problems.append(path)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--write", action="store_true", help="regenerate the checked-in artifacts")
    action.add_argument("--check", action="store_true", help="verify checked-in artifacts without changing them")
    args = parser.parse_args()
    if args.write:
        write_artifacts()
        return 0
    problems = check_artifacts()
    if problems:
        for problem in problems:
            print(f"out of date: {problem}")
        return 1
    print("production reference artifacts are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
