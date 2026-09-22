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

"""Direct unit coverage for contract.py, independent of collector/coordinator fixtures.

contract.py is the trust-boundary schema validator: it is the one place that
decides whether a byte string a client process asserts about itself is safe to
copy into a server-owned rollup. It previously had no dedicated test file and
was only incidentally exercised through collector_test.py/coordinator_archive_test.py
fixtures, which never construct multi-job study rollups, adversarial JSON, or
forbidden-key payloads.
"""

import json

import pytest

from nvflare.private.fed.resource_stats.contract import (
    KIND_PARTICIPANT_SUMMARY,
    KIND_RESOURCE_SUMMARY,
    MAX_JSON_DEPTH,
    ContractError,
    canonical_json_bytes,
    derive_job_totals,
    derive_participant_totals,
    derive_study_totals,
    load_and_validate,
    validate_record,
)


def _participant_summary(job_id="job-1", participant_name="site-1", reported_at="2026-09-17T12:00:00Z"):
    return {
        "schema_version": "1.0",
        "kind": KIND_PARTICIPANT_SUMMARY,
        "job_id": job_id,
        "participant_name": participant_name,
        "reported_at": reported_at,
        "resource_time": {
            "status": "reported",
            "measured_seconds": "2",
            "cpu": {"groups": [{"unit_seconds": "16", "model": "AMD EPYC 9654", "architecture": "x86_64"}]},
            "memory": {"byte_seconds": "8192"},
            "gpu": {"groups": []},
        },
        "workspace_filesystem": {"status": "reported", "capacity_bytes": "1024"},
        "retained_content": {"status": "unavailable", "issues": ["not_bound"]},
        "f3": {"status": "unavailable", "issues": ["not_bound"]},
    }


def _accepted_entry(participant_name="site-1", role="client", received_at="2026-09-17T12:00:00Z"):
    record = _participant_summary(participant_name=participant_name)
    return {
        "participant_name": participant_name,
        "role": role,
        "status": "accepted",
        "received_at": received_at,
        **derive_participant_totals(record),
    }


def _resource_summary(job_id="job-1", participants=None):
    participants = participants if participants is not None else [_accepted_entry()]
    return {
        "schema_version": "1.0",
        "kind": KIND_RESOURCE_SUMMARY,
        "job_id": job_id,
        "report_cutoff_at": "2026-09-17T12:00:01Z",
        "finalized_at": "2026-09-17T12:00:01Z",
        "participants": participants,
        "totals": derive_job_totals(participants),
    }


def test_validate_record_accepts_well_formed_participant_summary():
    validate_record(_participant_summary())


def test_validate_record_accepts_only_the_remote_f3_counter():
    reported = _participant_summary()
    reported["f3"] = {
        "status": "reported",
        "remote_accepted": {"payload_bytes": str(2**128 - 1), "messages": "1"},
    }
    validate_record(reported)

    partial = _participant_summary()
    partial["f3"] = {
        "status": "partial",
        "issues": ["counter_gap"],
        "remote_accepted": {"payload_bytes": "1", "messages": "1"},
    }
    validate_record(partial)

    old_bucket = _participant_summary()
    old_bucket["f3"] = {
        "status": "reported",
        "remote_accepted": {"payload_bytes": "1", "messages": "1"},
        "local_delivered": {"payload_bytes": "0", "messages": "0"},
    }
    with pytest.raises(ContractError):
        validate_record(old_bucket)

    missing_issue = _participant_summary()
    missing_issue["f3"] = {
        "status": "partial",
        "remote_accepted": {"payload_bytes": "1", "messages": "1"},
    }
    with pytest.raises(ContractError):
        validate_record(missing_issue)

    too_large = _participant_summary()
    too_large["f3"] = {
        "status": "reported",
        "remote_accepted": {"payload_bytes": str(2**128), "messages": "1"},
    }
    with pytest.raises(ContractError):
        validate_record(too_large)

    error = _participant_summary()
    error["f3"] = {"status": "error", "issues": ["malformed_source"]}
    validate_record(error)


def test_validate_record_rejects_unknown_kind():
    record = _participant_summary()
    record["kind"] = "nvflare.resource_stats.not_a_real_kind"
    with pytest.raises(ContractError):
        validate_record(record)


def test_validate_record_rejects_extra_field():
    record = _participant_summary()
    record["unexpected_field"] = "x"
    with pytest.raises(ContractError):
        validate_record(record)


def test_validate_record_rejects_serialized_size_over_the_kind_limit():
    record = _participant_summary()
    with pytest.raises(ContractError, match="exceeds the"):
        validate_record(record, serialized_size=64 * 1024 * 1024)


@pytest.mark.parametrize(
    "forbidden_key",
    ["hostname", "ip_address", "serial_number", "gpu_uuid", "pci_bus_id", "cuda_visible_devices"],
)
def test_validate_record_rejects_forbidden_privacy_keys_at_any_depth(forbidden_key):
    record = _participant_summary()
    record["workspace_filesystem"] = {
        "status": "reported",
        "capacity_bytes": "1024",
        "nested": {forbidden_key: "should-never-appear"},
    }
    with pytest.raises(ContractError, match="forbidden"):
        validate_record(record)


def test_validate_record_rejects_json_depth_over_the_bound():
    nested = {}
    cursor = nested
    for _ in range(MAX_JSON_DEPTH + 5):
        cursor["nested"] = {}
        cursor = cursor["nested"]
    record = _participant_summary()
    record["workspace_filesystem"] = {"status": "reported", "capacity_bytes": "1024", "deep": nested}
    with pytest.raises(ContractError, match="depth"):
        validate_record(record)


def test_load_and_validate_round_trips_canonical_bytes():
    record = _participant_summary()
    data = canonical_json_bytes(record)

    loaded = load_and_validate(data, KIND_PARTICIPANT_SUMMARY)

    assert loaded == record


def test_load_and_validate_rejects_kind_mismatch():
    data = canonical_json_bytes(_participant_summary())
    with pytest.raises(ContractError, match="kind"):
        load_and_validate(data, KIND_RESOURCE_SUMMARY)


def test_load_and_validate_rejects_duplicate_json_object_keys():
    # json.dumps cannot itself produce a duplicate key, so build the raw text.
    data = b'{"a": 1, "a": 2}'
    with pytest.raises(ContractError, match="duplicate"):
        load_and_validate(data)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_load_and_validate_rejects_nonfinite_json_numbers(literal):
    data = ('{"schema_version": "1.0", "kind": "%s", "x": %s}' % (KIND_PARTICIPANT_SUMMARY, literal)).encode()
    with pytest.raises(ContractError, match="non-finite"):
        load_and_validate(data)


def test_load_and_validate_rejects_non_utf8_input():
    with pytest.raises(ContractError, match="UTF-8"):
        load_and_validate(b"\xff\xfe\x00\x01")


def test_load_and_validate_rejects_malformed_json():
    with pytest.raises(ContractError, match="invalid JSON"):
        load_and_validate(b"{not json")


def test_load_and_validate_rejects_input_over_the_absolute_byte_limit():
    oversized = canonical_json_bytes(_participant_summary()) + b" " * (1024 * 1024)
    with pytest.raises(ContractError, match="byte input limit"):
        load_and_validate(oversized, KIND_PARTICIPANT_SUMMARY)


def test_canonical_json_bytes_is_deterministic_and_json_decodable():
    record = _participant_summary()

    first = canonical_json_bytes(record)
    second = canonical_json_bytes(record)

    assert first == second
    assert json.loads(first) == record


def test_derive_participant_totals_copies_exactly_the_three_reportable_fields():
    record = _participant_summary()

    totals = derive_participant_totals(record)

    assert set(totals) == {"resource_time", "retained_content", "f3"}
    assert totals["resource_time"] == record["resource_time"]
    # Must be a copy, not the same object the caller can still mutate.
    totals["resource_time"]["status"] = "mutated"
    assert record["resource_time"]["status"] == "reported"


def test_derive_job_totals_sums_only_accepted_participants():
    accepted_a = _accepted_entry(participant_name="site-1")
    accepted_b = _accepted_entry(participant_name="site-2")
    missing = {"participant_name": "site-3", "role": "client", "status": "missing"}

    totals = derive_job_totals([accepted_a, accepted_b, missing])

    # Two participants each contributed 2 measured_seconds of CPU/memory time.
    assert totals["resource_time"]["status"] == "partial"
    assert totals["resource_time"]["measured_seconds"] == "4"
    assert "observation_incomplete" in totals["resource_time"]["issues"]


def test_derive_job_totals_is_reported_when_every_expected_participant_accepted():
    accepted = _accepted_entry(participant_name="site-1")

    totals = derive_job_totals([accepted])

    assert totals["resource_time"]["status"] == "reported"
    assert totals["resource_time"]["measured_seconds"] == "2"


def test_derive_job_totals_rejects_unsorted_or_duplicate_participant_names():
    site_a = _accepted_entry(participant_name="site-a")
    site_b = _accepted_entry(participant_name="site-b")

    with pytest.raises(ContractError, match="sorted"):
        derive_job_totals([site_b, site_a])
    with pytest.raises(ContractError, match="unique"):
        derive_job_totals([site_a, site_a])


def test_derive_study_totals_aggregates_across_jobs_and_flags_incompleteness():
    job_row_included = {
        "job_id": "job-1",
        "job_status": "FINISHED:COMPLETED",
        "resource_data": "included",
        "totals": derive_job_totals([_accepted_entry(participant_name="site-1")]),
    }
    job_row_nonterminal = {
        "job_id": "job-2",
        "job_status": "RUNNING",
        "resource_data": "nonterminal",
    }

    totals = derive_study_totals([job_row_included, job_row_nonterminal])

    # Only the included job contributes; the nonterminal job makes the result
    # incomplete rather than silently omitted.
    assert totals["resource_time"]["measured_seconds"] == "2"
    assert totals["resource_time"]["status"] == "partial"
    assert "observation_incomplete" in totals["resource_time"]["issues"]


def test_derive_study_totals_is_reported_when_every_job_row_is_included():
    job_row = {
        "job_id": "job-1",
        "job_status": "FINISHED:COMPLETED",
        "resource_data": "included",
        "totals": derive_job_totals([_accepted_entry(participant_name="site-1")]),
    }

    totals = derive_study_totals([job_row])

    assert totals["resource_time"]["status"] == "reported"
    assert totals["resource_time"]["measured_seconds"] == "2"


def test_validate_study_job_rejects_nonterminal_status_with_included_data():
    job_row = {
        "job_id": "job-1",
        "job_status": "RUNNING",
        "resource_data": "included",
        "totals": derive_job_totals([_accepted_entry(participant_name="site-1")]),
    }

    with pytest.raises(ContractError, match="terminal"):
        derive_study_totals([job_row])


def test_validate_record_accepts_well_formed_resource_summary():
    validate_record(_resource_summary())


def test_validate_record_rejects_resource_summary_totals_that_do_not_match_participants():
    summary = _resource_summary()
    summary["totals"]["resource_time"] = {"status": "unavailable", "issues": ["observation_incomplete"]}

    with pytest.raises(ContractError):
        validate_record(summary)
