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

"""Generate clearly synthetic schema 3 examples through production code.

No captured run or earlier prototype golden is read, converted, or overwritten.
``--check`` rebuilds outputs in memory and detects drift without writing.
"""

from __future__ import annotations

import argparse
import copy
import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from nvflare.private.fed.resource_stats import contract
from nvflare.private.fed.resource_stats.archive_reader import WorkspaceResourceStatsReader
from nvflare.tool.job.job_resources import render_job_resources, render_study_resources

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden" / "v3"
AT = "2026-10-12T12:00:00Z"
GIB = 1024**3


def participant(name="site-1", job_id="synthetic-capacity-normal"):
    return {
        "schema_version": "3.0",
        "kind": contract.KIND_PARTICIPANT_SUMMARY,
        "job_id": job_id,
        "participant_name": name,
        "reported_at": AT,
        "resource_capacity": {
            "measured_seconds": "600",
            "cpu": {"groups": [{"units": "32", "model": "AMD EPYC 9654", "architecture": "x86_64"}]},
            "memory": {"bytes": str(64 * GIB)},
            "gpu": {
                "groups": [{"kind": "full_gpu", "count": "2", "model": "NVIDIA A100", "memory_bytes": str(80 * GIB)}]
            },
        },
        "cpu_consumed": {"seconds": "180", "measured_seconds": "600"},
        "workspace_filesystem": {"capacity_bytes": str(1024 * GIB)},
        "retained_content": {"bytes": "0"},
        "message_traffic": {"sent_bytes": str(GIB), "received_bytes": str(2 * GIB)},
    }


def server(job_id="synthetic-capacity-normal"):
    value = participant("server", job_id)
    value["resource_capacity"].update(
        measured_seconds="610",
        cpu={"groups": [{"units": "8"}]},
        memory={"bytes": str(16 * GIB)},
        gpu={"groups": []},
    )
    value["cpu_consumed"] = {"seconds": "120", "measured_seconds": "610"}
    value["retained_content"] = {"bytes": str(64 * 1024**2)}
    value["message_traffic"] = {"sent_bytes": str(2 * GIB), "received_bytes": str(GIB)}
    return value


def entry(record):
    return {
        "participant_name": record["participant_name"],
        "role": "server" if record["participant_name"] == "server" else "client",
        "received_at": AT,
        **contract.participant_measurements(record),
    }


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
    partial = participant("site-2")
    partial["resource_capacity"].pop("gpu")
    partial["resource_capacity"].update(status="partial", issues=["observation_incomplete"])
    partial["cpu_consumed"].update(status="partial", issues=["attribution_incomplete"])
    fallback = participant(job_id="synthetic-capacity-fallback")
    fallback["resource_capacity"].update(status="partial", issues=["observation_incomplete"])
    fallback["message_traffic"] = {"sent_bytes": "0", "received_bytes": "0"}
    unavailable = participant(job_id="synthetic-capacity-unavailable")
    unavailable["resource_capacity"] = {"status": "unavailable", "issues": ["unsupported"]}
    unavailable["message_traffic"] = {"sent_bytes": "0", "received_bytes": "0"}
    changed = participant(job_id="synthetic-capacity-changes")
    first = copy.deepcopy(changed["resource_capacity"])
    first["measured_seconds"] = "300"
    second = copy.deepcopy(first)
    second["cpu"]["groups"][0]["units"] = "16"
    second["memory"]["bytes"] = str(32 * GIB)
    second["gpu"]["groups"][0]["count"] = "1"
    changed["resource_capacity"] = {"measured_seconds": "600", "intervals": [first, second]}
    changed["message_traffic"] = {"sent_bytes": "0", "received_bytes": "0"}
    large = participant(job_id="synthetic-capacity-large")
    large["resource_capacity"].update(
        measured_seconds="9007199254740993",
        cpu={"groups": [{"units": "1048576"}]},
        memory={"bytes": str(contract.U64_MAX)},
        gpu={"groups": [{"kind": "cuda_device_unclassified", "count": "4096"}]},
    )
    large["cpu_consumed"] = {"seconds": "9007199254740993", "measured_seconds": "9007199254740993"}
    large["retained_content"] = {"bytes": str(2**64 + 1)}
    large["message_traffic"] = {"sent_bytes": "0", "received_bytes": "0"}
    records = {
        "participant_summary": normal,
        "participant_summary_server": normal_server,
        "participant_summary_partial": partial,
        "participant_summary_fallback": fallback,
        "participant_summary_unavailable": unavailable,
        "participant_summary_changes": changed,
        "participant_summary_large_value": large,
    }
    summaries = {}
    for label, members, missing in (
        ("resource_summary", [normal, normal_server], False),
        ("resource_summary_partial", [normal, partial, normal_server], False),
        ("resource_summary_fallback", [fallback], False),
        ("resource_summary_missing", [normal, normal_server], True),
        ("resource_summary_unavailable", [unavailable], False),
        ("resource_summary_changes", [changed], False),
        ("resource_summary_large_value", [large], False),
    ):
        summaries[label], _bodies = archive_read(members, missing=missing)
    second_job = participant(job_id="synthetic-capacity-second-job")
    second_job["resource_capacity"].update(
        measured_seconds="300", cpu={"groups": [{"units": "16"}]}, memory={"bytes": str(32 * GIB)}
    )
    second_job["cpu_consumed"] = {"seconds": "90", "measured_seconds": "300"}
    second_server = server(job_id=second_job["job_id"])
    second_server["resource_capacity"]["measured_seconds"] = "310"
    second_server["cpu_consumed"] = {"seconds": "60", "measured_seconds": "310"}
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
        "schema_version": "3.0",
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
            raise SystemExit("Synthetic schema 3 examples differ: " + ", ".join(mismatches))
    else:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for name, data in outputs.items():
            (GOLDEN / name).write_bytes(data)
    print(f"{'Checked' if args.check else 'Generated'} {len(outputs)} synthetic schema 3 JSON/CLI examples")


if __name__ == "__main__":
    main()
