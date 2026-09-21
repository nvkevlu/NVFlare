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

import pytest

from nvflare.private.fed.resource_stats.contract import ContractError, validate_record
from nvflare.private.fed.resource_stats.f3_counter import F3Counter, F3TrafficClass


def _zero_counter_dict():
    return {"payload_bytes": "0", "messages": "0"}


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


def test_zero_traffic_counter_is_reported_not_missing():
    counter = F3Counter()

    snapshot = counter.freeze()

    assert snapshot == {
        "status": "reported",
        "remote_accepted": _zero_counter_dict(),
        "local_delivered": _zero_counter_dict(),
        "remote_failed_before_acceptance": _zero_counter_dict(),
    }
    # This is a real, publishable f3 value on its own.
    validate_record(_participant_record(snapshot))


def test_remote_send_counts_only_on_transport_success():
    counter = F3Counter()

    result = counter.record_remote_send(F3TrafficClass.TASK_RESULT, 1024, lambda: "ok", messages=2)

    assert result == "ok"
    snapshot = counter.freeze()
    assert snapshot["remote_accepted"] == {"payload_bytes": "1024", "messages": "2"}
    assert snapshot["local_delivered"] == _zero_counter_dict()
    assert snapshot["remote_failed_before_acceptance"] == _zero_counter_dict()
    assert snapshot["status"] == "reported"


def test_remote_send_failure_counts_as_failed_before_acceptance_and_reraises():
    counter = F3Counter()

    def boom():
        raise RuntimeError("transport rejected")

    with pytest.raises(RuntimeError, match="transport rejected"):
        counter.record_remote_send(F3TrafficClass.TASK_REQUEST, 512, boom)

    snapshot = counter.freeze()
    assert snapshot["remote_failed_before_acceptance"] == {"payload_bytes": "512", "messages": "1"}
    assert snapshot["remote_accepted"] == _zero_counter_dict()
    # A failed remote send is still a "clean" observation, not a gap.
    assert snapshot["status"] == "reported"


def test_local_delivery_success_counts_local_delivered():
    counter = F3Counter()

    result = counter.record_local_delivery(F3TrafficClass.JOB_APPLICATION, 256, lambda: 42)

    assert result == 42
    snapshot = counter.freeze()
    assert snapshot["local_delivered"] == {"payload_bytes": "256", "messages": "1"}
    assert snapshot["remote_accepted"] == _zero_counter_dict()
    assert snapshot["remote_failed_before_acceptance"] == _zero_counter_dict()


def test_local_delivery_failure_is_not_counted_anywhere_but_still_reraises():
    counter = F3Counter()

    def boom():
        raise ValueError("delivery failed")

    with pytest.raises(ValueError, match="delivery failed"):
        counter.record_local_delivery(F3TrafficClass.JOB_APPLICATION, 256, boom)

    snapshot = counter.freeze()
    assert snapshot["local_delivered"] == _zero_counter_dict()
    assert snapshot["status"] == "reported"
    assert counter.pending_count == 0


def test_excluded_traffic_class_is_not_a_valid_admission_argument():
    counter = F3Counter()

    with pytest.raises(TypeError):
        counter.begin("task_request")  # a raw string, not F3TrafficClass, must be rejected


def test_close_stops_new_admissions_but_send_still_executes():
    counter = F3Counter()
    counter.close()
    calls = []

    result = counter.record_remote_send(F3TrafficClass.TASK_REQUEST, 999, lambda: calls.append(1) or "sent")

    # The send always happens -- this class only decides whether to count it.
    assert calls == [1]
    assert result == "sent"
    snapshot = counter.freeze()
    assert snapshot["remote_accepted"] == _zero_counter_dict()
    assert snapshot["status"] == "reported"


def test_admission_started_before_close_still_completes_during_closing():
    counter = F3Counter()
    admission = counter.begin(F3TrafficClass.TASK_RESULT)
    assert admission is not None

    counter.close()
    # begin() before close() succeeded; completing it now (during "closing") must still count.
    counter._complete(admission, "remote_accepted", 2048, 1)

    snapshot = counter.freeze()
    assert snapshot["remote_accepted"] == {"payload_bytes": "2048", "messages": "1"}
    assert snapshot["status"] == "reported"


def test_freeze_with_pending_admission_reports_counter_gap():
    counter = F3Counter()
    admission = counter.begin(F3TrafficClass.TASK_REQUEST)
    assert admission is not None
    assert counter.pending_count == 1

    snapshot = counter.freeze()

    assert snapshot["status"] == "partial"
    assert snapshot["issues"] == ["counter_gap"]
    # The gap doesn't invent numbers; the in-flight op is simply not in any bucket.
    assert snapshot["remote_accepted"] == _zero_counter_dict()
    validate_record(_participant_record(snapshot))


def test_completion_after_freeze_does_not_mutate_the_published_snapshot():
    counter = F3Counter()
    admission = counter.begin(F3TrafficClass.TASK_REQUEST)
    frozen = counter.freeze()
    assert frozen["status"] == "partial"

    # A callback that linearizes after freeze() must not change the canonical snapshot.
    counter._complete(admission, "remote_accepted", 999, 1)

    assert counter.freeze() is frozen
    assert frozen["remote_accepted"] == _zero_counter_dict()


def test_freeze_is_idempotent_and_returns_the_same_object():
    counter = F3Counter()
    counter.record_remote_send(F3TrafficClass.TASK_RESULT, 10, lambda: None)

    first = counter.freeze()
    counter.record_remote_send(F3TrafficClass.TASK_RESULT, 999, lambda: None)  # frozen: not admitted
    second = counter.freeze()

    assert first is second
    assert first["remote_accepted"] == {"payload_bytes": "10", "messages": "1"}


def test_snapshot_before_freeze_reflects_in_flight_state_without_fixing_cutoff():
    counter = F3Counter()
    counter.record_remote_send(F3TrafficClass.TASK_RESULT, 10, lambda: None)
    admission = counter.begin(F3TrafficClass.TASK_REQUEST)

    live = counter.snapshot()
    assert live["status"] == "partial"
    assert live["issues"] == ["counter_gap"]

    counter._complete(admission, "remote_accepted", 5, 1)
    settled = counter.snapshot()
    assert settled["status"] == "reported"
    assert settled["remote_accepted"] == {"payload_bytes": "15", "messages": "2"}

    # snapshot() never fixes the cutoff; freeze() still works normally afterward.
    frozen = counter.freeze()
    assert frozen["status"] == "reported"


def test_double_completion_of_the_same_admission_raises():
    counter = F3Counter()
    admission = counter.begin(F3TrafficClass.TASK_RESULT)
    counter._complete(admission, "remote_accepted", 1, 1)

    with pytest.raises(RuntimeError, match="already been completed"):
        counter._complete(admission, "remote_accepted", 1, 1)


@pytest.mark.parametrize("payload_bytes,messages", [(-1, 1), (1.0, 1), (True, 1), (1, 0), (1, -1), (1, 1.0)])
def test_invalid_payload_or_message_count_is_rejected(payload_bytes, messages):
    counter = F3Counter()

    with pytest.raises(ValueError):
        counter.record_remote_send(F3TrafficClass.TASK_RESULT, payload_bytes, lambda: None, messages=messages)


def test_concurrent_remote_sends_are_accounted_exactly():
    counter = F3Counter()
    thread_count = 32

    def worker():
        counter.record_remote_send(F3TrafficClass.TASK_REQUEST, 100, lambda: None)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    snapshot = counter.freeze()
    assert snapshot["remote_accepted"] == {"payload_bytes": str(100 * thread_count), "messages": str(thread_count)}
    assert snapshot["status"] == "reported"


def test_included_traffic_classes_cover_exactly_the_five_documented_classes():
    from nvflare.private.fed.resource_stats.f3_counter import INCLUDED_F3_TRAFFIC_CLASSES

    assert {value.value for value in INCLUDED_F3_TRAFFIC_CLASSES} == {
        "task_request",
        "task_response",
        "task_result",
        "job_application",
        "job_stream_data",
    }


def test_partial_snapshot_is_rejected_without_the_counter_gap_issue():
    # Sanity check that the production validator actually enforces the shape
    # this module relies on, so a future edit here can't silently drift.
    bad = {
        "status": "partial",
        "remote_accepted": _zero_counter_dict(),
        "local_delivered": _zero_counter_dict(),
        "remote_failed_before_acceptance": _zero_counter_dict(),
    }
    with pytest.raises(ContractError):
        validate_record(_participant_record(bad))
