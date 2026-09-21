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
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_ROOT = ROOT / "schema" / "golden" / "v1"
FINALIZED_RESOURCE_ROOT = GOLDEN_ROOT / "finalized_job" / "server_run" / "resource_stats"
sys.path.insert(0, str(ROOT))

from prototype_contract import WorkspaceArchiveError  # noqa: E402
from review_contract_fixtures import write_review_contract_fixtures  # noqa: E402


class TestReviewContractFixtures(unittest.TestCase):
    def test_fixtures_make_each_hardened_boundary_reviewable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            canonical_summary = (FINALIZED_RESOURCE_ROOT / "resource_summary.json").read_bytes()
            participant_summaries = {
                path.stem: path.read_bytes()
                for path in sorted((FINALIZED_RESOURCE_ROOT / "participants").glob("*.json"))
            }
            job_id = json.loads(canonical_summary)["job_id"]
            receipt = write_review_contract_fixtures(
                output_dir,
                job_id,
                canonical_summary,
                participant_summaries,
            )
            root = output_dir / "review_contracts"

            self.assertEqual("synthetic_contract_fixture", receipt["provenance"])
            self.assertEqual(5, receipt["entry_count"])
            self.assertEqual(
                sorted(f"review_contracts/{path.name}" for path in root.glob("*.json")),
                receipt["entries"],
            )

            gpu = json.loads((root / "gpu_cuda_runtime_validated.json").read_text())
            self.assertEqual(
                ["visible_full_gpu_count", "visible_mig_compute_instance_count"],
                [metric["name"] for metric in gpu["metrics"]],
            )
            self.assertEqual([1, 2], [m["value"] for m in gpu["metrics"]])
            self.assertEqual("not_emitted", gpu["raw_cuda_visible_devices"])

            network = json.loads((root / "f3_finalization.json").read_text())
            self.assertEqual("5632", network["primary_metrics"][0]["value"])
            self.assertEqual("2", network["primary_metrics"][1]["value"])
            self.assertEqual("256", network["canonical_f3"]["local_delivered"]["payload_bytes"])
            diagnostics = network["post_cutoff_diagnostics_not_embedded_in_summary"]
            self.assertEqual(1024, diagnostics["excluded_summary_publication"]["payload_bytes"])
            self.assertEqual(512, diagnostics["late_after_cutoff"]["payload_bytes"])
            self.assertNotIn("late_after_cutoff", network["canonical_f3"])
            self.assertNotIn("summary_excluded", network["canonical_f3"])

            accumulator = json.loads((root / "resource_time_accumulator.json").read_text())
            self.assertEqual(2, accumulator["observation_events"])
            self.assertEqual(1, accumulator["private_terminal_handoffs"])
            self.assertEqual(1, accumulator["persisted_terminal_reports"])
            self.assertEqual(0, accumulator["public_interval_records"])
            self.assertEqual("terminal_handoff.json", accumulator["terminal_handoff_file"])
            report = accumulator["participant_summary"]
            self.assertNotIn("attempts", report)
            self.assertNotIn("start", report)
            self.assertNotIn("final", report)
            self.assertEqual("900", report["resource_time"]["measured_seconds"])
            self.assertEqual("1200", report["resource_time"]["gpu"]["groups"][0]["instance_seconds"])

            handoff = json.loads((root / "terminal_handoff.json").read_text())
            self.assertEqual("1", handoff["internal_version"])
            self.assertEqual("nvflare.resource_stats.internal.terminal_handoff", handoff["kind"])
            self.assertNotIn("participant_name", handoff)

            archive = json.loads((root / "workspace_archive_reader.json").read_text())
            self.assertEqual("workspace", archive["component"])
            self.assertEqual("resource_stats/resource_summary.json", archive["summary_member"])
            self.assertEqual(
                [f"resource_stats/participants/{participant_name}.json" for participant_name in participant_summaries],
                archive["participant_members"],
            )
            self.assertTrue(archive["summary_matches_canonical"])
            self.assertTrue(archive["participants_match"])
            self.assertFalse(archive["separate_query_component_created"])
            self.assertTrue((root / archive["relative_path"]).is_file())
            with ZipFile(root / archive["relative_path"], "r") as workspace:
                self.assertFalse(any("terminal_handoff.json" in name for name in workspace.namelist()))
                self.assertEqual(
                    {
                        "resource_stats/resource_summary.json",
                        *archive["participant_members"],
                    },
                    set(workspace.namelist()),
                )

    def test_workspace_fixture_rejects_an_incomplete_participant_mapping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            canonical_summary = (FINALIZED_RESOURCE_ROOT / "resource_summary.json").read_bytes()
            one_participant_path = next(iter(sorted((FINALIZED_RESOURCE_ROOT / "participants").glob("*.json"))))
            with self.assertRaisesRegex(WorkspaceArchiveError, "exactly match"):
                write_review_contract_fixtures(
                    Path(temp_dir),
                    json.loads(canonical_summary)["job_id"],
                    canonical_summary,
                    {one_participant_path.stem: one_participant_path.read_bytes()},
                )


if __name__ == "__main__":
    unittest.main()
