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

"""Generate deterministic schema-v1 records, archives, and CLI examples.

The records model one moderately sized 14B-model job and one additional
completed job used by the study view. Each participant has exactly one terminal
report. The resource-time values are final accumulator outputs; private
observation intervals are intentionally absent.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from typing import Any
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from contract_v1 import (
    KIND_PARTICIPANT_SUMMARY,
    KIND_RESOURCE_SUMMARY,
    KIND_STUDY_SUMMARY,
    derive_job_totals,
    derive_study_totals,
    load_and_validate,
    validate_bundle,
)

from nvflare.tool.job.job_resources import render_job_resources, render_study_resources

SCHEMA_ROOT = Path(__file__).resolve().parent
GOLDEN_ROOT = SCHEMA_ROOT / "golden" / "v1"
DEFAULT_OUTPUT = GOLDEN_ROOT / "finalized_job"
JOB_ID = "job-20260909-001"
JOB_NAME = "qwen2.5-14b-federated-qualification"
STUDY_JOB_ID = "job-20260910-002"
STUDY_JOB_NAME = "qwen2.5-14b-h100-qualification"
STUDY_NAME = "cancer-research"
SITE_1_NAME = "site-1"
SITE_2_NAME = "site-2"
SITE_3_NAME = "site-3"
SERVER_NAME = "server"
STUDY_SITE_NAME = "site-4"
CLIENT_F3_BYTES = "147700336640"
RUN_DIR_FILE_BYTES = "29540266113"


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_workspace_archive(path: Path, members: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w", compression=ZIP_STORED) as archive:
        ordered = sorted(members.items(), key=lambda item: (item[0].endswith("/resource_summary.json"), item[0]))
        for member_name, data in ordered:
            info = ZipInfo(member_name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)


def _counter(payload_bytes: str = "0", messages: str = "0") -> dict[str, str]:
    return {"payload_bytes": payload_bytes, "messages": messages}


def _f3(
    *,
    sent_to: tuple[tuple[str, str, str], ...] = (),
) -> dict[str, Any]:
    return {
        "sent_to": [
            {"participant_name": name, **_counter(payload_bytes, messages)} for name, payload_bytes, messages in sent_to
        ],
    }


def _participant(
    *,
    job_id: str,
    participant_name: str,
    reported_at: str,
    resource_time: dict[str, Any],
    cpu_consumed: dict[str, Any],
    workspace_capacity_bytes: str,
    retained_content: dict[str, Any],
    f3: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "kind": KIND_PARTICIPANT_SUMMARY,
        "job_id": job_id,
        "participant_name": participant_name,
        "reported_at": reported_at,
        "resource_time": resource_time,
        "cpu_consumed": cpu_consumed,
        "workspace_filesystem": {
            "capacity_bytes": workspace_capacity_bytes,
        },
        "retained_content": retained_content,
        "message_traffic": f3,
    }


def _main_participant() -> dict[str, Any]:
    return _participant(
        job_id=JOB_ID,
        participant_name=SITE_1_NAME,
        reported_at="2026-09-09T14:37:03Z",
        resource_time={
            "measured_seconds": "2223",
            "cpu": {
                "groups": [
                    {
                        "unit_seconds": "71136",
                        "model": "AMD EPYC 9654",
                        "architecture": "x86_64",
                    }
                ]
            },
            "memory": {"byte_seconds": "458290190352384"},
            "gpu": {
                "groups": [
                    {
                        "kind": "full_gpu",
                        "instance_seconds": "8892",
                        "model": "NVIDIA A100 80GB",
                        "memory_bytes": "85899345920",
                    }
                ]
            },
        },
        cpu_consumed={"seconds": "1800"},
        workspace_capacity_bytes="1099511627776",
        retained_content={"bytes": "0"},
        f3=_f3(sent_to=((SERVER_NAME, CLIENT_F3_BYTES, "5"),)),
    )


def _partial_participant() -> dict[str, Any]:
    return _participant(
        job_id=JOB_ID,
        participant_name=SITE_2_NAME,
        reported_at="2026-09-09T14:37:03Z",
        resource_time={
            "status": "partial",
            "issues": ["observation_incomplete"],
            "measured_seconds": "1923",
            "cpu": {
                "groups": [
                    {
                        "unit_seconds": "56736",
                        "model": "Intel Xeon Platinum 8480+",
                        "architecture": "x86_64",
                    }
                ]
            },
            "memory": {"byte_seconds": "375826818269184"},
            "gpu": {
                "groups": [
                    {
                        "kind": "full_gpu",
                        "instance_seconds": "7092",
                        "model": "NVIDIA A100 80GB",
                        "memory_bytes": "85899345920",
                    }
                ]
            },
        },
        cpu_consumed={"status": "partial", "issues": ["observation_incomplete"], "seconds": "900"},
        workspace_capacity_bytes="2199023255552",
        retained_content={
            "status": "unavailable",
            "issues": ["not_bound"],
        },
        f3=_f3(sent_to=((SERVER_NAME, CLIENT_F3_BYTES, "5"),)),
    )


def _server_participant() -> dict[str, Any]:
    return _participant(
        job_id=JOB_ID,
        participant_name=SERVER_NAME,
        reported_at="2026-09-09T14:37:03Z",
        resource_time={
            "measured_seconds": "2223",
            "cpu": {
                "groups": [
                    {
                        "unit_seconds": "17784",
                        "model": "AMD EPYC 9654",
                        "architecture": "x86_64",
                    }
                ]
            },
            "memory": {"byte_seconds": "152763396784128"},
            "gpu": {"groups": []},
        },
        cpu_consumed={"seconds": "360"},
        workspace_capacity_bytes="1099511627776",
        retained_content={"bytes": RUN_DIR_FILE_BYTES},
        f3=_f3(
            sent_to=(
                (SITE_1_NAME, CLIENT_F3_BYTES, "5"),
                (SITE_2_NAME, CLIENT_F3_BYTES, "5"),
            )
        ),
    )


def _study_job_participant() -> dict[str, Any]:
    return _participant(
        job_id=STUDY_JOB_ID,
        participant_name=STUDY_SITE_NAME,
        reported_at="2026-09-10T18:00:00Z",
        resource_time={
            "measured_seconds": "14400",
            "cpu": {
                "groups": [
                    {
                        "unit_seconds": "1843200",
                        "model": "AMD EPYC 9654",
                        "architecture": "x86_64",
                    }
                ]
            },
            "memory": {"byte_seconds": "7916483719987200"},
            "gpu": {
                "groups": [
                    {
                        "kind": "full_gpu",
                        "instance_seconds": "115200",
                        "model": "NVIDIA H100 80GB HBM3",
                        "memory_bytes": "85899345920",
                    }
                ]
            },
        },
        cpu_consumed={"seconds": "7200"},
        workspace_capacity_bytes="4398046511104",
        retained_content={"bytes": "59080532226"},
        f3=_f3(),
    )


def _large_participant() -> dict[str, Any]:
    return _participant(
        job_id="job-large-exactness",
        participant_name="site-large",
        reported_at="2026-09-09T00:15:01Z",
        resource_time={
            "measured_seconds": "901",
            "cpu": {
                "groups": [
                    {
                        "unit_seconds": "901",
                        "model": "AMD EPYC 9654",
                        "architecture": "x86_64",
                    }
                ]
            },
            "memory": {"byte_seconds": "9010000000000901"},
            "gpu": {"groups": []},
        },
        cpu_consumed={"status": "unavailable", "issues": ["observation_incomplete"]},
        workspace_capacity_bytes="10000000000001",
        retained_content={"bytes": "0"},
        f3=_f3(),
    )


def _accepted_entry(
    participant: dict[str, Any],
    *,
    participant_name: str,
    role: str,
    received_at: str,
) -> dict[str, Any]:
    return {
        "participant_name": participant_name,
        "role": role,
        "received_at": received_at,
        "resource_time": deepcopy(participant["resource_time"]),
        "cpu_consumed": deepcopy(participant["cpu_consumed"]),
        "retained_content": deepcopy(participant["retained_content"]),
        "message_traffic": deepcopy(participant["message_traffic"]),
    }


def _resource_summary(
    job_id: str,
    participants: list[dict[str, Any]],
) -> dict[str, Any]:
    participants.sort(key=lambda item: (item["role"], item["participant_name"]))
    return {
        "schema_version": "1.0",
        "kind": KIND_RESOURCE_SUMMARY,
        "job_id": job_id,
        "participants": participants,
    }


def _decimal_sum(groups: list[dict[str, Any]], field: str) -> Decimal:
    return sum((Decimal(group[field]) for group in groups), Decimal(0))


def _study_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows.sort(key=lambda row: row["job_id"])
    return {
        "schema_version": "1.0",
        "kind": KIND_STUDY_SUMMARY,
        "selection": {"study_name": STUDY_NAME},
        "generated_at": "2026-09-12T20:00:00Z",
        "coverage": {
            "selected_jobs": str(len(rows)),
            "included_jobs": str(sum(row["resource_data"] == "included" for row in rows)),
            "unavailable_jobs": str(sum(row["resource_data"] == "unavailable" for row in rows)),
            "nonterminal_jobs": str(sum(row["resource_data"] == "nonterminal" for row in rows)),
        },
        "jobs": rows,
        "totals": derive_study_totals(rows),
    }


def _workspace_members(
    summary_bytes: bytes,
    participant_files: dict[str, bytes],
) -> dict[str, bytes]:
    return {
        **{
            f"resource_stats/participants/{participant_name}.json": participant_bytes
            for participant_name, participant_bytes in participant_files.items()
        },
        "resource_stats/resource_summary.json": summary_bytes,
    }


def build(output_root: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    site_1 = _main_participant()
    site_2 = _partial_participant()
    server = _server_participant()
    accepted_records = {
        SITE_1_NAME: site_1,
        SITE_2_NAME: site_2,
        SERVER_NAME: server,
    }
    accepted_bytes = {key: _json_bytes(record) for key, record in accepted_records.items()}
    participants = [
        _accepted_entry(
            site_1,
            participant_name=SITE_1_NAME,
            role="client",
            received_at="2026-09-09T14:37:03.1Z",
        ),
        _accepted_entry(
            site_2,
            participant_name=SITE_2_NAME,
            role="client",
            received_at="2026-09-09T14:37:03.2Z",
        ),
        {
            "participant_name": SITE_3_NAME,
            "role": "client",
            "status": "missing",
        },
        _accepted_entry(
            server,
            participant_name=SERVER_NAME,
            role="server",
            received_at="2026-09-09T14:37:03.3Z",
        ),
    ]
    summary = _resource_summary(JOB_ID, participants)
    job_totals = derive_job_totals(summary["participants"])
    summary_bytes = _json_bytes(summary)

    study_participant = _study_job_participant()
    study_participant_bytes = _json_bytes(study_participant)
    study_entry = _accepted_entry(
        study_participant,
        participant_name=STUDY_SITE_NAME,
        role="client",
        received_at="2026-09-10T18:00:00.1Z",
    )
    study_job_summary = _resource_summary(STUDY_JOB_ID, [study_entry])
    study_job_summary_bytes = _json_bytes(study_job_summary)
    study_participant_files = {STUDY_SITE_NAME: study_participant_bytes}

    study = _study_summary(
        [
            {
                "job_id": JOB_ID,
                "job_name": JOB_NAME,
                "job_status": "FINISHED:COMPLETED",
                "resource_data": "included",
                "totals": deepcopy(job_totals),
            },
            {
                "job_id": STUDY_JOB_ID,
                "job_name": STUDY_JOB_NAME,
                "job_status": "FINISHED:COMPLETED",
                "resource_data": "included",
                "totals": derive_job_totals(study_job_summary["participants"]),
            },
            {
                "job_id": "job-20260911-003",
                "job_name": "qwen2.5-14b-followup",
                "job_status": "FINISHED:COMPLETED",
                "resource_data": "unavailable",
            },
            {
                "job_id": "job-20260912-004",
                "job_name": "qwen2.5-14b-evaluation",
                "job_status": "RUNNING",
                "resource_data": "nonterminal",
            },
        ]
    )

    large_participant = _large_participant()
    large_entry = _accepted_entry(
        large_participant,
        participant_name="site-large",
        role="client",
        received_at="2026-09-09T00:15:01.2Z",
    )
    large_summary = _resource_summary(large_participant["job_id"], [large_entry])
    large_totals = derive_job_totals(large_summary["participants"])

    records = {
        "participant_summary.json": site_1,
        "participant_summary_partial.json": site_2,
        "participant_summary_server.json": server,
        "participant_summary_study_job.json": study_participant,
        "participant_summary_large_value.json": large_participant,
        "resource_summary.json": summary,
        "resource_summary_study_job.json": study_job_summary,
        "resource_summary_large_value.json": large_summary,
        "study_summary.json": study,
    }
    encoded = {name: _json_bytes(record) for name, record in records.items()}
    for data in encoded.values():
        load_and_validate(data)
    validate_bundle(
        summary,
        accepted_records,
        {
            "resource_summary.json": summary_bytes,
            **{
                f"participants/{participant_name}.json": participant_bytes
                for participant_name, participant_bytes in accepted_bytes.items()
            },
        },
    )
    validate_bundle(
        study_job_summary,
        {STUDY_SITE_NAME: study_participant},
        {
            "resource_summary.json": study_job_summary_bytes,
            f"participants/{STUDY_SITE_NAME}.json": study_participant_bytes,
        },
    )
    for name, data in encoded.items():
        _write(GOLDEN_ROOT / name, data)

    resource_root = output_root / "server_run" / "resource_stats"
    for participant_name, participant_bytes in accepted_bytes.items():
        _write(resource_root / "participants" / f"{participant_name}.json", participant_bytes)
    _write(resource_root / "resource_summary.json", summary_bytes)

    workspace_archive = output_root / "job_store" / "jobs" / JOB_ID / "workspace"
    workspace_members = _workspace_members(summary_bytes, accepted_bytes)
    _write_workspace_archive(workspace_archive, workspace_members)

    study_workspace_archive = output_root / "job_store" / "jobs" / STUDY_JOB_ID / "workspace"
    study_workspace_members = _workspace_members(
        study_job_summary_bytes,
        study_participant_files,
    )
    _write_workspace_archive(study_workspace_archive, study_workspace_members)

    cli_json = {
        "schema_version": "1",
        "status": "ok",
        "exit_code": 0,
        "data": {
            "selection": {"job_id": JOB_ID, "site": "all"},
            "summary": summary,
        },
    }
    site_records = {
        SITE_1_NAME: site_1,
        SITE_2_NAME: site_2,
        SERVER_NAME: server,
    }
    _write(output_root / "cli" / "resources-all.json", _json_bytes(cli_json))
    _write(
        output_root / "cli" / "resources-all.txt",
        (render_job_resources(summary, job_name=JOB_NAME) + "\n").encode("utf-8"),
    )
    _write(
        output_root / "cli" / "resources-site-1-details.txt",
        (render_job_resources(summary, site_records[SITE_1_NAME], job_name=JOB_NAME) + "\n").encode("utf-8"),
    )
    _write(
        output_root / "cli" / "resources-site-2-details.txt",
        (render_job_resources(summary, site_records[SITE_2_NAME], job_name=JOB_NAME) + "\n").encode("utf-8"),
    )
    study_cli_json = {
        "schema_version": "1",
        "status": "ok",
        "exit_code": 0,
        "data": {
            "selection": {"study": STUDY_NAME},
            "summary": study,
        },
    }
    _write(output_root / "cli" / "resources-study.json", _json_bytes(study_cli_json))
    _write(output_root / "cli" / "resources-study.txt", (render_study_resources(study) + "\n").encode("utf-8"))

    with ZipFile(workspace_archive, "r") as archive:
        workspace_summary_matches = archive.read("resource_stats/resource_summary.json") == summary_bytes
    with ZipFile(study_workspace_archive, "r") as archive:
        study_workspace_summary_matches = (
            archive.read("resource_stats/resource_summary.json") == study_job_summary_bytes
        )

    receipt = {
        "generator": Path(__file__).name,
        "schema_version": "1.0",
        "job_id": JOB_ID,
        "job_name": JOB_NAME,
        "study": STUDY_NAME,
        "public_participant_reports": len(accepted_records),
        "public_start_or_final_fragments": 0,
        "workspace_component": workspace_archive.name,
        "workspace_resource_summary_member": "resource_stats/resource_summary.json",
        "workspace_resource_summary_matches": workspace_summary_matches,
        "study_job_workspace_resource_summary_matches": study_workspace_summary_matches,
        "scenario_basis": {
            "description": "Illustrative values scaled to completed Qwen2.5-14B qualification jobs.",
            "reference_label": "Five-round 14B full-model qualification, 2026-07-31",
            "scope_note": (
                "The A100 model, four-GPU baseline, runtime scale, and model-state size are evidence-based; "
                "CPU capacity, CPU consumed time, memory, run-directory file bytes, workspace-filesystem "
                "capacity, and observation changes are illustrative."
            ),
            "reference_runtime_seconds": "2223",
            "reference_model_state_bytes": "29540067328",
            "reference_logical_state_directions": "20",
            "reference_logical_state_bytes": "590801346560",
            "illustrative_run_directory_file_bytes": RUN_DIR_FILE_BYTES,
            "message_traffic_note": (
                "The historical run recorded model-state size; its logical volume was derived, and it did "
                "not measure sender-confirmed post-encoding message payloads."
            ),
        },
        "derived_examples": {
            "site_1_measured_seconds": site_1["resource_time"]["measured_seconds"],
            "site_2_measured_seconds": site_2["resource_time"]["measured_seconds"],
            "server_measured_seconds": server["resource_time"]["measured_seconds"],
            "accepted_measured_seconds": job_totals["resource_time"]["measured_seconds"],
            "job_cpu_unit_seconds": str(_decimal_sum(job_totals["resource_time"]["cpu"]["groups"], "unit_seconds")),
            "job_cpu_consumed_seconds": job_totals["cpu_consumed"]["seconds"],
            "job_gpu_instance_seconds": str(
                _decimal_sum(job_totals["resource_time"]["gpu"]["groups"], "instance_seconds")
            ),
            "study_cpu_unit_seconds": str(
                _decimal_sum(study["totals"]["resource_time"]["cpu"]["groups"], "unit_seconds")
            ),
            "study_cpu_consumed_seconds": study["totals"]["cpu_consumed"]["seconds"],
            "study_gpu_instance_seconds": str(
                _decimal_sum(study["totals"]["resource_time"]["gpu"]["groups"], "instance_seconds")
            ),
            "large_memory_byte_seconds": large_totals["resource_time"]["memory"]["byte_seconds"],
        },
    }
    _write(output_root / "generation_receipt.json", _json_bytes(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))


if __name__ == "__main__":
    main()
