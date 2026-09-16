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
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generate_artifacts import generate  # noqa: E402
from prototype_contract import WorkspaceResourceStatsReader  # noqa: E402
from runtime_probe import (  # noqa: E402
    _decode_mountinfo,
    _effective_cpuset_count,
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
                return_value=(3.5, [{"quota_us": 350000, "period_us": 100000}]),
            ),
            patch("runtime_probe._cgroup_v2_location", return_value=(Path("/not-emitted"), Path("/not-emitted/job"))),
            patch(
                "runtime_probe._linux_cpu_identity",
                return_value={"architecture": "x86_64", "model": "AMD EPYC 9654"},
            ),
        ):
            metric = probe_cpu()

        self.assertEqual(2, metric["value"])
        self.assertEqual(2, metric["inputs"]["effective_cpuset_logical_cpu_count"])
        self.assertEqual({"architecture": "x86_64", "model": "AMD EPYC 9654"}, metric["dimensions"])
        emitted = json.dumps(metric)
        self.assertNotIn("/not-emitted", emitted)
        self.assertNotIn("cpuset.cpus.effective", emitted)

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
    def test_generator_writes_consistent_artifact_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "artifacts"
            receipt = generate(output_dir, "test-job", "test-study", 0.0)

            client_dir = output_dir / "client_run" / "resource_stats"
            server_dir = output_dir / "server_run" / "resource_stats"
            resource_summary_path = server_dir / "resource_summary.json"
            workspace_archive_path = output_dir / "job_store" / "jobs" / "test-job" / "workspace"
            self.assertTrue((client_dir / "participant_summary.json").is_file())
            participant_summary = json.loads((client_dir / "participant_summary.json").read_text())
            retained = participant_summary["attempts"][0]["retained_content"]
            self.assertEqual("prototype_owned_file_only", retained["coverage"])
            self.assertNotIn("entries", retained)
            self.assertNotIn("relative_path", json.dumps(retained))
            self.assertTrue(resource_summary_path.is_file())
            workspace_reader = WorkspaceResourceStatsReader(workspace_archive_path)
            self.assertEqual(resource_summary_path.read_bytes(), workspace_reader.read_resource_summary_bytes())
            self.assertEqual((server_dir / "manifest.json").read_bytes(), workspace_reader.read_manifest_bytes())
            archive_participant_key = participant_summary["participant_key"].replace("sha256:", "sha256-")
            self.assertEqual(
                (server_dir / "participants" / f"{archive_participant_key}.json").read_bytes(),
                workspace_reader.read_participant_summary_bytes(archive_participant_key),
            )
            self.assertTrue(receipt["integrity"]["workspace_resource_summary_matches"])
            self.assertTrue(receipt["integrity"]["workspace_manifest_matches"])
            self.assertTrue(receipt["integrity"]["workspace_participant_matches"])
            self.assertEqual("workspace", receipt["integrity"]["workspace_component"])

            summary = json.loads(resource_summary_path.read_text())
            self.assertEqual("test-job", summary["job"]["id"])
            self.assertEqual(2, summary["coverage"]["expected_participant_count"])
            self.assertEqual(1, summary["coverage"]["reported_participant_count"])
            self.assertNotIn(str(output_dir), json.dumps(summary))
            metric_names = {metric["name"] for metric in summary["qualified_totals"]["metrics"]}
            self.assertNotIn("visible_storage_capacity_byte_seconds", metric_names)
            rollup_names = {
                metric["name"] for metric in participant_summary["attempts"][0]["rollups"]
            }
            self.assertNotIn("visible_storage_capacity_byte_seconds", rollup_names)
            startup_names = {
                metric["name"] for metric in participant_summary["attempts"][0]["startup_snapshot"]["metrics"]
            }
            self.assertIn("visible_storage_capacity_bytes", startup_names)
            gpu_total = next(
                metric for metric in summary["qualified_totals"]["metrics"] if metric["name"] == "visible_gpu_seconds"
            )
            self.assertEqual("unavailable", gpu_total["status"])
            self.assertEqual(
                {"local-prototype-client", "server"},
                set(gpu_total["contribution_coverage"]["missing_participant_ids"]),
            )

            manifest = json.loads((server_dir / "manifest.json").read_text())
            for entry in manifest["entries"]:
                path = server_dir / entry["relative_path"]
                self.assertEqual(entry["byte_count"], path.stat().st_size)
                self.assertEqual(entry["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

            all_cli = json.loads((output_dir / "cli" / "resources-all.json").read_text())
            selected_cli = json.loads((output_dir / "cli" / "resources-local-prototype-client.json").read_text())
            self.assertTrue(all_cli["data"]["selection"]["is_job_total"])
            self.assertFalse(selected_cli["data"]["selection"]["is_job_total"])
            self.assertTrue((output_dir / "cli" / "resources-not-ready.json").is_file())
            corrupt = json.loads((output_dir / "cli" / "resources-corrupt.json").read_text())
            self.assertEqual(5, corrupt["exit_code"])
            self.assertTrue((output_dir / "cli" / "resources-corrupt.stderr.txt").is_file())
            self.assertTrue((output_dir / "review_contracts" / "manifest.json").is_file())
            self.assertEqual("synthetic_contract_fixture", receipt["review_contract_fixtures"]["provenance"])


if __name__ == "__main__":
    unittest.main()
