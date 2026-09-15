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
    MAX_ATTEMPTS,
    RECORD_KINDS,
    SCHEMA_VERSION,
    U128_MAX,
    ContractError,
    derive_job_totals,
    derive_participant_totals,
    load_and_validate,
    normalize_quota_units,
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
            resource_window_seconds, totals = derive_participant_totals(participant)
            roster.append(
                {
                    "participant_id": f"site-{index}",
                    "participant_key": key,
                    "role": "client",
                    "status": "accepted",
                    "received_at": "2026-09-09T14:20:00Z",
                    "summary_sha256": hashlib.sha256(data).hexdigest(),
                    "resource_window_seconds": resource_window_seconds,
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

    def test_all_eight_record_kinds_pass_executable_contract(self):
        seen = set()
        for path in sorted(GOLDEN_ROOT.glob("*.json")):
            with self.subTest(name=path.name):
                record = load_and_validate(path.read_bytes())
                seen.add(record["kind"])
        self.assertEqual(RECORD_KINDS, seen)
        self.assertEqual("1.0", SCHEMA_VERSION)

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
    def test_all_goldens_pass_draft_2020_12_schema(self):
        Draft202012Validator.check_schema(self.schema)
        for path in sorted(GOLDEN_ROOT.glob("*.json")):
            with self.subTest(name=path.name):
                record = json.loads(path.read_text(encoding="utf-8"))
                errors = sorted(self.json_validator.iter_errors(record), key=lambda error: list(error.path))
                self.assertEqual([], errors)

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

    def test_quota_units_use_exact_decimal_division_and_conservative_floor(self):
        self.assertEqual("1.5", normalize_quota_units(150_000, 100_000))
        self.assertEqual("0.333333333", normalize_quota_units(1, 3))
        self.assertEqual("0.666666666", normalize_quota_units(2, 3))
        with self.assertRaisesRegex(ValueError, "positive unsigned"):
            normalize_quota_units(0, 100_000)
        with self.assertRaisesRegex(ValueError, "below the v1"):
            normalize_quota_units(1, 10_000_000_000)

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

        partial_f3 = self._golden("participant_final.json")
        partial_f3["f3"]["status"] = "partial"
        partial_f3["f3"]["issues"] = ["counter_gap"]
        validate_record(partial_f3)

        reported_with_issue = self._golden("participant_final.json")
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

    def test_gpu_free_window_counts_cpu_memory_and_storage_spans_participant(self):
        participant = self._golden("participant_summary.json")
        window_seconds, totals = derive_participant_totals(participant)
        self.assertEqual("480", window_seconds)
        self.assertEqual("2026-09-09T14:00:00Z", participant["start"]["observed_at"])
        self.assertEqual("2026-09-09T14:08:00Z", participant["final"]["observed_at"])
        self.assertEqual("2026-09-09T14:01:00Z", participant["attempts"][0]["end"]["closed_at"])
        self.assertEqual("2026-09-09T14:01:00Z", participant["attempts"][1]["opened_at"])
        self.assertEqual([], participant["attempts"][1]["start"]["capacity"]["gpu"]["groups"])
        self.assertEqual("720", totals["cpu"]["groups"][0]["unit_seconds"])
        self.assertEqual("4123168604160", totals["memory"]["byte_seconds"])
        self.assertEqual("180", totals["gpu"]["groups"][0]["instance_seconds"])
        self.assertEqual("527765581332480", totals["storage"]["byte_seconds"])
        self.assertEqual("18874368", totals["retained_content"]["bytes"])
        self.assertEqual("5632", totals["f3"]["remote_accepted"]["payload_bytes"])
        self.assertTrue(all("retained_content" not in attempt["final"] for attempt in participant["attempts"]))
        self.assertTrue(all("f3" not in attempt["final"] for attempt in participant["attempts"]))

    def test_gpu_only_release_opens_an_immediate_zero_gpu_window(self):
        participant = self._golden("participant_summary.json")
        environment_key = participant["attempts"][0]["environment_key"]
        with_gpu = copy.deepcopy(participant["attempts"][0]["start"]["capacity"])
        without_gpu = copy.deepcopy(with_gpu)
        without_gpu["gpu"] = {"status": "reported", "cuda_mask_present": False, "groups": []}
        participant["attempts"] = [
            {
                "attempt_id": "1" * 32,
                "environment_key": environment_key,
                "opened_at": "2026-09-09T14:00:00Z",
                "start": {"capacity": copy.deepcopy(with_gpu)},
                "final": {"capacity": copy.deepcopy(with_gpu)},
                "end": {"closed_at": "2026-09-09T14:01:00Z", "reason": "reconfigured"},
            },
            {
                "attempt_id": "2" * 32,
                "environment_key": environment_key,
                "opened_at": "2026-09-09T14:01:00Z",
                "start": {"capacity": copy.deepcopy(without_gpu)},
                "final": {"capacity": copy.deepcopy(without_gpu)},
                "end": {"closed_at": "2026-09-09T14:06:00Z", "reason": "released"},
            },
        ]

        window_seconds, totals = derive_participant_totals(participant)
        self.assertEqual("360", window_seconds)
        self.assertEqual("540", totals["cpu"]["groups"][0]["unit_seconds"])
        self.assertEqual("3092376453120", totals["memory"]["byte_seconds"])
        self.assertEqual("60", totals["gpu"]["groups"][0]["instance_seconds"])

        gap_after_reconfiguration = copy.deepcopy(participant)
        gap_after_reconfiguration["attempts"][1]["opened_at"] = "2026-09-09T14:01:00.1Z"
        self._assert_invalid(gap_after_reconfiguration, "exact closure boundary")

        release_and_immediate_reacquire = copy.deepcopy(participant)
        release_and_immediate_reacquire["attempts"][0]["end"]["reason"] = "released"
        validate_record(release_and_immediate_reacquire)

        unchanged_reconfiguration = copy.deepcopy(participant)
        unchanged_reconfiguration["attempts"][1]["start"] = copy.deepcopy(
            unchanged_reconfiguration["attempts"][0]["start"]
        )
        self._assert_invalid(unchanged_reconfiguration, "requires a changed numeric capacity vector")

    def test_launch_failed_has_supervisor_bounds_and_no_capacity_snapshot(self):
        participant = self._golden("participant_summary.json")
        participant["attempts"] = [
            {
                "attempt_id": "1" * 32,
                "environment_key": participant["attempts"][0]["environment_key"],
                "opened_at": "2026-09-09T14:00:00Z",
                "end": {"closed_at": "2026-09-09T14:00:10Z", "reason": "launch_failed"},
            }
        ]
        window_seconds, totals = derive_participant_totals(participant)
        self.assertEqual("10", window_seconds)
        self.assertEqual({"status": "unavailable"}, totals["cpu"])
        self.assertEqual({"status": "unavailable"}, totals["memory"])
        self.assertEqual({"status": "unavailable"}, totals["gpu"])

        invented_start = copy.deepcopy(participant)
        invented_start["attempts"][0]["start"] = {
            "capacity": copy.deepcopy(self._golden("attempt_start.json")["capacity"])
        }
        self._assert_invalid_both(invented_start)

        negative_duration = copy.deepcopy(participant)
        negative_duration["attempts"][0]["end"]["closed_at"] = "2026-09-09T13:59:59Z"
        self._assert_invalid(negative_duration, "must not precede opened_at")

        standalone_end = self._golden("attempt_end_terminated.json")
        standalone_end["reason"] = "launch_failed"
        validate_record(standalone_end)
        standalone_end.pop("opened_at")
        self._assert_invalid_both(standalone_end)

    def test_attempt_bound_is_exactly_4096(self):
        participant = self._golden("participant_summary.json")
        environment_key = participant["attempts"][0]["environment_key"]
        participant["attempts"] = [
            {
                "attempt_id": f"{index:032x}",
                "environment_key": environment_key,
                "opened_at": "2026-09-09T14:00:00Z",
                "end": {"closed_at": "2026-09-09T14:00:00Z", "reason": "launch_failed"},
            }
            for index in range(MAX_ATTEMPTS)
        ]
        validate_record(participant)

        participant["attempts"].append(
            {
                "attempt_id": f"{MAX_ATTEMPTS:032x}",
                "environment_key": environment_key,
                "opened_at": "2026-09-09T14:00:00Z",
                "end": {"closed_at": "2026-09-09T14:00:00Z", "reason": "launch_failed"},
            }
        )
        self._assert_invalid_both(participant)

    def test_final_capacity_and_preemption_resume_derivation_are_honest(self):
        participant = self._golden("participant_summary.json")
        _, totals = derive_participant_totals(participant)
        self.assertEqual("reported", totals["cpu"]["status"])
        self.assertIn("capacity", participant["attempts"][0]["final"])

        changed = copy.deepcopy(participant)
        changed_cpu = changed["attempts"][0]["final"]["capacity"]["cpu"]
        changed_cpu["visible_units"] = "1"
        changed_cpu["evidence"]["quota_units"] = "1"
        _, changed_totals = derive_participant_totals(changed)
        self.assertEqual("partial", changed_totals["cpu"]["status"])
        self.assertEqual("720", changed_totals["cpu"]["groups"][0]["unit_seconds"])
        self.assertEqual("reported", changed_totals["memory"]["status"])

        failed_with_final = copy.deepcopy(participant)
        failed_with_final["attempts"][0]["end"]["reason"] = "failed"
        _, failed_with_final_totals = derive_participant_totals(failed_with_final)
        self.assertEqual(totals, failed_with_final_totals)

        resumed = self._golden("participant_summary_preempted_resume.json")
        resumed_seconds, resumed_totals = derive_participant_totals(resumed)
        self.assertEqual("180", resumed_seconds)
        self.assertNotIn("final", resumed["attempts"][0])
        self.assertEqual("terminated", resumed["attempts"][0]["end"]["reason"])
        self.assertEqual("released", resumed["attempts"][1]["end"]["reason"])
        self.assertEqual("partial", resumed_totals["cpu"]["status"])
        self.assertEqual(["90", "240"], [group["unit_seconds"] for group in resumed_totals["cpu"]["groups"]])
        self.assertEqual("partial", resumed_totals["memory"]["status"])
        self.assertEqual("2576980377600", resumed_totals["memory"]["byte_seconds"])
        self.assertEqual("partial", resumed_totals["gpu"]["status"])
        self.assertEqual(
            [("NVIDIA A100 80GB PCIe", "240"), ("NVIDIA H100 80GB HBM3", "60")],
            [(group["model"], group["instance_seconds"]) for group in resumed_totals["gpu"]["groups"]],
        )
        self.assertEqual("reported", resumed_totals["storage"]["status"])
        self.assertEqual("527765581332480", resumed_totals["storage"]["byte_seconds"])
        self.assertEqual("reported", resumed_totals["retained_content"]["status"])
        self.assertEqual("reported", resumed_totals["f3"]["status"])
        attempt_end = self._golden("attempt_end_terminated.json")
        self.assertNotIn("capacity", attempt_end)
        self.assertNotIn("return_code", attempt_end)
        self.assertEqual("2026-09-09T14:00:00Z", attempt_end["opened_at"])
        self.assertEqual("2026-09-09T14:01:00Z", attempt_end["closed_at"])

    def test_completed_participant_with_no_compute_windows_reports_zero_transient_time(self):
        participant = self._golden("participant_summary.json")
        participant["attempts"] = []
        window_seconds, totals = derive_participant_totals(participant)
        self.assertEqual("0", window_seconds)
        self.assertEqual({"status": "reported", "groups": []}, totals["cpu"])
        self.assertEqual({"status": "reported", "byte_seconds": "0"}, totals["memory"])
        self.assertEqual({"status": "reported", "groups": []}, totals["gpu"])
        self.assertEqual("527765581332480", totals["storage"]["byte_seconds"])

    def test_uncertain_continuous_storage_keeps_numeric_proxy_as_partial(self):
        participant = self._golden("participant_summary.json")
        for lifecycle_fact in (participant["start"], participant["final"]):
            lifecycle_fact["storage"] = {
                "status": "partial",
                "capacity_bytes": "1099511627776",
                "issues": ["observation_incomplete"],
            }
        _, totals = derive_participant_totals(participant)
        self.assertEqual(
            {"status": "partial", "byte_seconds": "527765581332480"},
            totals["storage"],
        )

    def test_overlapping_different_environments_sum_resource_window_seconds(self):
        participant = self._golden("participant_summary.json")
        first = copy.deepcopy(participant["attempts"][0])
        second = copy.deepcopy(first)
        first["attempt_id"] = "1" * 32
        first["opened_at"] = "2026-09-09T14:00:00Z"
        first["end"] = {"closed_at": "2026-09-09T14:01:00Z", "reason": "released"}
        second["attempt_id"] = "2" * 32
        second["environment_key"] = "sha256-" + "c" * 64
        second["opened_at"] = "2026-09-09T14:00:00Z"
        second["end"] = {"closed_at": "2026-09-09T14:01:00Z", "reason": "released"}
        participant["attempts"] = [first, second]

        window_seconds, totals = derive_participant_totals(participant)
        self.assertEqual("120", window_seconds)
        self.assertEqual("180", totals["cpu"]["groups"][0]["unit_seconds"])

    def test_large_integer_formula_is_exact_and_bounded(self):
        participant = self._golden("participant_summary_large_value.json")
        window_seconds, totals = derive_participant_totals(participant)
        self.assertEqual("901", window_seconds)
        self.assertEqual("9010000000000901", totals["storage"]["byte_seconds"])
        self.assertEqual(totals, self._golden("resource_summary_large_value.json")["totals"])

        maximum = self._golden("participant_final.json")
        maximum["f3"]["remote_accepted"] = {"payload_bytes": str(U128_MAX), "messages": "1"}
        validate_record(maximum)
        overflow = copy.deepcopy(maximum)
        overflow["f3"]["remote_accepted"]["payload_bytes"] = str(U128_MAX + 1)
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

        accepted_server = copy.deepcopy(summary["roster"][0])
        accepted_server["participant_id"] = "server"
        accepted_server["role"] = "server"
        self.assertEqual(accepted_server["totals"], derive_job_totals([accepted_server]))

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
        second["attempts"] = [second["attempts"][0]]
        attempt = second["attempts"][0]
        attempt["attempt_id"] = "3" * 32
        attempt["opened_at"] = "2026-09-09T14:08:00Z"
        attempt["end"] = {"closed_at": "2026-09-09T14:09:00Z", "reason": "released"}
        second["final"]["observed_at"] = "2026-09-09T14:09:00Z"
        validate_bundle(*self._bundle([first, second]))

        overlapping = copy.deepcopy(second)
        overlapping["attempts"][0]["opened_at"] = "2026-09-09T14:07:59Z"
        with self.assertRaisesRegex(ContractError, "overlapping trusted reporters"):
            validate_bundle(*self._bundle([first, overlapping]))

    def test_f3_bucket_semantics_and_freeze_shape_are_closed(self):
        final = self._golden("participant_final.json")
        self.assertEqual(
            {
                "remote_accepted",
                "local_delivered",
                "remote_failed_before_acceptance",
            },
            set(final["f3"]) - {"status"},
        )
        self.assertEqual("5632", final["f3"]["remote_accepted"]["payload_bytes"])

        impossible_counter = copy.deepcopy(final)
        impossible_counter["f3"]["remote_failed_before_acceptance"] = {
            "payload_bytes": "1",
            "messages": "0",
        }
        self._assert_invalid(impossible_counter, "payload_bytes must be zero")

        exposed_ordinal = copy.deepcopy(final)
        exposed_ordinal["f3"]["cutoff_sequence"] = "5"
        self._assert_invalid_both(exposed_ordinal)

        circular = copy.deepcopy(final)
        circular["f3"]["late_after_cutoff"] = {"payload_bytes": "0", "messages": "0"}
        self._assert_invalid_both(circular)

        summary_traffic = copy.deepcopy(final)
        summary_traffic["f3"]["summary_excluded"] = {"payload_bytes": "0", "messages": "0"}
        self._assert_invalid_both(summary_traffic)

    def test_unknown_fields_and_nulls_are_rejected(self):
        unknown = self._golden("participant_start.json")
        unknown["storage"]["available_bytes"] = "1"
        self._assert_invalid_both(unknown)

        null_value = self._golden("attempt_start.json")
        null_value["capacity"]["cpu"]["model"] = None
        self._assert_invalid_both(null_value)


if __name__ == "__main__":
    unittest.main()
