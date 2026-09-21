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
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generate_artifacts import _finish_local_report, generate  # noqa: E402
from prototype_contract import WorkspaceResourceStatsReader  # noqa: E402
from runtime_probe import (  # noqa: E402
    _decode_mountinfo,
    _effective_cpuset_count,
    _finite_v2_cpu_quota,
    _linux_cpu_identity,
    _parse_cpuset_count,
    _path_under_mount,
    probe_cpu,
    probe_gpu,
    probe_gpu_records,
    probe_storage,
)


class TestRuntimeProbe(unittest.TestCase):
    def test_mountinfo_escape_is_decoded(self):
        self.assertEqual("/a b", _decode_mountinfo("/a\\040b"))

    def test_cgroup_path_at_mount_root_is_not_duplicated(self):
        mount = {"root": "/slice", "mount_point": "/sys/fs/cgroup/cpu"}
        self.assertEqual(Path("/sys/fs/cgroup/cpu"), _path_under_mount(mount, "/slice"))

    def test_cpuset_parser_counts_unique_ranges_without_preserving_topology(self):
        self.assertEqual(7, _parse_cpuset_count("0-3,2-5,8"))
        self.assertIsNone(_parse_cpuset_count("3-1"))
        self.assertIsNone(_parse_cpuset_count("0-3,token"))

    def test_v2_effective_cpuset_uses_narrowest_ancestor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mount = Path(temp_dir)
            parent = mount / "parent"
            leaf = parent / "leaf"
            leaf.mkdir(parents=True)
            (mount / "cpuset.cpus.effective").write_text("0-15", encoding="utf-8")
            (parent / "cpuset.cpus.effective").write_text("2-9", encoding="utf-8")
            (leaf / "cpuset.cpus.effective").write_text("4-5,8", encoding="utf-8")

            with patch("runtime_probe._cgroup_v2_location", return_value=(mount, leaf)):
                count, version = _effective_cpuset_count()

        self.assertEqual(3, count)
        self.assertEqual("v2", version)

    def test_v1_cpuset_falls_back_to_cpuset_cpus(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mount = Path(temp_dir)
            leaf = mount / "leaf"
            leaf.mkdir()
            (mount / "cpuset.effective_cpus").write_text("0-7", encoding="utf-8")
            (leaf / "cpuset.cpus").write_text("2-3", encoding="utf-8")

            with (
                patch("runtime_probe._cgroup_v2_location", return_value=(None, None)),
                patch("runtime_probe._cgroup_v1_location", return_value=(mount, leaf)),
            ):
                count, version = _effective_cpuset_count()

        self.assertEqual(2, count)
        self.assertEqual("v1", version)

    def test_cpu_identity_uses_only_affinity_visible_homogeneous_models(self):
        cpuinfo = """
processor : 0
model name : AMD EPYC 9654
flags : private topology detail

processor : 1
model name : AMD   EPYC 9654

processor : 2
model name : Intel Xeon Platinum 8480+
"""
        with (
            patch("runtime_probe._read_text", return_value=cpuinfo),
            patch("runtime_probe.platform.machine", return_value="x86_64"),
        ):
            identity = _linux_cpu_identity({0, 1})
            heterogeneous = _linux_cpu_identity({0, 2})

        self.assertEqual({"architecture": "x86_64", "model": "AMD EPYC 9654"}, identity)
        self.assertEqual({"architecture": "x86_64"}, heterogeneous)
        self.assertNotIn("flags", json.dumps(identity))
        self.assertNotIn("processor", json.dumps(identity))

    def test_cpu_capacity_selects_cpuset_and_emits_only_normalized_identity(self):
        with (
            patch("runtime_probe.platform.system", return_value="Linux"),
            patch("runtime_probe.os.sched_getaffinity", return_value={0, 1, 2, 3}, create=True),
            patch("runtime_probe._online_cpu_count", return_value=8),
            patch("runtime_probe._effective_cpuset_count", return_value=(2, "v2")),
            patch(
                "runtime_probe._finite_v2_cpu_quota",
                return_value=("3.5", [{"quota_us": 350000, "period_us": 100000}]),
            ),
            patch("runtime_probe._cgroup_v2_location", return_value=(Path("/not-emitted"), Path("/not-emitted/job"))),
            patch(
                "runtime_probe._linux_cpu_identity",
                return_value={"architecture": "x86_64", "model": "AMD EPYC 9654"},
            ),
        ):
            metric = probe_cpu()

        self.assertEqual("2", metric["value"])
        self.assertEqual(2, metric["inputs"]["effective_cpuset_logical_cpu_count"])
        self.assertEqual({"architecture": "x86_64", "model": "AMD EPYC 9654"}, metric["dimensions"])
        emitted = json.dumps(metric)
        self.assertNotIn("/not-emitted", emitted)
        self.assertNotIn("cpuset.cpus.effective", emitted)

    def test_cpu_quota_is_exactly_floored_to_nine_decimal_places(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            mount = Path(temp_dir)
            leaf = mount / "leaf"
            leaf.mkdir()
            (leaf / "cpu.max").write_text("2 3", encoding="utf-8")

            with patch("runtime_probe._cgroup_v2_location", return_value=(mount, leaf)):
                quota, inputs = _finite_v2_cpu_quota()

        self.assertEqual("0.666666666", quota)
        self.assertEqual([{"quota_us": 2, "period_us": 3}], inputs)

    def test_gpu_mask_is_not_treated_as_a_device_count(self):
        for mask in ("", "0,0", "-1", "MIG-GPU-irrelevant/1/2"):
            with self.subTest(mask=mask), patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": mask}, clear=False):
                metric = probe_gpu()
                self.assertEqual("unavailable", metric["status"])
                self.assertIsNone(metric["value"])
                if mask:
                    # The date portion of an unrelated RFC 3339 timestamp can
                    # contain short masks such as ``-1``. Check the emitted
                    # resource payload after removing that timestamp field.
                    payload = {key: value for key, value in metric.items() if key != "observed_at"}
                    self.assertNotIn(mask, json.dumps(payload))

    def test_cuda_runtime_records_keep_full_gpus_and_mig_instances_separate(self):
        class Runtime:
            def enumerate_visible_devices(self):
                return [
                    {"cuda_identity": "cuda-full-0", "device_kind": "full_gpu"},
                    {"cuda_identity": "cuda-mig-0", "device_kind": "mig_compute_instance"},
                    {"cuda_identity": "cuda-mig-1", "device_kind": "mig_compute_instance"},
                ]

        class Nvml:
            def enrich_cuda_device(self, cuda_identity):
                return {
                    "cuda_identity": cuda_identity,
                    "vendor": "nvidia",
                    "model": "NVIDIA A100-SXM4-40GB",
                    "memory_bytes": 40 * 1024**3,
                    "mig_profile": "1g.5gb" if "mig" in cuda_identity else None,
                }

        # The duplicated mask must not alter a count supplied by the validated
        # runtime. It remains only a redacted diagnostic.
        with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "0,0"}, clear=False):
            records = probe_gpu_records(Runtime(), Nvml())

        self.assertEqual(["visible_full_gpu_count", "visible_mig_compute_instance_count"], [r["name"] for r in records])
        self.assertEqual([1, 2], [r["value"] for r in records])
        self.assertEqual(["full_gpu_instances", "mig_compute_instances"], [r["unit"] for r in records])
        self.assertEqual("full_gpu", records[0]["dimensions"]["device_kind"])
        self.assertEqual("mig_compute_instance", records[1]["dimensions"]["device_kind"])
        self.assertEqual("complete", records[0]["inputs"]["nvml_enrichment"])
        self.assertEqual("complete", records[1]["inputs"]["nvml_enrichment"])
        self.assertTrue(records[0]["inputs"]["cuda_visible_devices_set"])
        self.assertIn("CUDA_VISIBLE_DEVICES_SET_DIAGNOSTIC_ONLY", records[0]["caveat_codes"])
        emitted = json.dumps(records)
        self.assertNotIn("cuda-full-0", emitted)
        self.assertNotIn("cuda-mig-0", emitted)
        self.assertNotIn("0,0", emitted)

    def test_nvml_mismatch_cannot_create_or_change_a_cuda_runtime_group(self):
        class Runtime:
            def enumerate_visible_devices(self):
                return [{"cuda_identity": "cuda-full-0", "device_kind": "full_gpu"}]

        class MismatchedNvml:
            def enrich_cuda_device(self, _cuda_identity):
                return {
                    "cuda_identity": "some-other-device",
                    "model": "must-not-be-emitted",
                    "memory_bytes": 80 * 1024**3,
                }

        records = probe_gpu_records(Runtime(), MismatchedNvml())
        full_gpu = records[0]
        self.assertEqual("visible_full_gpu_count", full_gpu["name"])
        self.assertEqual(1, full_gpu["value"])
        self.assertEqual("unavailable", full_gpu["inputs"]["nvml_enrichment"])
        self.assertNotIn("model", full_gpu["dimensions"])
        self.assertNotIn("must-not-be-emitted", json.dumps(records))

    def test_invalid_or_failed_runtime_enumeration_has_no_numeric_count(self):
        class InvalidRuntime:
            def enumerate_visible_devices(self):
                return [{"cuda_identity": "duplicate", "device_kind": "full_gpu"}] * 2

        class FailingRuntime:
            def enumerate_visible_devices(self):
                raise RuntimeError("driver detail must not be emitted")

        for runtime, expected_caveat in (
            (InvalidRuntime(), "CUDA_RUNTIME_ENUMERATION_INVALID"),
            (FailingRuntime(), "CUDA_RUNTIME_ENUMERATION_FAILED"),
        ):
            with self.subTest(runtime=type(runtime).__name__):
                records = probe_gpu_records(runtime)
                self.assertEqual(1, len(records))
                self.assertEqual("unavailable", records[0]["status"])
                self.assertIsNone(records[0]["value"])
                self.assertIn(expected_caveat, records[0]["caveat_codes"])
                self.assertNotIn("driver detail", json.dumps(records))

    def test_storage_rejects_a_non_directory_workspace(self):
        with tempfile.NamedTemporaryFile() as stream:
            metric = probe_storage(Path(stream.name))
        self.assertEqual("unavailable", metric["status"])
        self.assertIsNone(metric["value"])
        self.assertEqual(["WORKSPACE_PATH_NOT_DIRECTORY"], metric["caveat_codes"])

    def test_storage_observes_only_the_supplied_workspace_filesystem(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with patch("runtime_probe.os.statvfs", wraps=os.statvfs) as statvfs:
                metric = probe_storage(workspace)
        statvfs.assert_called_once_with(workspace)
        self.assertEqual("visible_storage_capacity_bytes", metric["name"])
        self.assertEqual("reported", metric["status"])
        self.assertGreater(metric["value"], 0)


class TestGeneratedArtifacts(unittest.TestCase):
    def test_numeric_partial_probe_produces_partial_resource_time(self):
        cpu = {
            "value": "0.666666666",
            "status": "partial",
            "coverage": "partial",
            "dimensions": {"architecture": "x86_64"},
        }
        memory = {
            "value": 1024,
            "status": "reported",
            "coverage": "complete",
        }
        gpu = [
            {
                "value": 1,
                "status": "reported",
                "coverage": "complete",
                "dimensions": {"device_kind": "full_gpu"},
            },
            {
                "value": 0,
                "status": "reported",
                "coverage": "complete",
                "dimensions": {"device_kind": "mig_compute_instance"},
            },
        ]
        storage = {
            "value": 4096,
            "status": "reported",
            "coverage": "complete",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("generate_artifacts.probe_cpu", return_value=cpu),
                patch("generate_artifacts.probe_memory", return_value=memory),
                patch("generate_artifacts.probe_gpu_records", return_value=gpu),
                patch("generate_artifacts.probe_storage", return_value=storage),
                patch("generate_artifacts.time.monotonic_ns", side_effect=[10_000_000_000, 12_000_000_000]),
            ):
                report, _evidence, handoff = _finish_local_report(
                    "test-job",
                    "test-client",
                    Path(temp_dir),
                    0.0,
                )

        resource_time = report["resource_time"]
        self.assertEqual("partial", resource_time["status"])
        self.assertEqual(["observation_incomplete"], resource_time["issues"])
        self.assertEqual("2", resource_time["measured_seconds"])
        self.assertEqual("1.333333332", resource_time["cpu"]["groups"][0]["unit_seconds"])
        self.assertEqual("nvflare.resource_stats.internal.terminal_handoff", handoff["kind"])
        self.assertNotIn("job_id", handoff)
        self.assertNotIn("participant_name", handoff)

    def test_generator_writes_one_terminal_report_and_study_view(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "artifacts"
            receipt = generate(output_dir, "test-job", "test-study", 0.0)

            child_staging_dir = output_dir / "client_child" / "resource_stats" / "staging"
            parent_dir = output_dir / "client_parent" / "resource_stats"
            server_dir = output_dir / "server_run" / "resource_stats"
            resource_summary_path = server_dir / "resource_summary.json"
            workspace_archive_path = output_dir / "job_store" / "jobs" / "test-job" / "workspace"
            self.assertTrue((child_staging_dir / "terminal_handoff.json").is_file())
            handoff = json.loads((child_staging_dir / "terminal_handoff.json").read_text())
            self.assertEqual("1", handoff["internal_version"])
            self.assertEqual("nvflare.resource_stats.internal.terminal_handoff", handoff["kind"])
            self.assertFalse((child_staging_dir / "probe_evidence.json").exists())
            self.assertTrue((output_dir / "prototype_diagnostics" / "probe_evidence.json").is_file())
            self.assertTrue((parent_dir / "participant_summary.json").is_file())
            participant_summary = json.loads((parent_dir / "participant_summary.json").read_text())
            self.assertEqual(
                "nvflare.resource_stats.participant_summary",
                participant_summary["kind"],
            )
            self.assertNotIn("attempts", participant_summary)
            self.assertNotIn("start", participant_summary)
            self.assertNotIn("final", participant_summary)
            self.assertIn(
                participant_summary["resource_time"]["status"],
                {"reported", "partial", "unavailable"},
            )
            self.assertEqual("unavailable", participant_summary["retained_content"]["status"])
            self.assertEqual(["not_bound"], participant_summary["retained_content"]["issues"])
            self.assertIn("workspace_filesystem", participant_summary)
            self.assertTrue(resource_summary_path.is_file())
            workspace_reader = WorkspaceResourceStatsReader(workspace_archive_path)
            self.assertEqual(resource_summary_path.read_bytes(), workspace_reader.read_resource_summary_bytes())
            archive_participant_name = participant_summary["participant_name"]
            self.assertEqual(
                (server_dir / "participants" / f"{archive_participant_name}.json").read_bytes(),
                workspace_reader.read_participant_summary_bytes(archive_participant_name),
            )
            self.assertTrue(receipt["integrity"]["workspace_resource_summary_matches"])
            self.assertTrue(receipt["integrity"]["workspace_participant_matches"])
            self.assertEqual("workspace", receipt["integrity"]["workspace_component"])
            self.assertEqual(1, receipt["public_participant_reports"])
            self.assertEqual(0, receipt["public_start_or_final_fragments"])
            self.assertEqual(1, receipt["private_terminal_handoffs"])
            self.assertEqual(
                "client_child/resource_stats/staging/terminal_handoff.json",
                receipt["private_terminal_handoff_path"],
            )

            summary = json.loads(resource_summary_path.read_text())
            self.assertEqual("test-job", summary["job_id"])
            self.assertEqual(1, len(summary["participants"]))
            self.assertEqual("accepted", summary["participants"][0]["status"])
            self.assertEqual(
                participant_summary["resource_time"],
                summary["totals"]["resource_time"],
            )
            self.assertNotIn("workspace_filesystem", summary["totals"])
            self.assertNotIn(str(output_dir), json.dumps(summary))

            with ZipFile(workspace_archive_path, "r") as workspace:
                self.assertFalse(any("terminal_handoff.json" in name for name in workspace.namelist()))
                self.assertFalse(any("probe_evidence.json" in name for name in workspace.namelist()))
                self.assertEqual(
                    {
                        "resource_stats/resource_summary.json",
                        f"resource_stats/participants/{archive_participant_name}.json",
                    },
                    {name for name in workspace.namelist() if name.startswith("resource_stats/")},
                )

            all_cli = json.loads((output_dir / "cli" / "resources-all.json").read_text())
            self.assertEqual("test-job", all_cli["data"]["selection"]["job_id"])
            study_cli = json.loads((output_dir / "cli" / "resources-study.json").read_text())
            self.assertEqual({"study": "test-study"}, study_cli["data"]["selection"])
            study_summary = study_cli["data"]["summary"]
            self.assertEqual("test-study", study_summary["selection"]["study_name"])
            self.assertEqual("1", study_summary["coverage"]["included_jobs"])
            self.assertEqual("included", study_summary["jobs"][0]["resource_data"])
            study_text = (output_dir / "cli" / "resources-study.txt").read_text()
            self.assertIn("JOB STATUS", study_text)
            self.assertIn("FULL GPU h", study_text)
            self.assertIn("coverage:", study_text)
            self.assertIn("still running (excluded)", study_text)
            self.assertNotIn("RESOURCE DATA  GPU h", study_text)
            self.assertNotIn("billing data", study_text)
            has_positive_mig = any(
                group["kind"] == "mig_compute_instance" and Decimal(group["instance_seconds"]) > 0
                for group in study_summary["totals"]["resource_time"].get("gpu", {}).get("groups", [])
            )
            self.assertEqual(has_positive_mig, "MIG h" in study_text)
            self.assertEqual("synthetic_contract_fixture", receipt["review_contract_fixtures"]["provenance"])
            self.assertEqual(
                sorted(f"review_contracts/{path.name}" for path in (output_dir / "review_contracts").glob("*.json")),
                receipt["review_contract_fixtures"]["entries"],
            )


if __name__ == "__main__":
    unittest.main()
