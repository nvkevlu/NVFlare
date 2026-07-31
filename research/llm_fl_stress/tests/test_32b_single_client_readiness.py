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

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from research.llm_fl_stress.real_training.cs_oci_ord import validate_32b_single_client_readiness as readiness


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _marker(source: Path, marker: Path, protected: list[Path]) -> None:
    marker.write_text(f"{_sha256(source)}  {source}\n", encoding="utf-8")
    latest = max(path.stat().st_mtime_ns for path in [source, *protected])
    os.utime(marker, ns=(latest + 1_000_000, latest + 1_000_000))


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _build_fixture(tmp_path: Path) -> dict[str, Path | str]:
    project = tmp_path / "project"
    repo = project / "repos" / "NVFlare-runs" / "release"
    repo.mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "readiness@example.com")
    _git(repo, "config", "user.name", "Readiness Test")
    _git(repo, "config", "commit.gpgsign", "false")

    release = repo / "research" / "llm_fl_stress" / "real_training" / "QUALIFICATION_RELEASE"
    release.parent.mkdir(parents=True)
    release.write_text(readiness.EXPECTED_RELEASE + "\n", encoding="utf-8")
    dataset = release.parent / "data" / "site-1.jsonl"
    dataset.parent.mkdir(parents=True)
    dataset.write_text(
        "".join(
            json.dumps({"id": f"site-1-{index:03d}", "text": f"training record {index}"}) + "\n"
            for index in range(1, 49)
        ),
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "--detach", head)

    containers = project / "containers"
    containers.mkdir()
    image = containers / "pytorch-25.01-py3.sqsh"
    image.write_bytes(b"container payload is deliberately not read by readiness")
    checksum = Path(str(image) + ".sha256")
    checksum.write_text(f"{'1' * 64}  {image}\n", encoding="utf-8")
    container_marker = Path(str(checksum) + ".verified")
    _marker(checksum, container_marker, [image])

    env = project / "envs" / "nvflare-fsdp2"
    (env / "bin").mkdir(parents=True)
    python_target = env / "bin" / "python3"
    python_target.write_text("#!/bin/sh\n", encoding="utf-8")
    python_target.chmod(0o700)
    (env / "bin" / "python").symlink_to(python_target.name)
    (env / "requirements.lock").write_text(
        "torch==2.12.0+cu126\ntorchvision==0.27.0+cu126\ntransformers==4.57.6\n",
        encoding="utf-8",
    )

    model = project / "models" / readiness.MODEL_DIR
    model.mkdir(parents=True)
    revision = model / "REVISION"
    revision.write_text(readiness.MODEL_REVISION + "\n", encoding="utf-8")
    config = model / "config.json"
    _json(config, readiness.EXPECTED_CONFIG)
    index = model / "model.safetensors.index.json"
    shard_names = [
        f"model-{item:05d}-of-{readiness.SHARD_COUNT:05d}.safetensors" for item in range(1, readiness.SHARD_COUNT + 1)
    ]
    _json(
        index,
        {
            "metadata": {"total_size": readiness.LOGICAL_STATE_BYTES},
            "weight_map": {f"parameter.{item}": name for item, name in enumerate(shard_names)},
        },
    )
    protected = [revision, config, index]
    for name in shard_names:
        shard = model / name
        shard.write_bytes(name.encode())
        protected.append(shard)
    manifest = model / "MANIFEST.sha256"
    manifest.write_text(
        "".join(f"{_sha256(path)}  ./{path.name}\n" for path in protected),
        encoding="utf-8",
    )
    model_marker = model / "MANIFEST.sha256.verified"
    _marker(manifest, model_marker, protected)

    (project / "logs").mkdir()
    artifacts = project / "artifacts"
    artifacts.mkdir()
    static_result = artifacts / "32b-single-client-static.json"
    _json(
        static_result,
        {
            "event": "real_training_model_structure_preflight",
            "status": "PASS",
            "model_path": str(model),
            "model_revision": readiness.MODEL_REVISION,
            "config": readiness.EXPECTED_CONFIG,
            "parameter_count": readiness.PARAMETER_COUNT,
            "parameter_dtype": "bfloat16",
            "logical_state_payload_bytes": readiness.LOGICAL_STATE_BYTES,
            "physical_checkpoint_file_bytes": readiness.PHYSICAL_CHECKPOINT_BYTES,
            "tensor_payload_materialized": False,
            "gpu_required": False,
            "model_manifest_sha256": _sha256(manifest),
            "safetensor_structure": {
                "indexed_tensor_count": readiness.TENSOR_COUNT,
                "index_total_size_bytes": readiness.LOGICAL_STATE_BYTES,
                "computed_tensor_bytes": readiness.LOGICAL_STATE_BYTES,
                "validated_safetensor_files": shard_names,
                "validated_safetensor_file_count": readiness.SHARD_COUNT,
            },
            "dataset": {
                "path": str(dataset),
                "sha256": _sha256(dataset),
                "record_count": readiness.DATASET_RECORDS,
                "minimum_records": readiness.DATASET_RECORDS,
                "unique_ids": readiness.DATASET_RECORDS,
            },
        },
    )
    return {
        "project": project,
        "repo": repo,
        "head": head,
        "static_result": static_result,
        "image": image,
        "model": model,
        "manifest": manifest,
        "model_marker": model_marker,
    }


def _validate(fixture: dict[str, Path | str], **updates):
    arguments = {
        "repo_root": fixture["repo"],
        "expected_head": fixture["head"],
        "static_result": fixture["static_result"],
        "environ": {
            "PYTHONPATH": str(fixture["repo"]),
            "NVFLARE_EXPECTED_SOURCE_ROOT": str(fixture["repo"]),
        },
        "required_base_commit": fixture["head"],
    }
    arguments.update(updates)
    return readiness.validate_readiness(fixture["project"], **arguments)


def test_readiness_passes_and_emits_submission_bindings(tmp_path):
    fixture = _build_fixture(tmp_path)

    result = _validate(fixture)

    assert result["status"] == "PASS"
    assert result["safe_to_submit"] is True
    assert result["git_commit"] == fixture["head"]
    assert result["experiment_release"] == readiness.EXPERIMENT_RELEASE
    assert result["required_base_commit"] == fixture["head"]
    assert result["repo_root"] == str(fixture["repo"])
    assert result["pythonpath"] == str(fixture["repo"])
    assert result["nvflare_expected_source_root"] == str(fixture["repo"])
    assert result["model_manifest_sha256"] == _sha256(fixture["manifest"])
    assert result["container_manifest_sha256"] == _sha256(Path(str(fixture["image"]) + ".sha256"))
    assert result["static_result_sha256"] == _sha256(fixture["static_result"])


def test_readiness_allows_detached_clean_checkout(tmp_path):
    fixture = _build_fixture(tmp_path)

    result = _validate(fixture)

    assert result["branch"] == ""
    assert result["safe_to_submit"] is True


def test_readiness_rejects_non_release_worktree(tmp_path):
    fixture = _build_fixture(tmp_path)
    outside = fixture["project"] / "repos" / "NVFlare"
    _git(fixture["repo"], "worktree", "add", "--detach", str(outside), fixture["head"])

    with pytest.raises(readiness.ReadinessError, match="immutable worktree"):
        _validate(fixture, repo_root=outside)


@pytest.mark.parametrize("expected_head", ["b" * 40, "not-a-commit"])
def test_readiness_rejects_wrong_or_invalid_expected_head(tmp_path, expected_head):
    fixture = _build_fixture(tmp_path)

    with pytest.raises(readiness.ReadinessError, match="expected-head|repository HEAD"):
        _validate(fixture, expected_head=expected_head)


def test_readiness_rejects_missing_required_base_commit(tmp_path):
    fixture = _build_fixture(tmp_path)

    with pytest.raises(readiness.ReadinessError, match="does not contain required base commit"):
        _validate(fixture, required_base_commit="a" * 40)


def test_readiness_rejects_dirty_repository(tmp_path):
    fixture = _build_fixture(tmp_path)
    (fixture["repo"] / "untracked.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(readiness.ReadinessError, match="repository is dirty"):
        _validate(fixture)


@pytest.mark.parametrize(
    ("environment_name", "message"),
    [
        ("PYTHONPATH", "PYTHONPATH must equal"),
        ("NVFLARE_EXPECTED_SOURCE_ROOT", "NVFLARE_EXPECTED_SOURCE_ROOT must equal"),
    ],
)
def test_readiness_rejects_unbound_python_source(tmp_path, environment_name, message):
    fixture = _build_fixture(tmp_path)
    environment = {
        "PYTHONPATH": str(fixture["repo"]),
        "NVFLARE_EXPECTED_SOURCE_ROOT": str(fixture["repo"]),
    }
    environment[environment_name] = str(fixture["project"] / "repos" / "NVFlare")

    with pytest.raises(readiness.ReadinessError, match=message):
        _validate(fixture, environ=environment)


def test_readiness_rejects_container_changed_after_verification(tmp_path):
    fixture = _build_fixture(tmp_path)
    marker = Path(str(fixture["image"]) + ".sha256.verified")
    newer = marker.stat().st_mtime_ns + 1_000_000
    os.utime(fixture["image"], ns=(newer, newer))

    with pytest.raises(readiness.ReadinessError, match="container image or checksum changed"):
        _validate(fixture)


def test_readiness_rejects_model_file_changed_after_verification(tmp_path):
    fixture = _build_fixture(tmp_path)
    config = fixture["model"] / "config.json"
    newer = fixture["model_marker"].stat().st_mtime_ns + 1_000_000
    os.utime(config, ns=(newer, newer))

    with pytest.raises(readiness.ReadinessError, match="model file changed after verification"):
        _validate(fixture)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "FAIL", "static model preflight mismatch"),
        ("parameter_count", readiness.PARAMETER_COUNT - 1, "static model preflight mismatch"),
        ("model_manifest_sha256", "f" * 64, "model_manifest_sha256"),
        ("model_manifest_sha256", None, "model_manifest_sha256"),
    ],
)
def test_readiness_rejects_stale_or_inexact_static_result(tmp_path, field, value, message):
    fixture = _build_fixture(tmp_path)
    result = json.loads(fixture["static_result"].read_text(encoding="utf-8"))
    result[field] = value
    _json(fixture["static_result"], result)

    with pytest.raises(readiness.ReadinessError, match=message):
        _validate(fixture)


def test_readiness_rejects_inexact_dataset_evidence(tmp_path):
    fixture = _build_fixture(tmp_path)
    result = json.loads(fixture["static_result"].read_text(encoding="utf-8"))
    result["dataset"]["unique_ids"] = 47
    _json(fixture["static_result"], result)

    with pytest.raises(readiness.ReadinessError, match="static dataset evidence mismatch"):
        _validate(fixture)


def test_readiness_does_not_hash_large_payload_files(tmp_path, monkeypatch):
    fixture = _build_fixture(tmp_path)
    original = readiness._sha256
    hashed = []

    def record_hash(path):
        hashed.append(path)
        return original(path)

    monkeypatch.setattr(readiness, "_sha256", record_hash)

    _validate(fixture)

    assert fixture["image"] not in hashed
    assert not any(path.suffix == ".safetensors" for path in hashed)


def test_readiness_validator_preserves_python38_login_node_contract():
    path = Path(readiness.__file__)
    source = path.read_text(encoding="utf-8")

    ast.parse(source, filename=str(path), feature_version=8)
    for api in (".is_relative_to(", ".removeprefix(", ".removesuffix("):
        assert api not in source
