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
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schema"
COMMITTED_ROOT = SCHEMA_ROOT / "golden" / "v1" / "finalized_job"
sys.path.insert(0, str(SCHEMA_ROOT))

import build_review_artifacts as artifacts  # noqa: E402
from contract_v1 import load_and_validate, validate_bundle  # noqa: E402


class TestCanonicalReviewArtifacts(unittest.TestCase):
    def test_committed_tree_is_coherent_and_reproducible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temporary_root = Path(temp_dir)
            generated_root = temporary_root / "finalized_job"
            # build() also emits standalone goldens. Redirect that side output
            # so this reproducibility test never mutates the checkout.
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
            self.assertTrue(receipt["query_copy_matches_resource_summary"])
            self.assertEqual("2223", receipt["scenario_basis"]["reference_runtime_seconds"])
            self.assertEqual("590801346560", receipt["scenario_basis"]["reference_logical_state_bytes"])
            self.assertIn("did not measure the proposed post-encoding F3 counter", receipt["scenario_basis"]["f3_note"])
            self.assertEqual("2223", receipt["derived_examples"]["site_1_resource_window_seconds"])
            self.assertEqual("1923", receipt["derived_examples"]["site_2_resource_window_seconds"])
            self.assertEqual("2223", receipt["derived_examples"]["server_resource_window_seconds"])
            self.assertEqual("6369", receipt["derived_examples"]["accepted_resource_window_seconds"])
            self.assertEqual("145656", receipt["derived_examples"]["job_cpu_unit_seconds"])
            self.assertEqual("15984", receipt["derived_examples"]["job_gpu_instance_seconds"])
            self.assertEqual("9010000000000901", receipt["derived_examples"]["large_memory_byte_seconds"])

    def test_archive_manifest_digests_and_query_copy_are_exact(self):
        resource_root = COMMITTED_ROOT / "server_run" / "resource_stats"
        summary_path = resource_root / "resource_summary.json"
        manifest_path = resource_root / "manifest.json"
        summary_bytes = summary_path.read_bytes()
        summary = load_and_validate(summary_bytes)
        manifest = load_and_validate(manifest_path.read_bytes())
        standalone_root = SCHEMA_ROOT / "golden" / "v1"
        self.assertEqual((standalone_root / "resource_summary.json").read_bytes(), summary_bytes)
        self.assertEqual((standalone_root / "manifest.json").read_bytes(), manifest_path.read_bytes())
        participant_records = {}
        files = {"resource_summary.json": summary_bytes}
        for participant_path in sorted((resource_root / "participants").glob("*.json")):
            participant_bytes = participant_path.read_bytes()
            participant = load_and_validate(participant_bytes)
            key = participant["participant_key"]
            participant_records[key] = participant
            files[f"participants/{key}.json"] = participant_bytes
        self.assertEqual(3, len(participant_records))
        for standalone_name in (
            "participant_summary.json",
            "participant_summary_partial_periods.json",
            "participant_summary_server.json",
        ):
            standalone_bytes = (standalone_root / standalone_name).read_bytes()
            participant_key = json.loads(standalone_bytes)["participant_key"]
            self.assertEqual(
                standalone_bytes,
                files[f"participants/{participant_key}.json"],
            )
        validate_bundle(summary, participant_records, manifest, files)

        for entry in manifest["entries"]:
            self.assertEqual(entry["sha256"], hashlib.sha256(files[entry["relative_path"]]).hexdigest())
            self.assertEqual({"relative_path", "sha256"}, set(entry))
        query_copy = COMMITTED_ROOT / "job_store" / "jobs" / summary["job_id"] / "RESOURCE_STATS"
        self.assertEqual(summary_bytes, query_copy.read_bytes())

    def test_default_cli_is_compact_and_hides_inapplicable_mig(self):
        summary = json.loads((COMMITTED_ROOT / "server_run" / "resource_stats" / "resource_summary.json").read_text())
        human = artifacts._human_cli(summary)
        detail = artifacts._hardware_details(summary, "site-1")
        envelope = json.loads((COMMITTED_ROOT / "cli" / "resources-all.json").read_text())

        self.assertIn("job coverage: PARTIAL (3 accepted / 4 expected)", human)
        self.assertIn("Resources visible to the job while it ran.", human)
        self.assertNotIn("These are not utilization", human)
        self.assertNotIn("reserved capacity, or billing data", human)
        self.assertIn("site-1   client  accepted", human)
        self.assertIn("site-2   client  accepted  PARTIAL", human)
        self.assertIn("site-3   client  missing", human)
        self.assertIn("server   server  accepted", human)
        self.assertIn("MEASURED TIME", human)
        self.assertIn("37m3s", human)
        self.assertIn("32m3s", human)
        self.assertIn("MEASURED TIME 1h46m9s", human)
        self.assertIn("4.4400", human)
        self.assertNotIn("STORAGE", human)
        self.assertIn("REPORTED", human)
        self.assertIn("Site QUALITY PARTIAL", human)
        self.assertIn("SAVED RESULT GiB", human)
        self.assertIn("F3 REMOTE ACCEPTED GiB", human)
        self.assertIn("27.5115", human)
        self.assertIn("550.2266", human)
        self.assertIn("Totals from received reports | overall: PARTIAL", human)
        self.assertIn("JOB COVERAGE PARTIAL means not every expected report was accepted", human)
        self.assertNotIn("MIG", human)
        self.assertNotIn("MIG", detail)
        self.assertIn("AMD EPYC 9654 (x86_64)", detail)
        self.assertIn("NVIDIA A100 80GB", detail)
        selected = (COMMITTED_ROOT / "cli" / "resources-site-1-details.txt").read_text()
        self.assertIn("Resources visible to the job while it ran", selected)
        self.assertIn("selected site: site-1", selected)
        self.assertIn("job coverage: PARTIAL", selected)
        self.assertIn("site-1   client  accepted  REPORTED", selected)
        self.assertIn("Hardware detail for site-1", selected)
        self.assertIn("NVIDIA A100 80GB", selected)
        selected_partial = (COMMITTED_ROOT / "cli" / "resources-site-2-details.txt").read_text()
        self.assertIn("selected site: site-2", selected_partial)
        self.assertIn("site-2   client  accepted  PARTIAL", selected_partial)
        self.assertIn("32m3s", selected_partial)
        self.assertIn("Intel Xeon Platinum 8480+", selected_partial)
        self.assertIn("NVIDIA A100 80GB", selected_partial)
        self.assertEqual(summary, envelope["data"]["summary"])
        self.assertEqual({"job_id": summary["job_id"], "site": "all"}, envelope["data"]["selection"])
        self.assertNotIn("storage", summary["totals"])
        self.assertTrue(all("storage" not in entry.get("totals", {}) for entry in summary["participants"]))
        self.assertTrue(
            all(
                group["kind"] == "full_gpu"
                for entry in summary["participants"]
                if entry["status"] == "accepted"
                for group in entry["totals"]["gpu"].get("groups", [])
            )
        )

    def test_cli_shows_mig_only_for_a_positive_applicable_group(self):
        summary = json.loads((SCHEMA_ROOT / "golden" / "v1" / "resource_summary.json").read_text())
        zero_mig = {
            "kind": "mig_compute_instance",
            "model": "NVIDIA H100 80GB HBM3",
            "memory_bytes": "10737418240",
            "mig_profile": "1g.10gb",
            "instance_seconds": "0",
        }
        summary["participants"][0]["totals"]["gpu"]["groups"].append(zero_mig)
        self.assertNotIn("MIG", artifacts._human_cli(summary))

        summary["participants"][0]["totals"]["gpu"]["groups"][-1]["instance_seconds"] = "3600"
        human = artifacts._human_cli(summary)
        self.assertIn("MIG CI h", human)
        self.assertIn("1.0000", human)
        detail = artifacts._hardware_details(summary, "site-1")
        self.assertIn("MIG compute instance", detail)

    def test_cli_values_use_compact_totals_not_f3_side_buckets(self):
        summary = json.loads((SCHEMA_ROOT / "golden" / "v1" / "resource_summary.json").read_text())
        human = artifacts._human_cli(summary)
        accepted = summary["participants"][0]
        self.assertEqual("147700336640", accepted["totals"]["f3"]["remote_accepted"]["payload_bytes"])
        self.assertIn("137.5567", human)

        final = json.loads((SCHEMA_ROOT / "golden" / "v1" / "participant_final.json").read_text())
        self.assertEqual("0", final["f3"]["local_delivered"]["payload_bytes"])
        self.assertNotIn("late_after_cutoff", final["f3"])
        self.assertNotIn("summary_excluded", final["f3"])
        self.assertNotIn("local_delivered", accepted["totals"]["f3"])


if __name__ == "__main__":
    unittest.main()
