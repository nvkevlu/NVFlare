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

"""Generate clearly synthetic schema 1.0 examples through production code.

``--check`` rebuilds outputs in memory and detects drift without writing.
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from nvflare.private.fed.resource_stats import contract
from nvflare.private.fed.resource_stats.archive_reader import WorkspaceResourceStatsReader
from nvflare.tool.resources.resources_output import render_job_resources, render_study_resources

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "tests/unit_test/private/fed/resource_stats/data/golden/v1"
PUBLIC = ROOT / "docs/user_guide/admin_guide/resource_statistics/examples"
AT = "2026-10-29T12:00:00Z"
GIB = 1024**3


def participant(name="site-1", job_id="synthetic-capacity-normal"):
    return {
        "duration_seconds": "600",
        "schema_version": contract.SCHEMA_VERSION,
        "kind": contract.KIND_PARTICIPANT_SUMMARY,
        "job_id": job_id,
        "participant_name": name,
        "reported_at": AT,
        "resource_capacity": {
            "cpu": {"groups": [{"units": "32", "model": "AMD EPYC 9654", "architecture": "x86_64"}]},
            "memory": {"bytes": str(64 * GIB)},
            "gpu": {
                "groups": [{"kind": "full_gpu", "count": "2", "model": "NVIDIA A100", "memory_bytes": str(80 * GIB)}]
            },
        },
        "workspace_filesystem": {"capacity_bytes": str(1024 * GIB)},
        "resource_utilization": {
            "cpu_consumed": {"cpu_seconds": "180"},
            "retained_content": {"bytes": "0"},
            "message_traffic": {"sent_bytes": str(GIB), "received_bytes": str(2 * GIB)},
        },
    }


def server(job_id="synthetic-capacity-normal"):
    value = participant("server", job_id)
    value["duration_seconds"] = "610"
    value["resource_capacity"].update(
        cpu={"groups": [{"units": "8"}]},
        memory={"bytes": str(16 * GIB)},
        gpu={"groups": []},
    )
    value["resource_utilization"]["cpu_consumed"] = {"cpu_seconds": "120"}
    value["resource_utilization"]["retained_content"] = {"bytes": str(64 * 1024**2)}
    value["resource_utilization"]["message_traffic"] = {"sent_bytes": str(2 * GIB), "received_bytes": str(GIB)}
    return value


def entry(record):
    if "resource_time" not in record:
        record["resource_time"] = contract.capacity_to_resource_time(
            record["resource_capacity"], record.get("duration_seconds")
        )
    return {
        "participant_name": record["participant_name"],
        "role": "server" if record["participant_name"] == "server" else "client",
        "received_at": AT,
        **contract.participant_measurements(record),
    }


def task_participant():
    value = participant(job_id="synthetic-task-rollup")
    value["duration_seconds"] = "60"
    value["resource_capacity"] = {
        "cpu": {"groups": [{"units": "2"}]},
        "memory": {"bytes": str(2 * GIB)},
        "gpu": {"groups": []},
    }
    worker = {
        **value["resource_capacity"],
        "gpu": {"groups": [{"kind": "cuda_device_unclassified", "count": "1"}]},
    }
    value["resource_time"] = contract.aggregate_resource_time(
        [contract.capacity_to_resource_time(value["resource_capacity"], "60")]
        + [contract.capacity_to_resource_time(worker, duration) for duration in ("10", "5")]
    )
    value["resource_utilization"]["cpu_consumed"] = {"cpu_seconds": "14"}
    return value


def summary(records, *, missing=False):
    entries = [entry(record) for record in records]
    if missing:
        entries.append({"participant_name": "site-3", "role": "client", "status": "missing"})
    value = {
        "schema_version": records[0]["schema_version"],
        "kind": contract.KIND_RESOURCE_SUMMARY,
        "job_id": records[0]["job_id"],
        "participants": entries,
    }
    return contract.normalize_record(value)


def archive_read(records, *, missing=False):
    """Exercise production exact bundle validation, serializer, and ZIP reader."""
    value = summary(records, missing=missing)
    bodies = {record["participant_name"]: record for record in records}
    files = {f"participants/{name}.json": contract.canonical_json_bytes(record) for name, record in bodies.items()}
    files["resource_summary.json"] = contract.canonical_json_bytes(value)
    contract.validate_bundle(value, bodies, files)
    stream = io.BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr("resource_stats/" + name, data)
    reader = WorkspaceResourceStatsReader(stream.getvalue())
    decoded = reader.read_resource_summary()
    decoded_records = {name: reader.read_participant_summary(name) for name in bodies}
    return decoded, decoded_records


def examples():
    normal, normal_server = participant(), server()
    task = task_participant()
    partial = participant("site-2")
    partial["resource_capacity"].pop("gpu")
    partial["resource_capacity"].update(status="partial", issues=["observation_incomplete"])
    partial["resource_utilization"]["cpu_consumed"].update(status="partial", issues=["attribution_incomplete"])
    fallback = participant(job_id="synthetic-capacity-fallback")
    fallback["resource_capacity"].update(status="partial", issues=["observation_incomplete"])
    fallback["resource_utilization"]["message_traffic"] = {"sent_bytes": "0", "received_bytes": "0"}
    unavailable = participant(job_id="synthetic-capacity-unavailable")
    unavailable["resource_capacity"] = {"status": "unavailable", "issues": ["unsupported"]}
    unavailable["resource_utilization"]["message_traffic"] = {"sent_bytes": "0", "received_bytes": "0"}
    large = participant(job_id="synthetic-capacity-large")
    large["duration_seconds"] = "9007199254740993"
    large["resource_capacity"].update(
        cpu={"groups": [{"units": "1048576"}]},
        memory={"bytes": str(contract.U64_MAX)},
        gpu={"groups": [{"kind": "cuda_device_unclassified", "count": "4096"}]},
    )
    large["resource_utilization"]["cpu_consumed"] = {"cpu_seconds": "9007199254740993"}
    large["resource_utilization"]["retained_content"] = {"bytes": str(2**64 + 1)}
    large["resource_utilization"]["message_traffic"] = {"sent_bytes": "0", "received_bytes": "0"}
    records = {
        "participant_summary": normal,
        "participant_summary_server": normal_server,
        "participant_summary_partial": partial,
        "participant_summary_fallback": fallback,
        "participant_summary_unavailable": unavailable,
        "participant_summary_large_value": large,
        "participant_summary_task": task,
    }
    summaries = {}
    for label, members, missing in (
        ("resource_summary", [normal, normal_server], False),
        ("resource_summary_partial", [normal, partial, normal_server], False),
        ("resource_summary_fallback", [fallback], False),
        ("resource_summary_missing", [normal, normal_server], True),
        ("resource_summary_unavailable", [unavailable], False),
        ("resource_summary_large_value", [large], False),
        ("resource_summary_task", [task], False),
    ):
        summaries[label], _bodies = archive_read(members, missing=missing)
    second_job = participant(job_id="synthetic-capacity-second-job")
    second_job["duration_seconds"] = "300"
    second_job["resource_capacity"].update(cpu={"groups": [{"units": "16"}]}, memory={"bytes": str(32 * GIB)})
    second_job["resource_utilization"]["cpu_consumed"] = {"cpu_seconds": "90"}
    second_server = server(job_id=second_job["job_id"])
    second_server["duration_seconds"] = "310"
    second_server["resource_utilization"]["cpu_consumed"] = {"cpu_seconds": "60"}
    second_summary, _ = archive_read([second_job, second_server])
    rows = []
    for value in [summaries["resource_summary"], second_summary]:
        rows.append(
            {
                "job_id": value["job_id"],
                "job_name": "Synthetic capacity contract example",
                "job_status": "FINISHED:COMPLETED",
                "resource_data": "included",
                "totals": contract.derive_job_totals(value["participants"]),
            }
        )
    rows.extend(
        [
            {
                "job_id": "synthetic-no-resource-archive",
                "job_name": "Synthetic missing archive",
                "job_status": "FINISHED:COMPLETED",
                "resource_data": "unavailable",
            },
            {
                "job_id": "synthetic-running",
                "job_name": "Synthetic running job",
                "job_status": "RUNNING",
                "resource_data": "nonterminal",
            },
        ]
    )
    study = {
        "schema_version": contract.SCHEMA_VERSION,
        "kind": contract.KIND_STUDY_SUMMARY,
        "selection": {"study_name": "synthetic-capacity-examples"},
        "generated_at": AT,
        "coverage": {"selected_jobs": "4", "included_jobs": "2", "unavailable_jobs": "1", "nonterminal_jobs": "1"},
        "jobs": rows,
        "totals": contract.derive_study_totals(rows),
    }
    records.update(summaries)
    records["study_summary"] = study
    outputs = {}
    for name, record in records.items():
        contract.validate_record(record)
        outputs[name + ".json"] = contract.canonical_json_bytes(record)
    for name, value in summaries.items():
        outputs[name + ".txt"] = (
            render_job_resources(value, job_name="Synthetic capacity contract example") + "\n"
        ).encode()
    outputs["participant_summary.txt"] = (
        render_job_resources(summaries["resource_summary"], normal, job_name="Synthetic capacity contract example")
        + "\n"
    ).encode()
    outputs["study_summary.txt"] = (render_study_resources(study) + "\n").encode()
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = examples()
    if args.check:
        mismatches = [
            name
            for name, data in outputs.items()
            if not (GOLDEN / name).is_file() or (GOLDEN / name).read_bytes() != data
        ]
        if mismatches:
            raise SystemExit("Synthetic schema 1.0 examples differ: " + ", ".join(mismatches))
    else:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for name, data in outputs.items():
            (GOLDEN / name).write_bytes(data)
    public = {
        "participant_summary.json": outputs["participant_summary.json"],
        "resource_summary.json": outputs["resource_summary.json"],
        "job_resources.out": outputs["resource_summary.txt"],
        "study_resources.out": outputs["study_summary.txt"],
    }
    for name, data in public.items():
        if args.check:
            if not (PUBLIC / name).is_file() or (PUBLIC / name).read_bytes() != data:
                raise SystemExit("Public example differs: " + name)
        else:
            (PUBLIC / name).write_bytes(data)
    print(f"{'Checked' if args.check else 'Generated'} {len(outputs)} synthetic schema 1.0 JSON/CLI examples")


if __name__ == "__main__":
    main()
