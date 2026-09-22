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

import json
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_ROOT = ROOT / "schema" / "golden" / "v1"
sys.path.insert(0, str(ROOT))

from prototype_contract import (  # noqa: E402
    INTERNAL_HANDOFF_KIND,
    INTERNAL_HANDOFF_VERSION,
    MAX_TERMINAL_HANDOFF_BYTES,
    RESOURCE_SUMMARY_MEMBER,
    AccumulatorClosedError,
    InvalidTerminalHandoff,
    ObservationOrderError,
    ResourceTimeAccumulator,
    WorkspaceArchiveError,
    WorkspaceResourceStatsReader,
    assemble_participant_summary,
    load_terminal_handoff,
)
from schema.contract_v1 import derive_job_totals  # noqa: E402

FINALIZED_RESOURCE_ROOT = GOLDEN_ROOT / "finalized_job" / "server_run" / "resource_stats"


class TestResourceTimeAccumulator(unittest.TestCase):
    @staticmethod
    def capacity(cpu: str, memory: str, gpu_count: str) -> dict:
        return {
            "cpu": {
                "units": cpu,
                "model": "AMD EPYC 9654",
                "architecture": "x86_64",
            },
            "memory": {"bytes": memory},
            "gpu": {
                "groups": (
                    [
                        {
                            "kind": "full_gpu",
                            "count": gpu_count,
                            "model": "NVIDIA A100 80GB",
                            "memory_bytes": "85899345920",
                        }
                    ]
                    if gpu_count != "0"
                    else []
                )
            },
        }

    @staticmethod
    def handoff_fields() -> dict:
        return {
            "workspace_filesystem": {
                "status": "reported",
                "capacity_bytes": "1099511627776",
            },
            "retained_content": {"status": "reported", "bytes": "0"},
            "child_f3": {
                "status": "reported",
                "remote_accepted": {"payload_bytes": "100", "messages": "1"},
            },
        }

    @staticmethod
    def assemble(handoff: dict | None) -> dict:
        return assemble_participant_summary(
            job_id="job-a",
            participant_name="site-a",
            reported_at="2026-09-09T14:37:03Z",
            child_handoff=handoff,
            parent_f3={
                "status": "reported",
                "remote_accepted": {"payload_bytes": "300", "messages": "2"},
            },
        )

    def test_one_terminal_report_accumulates_resource_changes(self):
        accumulator = ResourceTimeAccumulator()
        accumulator.observe(100, self.capacity("8", "68719476736", "0"))
        accumulator.observe(160, self.capacity("8", "68719476736", "2"))
        handoff = accumulator.finish_measurements(280, **self.handoff_fields())
        self.assertEqual(INTERNAL_HANDOFF_VERSION, handoff["internal_version"])
        self.assertEqual(INTERNAL_HANDOFF_KIND, handoff["kind"])
        self.assertNotIn("participant_name", handoff)
        report = self.assemble(handoff)

        self.assertEqual("nvflare.resource_stats.participant_summary", report["kind"])
        self.assertNotIn("start", report)
        self.assertNotIn("final", report)
        self.assertNotIn("attempts", report)
        resource_time = report["resource_time"]
        self.assertEqual("reported", resource_time["status"])
        self.assertEqual("180", resource_time["measured_seconds"])
        self.assertEqual("1440", resource_time["cpu"]["groups"][0]["unit_seconds"])
        self.assertEqual(
            str(68719476736 * 180),
            resource_time["memory"]["byte_seconds"],
        )
        self.assertEqual("240", resource_time["gpu"]["groups"][0]["instance_seconds"])
        self.assertEqual("400", report["f3"]["remote_accepted"]["payload_bytes"])
        self.assertEqual("3", report["f3"]["remote_accepted"]["messages"])
        with self.assertRaises(AccumulatorClosedError):
            accumulator.observe(300, self.capacity("8", "68719476736", "0"))

    def test_missing_observation_makes_the_single_compute_status_partial(self):
        accumulator = ResourceTimeAccumulator()
        accumulator.observe(0, self.capacity("4", "34359738368", "1"))
        accumulator.mark_gap(30)
        report = self.assemble(accumulator.finish_measurements(45, **self.handoff_fields()))

        self.assertEqual("partial", report["resource_time"]["status"])
        self.assertEqual("30", report["resource_time"]["measured_seconds"])
        self.assertEqual(["observation_incomplete"], report["resource_time"]["issues"])

    def test_no_observation_is_unavailable_and_time_must_be_monotonic(self):
        unavailable = self.assemble(ResourceTimeAccumulator().finish_measurements(20, **self.handoff_fields()))
        self.assertEqual(
            {
                "status": "unavailable",
                "issues": ["observation_incomplete"],
            },
            unavailable["resource_time"],
        )

        accumulator = ResourceTimeAccumulator()
        accumulator.observe(20, self.capacity("4", "34359738368", "0"))
        with self.assertRaises(ObservationOrderError):
            accumulator.observe(19, self.capacity("4", "34359738368", "0"))

    def test_large_products_stay_exact_and_fractional_intervals_round_once(self):
        accumulator = ResourceTimeAccumulator()
        accumulator.observe(
            0,
            {
                "cpu": {"units": "1"},
                "memory": {"bytes": "10000000000001"},
                "gpu": {"groups": []},
            },
        )
        exact = self.assemble(accumulator.finish_measurements(901, **self.handoff_fields()))
        self.assertEqual(
            "9010000000000901",
            exact["resource_time"]["memory"]["byte_seconds"],
        )

        fractional = ResourceTimeAccumulator()
        fractional.observe(
            0,
            {
                "cpu": {"units": "1"},
                "memory": {"bytes": "1"},
                "gpu": {"groups": []},
            },
        )
        rounded = self.assemble(fractional.finish_measurements("0.333333333333", **self.handoff_fields()))
        self.assertEqual("0.333333333", rounded["resource_time"]["measured_seconds"])
        self.assertEqual("0.333333333", rounded["resource_time"]["memory"]["byte_seconds"])

    def test_parent_still_emits_one_typed_report_when_child_handoff_is_missing(self):
        report = self.assemble(None)
        self.assertEqual("unavailable", report["resource_time"]["status"])
        self.assertEqual("unavailable", report["workspace_filesystem"]["status"])
        self.assertEqual("unavailable", report["retained_content"]["status"])
        self.assertEqual("partial", report["f3"]["status"])
        self.assertEqual(["attribution_incomplete"], report["f3"]["issues"])
        self.assertEqual("300", report["f3"]["remote_accepted"]["payload_bytes"])

    def test_invalid_or_oversized_child_handoff_cannot_suppress_parent_report(self):
        malformed = self.handoff_fields()
        malformed["internal_version"] = INTERNAL_HANDOFF_VERSION
        malformed["kind"] = INTERNAL_HANDOFF_KIND
        malformed["resource_time"] = {"status": "reported", "made_up": "1"}
        report = self.assemble(malformed)
        self.assertEqual("unavailable", report["resource_time"]["status"])
        self.assertEqual("partial", report["f3"]["status"])

        valid_handoff = ResourceTimeAccumulator()
        valid_handoff.observe(0, self.capacity("4", "34359738368", "0"))
        handoff = valid_handoff.finish_measurements(10, **self.handoff_fields())
        encoded = json.dumps(handoff).encode()
        self.assertEqual(handoff, load_terminal_handoff(encoded))
        self.assertEqual(1 * 1024 * 1024, MAX_TERMINAL_HANDOFF_BYTES)
        with self.assertRaisesRegex(InvalidTerminalHandoff, "8-byte limit"):
            load_terminal_handoff(encoded, max_bytes=8)


class TestWorkspaceResourceStatsReader(unittest.TestCase):
    PARTICIPANT_NAME = "site-1"

    @staticmethod
    def _json_bytes(record: dict) -> bytes:
        return (json.dumps(record, indent=2) + "\n").encode()

    @staticmethod
    def _participant_bytes() -> dict[str, bytes]:
        return {
            path.stem: path.read_bytes() for path in sorted((FINALIZED_RESOURCE_ROOT / "participants").glob("*.json"))
        }

    @staticmethod
    def _valid_summary() -> bytes:
        return (GOLDEN_ROOT / "resource_summary.json").read_bytes()

    @staticmethod
    def _valid_participant() -> bytes:
        return (GOLDEN_ROOT / "participant_summary.json").read_bytes()

    @staticmethod
    def _write_archive(path: Path, members: list[tuple[str, bytes]]) -> None:
        with ZipFile(path, "w", compression=ZIP_STORED) as archive:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                for name, data in members:
                    archive.writestr(name, data)

    def test_reads_only_summary_derived_fixed_members(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "workspace"
            summary = (FINALIZED_RESOURCE_ROOT / "resource_summary.json").read_bytes()
            participants = self._participant_bytes()
            self._write_archive(
                archive_path,
                [
                    *[
                        (f"resource_stats/participants/{participant_name}.json", data)
                        for participant_name, data in participants.items()
                    ],
                    (RESOURCE_SUMMARY_MEMBER, summary),
                    ("unrelated/job-log.txt", b"not read"),
                ],
            )

            reader = WorkspaceResourceStatsReader(archive_path)
            self.assertEqual(summary, reader.read_resource_summary_bytes())
            self.assertEqual(
                participants[self.PARTICIPANT_NAME],
                reader.read_participant_summary_bytes(self.PARTICIPANT_NAME),
            )
            with self.assertRaises(ValueError):
                reader.read_participant_summary_bytes("../resource_summary")

    def test_archive_member_order_does_not_change_summary_derived_inventory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "workspace"
            summary = (FINALIZED_RESOURCE_ROOT / "resource_summary.json").read_bytes()
            participants = self._participant_bytes()
            self._write_archive(
                archive_path,
                [
                    (RESOURCE_SUMMARY_MEMBER, summary),
                    *[
                        (f"resource_stats/participants/{participant_name}.json", data)
                        for participant_name, data in participants.items()
                    ],
                ],
            )

            reader = WorkspaceResourceStatsReader(archive_path)
            self.assertEqual(summary, reader.read_resource_summary_bytes())
            self.assertEqual(
                participants[self.PARTICIPANT_NAME],
                reader.read_participant_summary_bytes(self.PARTICIPANT_NAME),
            )

    def test_allows_only_the_two_canonical_directory_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "workspace"
            summary = (FINALIZED_RESOURCE_ROOT / "resource_summary.json").read_bytes()
            participants = self._participant_bytes()
            self._write_archive(
                archive_path,
                [
                    ("resource_stats/", b""),
                    ("resource_stats/participants/", b""),
                    *[
                        (f"resource_stats/participants/{participant_name}.json", data)
                        for participant_name, data in participants.items()
                    ],
                    (RESOURCE_SUMMARY_MEMBER, summary),
                ],
            )

            self.assertEqual(summary, WorkspaceResourceStatsReader(archive_path).read_resource_summary_bytes())

    def test_rejects_inventory_that_does_not_exactly_match_accepted_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            summary = self._valid_summary()
            participant = self._valid_participant()

            missing_archive = root / "missing-accepted-participants"
            self._write_archive(
                missing_archive,
                [
                    (f"resource_stats/participants/{self.PARTICIPANT_NAME}.json", participant),
                    (RESOURCE_SUMMARY_MEMBER, summary),
                ],
            )
            with self.assertRaisesRegex(WorkspaceArchiveError, "exactly match"):
                WorkspaceResourceStatsReader(missing_archive).read_resource_summary_bytes()

            participants = self._participant_bytes()
            unexpected_name = "site-unexpected"
            participants[unexpected_name] = b"{}\n"
            extra_archive = root / "nonaccepted-participant"
            self._write_archive(
                extra_archive,
                [
                    *[
                        (f"resource_stats/participants/{participant_name}.json", data)
                        for participant_name, data in participants.items()
                    ],
                    (RESOURCE_SUMMARY_MEMBER, summary),
                ],
            )
            with self.assertRaisesRegex(WorkspaceArchiveError, "exactly match"):
                WorkspaceResourceStatsReader(extra_archive).read_resource_summary_bytes()

    def test_rejects_participant_values_that_disagree_with_accepted_summary_entry(self):
        mutations = {
            "resource_time": lambda entry: entry["resource_time"]["cpu"]["groups"][0].__setitem__(
                "unit_seconds", "71137"
            ),
            "retained_content": lambda entry: entry["retained_content"].__setitem__("bytes", "1"),
            "f3": lambda entry: entry["f3"]["remote_accepted"].__setitem__("payload_bytes", "147700336641"),
        }
        for field, mutate in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp_dir:
                archive_path = Path(temp_dir) / "workspace"
                participants = self._participant_bytes()
                summary_record = json.loads(self._valid_summary())
                accepted = next(
                    entry
                    for entry in summary_record["participants"]
                    if entry["participant_name"] == self.PARTICIPANT_NAME
                )
                mutate(accepted)
                summary_record["totals"] = derive_job_totals(summary_record["participants"])
                summary = self._json_bytes(summary_record)
                self._write_archive(
                    archive_path,
                    [
                        *[
                            (f"resource_stats/participants/{participant_name}.json", data)
                            for participant_name, data in participants.items()
                        ],
                        (RESOURCE_SUMMARY_MEMBER, summary),
                    ],
                )

                with self.assertRaisesRegex(WorkspaceArchiveError, field):
                    WorkspaceResourceStatsReader(archive_path).read_participant_summary_bytes(self.PARTICIPANT_NAME)

    def test_rejects_duplicate_exact_member(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "workspace"
            summary = self._valid_summary()
            self._write_archive(
                archive_path,
                [
                    (RESOURCE_SUMMARY_MEMBER, summary),
                    (RESOURCE_SUMMARY_MEMBER, summary),
                ],
            )
            with self.assertRaisesRegex(WorkspaceArchiveError, "exactly one"):
                WorkspaceResourceStatsReader(archive_path).read_resource_summary_bytes()

    def test_rejects_oversize_member_before_returning_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "workspace"
            summary = self._valid_summary()
            self._write_archive(
                archive_path,
                [
                    (RESOURCE_SUMMARY_MEMBER, summary),
                ],
            )
            reader = WorkspaceResourceStatsReader(archive_path, max_resource_summary_bytes=4)
            with self.assertRaisesRegex(WorkspaceArchiveError, "4-byte limit"):
                reader.read_resource_summary_bytes()

    def test_rejects_duplicate_json_object_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            duplicate_summary = b'{"kind":"first","kind":"second"}\n'
            summary_archive = root / "duplicate-summary"
            self._write_archive(
                summary_archive,
                [
                    (RESOURCE_SUMMARY_MEMBER, duplicate_summary),
                ],
            )
            with self.assertRaisesRegex(WorkspaceArchiveError, "duplicate JSON object key 'kind'"):
                WorkspaceResourceStatsReader(summary_archive).read_resource_summary_bytes()

    def test_rejects_staging_member_inside_final_resource_stats_namespace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "workspace"
            summary = self._valid_summary()
            self._write_archive(
                archive_path,
                [
                    (RESOURCE_SUMMARY_MEMBER, summary),
                    ("resource_stats/staging/terminal_handoff.json", b"{}\n"),
                ],
            )
            with self.assertRaisesRegex(WorkspaceArchiveError, "exactly match"):
                WorkspaceResourceStatsReader(archive_path).read_resource_summary_bytes()

    def test_rejects_staging_directory_inside_final_resource_stats_namespace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "workspace"
            summary = self._valid_summary()
            participants = self._participant_bytes()
            self._write_archive(
                archive_path,
                [
                    *[
                        (f"resource_stats/participants/{participant_name}.json", data)
                        for participant_name, data in participants.items()
                    ],
                    (RESOURCE_SUMMARY_MEMBER, summary),
                    ("resource_stats/staging/", b""),
                ],
            )
            with self.assertRaisesRegex(WorkspaceArchiveError, "exactly match"):
                WorkspaceResourceStatsReader(archive_path).read_resource_summary_bytes()
