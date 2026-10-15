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

"""Current raw-capacity schema, query arithmetic, and current-only archive policy."""

import copy
import json
import sys
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schema"
sys.path.insert(0, str(SCHEMA_ROOT))

import contract_v3  # noqa: E402
import generate_v3_examples as examples  # noqa: E402


@pytest.fixture(scope="module")
def schema_v3():
    schema = json.loads((SCHEMA_ROOT / "resource_stats_v3.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


@pytest.fixture(scope="module")
def generated():
    return examples.examples()


def current():
    return examples.participant()


def reject_both(record, schema):
    with pytest.raises(contract_v3.ContractError):
        contract_v3.validate_record(record)
    with pytest.raises(jsonschema.ValidationError):
        schema.validate(record)


def test_synthetic_goldens_match_production_and_current_json_schema(schema_v3, generated):
    assert len(generated) == 21
    for name, data in generated.items():
        assert (SCHEMA_ROOT / "golden" / "v3" / name).read_bytes() == data
        if name.endswith(".json"):
            record = contract_v3.load_and_validate(data)
            schema_v3.validate(record)
            assert contract_v3.canonical_json_bytes(record) == data


def test_live_and_archive_acceptance_is_only_current_format(schema_v3):
    assert contract_v3.SCHEMA_VERSION == "3.0"
    for version in ("1.0", "2.0"):
        record = current()
        record["schema_version"] = version
        encoded = contract_v3.canonical_json_bytes(record)
        with pytest.raises(contract_v3.ContractError):
            contract_v3.validate_record(record)
        with pytest.raises(contract_v3.ContractError):
            contract_v3.load_and_validate(encoded)
        with pytest.raises(jsonschema.ValidationError):
            schema_v3.validate(record)


def test_stored_normal_participant_and_job_entry_keep_raw_capacity_without_products(generated):
    participant = json.loads(generated["participant_summary.json"])
    summary = json.loads(generated["resource_summary.json"])
    assert participant["resource_capacity"]["cpu"]["groups"][0]["units"] == "32"
    assert participant["resource_capacity"]["gpu"]["groups"][0]["count"] == "2"
    assert participant["resource_capacity"]["memory"]["bytes"] == str(64 * examples.GIB)
    entry = next(row for row in summary["participants"] if row["participant_name"] == "site-1")
    assert entry["resource_capacity"] == participant["resource_capacity"]
    for value in (participant, summary):
        encoded = json.dumps(value)
        assert all(
            field not in encoded for field in ("resource_time", "unit_seconds", "instance_seconds", "byte_seconds")
        )
    assert "totals" not in summary


def test_known_capacity_change_uses_each_interval_instead_of_initial_snapshot(generated):
    record = json.loads(generated["participant_summary_changes.json"])
    capacity = record["resource_capacity"]
    assert [item["gpu"]["groups"][0]["count"] for item in capacity["intervals"]] == ["2", "1"]
    totals = contract_v3.capacity_to_resource_time(capacity)
    assert totals["gpu"]["groups"][0]["instance_seconds"] == "900"
    assert totals["cpu"]["groups"][0]["unit_seconds"] == "14400"
    assert totals["memory"]["byte_seconds"] == str(300 * (64 + 32) * examples.GIB)
    assert "varies" in generated["resource_summary_changes.txt"].decode()
    assert "varies" not in generated["resource_summary.txt"].decode()


@pytest.mark.parametrize("field", ["resource_time", "unit_seconds", "instance_seconds", "byte_seconds"])
def test_current_form_forbids_stored_product_fields(schema_v3, field):
    record = current()
    if field == "resource_time":
        record[field] = copy.deepcopy(record["resource_capacity"])
    elif field == "unit_seconds":
        record["resource_capacity"]["cpu"]["groups"][0][field] = "19200"
    elif field == "instance_seconds":
        record["resource_capacity"]["gpu"]["groups"][0][field] = "1200"
    else:
        record["resource_capacity"]["memory"][field] = "41231686041600"
    reject_both(record, schema_v3)


def test_flat_dimensions_and_exceptional_intervals_are_mutually_exclusive(schema_v3, generated):
    record = json.loads(generated["participant_summary_changes.json"])
    record["resource_capacity"]["cpu"] = current()["resource_capacity"]["cpu"]
    reject_both(record, schema_v3)


def test_interval_duration_sum_is_semantic_and_not_a_json_schema_arithmetic_rule(schema_v3, generated):
    record = json.loads(generated["participant_summary_changes.json"])
    record["resource_capacity"]["measured_seconds"] = "601"
    schema_v3.validate(record)
    with pytest.raises(contract_v3.ContractError, match="sum"):
        contract_v3.validate_record(record)


@pytest.mark.parametrize("length", [1, 4097])
def test_interval_count_bound_is_structural_and_semantic(schema_v3, length):
    record = current()
    interval = copy.deepcopy(record["resource_capacity"])
    interval["measured_seconds"] = "1"
    record["resource_capacity"] = {"measured_seconds": str(length), "intervals": [interval] * length}
    reject_both(record, schema_v3)


def test_successful_gpu_zero_and_gpu_unavailability_preserve_different_evidence(schema_v3):
    zero = current()
    zero["resource_capacity"]["gpu"] = {"groups": []}
    schema_v3.validate(zero)
    contract_v3.validate_record(zero)
    assert contract_v3.capacity_to_resource_time(zero["resource_capacity"])["gpu"] == {"groups": []}
    unknown = current()
    unknown["resource_capacity"].pop("gpu")
    unknown["resource_capacity"].update(status="partial", issues=["observation_incomplete"])
    schema_v3.validate(unknown)
    contract_v3.validate_record(unknown)
    derived = contract_v3.capacity_to_resource_time(unknown["resource_capacity"])
    assert "gpu" not in derived
    assert derived["cpu"]["groups"][0]["unit_seconds"] == "19200"
    assert derived["memory"]["byte_seconds"] == str(600 * 64 * examples.GIB)
    totals = contract_v3.derive_job_totals([examples.entry(unknown), examples.entry(examples.server())])
    assert "status" not in totals["cpu_consumed"]


@pytest.mark.parametrize(
    "dimension,field,value", [("cpu", "units", "1048577"), ("memory", "bytes", str(2**64)), ("gpu", "count", "4097")]
)
def test_numeric_semantic_bounds_remain_in_production(schema_v3, dimension, field, value):
    record = current()
    target = record["resource_capacity"][dimension]
    if dimension != "memory":
        target = target["groups"][0]
    target[field] = value
    schema_v3.validate(record)
    with pytest.raises(contract_v3.ContractError):
        contract_v3.validate_record(record)


@pytest.mark.parametrize(
    "dimension,field,value",
    [
        ("cpu", "units", "0"),
        ("memory", "bytes", "0"),
        ("memory", "bytes", "1.5"),
        ("gpu", "count", "0"),
        ("gpu", "count", "1.5"),
        ("gpu", "count", 2),
    ],
)
def test_raw_dimensions_require_positive_capacity_and_integer_memory_gpu_values(schema_v3, dimension, field, value):
    record = current()
    target = record["resource_capacity"][dimension]
    if dimension != "memory":
        target = target["groups"][0]
    target[field] = value
    reject_both(record, schema_v3)


def test_gpu_and_cpu_bounds_apply_to_group_sums(schema_v3):
    record = current()
    record["resource_capacity"]["gpu"]["groups"] = [
        {"kind": "full_gpu", "count": "4096"},
        {"kind": "cuda_device_unclassified", "count": "1"},
    ]
    schema_v3.validate(record)
    with pytest.raises(contract_v3.ContractError):
        contract_v3.validate_record(record)
    record = current()
    record["resource_capacity"]["cpu"]["groups"] = [
        {"units": "1048576", "model": "CPU A"},
        {"units": "1", "model": "CPU B"},
    ]
    schema_v3.validate(record)
    with pytest.raises(contract_v3.ContractError):
        contract_v3.validate_record(record)


@pytest.mark.parametrize(
    "capacity",
    [
        {"status": "reported", "measured_seconds": "1"},
        {"status": "partial", "issues": ["observation_incomplete"]},
        {"status": "unavailable", "issues": ["unsupported"], "measured_seconds": "1"},
        {"status": "error", "issues": ["malformed_source"]},
        {"status": "unavailable", "issues": ["dependency_missing"]},
    ],
)
def test_capacity_exception_syntax_is_closed(schema_v3, capacity):
    record = current()
    record["resource_capacity"] = capacity
    reject_both(record, schema_v3)


@pytest.mark.parametrize("key", ["uuid", "pci_bus_id", "hostname", "cuda_visible_devices"])
def test_current_capacity_rejects_private_raw_fields(schema_v3, key):
    record = current()
    record["resource_capacity"]["gpu"]["groups"][0][key] = "GPU-11111111-1111-1111-1111-111111111111"
    reject_both(record, schema_v3)


def test_private_uuid_cannot_be_hidden_in_a_model(schema_v3):
    record = current()
    record["resource_capacity"]["gpu"]["groups"][0]["model"] = "GPU-11111111-1111-1111-1111-111111111111"
    reject_both(record, schema_v3)


def test_study_combines_current_capacity_reports_without_version_cohorts(schema_v3, generated):
    study = json.loads(generated["study_summary.json"])
    schema_v3.validate(study)
    contract_v3.validate_record(study)
    assert study["totals"]["resource_time"]["gpu"]["groups"][0]["instance_seconds"] == "1800"
    assert study["coverage"] == {
        "selected_jobs": "4",
        "included_jobs": "2",
        "unavailable_jobs": "1",
        "nonterminal_jobs": "1",
    }
    assert "totals_by_schema_version" not in study
    assert all("resource_schema_version" not in row for row in study["jobs"])
    text = generated["study_summary.txt"].decode()
    assert "schema 1.0" not in text and "schema 2.0" not in text


def test_large_capacity_example_derives_exact_products_above_float_precision(generated):
    record = json.loads(generated["participant_summary_large_value.json"])
    duration = 9007199254740993
    totals = contract_v3.capacity_to_resource_time(record["resource_capacity"])
    assert int(totals["memory"]["byte_seconds"]) == contract_v3.U64_MAX * duration
    assert int(totals["cpu"]["groups"][0]["unit_seconds"]) == 1048576 * duration
    assert int(totals["gpu"]["groups"][0]["instance_seconds"]) == 4096 * duration


def test_fractional_cpu_units_and_equivalent_numeric_strings_are_normalized(schema_v3):
    record = current()
    record["resource_capacity"]["cpu"]["groups"][0]["units"] = "000.5000"
    record["resource_capacity"]["gpu"]["groups"][0]["count"] = "002.000"
    record["resource_capacity"]["memory"]["bytes"] = "01073741824.00"
    schema_v3.validate(record)
    normalized = contract_v3.normalize_record(record)
    assert normalized["resource_capacity"]["cpu"]["groups"][0]["units"] == "0.5"
    assert normalized["resource_capacity"]["gpu"]["groups"][0]["count"] == "2"
    assert normalized["resource_capacity"]["memory"]["bytes"] == "1073741824"
    assert (
        contract_v3.capacity_to_resource_time(normalized["resource_capacity"])["cpu"]["groups"][0]["unit_seconds"]
        == "300"
    )


def test_derived_capacity_time_overflow_is_rejected_before_acceptance(schema_v3):
    record = current()
    record["resource_capacity"]["measured_seconds"] = str(contract_v3.U128_MAX)
    schema_v3.validate(record)
    with pytest.raises(contract_v3.ContractError, match="bound"):
        contract_v3.validate_record(record)


def test_live_invalid_entry_does_not_accept_old_redundant_issue(schema_v3):
    summary = {
        "schema_version": "3.0",
        "kind": contract_v3.KIND_RESOURCE_SUMMARY,
        "job_id": "synthetic-invalid",
        "participants": [
            {"participant_name": "site-1", "role": "client", "status": "invalid", "received_at": examples.AT}
        ],
    }
    schema_v3.validate(summary)
    contract_v3.validate_record(summary)
    summary["participants"][0]["issues"] = ["malformed_source"]
    reject_both(summary, schema_v3)
