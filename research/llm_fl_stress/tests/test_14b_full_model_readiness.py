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

import hashlib
import json
import os
import struct
from pathlib import Path

import pytest

from research.llm_fl_stress.real_training.cs_oci_ord import validate_14b_full_model_readiness as readiness

HEAD = "b" * 40
CONTROL_JOB_ID = "201"
CPU_JOB_ID = "202"
GPU_JOB_ID = "203"


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _manifest(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{key}={item}\n" for key, item in value.items()), encoding="utf-8")


def _replace_manifest_value(path: Path, key: str, value: object) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    matches = [index for index, line in enumerate(lines) if line.startswith(f"{key}=")]
    assert len(matches) == 1
    lines[matches[0]] = f"{key}={value}"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_verification_marker(source: Path, marker: Path, protected: list[Path]) -> None:
    marker.write_text(_sha256(source) + "\n", encoding="utf-8")
    latest = max(path.stat().st_mtime_ns for path in [source, *protected])
    os.utime(marker, ns=(latest + 1_000_000, latest + 1_000_000))


def _build_gate_model(project_root: Path) -> Path:
    gate = project_root / "models" / readiness.GATE_MODEL_DIR
    gate.mkdir(parents=True)
    (gate / "REVISION").write_text(readiness.GATE_MODEL_REVISION + "\n", encoding="utf-8")
    _json(
        gate / "config.json",
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
    )
    (gate / "model.safetensors").write_bytes(b"gate")
    return gate


def _build_target_model(project_root: Path) -> tuple[Path, str]:
    target = project_root / "models" / readiness.TARGET_MODEL_DIR
    target.mkdir(parents=True)
    revision = target / "REVISION"
    revision.write_text(readiness.TARGET_MODEL_REVISION + "\n", encoding="utf-8")
    config = target / "config.json"
    _json(
        config,
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
    )
    tokenizer_config = target / "tokenizer_config.json"
    tokenizer_config.write_text('{"model_max_length":32768}\n', encoding="utf-8")
    tokenizer = target / "tokenizer.json"
    tokenizer.write_text('{"version":"1.0"}\n', encoding="utf-8")

    base_elements, remainder = divmod(readiness.TARGET_TRAINABLE_PARAMETERS, readiness.TARGET_TENSOR_COUNT)
    shard_entries: list[dict[str, dict]] = [dict() for _ in range(readiness.TARGET_SHARD_COUNT)]
    weight_map = {}
    for index in range(readiness.TARGET_TENSOR_COUNT):
        key = f"model.tensor.{index:03d}"
        shard_index = index % readiness.TARGET_SHARD_COUNT
        shard_name = f"model-{shard_index + 1:05d}-of-{readiness.TARGET_SHARD_COUNT:05d}.safetensors"
        elements = base_elements + (1 if index < remainder else 0)
        shard_entries[shard_index][key] = {"dtype": "BF16", "shape": [elements]}
        weight_map[key] = shard_name

    shards = []
    for shard_index, entries in enumerate(shard_entries, start=1):
        shard_name = f"model-{shard_index:05d}-of-{readiness.TARGET_SHARD_COUNT:05d}.safetensors"
        shard = target / shard_name
        offset = 0
        header = {}
        for key, entry in entries.items():
            size = entry["shape"][0] * 2
            header[key] = {**entry, "data_offsets": [offset, offset + size]}
            offset += size
        encoded_header = json.dumps(header, separators=(",", ":")).encode("utf-8")
        with shard.open("wb") as stream:
            stream.write(struct.pack("<Q", len(encoded_header)))
            stream.write(encoded_header)
            stream.truncate(8 + len(encoded_header) + offset)
        shards.append(shard)

    index = target / "model.safetensors.index.json"
    _json(index, {"metadata": {"total_size": readiness.TARGET_TENSOR_BYTES}, "weight_map": weight_map})
    manifest = target / "MANIFEST.sha256"
    covered = [revision, config, tokenizer_config, tokenizer, index, *shards]
    manifest.write_text(
        "".join(f"{hashlib.sha256(path.name.encode()).hexdigest()}  ./{path.name}\n" for path in covered),
        encoding="utf-8",
    )
    marker = target / "MANIFEST.sha256.verified"
    _write_verification_marker(manifest, marker, covered)
    return target, _sha256(manifest)


def _build_control_artifacts(project_root: Path, gate: Path) -> None:
    root = project_root / "artifacts" / f"control-plane-{CONTROL_JOB_ID}"
    _manifest(
        root / "manifest.txt",
        {
            "job_id": CONTROL_JOB_ID,
            "status": "PASS",
            "exit_code": 0,
            "host": "cpu-node",
            "model_path": gate,
            "model_revision": readiness.GATE_MODEL_REVISION,
            "operation_timeout_seconds": readiness.OPERATION_TIMEOUT_SECONDS,
            "transport_timeout_seconds": readiness.OPERATION_TIMEOUT_SECONDS,
            "service_startup_timeout_seconds": 300,
            "git_commit": HEAD,
        },
    )
    _json(
        root / "exported-job-preflight.json",
        {
            "event": "real_training_exported_job_preflight",
            "status": "PASS",
            "clients": ["site-1", "site-2"],
            "timeout_seconds": readiness.OPERATION_TIMEOUT_SECONDS,
            "max_resends": 3,
            "early_flare_init": True,
            "strict_start_job_reply_check": True,
            "launcher_shutdown_timeout_seconds": 600.0,
            "subprocess_tensor_download_timeout_seconds": readiness.OPERATION_TIMEOUT_SECONDS,
            "aggregation_weights": {"site-1": 1.0, "site-2": 1.0},
        },
    )
    _json(
        root / "environment.json",
        {
            "event": "real_training_production_environment",
            "status": "PASS",
            "transport_timeout_environment": readiness.TRANSPORT_TIMEOUT_ENVIRONMENT,
        },
    )
    _json(
        root / "services" / "transport-config.json",
        {
            "event": "real_training_transport_config",
            "status": "PASS",
            "timeout_seconds": readiness.OPERATION_TIMEOUT_SECONDS,
            "participants": {
                name: {
                    "path": f"/private/{name}/local/comm_config.json",
                    "settings": readiness.TRANSPORT_TIMEOUT_CONFIG,
                }
                for name in ("localhost", "site-1", "site-2")
            },
        },
    )
    _json(
        root / "control-plane.json",
        {
            "event": "real_training_production_control_plane",
            "status": "PASS",
            "connected_clients": ["site-1", "site-2"],
            "execution_environment": "ProdEnv",
            "transport": "provisioned-tls",
        },
    )
    summaries = []
    for sequence in (1, 2):
        summary = {
            "event": "real_training_production_control_plane_job",
            "status": "PASS",
            "sequence": sequence,
            "sites": ["site-1", "site-2"],
            "aggregated_results": 2,
            "job_status": "FINISHED:COMPLETED",
            "execution_environment": "ProdEnv",
            "job_id": f"flare-job-{sequence}",
        }
        summaries.append(summary)
        _json(root / f"control-plane-job-{sequence}" / "summary.json", summary)
    _json(
        root / "qualification.json",
        {
            "event": "real_training_production_qualification",
            "status": "PASS",
            "control_plane_only": True,
            "control_plane_jobs": summaries,
        },
    )


def _build_cpu_artifacts(
    project_root: Path,
    target: Path,
    model_manifest_sha256: str,
    container_manifest_sha256: str,
    static: dict,
) -> None:
    root = project_root / "artifacts" / f"14b-full-model-preflight-{CPU_JOB_ID}"
    _manifest(
        root / "manifest.txt",
        {
            "job_id": CPU_JOB_ID,
            "status": "PASS",
            "exit_code": 0,
            "host": "cpu-node",
            "model_path": target,
            "model_revision": readiness.TARGET_MODEL_REVISION,
            "trainable_target": readiness.TRAINABLE_TARGET,
            "state_scope": readiness.STATE_SCOPE,
            "expected_trainable_parameters": readiness.TARGET_TRAINABLE_PARAMETERS,
            "expected_tensor_count": readiness.TARGET_TENSOR_COUNT,
            "expected_payload_bytes": readiness.TARGET_PAYLOAD_BYTES,
            "local_steps": readiness.TARGET_LOCAL_STEPS,
            "max_length": readiness.TARGET_MAX_LENGTH,
            "exported_job_timeout_seconds": readiness.OPERATION_TIMEOUT_SECONDS,
            "slurm_mem_per_node_mib": readiness.CPU_PREFLIGHT_MINIMUM_MEMORY_MIB,
            "slurm_job_end_time_epoch": 2_000_000_000,
            "slurm_allocation_check_time_epoch": 1_999_996_400,
            "slurm_remaining_seconds_at_check": 3_600,
            "model_manifest_sha256": model_manifest_sha256,
            "container_manifest_sha256": container_manifest_sha256,
            "release": readiness.EXPECTED_RELEASE,
            "required_base_commit": readiness.REQUIRED_BASE_COMMIT,
            "git_commit": HEAD,
        },
    )
    _json(root / "static-readiness.json", static)
    _json(
        root / "dependency-check.json",
        {
            "event": "real_training_dependency_check",
            "status": "PASS",
            "torch_cuda_version": "12.6",
            "transformers_version": "4.57.6",
        },
    )
    _json(
        root / "full-state-server-preflight.json",
        {
            "event": "real_training_full_state_server_preflight",
            "status": "PASS",
            "model_path": str(target),
            "model_revision": readiness.TARGET_MODEL_REVISION,
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
            "safetensor_structure": {
                "indexed_tensor_count": readiness.TARGET_TENSOR_COUNT,
                "index_total_size_bytes": readiness.TARGET_TENSOR_BYTES,
                "computed_tensor_bytes": readiness.TARGET_TENSOR_BYTES,
                "validated_safetensor_file_count": readiness.TARGET_SHARD_COUNT,
            },
            "state": {
                "strategy": "schema-sha256-plus-bounded-values",
                "schema_sha256": "3" * 64,
                "tensor_count": readiness.TARGET_TENSOR_COUNT,
                "payload_bytes": readiness.TARGET_PAYLOAD_BYTES,
                "parameter_count": readiness.TARGET_TRAINABLE_PARAMETERS,
                "samples": [{"key": "model.tensor.000", "index": 0, "value": 1.0}],
            },
            "max_rss_bytes": 60 * 1024**3,
        },
    )
    repo_root = project_root / "repos" / "NVFlare"
    dataset_sha256 = {
        site: _sha256(repo_root / "research" / "llm_fl_stress" / "real_training" / "data" / f"{site}.jsonl")
        for site in ("site-1", "site-2")
    }
    _json(
        root / "job-export.json",
        {
            "event": "real_training_validation",
            "status": "PASS",
            "job_exported": True,
            "model_path": str(target),
            "model_revision": readiness.TARGET_MODEL_REVISION,
            "num_clients": 2,
            "nproc_per_node": 4,
            "num_rounds": 1,
            "local_steps": readiness.TARGET_LOCAL_STEPS,
            "max_length": readiness.TARGET_MAX_LENGTH,
            "trainable_target": readiness.TRAINABLE_TARGET,
            "run_mode": "train",
            "state_scope": readiness.STATE_SCOPE,
            "dataset_sha256": dataset_sha256,
        },
    )
    _json(
        root / "exported-job-preflight.json",
        {
            "event": "real_training_exported_job_preflight",
            "status": "PASS",
            "clients": ["site-1", "site-2"],
            "timeout_seconds": readiness.OPERATION_TIMEOUT_SECONDS,
            "max_resends": 3,
            "early_flare_init": True,
            "strict_start_job_reply_check": True,
            "launcher_shutdown_timeout_seconds": 600.0,
            "subprocess_tensor_download_timeout_seconds": readiness.OPERATION_TIMEOUT_SECONDS,
            "aggregation_weights": {"site-1": 1.0, "site-2": 1.0},
            "launcher_contract": {
                "trainable_target": readiness.TRAINABLE_TARGET,
                "state_scope": readiness.STATE_SCOPE,
                "local_steps": readiness.TARGET_LOCAL_STEPS,
                "max_length": readiness.TARGET_MAX_LENGTH,
                "model_revision": readiness.TARGET_MODEL_REVISION,
                "nproc_per_node": 4,
            },
            "dataset_sha256": dataset_sha256,
        },
    )


def _capacity(target: Path) -> dict:
    checkpoint_bytes = sum(path.stat().st_size for path in target.glob("model*.safetensors"))
    rank_peak_rss = 8 * 1024**3
    one_client = rank_peak_rss * 4
    projected_ranks = one_client * readiness.FULL_JOB_CLIENT_COUNT
    server_state_reserve = checkpoint_bytes * readiness.SERVER_STATE_COPIES
    projected = projected_ranks + server_state_reserve + readiness.FIXED_HOST_HEADROOM_GIB * 1024**3
    moment_values = 2 * readiness.TARGET_TRAINABLE_PARAMETERS
    moment_bytes = 4 * readiness.TARGET_TRAINABLE_PARAMETERS
    return {
        "event": "real_model_fsdp2_gpu_capacity_gate",
        "status": "PASS",
        "model_path": str(target),
        "model_revision": readiness.TARGET_MODEL_REVISION,
        "world_size": 4,
        "trainable_target": readiness.TRAINABLE_TARGET,
        "state_scope": readiness.STATE_SCOPE,
        "trainable_parameters": readiness.TARGET_TRAINABLE_PARAMETERS,
        "total_parameters": readiness.TARGET_TRAINABLE_PARAMETERS,
        "frozen_parameters": 0,
        "total_tensor_count": readiness.TARGET_TENSOR_COUNT,
        "trainable_tensor_count": readiness.TARGET_TENSOR_COUNT,
        "frozen_tensor_count": 0,
        "gradient_checkpointing_enabled": True,
        "local_steps": readiness.TARGET_LOCAL_STEPS,
        "max_length": readiness.TARGET_MAX_LENGTH,
        "payload_bytes": readiness.TARGET_PAYLOAD_BYTES,
        "tensor_count": readiness.TARGET_TENSOR_COUNT,
        "required_headroom_mib": readiness.GPU_HEADROOM_MIB,
        "full_job_memory_gib": readiness.FULL_JOB_MEMORY_GIB,
        "full_job_memory_bytes": readiness.FULL_JOB_MEMORY_GIB * 1024**3,
        "full_job_client_count": readiness.FULL_JOB_CLIENT_COUNT,
        "required_fixed_host_headroom_gib": readiness.FIXED_HOST_HEADROOM_GIB,
        "required_fixed_host_headroom_bytes": readiness.FIXED_HOST_HEADROOM_GIB * 1024**3,
        "server_state_copies": readiness.SERVER_STATE_COPIES,
        "max_model_ready_seconds": 0,
        "max_work_seconds": 0,
        "observed_max_model_ready_seconds": 900.0,
        "observed_max_work_seconds": 120.0,
        "training_evidence": {
            "optimizer_state": {
                "config": {"name": "AdamW", "foreach": False, "fused": False},
                "global_dtype_histogram": {
                    "bfloat16": {"tensor_count": 1158, "numel": moment_values, "bytes": moment_bytes},
                    "float32": {"tensor_count": 579, "numel": 579, "bytes": 2316},
                },
            }
        },
        "optimizer_moment_evidence": {
            "status": "PASS",
            "dtype": "bfloat16",
            "trainable_parameters": readiness.TARGET_TRAINABLE_PARAMETERS,
            "moment_values": moment_values,
            "moment_bytes": moment_bytes,
            "foreach": False,
            "fused": False,
        },
        "checkpoint_bytes": checkpoint_bytes,
        "one_client_rank_peak_rss_bytes": one_client,
        "projected_full_job_rank_peak_rss_bytes": projected_ranks,
        "projected_full_job_host_bytes": projected,
        "projected_full_job_host_headroom_bytes": readiness.FULL_JOB_MEMORY_GIB * 1024**3 - projected,
        "server_state_reserve_bytes": server_state_reserve,
        "initial_state": {
            "strategy": "schema-sha256-plus-bounded-values",
            "tensor_count": readiness.TARGET_TENSOR_COUNT,
            "payload_bytes": readiness.TARGET_PAYLOAD_BYTES,
            "schema_sha256": "1" * 64,
            "samples": [{"key": "model.tensor.000", "index": 0, "value": 1.0}],
        },
        "final_state": {
            "strategy": "schema-sha256-plus-bounded-values",
            "tensor_count": readiness.TARGET_TENSOR_COUNT,
            "payload_bytes": readiness.TARGET_PAYLOAD_BYTES,
            "schema_sha256": "1" * 64,
            "samples": [{"key": "model.tensor.000", "index": 0, "value": 1.0}],
            "bounded_values_changed": False,
        },
        "ranks": [
            {
                "rank": rank,
                "local_rank": rank,
                "gpu_name": "NVIDIA A100-SXM4-80GB",
                "reserved_headroom_bytes": 20 * 1024**3,
                "max_rss_bytes": rank_peak_rss,
                "loss": 1.0,
                "selected_max_abs_change": 1.0e-5,
                "training_evidence": {
                    "gradient_probes": [
                        {
                            "position": position,
                            "layer_index": layer_index,
                            "parameter": f"model.layers.{layer_index}.weight",
                            "global_l2_norm": 1.0,
                            "finite": True,
                            "nonzero": True,
                        }
                        for position, layer_index in (("early", 0), ("middle", 24), ("late", 47))
                    ],
                    "optimizer_state": {"tensor_count": 10, "tensor_numel": 100, "tensor_bytes": 400},
                },
            }
            for rank in range(4)
        ],
    }


def _build_gpu_artifacts(
    project_root: Path,
    target: Path,
    model_manifest_sha256: str,
    container_manifest_sha256: str,
    static: dict,
) -> None:
    root = project_root / "artifacts" / f"14b-full-model-gpu-preflight-{GPU_JOB_ID}"
    _manifest(
        root / "manifest.txt",
        {
            "job_id": GPU_JOB_ID,
            "status": "PASS",
            "exit_code": 0,
            "host": "gpu-node",
            "model_path": target,
            "model_revision": readiness.TARGET_MODEL_REVISION,
            "world_size": 4,
            "trainable_target": readiness.TRAINABLE_TARGET,
            "state_scope": readiness.STATE_SCOPE,
            "expected_trainable_parameters": readiness.TARGET_TRAINABLE_PARAMETERS,
            "expected_tensor_count": readiness.TARGET_TENSOR_COUNT,
            "expected_payload_bytes": readiness.TARGET_PAYLOAD_BYTES,
            "local_steps": readiness.TARGET_LOCAL_STEPS,
            "max_length": readiness.TARGET_MAX_LENGTH,
            "required_headroom_mib": readiness.GPU_HEADROOM_MIB,
            "full_job_memory_gib": readiness.FULL_JOB_MEMORY_GIB,
            "full_job_client_count": readiness.FULL_JOB_CLIENT_COUNT,
            "required_fixed_host_headroom_gib": readiness.FIXED_HOST_HEADROOM_GIB,
            "server_state_copies": readiness.SERVER_STATE_COPIES,
            "max_model_ready_seconds": readiness.MAX_MODEL_READY_SECONDS,
            "max_work_seconds": readiness.MAX_WORK_SECONDS,
            "slurm_mem_per_node_mib": readiness.GPU_PREFLIGHT_MINIMUM_MEMORY_MIB,
            "slurm_gpus_on_node": 4,
            "slurm_job_end_time_epoch": 2_000_000_000,
            "slurm_allocation_check_time_epoch": 1_999_996_400,
            "slurm_remaining_seconds_at_check": 3_600,
            "model_manifest_sha256": model_manifest_sha256,
            "container_manifest_sha256": container_manifest_sha256,
            "release": readiness.EXPECTED_RELEASE,
            "required_base_commit": readiness.REQUIRED_BASE_COMMIT,
            "git_commit": HEAD,
        },
    )
    _json(root / "static-readiness.json", static)
    _json(root / "capacity-gate.json", _capacity(target))


@pytest.fixture
def ready_project(tmp_path, monkeypatch):
    project_root = tmp_path.resolve()
    container = project_root / "containers" / "pytorch-25.01-py3.sqsh"
    container.parent.mkdir(parents=True)
    container.write_bytes(b"squashfs")
    checksum = container.with_suffix(container.suffix + ".sha256")
    checksum.write_text(f"{_sha256(container)}  {container.name}\n", encoding="utf-8")
    marker = container.with_suffix(container.suffix + ".sha256.verified")
    _write_verification_marker(checksum, marker, [container])

    python = project_root / "envs" / "nvflare-fsdp2" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)
    (python.parent.parent / "requirements.lock").write_text(
        "torch==2.12.0+cu126\ntorchvision==0.27.0+cu126\ntransformers==4.57.6\n",
        encoding="utf-8",
    )
    (project_root / "logs").mkdir()
    (project_root / "artifacts").mkdir()

    repo_root = project_root / "repos" / "NVFlare"
    release = repo_root / "research" / "llm_fl_stress" / "real_training" / "QUALIFICATION_RELEASE"
    release.parent.mkdir(parents=True)
    release.write_text(readiness.EXPECTED_RELEASE + "\n", encoding="utf-8")
    data_root = release.parent / "data"
    data_root.mkdir()
    (data_root / "site-1.jsonl").write_text('{"id":"site-1"}\n', encoding="utf-8")
    (data_root / "site-2.jsonl").write_text('{"id":"site-2"}\n', encoding="utf-8")
    monkeypatch.setattr(
        readiness,
        "_repo_state",
        lambda _repo: {
            "head": HEAD,
            "branch": readiness.EXPECTED_BRANCH,
            "status": "",
            "base_is_ancestor": True,
        },
    )

    gate = _build_gate_model(project_root)
    target, model_manifest_sha256 = _build_target_model(project_root)
    static = readiness.validate_static_readiness(project_root, environ={})
    _build_control_artifacts(project_root, gate)
    _build_cpu_artifacts(project_root, target, model_manifest_sha256, _sha256(checksum), static)
    _build_gpu_artifacts(project_root, target, model_manifest_sha256, _sha256(checksum), static)
    return project_root


def _validate(project_root: Path, *, environ=None):
    return readiness.validate_readiness(
        project_root,
        control_job_id=CONTROL_JOB_ID,
        cpu_job_id=CPU_JOB_ID,
        gpu_job_id=GPU_JOB_ID,
        environ={} if environ is None else environ,
    )


def test_readiness_accepts_exact_all_parameter_full_state_evidence(ready_project):
    result = _validate(ready_project)

    assert result["status"] == "PASS"
    assert result["safe_to_submit"] is True
    assert result["trainable_target"] == "all"
    assert result["state_scope"] == "full"
    assert result["expected_trainable_parameters"] == 14_770_033_664
    assert result["expected_payload_bytes"] == 29_540_067_328
    assert result["watchdog_feasibility_margin_seconds"] == 300


def test_readiness_rejects_dirty_checkout(ready_project, monkeypatch):
    monkeypatch.setattr(
        readiness,
        "_repo_state",
        lambda _repo: {
            "head": HEAD,
            "branch": readiness.EXPECTED_BRANCH,
            "status": " M client.py",
            "base_is_ancestor": True,
        },
    )

    with pytest.raises(readiness.ReadinessError, match="repository is dirty"):
        _validate(ready_project)


def test_readiness_rejects_inherited_nccl_override(ready_project):
    with pytest.raises(readiness.ReadinessError, match="must be unset"):
        _validate(ready_project, environ={"NCCL_P2P_DISABLE": "0"})


def test_readiness_rejects_stale_gate_commit(ready_project):
    path = ready_project / "artifacts" / f"14b-full-model-gpu-preflight-{GPU_JOB_ID}" / "manifest.txt"
    path.write_text(path.read_text().replace(HEAD, "c" * 40), encoding="utf-8")

    with pytest.raises(readiness.ReadinessError, match="git_commit"):
        _validate(ready_project)


@pytest.mark.parametrize(
    ("artifact", "key", "value", "message"),
    [
        (
            f"14b-full-model-preflight-{CPU_JOB_ID}",
            "slurm_mem_per_node_mib",
            readiness.CPU_PREFLIGHT_MINIMUM_MEMORY_MIB - 1,
            "CPU full-model preflight Slurm memory",
        ),
        (
            f"14b-full-model-preflight-{CPU_JOB_ID}",
            "slurm_remaining_seconds_at_check",
            readiness.PREFLIGHT_MINIMUM_REMAINING_SECONDS - 1,
            "CPU full-model preflight Slurm time remaining",
        ),
        (
            f"14b-full-model-gpu-preflight-{GPU_JOB_ID}",
            "slurm_mem_per_node_mib",
            readiness.GPU_PREFLIGHT_MINIMUM_MEMORY_MIB - 1,
            "GPU full-model preflight Slurm memory",
        ),
        (
            f"14b-full-model-gpu-preflight-{GPU_JOB_ID}",
            "slurm_gpus_on_node",
            8,
            "GPU full-model preflight Slurm GPU count",
        ),
        (
            f"14b-full-model-gpu-preflight-{GPU_JOB_ID}",
            "slurm_remaining_seconds_at_check",
            readiness.PREFLIGHT_MINIMUM_REMAINING_SECONDS - 1,
            "GPU full-model preflight Slurm time remaining",
        ),
    ],
)
def test_readiness_rejects_underprovisioned_preflight_allocation(ready_project, artifact, key, value, message):
    manifest = ready_project / "artifacts" / artifact / "manifest.txt"
    _replace_manifest_value(manifest, key, value)

    with pytest.raises(readiness.ReadinessError, match=message):
        _validate(ready_project)


def test_readiness_rejects_inconsistent_preflight_end_time_evidence(ready_project):
    manifest = ready_project / "artifacts" / f"14b-full-model-preflight-{CPU_JOB_ID}" / "manifest.txt"
    _replace_manifest_value(manifest, "slurm_job_end_time_epoch", 2_000_000_001)

    with pytest.raises(readiness.ReadinessError, match="end/check/remaining timestamps are inconsistent"):
        _validate(ready_project)


def test_readiness_rejects_last_layer_cpu_export(ready_project):
    path = ready_project / "artifacts" / f"14b-full-model-preflight-{CPU_JOB_ID}" / "job-export.json"
    value = json.loads(path.read_text())
    value["trainable_target"] = "last-layer"
    _json(path, value)

    with pytest.raises(readiness.ReadinessError, match="trainable_target"):
        _validate(ready_project)


def test_readiness_rejects_server_preflight_outside_reviewed_memory_envelope(ready_project):
    path = ready_project / "artifacts" / f"14b-full-model-preflight-{CPU_JOB_ID}" / "full-state-server-preflight.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["max_rss_bytes"] = 128 * 1024**3 + 1
    _json(path, value)

    with pytest.raises(readiness.ReadinessError, match="exceeds the reviewed 128 GiB envelope"):
        _validate(ready_project)


@pytest.mark.parametrize(
    "relative_path",
    [
        Path(f"control-plane-{CONTROL_JOB_ID}") / "exported-job-preflight.json",
        Path(f"14b-full-model-preflight-{CPU_JOB_ID}") / "exported-job-preflight.json",
    ],
)
def test_readiness_rejects_non_equal_exported_aggregation_weights(ready_project, relative_path):
    path = ready_project / "artifacts" / relative_path
    value = json.loads(path.read_text(encoding="utf-8"))
    value["aggregation_weights"]["site-2"] = 0.5
    _json(path, value)

    with pytest.raises(readiness.ReadinessError, match="aggregation_weights"):
        _validate(ready_project)


def test_readiness_rejects_capacity_gate_with_a_hidden_cutoff(ready_project):
    path = ready_project / "artifacts" / f"14b-full-model-gpu-preflight-{GPU_JOB_ID}" / "capacity-gate.json"
    value = json.loads(path.read_text())
    value["max_work_seconds"] = 1200
    _json(path, value)

    with pytest.raises(readiness.ReadinessError, match="max_work_seconds"):
        _validate(ready_project)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("observed_max_model_ready_seconds", -1.0, "model-ready telemetry"),
        ("observed_max_model_ready_seconds", 1500.001, "model-ready telemetry"),
        ("observed_max_work_seconds", 0.0, "post-ready work telemetry"),
        ("observed_max_work_seconds", 1500.001, "post-ready work telemetry"),
    ],
)
def test_readiness_rejects_capacity_timing_that_cannot_fit_final_watchdogs(ready_project, field, value, message):
    path = ready_project / "artifacts" / f"14b-full-model-gpu-preflight-{GPU_JOB_ID}" / "capacity-gate.json"
    capacity = json.loads(path.read_text(encoding="utf-8"))
    capacity[field] = value
    _json(path, capacity)

    with pytest.raises(readiness.ReadinessError, match=message):
        _validate(ready_project)


def test_readiness_rejects_wrong_all_parameter_count(ready_project):
    path = ready_project / "artifacts" / f"14b-full-model-gpu-preflight-{GPU_JOB_ID}" / "capacity-gate.json"
    value = json.loads(path.read_text())
    value["trainable_parameters"] -= 1
    _json(path, value)

    with pytest.raises(readiness.ReadinessError, match="trainable_parameters"):
        _validate(ready_project)


def test_readiness_rejects_incomplete_bf16_adamw_moment_coverage(ready_project):
    path = ready_project / "artifacts" / f"14b-full-model-gpu-preflight-{GPU_JOB_ID}" / "capacity-gate.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["training_evidence"]["optimizer_state"]["global_dtype_histogram"]["bfloat16"]["numel"] -= 1
    _json(path, value)

    with pytest.raises(readiness.ReadinessError, match="capacity BF16 AdamW moment coverage"):
        _validate(ready_project)


def test_readiness_rejects_unbounded_aggregated_optimizer_configuration(ready_project):
    path = ready_project / "artifacts" / f"14b-full-model-gpu-preflight-{GPU_JOB_ID}" / "capacity-gate.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["training_evidence"]["optimizer_state"]["config"]["foreach"] = True
    _json(path, value)

    with pytest.raises(readiness.ReadinessError, match="capacity aggregated optimizer configuration"):
        _validate(ready_project)


def test_readiness_rejects_insufficient_projected_host_memory(ready_project):
    path = ready_project / "artifacts" / f"14b-full-model-gpu-preflight-{GPU_JOB_ID}" / "capacity-gate.json"
    value = json.loads(path.read_text())
    rank_rss = 70 * 1024**3
    for rank in value["ranks"]:
        rank["max_rss_bytes"] = rank_rss
    one_client = rank_rss * 4
    projected_ranks = one_client * readiness.FULL_JOB_CLIENT_COUNT
    projected = (
        projected_ranks
        + value["checkpoint_bytes"] * readiness.SERVER_STATE_COPIES
        + readiness.FIXED_HOST_HEADROOM_GIB * 1024**3
    )
    value["one_client_rank_peak_rss_bytes"] = one_client
    value["projected_full_job_rank_peak_rss_bytes"] = projected_ranks
    value["projected_full_job_host_bytes"] = projected
    value["projected_full_job_host_headroom_bytes"] = readiness.FULL_JOB_MEMORY_GIB * 1024**3 - projected
    _json(path, value)

    with pytest.raises(readiness.ReadinessError, match="exceeds its 512 GiB"):
        _validate(ready_project)


def test_readiness_rejects_model_file_newer_than_verification_marker(ready_project):
    target = ready_project / "models" / readiness.TARGET_MODEL_DIR
    shard = target / f"model-{1:05d}-of-{readiness.TARGET_SHARD_COUNT:05d}.safetensors"
    marker = target / "MANIFEST.sha256.verified"
    newer = marker.stat().st_mtime_ns + 1_000_000
    os.utime(shard, ns=(newer, newer))

    with pytest.raises(readiness.ReadinessError, match="changed after verification"):
        _validate(ready_project)


def test_launchers_pin_resources_timeouts_and_full_model_contract():
    root = Path(__file__).parents[1] / "real_training" / "cs_oci_ord"
    control = (root / "control_plane_preflight.slurm").read_text(encoding="utf-8")
    cpu = (root / "model_14b_full_model_preflight.slurm").read_text(encoding="utf-8")
    gpu = (root / "model_14b_full_model_gpu_preflight.slurm").read_text(encoding="utf-8")
    final = (root / "two_client_14b_full_model.slurm").read_text(encoding="utf-8")
    shared = (root / "two_client_14b.slurm").read_text(encoding="utf-8")

    assert "#SBATCH --no-requeue" in control
    for token in (
        "#SBATCH --mem=128G",
        "#SBATCH --no-requeue",
        "MINIMUM_SLURM_MEMORY_MIB=131072",
        "MINIMUM_SLURM_REMAINING_SECONDS=3300",
        'SLURM_ALLOCATION_MEMORY_MIB="${SLURM_MEM_PER_NODE:-UNSET}"',
        'SLURM_ALLOCATION_END_TIME_EPOCH="${SLURM_JOB_END_TIME:-UNSET}"',
        "slurm_mem_per_node_mib=%s",
        "slurm_job_end_time_epoch=%s",
        "slurm_remaining_seconds_at_check=%s",
        "full_state_server_preflight.py",
        "--expected-parameters 14770033664",
        "--expected-trainable-target all",
        "--expected-state-scope full",
        "--expected-local-steps 8",
        "--expected-max-length 512",
        "--expected-model-revision '${MODEL_REVISION}'",
        "--trainable-target all",
        "--state-scope full",
        "--local-steps 8",
        "--max-length 512",
        "--timeout-seconds 10800",
    ):
        assert token in cpu
    for token in (
        "#SBATCH --gpus-per-node=4",
        "#SBATCH --no-requeue",
        "MINIMUM_SLURM_MEMORY_MIB=262144",
        "MINIMUM_SLURM_REMAINING_SECONDS=3300",
        "REQUIRED_SLURM_GPUS_ON_NODE=4",
        'SLURM_ALLOCATION_GPUS_ON_NODE="${SLURM_GPUS_ON_NODE:-UNSET}"',
        "slurm_gpus_on_node=%s",
        "--expected-trainable-parameters 14770033664",
        "--expected-tensor-count 579",
        "--expected-payload-bytes 29540067328",
        "--full-job-memory-gib 512",
        "--required-fixed-host-headroom-gib 128",
        "--server-state-copies 3",
        "--max-model-ready-seconds 0",
        "--max-work-seconds 0",
    ):
        assert token in gpu
    for token in (
        "#SBATCH --gpus-per-node=8",
        "#SBATCH --mem=512G",
        "#SBATCH --time=02:00:00",
        "#SBATCH --signal=TERM@300",
        "#SBATCH --no-requeue",
        "MINIMUM_SLURM_MEMORY_MIB=524288",
        "MINIMUM_SLURM_REMAINING_SECONDS=6900",
        "REQUIRED_SLURM_GPUS_ON_NODE=8",
        "export SLURM_ALLOCATION_MEMORY_MIB",
        "export SLURM_ALLOCATION_REMAINING_SECONDS",
        "QUALIFICATION_PROFILE=full-model-14b",
        "EXPECTED_TARGET_HIDDEN_SIZE=5120",
        "EXPECTED_TARGET_INTERMEDIATE_SIZE=13824",
        "EXPECTED_TARGET_NUM_HIDDEN_LAYERS=48",
        "EXPECTED_TARGET_NUM_ATTENTION_HEADS=40",
        "EXPECTED_TARGET_NUM_KEY_VALUE_HEADS=8",
        "EXPECTED_TARGET_SAFETENSOR_FILES=8",
        "EXPECTED_TARGET_TENSOR_BYTES=29540067328",
        "EXPECTED_TARGET_PAYLOAD_BYTES=29540067328",
        "EXPECTED_TARGET_TENSOR_COUNT=579",
        "EXPECTED_TARGET_TRAINABLE_PARAMETERS=14770033664",
        "GATE_READY_TIMEOUT=1800",
        "GATE_STALL_TIMEOUT=1800",
        "TARGET_READY_TIMEOUT=1800",
        "TARGET_STALL_TIMEOUT=1800",
    ):
        assert token in final
    for token in (
        "slurm_mem_per_node_mib=%s",
        "slurm_gpus_on_node=%s",
        "slurm_job_end_time_epoch=%s",
        "slurm_allocation_check_time_epoch=%s",
        "slurm_remaining_seconds_at_check=%s",
    ):
        assert token in shared
    assert readiness.REQUIRED_BASE_COMMIT == "a98b517ea63c8181719ff8fd92ab2ca079d915e8"
    assert readiness.EXPECTED_RELEASE == "2026-07-31-full-model-14b-v12"


def test_full_model_runbook_preserves_head_and_lists_real_artifacts():
    runbook = (Path(__file__).parents[1] / "docs" / "cs-oci-ord-two-client-14b-full-model-runbook.md").read_text(
        encoding="utf-8"
    )

    assert 'HEAD_FILE="$BUNDLE.head"' in runbook
    assert 'printf \'%s\\n\' "$EXPECTED_HEAD" > "$HEAD_FILE"' in runbook
    assert runbook.count('export EXPECTED_HEAD="$(cat "$HEAD_FILE")"') == 3
    assert 'export EXPECTED_HEAD="$(git rev-parse HEAD)"' not in runbook
    assert runbook.count('cat "$PREFLIGHT_ARTIFACT/static-readiness.json"') == 1
    assert runbook.count('cat "$GPU_PREFLIGHT_ARTIFACT/static-readiness.json"') == 1
    assert 'cat "$ARTIFACT/allocation-monitor.json"' in runbook
    assert 'test -s "$ARTIFACT/allocation-memory.jsonl"' in runbook
    assert "full-state-evidence.json" not in runbook
    assert "There is no intra-step compute" in runbook
    assert "at most 1,500 seconds" in runbook
    assert "watcher observed a stable nonempty full checkpoint" in runbook
