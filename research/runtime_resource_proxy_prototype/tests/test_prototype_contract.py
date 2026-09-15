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

import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prototype_contract import (  # noqa: E402
    RESOURCE_STATS_COMPONENT,
    FixedResourceStatsStore,
    ReporterLeaseConflict,
    ReporterLeaseRegistry,
    WorkspaceAttemptStore,
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


class TestFixedResourceStatsStore(unittest.TestCase):
    def test_resource_stats_is_one_exact_component_and_api_has_no_caller_selected_component(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = FixedResourceStatsStore(Path(temp_dir) / "job_store")
            payload = b'{"kind":"nvflare.resource_stats.resource_summary"}\n'
            receipt = store.save_resource_stats("job-a", payload)
            self.assertEqual(RESOURCE_STATS_COMPONENT, receipt.path.name)
            self.assertEqual(payload, store.get_resource_stats("job-a"))
            self.assertTrue(FixedResourceStatsStore.is_allowed_component(RESOURCE_STATS_COMPONENT))
            self.assertFalse(FixedResourceStatsStore.is_allowed_component("RESOURCE_STATS_site-1"))
            self.assertFalse(FixedResourceStatsStore.is_allowed_component("RESOURCE_STATS.json"))

            with self.assertRaises(WriteOnceRecordConflict):
                store.save_resource_stats("job-a", b"different bytes")

            self.assertNotIn("component", inspect.signature(store.save_resource_stats).parameters)
            self.assertNotIn("component", inspect.signature(store.get_resource_stats).parameters)
