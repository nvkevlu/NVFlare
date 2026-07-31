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
from pathlib import Path

import pytest

from research.llm_fl_stress.real_training.cs_oci_ord import validate_72b_readiness as readiness

HEAD = "a" * 40
CONTROL_JOB_ID = "101"
CPU_JOB_ID = "102"
GPU_JOB_ID = "103"


def _json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _manifest(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{key}={item}\n" for key, item in value.items()), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_entries_accepts_optional_dot_slash(tmp_path):
    manifest = tmp_path / "MANIFEST.sha256"
    config_digest = "a" * 64
    tokenizer_digest = "b" * 64
    manifest.write_text(
        f"{config_digest}  ./config.json\n{tokenizer_digest}  tokenizer.json\n",
        encoding="utf-8",
    )

    assert readiness._manifest_entries(manifest) == {"config.json", "tokenizer.json"}


def _write_verification_marker(source: Path, marker: Path, protected: list[Path]) -> None:
    marker.write_text(_sha256(source) + "\n", encoding="utf-8")
    latest = max(path.stat().st_mtime_ns for path in [source, *protected])
    os.utime(marker, ns=(latest + 1_000_000, latest + 1_000_000))


def _build_models(project_root: Path) -> tuple[Path, Path, str]:
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
            "hidden_size": 8192,
            "intermediate_size": 29568,
            "num_hidden_layers": 80,
            "num_attention_heads": 64,
            "num_key_value_heads": 8,
        },
    )
    shard_names = [
        f"model-{index:05d}-of-{readiness.TARGET_SHARD_COUNT:05d}.safetensors"
        for index in range(1, readiness.TARGET_SHARD_COUNT + 1)
    ]
    shards = []
    for name in shard_names:
        shard = target / name
        shard.write_bytes(name.encode())
        shards.append(shard)
    index = target / "model.safetensors.index.json"
    _json(
        index,
        {
            "metadata": {"total_size": readiness.TARGET_TENSOR_BYTES},
            "weight_map": {f"parameter.{item}": name for item, name in enumerate(shard_names)},
        },
    )
    tokenizer = target / "tokenizer.json"
    tokenizer.write_text('{"version":"1.0"}\n', encoding="utf-8")
    manifest = target / "MANIFEST.sha256"
    covered = [revision, config, index, tokenizer, *shards]
    manifest.write_text(
        "".join(f"{_sha256(path)}  ./{path.name}\n" for path in covered),
        encoding="utf-8",
    )
    marker = target / "MANIFEST.sha256.verified"
    _write_verification_marker(manifest, marker, covered)
    return gate, target, _sha256(manifest)


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
        },
    )
    _json(
        root / "environment.json",
        {
            "event": "real_training_production_environment",
            "status": "PASS",
            "cuda_device_count": 0,
            "cuda_devices": [],
            "gpu_check_skipped": True,
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
            "gate": None,
            "target": None,
        },
    )


def _build_cpu_artifacts(project_root: Path, target: Path, manifest_sha256: str) -> None:
    root = project_root / "artifacts" / f"72b-preflight-{CPU_JOB_ID}"
    _manifest(
        root / "manifest.txt",
        {
            "job_id": CPU_JOB_ID,
            "status": "PASS",
            "model_path": target,
            "model_revision": readiness.TARGET_MODEL_REVISION,
            "expected_payload_bytes": readiness.TARGET_PAYLOAD_BYTES,
            "max_payload_bytes": 2 * 1024**3,
            "exported_job_timeout_seconds": readiness.OPERATION_TIMEOUT_SECONDS,
            "model_manifest_verified": "PASS",
            "model_manifest_sha256": manifest_sha256,
            "git_commit": HEAD,
        },
    )
    _json(
        root / "model-manifest-verification.json",
        {
            "event": "real_training_model_manifest_verification",
            "status": "PASS",
            "manifest_sha256": manifest_sha256,
        },
    )
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
        root / "trainable-server-preflight.json",
        {
            "event": "real_training_trainable_server_preflight",
            "status": "PASS",
            "model_path": str(target),
            "model_revision": readiness.TARGET_MODEL_REVISION,
            "safetensor_file_count": readiness.TARGET_SHARD_COUNT,
            "max_payload_bytes": 2 * 1024**3,
            "safetensor_structure": {
                "index_total_size_bytes": readiness.TARGET_TENSOR_BYTES,
                "computed_tensor_bytes": readiness.TARGET_TENSOR_BYTES,
                "validated_safetensor_file_count": readiness.TARGET_SHARD_COUNT,
            },
            "state": {"payload_bytes": readiness.TARGET_PAYLOAD_BYTES},
        },
    )
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
            "state_scope": "trainable",
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
        },
    )


def _capacity(target: Path) -> dict:
    gib = 1024**3
    checkpoint_bytes = sum(path.stat().st_size for path in target.glob("model*.safetensors"))
    rank = {
        "gpu_name": "NVIDIA A100-SXM4-80GB",
        "reserved_headroom_bytes": readiness.GPU_HEADROOM_MIB * 1024**2,
        "max_rss_bytes": gib,
        "model_ready_seconds": 100.0,
        "post_ready_work_seconds": 50.0,
        "loss": 1.0,
        "selected_max_abs_change": 1.0e-5,
    }
    one_client_rank_peak_rss_bytes = 4 * gib
    projected_full_job_rank_peak_rss_bytes = one_client_rank_peak_rss_bytes * readiness.FULL_JOB_CLIENT_COUNT
    projected_full_job_host_bytes = (
        projected_full_job_rank_peak_rss_bytes + checkpoint_bytes + readiness.FIXED_HOST_HEADROOM_GIB * gib
    )
    full_job_memory_bytes = readiness.FULL_JOB_MEMORY_GIB * gib
    return {
        "event": "real_model_fsdp2_gpu_capacity_gate",
        "status": "PASS",
        "model_path": str(target),
        "model_revision": readiness.TARGET_MODEL_REVISION,
        "world_size": 4,
        "trainable_target": "last-layer",
        "local_steps": 2,
        "max_length": 128,
        "payload_bytes": readiness.TARGET_PAYLOAD_BYTES,
        "tensor_count": 12,
        "required_headroom_mib": readiness.GPU_HEADROOM_MIB,
        "full_job_memory_gib": readiness.FULL_JOB_MEMORY_GIB,
        "full_job_memory_bytes": readiness.FULL_JOB_MEMORY_GIB * 1024**3,
        "full_job_client_count": readiness.FULL_JOB_CLIENT_COUNT,
        "required_fixed_host_headroom_gib": readiness.FIXED_HOST_HEADROOM_GIB,
        "required_fixed_host_headroom_bytes": readiness.FIXED_HOST_HEADROOM_GIB * 1024**3,
        "checkpoint_bytes": checkpoint_bytes,
        "one_client_rank_peak_rss_bytes": one_client_rank_peak_rss_bytes,
        "projected_full_job_rank_peak_rss_bytes": projected_full_job_rank_peak_rss_bytes,
        "projected_full_job_host_bytes": projected_full_job_host_bytes,
        "projected_full_job_host_headroom_bytes": full_job_memory_bytes - projected_full_job_host_bytes,
        "max_model_ready_seconds": readiness.MAX_MODEL_READY_SECONDS,
        "observed_max_model_ready_seconds": 100.0,
        "max_work_seconds": readiness.MAX_WORK_SECONDS,
        "observed_max_work_seconds": 50.0,
        "initial_state": {
            "tensor_count": 12,
            "payload_bytes": readiness.TARGET_PAYLOAD_BYTES,
            "sha256": "1" * 64,
        },
        "final_state": {
            "tensor_count": 12,
            "payload_bytes": readiness.TARGET_PAYLOAD_BYTES,
            "sha256": "2" * 64,
        },
        "ranks": [{"rank": index, "local_rank": index, **rank} for index in range(4)],
    }


def _build_gpu_artifacts(project_root: Path, target: Path) -> None:
    root = project_root / "artifacts" / f"72b-gpu-preflight-{GPU_JOB_ID}"
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
            "expected_payload_bytes": readiness.TARGET_PAYLOAD_BYTES,
            "required_headroom_mib": readiness.GPU_HEADROOM_MIB,
            "full_job_memory_gib": readiness.FULL_JOB_MEMORY_GIB,
            "full_job_client_count": readiness.FULL_JOB_CLIENT_COUNT,
            "required_fixed_host_headroom_gib": readiness.FIXED_HOST_HEADROOM_GIB,
            "max_model_ready_seconds": readiness.MAX_MODEL_READY_SECONDS,
            "max_work_seconds": readiness.MAX_WORK_SECONDS,
            "git_commit": HEAD,
        },
    )
    _json(root / "capacity-gate.json", _capacity(target))


@pytest.fixture
def ready_project(tmp_path, monkeypatch):
    project_root = tmp_path.resolve()
    container = project_root / "containers" / "pytorch-25.01-py3.sqsh"
    container.parent.mkdir(parents=True)
    container.write_bytes(b"squashfs")
    checksum = container.with_suffix(container.suffix + ".sha256")
    checksum.write_text(f"{_sha256(container)}  {container.name}\n", encoding="utf-8")
    _write_verification_marker(
        checksum,
        container.with_suffix(container.suffix + ".sha256.verified"),
        [container],
    )
    python = project_root / "envs" / "nvflare-fsdp2" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)
    (python.parent.parent / "requirements.lock").write_text(
        "torch==2.12.0+cu126\n" "torchvision==0.27.0+cu126\n" "transformers==4.57.6\n",
        encoding="utf-8",
    )
    (project_root / "logs").mkdir()
    (project_root / "artifacts").mkdir()

    release = (
        project_root / "repos" / "NVFlare" / "research" / "llm_fl_stress" / "real_training" / "QUALIFICATION_RELEASE"
    )
    release.parent.mkdir(parents=True)
    release.write_text(readiness.EXPECTED_RELEASE + "\n", encoding="utf-8")
    monkeypatch.setattr(
        readiness,
        "_repo_state",
        lambda _repo: {"head": HEAD, "branch": readiness.EXPECTED_BRANCH, "status": ""},
    )

    gate, target, manifest_sha256 = _build_models(project_root)
    _build_control_artifacts(project_root, gate)
    _build_cpu_artifacts(project_root, target, manifest_sha256)
    _build_gpu_artifacts(project_root, target)
    return project_root


def _validate(project_root: Path, *, environ=None):
    return readiness.validate_readiness(
        project_root,
        control_job_id=CONTROL_JOB_ID,
        cpu_job_id=CPU_JOB_ID,
        gpu_job_id=GPU_JOB_ID,
        environ={} if environ is None else environ,
    )


def test_readiness_accepts_complete_exact_evidence(ready_project):
    result = _validate(ready_project)

    assert result["status"] == "PASS"
    assert result["git_commit"] == HEAD
    assert result["safe_to_submit"] is True


def test_readiness_rejects_stale_artifact_commit(ready_project):
    manifest_path = ready_project / "artifacts" / f"72b-gpu-preflight-{GPU_JOB_ID}" / "manifest.txt"
    manifest_path.write_text(manifest_path.read_text().replace(HEAD, "b" * 40), encoding="utf-8")

    with pytest.raises(readiness.ReadinessError, match="git_commit"):
        _validate(ready_project)


def test_readiness_requires_nccl_override_to_be_unset(ready_project):
    with pytest.raises(readiness.ReadinessError, match="must be unset"):
        _validate(ready_project, environ={"NCCL_P2P_DISABLE": ""})


def test_readiness_rejects_model_changed_after_verification(ready_project):
    target = ready_project / "models" / readiness.TARGET_MODEL_DIR
    shard = target / f"model-{1:05d}-of-{readiness.TARGET_SHARD_COUNT:05d}.safetensors"
    marker = target / "MANIFEST.sha256.verified"
    newer = marker.stat().st_mtime_ns + 1_000_000
    os.utime(shard, ns=(newer, newer))

    with pytest.raises(readiness.ReadinessError, match="changed after manifest verification"):
        _validate(ready_project)


def test_readiness_rejects_missing_file_listed_in_manifest(ready_project):
    target = ready_project / "models" / readiness.TARGET_MODEL_DIR
    (target / "tokenizer.json").unlink()

    with pytest.raises(readiness.ReadinessError, match="not a non-empty regular file"):
        _validate(ready_project)


def test_readiness_rejects_unmanifested_model_sidecar(ready_project):
    target = ready_project / "models" / readiness.TARGET_MODEL_DIR
    (target / "tokenizer_config.json").write_text('{"new":true}\n', encoding="utf-8")

    with pytest.raises(readiness.ReadinessError, match="file set differs"):
        _validate(ready_project)


def test_readiness_rejects_insufficient_projected_host_headroom(ready_project):
    capacity_path = ready_project / "artifacts" / f"72b-gpu-preflight-{GPU_JOB_ID}" / "capacity-gate.json"
    capacity = json.loads(capacity_path.read_text())
    gib = 1024**3
    for rank in capacity["ranks"]:
        rank["max_rss_bytes"] = 900 * gib
    one_client = sum(rank["max_rss_bytes"] for rank in capacity["ranks"])
    projected_ranks = one_client * readiness.FULL_JOB_CLIENT_COUNT
    projected = projected_ranks + capacity["checkpoint_bytes"] + readiness.FIXED_HOST_HEADROOM_GIB * gib
    capacity["one_client_rank_peak_rss_bytes"] = one_client
    capacity["projected_full_job_rank_peak_rss_bytes"] = projected_ranks
    capacity["projected_full_job_host_bytes"] = projected
    capacity["projected_full_job_host_headroom_bytes"] = readiness.FULL_JOB_MEMORY_GIB * gib - projected
    _json(capacity_path, capacity)

    with pytest.raises(readiness.ReadinessError, match="exceeds its host memory allocation"):
        _validate(ready_project)
