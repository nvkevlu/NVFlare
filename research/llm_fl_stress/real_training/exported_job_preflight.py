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

"""Fail-closed validation of the exported two-client large-model job."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

CLIENT_NAMES = ("site-1", "site-2")
EXPECTED_LAUNCHER_SHUTDOWN_TIMEOUT_SECONDS = 600.0


def _require_equal(mapping: dict[str, Any], expected: dict[str, Any], source: Path) -> None:
    mismatches = {
        key: {"expected": value, "observed": mapping.get(key)}
        for key, value in expected.items()
        if mapping.get(key) != value
    }
    if mismatches:
        raise RuntimeError(f"timeout/configuration mismatch in {source}: {mismatches}")


def _require_early_flare_init(client_script: Path) -> None:
    module = ast.parse(client_script.read_text(encoding="utf-8"), filename=str(client_script))
    run_function = next(
        (node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "_run"),
        None,
    )
    if run_function is None:
        raise RuntimeError(f"exported client has no _run function: {client_script}")

    init_lines = []
    load_lines = []
    for node in ast.walk(run_function):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "flare"
            and function.attr == "init"
        ):
            init_lines.append(node.lineno)
        elif isinstance(function, ast.Name) and function.id == "_load_model_and_tokenizer":
            load_lines.append(node.lineno)
    if len(init_lines) != 1 or len(load_lines) != 1 or init_lines[0] >= load_lines[0]:
        raise RuntimeError(
            f"exported client must call flare.init exactly once before model loading: "
            f"init_lines={init_lines}, load_lines={load_lines}, source={client_script}"
        )


def validate_exported_job(job_root: Path, timeout_seconds: int) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    if not job_root.is_dir():
        raise RuntimeError(f"exported job root does not exist: {job_root}")

    expected_client = {
        "EXTERNAL_PRE_INIT_TIMEOUT": timeout_seconds,
        "PEER_READ_TIMEOUT": timeout_seconds,
        "HEARTBEAT_TIMEOUT": timeout_seconds,
        "submit_result_timeout": timeout_seconds,
        "download_complete_timeout": timeout_seconds,
        "max_resends": 3,
        "last_result_transfer_timeout": timeout_seconds,
        "streaming_idle_timeout": timeout_seconds,
        "streaming_max_peer_silence": timeout_seconds * 1.5,
        "get_task_timeout": timeout_seconds,
        "max_runner_sync_timeout": timeout_seconds,
        "runner_sync_timeout": 5.0,
        "submit_task_result_timeout": timeout_seconds,
        "tensor_streaming_per_request_timeout": timeout_seconds,
        "tensor_min_download_timeout": timeout_seconds,
    }
    validated_clients = []
    for site_name in CLIENT_NAMES:
        app_root = job_root / f"app_{site_name}"
        config_path = app_root / "config" / "config_fed_client.json"
        client_script = app_root / "custom" / "research" / "llm_fl_stress" / "real_training" / "client.py"
        dataset = app_root / "custom" / "data" / f"{site_name}.jsonl"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        _require_equal(config, expected_client, config_path)
        if "streaming_per_request_timeout" in config:
            raise RuntimeError(
                f"{config_path} contains ineffective generic streaming_per_request_timeout; "
                "PyTorch tensor transfers require tensor_streaming_per_request_timeout"
            )
        if not dataset.is_file() or dataset.stat().st_size <= 0:
            raise RuntimeError(f"site dataset is missing or empty: {dataset}")
        launchers = [component for component in config.get("components", []) if component.get("id") == "launcher"]
        if len(launchers) != 1:
            raise RuntimeError(f"expected exactly one launcher component in {config_path}, found {len(launchers)}")
        launcher_args = launchers[0].get("args")
        if not isinstance(launcher_args, dict):
            raise RuntimeError(f"launcher component in {config_path} has invalid args: {launcher_args!r}")
        _require_equal(
            launcher_args,
            {"shutdown_timeout": EXPECTED_LAUNCHER_SHUTDOWN_TIMEOUT_SECONDS},
            config_path,
        )
        launcher_script = launcher_args.get("script", "")
        expected_dataset_arg = f"--dataset-file data/{site_name}.jsonl"
        if expected_dataset_arg not in launcher_script:
            raise RuntimeError(f"launcher in {config_path} does not contain {expected_dataset_arg!r}")
        _require_early_flare_init(client_script)
        validated_clients.append(site_name)

    server_config_path = job_root / "app_server" / "config" / "config_fed_server.json"
    server_config = json.loads(server_config_path.read_text(encoding="utf-8"))
    expected_server = {
        "strict_start_job_reply_check": True,
        "sync_client_jobs_require_previous_report": True,
        "streaming_idle_timeout": timeout_seconds,
        "streaming_max_peer_silence": timeout_seconds * 1.5,
        "tensor_streaming_per_request_timeout": timeout_seconds,
        "tensor_min_download_timeout": timeout_seconds,
    }
    _require_equal(server_config, expected_server, server_config_path)
    if "streaming_per_request_timeout" in server_config:
        raise RuntimeError(
            f"{server_config_path} contains ineffective generic streaming_per_request_timeout; "
            "PyTorch tensor transfers require tensor_streaming_per_request_timeout"
        )

    return {
        "event": "real_training_exported_job_preflight",
        "status": "PASS",
        "job_root": str(job_root),
        "clients": validated_clients,
        "timeout_seconds": timeout_seconds,
        "max_resends": 3,
        "launcher_shutdown_timeout_seconds": EXPECTED_LAUNCHER_SHUTDOWN_TIMEOUT_SECONDS,
        "subprocess_tensor_download_timeout_seconds": timeout_seconds,
        "early_flare_init": True,
        "strict_start_job_reply_check": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-root", required=True, type=Path)
    parser.add_argument("--timeout-seconds", required=True, type=int)
    args = parser.parse_args()
    print(
        json.dumps(
            validate_exported_job(args.job_root, args.timeout_seconds),
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
