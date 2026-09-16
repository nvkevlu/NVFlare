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

import hashlib
import json
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prototype_contract import (  # noqa: E402
    MAX_RESOURCE_MANIFEST_BYTES,
    RESOURCE_MANIFEST_MEMBER,
    RESOURCE_SUMMARY_MEMBER,
    ReporterLeaseConflict,
    ReporterLeaseRegistry,
    WorkspaceArchiveError,
    WorkspaceAttemptStore,
    WorkspaceResourceStatsReader,
    WriteOnceRecordConflict,
)


ATTEMPT_ID = "a" * 32


class TestReporterLeaseRegistry(unittest.TestCase):
    def test_one_reporter_per_job_and_environment_but_cross_job_overlap_remains_allowed(self):
        registry = ReporterLeaseRegistry()
        first = registry.acquire("job-a", "env-shared", "rank-0")
        self.assertIs(first, registry.acquire("job-a", "env-shared", "rank-0"))

        with self.assertRaises(ReporterLeaseConflict):
            registry.acquire("job-a", "env-shared", "rank-1")

        other_job = registry.acquire("job-b", "env-shared", "rank-0")
        self.assertNotEqual(first, other_job)
        self.assertTrue(other_job.as_record()["cross_job_overlap"] == "allowed")
        self.assertFalse(other_job.as_record()["participant_total_is_capacity"])


class TestWorkspaceAttemptStore(unittest.TestCase):
    def test_records_are_self_reported_and_a_missing_final_is_not_invented(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace_root = root / "job_workspace"
            store = WorkspaceAttemptStore(workspace_root)
            observation = {
                "schema_version": "prototype-0.3",
                "kind": "nvflare.resource_stats.attempt_start",
                "job_id": "job-a",
                "attempt_id": ATTEMPT_ID,
                "snapshot": {"resource_types": ["cpu", "memory", "gpu"]},
            }

            first = store.persist_observation("job-a", ATTEMPT_ID, "start.json", observation)
            replay = store.persist_observation("job-a", ATTEMPT_ID, "start.json", observation)
            self.assertTrue(first.created)
            self.assertFalse(replay.created)
            first.path.relative_to(workspace_root.resolve())

            stored = json.loads(first.path.read_text(encoding="utf-8"))
            self.assertEqual("self_reported", stored["trust"]["content_origin"])
            self.assertEqual("existing_job_workspace", stored["trust"]["storage_scope"])
            self.assertFalse(stored["trust"]["protected_from_job_code"])

            conflicting_record = {**observation, "snapshot": {"resource_types": ["cpu", "memory"]}}
            with self.assertRaises(WriteOnceRecordConflict):
                store.persist_observation("job-a", ATTEMPT_ID, "start.json", conflicting_record)

            end_receipt = store.record_attempt_end_without_final(
                "job-a", ATTEMPT_ID, "2026-09-04T11:59:00Z", "2026-09-04T12:00:00Z", "terminated"
            )
            end_record = json.loads(end_receipt.path.read_text(encoding="utf-8"))
            self.assertEqual("integration_supplied", end_record["trust"]["content_origin"])
            self.assertEqual("absent", end_record["final_observation"]["state"])
            self.assertEqual("2026-09-04T11:59:00Z", end_record["opened_at"])
            self.assertEqual("2026-09-04T12:00:00Z", end_record["closed_at"])
            self.assertEqual(
                "opened_at_and_closed_at_use_one_nvflare_clock",
                end_record["resource_window"]["clock_rule"],
            )
            self.assertEqual("integration_supplied", end_record["resource_window"]["basis"])
            self.assertEqual("terminated", end_record["reason"])
            self.assertEqual("not_invented", end_record["resource_observations"]["state"])


class TestWorkspaceResourceStatsReader(unittest.TestCase):
    PARTICIPANT_KEY = "sha256-" + "a" * 64

    @staticmethod
    def _manifest(summary: bytes, participant: bytes | None = None, *, summary_digest: str | None = None) -> bytes:
        entries = [
            {
                "relative_path": "resource_summary.json",
                "byte_count": len(summary),
                "sha256": summary_digest or hashlib.sha256(summary).hexdigest(),
            }
        ]
        if participant is not None:
            entries.append(
                {
                    "relative_path": f"participants/{TestWorkspaceResourceStatsReader.PARTICIPANT_KEY}.json",
                    "byte_count": len(participant),
                    "sha256": hashlib.sha256(participant).hexdigest(),
                }
            )
        return (json.dumps({"entries": entries}, sort_keys=True) + "\n").encode()

    @staticmethod
    def _write_archive(path: Path, members: list[tuple[str, bytes]]) -> None:
        with ZipFile(path, "w", compression=ZIP_STORED) as archive:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                for name, data in members:
                    archive.writestr(name, data)

    def test_reads_only_fixed_manifest_verified_members(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "workspace"
            summary = b'{"kind":"nvflare.resource_stats.resource_summary"}\n'
            participant = b'{"kind":"nvflare.resource_stats.participant_summary"}\n'
            manifest = self._manifest(summary, participant)
            self._write_archive(
                archive_path,
                [
                    (RESOURCE_SUMMARY_MEMBER, summary),
                    (RESOURCE_MANIFEST_MEMBER, manifest),
                    (f"resource_stats/participants/{self.PARTICIPANT_KEY}.json", participant),
                    ("unrelated/job-log.txt", b"not read"),
                ],
            )

            reader = WorkspaceResourceStatsReader(archive_path)
            self.assertEqual(summary, reader.read_resource_summary_bytes())
            self.assertEqual(manifest, reader.read_manifest_bytes())
            self.assertEqual(participant, reader.read_participant_summary_bytes(self.PARTICIPANT_KEY))
            with self.assertRaises(ValueError):
                reader.read_participant_summary_bytes("../resource_summary")

    def test_manifest_limit_matches_the_v1_contract(self):
        self.assertEqual(4 * 1024 * 1024, MAX_RESOURCE_MANIFEST_BYTES)

    def test_rejects_duplicate_exact_member(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "workspace"
            summary = b"{}\n"
            self._write_archive(
                archive_path,
                [
                    (RESOURCE_SUMMARY_MEMBER, summary),
                    (RESOURCE_SUMMARY_MEMBER, summary),
                    (RESOURCE_MANIFEST_MEMBER, self._manifest(summary)),
                ],
            )
            with self.assertRaisesRegex(WorkspaceArchiveError, "exactly one"):
                WorkspaceResourceStatsReader(archive_path).read_resource_summary_bytes()

    def test_rejects_oversize_member_before_returning_it(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "workspace"
            summary = b"12345"
            manifest = self._manifest(summary)
            self._write_archive(
                archive_path,
                [
                    (RESOURCE_SUMMARY_MEMBER, summary),
                    (RESOURCE_MANIFEST_MEMBER, manifest),
                ],
            )
            reader = WorkspaceResourceStatsReader(archive_path, max_resource_summary_bytes=4)
            with self.assertRaisesRegex(WorkspaceArchiveError, "4-byte limit"):
                reader.read_resource_summary_bytes()
            reader = WorkspaceResourceStatsReader(archive_path, max_manifest_bytes=len(manifest) - 1)
            with self.assertRaisesRegex(WorkspaceArchiveError, "byte limit"):
                reader.read_manifest_bytes()

    def test_rejects_manifest_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "workspace"
            summary = b"{}\n"
            self._write_archive(
                archive_path,
                [
                    (RESOURCE_SUMMARY_MEMBER, summary),
                    (RESOURCE_MANIFEST_MEMBER, self._manifest(summary, summary_digest="0" * 64)),
                ],
            )
            with self.assertRaisesRegex(WorkspaceArchiveError, "digest mismatch"):
                WorkspaceResourceStatsReader(archive_path).read_resource_summary_bytes()

    def test_rejects_duplicate_json_object_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            duplicate_summary = b'{"kind":"first","kind":"second"}\n'
            summary_archive = root / "duplicate-summary"
            self._write_archive(
                summary_archive,
                [
                    (RESOURCE_SUMMARY_MEMBER, duplicate_summary),
                    (RESOURCE_MANIFEST_MEMBER, self._manifest(duplicate_summary)),
                ],
            )
            with self.assertRaisesRegex(WorkspaceArchiveError, "duplicate object key 'kind'"):
                WorkspaceResourceStatsReader(summary_archive).read_resource_summary_bytes()

            manifest_archive = root / "duplicate-manifest"
            self._write_archive(
                manifest_archive,
                [
                    (RESOURCE_SUMMARY_MEMBER, b"{}\n"),
                    (RESOURCE_MANIFEST_MEMBER, b'{"entries":[],"entries":[]}\n'),
                ],
            )
            with self.assertRaisesRegex(WorkspaceArchiveError, "duplicate object key 'entries'"):
                WorkspaceResourceStatsReader(manifest_archive).read_manifest_bytes()
