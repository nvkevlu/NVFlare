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

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:  # The executable contract intentionally has no third-party dependency.
    Draft202012Validator = None


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schema"
GOLDEN_ROOT = SCHEMA_ROOT / "golden" / "v1"
sys.path.insert(0, str(SCHEMA_ROOT))

from contract_v1 import (  # noqa: E402
    ISSUE_CODES,
    KIND_MANIFEST,
    KIND_PARTICIPANT_SUMMARY,
    KIND_RESOURCE_SUMMARY,
    RECORD_KINDS,
    SCHEMA_VERSION,
    U128_MAX,
    ContractError,
    derive_job_totals,
    derive_participant_totals,
    load_and_validate,
    validate_bundle,
    validate_record,
)


def _json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


class TestCanonicalV1Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads((SCHEMA_ROOT / "resource_stats_v1.schema.json").read_text())
        cls.json_validator = Draft202012Validator(cls.schema) if Draft202012Validator else None

    def _golden(self, name):
        return json.loads((GOLDEN_ROOT / name).read_text(encoding="utf-8"))

    def _assert_invalid(self, value, pattern=None):
        context = self.assertRaisesRegex(ContractError, pattern) if pattern else self.assertRaises(ContractError)
        with context:
            validate_record(value)

    def _assert_invalid_both(self, value):
        self._assert_invalid(value)
        if self.json_validator:
            self.assertTrue(list(self.json_validator.iter_errors(value)))

    def _bundle(self, participants):
        participant_records = {}
        participant_files = {}
        roster = []
        for index, participant in enumerate(participants, start=1):
            key = participant["participant_key"]
            data = _json_bytes(participant)
            participant_records[key] = participant
            participant_files[f"participants/{key}.json"] = data
            observation_seconds, totals = derive_participant_totals(participant)
            roster.append(
                {
                    "participant_id": f"site-{index}",
                    "participant_key": key,
                    "role": "client",
                    "status": "accepted",
                    "received_at": "2026-09-09T14:20:00Z",
                    "summary_sha256": hashlib.sha256(data).hexdigest(),
                    "observation_seconds": observation_seconds,
                    "totals": totals,
                }
            )
        roster.sort(key=lambda item: (item["role"], item["participant_id"], item["participant_key"]))
        summary = {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND_RESOURCE_SUMMARY,
            "job_id": participants[0]["job_id"],
            "report_cutoff_at": "2026-09-09T14:21:00Z",
            "finalized_at": "2026-09-09T14:21:00.1Z",
            "roster": roster,
            "totals": derive_job_totals(roster),
        }
        summary_bytes = _json_bytes(summary)
        files = {**participant_files, "resource_summary.json": summary_bytes}
        entries = [
            {"relative_path": path, "sha256": hashlib.sha256(data).hexdigest()} for path, data in sorted(files.items())
        ]
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND_MANIFEST,
            "job_id": summary["job_id"],
            "entries": entries,
        }
        return summary, participant_records, manifest, files

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
    def test_all_six_record_kinds_pass_executable_and_draft_2020_12_schema(self):
        Draft202012Validator.check_schema(self.schema)
        seen = set()
        for path in sorted(GOLDEN_ROOT.glob("*.json")):
            with self.subTest(name=path.name):
                record = load_and_validate(path.read_bytes())
                errors = sorted(self.json_validator.iter_errors(record), key=lambda error: list(error.path))
                self.assertEqual([], errors)
                seen.add(record["kind"])
        self.assertEqual(RECORD_KINDS, seen)
        self.assertEqual("1.0", SCHEMA_VERSION)

    def test_cpu_selector_uses_minimum_and_online_is_fallback_only(self):
        record = self._golden("attempt_start.json")
        cpu = record["capacity"]["cpu"]
        self.assertEqual("1.5", cpu["visible_units"])
        self.assertEqual(
            {"affinity_count": "4", "cpuset_count": "4", "quota_units": "1.5"},
            cpu["evidence"],
        )
        self.assertNotIn("quota_us", cpu["evidence"])
        self.assertNotIn("period_us", cpu["evidence"])

        wrong_minimum = copy.deepcopy(record)
        wrong_minimum["capacity"]["cpu"]["visible_units"] = "4"
        self._assert_invalid(wrong_minimum, "minimum applicable CPU evidence")

        mixed_fallback = copy.deepcopy(record)
        mixed_fallback["capacity"]["cpu"]["evidence"]["online_count"] = "16"
        self._assert_invalid(mixed_fallback, "must be omitted")

        fallback = self._golden("participant_summary_large_value.json")["attempts"][0]["start"]
        self.assertEqual({"online_count": "1"}, fallback["capacity"]["cpu"]["evidence"])
        validate_record(self._golden("participant_summary_large_value.json"))

    def test_cuda_mask_is_diagnostic_and_zero_requires_reported_enumeration(self):
        unavailable = self._golden("attempt_start_cuda_unavailable.json")
        gpu = unavailable["capacity"]["gpu"]
        self.assertTrue(gpu["cuda_mask_present"])
        self.assertEqual("unavailable", gpu["status"])
        self.assertNotIn("groups", gpu)

        invented_count = copy.deepcopy(unavailable)
        invented_count["capacity"]["gpu"]["groups"] = [{"kind": "full_gpu", "count": "1"}]
        self._assert_invalid_both(invented_count)

        zero = self._golden("attempt_start_zero_gpu.json")["capacity"]["gpu"]
        self.assertEqual("reported", zero["status"])
        self.assertEqual([], zero["groups"])
        self.assertFalse(any(group["kind"] == "mig_compute_instance" for group in zero["groups"]))

        raw_mask = self._golden("attempt_start.json")
        raw_mask["capacity"]["gpu"]["cuda_visible_devices"] = "0,1"
        self._assert_invalid_both(raw_mask)

    def test_status_issue_allowlists_and_total_statuses_are_compact(self):
        unavailable = self._golden("attempt_start_cuda_unavailable.json")
        missing_issue = copy.deepcopy(unavailable)
        missing_issue["capacity"]["gpu"].pop("issues")
        self._assert_invalid_both(missing_issue)

        unknown_issue = copy.deepcopy(unavailable)
        unknown_issue["capacity"]["gpu"]["issues"] = ["cuda_failed"]
        self._assert_invalid_both(unknown_issue)
        self.assertEqual(
            {
                "not_bound",
                "counter_gap",
                "observation_incomplete",
                "attribution_incomplete",
                "unsupported",
                "permission_denied",
                "dependency_missing",
                "malformed_source",
            },
            ISSUE_CODES,
        )

        partial_f3 = self._golden("attempt_final.json")
        partial_f3["f3"]["status"] = "partial"
        partial_f3["f3"]["issues"] = ["counter_gap"]
        validate_record(partial_f3)

        reported_with_issue = self._golden("attempt_final.json")
        reported_with_issue["f3"]["issues"] = ["counter_gap"]
        self._assert_invalid_both(reported_with_issue)

        summary = self._golden("resource_summary.json")
        self.assertFalse(any("issues" in total for total in summary["totals"].values()))
        total_issue = copy.deepcopy(summary)
        total_issue["totals"]["cpu"]["issues"] = ["attribution_incomplete"]
        self._assert_invalid_both(total_issue)

    def test_models_are_optional_normalized_metadata(self):
        record = self._golden("attempt_start.json")
        self.assertEqual("AMD EPYC 9654", record["capacity"]["cpu"]["model"])
        self.assertEqual("NVIDIA H100 80GB HBM3", record["capacity"]["gpu"]["groups"][0]["model"])

        heterogeneous = copy.deepcopy(record)
        heterogeneous["capacity"]["cpu"].pop("model")
        validate_record(heterogeneous)
        self.assertEqual("reported", heterogeneous["capacity"]["cpu"]["status"])

        suppressed = copy.deepcopy(heterogeneous)
        suppressed["capacity"]["gpu"]["groups"][0].pop("model")
        validate_record(suppressed)

        identifying_model = copy.deepcopy(record)
        identifying_model["capacity"]["gpu"]["groups"][0]["model"] = "GPU-12345678-1234-1234-1234-123456789abc"
        self._assert_invalid(identifying_model, "must not contain")

        raw_cpu = copy.deepcopy(record)
        raw_cpu["capacity"]["cpu"]["raw_cpuinfo"] = "processor: 0"
        self._assert_invalid_both(raw_cpu)

    def test_final_capacity_is_retained_and_crash_derivation_is_honest(self):
        participant = self._golden("participant_summary.json")
        observation, totals = derive_participant_totals(participant)
        self.assertEqual("342.5", observation)
        self.assertEqual("reported", totals["cpu"]["status"])
        self.assertIn("capacity", participant["attempts"][0]["final"])

        changed = copy.deepcopy(participant)
        changed_cpu = changed["attempts"][0]["final"]["capacity"]["cpu"]
        changed_cpu["visible_units"] = "1"
        changed_cpu["evidence"]["quota_units"] = "1"
        _, changed_totals = derive_participant_totals(changed)
        self.assertEqual("partial", changed_totals["cpu"]["status"])
        self.assertEqual("513.75", changed_totals["cpu"]["groups"][0]["unit_seconds"])
        self.assertEqual("reported", changed_totals["memory"]["status"])

        crash = copy.deepcopy(participant)
        crash_attempt = crash["attempts"][0]
        crash_attempt.pop("final")
        crash_attempt["exit"] = {
            "observed_at": "2026-09-09T14:05:42.6Z",
            "outcome": "terminated",
            "return_code": -9,
        }
        crash_observation, crash_totals = derive_participant_totals(crash)
        self.assertEqual("342.6", crash_observation)
        self.assertEqual("partial", crash_totals["cpu"]["status"])
        self.assertEqual("513.9", crash_totals["cpu"]["groups"][0]["unit_seconds"])
        self.assertEqual({"status": "unavailable"}, crash_totals["retained_content"])
        self.assertEqual({"status": "unavailable"}, crash_totals["f3"])
        self.assertNotIn("capacity", self._golden("parent_exit_crash.json"))

    def test_large_integer_formula_is_exact_and_bounded(self):
        participant = self._golden("participant_summary_large_value.json")
        observation, totals = derive_participant_totals(participant)
        self.assertEqual("901", observation)
        self.assertEqual("9010000000000901", totals["storage"]["byte_seconds"])
        self.assertEqual(totals, self._golden("resource_summary_large_value.json")["totals"])

        maximum = self._golden("attempt_final_large_value.json")
        maximum["f3"]["summary_excluded"] = {"payload_bytes": str(U128_MAX), "messages": "1"}
        validate_record(maximum)
        overflow = copy.deepcopy(maximum)
        overflow["f3"]["summary_excluded"]["payload_bytes"] = str(U128_MAX + 1)
        self._assert_invalid(overflow, "no greater")

    def test_roster_recomputes_job_totals_and_role_occurs_only_there(self):
        summary = self._golden("resource_summary.json")
        self.assertEqual(summary["totals"], derive_job_totals(summary["roster"]))
        self.assertEqual(["client", "server"], [entry["role"] for entry in summary["roster"]])
        self.assertTrue(all(total["status"] == "partial" for total in summary["totals"].values()))

        changed = copy.deepcopy(summary)
        changed["totals"]["memory"]["byte_seconds"] = "1"
        self._assert_invalid(changed, "deterministic sum")

        participant = self._golden("participant_summary.json")
        self.assertNotIn("role", participant)
        with_role = copy.deepcopy(participant)
        with_role["role"] = "client"
        self._assert_invalid_both(with_role)

    def test_summary_bytes_are_idempotent_and_conflicts_fail_digest_checks(self):
        participant_path = GOLDEN_ROOT / "participant_summary.json"
        summary_path = GOLDEN_ROOT / "resource_summary.json"
        participant_bytes = participant_path.read_bytes()
        summary_bytes = summary_path.read_bytes()
        participant = json.loads(participant_bytes)
        summary = json.loads(summary_bytes)
        manifest = self._golden("manifest.json")
        key = participant["participant_key"]
        files = {
            f"participants/{key}.json": participant_bytes,
            "resource_summary.json": summary_bytes,
        }
        validate_bundle(summary, {key: participant}, manifest, files)
        self.assertNotIn("summary_id", participant)
        self.assertNotIn("summary_revision", participant)
        digest = hashlib.sha256(participant_bytes).digest()
        self.assertEqual(digest, hashlib.sha256(participant_bytes).digest())

        conflict = copy.deepcopy(participant)
        conflict["attempts"][0]["start"]["capacity"]["cpu"].pop("model")
        conflict_bytes = _json_bytes(conflict)
        self.assertNotEqual(digest, hashlib.sha256(conflict_bytes).digest())
        conflict_files = dict(files)
        conflict_files[f"participants/{key}.json"] = conflict_bytes
        with self.assertRaisesRegex(ContractError, "does not match archived bytes"):
            validate_bundle(summary, {key: conflict}, manifest, conflict_files)

    def test_bundle_rejects_cross_participant_environment_overlap_but_allows_retry_boundary(self):
        first = self._golden("participant_summary.json")
        second = copy.deepcopy(first)
        second["participant_key"] = "sha256-" + "e" * 64
        attempt = second["attempts"][0]
        attempt["attempt_id"] = "2" * 32
        attempt["start"]["observed_at"] = "2026-09-09T14:05:42.6Z"
        attempt["final"]["observed_at"] = "2026-09-09T14:10:00Z"
        attempt["exit"] = {
            "observed_at": "2026-09-09T14:10:00.1Z",
            "outcome": "finished_ok",
            "return_code": 0,
        }
        validate_bundle(*self._bundle([first, second]))

        overlapping = copy.deepcopy(second)
        overlapping["attempts"][0]["start"]["observed_at"] = "2026-09-09T14:05:42.5Z"
        with self.assertRaisesRegex(ContractError, "overlapping trusted reporters"):
            validate_bundle(*self._bundle([first, overlapping]))

    def test_f3_bucket_semantics_and_cutoff_are_closed(self):
        final = self._golden("attempt_final.json")
        self.assertEqual(
            {
                "remote_accepted",
                "local_delivered",
                "remote_failed_before_acceptance",
                "late_after_cutoff",
                "summary_excluded",
            },
            set(final["f3"]) - {"status", "cutoff_sequence"},
        )
        self.assertEqual("5632", final["f3"]["remote_accepted"]["payload_bytes"])

        impossible_counter = copy.deepcopy(final)
        impossible_counter["f3"]["remote_failed_before_acceptance"] = {
            "payload_bytes": "1",
            "messages": "0",
        }
        self._assert_invalid(impossible_counter, "payload_bytes must be zero")

        impossible_cutoff = copy.deepcopy(final)
        impossible_cutoff["f3"]["cutoff_sequence"] = "0"
        self._assert_invalid(impossible_cutoff, "must be zero when cutoff_sequence is zero")

    def test_unknown_fields_and_nulls_are_rejected(self):
        unknown = self._golden("attempt_start.json")
        unknown["capacity"]["storage"]["available_bytes"] = "1"
        self._assert_invalid_both(unknown)

        null_value = self._golden("attempt_start.json")
        null_value["capacity"]["cpu"]["model"] = None
        self._assert_invalid_both(null_value)


if __name__ == "__main__":
    unittest.main()
