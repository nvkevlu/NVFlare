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

"""Validate current participant, job, and study records at the report boundary."""

import json
from copy import deepcopy

import pytest

from nvflare.private.fed.resource_stats import contract
from nvflare.private.fed.resource_stats.contract import (
    KIND_PARTICIPANT_SUMMARY,
    KIND_RESOURCE_SUMMARY,
    MAX_JSON_DEPTH,
    SCHEMA_VERSION,
    ContractError,
    canonical_json_bytes,
    capacity_to_resource_time,
    derive_job_totals,
    derive_study_totals,
    load_and_validate,
    normalize_measurement,
    normalize_message_traffic,
    normalize_record,
    participant_measurements,
    validate_record,
)


def _participant_summary(job_id="job-1", participant_name="site-1", reported_at="2026-09-17T12:00:00Z"):
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND_PARTICIPANT_SUMMARY,
        "job_id": job_id,
        "participant_name": participant_name,
        "reported_at": reported_at,
        "resource_capacity": {
            "measured_seconds": "2",
            "cpu": {"groups": [{"units": "16", "model": "AMD EPYC 9654", "architecture": "x86_64"}]},
            "memory": {"bytes": "8192"},
            "gpu": {"groups": []},
        },
        "cpu_consumed": {"seconds": "0"},
        "workspace_filesystem": {"capacity_bytes": "1024"},
        "retained_content": {"status": "unavailable", "issues": ["unsupported"]},
        "message_traffic": {"status": "unavailable", "issues": ["unsupported"]},
    }


def _accepted_entry(participant_name="site-1", role="client", received_at="2026-09-17T12:00:00Z"):
    record = _participant_summary(participant_name=participant_name)
    return {
        "participant_name": participant_name,
        "role": role,
        "received_at": received_at,
        **participant_measurements(record),
    }


def _resource_summary(job_id="job-1", participants=None):
    participants = participants if participants is not None else [_accepted_entry()]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND_RESOURCE_SUMMARY,
        "job_id": job_id,
        "participants": participants,
    }


def test_validate_record_accepts_well_formed_participant_summary():
    validate_record(_participant_summary())


def test_current_accepts_unclassified_cuda_devices_without_inventing_type():
    report = _participant_summary()
    report["resource_capacity"]["gpu"]["groups"] = [
        {"kind": "cuda_device_unclassified", "count": "2", "model": "NVIDIA L40"}
    ]
    validate_record(report)

    report["resource_capacity"]["gpu"]["groups"][0]["mig_profile"] = "1g.10gb"
    with pytest.raises(ContractError, match="MIG compute-instance"):
        validate_record(report)


@pytest.mark.parametrize("version", ["1.0", "2.0", "4.0"])
def test_unreleased_feature_rejects_other_formats_for_all_readers(version):
    record = _participant_summary()
    record["schema_version"] = version
    data = canonical_json_bytes(record)
    with pytest.raises(ContractError, match="schema_version"):
        validate_record(record)
    with pytest.raises(ContractError, match="schema_version"):
        load_and_validate(data, KIND_PARTICIPANT_SUMMARY)
    with pytest.raises(ContractError, match="schema_version"):
        participant_measurements(record)


def test_success_statuses_and_issues_are_absent_from_complete_measurements():
    report = _participant_summary()
    report["retained_content"] = {"bytes": "0"}
    report["message_traffic"] = {"sent_to": []}
    validate_record(report)

    for field in ("resource_capacity", "cpu_consumed", "workspace_filesystem", "retained_content", "message_traffic"):
        explicit_success = deepcopy(report)
        explicit_success[field]["status"] = "reported"
        with pytest.raises(ContractError, match="status"):
            validate_record(explicit_success)

    issues_without_exception = deepcopy(report)
    issues_without_exception["resource_capacity"]["issues"] = ["observation_incomplete"]
    with pytest.raises(ContractError, match="unexpected fields"):
        validate_record(issues_without_exception)

    summary = _resource_summary()
    summary["participants"][0]["status"] = "accepted"
    with pytest.raises(ContractError, match="status"):
        validate_record(summary)


def test_cpu_consumed_is_required_in_unpublished_schema():
    report = _participant_summary()
    report.pop("cpu_consumed")
    with pytest.raises(ContractError, match="cpu_consumed"):
        validate_record(report)


def test_validate_record_accepts_only_sender_confirmed_destination_groups():
    reported = _participant_summary()
    reported["message_traffic"] = {
        "sent_to": [{"participant_name": "server", "payload_bytes": str(2**128 - 1), "messages": "1"}],
    }
    validate_record(reported)

    partial = _participant_summary()
    partial["message_traffic"] = {
        "status": "partial",
        "issues": ["counter_gap"],
        "sent_to": [{"participant_name": "server", "payload_bytes": "1", "messages": "1"}],
    }
    validate_record(partial)

    old_bucket = _participant_summary()
    old_bucket["message_traffic"] = {
        "remote_accepted": {"payload_bytes": "1", "messages": "1"},
        "local_delivered": {"payload_bytes": "0", "messages": "0"},
    }
    with pytest.raises(ContractError):
        validate_record(old_bucket)

    missing_issue = _participant_summary()
    missing_issue["message_traffic"] = {
        "status": "partial",
        "sent_to": [{"participant_name": "server", "payload_bytes": "1", "messages": "1"}],
    }
    with pytest.raises(ContractError):
        validate_record(missing_issue)

    too_large = _participant_summary()
    too_large["message_traffic"] = {
        "sent_to": [{"participant_name": "server", "payload_bytes": str(2**128), "messages": "1"}],
    }
    with pytest.raises(ContractError):
        validate_record(too_large)

    error = _participant_summary()
    error["message_traffic"] = {"status": "unavailable", "issues": ["malformed_source"]}
    validate_record(error)


def test_validate_record_accepts_unordered_but_rejects_duplicate_or_self_destinations():
    report = _participant_summary()
    report["message_traffic"] = {
        "sent_to": [
            {"participant_name": "server", "payload_bytes": "1", "messages": "1"},
            {"participant_name": "site-2", "payload_bytes": "2", "messages": "1"},
        ],
    }
    validate_record(report)

    report["message_traffic"]["sent_to"].reverse()
    validate_record(report)
    assert normalize_record(report)["message_traffic"]["sent_to"][0]["participant_name"] == "server"

    report["message_traffic"]["sent_to"] = [
        {"participant_name": "server", "payload_bytes": "1", "messages": "1"},
        {"participant_name": "server", "payload_bytes": "2", "messages": "1"},
    ]
    with pytest.raises(ContractError, match="unique"):
        validate_record(report)

    report["message_traffic"]["sent_to"] = [{"participant_name": "site-1", "payload_bytes": "1", "messages": "1"}]
    with pytest.raises(ContractError, match="sending participant"):
        validate_record(report)


def test_derive_job_totals_rejects_unknown_destination_and_sums_known_destinations():
    site = _accepted_entry(participant_name="site-1")
    site["message_traffic"] = {
        "sent_to": [{"participant_name": "server", "payload_bytes": "100", "messages": "2"}],
    }
    server = _accepted_entry(participant_name="server", role="server")
    server["message_traffic"] = {
        "sent_to": [{"participant_name": "site-1", "payload_bytes": "200", "messages": "3"}],
    }
    totals = derive_job_totals([site, server])
    assert totals["message_traffic"] == {"sent": {"payload_bytes": "300", "messages": "5"}}

    site["message_traffic"]["sent_to"][0]["participant_name"] = "site-unknown"
    with pytest.raises(ContractError, match="expected participant"):
        derive_job_totals([site, server])


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
    record["workspace_filesystem"] = {"capacity_bytes": "1024", "deep": nested}
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
    data = (
        '{"schema_version": "%s", "kind": "%s", "x": %s}' % (SCHEMA_VERSION, KIND_PARTICIPANT_SUMMARY, literal)
    ).encode()
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


def test_participant_measurements_copies_reportable_fields():
    record = _participant_summary()

    totals = participant_measurements(record)

    assert set(totals) == {"resource_capacity", "cpu_consumed", "retained_content", "message_traffic"}
    assert totals["cpu_consumed"] == {"seconds": "0"}
    assert totals["resource_capacity"] == record["resource_capacity"]
    # Must be a copy, not the same object the caller can still mutate.
    totals["resource_capacity"]["measured_seconds"] = "99"
    assert record["resource_capacity"]["measured_seconds"] == "2"


def test_cpu_consumed_is_independent_of_capacity_time_and_required():
    first = _accepted_entry(participant_name="site-1")
    first["cpu_consumed"] = {"seconds": "3600"}
    second = _accepted_entry(participant_name="site-2")
    second["cpu_consumed"] = {
        "status": "partial",
        "issues": ["attribution_incomplete"],
        "seconds": "1800",
    }
    second["resource_capacity"] = {"status": "unavailable", "issues": ["observation_incomplete"]}

    totals = derive_job_totals([first, second])
    assert totals["cpu_consumed"] == {"status": "partial", "seconds": "5400"}
    assert totals["resource_time"]["status"] == "partial"

    missing_cpu = _accepted_entry(participant_name="site-3")
    missing_cpu.pop("cpu_consumed")
    with pytest.raises(ContractError, match="cpu_consumed"):
        derive_job_totals([first, second, missing_cpu])


def test_cpu_consumed_requires_decimal_seconds_only_with_numeric_status():
    report = _participant_summary()
    report["cpu_consumed"] = {"seconds": "0"}
    validate_record(report)
    report["cpu_consumed"] = {"seconds": "NaN"}
    with pytest.raises(ContractError, match="cpu_consumed.seconds"):
        validate_record(report)
    report["cpu_consumed"] = {"status": "unavailable", "issues": ["observation_incomplete"], "seconds": "0"}
    with pytest.raises(ContractError, match="unexpected fields"):
        validate_record(report)


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

    assert "status" not in totals["resource_time"]
    assert totals["resource_time"]["measured_seconds"] == "2"


def test_derive_job_totals_accepts_unsorted_but_rejects_duplicate_participant_names():
    site_a = _accepted_entry(participant_name="site-a")
    site_b = _accepted_entry(participant_name="site-b")

    assert derive_job_totals([site_b, site_a]) == derive_job_totals([site_a, site_b])
    with pytest.raises(ContractError, match="unique"):
        derive_job_totals([site_a, site_a])


def test_derive_study_totals_tracks_included_jobs_separately_from_study_coverage():
    job_row_included = {
        "job_id": "job-1",
        "job_name": "hello-pt",
        "job_status": "FINISHED:COMPLETED",
        "resource_data": "included",
        "totals": derive_job_totals([_accepted_entry(participant_name="site-1")]),
    }
    job_row_nonterminal = {
        "job_id": "job-2",
        "job_name": "hello-pt-next",
        "job_status": "RUNNING",
        "resource_data": "nonterminal",
    }

    totals = derive_study_totals([job_row_included, job_row_nonterminal])

    # Global coverage tracks the nonterminal job separately from these totals.
    assert totals["resource_time"]["measured_seconds"] == "2"
    assert "status" not in totals["resource_time"]


def test_derive_study_totals_is_reported_when_every_job_row_is_included():
    job_row = {
        "job_id": "job-1",
        "job_name": "hello-pt",
        "job_status": "FINISHED:COMPLETED",
        "resource_data": "included",
        "totals": derive_job_totals([_accepted_entry(participant_name="site-1")]),
    }

    totals = derive_study_totals([job_row])

    assert "status" not in totals["resource_time"]
    assert totals["resource_time"]["measured_seconds"] == "2"


def test_derive_study_totals_allows_duplicate_display_names_for_distinct_job_ids():
    rows = []
    for job_id in ("job-1", "job-2"):
        rows.append(
            {
                "job_id": job_id,
                "job_name": "hello-pt",
                "job_status": "FINISHED:COMPLETED",
                "resource_data": "included",
                "totals": derive_job_totals([_accepted_entry(participant_name="site-1")]),
            }
        )

    totals = derive_study_totals(rows)

    assert totals["resource_time"]["measured_seconds"] == "4"


def test_study_totals_combine_current_jobs_without_version_cohorts():
    first = _accepted_entry(participant_name="site-1")
    first["resource_capacity"]["gpu"]["groups"] = [{"kind": "full_gpu", "count": "1"}]
    second = _accepted_entry(participant_name="site-1")
    second["resource_capacity"]["gpu"]["groups"] = [{"kind": "cuda_device_unclassified", "count": "1"}]
    rows = [
        {
            "job_id": "job-1",
            "job_name": "first-job",
            "job_status": "FINISHED:COMPLETED",
            "resource_data": "included",
            "totals": derive_job_totals([first]),
        },
        {
            "job_id": "job-2",
            "job_name": "second-job",
            "job_status": "FINISHED:COMPLETED",
            "resource_data": "included",
            "totals": derive_job_totals([second]),
        },
    ]
    totals = derive_study_totals(rows)
    assert totals["resource_time"]["gpu"]["groups"] == [
        {"kind": "cuda_device_unclassified", "instance_seconds": "2"},
        {"kind": "full_gpu", "instance_seconds": "2"},
    ]
    study = {
        "schema_version": SCHEMA_VERSION,
        "kind": "nvflare.resource_stats.study_summary",
        "selection": {"study_name": "default"},
        "generated_at": "2026-09-17T12:00:00Z",
        "coverage": {"selected_jobs": "2", "included_jobs": "2", "unavailable_jobs": "0", "nonterminal_jobs": "0"},
        "jobs": rows,
        "totals": totals,
    }
    validate_record(study)


def test_study_with_no_included_jobs_has_unavailable_totals():
    rows = [{"job_id": "job-1", "job_name": "queued", "job_status": "RUNNING", "resource_data": "nonterminal"}]
    totals = derive_study_totals(rows)
    assert totals["resource_time"] == {"status": "unavailable", "issues": ["observation_incomplete"]}
    assert totals["cpu_consumed"] == {"status": "unavailable"}
    assert totals["retained_content"] == {"status": "unavailable"}
    assert totals["message_traffic"] == {"status": "unavailable"}


def test_validate_study_job_rejects_nonterminal_status_with_included_data():
    job_row = {
        "job_id": "job-1",
        "job_name": "hello-pt",
        "job_status": "RUNNING",
        "resource_data": "included",
        "totals": derive_job_totals([_accepted_entry(participant_name="site-1")]),
    }

    with pytest.raises(ContractError, match="terminal"):
        derive_study_totals([job_row])


def test_validate_record_accepts_well_formed_resource_summary():
    validate_record(_resource_summary())


def test_validate_record_rejects_job_name_in_resource_summary():
    summary = _resource_summary()
    summary["job_name"] = "hello-pt"

    with pytest.raises(ContractError, match="unexpected fields"):
        validate_record(summary)


@pytest.mark.parametrize("removed_field", ["report_cutoff_at", "finalized_at", "totals"])
def test_validate_record_rejects_removed_resource_summary_fields(removed_field):
    summary = _resource_summary()
    summary[removed_field] = "unexpected"

    with pytest.raises(ContractError, match="unexpected fields"):
        validate_record(summary)


def test_validate_record_accepts_receipt_after_report_time_without_stored_cutoff():
    summary = _resource_summary(participants=[_accepted_entry(received_at="2026-09-18T12:00:00Z")])

    validate_record(summary)
    assert summary["participants"][0]["received_at"] == "2026-09-18T12:00:00Z"


@pytest.mark.parametrize("name", ["Test Job 1", "肺部训练 — étude 🚀", "name\n\t\x1b[2J\u202e", "é" * 255])
def test_study_display_name_is_not_an_identifier(name):
    row = {"job_id": "job-1", "job_name": name, "job_status": "RUNNING", "resource_data": "nonterminal"}

    assert derive_study_totals([row])["resource_time"]["status"] == "unavailable"
    assert json.loads(canonical_json_bytes(row))["job_name"] == name


@pytest.mark.parametrize("name", ["", "é" * 256, None, [], 123])
def test_study_display_name_retains_length_and_type_bounds(name):
    row = {"job_id": "job-1", "job_name": name, "job_status": "RUNNING", "resource_data": "nonterminal"}

    with pytest.raises(ContractError, match="job_name"):
        derive_study_totals([row])


@pytest.mark.parametrize("spelling", ["2", "2.0", "2.000000000", "0002", "0002.00"])
def test_equivalent_numeric_values_normalize_without_mutating_input(spelling):
    report = _participant_summary()
    report["resource_capacity"]["measured_seconds"] = spelling
    report["workspace_filesystem"]["capacity_bytes"] = spelling
    original = deepcopy(report)

    validate_record(report)
    normalized = normalize_record(report)
    assert normalized["resource_capacity"]["measured_seconds"] == "2"
    assert normalized["workspace_filesystem"]["capacity_bytes"] == "2"
    assert report == original
    assert load_and_validate(json.dumps(report, separators=(",", ":")).encode()) == normalized
    assert load_and_validate(json.dumps(report, indent=4).encode()) == normalized


@pytest.mark.parametrize("spelling", ["-1", "+2", "2e0", "NaN", "Infinity", " 2", "2 ", ".2", "2.", "0.1234567891"])
def test_numeric_normalization_does_not_accept_invalid_values(spelling):
    report = _participant_summary()
    report["resource_capacity"]["measured_seconds"] = spelling
    with pytest.raises(ContractError, match="measured_seconds"):
        normalize_record(report)


def test_numeric_normalization_preserves_precision_bounds_and_integer_semantics():
    report = _participant_summary()
    report["cpu_consumed"]["seconds"] = "0.000000001"
    report["retained_content"] = {"bytes": str(2**128 - 1) + ".0"}
    assert normalize_record(report)["retained_content"]["bytes"] == str(2**128 - 1)
    assert normalize_record(report)["cpu_consumed"]["seconds"] == "0.000000001"

    report["retained_content"]["bytes"] = str(2**128) + ".0"
    with pytest.raises(ContractError, match="no greater"):
        normalize_record(report)
    report["retained_content"]["bytes"] = "2.1"
    with pytest.raises(ContractError, match="integer-valued"):
        normalize_record(report)


def test_reordered_issues_and_hardware_groups_have_identical_normalized_output():
    report = _participant_summary()
    report["resource_capacity"]["cpu"]["groups"] = [
        {"model": "AMD", "units": "2"},
        {"model": "Intel", "units": "3"},
    ]
    report["resource_capacity"]["gpu"]["groups"] = [
        {"kind": "full_gpu", "count": "2", "memory_bytes": "1024"},
        {"kind": "mig_compute_instance", "count": "2", "memory_bytes": "512"},
    ]
    report["message_traffic"] = {
        "status": "partial",
        "issues": ["counter_gap", "observation_incomplete"],
        "sent_to": [],
    }
    reordered = deepcopy(report)
    reordered["resource_capacity"]["cpu"]["groups"].reverse()
    reordered["resource_capacity"]["gpu"]["groups"].reverse()
    reordered["message_traffic"]["issues"].reverse()

    validate_record(reordered)
    assert normalize_record(reordered) == report
    assert canonical_json_bytes(reordered) == canonical_json_bytes(dict(reversed(list(report.items()))))


def test_duplicate_groups_and_issues_remain_invalid_after_normalization():
    report = _participant_summary()
    report["resource_capacity"]["gpu"]["groups"] = [
        {"kind": "full_gpu", "count": "2", "memory_bytes": "1024"},
        {"kind": "full_gpu", "count": "3", "memory_bytes": "1024.0"},
    ]
    with pytest.raises(ContractError, match="unique"):
        normalize_record(report)
    report = _participant_summary()
    report["message_traffic"] = {"status": "partial", "issues": ["counter_gap", "counter_gap"], "sent_to": []}
    with pytest.raises(ContractError, match="unique"):
        normalize_record(report)


def test_traffic_helper_normalizes_without_losing_count_or_destination_checks():
    traffic = {
        "sent_to": [
            {"participant_name": "site-z", "payload_bytes": "02.00", "messages": "1.0"},
            {"participant_name": "site-a", "payload_bytes": "1", "messages": "1"},
        ]
    }
    assert normalize_message_traffic(traffic)["sent_to"] == [
        {"participant_name": "site-a", "payload_bytes": "1", "messages": "1"},
        {"participant_name": "site-z", "payload_bytes": "2", "messages": "1"},
    ]
    traffic["sent_to"][0]["messages"] = "0.0"
    with pytest.raises(ContractError):
        normalize_message_traffic(traffic)


@pytest.mark.parametrize("issue", ["not_bound", "dependency_missing", "permission_denied"])
def test_obsolete_exception_codes_are_not_accepted(issue):
    report = _participant_summary()
    report["retained_content"] = {
        "status": "error" if issue == "permission_denied" else "unavailable",
        "issues": [issue],
    }
    with pytest.raises(ContractError):
        normalize_record(report)
    assert report["retained_content"]["issues"] == [issue]


def test_unavailable_preserves_malformed_measurement_cause_and_invalid_entry_needs_no_issue():
    report = _participant_summary()
    for field in ("cpu_consumed", "workspace_filesystem", "retained_content", "message_traffic"):
        report[field] = {"status": "unavailable", "issues": ["malformed_source"]}
    validate_record(report)
    report["retained_content"]["status"] = "error"
    with pytest.raises(ContractError, match="status"):
        validate_record(report)

    summary = _resource_summary(
        participants=[
            {"participant_name": "site-1", "role": "client", "status": "invalid", "received_at": "2026-09-17T12:00:00Z"}
        ]
    )
    validate_record(summary)
    summary["participants"][0]["issues"] = ["malformed_source"]
    with pytest.raises(ContractError, match="unexpected fields"):
        validate_record(summary)


def test_invalid_causes_duplicates_and_issue_bounds_remain_errors():
    report = _participant_summary()
    for issues in (
        ["not_bound", "not_bound"],
        ["not_bound", "dependency_missing", "unsupported", "observation_incomplete", "attribution_incomplete"],
    ):
        report["retained_content"] = {"status": "unavailable", "issues": issues}
        with pytest.raises(ContractError):
            normalize_record(report)
    report["retained_content"] = {"status": "error", "issues": ["unsupported"]}
    with pytest.raises(ContractError, match="status"):
        normalize_record(report)
    report["retained_content"] = {"bytes": "0"}
    report["resource_capacity"] = {"status": "error", "issues": ["malformed_source"]}
    with pytest.raises(ContractError, match="status"):
        normalize_record(report)


def test_cpu_counter_duration_aggregates_exactly_the_numeric_cpu_contributors():
    first = _accepted_entry(participant_name="site-1")
    first["cpu_consumed"] = {"seconds": "2.0", "measured_seconds": "10.0"}
    first["resource_capacity"] = {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "measured_seconds": "10",
        "cpu": {"groups": [{"units": "8"}]},
    }
    second = _accepted_entry(participant_name="site-2")
    second["cpu_consumed"] = {
        "status": "partial",
        "issues": ["attribution_incomplete"],
        "seconds": "3",
        "measured_seconds": "20",
    }
    missing = {"participant_name": "site-3", "role": "client", "status": "missing"}
    assert derive_job_totals([missing, second, first])["cpu_consumed"] == {
        "status": "partial",
        "seconds": "5",
        "measured_seconds": "30",
    }

    second["cpu_consumed"].pop("measured_seconds")
    assert derive_job_totals([first, second])["cpu_consumed"] == {"status": "partial", "seconds": "5"}
    first["cpu_consumed"]["measured_seconds"] = "-1"
    with pytest.raises(ContractError, match="measured_seconds"):
        derive_job_totals([first])


def test_study_order_numeric_spelling_and_object_keys_do_not_change_validity():
    rows = [
        {"job_id": job_id, "job_name": "waiting", "job_status": "RUNNING", "resource_data": "nonterminal"}
        for job_id in ("job-2", "job-1")
    ]
    study = {
        "schema_version": SCHEMA_VERSION,
        "kind": "nvflare.resource_stats.study_summary",
        "selection": {"study_name": "default"},
        "generated_at": "2026-09-17T12:00:00Z",
        "coverage": {"selected_jobs": "2.0", "included_jobs": "0.0", "unavailable_jobs": "0", "nonterminal_jobs": "2"},
        "jobs": rows,
        "totals": derive_study_totals(rows),
    }
    validate_record(study)
    assert normalize_record(study)["jobs"][0]["job_id"] == "job-1"
    study["jobs"][1]["job_id"] = "job-2"
    with pytest.raises(ContractError, match="unique"):
        validate_record(study)


def test_capacity_products_are_query_only_and_stored_product_reports_are_rejected():
    report = _participant_summary()
    record = normalize_record(report)
    assert "resource_time" not in record
    entry = _accepted_entry()
    assert "resource_time" not in entry
    assert derive_job_totals([entry])["resource_time"]["cpu"]["groups"][0]["unit_seconds"] == "32"
    assert record == report
    legacy = deepcopy(report)
    legacy["resource_time"] = capacity_to_resource_time(legacy.pop("resource_capacity"))
    legacy["schema_version"] = "2.0"
    with pytest.raises(ContractError, match="schema_version"):
        validate_record(legacy)
    legacy["schema_version"] = SCHEMA_VERSION
    with pytest.raises(ContractError, match="resource_capacity"):
        normalize_record(legacy)


def test_capacity_change_uses_each_interval_duration_and_never_extends_gpu_visibility():
    report = _participant_summary()
    before = deepcopy(report["resource_capacity"])
    before["measured_seconds"] = "5"
    before["gpu"]["groups"] = [{"kind": "full_gpu", "count": "2"}]
    after = deepcopy(before)
    after["measured_seconds"] = "15"
    after["gpu"]["groups"] = []
    report["resource_capacity"] = {"measured_seconds": "20", "intervals": [before, after]}
    validate_record(report)
    derived = capacity_to_resource_time(report["resource_capacity"])
    assert derived["gpu"]["groups"] == [{"kind": "full_gpu", "instance_seconds": "10"}]
    report["resource_capacity"]["measured_seconds"] = "21"
    with pytest.raises(ContractError, match="sum"):
        validate_record(report)


@pytest.mark.parametrize("version", [[], {}, None, 3, True])
def test_version_must_be_the_current_string(version):
    report = _participant_summary()
    report["schema_version"] = version
    with pytest.raises(ContractError, match="schema_version"):
        validate_record(report)


@pytest.mark.parametrize(
    "resource,value",
    [
        ("cpu", {"groups": [{"units": "0"}]}),
        ("cpu", {"groups": [{"units": "1048577"}]}),
        ("memory", {"bytes": "1.5"}),
        ("memory", {"bytes": str(2**64)}),
        ("gpu", {"groups": [{"kind": "full_gpu", "count": "1.5"}]}),
        ("gpu", {"groups": [{"kind": "full_gpu", "count": "4097"}]}),
    ],
)
def test_raw_capacity_bounds_and_integer_device_count(resource, value):
    report = _participant_summary()
    report["resource_capacity"][resource] = value
    with pytest.raises(ContractError):
        validate_record(report)


def test_fractional_capacity_product_rounding_preserves_the_original_observation():
    report = _participant_summary()
    report["resource_capacity"]["measured_seconds"] = "0.000000001"
    report["resource_capacity"]["cpu"]["groups"] = [{"units": "0.000000001"}]
    assert normalize_record(report)["resource_capacity"]["cpu"]["groups"] == [{"units": "0.000000001"}]
    derived = capacity_to_resource_time(report["resource_capacity"])
    assert derived["cpu"]["groups"] == [{"unit_seconds": "0"}]


@pytest.mark.parametrize(
    "field",
    ["resource_capacity", "cpu_consumed", "workspace_filesystem", "retained_content", "message_traffic"],
)
def test_one_measurement_normalization_uses_the_same_rules_without_requiring_siblings(field):
    source = _participant_summary()[field]
    normalized = normalize_measurement(field, source)
    assert normalized == source
    assert normalized is not source
    normalized["unexpected"] = "value"
    with pytest.raises(ContractError, match="unexpected"):
        normalize_measurement(field, normalized)
    assert "unexpected" not in source


@pytest.mark.parametrize("field", ["resource_time", "cpu", "anything", None])
def test_one_measurement_normalization_rejects_unknown_names(field):
    with pytest.raises(ContractError, match="supported participant measurement"):
        normalize_measurement(field, {})


def test_best_effort_capacity_can_retain_all_values_and_matching_seconds():
    report = _participant_summary()
    report["resource_capacity"].update(status="partial", issues=["observation_incomplete"])
    normalized = normalize_record(report)
    copied = participant_measurements(normalized)
    totals = derive_job_totals([_accepted_entry() | copied])
    assert normalized["resource_capacity"]["measured_seconds"] == "2"
    assert totals["resource_time"]["status"] == "partial"
    assert totals["resource_time"]["issues"] == ["observation_incomplete"]
    assert totals["resource_time"]["measured_seconds"] == "2"
    assert totals["resource_time"]["cpu"]["groups"][0]["unit_seconds"] == "32"
    assert "status" not in totals["cpu_consumed"]


@pytest.mark.parametrize("operation", ["capacity", "job"])
def test_capacity_products_are_not_computed_twice_within_one_operation(monkeypatch, operation):
    report = _participant_summary()
    entry = _accepted_entry()
    original = contract._capacity_time_from_validated
    calls = []

    def counted(capacity):
        calls.append(capacity)
        return original(capacity)

    monkeypatch.setattr(contract, "_capacity_time_from_validated", counted)
    if operation == "capacity":
        capacity_to_resource_time(report["resource_capacity"])
    else:
        derive_job_totals([entry])
    assert len(calls) == 1
