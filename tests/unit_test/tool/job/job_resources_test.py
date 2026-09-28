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

from nvflare.private.fed.resource_stats.contract import derive_job_totals
from nvflare.tool.job.job_resources import render_job_resources, render_study_resources


def _participant():
    return {
        "participant_name": "site-1",
        "role": "client",
        "status": "accepted",
        "resource_time": {
            "status": "reported",
            "measured_seconds": "3600",
            "cpu": {"groups": [{"unit_seconds": "28800", "model": "AMD EPYC 9654"}]},
            "memory": {"byte_seconds": str(64 * 2**30 * 3600)},
            "gpu": {
                "groups": [
                    {
                        "kind": "full_gpu",
                        "instance_seconds": "7200",
                        "model": "NVIDIA H100 80GB HBM3",
                    }
                ]
            },
        },
        "retained_content": {"status": "unavailable", "issues": ["not_bound"]},
        "message_traffic": {"status": "unavailable", "issues": ["not_bound"]},
        "workspace_filesystem": {"status": "reported", "capacity_bytes": str(2 * 2**40)},
    }


def _job_summary(participant):
    return {
        "job_id": "job-1",
        "participants": [
            {
                "participant_name": participant["participant_name"],
                "role": participant["role"],
                "status": participant["status"],
                "received_at": "2026-09-17T12:00:00Z",
                "resource_time": participant["resource_time"],
                "retained_content": participant["retained_content"],
                "message_traffic": participant["message_traffic"],
            }
        ],
    }


def _with_missing_server(summary):
    summary["participants"].append({"participant_name": "server", "role": "server", "status": "missing"})
    return summary


def test_mig_column_is_hidden_when_no_participant_reports_mig():
    participant = _participant()

    output = render_job_resources(_job_summary(participant), job_name="hello-pt")

    assert output.startswith("Recorded resources for job hello-pt (ID: job-1).")
    assert "Recorded average visible capacity over each measured interval" in output
    assert "CPU UNITS" in output
    assert "MEM GiB" in output
    assert "FULL GPUs" in output
    assert "MIG INSTANCES" not in output
    assert "8.0000" in output
    assert "64.0000" in output
    assert "2.0000" in output
    assert "RUN-DIR FILES" not in output
    assert "MESSAGE PAYLOAD SENT" not in output
    assert "CPU 8.0000 unit h" in output
    assert "MEMORY 64.0000 GiB h" in output
    assert "FULL GPUs 2.0000 instance h" in output


def test_job_header_falls_back_to_id_when_name_metadata_is_not_supplied():
    output = render_job_resources(_job_summary(_participant()))
    assert output.startswith("Recorded resources for job ID job-1.")


def test_mig_column_and_site_detail_are_shown_only_when_applicable():
    participant = _participant()
    participant["resource_time"]["gpu"]["groups"].append(
        {
            "kind": "mig_compute_instance",
            "instance_seconds": "3600",
            "model": "NVIDIA H100 MIG 1g.10gb",
            "mig_profile": "1g.10gb",
        }
    )
    summary = _job_summary(participant)

    job_output = render_job_resources(summary)
    site_output = render_job_resources(summary, participant)

    assert "MIG INSTANCES" in job_output
    assert "1.0000" in job_output
    assert "MIG compute instance: NVIDIA H100 MIG 1g.10gb (1g.10gb)" in site_output
    assert "1.0000 average visible instances" in site_output


def test_run_directory_files_and_message_traffic_columns_are_only_shown_when_bound():
    participant = _participant()
    summary = _job_summary(participant)

    assert "Other recorded participant totals" not in render_job_resources(summary)

    participant["retained_content"] = {"status": "reported", "bytes": str(3 * 2**30)}
    participant["message_traffic"] = {
        "status": "partial",
        "issues": ["counter_gap"],
        "sent_to": [{"participant_name": "server", "payload_bytes": str(5 * 2**30), "messages": "10"}],
    }
    summary = _with_missing_server(_job_summary(participant))
    output = render_job_resources(summary)

    assert "Other recorded participant totals" in output
    assert "RUN-DIR FILES GiB" in output
    assert "RUN-DIR STATUS" in output
    assert "MESSAGE TRAFFIC STATUS" in output
    assert "PARTIAL" in output
    assert "MESSAGE PAYLOAD SENT GiB" in output
    assert "MESSAGE PAYLOAD SENT TO SITE GiB" in output
    assert "RUN-DIR FILES 3.0000 GiB" in output
    assert "RUN-DIR STATUS PARTIAL" in output
    assert "MESSAGE TRAFFIC STATUS PARTIAL" in output
    assert "MESSAGE PAYLOAD SENT 5.0000 GiB" in output

    participant["retained_content"] = {
        "status": "partial",
        "issues": ["observation_incomplete"],
        "bytes": str(2 * 2**30),
    }
    partial_output = render_job_resources(_with_missing_server(_job_summary(participant)))
    assert "RUN-DIR STATUS PARTIAL" in partial_output


def test_sender_confirmed_inbound_remains_visible_when_destination_report_is_missing():
    site = _participant()
    site["message_traffic"] = {
        "status": "reported",
        "sent_to": [{"participant_name": "server", "payload_bytes": str(2**30), "messages": "2"}],
    }
    summary = _with_missing_server(_job_summary(site))

    output = render_job_resources(summary)
    server_row = next(line for line in output.splitlines() if line.startswith("server") and "1.0000" in line)
    assert "N/A" in server_row
    assert "1.0000" in server_row
    assert "sender-confirmed" in output


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
    assert "MIG h" not in initial_output
    assert "RUN-DIR FILES" not in initial_output
    assert "MESSAGE PAYLOAD SENT" not in initial_output

    mig_group = {
        "kind": "mig_compute_instance",
        "instance_seconds": "3600",
        "model": "NVIDIA H100 MIG 1g.10gb",
    }
    job_totals["resource_time"]["gpu"]["groups"].append(mig_group)

    output = render_study_resources(study)
    assert "MIG h" in output
    assert "MIG INSTANCES 1.0000 instance h" in output

    job_totals["message_traffic"] = {
        "status": "partial",
        "sent": {"payload_bytes": str(5 * 2**30), "messages": "10"},
    }
    output = render_study_resources(study)
    assert "MESSAGE TRAFFIC STATUS" in output
    assert "MESSAGE TRAFFIC STATUS PARTIAL" in output
    assert "MESSAGE PAYLOAD SENT 5.0000 GiB" in output
