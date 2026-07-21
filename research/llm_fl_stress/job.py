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

"""Build, validate, export, or simulate an LLM-scale FLARE stress scenario."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from nvflare.client.config import ConfigKey, ExchangeFormat, TransferType
from nvflare.recipe.sim_env import SimEnv

from harness.artifacts import RunArtifacts, utc_now
from harness.config import Scenario, load_scenario
from harness.evidence import collect_workspace_evidence
from harness.preflight import assess_capacity
from harness.progress import RunProgressReporter
from harness.report import generate_summary
from server_observer import ServerResourceObserver
from stress_recipe import StressFedAvgRecipe


PROJECT_DIR = Path(__file__).resolve().parent
REPO_ROOT = PROJECT_DIR.parents[1]


def _parse_host_memory_limits(entries: list[str], description: str = "cgroup memory limit") -> dict[str, int]:
    result = {}
    for entry in entries:
        host, separator, value = entry.partition("=")
        if not separator or not host or not value:
            raise ValueError(f"invalid {description} {entry!r}; expected HOST=GIB")
        if host in result:
            raise ValueError(f"duplicate {description} for {host}")
        try:
            gib = float(value)
        except ValueError as error:
            raise ValueError(f"invalid GiB value in {description} {entry!r}") from error
        if gib <= 0:
            raise ValueError(f"{description} must be positive: {entry!r}")
        result[host] = int(gib * (1024**3))
    return result


def _parse_lease_expiry(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        expiry = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError("lease expiry must be an ISO-8601 timestamp") from error
    if expiry.tzinfo is None:
        raise ValueError("lease expiry must include a timezone, for example 2026-07-21T20:00:00Z")
    return expiry


@contextmanager
def _project_working_directory():
    original_directory = Path.cwd()
    os.chdir(PROJECT_DIR)
    try:
        yield
    finally:
        os.chdir(original_directory)


def _build_recipe(scenario: Scenario) -> StressFedAvgRecipe:
    model = {
        "class_path": "model.SyntheticShardModel",
        "args": {
            "parameter_count": scenario.model.parameter_count,
            "dtype": scenario.model.dtype,
            "tensor_shard_mib": scenario.model.tensor_shard_mib,
        },
    }
    recipe = StressFedAvgRecipe(
        name=scenario.name,
        model=model,
        min_clients=len(scenario.federation.clients),
        num_rounds=scenario.federation.rounds,
        train_script="client.py",
        train_args=f"--n-clients {len(scenario.federation.clients)}",
        launch_external_process=scenario.federation.launch_external_process,
        server_expected_format=ExchangeFormat.PYTORCH,
        params_transfer_type=TransferType.FULL,
        key_metric="sentinel_ok",
        server_memory_gc_rounds=scenario.federation.server_memory_gc_rounds,
        enable_tensor_disk_offload=scenario.transport.enable_tensor_disk_offload,
        client_memory_gc_rounds=scenario.federation.client_memory_gc_rounds,
    )
    recipe.add_server_file(str(PROJECT_DIR / "model.py"))
    recipe.add_server_file(str(PROJECT_DIR / "server_observer.py"))
    recipe.add_server_observer(
        ServerResourceObserver(
            trim_before_first_contribution=scenario.federation.server_trim_before_first_contribution,
        )
    )
    recipe.add_server_config(
        {
            "tensor_download_chunk_size": scenario.transport.tensor_download_chunk_size,
            "streaming_per_request_timeout": scenario.transport.streaming_per_request_timeout,
            "tensor_streaming_per_request_timeout": scenario.transport.streaming_per_request_timeout,
            "tensor_min_download_timeout": scenario.transport.tensor_min_download_timeout,
        }
    )
    recipe.add_client_config(
        {
            "get_task_timeout": scenario.transport.get_task_timeout,
            "submit_task_result_timeout": scenario.transport.submit_task_result_timeout,
            "tensor_download_chunk_size": scenario.transport.tensor_download_chunk_size,
            "streaming_per_request_timeout": scenario.transport.streaming_per_request_timeout,
            "tensor_streaming_per_request_timeout": scenario.transport.streaming_per_request_timeout,
            "tensor_min_download_timeout": scenario.transport.tensor_min_download_timeout,
            "max_resends": scenario.transport.max_resends,
            ConfigKey.HEARTBEAT_TIMEOUT: scenario.transport.streaming_per_request_timeout,
        }
    )
    return recipe


def _record_non_run_result(artifacts: RunArtifacts, mode: str, status: str) -> int:
    artifacts.write_result(
        {
            "mode": mode,
            "status": status,
            "finished_at": utc_now(),
            "workspace_path": str(artifacts.workspace_dir),
            "job_config_path": str(artifacts.job_config_dir),
        }
    )
    collect_workspace_evidence(artifacts)
    summary = generate_summary(artifacts.root)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Artifacts: {artifacts.root}")
    return 0


def _record_launcher_failure(artifacts: RunArtifacts, mode: str, exception: Exception) -> int:
    (artifacts.logs_dir / "launcher_error.log").write_text(traceback.format_exc(), encoding="utf-8")
    artifacts.write_result(
        {
            "mode": mode,
            "status": "FINISHED:FAILED",
            "finished_at": utc_now(),
            "workspace_path": str(artifacts.workspace_dir),
            "job_config_path": str(artifacts.job_config_dir),
            "error": {"type": type(exception).__name__, "message": str(exception)},
        }
    )
    collect_workspace_evidence(artifacts)
    summary = generate_summary(artifacts.root)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Artifacts: {artifacts.root}")
    return 1


def _wait_for_monitor(process: subprocess.Popen, artifacts: RunArtifacts, timeout_seconds: float = 10.0) -> None:
    process_samples = artifacts.metrics_dir / "process_samples.csv"
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(f"telemetry monitor exited during startup with code {return_code}")
        try:
            if process_samples.stat().st_size > 0:
                return
        except OSError:
            pass
        time.sleep(0.05)
    raise TimeoutError(f"telemetry monitor did not become ready within {timeout_seconds} seconds")


def _run_simulation(
    recipe: StressFedAvgRecipe, scenario: Scenario, artifacts: RunArtifacts, capacity_preflight: dict
) -> int:
    monitor_stop_path = artifacts.metrics_dir / "monitor.stop"
    monitor_log = (artifacts.logs_dir / "monitor_process.log").open("w", encoding="utf-8")
    monitor_environment = dict(os.environ)
    python_path = monitor_environment.get("PYTHONPATH")
    monitor_environment["PYTHONPATH"] = (
        str(PROJECT_DIR) if not python_path else f"{PROJECT_DIR}{os.pathsep}{python_path}"
    )
    monitor_command = [
        sys.executable,
        "-m",
        "harness.monitor",
        "--pid",
        str(os.getpid()),
        "--output-dir",
        str(artifacts.metrics_dir),
        "--interval",
        str(scenario.monitoring.sample_interval_seconds),
        "--gpu-interval",
        str(scenario.monitoring.gpu_sample_interval_seconds),
        "--host-label",
        "local-simulation",
        "--stop-file",
        str(monitor_stop_path),
    ]
    started_at = utc_now()
    artifacts.append_event("job_started", "harness", mode="simulation")
    terminal_status = "FINISHED:FAILED"
    error = None
    monitor_process = None
    try:
        monitor_process = subprocess.Popen(
            monitor_command,
            cwd=PROJECT_DIR,
            env=monitor_environment,
            stdout=monitor_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _wait_for_monitor(monitor_process, artifacts)
        environment = SimEnv(
            clients=scenario.federation.clients,
            num_threads=scenario.federation.simulator_threads,
            workspace_root=str(artifacts.workspace_dir),
        )
        recipe.run(environment)
        terminal_status = "FINISHED:COMPLETED"
    except Exception as exception:
        error = {
            "type": type(exception).__name__,
            "message": str(exception),
        }
        (artifacts.logs_dir / "launcher_error.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        artifacts.append_event("job_finished", "harness", mode="simulation", status=terminal_status)
        if monitor_process is not None:
            monitor_stop_path.touch()
            try:
                monitor_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                monitor_process.terminate()
                try:
                    monitor_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    monitor_process.kill()
                    monitor_process.wait(timeout=5)
            monitor_stop_path.unlink(missing_ok=True)
        monitor_log.close()

    artifacts.write_result(
        {
            "mode": "simulation",
            "status": terminal_status,
            "started_at": started_at,
            "finished_at": utc_now(),
            "workspace_path": str(artifacts.workspace_dir),
            "job_config_path": str(artifacts.job_config_dir),
            "capacity_preflight": capacity_preflight,
            "error": error,
        }
    )
    collect_workspace_evidence(artifacts)
    summary = generate_summary(artifacts.root)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Artifacts: {artifacts.root}")
    return 0 if summary["status"] == "PASS" else 1


def _run_production(
    recipe: StressFedAvgRecipe,
    scenario: Scenario,
    artifacts: RunArtifacts,
    args: argparse.Namespace,
) -> int:
    from nvflare.recipe.prod_env import ProdEnv

    from harness.remote import ArtifactCheckpointWorker, RemoteTelemetry, build_remote_hosts

    remote_hosts = build_remote_hosts(scenario, args.server_ssh_alias, args.client_ssh_alias)
    progress = RunProgressReporter(artifacts, report_interval_seconds=args.status_report_interval_seconds)
    progress.update("CAPACITY_PREFLIGHT", "PENDING", force=True)
    telemetry = RemoteTelemetry(
        ssh_config=args.ssh_config,
        hosts=remote_hosts,
        source_root=args.remote_source_root,
        service_root=args.remote_service_root,
        output_root=args.remote_output_root,
        run_id=artifacts.root.name,
        sample_interval_seconds=scenario.monitoring.sample_interval_seconds,
        gpu_sample_interval_seconds=scenario.monitoring.gpu_sample_interval_seconds,
        memory_max_by_host=args.cgroup_memory_max_bytes_by_host,
        memory_high_by_host=args.cgroup_memory_high_bytes_by_host,
        expected_oom_hosts=args.expected_cgroup_oom_hosts,
        memory_high_ratio=args.cgroup_memory_high_ratio,
    )
    capacity_preflight = telemetry.capacity_preflight(scenario)
    artifacts.append_event(
        "capacity_preflight",
        "harness",
        mode="production",
        passed=capacity_preflight["passed"],
        risks=capacity_preflight["risks"],
        override=args.allow_capacity_risk,
    )
    if not capacity_preflight["passed"] and not args.allow_capacity_risk:
        artifacts.write_result(
            {
                "mode": "production",
                "status": "BLOCKED:CAPACITY_PREFLIGHT",
                "finished_at": utc_now(),
                "workspace_path": str(artifacts.workspace_dir),
                "job_config_path": str(artifacts.job_config_dir),
                "capacity_preflight": capacity_preflight,
                "error": {
                    "type": "CapacityPreflight",
                    "message": "Use --allow-capacity-risk only for an intentional failure test.",
                },
            }
        )
        collect_workspace_evidence(artifacts)
        summary = generate_summary(artifacts.root)
        print(json.dumps(summary, indent=2, sort_keys=True))
        print(f"Artifacts: {artifacts.root}", flush=True)
        progress.finish(summary["status"], "BLOCKED:CAPACITY_PREFLIGHT")
        return 2

    terminal_status = "FINISHED:FAILED"
    error = None
    job_id = None
    downloaded_result = None
    monitor_errors = []
    cgroup_metadata = {}
    observed_memory_events = {}
    service_environment_check = {"passed": True, "expected": {}, "hosts": {}, "mismatches": []}
    started_at = utc_now()
    job_started = False
    checkpoint_worker = ArtifactCheckpointWorker(
        telemetry=telemetry,
        artifacts=artifacts,
        interval_seconds=args.artifact_checkpoint_interval_seconds,
        lease_expiry_utc=args.lease_expiry,
        final_checkpoint_lead_seconds=args.lease_final_checkpoint_lead_seconds,
    )
    environment = ProdEnv(
        startup_kit_location=str(args.startup_kit_location),
        login_timeout=args.login_timeout,
        username=args.username,
        study=args.study,
    )
    try:
        progress.update("STARTING_TELEMETRY", "PENDING", force=True)
        telemetry.start()
        checkpoint_worker.start()
        cgroup_metadata = telemetry.cgroup_metadata()
        if cgroup_metadata:
            artifacts.append_event(
                "fault_injection_started",
                "harness",
                cgroups=cgroup_metadata,
                expected_cgroup_oom_hosts=sorted(args.expected_cgroup_oom_hosts),
            )
        service_environment_check = telemetry.check_service_environment(
            scenario.transport.f3_service_environment
        )
        artifacts.append_event(
            "service_environment_check",
            "harness",
            **service_environment_check,
        )
        if not service_environment_check["passed"]:
            terminal_status = "FAILED:TRANSPORT_CONFIG"
            raise RuntimeError(
                "F3 service environment does not match the scenario: "
                f"{service_environment_check['mismatches']}"
            )
        artifacts.append_event("job_started", "harness", mode="production")
        job_started = True
        run = recipe.run(environment)
        job_id = run.get_job_id()
        progress.update("FEDERATED_RUN", "SUBMITTED", job_id=job_id, force=True)
        if args.skip_result_download:
            deadline = time.monotonic() + args.result_timeout
            while time.monotonic() < deadline:
                if cgroup_metadata:
                    observed_memory_events = telemetry.managed_memory_events()
                    oom_kill_hosts = sorted(
                        label for label, events in observed_memory_events.items() if events.get("oom_kill", 0) > 0
                    )
                    if (
                        oom_kill_hosts
                        and args.expected_cgroup_oom_hosts
                        and args.expected_cgroup_oom_hosts.issubset(oom_kill_hosts)
                    ):
                        terminal_status = "EXPECTED:CGROUP_OOM"
                        break
                    if oom_kill_hosts:
                        terminal_status = "FAILED:CGROUP_OOM"
                        raise RuntimeError(f"unexpected cgroup OOM kill observed on: {', '.join(oom_kill_hosts)}")
                try:
                    terminal_status = str(run.get_status() or "UNKNOWN")
                except Exception:
                    if args.expected_cgroup_oom_hosts:
                        expected_failure_met, observed_memory_events = telemetry.expected_ooms_observed()
                        if expected_failure_met:
                            terminal_status = "EXPECTED:CGROUP_OOM"
                            break
                    raise
                progress.update("FEDERATED_RUN", terminal_status, job_id=job_id)
                if terminal_status.startswith("FINISHED:"):
                    break
                time.sleep(args.status_poll_interval_seconds)
            else:
                environment.abort_job(job_id)
                raise TimeoutError(f"production job did not finish within {args.result_timeout} seconds")
        else:
            progress.update("WAITING_FOR_RESULT", "MONITORING", job_id=job_id, force=True)
            downloaded_result = run.get_result(timeout=args.result_timeout, clean_up=False)
            terminal_status = str(run.get_status() or "UNKNOWN")
            if downloaded_result is None:
                environment.abort_job(job_id)
                raise TimeoutError(f"production job did not finish within {args.result_timeout} seconds")
            downloaded_path = Path(downloaded_result).resolve()
            if not downloaded_path.is_dir():
                raise RuntimeError(f"downloaded production result is not a directory: {downloaded_path}")
            shutil.copytree(downloaded_path, artifacts.workspace_dir, dirs_exist_ok=True)
    except Exception as exception:
        error = {"type": type(exception).__name__, "message": str(exception)}
        if not terminal_status.startswith(("FINISHED:", "EXPECTED:", "FAILED:")):
            terminal_status = "FINISHED:FAILED"
        (artifacts.logs_dir / "launcher_error.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        checkpoint_worker.stop()
        if cgroup_metadata:
            try:
                observed_memory_events = telemetry.managed_memory_events()
            except Exception:
                pass
        if job_started:
            artifacts.append_event("job_finished", "harness", mode="production", status=terminal_status)
        progress.update(
            "COLLECTING_ARTIFACTS",
            terminal_status,
            job_id=job_id,
            force=True,
            error_type=error.get("type") if error else None,
        )
        monitor_errors = telemetry.stop_and_collect(artifacts)

    artifacts.write_result(
        {
            "mode": "production",
            "status": terminal_status,
            "started_at": started_at,
            "finished_at": utc_now(),
            "job_id": job_id,
            "downloaded_result_path": str(downloaded_result) if downloaded_result else None,
            "result_download_skipped": args.skip_result_download,
            "workspace_path": str(artifacts.workspace_dir),
            "job_config_path": str(artifacts.job_config_dir),
            "capacity_preflight": capacity_preflight,
            "fault_injection": {
                "cgroups": cgroup_metadata,
                "expected_cgroup_oom_hosts": sorted(args.expected_cgroup_oom_hosts),
                "observed_memory_events": observed_memory_events,
            },
            "remote_telemetry": {
                "status_poll_interval_seconds": args.status_poll_interval_seconds,
                "status_report_interval_seconds": args.status_report_interval_seconds,
                "artifact_checkpoint_interval_seconds": args.artifact_checkpoint_interval_seconds,
                "lease_expiry_utc": args.lease_expiry.isoformat() if args.lease_expiry else None,
                "lease_final_checkpoint_lead_seconds": args.lease_final_checkpoint_lead_seconds,
                "artifact_checkpoints": checkpoint_worker.records,
                "remote_source_root": args.remote_source_root,
                "remote_service_root": args.remote_service_root,
                "remote_output_root": args.remote_output_root,
                "hosts": [
                    {"label": host.label, "ssh_alias": host.ssh_alias, "role": host.role} for host in remote_hosts
                ],
                "service_environment_check": service_environment_check,
                "errors": monitor_errors,
            },
            "error": error,
        }
    )
    collect_workspace_evidence(artifacts)
    summary = generate_summary(artifacts.root)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Artifacts: {artifacts.root}", flush=True)
    progress.finish(summary["status"], terminal_status, job_id=job_id, error=error)
    return 0 if summary["status"] in {"PASS", "EXPECTED_FAILURE"} else 1


def _execute(args: argparse.Namespace, scenario: Scenario, artifacts: RunArtifacts) -> int:
    with _project_working_directory():
        recipe = _build_recipe(scenario)
        if args.validate_only:
            return _record_non_run_result(artifacts, "validate", "VALIDATED")
        recipe.export(str(artifacts.job_config_dir))
        if args.export_only:
            return _record_non_run_result(artifacts, "export", "EXPORTED")
        if args.production:
            return _run_production(recipe, scenario, artifacts, args)
        import psutil

        from harness.monitor import read_cgroup_memory

        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(artifacts.root)
        effective_available_memory = memory.available
        cgroup_memory = read_cgroup_memory(os.getpid())
        cgroup_max = cgroup_memory.get("cgroup_memory_max_bytes")
        cgroup_current = cgroup_memory.get("cgroup_memory_current_bytes")
        if isinstance(cgroup_max, int) and isinstance(cgroup_current, int):
            effective_available_memory = min(effective_available_memory, max(0, cgroup_max - cgroup_current))
        capacity_preflight = assess_capacity(scenario, effective_available_memory, disk.free)
        capacity_preflight["observed"] = {
            "system_available_memory_bytes": memory.available,
            "cgroup_memory": cgroup_memory,
            "effective_available_memory_bytes": effective_available_memory,
            "filesystem_free_bytes": disk.free,
        }
        artifacts.append_event(
            "capacity_preflight",
            "harness",
            passed=capacity_preflight["passed"],
            risks=capacity_preflight["risks"],
            override=args.allow_capacity_risk,
        )
        if not capacity_preflight["passed"] and not args.allow_capacity_risk:
            artifacts.write_result(
                {
                    "mode": "simulation",
                    "status": "BLOCKED:CAPACITY_PREFLIGHT",
                    "finished_at": utc_now(),
                    "workspace_path": str(artifacts.workspace_dir),
                    "job_config_path": str(artifacts.job_config_dir),
                    "capacity_preflight": capacity_preflight,
                    "error": {
                        "type": "CapacityPreflight",
                        "message": "Use --allow-capacity-risk only for an intentional failure test.",
                    },
                }
            )
            collect_workspace_evidence(artifacts)
            summary = generate_summary(artifacts.root)
            print(json.dumps(summary, indent=2, sort_keys=True))
            print(f"Artifacts: {artifacts.root}")
            return 2
        return _run_simulation(recipe, scenario, artifacts, capacity_preflight)


def main() -> int:
    invocation_directory = Path.cwd()
    parser = argparse.ArgumentParser(description="Run an LLM-scale FLARE server stress scenario.")
    parser.add_argument("--scenario", type=Path, default=PROJECT_DIR / "configs" / "smoke.json")
    parser.add_argument("--output-root", type=Path, default=PROJECT_DIR / "runs")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--export-only", action="store_true")
    mode.add_argument("--production", action="store_true")
    parser.add_argument("--startup-kit-location", type=Path)
    parser.add_argument("--username", default="admin@nvidia.com")
    parser.add_argument("--study", default="default")
    parser.add_argument("--login-timeout", type=float, default=10.0)
    parser.add_argument("--result-timeout", type=float, default=1800.0)
    parser.add_argument(
        "--status-poll-interval-seconds",
        type=float,
        default=5.0,
        help="poll FLARE status and managed cgroup OOM events at this interval during thin production runs",
    )
    parser.add_argument(
        "--status-report-interval-seconds",
        type=float,
        default=60.0,
        help="write and print a local run heartbeat at this interval during production runs",
    )
    parser.add_argument(
        "--artifact-checkpoint-interval-seconds",
        type=float,
        default=300.0,
        help="incrementally recover remote telemetry and service logs at this interval; use 0 to disable",
    )
    parser.add_argument(
        "--lease-expiry-utc",
        help="lease expiry as a timezone-aware ISO-8601 timestamp; enables a pre-expiry recovery checkpoint",
    )
    parser.add_argument(
        "--lease-final-checkpoint-lead-seconds",
        type=float,
        default=900.0,
        help="recover artifacts this many seconds before --lease-expiry-utc",
    )
    parser.add_argument(
        "--skip-result-download",
        action="store_true",
        help="retain logs and telemetry but leave large checkpoints on the server",
    )
    parser.add_argument("--ssh-config", type=Path)
    parser.add_argument("--server-ssh-alias", default="flare-server")
    parser.add_argument(
        "--client-ssh-alias",
        action="append",
        default=[],
        metavar="SITE=SSH_ALIAS",
        help="map a configured client name to an SSH alias; defaults to flare-SITE",
    )
    parser.add_argument("--remote-source-root", default="nvflare-stress-src")
    parser.add_argument("--remote-service-root", default="nvflare-stress-kit")
    parser.add_argument("--remote-output-root", default="nvflare-stress-runs")
    parser.add_argument(
        "--allow-capacity-risk",
        action="store_true",
        help="run even when conservative RAM or disk preflight checks fail",
    )
    parser.add_argument(
        "--cgroup-memory-max-gib",
        action="append",
        default=[],
        metavar="HOST=GIB",
        help="place a production host service in a per-run cgroup with this hard memory limit",
    )
    parser.add_argument(
        "--cgroup-memory-high-gib",
        action="append",
        default=[],
        metavar="HOST=GIB",
        help="set an absolute soft memory.high threshold without requiring a lowered memory.max",
    )
    parser.add_argument(
        "--expect-cgroup-oom",
        action="append",
        default=[],
        metavar="HOST",
        help="treat a cgroup OOM kill on this limited host as the expected test outcome",
    )
    parser.add_argument(
        "--cgroup-memory-high-ratio",
        type=float,
        default=0.9,
        help="set memory.high as this fraction of each hard cgroup limit; use 1.0 for a hard-OOM lane",
    )
    args = parser.parse_args()
    if args.production:
        if args.startup_kit_location is None:
            parser.error("--production requires --startup-kit-location")
        if args.ssh_config is None:
            parser.error("--production requires --ssh-config")
        if (
            args.result_timeout <= 0
            or args.login_timeout <= 0
            or args.status_poll_interval_seconds <= 0
            or args.status_report_interval_seconds <= 0
            or args.artifact_checkpoint_interval_seconds < 0
            or args.lease_final_checkpoint_lead_seconds < 0
        ):
            parser.error("production timeouts must be positive and checkpoint intervals cannot be negative")
        args.startup_kit_location = (invocation_directory / args.startup_kit_location).resolve()
        args.ssh_config = (invocation_directory / args.ssh_config).resolve()

    scenario_path = (invocation_directory / args.scenario).resolve()
    scenario = load_scenario(scenario_path)
    try:
        args.lease_expiry = _parse_lease_expiry(args.lease_expiry_utc)
        args.cgroup_memory_max_bytes_by_host = _parse_host_memory_limits(
            args.cgroup_memory_max_gib, "cgroup memory.max limit"
        )
        args.cgroup_memory_high_bytes_by_host = _parse_host_memory_limits(
            args.cgroup_memory_high_gib, "cgroup memory.high threshold"
        )
    except ValueError as error:
        parser.error(str(error))
    args.expected_cgroup_oom_hosts = set(args.expect_cgroup_oom)
    configured_hosts = {"server", *scenario.federation.clients}
    unknown_fault_hosts = sorted(
        (
            set(args.cgroup_memory_max_bytes_by_host)
            | set(args.cgroup_memory_high_bytes_by_host)
            | args.expected_cgroup_oom_hosts
        )
        - configured_hosts
    )
    if unknown_fault_hosts:
        parser.error(f"unknown fault-injection hosts: {unknown_fault_hosts}")
    if not args.expected_cgroup_oom_hosts.issubset(args.cgroup_memory_max_bytes_by_host):
        parser.error("every --expect-cgroup-oom host requires --cgroup-memory-max-gib HOST=GIB")
    invalid_high_limits = sorted(
        label
        for label in set(args.cgroup_memory_max_bytes_by_host) & set(args.cgroup_memory_high_bytes_by_host)
        if args.cgroup_memory_high_bytes_by_host[label] > args.cgroup_memory_max_bytes_by_host[label]
    )
    if invalid_high_limits:
        parser.error(f"cgroup memory.high exceeds memory.max for: {invalid_high_limits}")
    cgroup_hosts = set(args.cgroup_memory_max_bytes_by_host) | set(args.cgroup_memory_high_bytes_by_host)
    if cgroup_hosts and not args.production:
        parser.error("cgroup memory controls require --production")
    if cgroup_hosts and not args.allow_capacity_risk:
        parser.error("cgroup memory controls require --allow-capacity-risk")
    if args.expected_cgroup_oom_hosts and not args.skip_result_download:
        parser.error("expected cgroup OOM tests require --skip-result-download")
    if not 0 < args.cgroup_memory_high_ratio <= 1:
        parser.error("--cgroup-memory-high-ratio must be in (0, 1]")
    artifacts = RunArtifacts.create(
        output_root=(invocation_directory / args.output_root).resolve(),
        scenario=scenario,
        source_scenario_path=scenario_path,
        repo_root=REPO_ROOT,
        command=[sys.executable, *sys.argv],
    )
    print(f"Run artifacts: {artifacts.root}", flush=True)
    requested_mode = (
        "validate"
        if args.validate_only
        else "export"
        if args.export_only
        else "production"
        if args.production
        else "simulation"
    )
    try:
        return _execute(args, scenario, artifacts)
    except Exception as exception:
        return _record_launcher_failure(artifacts, requested_mode, exception)


if __name__ == "__main__":
    raise SystemExit(main())
