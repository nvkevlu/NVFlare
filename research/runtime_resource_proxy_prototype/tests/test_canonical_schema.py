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
import json
import sys
import unittest
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schema"
sys.path.insert(0, str(SCHEMA_ROOT))

from contract_v1 import (  # noqa: E402
    ISSUE_CODES,
    KIND_PARTICIPANT_SUMMARY,
    KIND_RESOURCE_SUMMARY,
    KIND_STUDY_SUMMARY,
    MAX_RECORD_BYTES,
    MAX_STUDY_JOBS,
    RECORD_KINDS,
    SCHEMA_VERSION,
    U128_MAX,
    ContractError,
    derive_job_totals,
    derive_participant_totals,
    derive_study_totals,
    load_and_validate,
    normalize_quota_units,
    validate_bundle,
    validate_record,
)

JOB_ID = "job-20260909-001"
NAME_A = "site-a"
NAME_B = "site-b"


def _json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()


def _counter(payload="1000", messages="10"):
    return {"payload_bytes": payload, "messages": messages}


def _resource_time(
    *,
    seconds="120",
    cpu_seconds="3840",
    memory_seconds="24739011624960",
    gpu_seconds="480",
    cpu_model="AMD EPYC 9654",
    gpu_model="NVIDIA A100 80GB",
):
    return {
        "status": "reported",
        "measured_seconds": seconds,
        "cpu": {
            "groups": [
                {
                    "unit_seconds": cpu_seconds,
                    "model": cpu_model,
                    "architecture": "x86_64",
                }
            ]
        },
        "memory": {"byte_seconds": memory_seconds},
        "gpu": {
            "groups": [
                {
                    "kind": "full_gpu",
                    "instance_seconds": gpu_seconds,
                    "model": gpu_model,
                    "memory_bytes": "85899345920",
                }
            ]
        },
    }


def _participant(name=NAME_A, *, resource_time=None):
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND_PARTICIPANT_SUMMARY,
        "job_id": JOB_ID,
        "participant_name": name,
        "reported_at": "2026-09-09T14:37:03Z",
        "resource_time": resource_time or _resource_time(),
        "workspace_filesystem": {"status": "reported", "capacity_bytes": "1099511627776"},
        "retained_content": {"status": "reported", "bytes": "29540266113"},
        "f3": {
            "status": "reported",
            "remote_accepted": _counter("147700336640", "23500"),
            "local_delivered": _counter("65536", "12"),
            "remote_failed_before_acceptance": _counter("0", "0"),
        },
    }


def _accepted(record, participant_name, role="client"):
    return {
        "participant_name": participant_name,
        "role": role,
        "status": "accepted",
        "received_at": "2026-09-09T14:38:00Z",
        **derive_participant_totals(record),
    }


def _summary(participants):
    participants = sorted(
        participants,
        key=lambda item: (item["role"], item["participant_name"]),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND_RESOURCE_SUMMARY,
        "job_id": JOB_ID,
        "report_cutoff_at": "2026-09-09T14:40:00Z",
        "finalized_at": "2026-09-09T14:40:00.1Z",
        "participants": participants,
        "totals": derive_job_totals(participants),
    }


class TestCanonicalFinalOnlyV1Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads((SCHEMA_ROOT / "resource_stats_v1.schema.json").read_text())
        cls.json_validator = Draft202012Validator(cls.schema) if Draft202012Validator else None

    def _assert_invalid(self, value, pattern=None):
        context = self.assertRaisesRegex(ContractError, pattern) if pattern else self.assertRaises(ContractError)
        with context:
            validate_record(value)

    def _assert_invalid_both(self, value):
        self._assert_invalid(value)
        if self.json_validator:
            self.assertTrue(list(self.json_validator.iter_errors(value)))

    def test_only_three_final_or_derived_record_kinds_remain(self):
        self.assertEqual(
            {
                KIND_PARTICIPANT_SUMMARY,
                KIND_RESOURCE_SUMMARY,
                KIND_STUDY_SUMMARY,
            },
            RECORD_KINDS,
        )
        self.assertFalse(
            {
                "attempt_start",
                "attempt_final",
                "attempt_end",
                "participant_start_record",
                "participant_final_record",
                "participant_attempt",
            }
            & set(self.schema["$defs"])
        )
        old = {
            "schema_version": SCHEMA_VERSION,
            "kind": "nvflare.resource_stats.attempt_start",
        }
        self._assert_invalid(old)

    def test_participant_limit_is_small_while_server_local_limits_are_unchanged(self):
        self.assertEqual(1 * 1024 * 1024, MAX_RECORD_BYTES[KIND_PARTICIPANT_SUMMARY])
        self.assertEqual(64 * 1024 * 1024, MAX_RECORD_BYTES[KIND_RESOURCE_SUMMARY])
        self.assertEqual(64 * 1024 * 1024, MAX_RECORD_BYTES[KIND_STUDY_SUMMARY])

    def test_participant_is_one_terminal_report_with_exact_fields(self):
        participant = _participant()
        validate_record(participant)
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
        self.assertFalse({"start", "final", "attempts", "attempt_id", "environment_key"} & set(participant))

        old_field = copy.deepcopy(participant)
        old_field["attempts"] = []
        self._assert_invalid_both(old_field)

    def test_resource_time_uses_one_status_for_all_three_resources(self):
        participant = _participant()
        validate_record(participant)
        self.assertEqual("reported", participant["resource_time"]["status"])
        self.assertFalse(any("status" in participant["resource_time"][name] for name in ("cpu", "memory", "gpu")))

        per_resource_status = copy.deepcopy(participant)
        per_resource_status["resource_time"]["cpu"]["status"] = "reported"
        self._assert_invalid_both(per_resource_status)

        error = copy.deepcopy(participant)
        error["resource_time"] = {"status": "error", "issues": ["malformed_source"]}
        self._assert_invalid_both(error)

    def test_partial_requires_generic_issues_and_one_numeric_member(self):
        participant = _participant(
            resource_time={
                "status": "partial",
                "issues": ["observation_incomplete"],
                "measured_seconds": "120",
                "gpu": {"groups": []},
            }
        )
        validate_record(participant)
        self.assertEqual([], participant["resource_time"]["gpu"]["groups"])

        no_numeric = copy.deepcopy(participant)
        no_numeric["resource_time"].pop("measured_seconds")
        no_numeric["resource_time"].pop("gpu")
        self._assert_invalid_both(no_numeric)

        specialized_issue = copy.deepcopy(participant)
        specialized_issue["resource_time"]["issues"] = ["gpu_observation_missing"]
        self._assert_invalid_both(specialized_issue)

    def test_unavailable_has_issues_and_no_numeric_values(self):
        participant = _participant(resource_time={"status": "unavailable", "issues": ["dependency_missing"]})
        validate_record(participant)

        with_numeric = copy.deepcopy(participant)
        with_numeric["resource_time"]["measured_seconds"] = "120"
        self._assert_invalid_both(with_numeric)

        without_issue = copy.deepcopy(participant)
        without_issue["resource_time"].pop("issues")
        self._assert_invalid_both(without_issue)

    def test_gpu_zero_is_empty_groups_and_stored_groups_are_positive(self):
        zero = _participant()
        zero["resource_time"]["gpu"] = {"groups": []}
        validate_record(zero)

        zero_group = _participant()
        zero_group["resource_time"]["gpu"]["groups"][0]["instance_seconds"] = "0"
        self._assert_invalid_both(zero_group)

        raw_mask = _participant()
        raw_mask["resource_time"]["gpu"]["cuda_visible_devices"] = "0,1"
        self._assert_invalid_both(raw_mask)

    def test_models_are_optional_normalized_metadata(self):
        participant = _participant()
        participant["resource_time"]["cpu"]["groups"][0].pop("model")
        participant["resource_time"]["gpu"]["groups"][0].pop("model")
        validate_record(participant)

        identifying = _participant()
        identifying["resource_time"]["gpu"]["groups"][0]["model"] = "GPU-12345678-1234-1234-1234-123456789abc"
        self._assert_invalid(identifying, "must not contain")

        raw_cpu = _participant()
        raw_cpu["resource_time"]["cpu"]["groups"][0]["raw_cpuinfo"] = "processor: 0"
        self._assert_invalid_both(raw_cpu)

    def test_participant_derivation_is_an_exact_deep_copy_not_interval_math(self):
        participant = _participant()
        copied = derive_participant_totals(participant)
        self.assertEqual(
            {"resource_time", "retained_content", "f3"},
            set(copied),
        )
        self.assertEqual(participant["resource_time"], copied["resource_time"])
        copied["resource_time"]["measured_seconds"] = "1"
        self.assertEqual("120", participant["resource_time"]["measured_seconds"])

    def test_job_totals_sum_final_values_and_keep_hardware_groups(self):
        first = _participant(NAME_A)
        second = _participant(
            NAME_B,
            resource_time=_resource_time(
                seconds="60",
                cpu_seconds="480",
                memory_seconds="8246337208320",
                gpu_seconds="60",
                cpu_model="Intel Xeon Platinum 8480CL",
                gpu_model="NVIDIA H100 80GB HBM3",
            ),
        )
        participants = [_accepted(first, "site-a"), _accepted(second, "site-b")]
        totals = derive_job_totals(participants)
        self.assertEqual("reported", totals["resource_time"]["status"])
        self.assertEqual("180", totals["resource_time"]["measured_seconds"])
        self.assertEqual("32985348833280", totals["resource_time"]["memory"]["byte_seconds"])
        self.assertEqual(2, len(totals["resource_time"]["cpu"]["groups"]))
        self.assertEqual(2, len(totals["resource_time"]["gpu"]["groups"]))
        self.assertEqual("59080532226", totals["retained_content"]["bytes"])
        self.assertEqual("295400673280", totals["f3"]["remote_accepted"]["payload_bytes"])

    def test_missing_expected_report_makes_numeric_totals_partial(self):
        first = _participant()
        participants = [
            _accepted(first, "site-a"),
            {
                "participant_name": NAME_B,
                "role": "client",
                "status": "missing",
            },
        ]
        totals = derive_job_totals(participants)
        self.assertEqual("partial", totals["resource_time"]["status"])
        self.assertEqual(["observation_incomplete"], totals["resource_time"]["issues"])
        self.assertEqual("partial", totals["retained_content"]["status"])
        self.assertEqual("partial", totals["f3"]["status"])

    def test_resource_summary_requires_exact_derived_totals_and_cutoff(self):
        summary = _summary([_accepted(_participant(), "site-a")])
        validate_record(summary)

        wrong = copy.deepcopy(summary)
        wrong["totals"]["resource_time"]["memory"]["byte_seconds"] = "1"
        self._assert_invalid(wrong, "deterministic sum")

        late = copy.deepcopy(summary)
        late["participants"][0]["received_at"] = "2026-09-09T14:40:01Z"
        self._assert_invalid(late, "report_cutoff_at")

    def test_invalid_participant_is_only_a_malformed_report(self):
        invalid_entry = {
            "participant_name": "site-invalid",
            "role": "client",
            "status": "invalid",
            "received_at": "2026-09-09T14:38:00Z",
            "issues": ["malformed_source"],
        }
        valid_summary = _summary([invalid_entry])
        validate_record(valid_summary)

        permission_denied = copy.deepcopy(valid_summary)
        permission_denied["participants"][0]["issues"] = ["permission_denied"]
        self._assert_invalid_both(permission_denied)

    def test_study_summary_distinguishes_job_status_from_resource_data(self):
        job_totals = _summary([_accepted(_participant(), "site-a")])["totals"]
        jobs = [
            {
                "job_id": "job-a",
                "job_status": "FINISHED:COMPLETED",
                "resource_data": "included",
                "totals": job_totals,
            },
            {"job_id": "job-b", "job_status": "FINISHED:FAILED", "resource_data": "unavailable"},
            {"job_id": "job-c", "job_status": "RUNNING", "resource_data": "nonterminal"},
        ]
        study = {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND_STUDY_SUMMARY,
            "selection": {"study_name": "llm-study-2026"},
            "generated_at": "2026-09-09T15:00:00Z",
            "coverage": {
                "selected_jobs": "3",
                "included_jobs": "1",
                "unavailable_jobs": "1",
                "nonterminal_jobs": "1",
            },
            "jobs": jobs,
            "totals": derive_study_totals(jobs),
        }
        validate_record(study)
        self.assertEqual("partial", study["totals"]["resource_time"]["status"])
        self.assertEqual("partial", study["totals"]["retained_content"]["status"])
        self.assertNotEqual(jobs[0]["job_status"], jobs[0]["resource_data"])

        totals_on_excluded = copy.deepcopy(study)
        totals_on_excluded["jobs"][1]["totals"] = job_totals
        self._assert_invalid_both(totals_on_excluded)

        included_while_running = copy.deepcopy(study)
        included_while_running["jobs"][0]["job_status"] = "RUNNING"
        self._assert_invalid_both(included_while_running)

        terminal_marked_nonterminal = copy.deepcopy(study)
        terminal_marked_nonterminal["jobs"][2]["job_status"] = "FINISHED:COMPLETED"
        self._assert_invalid_both(terminal_marked_nonterminal)

    def test_study_selection_coverage_order_and_bounds_are_closed(self):
        empty = {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND_STUDY_SUMMARY,
            "selection": {"study_name": "study-1"},
            "generated_at": "2026-09-09T15:00:00Z",
            "coverage": {
                "selected_jobs": "0",
                "included_jobs": "0",
                "unavailable_jobs": "0",
                "nonterminal_jobs": "0",
            },
            "jobs": [],
            "totals": derive_study_totals([]),
        }
        validate_record(empty)
        self.assertEqual("unavailable", empty["totals"]["resource_time"]["status"])
        self.assertEqual(10_000, MAX_STUDY_JOBS)

        bad_name = copy.deepcopy(empty)
        bad_name["selection"]["study_name"] = "Uppercase Study"
        self._assert_invalid_both(bad_name)

        for valid_name in ("a", "study_1-final", "a" * 63):
            with self.subTest(valid_name=valid_name):
                valid = copy.deepcopy(empty)
                valid["selection"]["study_name"] = valid_name
                validate_record(valid)

        for invalid_name in ("study.name", "study-", "_study", "a" * 64):
            with self.subTest(invalid_name=invalid_name):
                invalid = copy.deepcopy(empty)
                invalid["selection"]["study_name"] = invalid_name
                self._assert_invalid_both(invalid)

        wrong_coverage = copy.deepcopy(empty)
        wrong_coverage["coverage"]["selected_jobs"] = "1"
        self._assert_invalid(wrong_coverage, "must equal 0")

    def test_study_terminal_classification_reuses_current_cli_predicate(self):
        job_totals = _summary([_accepted(_participant(), "site-a")])["totals"]
        terminal_states = (
            "FINISHED:COMPLETED",
            "FINISHED:",
            "FINISHED_OK",
            "FINISHED_EXCEPTION",
            "ABORTED",
            "ABANDONED",
            "FAILED",
        )
        for index, job_status in enumerate(terminal_states):
            with self.subTest(job_status=job_status):
                included = {
                    "job_id": f"job-{index}",
                    "job_status": job_status,
                    "resource_data": "included",
                    "totals": job_totals,
                }
                derive_study_totals([included])

                unavailable = {
                    "job_id": f"job-{index}",
                    "job_status": job_status,
                    "resource_data": "unavailable",
                }
                derive_study_totals([unavailable])

                nonterminal = dict(unavailable, resource_data="nonterminal")
                with self.assertRaisesRegex(ContractError, "must not be a terminal"):
                    derive_study_totals([nonterminal])

        running_included = {
            "job_id": "job-running",
            "job_status": "RUNNING",
            "resource_data": "included",
            "totals": job_totals,
        }
        with self.assertRaisesRegex(ContractError, "must be a terminal"):
            derive_study_totals([running_included])

        # FINISHED without the current CLI's colon is not terminal.
        derive_study_totals([{"job_id": "job-finished", "job_status": "FINISHED", "resource_data": "nonterminal"}])

    def test_bundle_checks_exact_inventory_bytes_and_copied_values(self):
        participant = _participant()
        participant_data = _json_bytes(participant)
        summary = _summary([_accepted(participant, "site-a")])
        summary_data = _json_bytes(summary)
        files = {
            f"participants/{NAME_A}.json": participant_data,
            "resource_summary.json": summary_data,
        }
        validate_bundle(summary, {NAME_A: participant}, files)

        changed = copy.deepcopy(summary)
        changed["participants"][0]["resource_time"]["measured_seconds"] = "1"
        changed["totals"] = derive_job_totals(changed["participants"])
        with self.assertRaisesRegex(ContractError, "does not equal the exact decoded"):
            validate_bundle(changed, {NAME_A: participant}, files)

        with self.assertRaisesRegex(ContractError, "exactly match"):
            validate_bundle(summary, {NAME_A: participant}, {**files, "participants/site-b.json": b"{}\n"})

    def test_issue_allowlist_is_compact_and_sorted(self):
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
        unsorted = _participant(
            resource_time={
                "status": "partial",
                "issues": ["observation_incomplete", "attribution_incomplete"],
                "measured_seconds": "1",
            }
        )
        self._assert_invalid(unsorted, "sorted and unique")

    def test_strict_loader_rejects_duplicate_keys_and_nonfinite_numbers(self):
        with self.assertRaisesRegex(ContractError, "duplicate JSON object key"):
            load_and_validate(b'{"kind":"x","kind":"y"}')
        with self.assertRaisesRegex(ContractError, "non-finite"):
            load_and_validate(b'{"kind":NaN}')
        with self.assertRaisesRegex(ContractError, "valid UTF-8"):
            load_and_validate(b"\xff")

    def test_deep_nesting_is_always_a_contract_error(self):
        serialized = (
            b'{"kind":"nvflare.resource_stats.participant_summary","nested":'
            + b"[" * 1_100
            + b"0"
            + b"]" * 1_100
            + b"}"
        )
        with self.assertRaisesRegex(ContractError, "depth|nesting"):
            load_and_validate(serialized)

        nested = 0
        for _ in range(1_100):
            nested = [nested]
        decoded = _participant()
        decoded["nested"] = nested
        with self.assertRaisesRegex(ContractError, "depth"):
            validate_record(decoded)

    def test_canonical_numbers_and_aggregate_overflow_are_bounded(self):
        bad = _participant()
        bad["resource_time"]["measured_seconds"] = "01"
        self._assert_invalid_both(bad)

        near_limit_a = _participant(NAME_A)
        near_limit_b = _participant(NAME_B)
        near_limit_a["resource_time"]["memory"]["byte_seconds"] = str(U128_MAX - 10**30)
        near_limit_b["resource_time"]["memory"]["byte_seconds"] = str(10**30)
        valid_totals = derive_job_totals([_accepted(near_limit_a, "a"), _accepted(near_limit_b, "b")])
        self.assertEqual(
            str(U128_MAX),
            valid_totals["resource_time"]["memory"]["byte_seconds"],
        )

        huge_a = _participant(NAME_A)
        huge_b = _participant(NAME_B)
        huge_a["resource_time"]["memory"]["byte_seconds"] = str(U128_MAX)
        huge_b["resource_time"]["memory"]["byte_seconds"] = "1"
        with self.assertRaisesRegex(ContractError, "aggregate exceeds"):
            derive_job_totals([_accepted(huge_a, "a"), _accepted(huge_b, "b")])

    def test_quota_normalization_remains_an_exact_collector_helper(self):
        self.assertEqual("1.5", normalize_quota_units(150_000, 100_000))
        self.assertEqual("0.333333333", normalize_quota_units(1, 3))
        with self.assertRaisesRegex(ValueError, "positive unsigned"):
            normalize_quota_units(0, 100_000)

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
    def test_schema_accepts_each_new_record_kind(self):
        Draft202012Validator.check_schema(self.schema)
        participant = _participant()
        summary = _summary([_accepted(participant, "site-a")])
        jobs = [
            {
                "job_id": JOB_ID,
                "job_status": "FINISHED:COMPLETED",
                "resource_data": "included",
                "totals": summary["totals"],
            }
        ]
        study = {
            "schema_version": SCHEMA_VERSION,
            "kind": KIND_STUDY_SUMMARY,
            "selection": {"study_name": "study-1"},
            "generated_at": "2026-09-09T15:00:00Z",
            "coverage": {
                "selected_jobs": "1",
                "included_jobs": "1",
                "unavailable_jobs": "0",
                "nonterminal_jobs": "0",
            },
            "jobs": jobs,
            "totals": derive_study_totals(jobs),
        }
        for record in (participant, summary, study):
            with self.subTest(kind=record["kind"]):
                self.assertEqual([], list(self.json_validator.iter_errors(record)))


if __name__ == "__main__":
    unittest.main()
