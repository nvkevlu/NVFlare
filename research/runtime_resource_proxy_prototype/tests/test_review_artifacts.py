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
            self.assertEqual(receipt, json.loads(generated_files[Path("generation_receipt.json")]))
            self.assertEqual("build_review_artifacts.py", receipt["generator"])
            self.assertTrue(receipt["query_copy_matches_resource_summary"])
            self.assertEqual("342.5", receipt["derived_examples"]["observation_seconds"])
            self.assertEqual("513.75", receipt["derived_examples"]["cpu_unit_seconds"])
            self.assertEqual("9010000000000901", receipt["derived_examples"]["large_storage_byte_seconds"])

    def test_archive_manifest_digests_and_query_copy_are_exact(self):
        resource_root = COMMITTED_ROOT / "server_run" / "resource_stats"
        summary_path = resource_root / "resource_summary.json"
        participant_path = next((resource_root / "participants").glob("*.json"))
        manifest_path = resource_root / "manifest.json"
        summary_bytes = summary_path.read_bytes()
        participant_bytes = participant_path.read_bytes()
        summary = load_and_validate(summary_bytes)
        participant = load_and_validate(participant_bytes)
        manifest = load_and_validate(manifest_path.read_bytes())
        key = participant["participant_key"]
        files = {
            "resource_summary.json": summary_bytes,
            f"participants/{key}.json": participant_bytes,
        }
        validate_bundle(summary, {key: participant}, manifest, files)

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

        self.assertIn("coverage: PARTIAL (1 accepted / 2 expected)", human)
        self.assertIn("site-1   client  accepted", human)
        self.assertIn("server   server  missing", human)
        self.assertIn("5.5000 KiB", human)
        self.assertNotIn("MIG", human)
        self.assertNotIn("MIG", detail)
        self.assertIn("AMD EPYC 9654 (x86_64)", detail)
        self.assertIn("NVIDIA H100 80GB HBM3", detail)
        self.assertEqual(summary, envelope["data"]["summary"])
        self.assertEqual({"job_id": summary["job_id"], "site": "all"}, envelope["data"]["selection"])
        self.assertTrue(
            all(
                group["kind"] == "full_gpu"
                for entry in summary["roster"]
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
        summary["roster"][0]["totals"]["gpu"]["groups"].append(zero_mig)
        self.assertNotIn("MIG", artifacts._human_cli(summary))

        summary["roster"][0]["totals"]["gpu"]["groups"][-1]["instance_seconds"] = "3600"
        human = artifacts._human_cli(summary)
        self.assertIn("MIG CI h", human)
        self.assertIn("1.0000", human)
        detail = artifacts._hardware_details(summary, "site-1")
        self.assertIn("MIG compute instance", detail)

    def test_cli_values_use_compact_totals_not_f3_side_buckets(self):
        summary = json.loads((SCHEMA_ROOT / "golden" / "v1" / "resource_summary.json").read_text())
        human = artifacts._human_cli(summary)
        accepted = summary["roster"][0]
        self.assertEqual("5632", accepted["totals"]["f3"]["remote_accepted"]["payload_bytes"])
        self.assertIn("5.5000 KiB", human)

        final = json.loads((SCHEMA_ROOT / "golden" / "v1" / "attempt_final.json").read_text())
        self.assertEqual("256", final["f3"]["local_delivered"]["payload_bytes"])
        self.assertEqual("512", final["f3"]["late_after_cutoff"]["payload_bytes"])
        self.assertEqual("1024", final["f3"]["summary_excluded"]["payload_bytes"])
        self.assertNotIn("local_delivered", accepted["totals"]["f3"])
        self.assertNotIn("late_after_cutoff", accepted["totals"]["f3"])
        self.assertNotIn("summary_excluded", accepted["totals"]["f3"])


if __name__ == "__main__":
    unittest.main()
