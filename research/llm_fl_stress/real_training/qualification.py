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

"""Fail-closed small-model gate and large-model run using real provisioned NVFLARE services."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from argparse import Namespace
from pathlib import Path
from typing import Any

REAL_TRAINING_DIR = Path(__file__).resolve().parent
CONTROL_PLANE_CLIENT = REAL_TRAINING_DIR / "control_plane_client.py"
if str(REAL_TRAINING_DIR) not in sys.path:
    sys.path.insert(0, str(REAL_TRAINING_DIR))

from config import RealTrainingConfig  # noqa: E402
from evidence import validate_production_evidence, validate_trainable_state_evidence  # noqa: E402
from job import DATA_FILES, _build_recipe  # noqa: E402
from provisioned import (  # noqa: E402
    ADMIN_NAME,
    CLIENT_NAMES,
    SERVER_NAME,
    LocalProductionFederation,
    PersistedModelWatcher,
)
from state_evidence import file_sha256, inspect_persisted_checkpoint  # noqa: E402

_PROFILES = ("full-state", "trainable-multiround", "trainable-32b")
_TRAINABLE_PAYLOAD_CEILING_BYTES = 1024 * 1024 * 1024
_CLIENT_OPERATION_TIMEOUT_SECONDS = 2400
_PERSISTENCE_TIMEOUT_SECONDS = 2400.0
_MIN_32B_READY_TIMEOUT_SECONDS = 1800.0
_MIN_32B_STALL_TIMEOUT_SECONDS = 900.0


def _profile_settings(profile: str) -> dict[str, Any]:
    if profile == "full-state":
        return {
            "gate_rounds": 1,
            "target_rounds": 1,
            "local_steps": 1,
            "state_scope": "full",
            "target_name": "target-14b",
        }
    if profile == "trainable-multiround":
        return {
            "gate_rounds": 2,
            "target_rounds": 3,
            "local_steps": 4,
            "state_scope": "trainable",
            "target_name": "target-14b",
        }
    if profile == "trainable-32b":
        return {
            "gate_rounds": 2,
            "target_rounds": 1,
            "local_steps": 2,
            "state_scope": "trainable",
            "target_name": "target-32b",
        }
    raise ValueError(f"unsupported qualification profile: {profile}")


def _validate_profile_timeouts(
    profile: str,
    *,
    target_ready_timeout: float,
    target_stall_timeout: float,
) -> None:
    """Reject known-unsafe 32B watchdog settings before services or GPUs start."""

    if profile != "trainable-32b":
        return
    if target_ready_timeout < _MIN_32B_READY_TIMEOUT_SECONDS:
        raise ValueError(
            "trainable-32b target_ready_timeout must be at least "
            f"{_MIN_32B_READY_TIMEOUT_SECONDS}s, got {target_ready_timeout}s"
        )
    if target_stall_timeout < _MIN_32B_STALL_TIMEOUT_SECONDS:
        raise ValueError(
            "trainable-32b target_stall_timeout must be at least "
            f"{_MIN_32B_STALL_TIMEOUT_SECONDS}s, got {target_stall_timeout}s"
        )


class _GpuMonitor:
    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.process: subprocess.Popen | None = None
        self.stream = None
        self.return_code_before_shutdown: int | None = None

    def start(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.output_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [
                "nvidia-smi",
                "--query-gpu=timestamp,index,uuid,name,memory.used,utilization.gpu",
                "--format=csv",
                "--loop=5",
            ],
            stdout=self.stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
        time.sleep(0.25)
        self.return_code_before_shutdown = self.process.poll()
        if self.return_code_before_shutdown is not None:
            self.stream.flush()
            raise RuntimeError(
                f"nvidia-smi utilization monitor exited with {self.return_code_before_shutdown}: "
                f"{self.output_path.read_text(encoding='utf-8', errors='replace')}"
            )

    def close(self) -> dict[str, Any]:
        if self.process is not None:
            observed_return_code = self.process.poll()
            if observed_return_code is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5.0)
            else:
                self.return_code_before_shutdown = observed_return_code
        if self.stream is not None:
            self.stream.close()
        size_bytes = self.output_path.stat().st_size if self.output_path.is_file() else 0
        sample_lines = 0
        samples_per_gpu: dict[int, int] = {}
        peak_utilization_percent: dict[int, int] = {}
        peak_memory_mib: dict[int, int] = {}
        if size_bytes:
            with self.output_path.open(encoding="utf-8", errors="replace") as stream:
                for record in csv.DictReader(stream, skipinitialspace=True):
                    try:
                        index = int(record["index"].strip())
                        utilization = int(record["utilization.gpu [%]"].split()[0])
                        memory_mib = int(record["memory.used [MiB]"].split()[0])
                    except (KeyError, TypeError, ValueError):
                        continue
                    sample_lines += 1
                    samples_per_gpu[index] = samples_per_gpu.get(index, 0) + 1
                    peak_utilization_percent[index] = max(
                        peak_utilization_percent.get(index, 0),
                        utilization,
                    )
                    peak_memory_mib[index] = max(peak_memory_mib.get(index, 0), memory_mib)
        observed_gpu_indices = sorted(samples_per_gpu)
        active_gpu_indices = sorted(
            index
            for index in observed_gpu_indices
            if peak_utilization_percent.get(index, 0) > 0 and peak_memory_mib.get(index, 0) > 0
        )
        status = (
            "PASS"
            if self.process is not None
            and self.return_code_before_shutdown is None
            and observed_gpu_indices == list(range(8))
            and active_gpu_indices == list(range(8))
            else "FAIL"
        )
        return {
            "event": "real_training_gpu_monitor",
            "status": status,
            "output_path": str(self.output_path),
            "output_size_bytes": size_bytes,
            "sample_lines": sample_lines,
            "observed_gpu_indices": observed_gpu_indices,
            "active_gpu_indices": active_gpu_indices,
            "samples_per_gpu": {str(index): samples_per_gpu[index] for index in observed_gpu_indices},
            "peak_utilization_percent": {str(index): peak_utilization_percent[index] for index in observed_gpu_indices},
            "peak_memory_mib": {str(index): peak_memory_mib[index] for index in observed_gpu_indices},
            "return_code_before_shutdown": self.return_code_before_shutdown,
        }


def _define_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-model-path", required=True, type=Path)
    parser.add_argument("--gate-model-revision", required=True)
    parser.add_argument("--target-model-path", required=True, type=Path)
    parser.add_argument("--target-model-revision", required=True)
    parser.add_argument("--expected-target-hidden-size", type=int, default=0)
    parser.add_argument("--expected-target-num-hidden-layers", type=int, default=0)
    parser.add_argument("--expected-target-min-weight-bytes", type=int, default=0)
    parser.add_argument("--expected-target-safetensor-files", type=int, default=0)
    parser.add_argument("--expected-target-payload-bytes", type=int, default=0)
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--expected-gpu-name-substring", default="A100-SXM4-80GB")
    parser.add_argument("--profile", choices=_PROFILES, default="full-state")
    parser.add_argument("--service-startup-timeout", type=float, default=90.0)
    parser.add_argument("--gate-ready-timeout", type=float, default=120.0)
    parser.add_argument("--gate-stall-timeout", type=float, default=300.0)
    parser.add_argument("--target-ready-timeout", type=float, default=300.0)
    parser.add_argument("--target-stall-timeout", type=float, default=300.0)
    parser.add_argument(
        "--control-plane-only",
        action="store_true",
        help="Provision services and require both clients through the admin API without submitting a GPU job.",
    )
    return parser


def _require_revision(model_path: Path, expected_revision: str) -> None:
    revision_path = model_path / "REVISION"
    if not revision_path.is_file():
        raise RuntimeError(f"staged model is missing REVISION: {revision_path}")
    observed = revision_path.read_text(encoding="utf-8").strip()
    if observed != expected_revision:
        raise RuntimeError(
            f"staged model revision mismatch for {model_path}: expected {expected_revision}, observed {observed}"
        )


def _require_target_identity(
    model_path: Path,
    *,
    expected_hidden_size: int,
    expected_num_hidden_layers: int,
    expected_min_weight_bytes: int,
    expected_safetensor_files: int = 0,
) -> dict[str, Any]:
    config_path = model_path / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    observed = {
        "architectures": config.get("architectures"),
        "hidden_size": config.get("hidden_size"),
        "model_type": config.get("model_type"),
        "num_hidden_layers": config.get("num_hidden_layers"),
        "torch_dtype": config.get("torch_dtype"),
    }
    if expected_hidden_size and observed["hidden_size"] != expected_hidden_size:
        raise RuntimeError(
            f"target hidden_size mismatch: expected {expected_hidden_size}, observed {observed['hidden_size']}"
        )
    if expected_num_hidden_layers and observed["num_hidden_layers"] != expected_num_hidden_layers:
        raise RuntimeError(
            "target num_hidden_layers mismatch: "
            f"expected {expected_num_hidden_layers}, observed {observed['num_hidden_layers']}"
        )
    if expected_hidden_size or expected_num_hidden_layers:
        if (
            observed["architectures"] != ["Qwen2ForCausalLM"]
            or observed["model_type"] != "qwen2"
            or observed["torch_dtype"] != "bfloat16"
        ):
            raise RuntimeError(f"target architecture or dtype mismatch: {observed}")

    weight_files = sorted(model_path.glob("model*.safetensors"))
    if expected_safetensor_files and len(weight_files) != expected_safetensor_files:
        raise RuntimeError(
            f"target safetensor file-count mismatch: expected {expected_safetensor_files}, "
            f"observed {len(weight_files)}"
        )
    weight_bytes = sum(path.stat().st_size for path in weight_files)
    if expected_min_weight_bytes and weight_bytes < expected_min_weight_bytes:
        raise RuntimeError(
            f"target safetensor bytes below minimum: expected at least {expected_min_weight_bytes}, "
            f"observed {weight_bytes}"
        )
    return {
        **observed,
        "safetensor_file_count": len(weight_files),
        "safetensor_bytes": weight_bytes,
    }


def _require_payload_bytes(phase: str, observed: int, expected: int) -> None:
    if expected and observed != expected:
        raise RuntimeError(f"{phase} trainable payload mismatch: expected {expected}, observed {observed}")


def _phase_args(
    model_path: Path,
    model_revision: str,
    phase_root: Path,
    *,
    num_rounds: int = 1,
    local_steps: int = 1,
    state_scope: str = "full",
) -> Namespace:
    return Namespace(
        model_name_or_path=model_path,
        model_revision=model_revision,
        workspace_root=phase_root / "unused-workspace",
        export_root=phase_root / "unused-export",
        num_clients=2,
        nproc_per_node=4,
        num_rounds=num_rounds,
        local_steps=local_steps,
        max_length=128,
        learning_rate=1.0e-5,
        trainable_target="last-layer",
        run_mode="train",
        state_scope=state_scope,
        timeout_seconds=_CLIENT_OPERATION_TIMEOUT_SECONDS,
        expected_gpu_name_substring=None,
    )


def _validate_phase_inputs(
    model_path: Path,
    model_revision: str,
    phase_root: Path,
    *,
    num_rounds: int = 1,
    local_steps: int = 1,
    state_scope: str = "full",
) -> None:
    config = RealTrainingConfig(
        model_path=model_path,
        workspace_root=phase_root / "unused-workspace",
        export_root=phase_root / "unused-export",
        num_clients=2,
        nproc_per_node=4,
        num_rounds=num_rounds,
        local_steps=local_steps,
        max_length=128,
        learning_rate=1.0e-5,
        trainable_target="last-layer",
        run_mode="train",
        state_scope=state_scope,
    )
    config.validate(require_model_files=True)
    _require_revision(model_path, model_revision)


def _environment_check(expected_gpu_name_substring: str, *, require_gpus: bool) -> dict[str, Any]:
    import torch

    if os.environ.get("NCCL_P2P_DISABLE"):
        raise RuntimeError(
            f"refusing inherited NCCL_P2P_DISABLE={os.environ['NCCL_P2P_DISABLE']}; use cluster NCCL defaults"
        )
    count = torch.cuda.device_count()
    names = [torch.cuda.get_device_name(index) for index in range(count)]
    if not require_gpus:
        return {
            "event": "real_training_production_environment",
            "status": "PASS",
            "cuda_device_count": count,
            "cuda_devices": names,
            "gpu_check_skipped": True,
            "torch_version": torch.__version__,
            "torch_cuda_version": torch.version.cuda,
        }
    if count != 8:
        raise RuntimeError(f"qualification requires exactly 8 visible GPUs, found {count}: {names}")
    mismatches = [name for name in names if expected_gpu_name_substring not in name]
    if mismatches:
        raise RuntimeError(f"GPU names must contain {expected_gpu_name_substring!r}; mismatched devices: {mismatches}")
    return {
        "event": "real_training_production_environment",
        "status": "PASS",
        "cuda_device_count": count,
        "cuda_devices": names,
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_phase(
    federation: LocalProductionFederation,
    *,
    name: str,
    model_path: Path,
    model_revision: str,
    evidence_root: Path,
    expected_gpu_name_substring: str,
    ready_timeout: float,
    stall_timeout: float,
    expected_payload_bytes: int = 0,
    num_rounds: int = 1,
    local_steps: int = 1,
    state_scope: str = "full",
) -> dict[str, Any]:
    from nvflare.recipe.prod_env import ProdEnv

    phase_root = evidence_root / name
    phase_root.mkdir(parents=True, exist_ok=False)
    _write_json(
        phase_root / "configuration.json",
        {
            "event": "real_training_production_phase_configuration",
            "phase": name,
            "model_path": str(model_path),
            "model_revision": model_revision,
            "ready_timeout_seconds": ready_timeout,
            "stall_timeout_seconds": stall_timeout,
            "client_operation_timeout_seconds": _CLIENT_OPERATION_TIMEOUT_SECONDS,
            "persistence_timeout_seconds": _PERSISTENCE_TIMEOUT_SECONDS,
            "num_clients": 2,
            "nproc_per_client": 4,
            "num_rounds": num_rounds,
            "local_steps": local_steps,
            "state_scope": state_scope,
            "dataset_sha256": (
                {site_name: file_sha256(path) for site_name, path in DATA_FILES.items()}
                if state_scope == "trainable"
                else None
            ),
            "gpu_mapping": {"site-1": [0, 1, 2, 3], "site-2": [4, 5, 6, 7]},
            "execution_environment": "ProdEnv",
        },
    )
    started_at = time.monotonic()
    job_id = None
    watcher = None
    try:
        recipe = _build_recipe(
            _phase_args(
                model_path,
                model_revision,
                phase_root,
                num_rounds=num_rounds,
                local_steps=local_steps,
                state_scope=state_scope,
            )
        )
        environment = ProdEnv(
            startup_kit_location=str(federation.admin_kit),
            login_timeout=10.0,
            username=ADMIN_NAME,
            study="default",
        )
        run = recipe.run(environment)
        job_id = run.get_job_id()
        watcher = PersistedModelWatcher(
            federation,
            job_id,
            phase_root / "persistence",
            expected_count=num_rounds,
            checkpoint_inspector=inspect_persisted_checkpoint if state_scope == "trainable" else None,
            model_file_timeout=_PERSISTENCE_TIMEOUT_SECONDS,
        )
        watcher.start()
        _write_json(
            phase_root / "submitted.json",
            {
                "event": "real_training_production_submitted",
                "job_id": job_id,
                "model_path": str(model_path),
                "model_revision": model_revision,
                "phase": name,
            },
        )
        status = federation.wait_for_run(
            run,
            model_path=model_path,
            ready_timeout=ready_timeout,
            stall_timeout=stall_timeout,
        )
        persisted_models = watcher.wait_all(timeout=_PERSISTENCE_TIMEOUT_SECONDS)
        persisted = persisted_models[-1]
        collected_roots = federation.collect_job_logs(job_id, phase_root / "logs")
        roots = {site_name: collected_roots[site_name] for site_name in CLIENT_NAMES}
        evidence = validate_production_evidence(
            client_roots=roots,
            server_root=collected_roots[SERVER_NAME],
            site_names=list(CLIENT_NAMES),
            model_path=model_path,
            run_mode="train",
            nproc_per_client=4,
            num_rounds=num_rounds,
            expected_gpu_name_substring=expected_gpu_name_substring,
        )
        trainable_evidence = None
        if state_scope == "trainable":
            trainable_evidence = validate_trainable_state_evidence(
                client_roots=roots,
                site_names=list(CLIENT_NAMES),
                model_path=model_path,
                num_rounds=num_rounds,
                local_steps=local_steps,
                nproc_per_client=4,
                expected_dataset_sha256={site_name: file_sha256(path) for site_name, path in DATA_FILES.items()},
                persisted_models=persisted_models,
                max_payload_bytes=_TRAINABLE_PAYLOAD_CEILING_BYTES,
            )
            observed_payload_bytes = trainable_evidence["payload_bytes_per_transfer"]
            _require_payload_bytes(name, observed_payload_bytes, expected_payload_bytes)
            _write_json(phase_root / "trainable-state-evidence.json", trainable_evidence)
        summary = {
            **evidence,
            "phase": name,
            "job_id": job_id,
            "job_status": status,
            "model_path": str(model_path),
            "model_revision": model_revision,
            "persisted_model": persisted,
            "persisted_models": persisted_models,
            "trainable_state_evidence": trainable_evidence,
            "state_scope": state_scope,
            "num_rounds": num_rounds,
            "local_steps": local_steps,
            "elapsed_seconds": time.monotonic() - started_at,
            "execution_environment": "ProdEnv",
            "service_topology": "localhost-tls-server-plus-two-real-clients",
        }
        _write_json(phase_root / "summary.json", summary)
        print(json.dumps(summary, sort_keys=True), flush=True)
        return summary
    except Exception as exc:
        failure = {
            "event": "real_training_production_phase_failure",
            "status": "FAIL",
            "phase": name,
            "job_id": job_id,
            "model_path": str(model_path),
            "model_revision": model_revision,
            "ready_timeout_seconds": ready_timeout,
            "stall_timeout_seconds": stall_timeout,
            "state_scope": state_scope,
            "num_rounds": num_rounds,
            "local_steps": local_steps,
            "elapsed_seconds": time.monotonic() - started_at,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        if job_id is not None:
            try:
                federation.collect_job_logs(job_id, phase_root / "failure-logs")
                failure["failure_logs_collected"] = True
            except Exception as collection_error:
                failure["failure_logs_collected"] = False
                failure["log_collection_error"] = f"{type(collection_error).__name__}: {collection_error}"
        _write_json(phase_root / "failure.json", failure)
        print(json.dumps(failure, sort_keys=True), flush=True)
        raise
    finally:
        if watcher is not None:
            watcher.close()


def _build_control_plane_recipe(sequence: int):
    from nvflare.app_common.np.recipes.fedavg import NumpyFedAvgRecipe

    recipe = NumpyFedAvgRecipe(
        name=f"llm_real_services_control_plane_{sequence}",
        min_clients=2,
        num_rounds=1,
        model=[[1.0, 2.0], [3.0, 4.0]],
        train_script=str(CONTROL_PLANE_CLIENT),
        shutdown_timeout=10.0,
        key_metric="smoke_metric",
    )
    recipe.add_client_config(
        {
            "get_task_timeout": 60.0,
            "max_runner_sync_timeout": 60.0,
            "runner_sync_timeout": 5.0,
            "submit_task_result_timeout": 60.0,
        }
    )
    return recipe


def _run_control_plane_job(
    federation: LocalProductionFederation,
    evidence_root: Path,
    sequence: int,
) -> dict[str, Any]:
    from nvflare.recipe.prod_env import ProdEnv

    destination = evidence_root / f"control-plane-job-{sequence}"
    destination.mkdir(parents=True, exist_ok=False)
    started_at = time.monotonic()
    job_id = None
    try:
        environment = ProdEnv(
            startup_kit_location=str(federation.admin_kit),
            login_timeout=10.0,
            username=ADMIN_NAME,
            study="default",
        )
        run = _build_control_plane_recipe(sequence).run(environment)
        job_id = run.get_job_id()
        _write_json(
            destination / "submitted.json",
            {
                "event": "real_training_production_control_plane_submitted",
                "job_id": job_id,
                "sequence": sequence,
                "sites": list(CLIENT_NAMES),
            },
        )
        status = federation.wait_for_terminal(run, total_timeout=90.0)
        sites = set()
        for site_name in CLIENT_NAMES:
            events = list(
                {
                    json.dumps(event, sort_keys=True): event
                    for event in federation.job_events(site_name, job_id, "real_training_control_plane_round")
                }.values()
            )
            if len(events) != 1 or events[0].get("status") != "PASS" or events[0].get("site_name") != site_name:
                raise RuntimeError(f"control-plane job has invalid {site_name} evidence: {events}")
            sites.add(site_name)
        server_text = federation.service_job_text(SERVER_NAME, job_id)
        if "Aggregated 2/2 results" not in server_text:
            raise RuntimeError("control-plane job did not aggregate both client results")
        federation.collect_job_logs(job_id, destination)
        summary = {
            "aggregated_results": 2,
            "event": "real_training_production_control_plane_job",
            "execution_environment": "ProdEnv",
            "job_id": job_id,
            "job_status": status,
            "sequence": sequence,
            "sites": sorted(sites),
            "status": "PASS",
        }
        _write_json(destination / "summary.json", summary)
        print(json.dumps(summary, sort_keys=True), flush=True)
        return summary
    except Exception as exc:
        failure = {
            "event": "real_training_production_control_plane_failure",
            "status": "FAIL",
            "job_id": job_id,
            "sequence": sequence,
            "elapsed_seconds": time.monotonic() - started_at,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
        if job_id is not None:
            try:
                federation.collect_job_logs(job_id, destination / "failure-logs")
                failure["failure_logs_collected"] = True
            except Exception as collection_error:
                failure["failure_logs_collected"] = False
                failure["log_collection_error"] = f"{type(collection_error).__name__}: {collection_error}"
        _write_json(destination / "failure.json", failure)
        print(json.dumps(failure, sort_keys=True), flush=True)
        raise


def _install_signal_handlers() -> None:
    def _interrupted(signum, _frame):
        raise InterruptedError(f"qualification interrupted by signal {signum}")

    signal.signal(signal.SIGTERM, _interrupted)
    signal.signal(signal.SIGINT, _interrupted)


def _cleanup_private_root(private_root: Path) -> None:
    marker = private_root / ".nvflare-qualification-private"
    if marker.is_file():
        shutil.rmtree(private_root)


def main() -> int:
    args = _define_parser().parse_args()
    args.private_root = args.private_root.resolve()
    args.evidence_root = args.evidence_root.resolve()
    args.gate_model_path = args.gate_model_path.resolve()
    args.target_model_path = args.target_model_path.resolve()
    args.evidence_root.mkdir(parents=True, exist_ok=True)
    _install_signal_handlers()

    result_path = args.evidence_root / "qualification.json"
    monitor = _GpuMonitor(args.evidence_root / "gpu-samples.csv")
    result: dict[str, Any] = {
        "event": "real_training_production_qualification",
        "status": "FAIL",
        "profile": args.profile,
        "gate": None,
        "target": None,
    }
    exit_code = 1
    _write_json(
        args.evidence_root / "configuration.json",
        {
            "event": "real_training_production_configuration",
            "control_plane_only": args.control_plane_only,
            "profile": args.profile,
            "gate_model_path": str(args.gate_model_path),
            "gate_model_revision": args.gate_model_revision,
            "target_model_path": str(args.target_model_path),
            "target_model_revision": args.target_model_revision,
            "expected_target_hidden_size": args.expected_target_hidden_size,
            "expected_target_num_hidden_layers": args.expected_target_num_hidden_layers,
            "expected_target_min_weight_bytes": args.expected_target_min_weight_bytes,
            "expected_target_safetensor_files": args.expected_target_safetensor_files,
            "expected_target_payload_bytes": args.expected_target_payload_bytes,
            "expected_gpu_name_substring": args.expected_gpu_name_substring,
            "service_startup_timeout_seconds": args.service_startup_timeout,
            "gate_ready_timeout_seconds": args.gate_ready_timeout,
            "gate_stall_timeout_seconds": args.gate_stall_timeout,
            "target_ready_timeout_seconds": args.target_ready_timeout,
            "target_stall_timeout_seconds": args.target_stall_timeout,
            "service_topology": "localhost-tls-server-plus-two-real-clients",
            "execution_environment": "ProdEnv",
            "gpu_mapping": {"site-1": [0, 1, 2, 3], "site-2": [4, 5, 6, 7]},
        },
    )
    try:
        profile = _profile_settings(args.profile)
        if not args.control_plane_only:
            _validate_profile_timeouts(
                args.profile,
                target_ready_timeout=args.target_ready_timeout,
                target_stall_timeout=args.target_stall_timeout,
            )
        gate_rounds = profile["gate_rounds"]
        target_rounds = profile["target_rounds"]
        local_steps = profile["local_steps"]
        state_scope = profile["state_scope"]
        target_name = profile["target_name"]
        if not args.control_plane_only:
            target_identity = _require_target_identity(
                args.target_model_path,
                expected_hidden_size=args.expected_target_hidden_size,
                expected_num_hidden_layers=args.expected_target_num_hidden_layers,
                expected_min_weight_bytes=args.expected_target_min_weight_bytes,
                expected_safetensor_files=args.expected_target_safetensor_files,
            )
            _write_json(args.evidence_root / "target-identity.json", target_identity)
            _validate_phase_inputs(
                args.gate_model_path,
                args.gate_model_revision,
                args.evidence_root / "gate",
                num_rounds=gate_rounds,
                local_steps=local_steps,
                state_scope=state_scope,
            )
            _validate_phase_inputs(
                args.target_model_path,
                args.target_model_revision,
                args.evidence_root / "target",
                num_rounds=target_rounds,
                local_steps=local_steps,
                state_scope=state_scope,
            )
        environment = _environment_check(
            args.expected_gpu_name_substring,
            require_gpus=not args.control_plane_only,
        )
        _write_json(args.evidence_root / "environment.json", environment)
        print(json.dumps(environment, sort_keys=True), flush=True)
        if not args.control_plane_only:
            monitor.start()

        with LocalProductionFederation(
            private_root=args.private_root,
            evidence_root=args.evidence_root / "services",
            startup_timeout=args.service_startup_timeout,
        ) as federation:
            connected = federation.wait_for_clients()
            control_plane = {
                "event": "real_training_production_control_plane",
                "status": "PASS",
                "connected_clients": connected,
                "execution_environment": "ProdEnv",
                "transport": "provisioned-tls",
            }
            _write_json(args.evidence_root / "control-plane.json", control_plane)
            print(json.dumps(control_plane, sort_keys=True), flush=True)
            if args.control_plane_only:
                control_plane_jobs = [
                    _run_control_plane_job(federation, args.evidence_root, sequence) for sequence in (1, 2)
                ]
                result.update(
                    status="PASS",
                    control_plane_only=True,
                    control_plane_jobs=control_plane_jobs,
                )
            else:
                result["gate"] = _run_phase(
                    federation,
                    name="gate-1.5b",
                    model_path=args.gate_model_path,
                    model_revision=args.gate_model_revision,
                    evidence_root=args.evidence_root,
                    expected_gpu_name_substring=args.expected_gpu_name_substring,
                    ready_timeout=args.gate_ready_timeout,
                    stall_timeout=args.gate_stall_timeout,
                    expected_payload_bytes=0,
                    num_rounds=gate_rounds,
                    local_steps=local_steps,
                    state_scope=state_scope,
                )
                if result["gate"]["status"] != "PASS":
                    raise RuntimeError("1.5B exact-topology gate did not pass")
                result["target"] = _run_phase(
                    federation,
                    name=target_name,
                    model_path=args.target_model_path,
                    model_revision=args.target_model_revision,
                    evidence_root=args.evidence_root,
                    expected_gpu_name_substring=args.expected_gpu_name_substring,
                    ready_timeout=args.target_ready_timeout,
                    stall_timeout=args.target_stall_timeout,
                    expected_payload_bytes=args.expected_target_payload_bytes,
                    num_rounds=target_rounds,
                    local_steps=local_steps,
                    state_scope=state_scope,
                )
                result["status"] = "PASS"
        exit_code = 0
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        (args.evidence_root / "qualification-error.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        try:
            monitor_summary = monitor.close()
        except Exception as monitor_error:
            monitor_summary = {
                "event": "real_training_gpu_monitor",
                "status": "FAIL",
                "output_path": str(monitor.output_path),
                "error": f"{type(monitor_error).__name__}: {monitor_error}",
            }
        if not args.control_plane_only:
            result["gpu_monitor"] = monitor_summary
            _write_json(args.evidence_root / "gpu-monitor.json", monitor_summary)
            if monitor_summary["status"] != "PASS" and exit_code == 0:
                result["status"] = "FAIL"
                result["error"] = {
                    "type": "RuntimeError",
                    "message": "GPU utilization monitor did not produce valid samples",
                }
                exit_code = 1
        _write_json(result_path, result)
        print(json.dumps(result, sort_keys=True), flush=True)
        _cleanup_private_root(args.private_root)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
