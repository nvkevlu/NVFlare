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

"""Fail-closed 1.5B gate and 14B run using real provisioned NVFLARE services."""

from __future__ import annotations

import argparse
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
from evidence import validate_production_evidence  # noqa: E402
from job import _build_recipe  # noqa: E402
from provisioned import (  # noqa: E402
    ADMIN_NAME,
    CLIENT_NAMES,
    SERVER_NAME,
    LocalProductionFederation,
    PersistedModelWatcher,
)


class _GpuMonitor:
    def __init__(self, output_path: Path):
        self.output_path = output_path
        self.process: subprocess.Popen | None = None
        self.stream = None

    def start(self) -> None:
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

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5.0)
        if self.stream is not None:
            self.stream.close()


def _define_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-model-path", required=True, type=Path)
    parser.add_argument("--gate-model-revision", required=True)
    parser.add_argument("--target-model-path", required=True, type=Path)
    parser.add_argument("--target-model-revision", required=True)
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--expected-gpu-name-substring", default="A100-SXM4-80GB")
    parser.add_argument("--service-startup-timeout", type=float, default=90.0)
    parser.add_argument("--gate-ready-timeout", type=float, default=120.0)
    parser.add_argument("--gate-total-timeout", type=float, default=300.0)
    parser.add_argument("--target-ready-timeout", type=float, default=300.0)
    parser.add_argument("--target-total-timeout", type=float, default=720.0)
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


def _phase_args(model_path: Path, model_revision: str, phase_root: Path) -> Namespace:
    return Namespace(
        model_name_or_path=model_path,
        model_revision=model_revision,
        workspace_root=phase_root / "unused-workspace",
        export_root=phase_root / "unused-export",
        num_clients=2,
        nproc_per_node=4,
        num_rounds=1,
        local_steps=1,
        max_length=128,
        learning_rate=1.0e-5,
        trainable_target="last-layer",
        run_mode="train",
        timeout_seconds=900,
        expected_gpu_name_substring=None,
    )


def _validate_phase_inputs(model_path: Path, model_revision: str, phase_root: Path) -> None:
    config = RealTrainingConfig(
        model_path=model_path,
        workspace_root=phase_root / "unused-workspace",
        export_root=phase_root / "unused-export",
        num_clients=2,
        nproc_per_node=4,
        num_rounds=1,
        local_steps=1,
        max_length=128,
        learning_rate=1.0e-5,
        trainable_target="last-layer",
        run_mode="train",
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
    total_timeout: float,
) -> dict[str, Any]:
    from nvflare.recipe.prod_env import ProdEnv

    phase_root = evidence_root / name
    phase_root.mkdir(parents=True, exist_ok=False)
    recipe = _build_recipe(_phase_args(model_path, model_revision, phase_root))
    environment = ProdEnv(
        startup_kit_location=str(federation.admin_kit),
        login_timeout=10.0,
        username=ADMIN_NAME,
        study="default",
    )
    started_at = time.monotonic()
    run = recipe.run(environment)
    job_id = run.get_job_id()
    watcher = PersistedModelWatcher(federation, job_id, phase_root / "persistence")
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
    try:
        status = federation.wait_for_run(
            run,
            model_path=model_path,
            ready_timeout=ready_timeout,
            total_timeout=total_timeout,
        )
        persisted = watcher.wait()
    finally:
        watcher.close()
    collected_roots = federation.collect_job_logs(job_id, phase_root / "logs")
    roots = {site_name: collected_roots[site_name] for site_name in CLIENT_NAMES}
    evidence = validate_production_evidence(
        client_roots=roots,
        server_root=collected_roots[SERVER_NAME],
        site_names=list(CLIENT_NAMES),
        model_path=model_path,
        run_mode="train",
        nproc_per_client=4,
        num_rounds=1,
        expected_gpu_name_substring=expected_gpu_name_substring,
    )
    summary = {
        **evidence,
        "phase": name,
        "job_id": job_id,
        "job_status": status,
        "model_path": str(model_path),
        "model_revision": model_revision,
        "persisted_model": persisted,
        "elapsed_seconds": time.monotonic() - started_at,
        "execution_environment": "ProdEnv",
        "service_topology": "localhost-tls-server-plus-two-real-clients",
    }
    _write_json(phase_root / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    return summary


def _build_control_plane_recipe():
    from nvflare.app_common.np.recipes.fedavg import NumpyFedAvgRecipe

    recipe = NumpyFedAvgRecipe(
        name="llm_real_services_control_plane",
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
) -> dict[str, Any]:
    from nvflare.recipe.prod_env import ProdEnv

    environment = ProdEnv(
        startup_kit_location=str(federation.admin_kit),
        login_timeout=10.0,
        username=ADMIN_NAME,
        study="default",
    )
    run = _build_control_plane_recipe().run(environment)
    job_id = run.get_job_id()
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
    destination = evidence_root / "control-plane-job"
    federation.collect_job_logs(job_id, destination)
    summary = {
        "aggregated_results": 2,
        "event": "real_training_production_control_plane_job",
        "execution_environment": "ProdEnv",
        "job_id": job_id,
        "job_status": status,
        "sites": sorted(sites),
        "status": "PASS",
    }
    _write_json(destination / "summary.json", summary)
    print(json.dumps(summary, sort_keys=True), flush=True)
    return summary


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
        "gate": None,
        "target": None,
    }
    try:
        if not args.control_plane_only:
            _validate_phase_inputs(args.gate_model_path, args.gate_model_revision, args.evidence_root / "gate")
            _validate_phase_inputs(args.target_model_path, args.target_model_revision, args.evidence_root / "target")
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
                result.update(
                    status="PASS",
                    control_plane_only=True,
                    control_plane_job=_run_control_plane_job(federation, args.evidence_root),
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
                    total_timeout=args.gate_total_timeout,
                )
                if result["gate"]["status"] != "PASS":
                    raise RuntimeError("1.5B exact-topology gate did not pass")
                result["target"] = _run_phase(
                    federation,
                    name="target-14b",
                    model_path=args.target_model_path,
                    model_revision=args.target_model_revision,
                    evidence_root=args.evidence_root,
                    expected_gpu_name_substring=args.expected_gpu_name_substring,
                    ready_timeout=args.target_ready_timeout,
                    total_timeout=args.target_total_timeout,
                )
                result["status"] = "PASS"
        return 0
    except Exception as exc:
        result["error"] = {"type": type(exc).__name__, "message": str(exc)}
        (args.evidence_root / "qualification-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(json.dumps(result, sort_keys=True), flush=True)
        return 1
    finally:
        monitor.close()
        _write_json(result_path, result)
        _cleanup_private_root(args.private_root)


if __name__ == "__main__":
    raise SystemExit(main())
