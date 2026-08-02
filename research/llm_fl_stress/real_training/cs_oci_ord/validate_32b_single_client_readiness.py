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

"""Fail-closed, zero-GPU readiness for the single-client 32B experiment.

This validator reads only small metadata, checksum manifests, JSON evidence,
and Git state.  The large container and checkpoint payloads must already have
been verified on a Data Copier; this command validates their verification
markers and rejects files changed afterward.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

EXPECTED_RELEASE = "2026-07-31-full-model-14b-v12"
EXPERIMENT_RELEASE = "2026-08-02-single-client-full-model-32b-v3"
REQUIRED_BASE_COMMIT = "27c39f637506f7589c8b4536fd3c8b4e4664b82f"
MODEL_DIR = "Qwen2.5-32B-1818d35814b8"
MODEL_REVISION = "1818d35814b8319459f4bd55ed1ac8709630f003"
EXPECTED_CONFIG = {
    "architectures": ["Qwen2ForCausalLM"],
    "model_type": "qwen2",
    "torch_dtype": "bfloat16",
    "hidden_size": 5120,
    "intermediate_size": 27648,
    "num_hidden_layers": 64,
    "num_attention_heads": 40,
    "num_key_value_heads": 8,
}
PARAMETER_COUNT = 32_763_876_352
TENSOR_COUNT = 771
LOGICAL_STATE_BYTES = 65_527_752_704
PHYSICAL_CHECKPOINT_BYTES = 65_527_841_752
SHARD_COUNT = 17
DATASET_RECORDS = 48
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_HEAD_RE = re.compile(r"[0-9a-f]{40}")


class ReadinessError(RuntimeError):
    """A required readiness invariant was not proven."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReadinessError(message)


def _read_text(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ReadinessError(f"cannot read required file {path}: {exc}") from exc
    _require(bool(value), f"required file is empty: {path}")
    return value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise ReadinessError(f"invalid JSON in {path}: {exc}") from exc
    _require(isinstance(value, dict), f"expected a JSON object in {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ReadinessError(f"cannot hash required metadata file {path}: {exc}") from exc
    return digest.hexdigest()


def _require_nonempty_file(path: Path, *, executable: bool = False) -> None:
    _require(path.is_file(), f"required file does not exist: {path}")
    _require(not path.is_symlink(), f"required file must not be a symbolic link: {path}")
    _require(path.stat().st_size > 0, f"required file is empty: {path}")
    if executable:
        _require(os.access(path, os.X_OK), f"required executable is not executable: {path}")


def _require_mapping(source: Mapping[str, Any], expected: Mapping[str, Any], label: str) -> None:
    mismatches = {
        key: {"expected": expected_value, "observed": source.get(key)}
        for key, expected_value in expected.items()
        if source.get(key) != expected_value
    }
    _require(not mismatches, f"{label} mismatch: {mismatches}")


def _git(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReadinessError(f"Git validation failed for {repo_root}: {exc}") from exc
    return completed.stdout.strip()


def _validate_repository(repo_root: Path, expected_head: str, required_base_commit: str) -> dict[str, str]:
    _require(repo_root.is_absolute(), f"--repo-root must be absolute: {repo_root}")
    _require(repo_root.is_dir(), f"repository root does not exist: {repo_root}")
    _require(bool(_HEAD_RE.fullmatch(expected_head)), "--expected-head must be a lowercase 40-character Git commit")
    observed_head = _git(repo_root, "rev-parse", "HEAD")
    _require(observed_head == expected_head, f"repository HEAD is {observed_head}, expected {expected_head}")
    _require(bool(_HEAD_RE.fullmatch(required_base_commit)), "required base commit must be a lowercase Git commit")
    try:
        _git(repo_root, "merge-base", "--is-ancestor", required_base_commit, observed_head)
    except ReadinessError as exc:
        raise ReadinessError(
            f"repository HEAD {observed_head} does not contain required base commit {required_base_commit}"
        ) from exc
    status = _git(repo_root, "status", "--porcelain", "--untracked-files=all")
    _require(not status, "repository is dirty; do not submit from an uncommitted checkout")
    branch = _git(repo_root, "branch", "--show-current")
    _require(not branch, "32B submission repository must be a detached immutable release worktree")
    release_path = repo_root / "research" / "llm_fl_stress" / "real_training" / "QUALIFICATION_RELEASE"
    _require(_read_text(release_path) == EXPECTED_RELEASE, f"qualification release is not {EXPECTED_RELEASE}")
    return {
        "head": observed_head,
        "branch": branch,
        "release_file": str(release_path),
    }


def _checksum_record(path: Path, label: str) -> tuple[str, str]:
    fields = _read_text(path).split()
    _require(len(fields) == 2, f"{label} must contain exactly one sha256sum record")
    digest = fields[0]
    target = fields[1].lstrip("*")
    _require(bool(_SHA256_RE.fullmatch(digest)), f"{label} contains an invalid SHA-256")
    _require(bool(target), f"{label} does not name a target")
    return digest, target


def _validate_container(project_root: Path) -> dict[str, str]:
    image = project_root / "containers" / "pytorch-25.01-py3.sqsh"
    checksum = Path(str(image) + ".sha256")
    marker = Path(str(checksum) + ".verified")
    for path in (image, checksum, marker):
        _require_nonempty_file(path)
    _, checksum_target = _checksum_record(checksum, "container checksum")
    _require(Path(checksum_target).name == image.name, "container checksum does not name the pinned image")
    marker_digest, marker_target = _checksum_record(marker, "container verification marker")
    _require(Path(marker_target).name == checksum.name, "container verification marker does not name the checksum")
    checksum_sha256 = _sha256(checksum)
    _require(marker_digest == checksum_sha256, "container verification marker does not match the checksum file")
    marker_mtime = marker.stat().st_mtime_ns
    _require(
        image.stat().st_mtime_ns <= marker_mtime and checksum.stat().st_mtime_ns <= marker_mtime,
        "container image or checksum changed after verification",
    )
    return {
        "image": str(image),
        "checksum": str(checksum),
        "verification_marker": str(marker),
        "manifest_sha256": checksum_sha256,
    }


def _manifest_entries(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_number, line in enumerate(_read_text(path).splitlines(), start=1):
        digest, separator, relative = line.partition("  ")
        _require(
            bool(separator) and bool(_SHA256_RE.fullmatch(digest)),
            f"invalid checksum manifest line {path}:{line_number}",
        )
        normalized = relative[2:] if relative.startswith("./") else relative
        relative_path = Path(normalized)
        _require(
            bool(normalized)
            and not relative_path.is_absolute()
            and ".." not in relative_path.parts
            and normalized not in entries,
            f"unsafe or duplicate model manifest path: {relative!r}",
        )
        entries[normalized] = digest
    return entries


def _validate_model(project_root: Path) -> dict[str, Any]:
    model_path = project_root / "models" / MODEL_DIR
    _require(model_path.is_dir(), f"model directory does not exist: {model_path}")
    _require(_read_text(model_path / "REVISION") == MODEL_REVISION, f"model revision is not {MODEL_REVISION}")
    manifest = model_path / "MANIFEST.sha256"
    marker = model_path / "MANIFEST.sha256.verified"
    _require_nonempty_file(manifest)
    _require_nonempty_file(marker)
    marker_digest, marker_target = _checksum_record(marker, "model verification marker")
    _require(Path(marker_target).name == manifest.name, "model verification marker does not name MANIFEST.sha256")
    manifest_sha256 = _sha256(manifest)
    _require(marker_digest == manifest_sha256, "model verification marker does not match MANIFEST.sha256")
    marker_mtime = marker.stat().st_mtime_ns
    _require(manifest.stat().st_mtime_ns <= marker_mtime, "model manifest changed after verification")

    entries = _manifest_entries(manifest)
    expected_shards = {f"model-{index:05d}-of-{SHARD_COUNT:05d}.safetensors" for index in range(1, SHARD_COUNT + 1)}
    required_entries = {"REVISION", "config.json", "model.safetensors.index.json", *expected_shards}
    _require(required_entries.issubset(entries), "model manifest does not cover all identity and checkpoint files")
    for relative in entries:
        path = model_path / relative
        _require_nonempty_file(path)
        _require(path.stat().st_mtime_ns <= marker_mtime, f"model file changed after verification: {path}")

    for path in model_path.rglob("*"):
        relative = path.relative_to(model_path)
        if ".cache" in relative.parts or path in (manifest, marker):
            continue
        if (path.is_file() or path.is_symlink()) and path.stat().st_mtime_ns > marker_mtime:
            raise ReadinessError(f"model path changed after verification: {path}")
    return {
        "path": str(model_path),
        "revision": MODEL_REVISION,
        "manifest": str(manifest),
        "verification_marker": str(marker),
        "manifest_sha256": manifest_sha256,
        "manifest_entry_count": len(entries),
    }


def _validate_requirements(project_root: Path) -> dict[str, Any]:
    venv_python = project_root / "envs" / "nvflare-fsdp2" / "bin" / "python"
    requirements = project_root / "envs" / "nvflare-fsdp2" / "requirements.lock"
    # Standard venvs commonly make bin/python a symlink to their interpreter.
    # Allow that one executable symlink while retaining strict regular-file
    # checks for model and container evidence.
    _require(venv_python.is_file(), f"required virtualenv Python does not exist: {venv_python}")
    _require(venv_python.stat().st_size > 0, f"required virtualenv Python is empty: {venv_python}")
    _require(os.access(venv_python, os.X_OK), f"required virtualenv Python is not executable: {venv_python}")
    _require_nonempty_file(requirements)
    versions: dict[str, str] = {}
    for line in _read_text(requirements).splitlines():
        requirement = line.strip()
        if not requirement or requirement.startswith("#") or "==" not in requirement:
            continue
        name, version = requirement.split("==", 1)
        versions[name.lower().replace("_", "-")] = version
    _require_mapping(
        versions,
        {"torch": "2.12.0+cu126", "torchvision": "0.27.0+cu126", "transformers": "4.57.6"},
        "requirements lock",
    )
    return {
        "path": str(requirements),
        "sha256": _sha256(requirements),
        "pinned_versions": {key: versions[key] for key in ("torch", "torchvision", "transformers")},
        "venv_python": str(venv_python),
    }


def _validate_dataset(repo_root: Path, static_dataset: Mapping[str, Any]) -> dict[str, Any]:
    dataset_path = repo_root / "research" / "llm_fl_stress" / "real_training" / "data" / "site-1.jsonl"
    records = []
    identifiers = set()
    for line_number, line in enumerate(_read_text(dataset_path).splitlines(), start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReadinessError(f"invalid dataset JSON at {dataset_path}:{line_number}: {exc}") from exc
        _require(isinstance(record, dict) and set(record) == {"id", "text"}, "dataset records require only id/text")
        _require(isinstance(record["id"], str) and bool(record["id"]), "dataset record has an invalid id")
        _require(isinstance(record["text"], str) and bool(record["text"].strip()), "dataset record has empty text")
        _require(record["id"] not in identifiers, f"duplicate dataset id {record['id']!r}")
        identifiers.add(record["id"])
        records.append(record)
    dataset_sha256 = _sha256(dataset_path)
    _require(len(records) == DATASET_RECORDS, f"dataset must contain exactly {DATASET_RECORDS} records")
    _require_mapping(
        static_dataset,
        {
            "path": str(dataset_path),
            "sha256": dataset_sha256,
            "record_count": DATASET_RECORDS,
            "minimum_records": DATASET_RECORDS,
            "unique_ids": DATASET_RECORDS,
        },
        "static dataset evidence",
    )
    return {"path": str(dataset_path), "sha256": dataset_sha256, "record_count": len(records)}


def _validate_static_result(
    static_result: Path,
    *,
    repo_root: Path,
    model: Mapping[str, Any],
) -> dict[str, Any]:
    _require(static_result.is_absolute(), f"--static-result must be absolute: {static_result}")
    _require_nonempty_file(static_result)
    result = _read_json(static_result)
    _require_mapping(
        result,
        {
            "event": "real_training_model_structure_preflight",
            "status": "PASS",
            "model_path": model["path"],
            "model_revision": MODEL_REVISION,
            "config": EXPECTED_CONFIG,
            "parameter_count": PARAMETER_COUNT,
            "parameter_dtype": "bfloat16",
            "logical_state_payload_bytes": LOGICAL_STATE_BYTES,
            "physical_checkpoint_file_bytes": PHYSICAL_CHECKPOINT_BYTES,
            "tensor_payload_materialized": False,
            "gpu_required": False,
        },
        "static model preflight",
    )
    structure = result.get("safetensor_structure")
    _require(isinstance(structure, dict), "static model preflight lacks safetensor_structure")
    expected_shards = [f"model-{index:05d}-of-{SHARD_COUNT:05d}.safetensors" for index in range(1, SHARD_COUNT + 1)]
    _require_mapping(
        structure,
        {
            "indexed_tensor_count": TENSOR_COUNT,
            "index_total_size_bytes": LOGICAL_STATE_BYTES,
            "computed_tensor_bytes": LOGICAL_STATE_BYTES,
            "validated_safetensor_files": expected_shards,
            "validated_safetensor_file_count": SHARD_COUNT,
        },
        "static safetensor evidence",
    )
    dataset = result.get("dataset")
    _require(isinstance(dataset, dict), "static model preflight lacks dataset evidence")
    dataset_evidence = _validate_dataset(repo_root, dataset)
    static_manifest_sha256 = result.get("model_manifest_sha256")
    _require(
        static_manifest_sha256 == model["manifest_sha256"],
        "static preflight model_manifest_sha256 does not match the verified model manifest",
    )
    return {
        "path": str(static_result),
        "sha256": _sha256(static_result),
        "dataset": dataset_evidence,
        "model_manifest_sha256": static_manifest_sha256,
    }


def validate_readiness(
    project_root: Path,
    *,
    repo_root: Path,
    expected_head: str,
    static_result: Path,
    environ: Mapping[str, str] | None = None,
    required_base_commit: str = REQUIRED_BASE_COMMIT,
) -> dict[str, Any]:
    """Validate every zero-GPU invariant required immediately before sbatch."""

    _require(project_root.is_absolute(), f"--project-root must be absolute: {project_root}")
    _require(project_root.is_dir(), f"project root does not exist: {project_root}")
    release_root = (project_root / "repos" / "NVFlare-runs").resolve()
    resolved_repo = repo_root.resolve()
    _require(
        os.path.commonpath((str(release_root), str(resolved_repo))) == str(release_root),
        f"--repo-root must be an immutable worktree under {release_root}",
    )
    environment = os.environ if environ is None else environ
    if "NCCL_P2P_DISABLE" in environment:
        raise ReadinessError("NCCL_P2P_DISABLE must be unset before submission")
    _require(environment.get("PYTHONPATH") == str(repo_root), "PYTHONPATH must equal the immutable release worktree")
    _require(
        environment.get("NVFLARE_EXPECTED_SOURCE_ROOT") == str(repo_root),
        "NVFLARE_EXPECTED_SOURCE_ROOT must equal the immutable release worktree",
    )
    repository = _validate_repository(repo_root, expected_head, required_base_commit)
    container = _validate_container(project_root)
    model = _validate_model(project_root)
    requirements = _validate_requirements(project_root)
    static = _validate_static_result(static_result, repo_root=repo_root, model=model)
    logs = project_root / "logs"
    artifacts = project_root / "artifacts"
    _require(logs.is_dir(), f"required log directory does not exist: {logs}")
    _require(artifacts.is_dir(), f"required artifact directory does not exist: {artifacts}")
    return {
        "event": "real_training_32b_single_client_readiness",
        "status": "PASS",
        "safe_to_submit": True,
        "project_root": str(project_root),
        "repo_root": str(repo_root),
        "git_commit": repository["head"],
        "required_base_commit": required_base_commit,
        "branch": repository["branch"],
        "pythonpath": environment["PYTHONPATH"],
        "nvflare_expected_source_root": environment["NVFLARE_EXPECTED_SOURCE_ROOT"],
        "release": EXPECTED_RELEASE,
        "experiment_release": EXPERIMENT_RELEASE,
        "model_path": model["path"],
        "model_revision": MODEL_REVISION,
        "model_manifest_sha256": model["manifest_sha256"],
        "container_manifest_sha256": container["manifest_sha256"],
        "static_result": str(static_result),
        "static_result_sha256": static["sha256"],
        "requirements_lock_sha256": requirements["sha256"],
        "expected_trainable_parameters": PARAMETER_COUNT,
        "expected_tensor_count": TENSOR_COUNT,
        "expected_payload_bytes": LOGICAL_STATE_BYTES,
        "expected_checkpoint_file_bytes": PHYSICAL_CHECKPOINT_BYTES,
        "dataset_sha256": static["dataset"]["sha256"],
        "dataset_records": DATASET_RECORDS,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--static-result", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = validate_readiness(
            args.project_root,
            repo_root=args.repo_root,
            expected_head=args.expected_head,
            static_result=args.static_result,
        )
    except ReadinessError as exc:
        print(
            json.dumps(
                {
                    "event": "real_training_32b_single_client_readiness",
                    "status": "FAIL",
                    "safe_to_submit": False,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
