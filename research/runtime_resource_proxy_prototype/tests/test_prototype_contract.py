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
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prototype_contract import (  # noqa: E402
    ATTEMPT_ID_ARGUMENT,
    LAUNCHER_ATTEMPT_ARG_ALLOWLIST,
    RESOURCE_STATS_COMPONENT,
    FixedResourceStatsStore,
    WriteOnceRecordConflict,
    ParentOwnedAttemptStore,
    ReporterLeaseConflict,
    ReporterLeaseRegistry,
    build_sanitized_launch_plan,
)


ATTEMPT_ID = "a" * 32


class TestSanitizedLaunchPlan(unittest.TestCase):
    def test_all_launchers_use_fixed_attempt_argument_after_sanitized_python_start(self):
        for launcher in LAUNCHER_ATTEMPT_ARG_ALLOWLIST:
            with self.subTest(launcher=launcher):
                plan = build_sanitized_launch_plan(
                    launcher=launcher,
                    python_executable="/opt/nvflare/python",
                    module="nvflare.private.fed.app.resource_bootstrap",
                    platform_args=("--workspace", "/workspace"),
                    environment={"PYTHONPATH": "/job/custom:/site/custom", "KEEP_ME": "yes"},
                    attempt_id=ATTEMPT_ID,
                    custom_import_paths=("/job/custom", "/site/custom"),
                )
                self.assertEqual(("-S", "-u", "-m"), plan.argv[1:4])
                self.assertNotIn("PYTHONPATH", plan.pre_python_environment)
                self.assertEqual("yes", plan.pre_python_environment["KEEP_ME"])
                self.assertEqual(("/job/custom", "/site/custom"), plan.post_snapshot_custom_import_paths)
                self.assertNotIn("/job/custom", plan.argv)
                self.assertEqual(1, plan.argv.count(ATTEMPT_ID_ARGUMENT))
                self.assertEqual(ATTEMPT_ID, plan.argv[-1])
                self.assertEqual("capture_platform_owned_start_snapshot", plan.bootstrap_steps[1])
                self.assertEqual("enable_custom_import_paths", plan.bootstrap_steps[-1])

    def test_attempt_argument_cannot_be_supplied_by_callers_or_unknown_launchers(self):
        args = ("--workspace", "/workspace", ATTEMPT_ID_ARGUMENT, "b" * 32)
        with self.assertRaisesRegex(ValueError, "fixed launcher allowlist"):
            build_sanitized_launch_plan(
                "process", "/python", "platform.bootstrap", args, {}, ATTEMPT_ID, ("/job/custom",)
            )
        with self.assertRaisesRegex(ValueError, "unsupported launcher"):
            build_sanitized_launch_plan("unknown", "/python", "platform.bootstrap", (), {}, ATTEMPT_ID)
        with self.assertRaisesRegex(ValueError, "32 lowercase hexadecimal"):
            build_sanitized_launch_plan("process", "/python", "platform.bootstrap", (), {}, "ABC")

    def test_sanitized_python_start_defers_job_sitecustomize_until_after_snapshot(self):
        """Exercise the pre-Python ordering promise with a real child interpreter.

        This is intentionally a bootstrap fixture, not a real NVFlare launcher:
        it proves that the proposed ``-S`` plus stripped ``PYTHONPATH`` boundary
        prevents a job-owned ``sitecustomize`` from executing before the
        platform snapshot marker exists.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            custom = root / "job_custom"
            custom.mkdir()
            snapshot_marker = root / "snapshot-complete"
            site_marker = root / "job-sitecustomize-ran"
            job_marker = root / "job-module-ran"
            (custom / "sitecustomize.py").write_text(
                "from pathlib import Path\n" f"Path({str(site_marker)!r}).write_text('enabled', encoding='utf-8')\n",
                encoding="utf-8",
            )
            (custom / "job_module.py").write_text(
                "from pathlib import Path\n" f"Path({str(job_marker)!r}).write_text('enabled', encoding='utf-8')\n",
                encoding="utf-8",
            )
            plan = build_sanitized_launch_plan(
                "process",
                sys.executable,
                "nvflare.private.fed.app.resource_bootstrap",
                ("--workspace", "/workspace"),
                {"PYTHONPATH": str(custom)},
                ATTEMPT_ID,
                (str(custom),),
            )
            bootstrap = textwrap.dedent(
                f"""
                import importlib
                import sys
                from pathlib import Path

                snapshot = Path({str(snapshot_marker)!r})
                site_marker = Path({str(site_marker)!r})
                assert not site_marker.exists(), 'job sitecustomize ran before snapshot'
                snapshot.write_text('captured', encoding='utf-8')
                sys.path.insert(0, {str(custom)!r})
                importlib.import_module('sitecustomize')
                importlib.import_module('job_module')
                assert snapshot.exists()
                """
            )
            child_environment = dict(os.environ)
            child_environment.pop("PYTHONPATH", None)
            child_environment.update(plan.pre_python_environment)
            completed = subprocess.run(
                [sys.executable, "-S", "-u", "-c", bootstrap],
                cwd=root,
                env=child_environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue(snapshot_marker.is_file())
            self.assertTrue(site_marker.is_file())
            self.assertTrue(job_marker.is_file())


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


class TestParentOwnedAttemptStore(unittest.TestCase):
    def test_child_records_are_write_once_parent_owned_and_crash_exit_invents_no_final_sample(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_writable_root = root / "job_writable"
            parent_owned_root = root / "parent_owned"
            store = ParentOwnedAttemptStore(parent_owned_root, job_writable_root)
            child_record = {
                "schema_version": "prototype-0.3",
                "kind": "nvflare.resource_stats.attempt_start",
                "job_id": "job-a",
                "attempt_id": ATTEMPT_ID,
                "snapshot": {"metric_count": 4},
            }

            first = store.persist_child_fragment("job-a", ATTEMPT_ID, "start.json", child_record)
            replay = store.persist_child_fragment("job-a", ATTEMPT_ID, "start.json", child_record)
            self.assertTrue(first.created)
            self.assertFalse(replay.created)
            with self.assertRaises(ValueError):
                first.path.relative_to(job_writable_root)

            stored_child = json.loads(first.path.read_text(encoding="utf-8"))
            self.assertEqual("platform_parent", stored_child["trust"]["storage_owner"])
            self.assertEqual("child_self_reported", stored_child["trust"]["content_origin"])
            self.assertTrue(stored_child["trust"]["authenticated_handoff_required"])

            conflicting_record = {**child_record, "snapshot": {"metric_count": 5}}
            with self.assertRaises(WriteOnceRecordConflict):
                store.persist_child_fragment("job-a", ATTEMPT_ID, "start.json", conflicting_record)

            exit_receipt = store.record_crash_parent_exit("job-a", ATTEMPT_ID, "2026-09-04T12:00:00Z", 137)
            exit_record = json.loads(exit_receipt.path.read_text(encoding="utf-8"))
            self.assertEqual("parent_observed_lifecycle", exit_record["trust"]["content_origin"])
            self.assertEqual("absent", exit_record["child_final"]["state"])
            self.assertEqual("parent_observed_exit", exit_record["observation_end"]["basis"])
            self.assertEqual("not_invented", exit_record["resource_observations"]["state"])

    def test_parent_storage_must_not_overlap_job_writable_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "must not overlap"):
                ParentOwnedAttemptStore(root / "job_writable" / "resource_stats", root / "job_writable")


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
