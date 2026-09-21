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
import threading
import unittest
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from terminal_report_transport import (  # noqa: E402
    MAX_PARTICIPANT_SUMMARY_BYTES,
    RESOURCE_REPORT_ACCEPTED,
    RESOURCE_REPORT_CONFLICT,
    RESOURCE_REPORT_DUPLICATE,
    RESOURCE_REPORT_INVALID,
    RESOURCE_REPORT_NOT_PROVIDED,
    RESOURCE_REPORT_SERVER_ERROR,
    RESOURCE_REPORT_TOO_LATE,
    TERMINAL_OUTCOME_ACCEPTED,
    TERMINAL_OUTCOME_DUPLICATE,
    TERMINAL_OUTCOME_TOO_LATE,
    ExpectedParticipant,
    TerminalReportReceiver,
    UnexpectedParticipantError,
    build_terminal_outcome_envelope,
)

JOB_ID = "job-20260909-001"
PARTICIPANT_NAME = "site-1"
OTHER_PARTICIPANT_NAME = "site-2"


def summary_bytes(
    *,
    job_id: str = JOB_ID,
    participant_name: str = PARTICIPANT_NAME,
    reported_at: str = "2026-09-09T14:37:03Z",
) -> bytes:
    record = {
        "schema_version": "1.0",
        "kind": "nvflare.resource_stats.participant_summary",
        "job_id": job_id,
        "participant_name": participant_name,
        "reported_at": reported_at,
        "resource_time": {
            "status": "unavailable",
            "issues": ["observation_incomplete"],
        },
        "workspace_filesystem": {
            "status": "unavailable",
            "issues": ["observation_incomplete"],
        },
        "retained_content": {
            "status": "unavailable",
            "issues": ["observation_incomplete"],
        },
        "f3": {
            "status": "unavailable",
            "issues": ["observation_incomplete"],
        },
    }
    return (
        json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def semantic_validator(record: Mapping[str, Any], serialized_size: int) -> None:
    if serialized_size <= 0:
        raise ValueError("serialized record must not be empty")
    if record.get("schema_version") != "1.0":
        raise ValueError("unsupported schema version")
    if record.get("kind") != "nvflare.resource_stats.participant_summary":
        raise ValueError("wrong record kind")


def new_receiver(*, second_participant: bool = False, max_bytes: int = MAX_PARTICIPANT_SUMMARY_BYTES):
    expected = [ExpectedParticipant(JOB_ID, "site-1", PARTICIPANT_NAME)]
    if second_participant:
        expected.append(ExpectedParticipant(JOB_ID, "site-2", OTHER_PARTICIPANT_NAME))
    return TerminalReportReceiver(
        expected,
        semantic_validator,
        max_participant_summary_bytes=max_bytes,
    )


class TestTerminalReportTransport(unittest.TestCase):
    def test_builder_matches_common_completion_body_and_missing_report_keeps_outcome(self):
        report = summary_bytes()
        envelope = build_terminal_outcome_envelope(JOB_ID, 0, None, report)
        self.assertEqual({"job_id", "code", "reason", "resource_report"}, set(envelope))
        self.assertEqual(report, envelope["resource_report"]["participant_summary"])
        self.assertEqual({"participant_summary"}, set(envelope["resource_report"]))

        receiver = new_receiver()
        result = receiver.accept(build_terminal_outcome_envelope(JOB_ID, 0, None), "site-1")
        self.assertEqual(TERMINAL_OUTCOME_ACCEPTED, result.terminal_outcome_status)
        self.assertEqual(RESOURCE_REPORT_NOT_PROVIDED, result.resource_report_status)
        self.assertEqual((0, None), receiver.get_terminal_outcome(JOB_ID, "site-1"))
        self.assertIsNone(receiver.get_accepted_report(JOB_ID, PARTICIPANT_NAME))

    def test_first_valid_report_wins_and_exact_retry_is_idempotent(self):
        receiver = new_receiver()
        report = summary_bytes()
        envelope = build_terminal_outcome_envelope(JOB_ID, 0, None, report)

        accepted = receiver.accept(envelope, "site-1")
        duplicate = receiver.accept(envelope, "site-1")

        self.assertEqual(TERMINAL_OUTCOME_ACCEPTED, accepted.terminal_outcome_status)
        self.assertEqual(RESOURCE_REPORT_ACCEPTED, accepted.resource_report_status)
        self.assertEqual(TERMINAL_OUTCOME_DUPLICATE, duplicate.terminal_outcome_status)
        self.assertEqual(RESOURCE_REPORT_DUPLICATE, duplicate.resource_report_status)
        stored = receiver.get_accepted_report(JOB_ID, PARTICIPANT_NAME)
        self.assertIsNotNone(stored)
        self.assertEqual(report, stored.participant_summary)

        conflict = receiver.accept(
            build_terminal_outcome_envelope(
                JOB_ID,
                0,
                None,
                summary_bytes(reported_at="2026-09-09T14:37:04Z"),
            ),
            "site-1",
        )
        self.assertEqual(RESOURCE_REPORT_CONFLICT, conflict.resource_report_status)
        self.assertEqual(report, receiver.get_accepted_report(JOB_ID, PARTICIPANT_NAME).participant_summary)

    def test_invalid_candidate_does_not_reserve_the_slot(self):
        receiver = new_receiver()
        valid = summary_bytes()
        invalid = build_terminal_outcome_envelope(JOB_ID, 0, None, valid)
        invalid["resource_report"]["participant_summary"] = "not bytes"

        rejected = receiver.accept(invalid, "site-1")
        self.assertEqual(TERMINAL_OUTCOME_ACCEPTED, rejected.terminal_outcome_status)
        self.assertEqual(RESOURCE_REPORT_INVALID, rejected.resource_report_status)
        self.assertIsNone(receiver.get_accepted_report(JOB_ID, PARTICIPANT_NAME))

        accepted = receiver.accept(
            build_terminal_outcome_envelope(JOB_ID, 0, None, valid),
            "site-1",
        )
        self.assertEqual(TERMINAL_OUTCOME_DUPLICATE, accepted.terminal_outcome_status)
        self.assertEqual(RESOURCE_REPORT_ACCEPTED, accepted.resource_report_status)

    def test_injected_semantic_validator_rejects_without_reserving_the_slot(self):
        receiver = new_receiver()
        unsupported = summary_bytes().replace(b'"schema_version":"1.0"', b'"schema_version":"2.0"')

        rejected = receiver.accept(
            build_terminal_outcome_envelope(JOB_ID, 0, None, unsupported),
            "site-1",
        )
        self.assertEqual(RESOURCE_REPORT_INVALID, rejected.resource_report_status)
        self.assertIn("unsupported schema version", rejected.detail)
        self.assertIsNone(receiver.get_accepted_report(JOB_ID, PARTICIPANT_NAME))

        accepted = receiver.accept(
            build_terminal_outcome_envelope(JOB_ID, 0, None, summary_bytes()),
            "site-1",
        )
        self.assertEqual(RESOURCE_REPORT_ACCEPTED, accepted.resource_report_status)

    def test_unexpected_validator_fault_is_server_error_not_invalid_client_data(self):
        def broken_validator(record: Mapping[str, Any], serialized_size: int) -> None:
            raise RuntimeError("database unavailable")

        receiver = TerminalReportReceiver(
            [ExpectedParticipant(JOB_ID, "site-1", PARTICIPANT_NAME)],
            broken_validator,
        )
        result = receiver.accept(
            build_terminal_outcome_envelope(JOB_ID, 0, None, summary_bytes()),
            "site-1",
        )

        self.assertEqual(TERMINAL_OUTCOME_ACCEPTED, result.terminal_outcome_status)
        self.assertEqual(RESOURCE_REPORT_SERVER_ERROR, result.resource_report_status)
        self.assertEqual("server could not validate the resource report", result.detail)
        self.assertIsNone(receiver.get_accepted_report(JOB_ID, PARTICIPANT_NAME))

    def test_duplicate_keys_and_trusted_identity_mismatch_are_invalid(self):
        duplicate_key_report = (
            '{"schema_version":"1.0",'
            '"kind":"nvflare.resource_stats.participant_summary",'
            f'"job_id":"{JOB_ID}","job_id":"{JOB_ID}",'
            f'"participant_name":"{PARTICIPANT_NAME}"}}\n'
        ).encode()
        duplicate_receiver = new_receiver()
        duplicate_result = duplicate_receiver.accept(
            build_terminal_outcome_envelope(JOB_ID, 0, None, duplicate_key_report),
            "site-1",
        )
        self.assertEqual(RESOURCE_REPORT_INVALID, duplicate_result.resource_report_status)
        self.assertIn("duplicate JSON object key", duplicate_result.detail)
        self.assertIsNone(duplicate_receiver.get_accepted_report(JOB_ID, PARTICIPANT_NAME))

        deeply_nested_receiver = new_receiver()
        deeply_nested_report = ("[" * 2000 + "0" + "]" * 2000).encode("utf-8")
        deeply_nested_result = deeply_nested_receiver.accept(
            build_terminal_outcome_envelope(JOB_ID, 0, None, deeply_nested_report),
            "site-1",
        )
        self.assertEqual(RESOURCE_REPORT_INVALID, deeply_nested_result.resource_report_status)
        self.assertIsNone(deeply_nested_receiver.get_accepted_report(JOB_ID, PARTICIPANT_NAME))

        mismatch_receiver = new_receiver()
        mismatch_result = mismatch_receiver.accept(
            build_terminal_outcome_envelope(
                JOB_ID,
                0,
                None,
                summary_bytes(participant_name=OTHER_PARTICIPANT_NAME),
            ),
            "site-1",
        )
        self.assertEqual(RESOURCE_REPORT_INVALID, mismatch_result.resource_report_status)
        self.assertIn("participant_name does not match trusted state", mismatch_result.detail)
        self.assertIsNone(mismatch_receiver.get_accepted_report(JOB_ID, PARTICIPANT_NAME))

    def test_size_is_enforced_before_json_decode_or_semantic_validation(self):
        validator_calls = 0

        def counting_validator(record: Mapping[str, Any], serialized_size: int) -> None:
            nonlocal validator_calls
            validator_calls += 1

        receiver = TerminalReportReceiver(
            [ExpectedParticipant(JOB_ID, "site-1", PARTICIPANT_NAME)],
            counting_validator,
            max_participant_summary_bytes=32,
        )
        oversized = b"{" + b" " * 32 + b"}"
        result = receiver.accept(
            build_terminal_outcome_envelope(JOB_ID, 0, None, oversized),
            "site-1",
        )
        self.assertEqual(1 * 1024 * 1024, MAX_PARTICIPANT_SUMMARY_BYTES)
        self.assertEqual(RESOURCE_REPORT_INVALID, result.resource_report_status)
        self.assertIn("32-byte limit", result.detail)
        self.assertEqual(0, validator_calls)

    def test_resource_report_rejects_unknown_envelope_fields(self):
        receiver = new_receiver()
        envelope = build_terminal_outcome_envelope(JOB_ID, 0, None, summary_bytes())
        envelope["resource_report"]["caller_selected_field"] = "not allowed"

        result = receiver.accept(envelope, "site-1")

        self.assertEqual(TERMINAL_OUTCOME_ACCEPTED, result.terminal_outcome_status)
        self.assertEqual(RESOURCE_REPORT_INVALID, result.resource_report_status)
        self.assertIn("requires only", result.detail)
        self.assertIsNone(receiver.get_accepted_report(JOB_ID, PARTICIPANT_NAME))

    def test_cutoff_allows_only_an_already_accepted_exact_retry(self):
        receiver = new_receiver(second_participant=True)
        site_1_envelope = build_terminal_outcome_envelope(JOB_ID, 0, None, summary_bytes())
        receiver.accept(site_1_envelope, "site-1")
        receiver.close_job(JOB_ID)

        duplicate = receiver.accept(site_1_envelope, "site-1")
        late = receiver.accept(
            build_terminal_outcome_envelope(
                JOB_ID,
                0,
                None,
                summary_bytes(participant_name=OTHER_PARTICIPANT_NAME),
            ),
            "site-2",
        )

        self.assertEqual(RESOURCE_REPORT_DUPLICATE, duplicate.resource_report_status)
        self.assertEqual(TERMINAL_OUTCOME_DUPLICATE, duplicate.terminal_outcome_status)
        self.assertEqual(RESOURCE_REPORT_TOO_LATE, late.resource_report_status)
        self.assertEqual(TERMINAL_OUTCOME_TOO_LATE, late.terminal_outcome_status)
        self.assertIsNone(receiver.get_accepted_report(JOB_ID, OTHER_PARTICIPANT_NAME))

    def test_cutoff_wins_atomically_over_a_candidate_still_in_validation(self):
        validation_started = threading.Event()
        finish_validation = threading.Event()

        def blocking_validator(record: Mapping[str, Any], serialized_size: int) -> None:
            semantic_validator(record, serialized_size)
            validation_started.set()
            if not finish_validation.wait(timeout=2):
                raise RuntimeError("test did not release validation")

        receiver = TerminalReportReceiver(
            [ExpectedParticipant(JOB_ID, "site-1", PARTICIPANT_NAME)],
            blocking_validator,
        )
        envelope = build_terminal_outcome_envelope(JOB_ID, 0, None, summary_bytes())
        result_holder = []

        worker = threading.Thread(
            target=lambda: result_holder.append(receiver.accept(envelope, "site-1")),
            daemon=True,
        )
        worker.start()
        self.assertTrue(validation_started.wait(timeout=2))

        receiver.close_job(JOB_ID)
        finish_validation.set()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(1, len(result_holder))
        self.assertEqual(RESOURCE_REPORT_TOO_LATE, result_holder[0].resource_report_status)
        self.assertEqual(TERMINAL_OUTCOME_TOO_LATE, result_holder[0].terminal_outcome_status)
        self.assertIsNone(receiver.get_accepted_report(JOB_ID, PARTICIPANT_NAME))

    def test_authenticated_sender_must_match_server_expected_participants(self):
        receiver = new_receiver()
        envelope = build_terminal_outcome_envelope(JOB_ID, 0, None, summary_bytes())

        with self.assertRaises(UnexpectedParticipantError):
            receiver.accept(envelope, "site-that-was-not-selected")

        self.assertIsNone(receiver.get_terminal_outcome(JOB_ID, "site-1"))
        self.assertIsNone(receiver.get_accepted_report(JOB_ID, PARTICIPANT_NAME))


if __name__ == "__main__":
    unittest.main()
