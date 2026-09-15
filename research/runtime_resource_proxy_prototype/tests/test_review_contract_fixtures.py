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
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from review_contract_fixtures import write_review_contract_fixtures  # noqa: E402


class TestReviewContractFixtures(unittest.TestCase):
    def test_fixtures_make_each_hardened_boundary_reviewable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            canonical_summary = b'{"kind":"nvflare.resource_stats.resource_summary"}\n'
            receipt = write_review_contract_fixtures(output_dir, "fixture-job", canonical_summary)
            root = output_dir / "review_contracts"

            self.assertEqual("synthetic_contract_fixture", receipt["provenance"])
            self.assertTrue((root / "manifest.json").is_file())

            bootstrap = json.loads((root / "trusted_bootstrap_plans.json").read_text())
            self.assertEqual({"process", "docker", "k8s", "slurm"}, {p["launcher"] for p in bootstrap["plans"]})
            for plan in bootstrap["plans"]:
                self.assertEqual(["-I", "-S", "-u"], plan["argv"][1:4])
                self.assertEqual("/opt/nvflare/platform", plan["platform_owned_cwd"])
                self.assertEqual("/opt/nvflare/platform/resource_bootstrap.py", plan["trusted_bootstrap_path"])
                self.assertEqual("4" * 32, plan["handoff_locator"])
                self.assertNotIn("PYTHONPATH", plan["pre_python_environment"])
                self.assertNotIn("PYTHONHOME", plan["pre_python_environment"])
                self.assertEqual("capture_platform_owned_start_snapshot", plan["bootstrap_steps"][2])

            gpu = json.loads((root / "gpu_cuda_runtime_validated.json").read_text())
            self.assertEqual(
                ["visible_full_gpu_count", "visible_mig_compute_instance_count"],
                [metric["name"] for metric in gpu["metrics"]],
            )
            self.assertEqual([1, 2], [m["value"] for m in gpu["metrics"]])
            self.assertEqual("not_emitted", gpu["raw_cuda_visible_devices"])

            network = json.loads((root / "f3_finalization.json").read_text())
            self.assertEqual(5632, network["primary_metrics"][0]["value"])
            self.assertEqual(2, network["primary_metrics"][1]["value"])
            self.assertEqual(256, network["canonical_f3"]["local_delivered"]["payload_bytes"])
            diagnostics = network["post_cutoff_diagnostics_not_embedded_in_summary"]
            self.assertEqual(1024, diagnostics["excluded_summary_publication"]["payload_bytes"])
            self.assertEqual(512, diagnostics["late_after_cutoff"]["payload_bytes"])
            self.assertNotIn("late_after_cutoff", network["canonical_f3"])
            self.assertNotIn("summary_excluded", network["canonical_f3"])

            lease = json.loads((root / "reporter_lease.json").read_text())
            self.assertTrue(lease["same_job_same_environment_second_rank_suppressed"])
            self.assertTrue(lease["different_job_same_environment"]["cross_job_overlap"] == "allowed")
            self.assertFalse(lease["owner"]["participant_total_is_capacity"])

            fragments = json.loads((root / "supervisor_owned_fragments.json").read_text())
            self.assertEqual("supervisor_owned_fragments", fragments["supervisor_owned_root"])
            end_record = next(record for record in fragments["records"] if "end.json" in record["relative_path"])
            end_path = root / end_record["relative_path"]
            attempt_end = json.loads(end_path.read_text())
            self.assertEqual("site_supervisor", attempt_end["resource_window"]["clock_owner"])
            self.assertEqual("supervisor_confirmed_acquire_release", attempt_end["resource_window"]["basis"])
            self.assertEqual("terminated", attempt_end["reason"])
            self.assertEqual("not_invented", attempt_end["resource_observations"]["state"])

            component = json.loads((root / "fixed_resource_stats_component.json").read_text())
            self.assertEqual("RESOURCE_STATS", component["component"])
            self.assertTrue(component["exact_component_allowed"])
            self.assertFalse(component["prefix_variant_allowed"])
            self.assertTrue(component["byte_identical_to_canonical_summary"])


if __name__ == "__main__":
    unittest.main()
