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
    HANDOFF_LOCATOR_ARGUMENT,
    LAUNCHER_ATTEMPT_ARG_ALLOWLIST,
    RESOURCE_STATS_COMPONENT,
    FixedResourceStatsStore,
    WriteOnceRecordConflict,
    SupervisorOwnedAttemptStore,
    ReporterLeaseConflict,
    ReporterLeaseRegistry,
    build_sanitized_launch_plan,
)


ATTEMPT_ID = "a" * 32
HANDOFF_LOCATOR = "b" * 32


class TestSanitizedLaunchPlan(unittest.TestCase):
    def test_all_launchers_use_fixed_attempt_argument_after_sanitized_python_start(self):
        for launcher in LAUNCHER_ATTEMPT_ARG_ALLOWLIST:
            with self.subTest(launcher=launcher):
                plan = build_sanitized_launch_plan(
                    launcher=launcher,
                    python_executable="/opt/nvflare/python",
                    trusted_bootstrap_path="/opt/nvflare/platform/resource_bootstrap.py",
                    platform_args=("--workspace", "/workspace"),
                    environment={
                        "PYTHONPATH": "/job/custom:/site/custom",
                        "PYTHONHOME": "/job/python",
                        "KEEP_ME": "no",
                        "CUDA_VISIBLE_DEVICES": "0",
                    },
                    attempt_id=ATTEMPT_ID,
                    handoff_locator=HANDOFF_LOCATOR,
                    custom_import_paths=("/job/custom", "/site/custom"),
                    platform_owned_cwd="/opt/nvflare/platform",
                )
                self.assertEqual(("-I", "-S", "-u"), plan.argv[1:4])
                self.assertEqual("/opt/nvflare/platform/resource_bootstrap.py", plan.argv[4])
                self.assertNotIn("PYTHONPATH", plan.pre_python_environment)
                self.assertNotIn("PYTHONHOME", plan.pre_python_environment)
                self.assertNotIn("KEEP_ME", plan.pre_python_environment)
                self.assertEqual({"CUDA_VISIBLE_DEVICES": "0"}, plan.pre_python_environment)
                self.assertEqual(("/job/custom", "/site/custom"), plan.post_snapshot_custom_import_paths)
                self.assertNotIn("/job/custom", plan.argv)
                self.assertEqual(1, plan.argv.count(ATTEMPT_ID_ARGUMENT))
                self.assertEqual(ATTEMPT_ID, plan.argv[plan.argv.index(ATTEMPT_ID_ARGUMENT) + 1])
                self.assertEqual(1, plan.argv.count(HANDOFF_LOCATOR_ARGUMENT))
                self.assertEqual(HANDOFF_LOCATOR, plan.argv[-1])
                self.assertEqual("capture_platform_owned_start_snapshot", plan.bootstrap_steps[2])
                self.assertEqual("enable_custom_import_paths", plan.bootstrap_steps[-1])

    def test_attempt_argument_cannot_be_supplied_by_callers_or_unknown_launchers(self):
        for forbidden_arg, forbidden_value in (
            (ATTEMPT_ID_ARGUMENT, ATTEMPT_ID),
            (HANDOFF_LOCATOR_ARGUMENT, HANDOFF_LOCATOR),
        ):
            with self.subTest(forbidden_arg=forbidden_arg):
                args = ("--workspace", "/workspace", forbidden_arg, forbidden_value)
                with self.assertRaisesRegex(ValueError, "fixed launcher allowlist"):
                    build_sanitized_launch_plan(
                        "process",
                        "/python",
                        "/platform/bootstrap.py",
                        args,
                        {},
                        ATTEMPT_ID,
                        HANDOFF_LOCATOR,
                        ("/job/custom",),
                        platform_owned_cwd="/platform",
                    )
        with self.assertRaisesRegex(ValueError, "unsupported launcher"):
            build_sanitized_launch_plan(
                "unknown",
                "/python",
                "/platform/bootstrap.py",
                (),
                {},
                ATTEMPT_ID,
                HANDOFF_LOCATOR,
                platform_owned_cwd="/platform",
            )
        with self.assertRaisesRegex(ValueError, "32 lowercase hexadecimal"):
            build_sanitized_launch_plan(
                "process",
                "/python",
                "/platform/bootstrap.py",
                (),
                {},
                "ABC",
                HANDOFF_LOCATOR,
                platform_owned_cwd="/platform",
            )
        with self.assertRaisesRegex(ValueError, "handoff_locator"):
            build_sanitized_launch_plan(
                "process",
                "/python",
                "/platform/bootstrap.py",
                (),
                {},
                ATTEMPT_ID,
                "BAD",
                platform_owned_cwd="/platform",
            )
        with self.assertRaisesRegex(ValueError, "inside platform_owned_cwd"):
            build_sanitized_launch_plan(
                "process",
                "/python",
                "/job/bootstrap.py",
                (),
                {},
                ATTEMPT_ID,
                HANDOFF_LOCATOR,
                platform_owned_cwd="/platform",
            )

    def test_isolated_absolute_bootstrap_defeats_cwd_shadowing_and_defers_custom_imports(self):
        """Exercise the pre-custom-code boundary with a real child interpreter.

        This is intentionally a bootstrap fixture, not a real NVFlare launcher:
        it proves that an absolute platform-owned script plus ``-I -S``, a
        platform-owned cwd, and the environment allowlist defeat both module
        shadowing and job-owned ``sitecustomize`` before the snapshot marker.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            platform = root / "platform"
            platform.mkdir()
            job_cwd = root / "job"
            malicious_package = job_cwd / "nvflare" / "private" / "fed" / "app"
            malicious_package.mkdir(parents=True)
            package_dirs = [
                job_cwd / "nvflare",
                job_cwd / "nvflare" / "private",
                job_cwd / "nvflare" / "private" / "fed",
                malicious_package,
            ]
            for package in package_dirs:
                (package / "__init__.py").write_text("", encoding="utf-8")
            custom = root / "job_custom"
            custom.mkdir()
            snapshot_marker = root / "snapshot-complete"
            site_marker = root / "job-sitecustomize-ran"
            job_marker = root / "job-module-ran"
            malicious_marker = root / "job-bootstrap-ran"
            (malicious_package / "resource_bootstrap.py").write_text(
                "from pathlib import Path\n" f"Path({str(malicious_marker)!r}).write_text('bad', encoding='utf-8')\n",
                encoding="utf-8",
            )
            (custom / "sitecustomize.py").write_text(
                "from pathlib import Path\n" f"Path({str(site_marker)!r}).write_text('enabled', encoding='utf-8')\n",
                encoding="utf-8",
            )
            (custom / "job_module.py").write_text(
                "from pathlib import Path\n" f"Path({str(job_marker)!r}).write_text('enabled', encoding='utf-8')\n",
                encoding="utf-8",
            )
            bootstrap_path = platform / "resource_bootstrap.py"
            bootstrap_path.write_text(textwrap.dedent(
                f"""
                import importlib
                import sys
                from pathlib import Path

                snapshot = Path({str(snapshot_marker)!r})
                site_marker = Path({str(site_marker)!r})
                malicious_marker = Path({str(malicious_marker)!r})
                assert not site_marker.exists(), 'job sitecustomize ran before snapshot'
                assert not malicious_marker.exists(), 'job bootstrap shadowed platform bootstrap'
                snapshot.write_text('captured', encoding='utf-8')
                sys.path.insert(0, {str(custom)!r})
                importlib.import_module('sitecustomize')
                importlib.import_module('job_module')
                assert snapshot.exists()
                """
            ), encoding="utf-8")
            plan = build_sanitized_launch_plan(
                "process",
                sys.executable,
                str(bootstrap_path),
                ("--workspace", "/workspace"),
                {"PYTHONPATH": str(custom), "PYTHONHOME": str(job_cwd), "KEEP_ME": "no"},
                ATTEMPT_ID,
                HANDOFF_LOCATOR,
                (str(custom),),
                platform_owned_cwd=str(platform),
            )
            completed = subprocess.run(
                plan.argv,
                cwd=plan.platform_owned_cwd,
                env=plan.pre_python_environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue(snapshot_marker.is_file())
            self.assertTrue(site_marker.is_file())
            self.assertTrue(job_marker.is_file())
            self.assertFalse(malicious_marker.exists())


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


class TestSupervisorOwnedAttemptStore(unittest.TestCase):
    def test_worker_records_are_write_once_and_terminated_window_invents_no_final_sample(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            job_writable_root = root / "job_writable"
            supervisor_owned_root = root / "supervisor_owned"
            store = SupervisorOwnedAttemptStore(supervisor_owned_root, job_writable_root)
            worker_record = {
                "schema_version": "prototype-0.3",
                "kind": "nvflare.resource_stats.attempt_start",
                "job_id": "job-a",
                "attempt_id": ATTEMPT_ID,
                "snapshot": {"resource_types": ["cpu", "memory", "gpu"]},
            }

            first = store.persist_worker_fragment("job-a", ATTEMPT_ID, "start.json", worker_record)
            replay = store.persist_worker_fragment("job-a", ATTEMPT_ID, "start.json", worker_record)
            self.assertTrue(first.created)
            self.assertFalse(replay.created)
            with self.assertRaises(ValueError):
                first.path.relative_to(job_writable_root)

            stored_worker = json.loads(first.path.read_text(encoding="utf-8"))
            self.assertEqual("site_supervisor", stored_worker["trust"]["storage_owner"])
            self.assertEqual("worker_self_reported", stored_worker["trust"]["content_origin"])
            self.assertTrue(stored_worker["trust"]["authenticated_handoff_required"])

            conflicting_record = {**worker_record, "snapshot": {"resource_types": ["cpu", "memory"]}}
            with self.assertRaises(WriteOnceRecordConflict):
                store.persist_worker_fragment("job-a", ATTEMPT_ID, "start.json", conflicting_record)

            end_receipt = store.record_attempt_end_without_final(
                "job-a", ATTEMPT_ID, "2026-09-04T11:59:00Z", "2026-09-04T12:00:00Z", "terminated"
            )
            end_record = json.loads(end_receipt.path.read_text(encoding="utf-8"))
            self.assertEqual("supervisor_observed_lifecycle", end_record["trust"]["content_origin"])
            self.assertEqual("absent", end_record["worker_final"]["state"])
            self.assertEqual("2026-09-04T11:59:00Z", end_record["opened_at"])
            self.assertEqual("2026-09-04T12:00:00Z", end_record["closed_at"])
            self.assertEqual("site_supervisor", end_record["resource_window"]["clock_owner"])
            self.assertEqual("supervisor_confirmed_acquire_release", end_record["resource_window"]["basis"])
            self.assertEqual("terminated", end_record["reason"])
            self.assertEqual("not_invented", end_record["resource_observations"]["state"])

    def test_parent_storage_must_not_overlap_job_writable_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "must not overlap"):
                SupervisorOwnedAttemptStore(root / "job_writable" / "resource_stats", root / "job_writable")


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
