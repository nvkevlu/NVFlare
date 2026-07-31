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

"""Fail-closed login-node readiness for the two-client 14B full-model run.

The validator is intentionally dependency-free.  It reads checkpoint headers,
manifests, prior gate artifacts, and Git metadata, but it never loads tensor
payloads, imports the training environment, invokes Slurm, or starts NVFLARE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

EXPECTED_BRANCH = "codex/llm-fl-real-14b"
EXPECTED_RELEASE = "2026-07-31-full-model-14b-v12"
REQUIRED_BASE_COMMIT = "a98b517ea63c8181719ff8fd92ab2ca079d915e8"
GATE_MODEL_DIR = "Qwen2.5-1.5B-8faed761d45a"
GATE_MODEL_REVISION = "8faed761d45a263340a0528343f099c05c9a4323"
TARGET_MODEL_DIR = "Qwen2.5-14B-97e1e76335b7"
TARGET_MODEL_REVISION = "97e1e76335b7017d8f67c08a19d103c0504298c9"
TARGET_TENSOR_BYTES = 29_540_067_328
TARGET_PAYLOAD_BYTES = 29_540_067_328
TARGET_TENSOR_COUNT = 579
TARGET_TRAINABLE_PARAMETERS = 14_770_033_664
TARGET_SHARD_COUNT = 8
TARGET_LOCAL_STEPS = 8
TARGET_MAX_LENGTH = 512
TRAINABLE_TARGET = "all"
STATE_SCOPE = "full"
OPERATION_TIMEOUT_SECONDS = 10_800
READY_TIMEOUT_SECONDS = 1_800
STALL_TIMEOUT_SECONDS = 1_800
GPU_HEADROOM_MIB = 16_384
FULL_JOB_MEMORY_GIB = 512
FULL_JOB_CLIENT_COUNT = 2
FIXED_HOST_HEADROOM_GIB = 128
SERVER_STATE_COPIES = 3
MAX_MODEL_READY_SECONDS = 0
MAX_WORK_SECONDS = 0
MINIMUM_SCRATCH_FREE_BYTES = 200 * 1024**3
CPU_PREFLIGHT_MINIMUM_MEMORY_MIB = 128 * 1024
GPU_PREFLIGHT_MINIMUM_MEMORY_MIB = 256 * 1024
PREFLIGHT_MINIMUM_REMAINING_SECONDS = 55 * 60
WATCHDOG_FEASIBILITY_MARGIN_SECONDS = 300
TRANSPORT_TIMEOUT_CONFIG = {
    "streaming_ack_wait": OPERATION_TIMEOUT_SECONDS,
    "streaming_ack_progress_timeout": OPERATION_TIMEOUT_SECONDS,
    "streaming_read_timeout": OPERATION_TIMEOUT_SECONDS,
    "streaming_send_timeout": OPERATION_TIMEOUT_SECONDS,
}
TRANSPORT_TIMEOUT_ENVIRONMENT = {f"NVFLARE_{name.upper()}": value for name, value in TRANSPORT_TIMEOUT_CONFIG.items()}

_GIB = 1024**3
_SHA256_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_DTYPE_BYTES = {
    "BOOL": 1,
    "U8": 1,
    "I8": 1,
    "F8_E4M3": 1,
    "F8_E5M2": 1,
    "I16": 2,
    "U16": 2,
    "F16": 2,
    "BF16": 2,
    "I32": 4,
    "U32": 4,
    "F32": 4,
    "I64": 8,
    "U64": 8,
    "F64": 8,
}


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


def _git(repo_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=check,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReadinessError(f"Git validation failed for {repo_root}: {exc}") from exc


def _repo_state(repo_root: Path) -> dict[str, Any]:
    return {
        "head": _git(repo_root, "rev-parse", "HEAD").stdout.strip(),
        "branch": _git(repo_root, "branch", "--show-current").stdout.strip(),
        "status": _git(repo_root, "status", "--porcelain", "--untracked-files=all").stdout.strip(),
        "base_is_ancestor": _git(
            repo_root,
            "merge-base",
            "--is-ancestor",
            REQUIRED_BASE_COMMIT,
            "HEAD",
            check=False,
        ).returncode
        == 0,
    }


def _validate_repository(project_root: Path) -> dict[str, Any]:
    repo_root = project_root / "repos" / "NVFlare"
    release_file = repo_root / "research" / "llm_fl_stress" / "real_training" / "QUALIFICATION_RELEASE"
    repo = _repo_state(repo_root)
    _require(repo["branch"] == EXPECTED_BRANCH, f"expected branch {EXPECTED_BRANCH}, observed {repo['branch']!r}")
    _require(not repo["status"], "repository is dirty; do not submit from an uncommitted checkout")
    _require(repo["base_is_ancestor"], f"checkout does not contain required base {REQUIRED_BASE_COMMIT}")
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", repo["head"])), f"invalid Git commit: {repo['head']!r}")
    _require(_read_text(release_file) == EXPECTED_RELEASE, f"qualification release is not {EXPECTED_RELEASE}")
    return {**repo, "repo_root": str(repo_root), "release_file": str(release_file)}


def _validate_environment(project_root: Path, environ: Mapping[str, str]) -> dict[str, str]:
    _require(project_root.is_absolute(), f"--project-root must be absolute: {project_root}")
    _require(project_root.is_dir(), f"project root does not exist: {project_root}")
    if "NCCL_P2P_DISABLE" in environ:
        raise ReadinessError("NCCL_P2P_DISABLE must be unset before submission")

    paths = {
        "container_image": project_root / "containers" / "pytorch-25.01-py3.sqsh",
        "container_checksum": project_root / "containers" / "pytorch-25.01-py3.sqsh.sha256",
        "container_verification_marker": project_root / "containers" / "pytorch-25.01-py3.sqsh.sha256.verified",
        "venv_python": project_root / "envs" / "nvflare-fsdp2" / "bin" / "python",
        "requirements_lock": project_root / "envs" / "nvflare-fsdp2" / "requirements.lock",
        "logs": project_root / "logs",
        "artifacts": project_root / "artifacts",
    }
    for name in ("container_image", "container_checksum", "container_verification_marker"):
        _require_nonempty_path(paths[name])
    checksum_text = _read_text(paths["container_checksum"])
    checksum_match = _SHA256_RE.search(checksum_text)
    _require(checksum_match is not None, "container checksum file contains no SHA-256")
    _require(
        Path(checksum_text.split()[-1].lstrip("*")).name == paths["container_image"].name,
        "container checksum file does not name the pinned SquashFS image",
    )
    marker_match = _SHA256_RE.search(_read_text(paths["container_verification_marker"]))
    _require(marker_match is not None, "container verification marker contains no SHA-256")
    _require(
        marker_match.group(0) == _sha256(paths["container_checksum"]),
        "container verification marker hash does not match the checksum file",
    )
    marker_mtime = paths["container_verification_marker"].stat().st_mtime_ns
    _require(
        paths["container_image"].stat().st_mtime_ns <= marker_mtime
        and paths["container_checksum"].stat().st_mtime_ns <= marker_mtime,
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
        {"torch": "2.12.0+cu126", "torchvision": "0.27.0+cu126", "transformers": "4.57.6"},
        "requirements lock",
    )
    _require(paths["logs"].is_dir(), f"required log directory does not exist: {paths['logs']}")
    _require(paths["artifacts"].is_dir(), f"required artifact directory does not exist: {paths['artifacts']}")
    result = {name: str(path) for name, path in paths.items()}
    result["container_manifest_sha256"] = _sha256(paths["container_checksum"])
    return result


def _validate_gate_model(model_path: Path) -> None:
    _require(model_path.is_dir(), f"gate model directory does not exist: {model_path}")
    _require(_read_text(model_path / "REVISION") == GATE_MODEL_REVISION, "gate model revision mismatch")
    _require_mapping(
        _read_json(model_path / "config.json"),
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


def _model_manifest_entries(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, line in enumerate(_read_text(path).splitlines(), start=1):
        digest, separator, relative = line.partition("  ")
        _require(
            bool(separator) and bool(re.fullmatch(r"[0-9a-f]{64}", digest)),
            f"invalid checksum manifest line {path}:{line_number}",
        )
        normalized = relative[2:] if relative.startswith("./") else relative
        relative_path = Path(normalized)
        _require(
            bool(normalized) and not relative_path.is_absolute() and ".." not in relative_path.parts,
            f"unsafe path in {path}: {relative!r}",
        )
        _require(normalized not in result, f"duplicate path in {path}: {relative!r}")
        result[normalized] = digest
    return result


def _read_safetensor_header(path: Path) -> tuple[dict[str, Any], int]:
    try:
        with path.open("rb") as stream:
            raw_size = stream.read(8)
            _require(len(raw_size) == 8, f"safetensor has no complete header length: {path}")
            header_size = struct.unpack("<Q", raw_size)[0]
            _require(0 < header_size <= path.stat().st_size - 8, f"invalid safetensor header size in {path}")
            header = json.loads(stream.read(header_size))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"cannot read safetensor header {path}: {exc}") from exc
    _require(isinstance(header, dict), f"safetensor header is not an object: {path}")
    return header, header_size


def _validate_safetensor_structure(
    model_path: Path,
    weight_map: Mapping[str, Any],
    expected_shards: set[str],
) -> dict[str, Any]:
    expected_keys_by_shard: dict[str, set[str]] = {name: set() for name in expected_shards}
    for key, shard in weight_map.items():
        _require(isinstance(key, str) and bool(key), "target index contains an invalid tensor name")
        _require(shard in expected_shards, f"target index contains an invalid shard name: {shard!r}")
        expected_keys_by_shard[shard].add(key)

    tensor_bytes = 0
    parameter_count = 0
    tensor_count = 0
    for shard_name in sorted(expected_shards):
        shard_path = model_path / shard_name
        header, header_size = _read_safetensor_header(shard_path)
        header_keys = set(header).difference({"__metadata__"})
        _require(
            header_keys == expected_keys_by_shard[shard_name],
            f"safetensor header keys differ from the index for {shard_path}",
        )
        spans = []
        for key in header_keys:
            entry = header[key]
            _require(isinstance(entry, dict), f"invalid safetensor entry {key!r} in {shard_path}")
            dtype = entry.get("dtype")
            shape = entry.get("shape")
            offsets = entry.get("data_offsets")
            _require(dtype in _DTYPE_BYTES, f"unsupported safetensor dtype {dtype!r} in {shard_path}")
            _require(
                isinstance(shape, list)
                and all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in shape),
                f"invalid shape for safetensor tensor {key!r}",
            )
            _require(
                isinstance(offsets, list)
                and len(offsets) == 2
                and all(isinstance(value, int) and not isinstance(value, bool) for value in offsets)
                and 0 <= offsets[0] <= offsets[1],
                f"invalid offsets for safetensor tensor {key!r}",
            )
            elements = math.prod(shape)
            _require(
                offsets[1] - offsets[0] == elements * _DTYPE_BYTES[dtype],
                f"shape/byte mismatch for safetensor tensor {key!r}",
            )
            spans.append((offsets[0], offsets[1], key, elements))

        expected_start = 0
        for start, end, key, elements in sorted(spans):
            _require(start == expected_start, f"non-contiguous safetensor data before {key!r} in {shard_path}")
            expected_start = end
            tensor_bytes += end - start
            parameter_count += elements
            tensor_count += 1
        _require(
            expected_start == shard_path.stat().st_size - 8 - header_size,
            f"safetensor data size differs from its header: {shard_path}",
        )

    _require(
        tensor_count == TARGET_TENSOR_COUNT, f"target tensor count must be {TARGET_TENSOR_COUNT}, got {tensor_count}"
    )
    _require(
        tensor_bytes == TARGET_TENSOR_BYTES, f"target tensor bytes must be {TARGET_TENSOR_BYTES}, got {tensor_bytes}"
    )
    _require(
        parameter_count == TARGET_TRAINABLE_PARAMETERS,
        f"target parameter count must be {TARGET_TRAINABLE_PARAMETERS}, got {parameter_count}",
    )
    return {
        "indexed_tensor_count": tensor_count,
        "computed_tensor_bytes": tensor_bytes,
        "computed_parameter_count": parameter_count,
        "validated_safetensor_file_count": len(expected_shards),
        "validated_safetensor_files": sorted(expected_shards),
    }


def _validate_target_model(model_path: Path) -> dict[str, Any]:
    _require(model_path.is_dir(), f"target model directory does not exist: {model_path}")
    _require(_read_text(model_path / "REVISION") == TARGET_MODEL_REVISION, "target model revision mismatch")
    config_path = model_path / "config.json"
    index_path = model_path / "model.safetensors.index.json"
    manifest_path = model_path / "MANIFEST.sha256"
    marker_path = model_path / "MANIFEST.sha256.verified"
    _require_mapping(
        _read_json(config_path),
        {
            "architectures": ["Qwen2ForCausalLM"],
            "model_type": "qwen2",
            "torch_dtype": "bfloat16",
            "hidden_size": 5120,
            "intermediate_size": 13824,
            "num_hidden_layers": 48,
            "num_attention_heads": 40,
            "num_key_value_heads": 8,
        },
        "target model config",
    )
    expected_shards = {
        f"model-{index:05d}-of-{TARGET_SHARD_COUNT:05d}.safetensors" for index in range(1, TARGET_SHARD_COUNT + 1)
    }
    observed_shards = {path.name for path in model_path.glob("model*.safetensors") if path.is_file()}
    _require(observed_shards == expected_shards, "target model does not contain exactly the eight pinned shards")
    index = _read_json(index_path)
    weight_map = index.get("weight_map")
    _require(isinstance(weight_map, dict) and bool(weight_map), f"invalid weight_map in {index_path}")
    _require(len(weight_map) == TARGET_TENSOR_COUNT, "target index tensor count is not 579")
    _require(
        all(isinstance(value, str) for value in weight_map.values()),
        "target index contains a non-string shard name",
    )
    _require(set(weight_map.values()) == expected_shards, "target index does not reference exactly the eight shards")
    _require(
        index.get("metadata", {}).get("total_size") == TARGET_TENSOR_BYTES,
        f"target index metadata.total_size is not {TARGET_TENSOR_BYTES}",
    )
    structure = _validate_safetensor_structure(model_path, weight_map, expected_shards)

    entries = _model_manifest_entries(manifest_path)
    required_entries = expected_shards | {"config.json", "model.safetensors.index.json", "REVISION"}
    _require(required_entries <= set(entries), "MANIFEST.sha256 does not cover target identity and checkpoint files")
    marker_match = _SHA256_RE.search(_read_text(marker_path))
    _require(marker_match is not None, "target manifest verification marker contains no SHA-256")
    manifest_sha256 = _sha256(manifest_path)
    _require(marker_match.group(0) == manifest_sha256, "target manifest marker does not match MANIFEST.sha256")
    marker_mtime = marker_path.stat().st_mtime_ns
    for relative_name in entries:
        protected = model_path / relative_name
        _require(
            protected.is_file() and not protected.is_symlink() and protected.stat().st_size > 0,
            f"manifest entry is not a non-empty regular file: {protected}",
        )
        _require(protected.stat().st_mtime_ns <= marker_mtime, f"model file changed after verification: {protected}")
    _require(manifest_path.stat().st_mtime_ns <= marker_mtime, "MANIFEST.sha256 changed after verification")
    observed_files: set[str] = set()
    for staged_path in model_path.rglob("*"):
        relative_path = staged_path.relative_to(model_path)
        if relative_path.parts and relative_path.parts[0] == ".cache":
            continue
        if staged_path.is_symlink():
            raise ReadinessError(f"unverified symbolic link in staged model: {staged_path}")
        if staged_path.is_file() and staged_path not in (manifest_path, marker_path):
            observed_files.add(relative_path.as_posix())
    _require(
        observed_files == set(entries),
        "staged model file set differs from MANIFEST.sha256: "
        f"unmanifested={sorted(observed_files - set(entries))}, missing={sorted(set(entries) - observed_files)}",
    )
    return {
        "model_path": str(model_path),
        "model_revision": TARGET_MODEL_REVISION,
        "manifest_sha256": manifest_sha256,
        "payload_bytes": TARGET_PAYLOAD_BYTES,
        "trainable_target": TRAINABLE_TARGET,
        "state_scope": STATE_SCOPE,
        "structure": structure,
    }


def validate_static_readiness(project_root: Path, *, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Validate immutable inputs before either CPU or GPU preflight submission."""

    environment = _validate_environment(project_root, os.environ if environ is None else environ)
    repository = _validate_repository(project_root)
    gate_model = project_root / "models" / GATE_MODEL_DIR
    target_model = project_root / "models" / TARGET_MODEL_DIR
    _validate_gate_model(gate_model)
    target = _validate_target_model(target_model)
    return {
        "event": "real_training_14b_full_model_static_readiness",
        "status": "PASS",
        "safe_to_run_preflights": True,
        "project_root": str(project_root),
        "git_commit": repository["head"],
        "branch": repository["branch"],
        "release": EXPECTED_RELEASE,
        "required_base_commit": REQUIRED_BASE_COMMIT,
        "gate_model_revision": GATE_MODEL_REVISION,
        "target_model": target,
        "environment": environment,
    }


def _validate_job_id(name: str, value: str) -> str:
    _require(bool(re.fullmatch(r"[0-9]+", value)), f"{name} must be a numeric Slurm job ID, got {value!r}")
    return value


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
    _require(manifest.get("exit_code", "0") == "0", f"nonzero exit_code in {path}")
    return manifest


def _manifest_nonnegative_integer(manifest: Mapping[str, str], key: str, label: str) -> int:
    raw_value = manifest.get(key)
    _require(
        isinstance(raw_value, str) and bool(re.fullmatch(r"[0-9]+", raw_value)),
        f"{label} has invalid {key}={raw_value!r}",
    )
    return int(raw_value)


def _validate_slurm_allocation_manifest(
    manifest: Mapping[str, str],
    *,
    label: str,
    minimum_memory_mib: int,
    minimum_remaining_seconds: int,
    expected_gpus_on_node: int | None = None,
) -> None:
    memory_mib = _manifest_nonnegative_integer(manifest, "slurm_mem_per_node_mib", label)
    end_time = _manifest_nonnegative_integer(manifest, "slurm_job_end_time_epoch", label)
    check_time = _manifest_nonnegative_integer(manifest, "slurm_allocation_check_time_epoch", label)
    remaining = _manifest_nonnegative_integer(manifest, "slurm_remaining_seconds_at_check", label)
    _require(
        memory_mib >= minimum_memory_mib,
        f"{label} Slurm memory is below {minimum_memory_mib} MiB: {memory_mib}",
    )
    _require(
        remaining >= minimum_remaining_seconds,
        f"{label} Slurm time remaining is below {minimum_remaining_seconds} seconds: {remaining}",
    )
    _require(
        end_time - check_time == remaining,
        f"{label} Slurm end/check/remaining timestamps are inconsistent",
    )
    if expected_gpus_on_node is not None:
        gpus_on_node = _manifest_nonnegative_integer(manifest, "slurm_gpus_on_node", label)
        _require(
            gpus_on_node == expected_gpus_on_node,
            f"{label} Slurm GPU count must be {expected_gpus_on_node}, got {gpus_on_node}",
        )


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
            "aggregation_weights": {"site-1": 1.0, "site-2": 1.0},
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
    transport = _read_json(root / "services" / "transport-config.json")
    _require_mapping(
        transport,
        {
            "event": "real_training_transport_config",
            "status": "PASS",
            "timeout_seconds": OPERATION_TIMEOUT_SECONDS,
        },
        "control transport config",
    )
    participants = transport.get("participants")
    _require(
        isinstance(participants, dict) and set(participants) == {"localhost", "site-1", "site-2"},
        "control transport config does not cover the server and both clients",
    )
    for participant, evidence in participants.items():
        _require(
            isinstance(evidence, dict) and evidence.get("settings") == TRANSPORT_TIMEOUT_CONFIG,
            f"control transport settings are incorrect for {participant}",
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
    _require(qualification.get("control_plane_jobs") == summaries, "control-plane summaries do not match")


def _data_sha256(repo_root: Path) -> dict[str, str]:
    data_root = repo_root / "research" / "llm_fl_stress" / "real_training" / "data"
    return {site: _sha256(data_root / f"{site}.jsonl") for site in ("site-1", "site-2")}


def _validate_cpu_artifacts(
    project_root: Path,
    job_id: str,
    head: str,
    target_model: Path,
    model_manifest_sha256: str,
    container_manifest_sha256: str,
) -> None:
    root = _artifact_root(project_root, "14b-full-model-preflight-", job_id)
    manifest = _validate_artifact_manifest(
        root / "manifest.txt",
        job_id=job_id,
        head=head,
        expected={
            "model_path": str(target_model),
            "model_revision": TARGET_MODEL_REVISION,
            "trainable_target": TRAINABLE_TARGET,
            "state_scope": STATE_SCOPE,
            "expected_trainable_parameters": str(TARGET_TRAINABLE_PARAMETERS),
            "expected_tensor_count": str(TARGET_TENSOR_COUNT),
            "expected_payload_bytes": str(TARGET_PAYLOAD_BYTES),
            "local_steps": str(TARGET_LOCAL_STEPS),
            "max_length": str(TARGET_MAX_LENGTH),
            "exported_job_timeout_seconds": str(OPERATION_TIMEOUT_SECONDS),
            "model_manifest_sha256": model_manifest_sha256,
            "container_manifest_sha256": container_manifest_sha256,
            "release": EXPECTED_RELEASE,
            "required_base_commit": REQUIRED_BASE_COMMIT,
        },
    )
    _validate_slurm_allocation_manifest(
        manifest,
        label="CPU full-model preflight",
        minimum_memory_mib=CPU_PREFLIGHT_MINIMUM_MEMORY_MIB,
        minimum_remaining_seconds=PREFLIGHT_MINIMUM_REMAINING_SECONDS,
    )
    static = _read_json(root / "static-readiness.json")
    _require_mapping(
        static,
        {
            "event": "real_training_14b_full_model_static_readiness",
            "status": "PASS",
            "safe_to_run_preflights": True,
            "git_commit": head,
            "release": EXPECTED_RELEASE,
        },
        "CPU static readiness",
    )
    _require(
        static.get("target_model", {}).get("manifest_sha256") == model_manifest_sha256,
        "CPU static readiness has the wrong model manifest",
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
    server = _read_json(root / "full-state-server-preflight.json")
    _require_mapping(
        server,
        {
            "event": "real_training_full_state_server_preflight",
            "status": "PASS",
            "model_path": str(target_model),
            "model_revision": TARGET_MODEL_REVISION,
            "config": {
                "architectures": ["Qwen2ForCausalLM"],
                "model_type": "qwen2",
                "torch_dtype": "bfloat16",
                "hidden_size": 5120,
                "intermediate_size": 13824,
                "num_hidden_layers": 48,
                "num_attention_heads": 40,
                "num_key_value_heads": 8,
            },
        },
        "full-state server preflight",
    )
    _require_mapping(
        server.get("safetensor_structure", {}),
        {
            "indexed_tensor_count": TARGET_TENSOR_COUNT,
            "index_total_size_bytes": TARGET_TENSOR_BYTES,
            "computed_tensor_bytes": TARGET_TENSOR_BYTES,
            "validated_safetensor_file_count": TARGET_SHARD_COUNT,
        },
        "full-state server safetensor structure",
    )
    _require_mapping(
        server.get("state", {}),
        {
            "strategy": "schema-sha256-plus-bounded-values",
            "tensor_count": TARGET_TENSOR_COUNT,
            "payload_bytes": TARGET_PAYLOAD_BYTES,
            "parameter_count": TARGET_TRAINABLE_PARAMETERS,
        },
        "full-state materialized server state",
    )
    max_server_rss_bytes = server.get("max_rss_bytes")
    _require(
        isinstance(max_server_rss_bytes, int)
        and not isinstance(max_server_rss_bytes, bool)
        and 0 < max_server_rss_bytes <= CPU_PREFLIGHT_MINIMUM_MEMORY_MIB * 1024**2,
        "full-state server preflight max RSS is missing or exceeds the reviewed 128 GiB envelope: "
        f"{max_server_rss_bytes!r}",
    )
    expected_data = _data_sha256(project_root / "repos" / "NVFlare")
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
            "num_rounds": 1,
            "local_steps": TARGET_LOCAL_STEPS,
            "max_length": TARGET_MAX_LENGTH,
            "trainable_target": TRAINABLE_TARGET,
            "run_mode": "train",
            "state_scope": STATE_SCOPE,
            "dataset_sha256": expected_data,
        },
        "14B full-model job export",
    )
    exported = _read_json(root / "exported-job-preflight.json")
    _require_mapping(
        exported,
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
            "aggregation_weights": {"site-1": 1.0, "site-2": 1.0},
        },
        "14B full-model exported-job preflight",
    )
    _require_mapping(
        exported.get("launcher_contract", {}),
        {
            "trainable_target": TRAINABLE_TARGET,
            "state_scope": STATE_SCOPE,
            "local_steps": TARGET_LOCAL_STEPS,
            "max_length": TARGET_MAX_LENGTH,
            "model_revision": TARGET_MODEL_REVISION,
            "nproc_per_node": 4,
        },
        "exported launcher contract",
    )
    _require(exported.get("dataset_sha256") == expected_data, "exported dataset checksums are incorrect")


def _validate_gpu_artifacts(
    project_root: Path,
    job_id: str,
    head: str,
    target_model: Path,
    model_manifest_sha256: str,
    container_manifest_sha256: str,
) -> None:
    root = _artifact_root(project_root, "14b-full-model-gpu-preflight-", job_id)
    manifest = _validate_artifact_manifest(
        root / "manifest.txt",
        job_id=job_id,
        head=head,
        expected={
            "model_path": str(target_model),
            "model_revision": TARGET_MODEL_REVISION,
            "world_size": "4",
            "trainable_target": TRAINABLE_TARGET,
            "state_scope": STATE_SCOPE,
            "expected_trainable_parameters": str(TARGET_TRAINABLE_PARAMETERS),
            "expected_tensor_count": str(TARGET_TENSOR_COUNT),
            "expected_payload_bytes": str(TARGET_PAYLOAD_BYTES),
            "local_steps": str(TARGET_LOCAL_STEPS),
            "max_length": str(TARGET_MAX_LENGTH),
            "required_headroom_mib": str(GPU_HEADROOM_MIB),
            "full_job_memory_gib": str(FULL_JOB_MEMORY_GIB),
            "full_job_client_count": str(FULL_JOB_CLIENT_COUNT),
            "required_fixed_host_headroom_gib": str(FIXED_HOST_HEADROOM_GIB),
            "server_state_copies": str(SERVER_STATE_COPIES),
            "max_model_ready_seconds": "0",
            "max_work_seconds": "0",
            "model_manifest_sha256": model_manifest_sha256,
            "container_manifest_sha256": container_manifest_sha256,
            "release": EXPECTED_RELEASE,
            "required_base_commit": REQUIRED_BASE_COMMIT,
        },
    )
    _validate_slurm_allocation_manifest(
        manifest,
        label="GPU full-model preflight",
        minimum_memory_mib=GPU_PREFLIGHT_MINIMUM_MEMORY_MIB,
        minimum_remaining_seconds=PREFLIGHT_MINIMUM_REMAINING_SECONDS,
        expected_gpus_on_node=4,
    )
    static = _read_json(root / "static-readiness.json")
    _require_mapping(
        static,
        {
            "event": "real_training_14b_full_model_static_readiness",
            "status": "PASS",
            "safe_to_run_preflights": True,
            "git_commit": head,
            "release": EXPECTED_RELEASE,
        },
        "GPU static readiness",
    )
    _require(
        static.get("target_model", {}).get("manifest_sha256") == model_manifest_sha256,
        "GPU static readiness has the wrong model manifest",
    )
    _require(
        static.get("environment", {}).get("container_manifest_sha256") == container_manifest_sha256,
        "GPU static readiness has the wrong container manifest",
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
            "trainable_target": TRAINABLE_TARGET,
            "state_scope": STATE_SCOPE,
            "trainable_parameters": TARGET_TRAINABLE_PARAMETERS,
            "total_parameters": TARGET_TRAINABLE_PARAMETERS,
            "frozen_parameters": 0,
            "total_tensor_count": TARGET_TENSOR_COUNT,
            "trainable_tensor_count": TARGET_TENSOR_COUNT,
            "frozen_tensor_count": 0,
            "gradient_checkpointing_enabled": True,
            "local_steps": TARGET_LOCAL_STEPS,
            "max_length": TARGET_MAX_LENGTH,
            "payload_bytes": TARGET_PAYLOAD_BYTES,
            "tensor_count": TARGET_TENSOR_COUNT,
            "required_headroom_mib": GPU_HEADROOM_MIB,
            "full_job_memory_gib": FULL_JOB_MEMORY_GIB,
            "full_job_memory_bytes": FULL_JOB_MEMORY_GIB * _GIB,
            "full_job_client_count": FULL_JOB_CLIENT_COUNT,
            "required_fixed_host_headroom_gib": FIXED_HOST_HEADROOM_GIB,
            "required_fixed_host_headroom_bytes": FIXED_HOST_HEADROOM_GIB * _GIB,
            "server_state_copies": SERVER_STATE_COPIES,
            "max_model_ready_seconds": 0,
            "max_work_seconds": 0,
        },
        "four-GPU full-model capacity gate",
    )
    model_ready_seconds = capacity.get("observed_max_model_ready_seconds")
    work_seconds = capacity.get("observed_max_work_seconds")
    maximum_feasible_model_ready_seconds = READY_TIMEOUT_SECONDS - WATCHDOG_FEASIBILITY_MARGIN_SECONDS
    maximum_feasible_work_seconds = STALL_TIMEOUT_SECONDS - WATCHDOG_FEASIBILITY_MARGIN_SECONDS
    _require(
        isinstance(model_ready_seconds, (int, float))
        and not isinstance(model_ready_seconds, bool)
        and math.isfinite(model_ready_seconds)
        and 0 <= model_ready_seconds <= maximum_feasible_model_ready_seconds,
        "capacity gate model-ready telemetry does not fit the final readiness watchdog with the 300-second margin: "
        f"{model_ready_seconds!r}",
    )
    _require(
        isinstance(work_seconds, (int, float))
        and not isinstance(work_seconds, bool)
        and math.isfinite(work_seconds)
        and 0 < work_seconds <= maximum_feasible_work_seconds,
        "capacity gate post-ready work telemetry does not fit the final stall watchdog with the 300-second margin: "
        f"{work_seconds!r}",
    )
    aggregate_training = capacity.get("training_evidence")
    _require(isinstance(aggregate_training, dict), "capacity gate has no aggregated training_evidence")
    aggregate_optimizer = aggregate_training.get("optimizer_state")
    _require(isinstance(aggregate_optimizer, dict), "capacity gate has no aggregated optimizer_state")
    _require_mapping(
        aggregate_optimizer.get("config", {}),
        {"name": "AdamW", "foreach": False, "fused": False},
        "capacity aggregated optimizer configuration",
    )
    dtype_histogram = aggregate_optimizer.get("global_dtype_histogram")
    _require(isinstance(dtype_histogram, dict), "capacity aggregated optimizer state has no dtype histogram")
    bf16_moments = dtype_histogram.get("bfloat16")
    _require(isinstance(bf16_moments, dict), "capacity aggregated optimizer state has no BF16 moments")
    expected_moment_values = 2 * TARGET_TRAINABLE_PARAMETERS
    expected_moment_bytes = 4 * TARGET_TRAINABLE_PARAMETERS
    _require_mapping(
        bf16_moments,
        {"numel": expected_moment_values, "bytes": expected_moment_bytes},
        "capacity BF16 AdamW moment coverage",
    )
    _require(
        isinstance(bf16_moments.get("tensor_count"), int) and bf16_moments["tensor_count"] > 0,
        "capacity BF16 AdamW moment tensor count must be positive",
    )
    _require_mapping(
        capacity.get("optimizer_moment_evidence", {}),
        {
            "status": "PASS",
            "dtype": "bfloat16",
            "trainable_parameters": TARGET_TRAINABLE_PARAMETERS,
            "moment_values": expected_moment_values,
            "moment_bytes": expected_moment_bytes,
            "foreach": False,
            "fused": False,
        },
        "capacity optimizer-moment evidence",
    )
    checkpoint_bytes = sum(path.stat().st_size for path in target_model.glob("model*.safetensors") if path.is_file())
    ranks = capacity.get("ranks")
    _require(isinstance(ranks, list) and len(ranks) == 4, "capacity gate did not report four ranks")
    _require({rank.get("rank") for rank in ranks} == {0, 1, 2, 3}, "capacity rank identities are incomplete")
    rank_peak_rss = [rank.get("max_rss_bytes") for rank in ranks]
    _require(
        all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in rank_peak_rss),
        f"capacity gate has invalid rank max RSS values: {rank_peak_rss}",
    )
    one_client_rank_peak_rss_bytes = sum(rank_peak_rss)
    projected_rank_bytes = one_client_rank_peak_rss_bytes * FULL_JOB_CLIENT_COUNT
    server_state_reserve_bytes = checkpoint_bytes * SERVER_STATE_COPIES
    projected_host_bytes = projected_rank_bytes + server_state_reserve_bytes + FIXED_HOST_HEADROOM_GIB * _GIB
    projected_headroom = FULL_JOB_MEMORY_GIB * _GIB - projected_host_bytes
    _require_mapping(
        capacity,
        {
            "checkpoint_bytes": checkpoint_bytes,
            "server_state_reserve_bytes": server_state_reserve_bytes,
            "one_client_rank_peak_rss_bytes": one_client_rank_peak_rss_bytes,
            "projected_full_job_rank_peak_rss_bytes": projected_rank_bytes,
            "projected_full_job_host_bytes": projected_host_bytes,
            "projected_full_job_host_headroom_bytes": projected_headroom,
        },
        "four-GPU host projection arithmetic",
    )
    _require(projected_headroom >= 0, "projected full job exceeds its 512 GiB host memory allocation")
    states = {}
    for name in ("initial_state", "final_state"):
        state = capacity.get(name, {})
        _require_mapping(
            state,
            {"tensor_count": TARGET_TENSOR_COUNT, "payload_bytes": TARGET_PAYLOAD_BYTES},
            f"capacity {name}",
        )
        _require(state.get("strategy") == "schema-sha256-plus-bounded-values", f"capacity {name} strategy is wrong")
        _require(
            isinstance(state.get("schema_sha256"), str) and bool(re.fullmatch(r"[0-9a-f]{64}", state["schema_sha256"])),
            f"capacity {name} has no valid schema SHA-256",
        )
        samples = state.get("samples")
        _require(isinstance(samples, list) and bool(samples), f"capacity {name} has no bounded value samples")
        for sample in samples:
            _require(
                isinstance(sample, dict)
                and isinstance(sample.get("key"), str)
                and isinstance(sample.get("index"), int)
                and isinstance(sample.get("value"), (int, float))
                and math.isfinite(sample["value"]),
                f"capacity {name} has an invalid bounded value sample",
            )
        states[name] = state
    _require(
        states["initial_state"]["schema_sha256"] == states["final_state"]["schema_sha256"],
        "capacity full-state tensor schema changed",
    )
    _require(
        isinstance(states["final_state"].get("bounded_values_changed"), bool),
        "capacity final state does not report whether bounded values changed",
    )
    for rank in ranks:
        _require(rank.get("gpu_name") == "NVIDIA A100-SXM4-80GB", "capacity gate used an unqualified GPU")
        _require(
            rank.get("reserved_headroom_bytes", -1) >= GPU_HEADROOM_MIB * 1024**2,
            f"rank {rank.get('rank')} has insufficient GPU memory headroom",
        )
        _require(
            isinstance(rank.get("loss"), (int, float)) and math.isfinite(rank["loss"]),
            f"rank {rank.get('rank')} has a non-finite loss",
        )
        _require(
            isinstance(rank.get("selected_max_abs_change"), (int, float)) and rank["selected_max_abs_change"] > 0,
            f"rank {rank.get('rank')} did not prove a positive optimizer update",
        )
        training = rank.get("training_evidence")
        _require(isinstance(training, dict), f"rank {rank.get('rank')} has no training evidence")
        probes = training.get("gradient_probes")
        _require(isinstance(probes, list) and len(probes) == 3, "all-parameter training needs three gradient probes")
        _require(
            {(probe.get("position"), probe.get("layer_index")) for probe in probes}
            == {("early", 0), ("middle", 24), ("late", 47)},
            "gradient probes do not cover early, middle, and late decoder layers",
        )
        for probe in probes:
            _require(
                probe.get("finite") is True
                and probe.get("nonzero") is True
                and isinstance(probe.get("global_l2_norm"), (int, float))
                and math.isfinite(probe["global_l2_norm"])
                and probe["global_l2_norm"] > 0,
                f"rank {rank.get('rank')} has an invalid gradient probe",
            )
        optimizer = training.get("optimizer_state")
        _require(
            isinstance(optimizer, dict)
            and optimizer.get("tensor_count", 0) > 0
            and optimizer.get("tensor_numel", 0) > 0
            and optimizer.get("tensor_bytes", 0) > 0,
            f"rank {rank.get('rank')} has no initialized optimizer tensor state",
        )


def validate_readiness(
    project_root: Path,
    *,
    control_job_id: str,
    cpu_job_id: str,
    gpu_job_id: str,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate all evidence required before submitting the eight-GPU job."""

    control_job_id = _validate_job_id("control_job_id", control_job_id)
    cpu_job_id = _validate_job_id("cpu_job_id", cpu_job_id)
    gpu_job_id = _validate_job_id("gpu_job_id", gpu_job_id)
    static = validate_static_readiness(project_root, environ=environ)
    head = static["git_commit"]
    gate_model = project_root / "models" / GATE_MODEL_DIR
    target_model = project_root / "models" / TARGET_MODEL_DIR
    model_manifest_sha256 = static["target_model"]["manifest_sha256"]
    container_manifest_sha256 = static["environment"]["container_manifest_sha256"]
    _validate_control_artifacts(project_root, control_job_id, head, gate_model)
    _validate_cpu_artifacts(
        project_root,
        cpu_job_id,
        head,
        target_model,
        model_manifest_sha256,
        container_manifest_sha256,
    )
    _validate_gpu_artifacts(
        project_root,
        gpu_job_id,
        head,
        target_model,
        model_manifest_sha256,
        container_manifest_sha256,
    )
    return {
        "event": "real_training_14b_full_model_login_readiness",
        "status": "PASS",
        "safe_to_submit": True,
        "project_root": str(project_root),
        "git_commit": head,
        "branch": static["branch"],
        "release": EXPECTED_RELEASE,
        "required_base_commit": REQUIRED_BASE_COMMIT,
        "control_job_id": control_job_id,
        "cpu_job_id": cpu_job_id,
        "gpu_job_id": gpu_job_id,
        "gate_model_revision": GATE_MODEL_REVISION,
        "target_model_revision": TARGET_MODEL_REVISION,
        "model_manifest_sha256": model_manifest_sha256,
        "container_manifest_sha256": container_manifest_sha256,
        "trainable_target": TRAINABLE_TARGET,
        "state_scope": STATE_SCOPE,
        "expected_trainable_parameters": TARGET_TRAINABLE_PARAMETERS,
        "expected_tensor_count": TARGET_TENSOR_COUNT,
        "expected_payload_bytes": TARGET_PAYLOAD_BYTES,
        "local_steps": TARGET_LOCAL_STEPS,
        "max_length": TARGET_MAX_LENGTH,
        "full_job_memory_gib": FULL_JOB_MEMORY_GIB,
        "minimum_scratch_free_bytes": MINIMUM_SCRATCH_FREE_BYTES,
        "target_ready_timeout_seconds": READY_TIMEOUT_SECONDS,
        "target_stall_timeout_seconds": STALL_TIMEOUT_SECONDS,
        "watchdog_feasibility_margin_seconds": WATCHDOG_FEASIBILITY_MARGIN_SECONDS,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--control-job-id")
    parser.add_argument("--cpu-job-id")
    parser.add_argument("--gpu-job-id")
    parser.add_argument("--static-only", action="store_true")
    args = parser.parse_args()
    event = (
        "real_training_14b_full_model_static_readiness"
        if args.static_only
        else "real_training_14b_full_model_login_readiness"
    )
    try:
        if args.static_only:
            _require(
                not any((args.control_job_id, args.cpu_job_id, args.gpu_job_id)),
                "--static-only does not accept gate job IDs",
            )
            result = validate_static_readiness(args.project_root)
        else:
            _require(
                all((args.control_job_id, args.cpu_job_id, args.gpu_job_id)),
                "control, CPU, and GPU job IDs are all required",
            )
            result = validate_readiness(
                args.project_root,
                control_job_id=args.control_job_id,
                cpu_job_id=args.cpu_job_id,
                gpu_job_id=args.gpu_job_id,
            )
    except ReadinessError as exc:
        print(
            json.dumps({"event": event, "status": "FAIL", "safe_to_submit": False, "error": str(exc)}, sort_keys=True),
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
