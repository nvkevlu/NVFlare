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

import re
from copy import deepcopy

import pytest

from nvflare.private.fed.resource_stats.contract import SCHEMA_VERSION, derive_job_totals, derive_study_totals
from nvflare.tool.job.job_resources import render_job_resources, render_study_resources


def _job_summary(participant):
    return {
        "schema_version": SCHEMA_VERSION,
        "job_id": "job-1",
        "participants": [
            {
                "participant_name": participant["participant_name"],
                "role": participant["role"],
                "received_at": "2026-09-17T12:00:00Z",
                "resource_capacity": participant["resource_capacity"],
                "cpu_consumed": participant["cpu_consumed"],
                "retained_content": participant["retained_content"],
                "message_traffic": participant["message_traffic"],
            }
        ],
    }


def _participant():
    return {
        "participant_name": "site-1",
        "role": "client",
        "resource_capacity": {
            "measured_seconds": "3600",
            "cpu": {"groups": [{"units": "8", "model": "AMD EPYC 9654"}]},
            "memory": {"bytes": str(64 * 2**30)},
            "gpu": {"groups": [{"kind": "full_gpu", "count": "2", "model": "NVIDIA H100 80GB HBM3"}]},
        },
        "cpu_consumed": {"seconds": "1800", "measured_seconds": "3600"},
        "retained_content": {"status": "unavailable", "issues": ["observation_incomplete"]},
        "message_traffic": {"status": "unavailable", "issues": ["observation_incomplete"]},
        "workspace_filesystem": {"capacity_bytes": str(2 * 2**40)},
    }


def _with_missing_server(summary):
    summary["participants"].append({"participant_name": "server", "role": "server", "status": "missing"})
    return summary


def _site_cell(output: str, header: str, site: str = "site-1") -> str:
    headings = next(line for line in output.splitlines() if header in line)
    values = next(line for line in output.splitlines() if line.startswith(site))
    columns = re.split(r"\s{2,}", headings.strip())
    cells = re.split(r"\s{2,}", values.strip())
    return cells[next(index for index, column in enumerate(columns) if column.startswith(header))]


@pytest.mark.parametrize("measured, cpu_hours", [("3600", "8.0000"), ("7200", "16.0000"), ("0", "0.0000")])
def test_schema_3_displays_observed_capacity_without_dividing_by_duration(measured, cpu_hours):
    participant = _participant()
    participant["resource_capacity"]["measured_seconds"] = measured
    summary = _job_summary(participant)

    output = render_job_resources(summary, job_name="hello-pt")
    detail = render_job_resources(summary, participant)

    assert "GPU count basis: CUDA Driver (schema 3.0)." in output
    assert "Observed resources per participant" in output
    assert "AVG CPU VISIBLE" not in output
    assert "AVG MEM" not in output
    assert "AVG CUDA DEVICES" not in output
    assert _site_cell(output, "CPU VISIBLE") == "8.0000"
    assert _site_cell(output, "AVG CPU USED") == "0.5000"
    assert _site_cell(output, "MEM GiB") == "64.0000"
    assert _site_cell(output, "CUDA DEVICES") == "2.0000"
    assert _site_cell(output, "VERIFIED FULL GPUs") == "2.0000"
    assert "Derived capacity-time totals" in output
    assert f"CPU visible {cpu_hours} core-h" in output
    assert "matching measured interval" in output
    assert "AMD EPYC 9654; 8.0000 visible units" in detail
    assert "NVIDIA H100 80GB HBM3; 2.0000 visible instances" in detail
    assert "average visible" not in detail
    assert "visible capacity unavailable" not in output


def test_schema_3_partial_capacity_and_cpu_counter_keep_their_own_values_and_windows():
    participant = _participant()
    participant["resource_capacity"] = {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "measured_seconds": "3",
        "cpu": {"groups": [{"units": "8"}]},
        "memory": {"bytes": str(64 * 2**30)},
    }
    participant["cpu_consumed"] = {"seconds": "2", "measured_seconds": "10"}

    output = render_job_resources(_job_summary(participant))

    assert _site_cell(output, "CPU VISIBLE") == "8.0000*"
    assert _site_cell(output, "MEM GiB") == "64.0000*"
    assert _site_cell(output, "AVG CPU USED") == "0.2000"
    assert _site_cell(output, "CUDA DEVICES") == "—"
    assert "visible capacity partial (observation incomplete)" in output


def test_schema_3_zero_visible_devices_is_an_observed_zero():
    participant = _participant()
    participant["resource_capacity"]["gpu"] = {"groups": []}

    output = render_job_resources(_job_summary(participant))

    assert _site_cell(output, "CUDA DEVICES") == "0.0000"
    assert _site_cell(output, "VERIFIED FULL GPUs") == "0.0000"
    assert "CUDA devices available 0.0000 device-h" in output
    assert "visible capacity unavailable" not in output


def test_schema_3_capacity_changes_show_varies_without_inventing_an_average():
    participant = _participant()
    first = deepcopy(participant["resource_capacity"])
    first["measured_seconds"] = "1800"
    second = deepcopy(first)
    second["cpu"]["groups"][0]["units"] = "16"
    second["gpu"]["groups"][0]["count"] = "4"
    participant["resource_capacity"] = {"measured_seconds": "3600", "intervals": [first, second]}
    summary = _job_summary(participant)

    output = render_job_resources(summary)
    detail = render_job_resources(summary, participant)

    assert _site_cell(output, "CPU VISIBLE") == "varies"
    assert _site_cell(output, "MEM GiB") == "64.0000"
    assert _site_cell(output, "CUDA DEVICES") == "varies"
    assert _site_cell(output, "VERIFIED FULL GPUs") == "varies"
    assert _site_cell(output, "AVG CPU USED") == "0.5000"
    assert "CPU visible 12.0000 core-h" in output
    assert "CUDA devices available 3.0000 device-h" in output
    assert "2 recorded intervals" in detail
    assert "each interval's capacity and hardware details" in detail
    assert "average visible" not in detail


def test_schema_3_gpu_classes_are_inspected_across_capacity_intervals():
    participant = _participant()
    first = deepcopy(participant["resource_capacity"])
    first["measured_seconds"] = "1800"
    second = deepcopy(first)
    second["gpu"]["groups"] = [
        {"kind": "mig_compute_instance", "count": "1", "model": "NVIDIA H100 MIG 1g.10gb"},
        {"kind": "cuda_device_unclassified", "count": "1"},
    ]
    participant["resource_capacity"] = {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "measured_seconds": "3600",
        "intervals": [first, second],
    }

    output = render_job_resources(_job_summary(participant))

    assert _site_cell(output, "CUDA DEVICES") == "2.0000*"
    assert _site_cell(output, "VERIFIED FULL GPUs") == "varies*"
    assert _site_cell(output, "MIG INSTANCES") == "varies*"
    assert _site_cell(output, "TYPE-UNVERIFIED") == "varies*"
    assert "MIG instances visible 0.5000* instance-h" in output
    assert "Type-unverified CUDA devices 0.5000* device-h" in output


def test_schema_3_site_detail_reports_observed_mig_and_unclassified_counts():
    participant = _participant()
    participant["resource_capacity"]["gpu"]["groups"].extend(
        [
            {
                "kind": "mig_compute_instance",
                "count": "1",
                "model": "NVIDIA H100 MIG 1g.10gb",
                "mig_profile": "1g.10gb",
            },
            {"kind": "cuda_device_unclassified", "count": "1", "model": "NVIDIA H100 80GB HBM3"},
        ]
    )

    output = render_job_resources(_job_summary(participant), participant)

    assert _site_cell(output, "CUDA DEVICES") == "4.0000"
    assert _site_cell(output, "MIG INSTANCES") == "1.0000"
    assert _site_cell(output, "TYPE-UNVERIFIED") == "1.0000"
    assert "MIG compute instance: NVIDIA H100 MIG 1g.10gb (1g.10gb); 1.0000 visible instances" in output
    assert "CUDA device, type unverified: NVIDIA H100 80GB HBM3; 1.0000 visible instances" in output


def test_mig_column_is_hidden_when_no_participant_reports_mig():
    participant = _participant()

    output = render_job_resources(_job_summary(participant), job_name="hello-pt")

    assert output.startswith("Recorded resources for job hello-pt (ID: job-1).")
    assert "GPU count basis: CUDA Driver (schema 3.0)." in output
    assert "CPU VISIBLE" in output
    assert "AVG CPU USED" in output
    assert "MEM GiB" in output
    assert "CUDA DEVICES" in output
    assert "VERIFIED FULL GPUs" in output
    assert "MIG INSTANCES" not in output
    assert "8.0000" in output
    assert "0.5000" in output  # 1,800 consumed CPU seconds / 3,600 measured seconds.
    assert "64.0000" in output
    assert "2.0000" in output
    assert "RUN-DIR FILES" not in output
    assert "MESSAGE PAYLOAD SENT" not in output
    assert "CPU visible 8.0000 core-h" in output
    assert "CPU time used 0.5000 core-h" in output
    assert "Memory visible 64.0000 GiB-h" in output
    assert "CUDA devices available 2.0000 device-h" in output
    assert "Verified full GPUs 2.0000 GPU-h" in output
    assert "COMPUTE" not in output
    assert "CPU CONSUMED STATUS" not in output
    assert "accepted" not in output.lower()
    assert "reported" not in output.lower()


def test_job_header_falls_back_to_id_when_name_metadata_is_not_supplied():
    output = render_job_resources(_job_summary(_participant()))
    assert output.startswith("Recorded resources for job ID job-1.")


def test_mig_column_and_site_detail_are_shown_only_when_applicable():
    participant = _participant()
    participant["resource_capacity"]["gpu"]["groups"].append(
        {
            "kind": "mig_compute_instance",
            "count": "1",
            "model": "NVIDIA H100 MIG 1g.10gb",
            "mig_profile": "1g.10gb",
        }
    )
    summary = _job_summary(participant)

    job_output = render_job_resources(summary)
    site_output = render_job_resources(summary, participant)

    assert "MIG INSTANCES" in job_output
    assert "1.0000" in job_output
    assert "CUDA devices available 3.0000 device-h" in job_output
    assert "MIG compute instance: NVIDIA H100 MIG 1g.10gb (1g.10gb)" in site_output
    assert "1.0000 visible instances" in site_output


def test_driver_counted_unclassified_time_is_complete_and_not_double_counted():
    participant = _participant()
    participant["resource_capacity"]["gpu"]["groups"].insert(
        0, {"kind": "cuda_device_unclassified", "count": "1", "model": "NVIDIA H100 80GB HBM3"}
    )
    summary = _job_summary(participant)

    output = render_job_resources(summary)
    detail = render_job_resources(summary, participant)

    assert _site_cell(output, "CUDA DEVICES") == "3.0000"
    assert _site_cell(output, "VERIFIED FULL GPUs") == "2.0000"
    assert _site_cell(output, "TYPE-UNVERIFIED") == "1.0000"
    assert "CUDA devices available 3.0000 device-h" in output
    assert "Verified full GPUs 2.0000 GPU-h" in output
    assert "Type-unverified CUDA devices 1.0000 device-h" in output
    assert "CUDA device, type unverified: NVIDIA H100 80GB HBM3" in detail
    assert "visible capacity incomplete" not in output


def test_run_directory_files_and_message_traffic_columns_are_only_shown_when_bound():
    participant = _participant()
    summary = _job_summary(participant)

    initial_output = render_job_resources(summary)
    assert "RUN-DIR FILES" not in initial_output
    assert "MESSAGE PAYLOAD SENT" not in initial_output

    participant["retained_content"] = {"bytes": str(3 * 2**30)}
    participant["message_traffic"] = {
        "status": "partial",
        "issues": ["counter_gap"],
        "sent_to": [{"participant_name": "server", "payload_bytes": str(5 * 2**30), "messages": "10"}],
    }
    summary = _with_missing_server(_job_summary(participant))
    output = render_job_resources(summary)

    assert "RUN-DIR FILES GiB" in output
    assert "PAYLOAD SENT GiB" in output
    assert "PAYLOAD SENT TO SITE GiB" in output
    assert "Run-dir files 3.0000* GiB" in output  # The server report is missing.
    assert "5.0000*" in output  # Counter gap: useful subtotal, not a complete send total.
    assert "RUN-DIR STATUS" not in output
    assert "MESSAGE TRAFFIC STATUS" not in output
    assert "Data gaps" in output
    assert "server" in output  # The expected server report is missing.

    participant["retained_content"] = {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "bytes": str(2 * 2**30),
    }
    partial_output = render_job_resources(_with_missing_server(_job_summary(participant)))
    assert "2.0000*" in partial_output
    assert "RUN-DIR STATUS" not in partial_output


def test_sender_confirmed_inbound_remains_visible_when_destination_report_is_missing():
    site = _participant()
    site["message_traffic"] = {
        "sent_to": [{"participant_name": "server", "payload_bytes": str(2**30), "messages": "2"}],
    }
    summary = _with_missing_server(_job_summary(site))

    output = render_job_resources(summary)
    server_row = next(line for line in output.splitlines() if line.startswith("server") and "1.0000" in line)
    assert "—" in server_row
    assert "1.0000" in server_row
    assert "sender-confirmed" in output


def test_cpu_used_average_is_marked_when_process_cpu_is_incomplete():
    participant = _participant()
    participant["cpu_consumed"] = {
        "status": "partial",
        "issues": ["attribution_incomplete"],
        "seconds": "900",
        "measured_seconds": "3600",
    }

    output = render_job_resources(_job_summary(participant))

    assert _site_cell(output, "CPU VISIBLE") == "8.0000"
    assert _site_cell(output, "AVG CPU USED") == "0.2500*"  # 900 / 3,600; incomplete subtotal.
    assert "Data gaps" in output
    assert "CPU CONSUMED STATUS" not in output


def test_cpu_used_average_does_not_use_capacity_duration_when_its_clock_is_missing():
    participant = _participant()
    participant["resource_capacity"] = {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "measured_seconds": "3600",
        "cpu": participant["resource_capacity"]["cpu"],
    }

    participant["cpu_consumed"] = {"seconds": "2"}

    output = render_job_resources(_job_summary(participant))

    assert _site_cell(output, "AVG CPU USED") == "—"
    assert "Data gaps" in output


@pytest.mark.parametrize("cpu_partial", [False, True])
def test_cpu_used_average_uses_its_own_interval_when_gpu_observation_is_missing(cpu_partial):
    participant = _participant()
    participant["resource_capacity"] = {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "measured_seconds": "10",
        "cpu": {"groups": [{"units": "8"}]},
        "memory": {"bytes": str(64 * 2**30)},
    }
    participant["cpu_consumed"] = {"seconds": "2", "measured_seconds": "10"}
    if cpu_partial:
        participant["cpu_consumed"].update(status="partial", issues=["attribution_incomplete"])

    output = render_job_resources(_job_summary(participant))

    assert _site_cell(output, "AVG CPU USED") == ("0.2000*" if cpu_partial else "0.2000")
    assert _site_cell(output, "CUDA DEVICES") == "—"


def test_cpu_used_average_never_divides_by_a_different_capacity_interval():
    participant = _participant()
    participant["resource_capacity"].update(status="partial", issues=["observation_incomplete"], measured_seconds="3")
    participant["cpu_consumed"] = {"seconds": "2", "measured_seconds": "10"}

    output = render_job_resources(_job_summary(participant))

    assert _site_cell(output, "AVG CPU USED") == "0.2000"


def test_cpu_used_average_remains_available_without_any_capacity_measurement():
    participant = _participant()
    participant["resource_capacity"] = {"status": "unavailable", "issues": ["observation_incomplete"]}
    participant["cpu_consumed"] = {"seconds": "2", "measured_seconds": "10"}

    output = render_job_resources(_job_summary(participant))

    assert _site_cell(output, "AVG CPU USED") == "0.2000"
    assert _site_cell(output, "CPU VISIBLE") == "—"


def test_zero_cpu_counter_window_is_not_replaced_by_capacity_duration():
    participant = _participant()
    participant["cpu_consumed"] = {"seconds": "2", "measured_seconds": "0"}

    output = render_job_resources(_job_summary(participant))

    assert _site_cell(output, "AVG CPU USED") == "—"


def test_failed_cpu_clock_does_not_fall_back_to_an_unrelated_capacity_window():
    participant = _participant()
    participant["cpu_consumed"] = {"status": "partial", "issues": ["observation_incomplete"], "seconds": "2"}

    output = render_job_resources(_job_summary(participant))

    assert _site_cell(output, "AVG CPU USED") == "—"


def test_unavailable_source_cause_is_shown_without_another_status_column():
    participant = _participant()
    participant["retained_content"] = {"status": "unavailable", "issues": ["malformed_source"]}

    output = render_job_resources(_job_summary(participant))

    assert "run-dir files unavailable (invalid source data)" in output
    assert "RUN-DIR STATUS" not in output


def test_job_renderer_sorts_participants_and_accepts_equivalent_integer_spelling():
    summary = _with_missing_server(_job_summary(_participant()))
    summary["participants"][0]["message_traffic"] = {
        "sent_to": [{"participant_name": "server", "payload_bytes": "1073741824", "messages": "1"}]
    }
    alternate = deepcopy(summary)
    alternate["participants"].reverse()
    alternate["participants"][1]["message_traffic"]["sent_to"][0]["payload_bytes"] = "1073741824.0"

    assert render_job_resources(alternate) == render_job_resources(summary)


def test_study_mig_column_is_shown_only_when_an_included_job_reports_mig():
    participant = _participant()
    job_totals = derive_job_totals(_job_summary(participant)["participants"])
    study = {
        "selection": {"study_name": "default"},
        "coverage": {
            "selected_jobs": "1",
            "included_jobs": "1",
            "unavailable_jobs": "0",
            "nonterminal_jobs": "0",
        },
        "jobs": [
            {
                "job_id": "job-1",
                "job_name": "hello-pt",
                "job_status": "FINISHED_COMPLETED",
                "resource_data": "included",
                "totals": job_totals,
            }
        ],
        "totals": job_totals,
    }

    initial_output = render_study_resources(study)
    assert "JOB ID" in initial_output
    assert "NAME" in initial_output
    assert "hello-pt" in initial_output
    assert "GPU BASIS" not in initial_output
    assert "Derived capacity-time totals" in initial_output
    assert "CUDA DEVICE-h" in initial_output
    assert "CPU USED core-h" in initial_output
    assert "0.5000" in initial_output
    assert "MIG instance-h" not in initial_output
    assert "RUN-DIR FILES" not in initial_output
    assert "MESSAGE PAYLOAD SENT" not in initial_output
    assert "QUALITY" not in initial_output
    assert "RESOURCE DATA" not in initial_output
    assert "CPU CONSUMED STATUS" not in initial_output

    mig_group = {
        "kind": "mig_compute_instance",
        "instance_seconds": "3600",
        "model": "NVIDIA H100 MIG 1g.10gb",
    }
    job_totals["resource_time"]["gpu"]["groups"].append(mig_group)

    output = render_study_resources(study)
    assert "MIG instance-h" in output
    assert "MIG instances visible 1.0000 instance-h" in output
    assert "CUDA devices available 3.0000 device-h" in output

    job_totals["message_traffic"] = {
        "status": "partial",
        "sent": {"payload_bytes": str(5 * 2**30), "messages": "10"},
    }
    output = render_study_resources(study)
    assert "PAYLOAD SENT GiB" in output
    assert "5.0000*" in output
    assert "MESSAGE TRAFFIC STATUS" not in output


def test_cpu_consumed_job_and_study_cli_reconcile_without_changing_capacity_time():
    first = _job_summary(_participant())
    second_participant = _participant()
    second_participant["cpu_consumed"] = {"seconds": "900", "measured_seconds": "3600"}
    second = _job_summary(second_participant)
    job_totals = [derive_job_totals(summary["participants"]) for summary in (first, second)]
    assert [total["cpu_consumed"]["seconds"] for total in job_totals] == ["1800", "900"]

    jobs = [
        {
            "job_id": f"job-{index}",
            "job_name": f"run-{index}",
            "job_status": "FINISHED:COMPLETED",
            "resource_data": "included",
            "totals": total,
        }
        for index, total in enumerate(job_totals, 1)
    ]
    study_totals = derive_study_totals(jobs)
    assert study_totals["cpu_consumed"] == {"seconds": "2700", "measured_seconds": "7200"}
    assert study_totals["resource_time"]["cpu"]["groups"][0]["unit_seconds"] == "57600"

    study = {
        "selection": {"study_name": "default"},
        "coverage": {"selected_jobs": "2", "included_jobs": "2", "unavailable_jobs": "0", "nonterminal_jobs": "0"},
        "jobs": jobs,
        "totals": study_totals,
    }
    output = render_study_resources(study)
    assert "CPU time used 0.7500 core-h" in output
    assert "CPU visible 16.0000 core-h" in output


@pytest.mark.parametrize(
    "name, displayed",
    [
        ("肺部训练 — étude 🚀", "肺部训练 — étude 🚀"),
        ("name\nnext\r\t\x1b[2J", r"name\nnext\r\t\x1b[2J"),
        ("name\x7f\x9b\u202e\u2028\u2066", r"name\x7f\x9b\u202e\u2028\u2066"),
    ],
)
def test_human_output_escapes_terminal_controls_without_changing_query_names(name, displayed):
    summary = _job_summary(_participant())
    row = {
        "job_id": "job-1",
        "job_name": name,
        "job_status": "FINISHED:COMPLETED",
        "resource_data": "included",
        "totals": derive_job_totals(summary["participants"]),
    }
    study = {
        "selection": {"study_name": "default"},
        "coverage": {"selected_jobs": "1", "included_jobs": "1", "unavailable_jobs": "0", "nonterminal_jobs": "0"},
        "jobs": [row],
        "totals": derive_study_totals([row]),
    }

    job_output = render_job_resources(summary, job_name=name)
    study_output = render_study_resources(study)

    assert displayed in job_output
    assert displayed in study_output
    assert "\x1b" not in job_output + study_output
    assert "\u202e" not in job_output + study_output
    assert row["job_name"] == name


def test_unknown_job_status_is_not_described_as_running():
    row = {"job_id": "job-1", "job_name": "job", "job_status": "UNKNOWN", "resource_data": "nonterminal"}
    study = {
        "selection": {"study_name": "default"},
        "coverage": {"selected_jobs": "1", "included_jobs": "0", "unavailable_jobs": "0", "nonterminal_jobs": "1"},
        "jobs": [row],
        "totals": derive_study_totals([row]),
    }

    output = render_study_resources(study)

    assert "not finalized (excluded)" in output
    assert "still running" not in output
