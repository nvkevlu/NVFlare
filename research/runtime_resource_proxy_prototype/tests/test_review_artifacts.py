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
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schema"
COMMITTED_ROOT = SCHEMA_ROOT / "golden" / "v1" / "finalized_job"
sys.path.insert(0, str(SCHEMA_ROOT))

import build_review_artifacts as artifacts  # noqa: E402
from contract_v1 import derive_study_totals, load_and_validate, validate_bundle  # noqa: E402


class TestCanonicalReviewArtifacts(unittest.TestCase):
    def test_committed_tree_is_coherent_and_reproducible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temporary_root = Path(temp_dir)
            generated_root = temporary_root / "finalized_job"
            with patch.object(artifacts, "GOLDEN_ROOT", temporary_root / "standalone"):
                receipt = artifacts.build(generated_root)

            generated_files = {
                path.relative_to(generated_root): path.read_bytes()
                for path in generated_root.rglob("*")
                if path.is_file()
            }
            committed_files = {
                path.relative_to(COMMITTED_ROOT): path.read_bytes()
                for path in COMMITTED_ROOT.rglob("*")
                if path.is_file()
            }
            self.assertEqual(generated_files, committed_files)
            generated_standalone = {
                path.name: path.read_bytes() for path in (temporary_root / "standalone").glob("*.json")
            }
            committed_standalone = {
                path.name: path.read_bytes() for path in (SCHEMA_ROOT / "golden" / "v1").glob("*.json")
            }
            self.assertEqual(generated_standalone, committed_standalone)
            self.assertEqual(receipt, json.loads(generated_files[Path("generation_receipt.json")]))
            self.assertEqual("build_review_artifacts.py", receipt["generator"])
            self.assertEqual(3, receipt["public_participant_reports"])
            self.assertEqual(0, receipt["public_start_or_final_fragments"])
            self.assertEqual("workspace", receipt["workspace_component"])
            self.assertTrue(receipt["workspace_resource_summary_matches"])
            self.assertTrue(receipt["study_job_workspace_resource_summary_matches"])
            self.assertEqual("2223", receipt["scenario_basis"]["reference_runtime_seconds"])
            self.assertEqual("590801346560", receipt["scenario_basis"]["reference_logical_state_bytes"])
            self.assertEqual("2223", receipt["derived_examples"]["site_1_measured_seconds"])
            self.assertEqual("1923", receipt["derived_examples"]["site_2_measured_seconds"])
            self.assertEqual("2223", receipt["derived_examples"]["server_measured_seconds"])
            self.assertEqual("6369", receipt["derived_examples"]["accepted_measured_seconds"])
            self.assertEqual("145656", receipt["derived_examples"]["job_cpu_unit_seconds"])
            self.assertEqual("15984", receipt["derived_examples"]["job_gpu_instance_seconds"])
            self.assertEqual("1988856", receipt["derived_examples"]["study_cpu_unit_seconds"])
            self.assertEqual("131184", receipt["derived_examples"]["study_gpu_instance_seconds"])
            self.assertEqual("9010000000000901", receipt["derived_examples"]["large_memory_byte_seconds"])

    def test_archive_inventory_and_participant_copies_are_exact(self):
        resource_root = COMMITTED_ROOT / "server_run" / "resource_stats"
        summary_path = resource_root / "resource_summary.json"
        summary_bytes = summary_path.read_bytes()
        summary = load_and_validate(summary_bytes)
        standalone_root = SCHEMA_ROOT / "golden" / "v1"
        self.assertEqual((standalone_root / "resource_summary.json").read_bytes(), summary_bytes)
        participant_records = {}
        files = {"resource_summary.json": summary_bytes}
        for participant_path in sorted((resource_root / "participants").glob("*.json")):
            participant_bytes = participant_path.read_bytes()
            participant = load_and_validate(participant_bytes)
            name = participant["participant_name"]
            participant_records[name] = participant
            files[f"participants/{name}.json"] = participant_bytes
        self.assertEqual(3, len(participant_records))
        for standalone_name in (
            "participant_summary.json",
            "participant_summary_partial.json",
            "participant_summary_server.json",
        ):
            standalone_bytes = (standalone_root / standalone_name).read_bytes()
            participant_name = json.loads(standalone_bytes)["participant_name"]
            self.assertEqual(standalone_bytes, files[f"participants/{participant_name}.json"])
        validate_bundle(summary, participant_records, files)

        workspace_archive = COMMITTED_ROOT / "job_store" / "jobs" / summary["job_id"] / "workspace"
        with ZipFile(workspace_archive, "r") as archive:
            expected_resource_members = {"resource_stats/resource_summary.json"} | {
                f"resource_stats/participants/{participant_name}.json" for participant_name in participant_records
            }
            actual_resource_members = {name for name in archive.namelist() if name.startswith("resource_stats/")}
            self.assertEqual(expected_resource_members, actual_resource_members)
            self.assertEqual(summary_bytes, archive.read("resource_stats/resource_summary.json"))
            for participant_name in participant_records:
                member = f"resource_stats/participants/{participant_name}.json"
                self.assertEqual(files[f"participants/{participant_name}.json"], archive.read(member))

    def test_one_terminal_report_shape_and_compact_job_cli(self):
        standalone_root = SCHEMA_ROOT / "golden" / "v1"
        participant = json.loads((standalone_root / "participant_summary.json").read_text())
        self.assertEqual(
            {
                "schema_version",
                "kind",
                "job_id",
                "participant_name",
                "reported_at",
                "resource_time",
                "workspace_filesystem",
                "retained_content",
                "f3",
            },
            set(participant),
        )
        self.assertNotIn("attempts", participant)
        self.assertNotIn("start", participant)
        self.assertNotIn("final", participant)

        summary = json.loads((COMMITTED_ROOT / "server_run/resource_stats/resource_summary.json").read_text())
        human = artifacts._human_cli(summary)
        detail = artifacts._hardware_details(summary, "site-1")
        envelope = json.loads((COMMITTED_ROOT / "cli/resources-all.json").read_text())

        self.assertIn("Job coverage: PARTIAL (3 accepted / 4 expected)", human)
        self.assertIn("site-1", human)
        self.assertIn("site-2", human)
        self.assertIn("site-3", human)
        self.assertIn("server", human)
        self.assertIn("Recorded average visible capacity over each measured interval", human)
        self.assertIn("CPU UNITS", human)
        self.assertIn("MEM GiB", human)
        self.assertIn("FULL GPUs", human)
        self.assertIn("Summed measured participant time: 1h46m9s", human)
        self.assertIn("FULL GPUs 4.4400 instance h", human)
        self.assertIn("CPU 40.4600 unit h", human)
        self.assertIn("MEMORY 255.3067 GiB h", human)
        self.assertIn("SAVED CONTENT 27.5115 GiB", human)
        self.assertIn("F3 REMOTE ACCEPTED 550.2266 GiB", human)
        self.assertNotIn("STORAGE", human)
        self.assertNotIn("not utilization", human)
        self.assertNotIn("reserved capacity", human)
        self.assertNotIn("MIG", human)
        self.assertNotIn("MIG", detail)
        self.assertIn("AMD EPYC 9654 (x86_64)", detail)
        self.assertIn("NVIDIA A100 80GB", detail)
        selected = (COMMITTED_ROOT / "cli/resources-site-1-details.txt").read_text()
        self.assertIn("selected site: site-1", selected)
        self.assertIn("Hardware detail for site-1", selected)
        self.assertIn("Visible workspace-filesystem capacity at reporting time", selected)
        self.assertEqual(summary, envelope["data"]["summary"])
        self.assertEqual({"job_id": summary["job_id"], "site": "all"}, envelope["data"]["selection"])
        self.assertNotIn("workspace_filesystem", summary["totals"])
        self.assertTrue(all("workspace_filesystem" not in entry for entry in summary["participants"]))

    def test_cli_shows_mig_only_when_a_group_is_applicable(self):
        summary = json.loads((SCHEMA_ROOT / "golden/v1/resource_summary.json").read_text())
        self.assertNotIn("MIG", artifacts._human_cli(summary))

        positive_mig = {
            "kind": "mig_compute_instance",
            "model": "NVIDIA H100 80GB HBM3",
            "memory_bytes": "10737418240",
            "mig_profile": "1g.10gb",
            "instance_seconds": "3600",
        }
        summary["participants"][0]["resource_time"]["gpu"]["groups"].append(positive_mig)
        human = artifacts._human_cli(summary)
        self.assertIn("MIG INSTANCES", human)
        self.assertIn("1.6194", human)
        detail = artifacts._hardware_details(summary, "site-1")
        self.assertIn("MIG compute instance", detail)

    def test_study_cli_reconciles_selected_jobs_and_additive_totals(self):
        standalone_root = SCHEMA_ROOT / "golden" / "v1"
        study = load_and_validate((standalone_root / "study_summary.json").read_bytes())
        self.assertEqual(
            {
                "selected_jobs": "4",
                "included_jobs": "2",
                "unavailable_jobs": "1",
                "nonterminal_jobs": "1",
            },
            study["coverage"],
        )
        self.assertEqual(study["totals"], derive_study_totals(study["jobs"]))
        self.assertEqual(
            {"included", "unavailable", "nonterminal"},
            {row["resource_data"] for row in study["jobs"]},
        )
        included = {row["job_id"]: row for row in study["jobs"] if row["resource_data"] == "included"}
        for job_id, filename in (
            ("job-20260909-001", "resource_summary.json"),
            ("job-20260910-002", "resource_summary_study_job.json"),
        ):
            data = (standalone_root / filename).read_bytes()
            self.assertEqual(json.loads(data)["totals"], included[job_id]["totals"])

        human = (COMMITTED_ROOT / "cli/resources-study.txt").read_text()
        envelope = json.loads((COMMITTED_ROOT / "cli/resources-study.json").read_text())
        self.assertIn("Resources recorded for finalized jobs in study cancer-research", human)
        self.assertIn("4 jobs found | 3 finalized | 2 valid summaries", human)
        self.assertIn("1 unavailable | 1 still running (excluded)", human)
        self.assertIn("Study totals from 2 valid job summaries | coverage: PARTIAL", human)
        self.assertIn("FULL GPUs 36.4400 instance h", human)
        self.assertIn("CPU 552.4600 unit h", human)
        self.assertIn("MEMORY 2303.3067 GiB h", human)
        self.assertNotIn("MIG", human)
        self.assertEqual({"study": "cancer-research"}, envelope["data"]["selection"])
        self.assertEqual(study, envelope["data"]["summary"])

        with_mig = json.loads(json.dumps(study))
        mig_group = {
            "kind": "mig_compute_instance",
            "model": "NVIDIA H100 80GB HBM3",
            "memory_bytes": "10737418240",
            "mig_profile": "1g.10gb",
            "instance_seconds": "7200",
        }
        with_mig["jobs"][0]["totals"]["resource_time"]["gpu"]["groups"].append(mig_group)
        with_mig["totals"]["resource_time"]["gpu"]["groups"].append(mig_group)
        mig_human = artifacts._human_study_cli(with_mig)
        self.assertIn("MIG h", mig_human)
        self.assertIn("MIG INSTANCES 2.0000 instance h", mig_human)

        partial_saved = json.loads(json.dumps(study))
        included_row = partial_saved["jobs"][1]
        partial_saved["jobs"] = [included_row]
        partial_saved["coverage"] = {
            "selected_jobs": "1",
            "included_jobs": "1",
            "unavailable_jobs": "0",
            "nonterminal_jobs": "0",
        }
        included_row["totals"]["retained_content"]["status"] = "partial"
        partial_saved["totals"] = json.loads(json.dumps(included_row["totals"]))
        partial_human = artifacts._human_study_cli(partial_saved)
        self.assertIn("RESOURCE DATA  QUALITY", partial_human)
        self.assertIn("included       PARTIAL", partial_human)
        self.assertIn("coverage: PARTIAL", partial_human)

    def test_f3_job_total_keeps_only_the_additive_remote_counter(self):
        summary = json.loads((SCHEMA_ROOT / "golden/v1/resource_summary.json").read_text())
        accepted = summary["participants"][0]
        self.assertEqual("147700336640", accepted["f3"]["remote_accepted"]["payload_bytes"])
        self.assertIn("local_delivered", accepted["f3"])
        self.assertEqual(
            {"status", "remote_accepted"},
            set(summary["totals"]["f3"]),
        )
        self.assertNotIn("late_after_cutoff", json.dumps(summary))
        self.assertNotIn("summary_excluded", json.dumps(summary))


if __name__ == "__main__":
    unittest.main()
