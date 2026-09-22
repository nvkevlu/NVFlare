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

import threading

from nvflare.private.fed.resource_stats.contract import U128_MAX, validate_record
from nvflare.private.fed.resource_stats.f3_counter import INCLUDED_F3_TRAFFIC_CLASSES, F3Counter, F3TrafficClass


def _counter_dict(payload_bytes=0, messages=0):
    return {"payload_bytes": str(payload_bytes), "messages": str(messages)}


def _participant_record(f3):
    return {
        "schema_version": "1.0",
        "kind": "nvflare.resource_stats.participant_summary",
        "job_id": "job-1",
        "participant_name": "site-1",
        "reported_at": "2026-09-17T12:00:00Z",
        "resource_time": {"status": "unavailable", "issues": ["observation_incomplete"]},
        "workspace_filesystem": {"status": "unavailable", "issues": ["observation_incomplete"]},
        "retained_content": {"status": "unavailable", "issues": ["not_bound"]},
        "f3": f3,
    }


def test_zero_traffic_counter_is_a_reported_value():
    snapshot = F3Counter().freeze()

    assert snapshot == {"status": "reported", "remote_accepted": _counter_dict()}
    validate_record(_participant_record(snapshot))


def test_completion_counts_main_and_out_of_band_bytes_as_one_message():
    counter = F3Counter()
    admission = counter.try_begin(F3TrafficClass.TASK_RESULT)

    assert counter.add_accepted_payload_bytes(admission, 4096)
    assert counter.add_accepted_payload_bytes(admission, 2048)
    assert counter.complete_remote_accepted(admission, 128)

    assert counter.freeze() == {
        "status": "reported",
        "remote_accepted": _counter_dict(6272, 1),
    }


def test_abandoned_operation_is_not_counted_or_reported_as_a_gap():
    counter = F3Counter()
    admission = counter.try_begin(F3TrafficClass.JOB_APPLICATION)
    assert counter.add_accepted_payload_bytes(admission, 100)

    assert counter.abandon(admission)

    assert counter.pending_count == 0
    assert counter.freeze() == {"status": "reported", "remote_accepted": _counter_dict()}


def test_incomplete_operation_is_released_and_reported_as_a_gap():
    counter = F3Counter()
    admission = counter.try_begin(F3TrafficClass.TASK_RESULT)
    assert counter.add_accepted_payload_bytes(admission, 100)

    assert counter.mark_incomplete(admission)

    assert counter.pending_count == 0
    assert counter.freeze() == {
        "status": "partial",
        "issues": ["counter_gap"],
        "remote_accepted": _counter_dict(),
    }


def test_pre_admission_instrumentation_failure_can_mark_a_counter_gap():
    counter = F3Counter()

    assert counter.mark_counter_gap()
    assert counter.mark_counter_gap()
    snapshot = counter.freeze()

    assert snapshot["status"] == "partial"
    assert snapshot["issues"] == ["counter_gap"]
    assert not counter.mark_counter_gap()


def test_invalid_class_is_fail_safe_and_marks_the_observation_partial():
    counter = F3Counter()

    assert counter.try_begin("task_result") is None

    assert counter.freeze() == {
        "status": "partial",
        "issues": ["counter_gap"],
        "remote_accepted": _counter_dict(),
    }


def test_close_stops_admission_without_affecting_caller_work():
    counter = F3Counter()
    counter.close()
    caller_work = []

    admission = counter.try_begin(F3TrafficClass.TASK_RESULT)
    caller_work.append("sent")

    assert admission is None
    assert caller_work == ["sent"]
    assert counter.freeze()["status"] == "reported"


def test_operation_admitted_before_close_can_complete_while_closing():
    counter = F3Counter()
    admission = counter.try_begin(F3TrafficClass.TASK_RESPONSE)

    counter.close()

    assert counter.complete_remote_accepted(admission, 2048)
    assert counter.freeze()["remote_accepted"] == _counter_dict(2048, 1)


def test_freeze_with_pending_admission_reports_counter_gap():
    counter = F3Counter()
    admission = counter.try_begin(F3TrafficClass.TASK_RESULT)

    snapshot = counter.freeze()

    assert admission is not None
    assert snapshot == {
        "status": "partial",
        "issues": ["counter_gap"],
        "remote_accepted": _counter_dict(),
    }
    validate_record(_participant_record(snapshot))


def test_completion_after_freeze_cannot_change_the_published_value():
    counter = F3Counter()
    admission = counter.try_begin(F3TrafficClass.TASK_RESULT)
    frozen = counter.freeze()

    assert not counter.complete_remote_accepted(admission, 999)
    assert counter.freeze() == frozen
    assert counter.freeze()["remote_accepted"] == _counter_dict()


def test_frozen_snapshots_are_defensive_copies():
    counter = F3Counter()
    counter.mark_prior_history_incomplete()
    first = counter.freeze()

    first["status"] = "reported"
    first["issues"].append("counter_gap")
    first["remote_accepted"]["payload_bytes"] = "999"
    second = counter.freeze()

    assert first is not second
    assert second == {
        "status": "partial",
        "issues": ["attribution_incomplete"],
        "remote_accepted": _counter_dict(),
    }


def test_snapshot_reports_in_flight_work_without_fixing_the_cutoff():
    counter = F3Counter()
    admission = counter.try_begin(F3TrafficClass.TASK_RESULT)

    assert counter.snapshot()["issues"] == ["counter_gap"]
    assert counter.complete_remote_accepted(admission, 5)
    assert counter.snapshot() == {"status": "reported", "remote_accepted": _counter_dict(5, 1)}
    assert counter.freeze()["status"] == "reported"


def test_duplicate_completion_is_ignored_without_raising_or_double_counting():
    counter = F3Counter()
    admission = counter.try_begin(F3TrafficClass.TASK_RESULT)

    assert counter.complete_remote_accepted(admission, 10)
    assert not counter.complete_remote_accepted(admission, 10)

    assert counter.freeze() == {"status": "reported", "remote_accepted": _counter_dict(10, 1)}


def test_foreign_admission_is_ignored_without_mutating_either_counter():
    owner = F3Counter()
    other = F3Counter()
    admission = owner.try_begin(F3TrafficClass.TASK_RESULT)

    assert not other.complete_remote_accepted(admission, 10)
    assert other.freeze()["status"] == "reported"
    assert owner.abandon(admission)


def test_malformed_completion_never_raises_and_marks_result_partial():
    for bad_value in (-1, 1.5, True, U128_MAX + 1):
        counter = F3Counter()
        admission = counter.try_begin(F3TrafficClass.TASK_RESULT)

        assert not counter.complete_remote_accepted(admission, bad_value)
        assert counter.pending_count == 0
        assert counter.freeze() == {
            "status": "partial",
            "issues": ["counter_gap"],
            "remote_accepted": _counter_dict(),
        }


def test_malformed_out_of_band_part_never_raises_and_invalidates_operation():
    counter = F3Counter()
    admission = counter.try_begin(F3TrafficClass.TASK_RESULT)

    assert not counter.add_accepted_payload_bytes(admission, -1)
    assert not counter.complete_remote_accepted(admission, 10)

    assert counter.freeze()["remote_accepted"] == _counter_dict()
    assert counter.freeze()["issues"] == ["counter_gap"]


def test_out_of_band_part_after_completion_is_detected_as_a_gap():
    counter = F3Counter()
    admission = counter.try_begin(F3TrafficClass.TASK_RESULT)
    assert counter.complete_remote_accepted(admission, 10)

    assert not counter.add_accepted_payload_bytes(admission, 5)

    assert counter.freeze() == {
        "status": "partial",
        "issues": ["counter_gap"],
        "remote_accepted": _counter_dict(10, 1),
    }


def test_u128_boundary_is_accepted_but_overflow_is_not_published():
    at_limit = F3Counter()
    assert at_limit.complete_remote_accepted(at_limit.try_begin(F3TrafficClass.TASK_RESULT), U128_MAX)
    assert at_limit.freeze()["remote_accepted"] == _counter_dict(U128_MAX, 1)

    overflow = F3Counter()
    assert overflow.complete_remote_accepted(overflow.try_begin(F3TrafficClass.TASK_RESULT), U128_MAX)
    assert not overflow.complete_remote_accepted(overflow.try_begin(F3TrafficClass.TASK_RESULT), 1)
    assert overflow.freeze() == {
        "status": "partial",
        "issues": ["counter_gap"],
        "remote_accepted": _counter_dict(U128_MAX, 1),
    }


def test_u128_overflow_across_main_and_out_of_band_bytes_is_not_published():
    counter = F3Counter()
    admission = counter.try_begin(F3TrafficClass.TASK_RESULT)
    assert counter.add_accepted_payload_bytes(admission, U128_MAX)

    assert not counter.complete_remote_accepted(admission, 1)

    assert counter.freeze()["remote_accepted"] == _counter_dict()
    assert counter.freeze()["status"] == "partial"


def test_concurrent_completions_are_accounted_exactly():
    counter = F3Counter()
    thread_count = 32

    def worker():
        admission = counter.try_begin(F3TrafficClass.TASK_RESULT)
        counter.complete_remote_accepted(admission, 100)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert counter.freeze() == {
        "status": "reported",
        "remote_accepted": _counter_dict(100 * thread_count, thread_count),
    }


def test_condition_drain_waits_for_an_admitted_operation():
    counter = F3Counter()
    admission = counter.try_begin(F3TrafficClass.TASK_RESULT)
    timer = threading.Timer(0.02, counter.complete_remote_accepted, args=(admission, 10))
    timer.start()
    try:
        assert counter.close_and_drain(1.0)
    finally:
        timer.join()

    assert counter.freeze()["status"] == "reported"


def test_condition_drain_timeout_leaves_freeze_to_report_the_gap():
    counter = F3Counter()
    counter.try_begin(F3TrafficClass.TASK_RESULT)

    assert not counter.close_and_drain(0.0)
    assert counter.state == "closing"
    assert counter.freeze()["issues"] == ["counter_gap"]


def test_invalid_drain_timeout_is_fail_safe_and_marks_result_partial():
    counter = F3Counter()

    assert counter.close_and_drain(float("inf"))

    assert counter.freeze()["issues"] == ["counter_gap"]


def test_prior_history_incomplete_is_idempotent_and_survives_freeze():
    counter = F3Counter()

    assert counter.mark_prior_history_incomplete()
    assert counter.mark_prior_history_incomplete()
    snapshot = counter.freeze()

    assert snapshot["status"] == "partial"
    assert snapshot["issues"] == ["attribution_incomplete"]
    assert not counter.mark_prior_history_incomplete()


def test_included_traffic_classes_are_the_three_origin_operations():
    assert {value.value for value in INCLUDED_F3_TRAFFIC_CLASSES} == {
        "job_application",
        "task_response",
        "task_result",
    }
