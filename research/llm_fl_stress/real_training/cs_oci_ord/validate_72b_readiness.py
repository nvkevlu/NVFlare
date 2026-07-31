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

"""Fail-closed, login-node validation before the scarce 72B GPU allocation.

This command only reads local files and Git metadata. It never invokes Slurm,
starts NVFLARE services, imports the training environment, or reads model
checkpoint contents. The large checkpoint was already verified on a Data
Copier node; this validator verifies that marker and rejects model files
modified after it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

EXPECTED_BRANCH = "codex/llm-fl-real-14b"
EXPECTED_RELEASE = "2026-07-31-full-model-14b-v12"
GATE_MODEL_DIR = "Qwen2.5-1.5B-8faed761d45a"
GATE_MODEL_REVISION = "8faed761d45a263340a0528343f099c05c9a4323"
TARGET_MODEL_DIR = "Qwen2.5-72B-efba10c8e54e"
TARGET_MODEL_REVISION = "efba10c8e54e91e0d9570ab5f7b51a958474d4cb"
TARGET_PAYLOAD_BYTES = 1_755_369_472
TARGET_TENSOR_BYTES = 145_412_407_296
TARGET_SHARD_COUNT = 37
OPERATION_TIMEOUT_SECONDS = 10800
TRANSPORT_TIMEOUT_CONFIG = {
    "streaming_ack_wait": OPERATION_TIMEOUT_SECONDS,
    "streaming_ack_progress_timeout": OPERATION_TIMEOUT_SECONDS,
    "streaming_read_timeout": OPERATION_TIMEOUT_SECONDS,
    "streaming_send_timeout": OPERATION_TIMEOUT_SECONDS,
}
TRANSPORT_TIMEOUT_ENVIRONMENT = {f"NVFLARE_{name.upper()}": value for name, value in TRANSPORT_TIMEOUT_CONFIG.items()}
GPU_HEADROOM_MIB = 16384
FULL_JOB_MEMORY_GIB = 1600
FULL_JOB_CLIENT_COUNT = 2
FIXED_HOST_HEADROOM_GIB = 128
MAX_MODEL_READY_SECONDS = 2400
MAX_WORK_SECONDS = 1200
_GIB = 1024**3
_SHA256_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")


class ReadinessError(RuntimeError):
    """An operational readiness invariant was not proven."""


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


def _read_last_json_object(path: Path) -> dict[str, Any]:
    text = _read_text(path)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
        for line in reversed(text.splitlines()):
            try:
                candidate = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                value = candidate
                break
    _require(isinstance(value, dict), f"no JSON object found in {path}")
    return value


def _read_manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, line in enumerate(_read_text(path).splitlines(), start=1):
        key, separator, value = line.partition("=")
        _require(bool(separator) and bool(key) and bool(value), f"invalid manifest line {path}:{line_number}")
        _require(key not in result, f"duplicate manifest key {key!r} in {path}")
        result[key] = value
    return result


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


def _repo_state(repo_root: Path) -> dict[str, str]:
    return {
        "head": _git(repo_root, "rev-parse", "HEAD"),
        "branch": _git(repo_root, "branch", "--show-current"),
        "status": _git(repo_root, "status", "--porcelain", "--untracked-files=all"),
    }


def _validate_job_id(name: str, value: str) -> str:
    _require(bool(re.fullmatch(r"[0-9]+", value)), f"{name} must be a numeric Slurm job ID, got {value!r}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise ReadinessError(f"cannot hash required file {path}: {exc}") from exc
    return digest.hexdigest()


def _require_nonempty_path(path: Path, *, executable: bool = False) -> None:
    _require(path.exists(), f"required path does not exist: {path}")
    if path.is_file():
        _require(path.stat().st_size > 0, f"required file is empty: {path}")
    if executable:
        _require(os.access(path, os.X_OK), f"required executable is not executable: {path}")


def _validate_environment(project_root: Path, environ: Mapping[str, str]) -> dict[str, str]:
    _require(project_root.is_absolute(), f"--project-root must be absolute: {project_root}")
    _require(project_root.is_dir(), f"project root does not exist: {project_root}")
    if "NCCL_P2P_DISABLE" in environ:
        raise ReadinessError("NCCL_P2P_DISABLE must be unset before submission")

    paths = {
        "container_image": project_root / "containers" / "pytorch-25.01-py3.sqsh",
        "container_checksum": project_root / "containers" / "pytorch-25.01-py3.sqsh.sha256",
        "container_verification_marker": (project_root / "containers" / "pytorch-25.01-py3.sqsh.sha256.verified"),
        "venv_python": project_root / "envs" / "nvflare-fsdp2" / "bin" / "python",
        "requirements_lock": project_root / "envs" / "nvflare-fsdp2" / "requirements.lock",
        "logs": project_root / "logs",
        "artifacts": project_root / "artifacts",
    }
    _require_nonempty_path(paths["container_image"])
    _require_nonempty_path(paths["container_checksum"])
    _require_nonempty_path(paths["container_verification_marker"])
    checksum_text = _read_text(paths["container_checksum"])
    checksum_match = _SHA256_RE.search(checksum_text)
    _require(checksum_match is not None, "container checksum file contains no SHA-256")
    _require(
        Path(checksum_text.split()[-1]).name == paths["container_image"].name,
        "container checksum file does not name the pinned SquashFS image",
    )
    marker_match = _SHA256_RE.search(_read_text(paths["container_verification_marker"]))
    _require(marker_match is not None, "container verification marker contains no SHA-256")
    _require(
        marker_match.group(0) == _sha256(paths["container_checksum"]),
        "container verification marker hash does not match the checksum file",
    )
    container_marker_mtime = paths["container_verification_marker"].stat().st_mtime_ns
    _require(
        paths["container_image"].stat().st_mtime_ns <= container_marker_mtime
        and paths["container_checksum"].stat().st_mtime_ns <= container_marker_mtime,
        "container image or checksum changed after verification",
    )
    _require_nonempty_path(paths["venv_python"], executable=True)
    _require_nonempty_path(paths["requirements_lock"])
    locked_versions = {}
    for line in _read_text(paths["requirements_lock"]).splitlines():
        requirement = line.strip()
        if not requirement or requirement.startswith("#") or "==" not in requirement:
            continue
        name, version = requirement.split("==", 1)
        locked_versions[name.lower().replace("_", "-")] = version
    _require_mapping(
        locked_versions,
        {
            "torch": "2.12.0+cu126",
            "torchvision": "0.27.0+cu126",
            "transformers": "4.57.6",
        },
        "requirements lock",
    )
    _require(paths["logs"].is_dir(), f"required log directory does not exist: {paths['logs']}")
    _require(paths["artifacts"].is_dir(), f"required artifact directory does not exist: {paths['artifacts']}")
    return {name: str(path) for name, path in paths.items()}


def _validate_gate_model(model_path: Path) -> None:
    _require(model_path.is_dir(), f"gate model directory does not exist: {model_path}")
    _require(
        _read_text(model_path / "REVISION") == GATE_MODEL_REVISION,
        f"gate model revision is not {GATE_MODEL_REVISION}",
    )
    config = _read_json(model_path / "config.json")
    _require_mapping(
        config,
        {
            "architectures": ["Qwen2ForCausalLM"],
            "model_type": "qwen2",
            "torch_dtype": "bfloat16",
            "hidden_size": 1536,
            "intermediate_size": 8960,
            "num_hidden_layers": 28,
            "num_attention_heads": 12,
            "num_key_value_heads": 2,
        },
        "gate model config",
    )
    _require_nonempty_path(model_path / "model.safetensors")


def _manifest_entries(path: Path) -> set[str]:
    result: set[str] = set()
    for line_number, line in enumerate(_read_text(path).splitlines(), start=1):
        digest, separator, relative = line.partition("  ")
        _require(
            bool(separator) and bool(re.fullmatch(r"[0-9a-f]{64}", digest)),
            f"invalid checksum manifest line {path}:{line_number}",
        )
        normalized = relative[2:] if relative.startswith("./") else relative
        _require(bool(normalized) and normalized not in result, f"invalid or duplicate path in {path}: {relative!r}")
        result.add(normalized)
    return result


def _validate_target_model(model_path: Path) -> str:
    _require(model_path.is_dir(), f"target model directory does not exist: {model_path}")
    _require(
        _read_text(model_path / "REVISION") == TARGET_MODEL_REVISION,
        f"target model revision is not {TARGET_MODEL_REVISION}",
    )
    config_path = model_path / "config.json"
    index_path = model_path / "model.safetensors.index.json"
    manifest_path = model_path / "MANIFEST.sha256"
    marker_path = model_path / "MANIFEST.sha256.verified"
    config = _read_json(config_path)
    _require_mapping(
        config,
        {
            "architectures": ["Qwen2ForCausalLM"],
            "model_type": "qwen2",
            "torch_dtype": "bfloat16",
            "hidden_size": 8192,
            "intermediate_size": 29568,
            "num_hidden_layers": 80,
            "num_attention_heads": 64,
            "num_key_value_heads": 8,
        },
        "target model config",
    )

    expected_shards = {f"model-{index:05d}-of-{TARGET_SHARD_COUNT:05d}.safetensors" for index in range(1, 38)}
    observed_shards = {path.name for path in model_path.glob("model*.safetensors") if path.is_file()}
    _require(observed_shards == expected_shards, "target model does not contain exactly the 37 expected shards")
    for shard in expected_shards:
        _require_nonempty_path(model_path / shard)

    index = _read_json(index_path)
    weight_map = index.get("weight_map")
    _require(isinstance(weight_map, dict) and bool(weight_map), f"invalid weight_map in {index_path}")
    _require(set(weight_map.values()) == expected_shards, "target model index does not reference exactly the 37 shards")
    total_size = index.get("metadata", {}).get("total_size")
    _require(
        total_size == TARGET_TENSOR_BYTES,
        f"target index total_size must be exactly {TARGET_TENSOR_BYTES}, observed {total_size!r}",
    )

    manifest_entries = _manifest_entries(manifest_path)
    required_entries = expected_shards | {"config.json", "model.safetensors.index.json", "REVISION"}
    _require(required_entries <= manifest_entries, "MANIFEST.sha256 does not cover all identity and checkpoint files")
    marker_text = _read_text(marker_path)
    marker_match = _SHA256_RE.search(marker_text)
    _require(marker_match is not None, f"manifest verification marker contains no SHA-256: {marker_path}")
    manifest_sha256 = _sha256(manifest_path)
    _require(
        marker_match.group(0) == manifest_sha256, "manifest verification marker hash does not match MANIFEST.sha256"
    )

    marker_mtime = marker_path.stat().st_mtime_ns
    protected_paths = [manifest_path]
    for relative_name in manifest_entries:
        relative_path = Path(relative_name)
        _require(
            not relative_path.is_absolute() and ".." not in relative_path.parts,
            f"unsafe path in MANIFEST.sha256: {relative_name!r}",
        )
        protected_path = model_path / relative_path
        _require(
            protected_path.is_file() and not protected_path.is_symlink() and protected_path.stat().st_size > 0,
            f"manifest entry is not a non-empty regular file: {protected_path}",
        )
        protected_paths.append(protected_path)
    observed_staged_files: set[str] = set()
    for staged_path in model_path.rglob("*"):
        relative_path = staged_path.relative_to(model_path)
        if relative_path.parts and relative_path.parts[0] == ".cache":
            continue
        if staged_path.is_symlink():
            raise ReadinessError(f"unverified symbolic link in staged model: {staged_path}")
        if staged_path.is_file() and staged_path not in (manifest_path, marker_path):
            observed_staged_files.add(relative_path.as_posix())
    _require(
        observed_staged_files == manifest_entries,
        "staged model file set differs from MANIFEST.sha256: "
        f"unmanifested={sorted(observed_staged_files - manifest_entries)}, "
        f"missing={sorted(manifest_entries - observed_staged_files)}",
    )
    newer = [str(path) for path in protected_paths if path.stat().st_mtime_ns > marker_mtime]
    _require(not newer, f"model files changed after manifest verification: {newer}")
    return manifest_sha256


def _artifact_root(project_root: Path, prefix: str, job_id: str) -> Path:
    path = project_root / "artifacts" / f"{prefix}{job_id}"
    _require(path.is_dir(), f"artifact directory does not exist: {path}")
    return path


def _validate_artifact_manifest(
    path: Path,
    *,
    job_id: str,
    head: str,
    expected: Mapping[str, str],
) -> dict[str, str]:
    manifest = _read_manifest(path)
    _require_mapping(manifest, {"job_id": job_id, "status": "PASS", "git_commit": head, **expected}, str(path))
    if "exit_code" in manifest:
        _require(manifest["exit_code"] == "0", f"nonzero exit_code in {path}: {manifest['exit_code']}")
    return manifest


def _validate_control_artifacts(project_root: Path, job_id: str, head: str, gate_model: Path) -> None:
    root = _artifact_root(project_root, "control-plane-", job_id)
    _validate_artifact_manifest(
        root / "manifest.txt",
        job_id=job_id,
        head=head,
        expected={
            "model_path": str(gate_model),
            "model_revision": GATE_MODEL_REVISION,
            "operation_timeout_seconds": str(OPERATION_TIMEOUT_SECONDS),
            "transport_timeout_seconds": str(OPERATION_TIMEOUT_SECONDS),
            "service_startup_timeout_seconds": "300",
        },
    )
    _require_mapping(
        _read_json(root / "exported-job-preflight.json"),
        {
            "event": "real_training_exported_job_preflight",
            "status": "PASS",
            "clients": ["site-1", "site-2"],
            "timeout_seconds": OPERATION_TIMEOUT_SECONDS,
            "max_resends": 3,
            "early_flare_init": True,
            "strict_start_job_reply_check": True,
            "launcher_shutdown_timeout_seconds": 600.0,
            "subprocess_tensor_download_timeout_seconds": OPERATION_TIMEOUT_SECONDS,
        },
        "control exported-job preflight",
    )
    _require_mapping(
        _read_json(root / "environment.json"),
        {
            "event": "real_training_production_environment",
            "status": "PASS",
            "transport_timeout_environment": TRANSPORT_TIMEOUT_ENVIRONMENT,
        },
        "control transport environment",
    )
    transport_config = _read_json(root / "services" / "transport-config.json")
    _require_mapping(
        transport_config,
        {
            "event": "real_training_transport_config",
            "status": "PASS",
            "timeout_seconds": OPERATION_TIMEOUT_SECONDS,
        },
        "control provisioned transport config",
    )
    participants = transport_config.get("participants")
    _require(
        isinstance(participants, dict) and set(participants) == {"localhost", "site-1", "site-2"},
        "control transport config does not cover the server and both clients",
    )
    for participant, evidence in participants.items():
        _require(
            isinstance(evidence, dict) and evidence.get("settings") == TRANSPORT_TIMEOUT_CONFIG,
            f"control transport config is incorrect for {participant}",
        )
    _require_mapping(
        _read_json(root / "control-plane.json"),
        {
            "event": "real_training_production_control_plane",
            "status": "PASS",
            "connected_clients": ["site-1", "site-2"],
            "execution_environment": "ProdEnv",
            "transport": "provisioned-tls",
        },
        "control-plane evidence",
    )
    summaries = []
    for sequence in (1, 2):
        summary = _read_json(root / f"control-plane-job-{sequence}" / "summary.json")
        _require_mapping(
            summary,
            {
                "event": "real_training_production_control_plane_job",
                "status": "PASS",
                "sequence": sequence,
                "sites": ["site-1", "site-2"],
                "aggregated_results": 2,
                "job_status": "FINISHED:COMPLETED",
                "execution_environment": "ProdEnv",
            },
            f"control-plane job {sequence}",
        )
        summaries.append(summary)
    qualification = _read_json(root / "qualification.json")
    _require_mapping(
        qualification,
        {
            "event": "real_training_production_qualification",
            "status": "PASS",
            "control_plane_only": True,
        },
        "control-plane qualification",
    )
    _require(qualification.get("control_plane_jobs") == summaries, "qualification control-plane summaries do not match")


def _validate_cpu_artifacts(
    project_root: Path,
    job_id: str,
    head: str,
    target_model: Path,
    manifest_sha256: str,
) -> None:
    root = _artifact_root(project_root, "72b-preflight-", job_id)
    _validate_artifact_manifest(
        root / "manifest.txt",
        job_id=job_id,
        head=head,
        expected={
            "model_path": str(target_model),
            "model_revision": TARGET_MODEL_REVISION,
            "expected_payload_bytes": str(TARGET_PAYLOAD_BYTES),
            "max_payload_bytes": str(2 * _GIB),
            "exported_job_timeout_seconds": str(OPERATION_TIMEOUT_SECONDS),
            "model_manifest_verified": "PASS",
            "model_manifest_sha256": manifest_sha256,
        },
    )
    _require_mapping(
        _read_json(root / "model-manifest-verification.json"),
        {
            "event": "real_training_model_manifest_verification",
            "status": "PASS",
            "manifest_sha256": manifest_sha256,
        },
        "model manifest verification",
    )
    _require_mapping(
        _read_json(root / "dependency-check.json"),
        {
            "event": "real_training_dependency_check",
            "status": "PASS",
            "torch_cuda_version": "12.6",
            "transformers_version": "4.57.6",
        },
        "dependency check",
    )
    server = _read_json(root / "trainable-server-preflight.json")
    _require_mapping(
        server,
        {
            "event": "real_training_trainable_server_preflight",
            "status": "PASS",
            "model_path": str(target_model),
            "model_revision": TARGET_MODEL_REVISION,
            "safetensor_file_count": TARGET_SHARD_COUNT,
            "max_payload_bytes": 2 * _GIB,
        },
        "trainable server preflight",
    )
    _require(server.get("state", {}).get("payload_bytes") == TARGET_PAYLOAD_BYTES, "CPU payload proof is incorrect")
    structure = server.get("safetensor_structure", {})
    _require_mapping(
        structure,
        {
            "index_total_size_bytes": TARGET_TENSOR_BYTES,
            "computed_tensor_bytes": TARGET_TENSOR_BYTES,
            "validated_safetensor_file_count": TARGET_SHARD_COUNT,
        },
        "CPU safetensor structure",
    )
    _require_mapping(
        _read_json(root / "job-export.json"),
        {
            "event": "real_training_validation",
            "status": "PASS",
            "job_exported": True,
            "model_path": str(target_model),
            "model_revision": TARGET_MODEL_REVISION,
            "num_clients": 2,
            "nproc_per_node": 4,
            "state_scope": "trainable",
        },
        "72B job export",
    )
    _require_mapping(
        _read_json(root / "exported-job-preflight.json"),
        {
            "event": "real_training_exported_job_preflight",
            "status": "PASS",
            "clients": ["site-1", "site-2"],
            "timeout_seconds": OPERATION_TIMEOUT_SECONDS,
            "max_resends": 3,
            "early_flare_init": True,
            "strict_start_job_reply_check": True,
            "launcher_shutdown_timeout_seconds": 600.0,
            "subprocess_tensor_download_timeout_seconds": OPERATION_TIMEOUT_SECONDS,
        },
        "72B exported-job preflight",
    )


def _validate_gpu_artifacts(project_root: Path, job_id: str, head: str, target_model: Path) -> None:
    root = _artifact_root(project_root, "72b-gpu-preflight-", job_id)
    _validate_artifact_manifest(
        root / "manifest.txt",
        job_id=job_id,
        head=head,
        expected={
            "model_path": str(target_model),
            "model_revision": TARGET_MODEL_REVISION,
            "world_size": "4",
            "expected_payload_bytes": str(TARGET_PAYLOAD_BYTES),
            "required_headroom_mib": str(GPU_HEADROOM_MIB),
            "full_job_memory_gib": str(FULL_JOB_MEMORY_GIB),
            "full_job_client_count": str(FULL_JOB_CLIENT_COUNT),
            "required_fixed_host_headroom_gib": str(FIXED_HOST_HEADROOM_GIB),
            "max_model_ready_seconds": str(MAX_MODEL_READY_SECONDS),
            "max_work_seconds": str(MAX_WORK_SECONDS),
        },
    )
    capacity = _read_last_json_object(root / "capacity-gate.json")
    _require_mapping(
        capacity,
        {
            "event": "real_model_fsdp2_gpu_capacity_gate",
            "status": "PASS",
            "model_path": str(target_model),
            "model_revision": TARGET_MODEL_REVISION,
            "world_size": 4,
            "trainable_target": "last-layer",
            "local_steps": 2,
            "max_length": 128,
            "payload_bytes": TARGET_PAYLOAD_BYTES,
            "required_headroom_mib": GPU_HEADROOM_MIB,
            "full_job_memory_gib": FULL_JOB_MEMORY_GIB,
            "full_job_memory_bytes": FULL_JOB_MEMORY_GIB * _GIB,
            "full_job_client_count": FULL_JOB_CLIENT_COUNT,
            "required_fixed_host_headroom_gib": FIXED_HOST_HEADROOM_GIB,
            "required_fixed_host_headroom_bytes": FIXED_HOST_HEADROOM_GIB * _GIB,
            "max_model_ready_seconds": MAX_MODEL_READY_SECONDS,
            "max_work_seconds": MAX_WORK_SECONDS,
        },
        "four-GPU capacity gate",
    )
    _require(
        capacity.get("observed_max_model_ready_seconds", float("inf")) <= MAX_MODEL_READY_SECONDS,
        "four-GPU capacity proof exceeds the model readiness limit",
    )
    _require(
        capacity.get("observed_max_work_seconds", float("inf")) <= MAX_WORK_SECONDS,
        "four-GPU capacity proof exceeds the post-readiness work limit",
    )
    checkpoint_bytes = sum(path.stat().st_size for path in target_model.glob("model*.safetensors") if path.is_file())
    ranks = capacity.get("ranks")
    _require(isinstance(ranks, list) and len(ranks) == 4, "four-GPU capacity gate did not report four ranks")
    _require({rank.get("rank") for rank in ranks} == {0, 1, 2, 3}, "capacity rank identities are incomplete")
    rank_peak_rss = [rank.get("max_rss_bytes") for rank in ranks]
    _require(
        all(isinstance(value, int) and value > 0 for value in rank_peak_rss),
        f"capacity gate has invalid rank max RSS values: {rank_peak_rss}",
    )
    one_client_rank_peak_rss_bytes = sum(rank_peak_rss)
    projected_full_job_rank_peak_rss_bytes = one_client_rank_peak_rss_bytes * FULL_JOB_CLIENT_COUNT
    fixed_host_headroom_bytes = FIXED_HOST_HEADROOM_GIB * _GIB
    projected_full_job_host_bytes = (
        projected_full_job_rank_peak_rss_bytes + checkpoint_bytes + fixed_host_headroom_bytes
    )
    full_job_memory_bytes = FULL_JOB_MEMORY_GIB * _GIB
    projected_full_job_host_headroom_bytes = full_job_memory_bytes - projected_full_job_host_bytes
    _require_mapping(
        capacity,
        {
            "checkpoint_bytes": checkpoint_bytes,
            "one_client_rank_peak_rss_bytes": one_client_rank_peak_rss_bytes,
            "projected_full_job_rank_peak_rss_bytes": projected_full_job_rank_peak_rss_bytes,
            "projected_full_job_host_bytes": projected_full_job_host_bytes,
            "projected_full_job_host_headroom_bytes": projected_full_job_host_headroom_bytes,
        },
        "four-GPU host projection arithmetic",
    )
    _require(projected_full_job_host_headroom_bytes >= 0, "projected full job exceeds its host memory allocation")
    _require(capacity.get("tensor_count") == 12, "capacity trainable tensor count is not 12")
    initial_state = capacity.get("initial_state", {})
    final_state = capacity.get("final_state", {})
    for name, state in (("initial", initial_state), ("final", final_state)):
        _require_mapping(
            state,
            {"tensor_count": 12, "payload_bytes": TARGET_PAYLOAD_BYTES},
            f"capacity {name} state",
        )
        _require(
            isinstance(state.get("sha256"), str) and bool(re.fullmatch(r"[0-9a-f]{64}", state["sha256"])),
            f"capacity {name} state has no valid SHA-256",
        )
    _require(initial_state["sha256"] != final_state["sha256"], "capacity optimizer step did not change state")
    for rank in ranks:
        _require(
            rank.get("gpu_name") == "NVIDIA A100-SXM4-80GB",
            f"rank {rank.get('rank')} did not run on the exact qualified GPU",
        )
        _require(
            rank.get("reserved_headroom_bytes", -1) >= GPU_HEADROOM_MIB * 1024**2,
            f"rank {rank.get('rank')} has insufficient GPU memory headroom",
        )
        _require(
            rank.get("model_ready_seconds", float("inf")) <= MAX_MODEL_READY_SECONDS,
            f"rank {rank.get('rank')} exceeded the model readiness limit",
        )
        _require(
            rank.get("post_ready_work_seconds", float("inf")) <= MAX_WORK_SECONDS,
            f"rank {rank.get('rank')} exceeded the post-readiness work limit",
        )
        _require(
            isinstance(rank.get("loss"), (int, float)) and math.isfinite(rank["loss"]),
            f"rank {rank.get('rank')} has a non-finite loss",
        )
        _require(
            isinstance(rank.get("selected_max_abs_change"), (int, float)) and rank["selected_max_abs_change"] > 0,
            f"rank {rank.get('rank')} did not prove a positive optimizer change",
        )


def validate_readiness(
    project_root: Path,
    *,
    control_job_id: str,
    cpu_job_id: str,
    gpu_job_id: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate all evidence required before submitting the full 72B job."""

    control_job_id = _validate_job_id("control_job_id", control_job_id)
    cpu_job_id = _validate_job_id("cpu_job_id", cpu_job_id)
    gpu_job_id = _validate_job_id("gpu_job_id", gpu_job_id)
    environment = _validate_environment(project_root, os.environ if environ is None else environ)

    repo_root = project_root / "repos" / "NVFlare"
    release_file = repo_root / "research" / "llm_fl_stress" / "real_training" / "QUALIFICATION_RELEASE"
    repo = _repo_state(repo_root)
    _require(repo["branch"] == EXPECTED_BRANCH, f"expected branch {EXPECTED_BRANCH}, observed {repo['branch']!r}")
    _require(not repo["status"], "repository is dirty; do not submit from an uncommitted checkout")
    _require(_read_text(release_file) == EXPECTED_RELEASE, f"qualification release is not {EXPECTED_RELEASE}")

    gate_model = project_root / "models" / GATE_MODEL_DIR
    target_model = project_root / "models" / TARGET_MODEL_DIR
    _validate_gate_model(gate_model)
    manifest_sha256 = _validate_target_model(target_model)
    _validate_control_artifacts(project_root, control_job_id, repo["head"], gate_model)
    _validate_cpu_artifacts(project_root, cpu_job_id, repo["head"], target_model, manifest_sha256)
    _validate_gpu_artifacts(project_root, gpu_job_id, repo["head"], target_model)

    return {
        "event": "real_training_72b_login_readiness",
        "status": "PASS",
        "project_root": str(project_root),
        "git_commit": repo["head"],
        "branch": repo["branch"],
        "release": EXPECTED_RELEASE,
        "control_job_id": control_job_id,
        "cpu_job_id": cpu_job_id,
        "gpu_job_id": gpu_job_id,
        "gate_model_revision": GATE_MODEL_REVISION,
        "target_model_revision": TARGET_MODEL_REVISION,
        "model_manifest_sha256": manifest_sha256,
        "environment": environment,
        "safe_to_submit": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--control-job-id", required=True)
    parser.add_argument("--cpu-job-id", required=True)
    parser.add_argument("--gpu-job-id", required=True)
    args = parser.parse_args()
    try:
        result = validate_readiness(
            args.project_root,
            control_job_id=args.control_job_id,
            cpu_job_id=args.cpu_job_id,
            gpu_job_id=args.gpu_job_id,
        )
    except ReadinessError as exc:
        print(
            json.dumps(
                {
                    "event": "real_training_72b_login_readiness",
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
