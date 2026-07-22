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

"""Validate, export, or run the one-client Hugging Face/FSDP2 NVFLARE job."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

REAL_TRAINING_DIR = Path(__file__).resolve().parent
CLIENT_SCRIPT = Path("research/llm_fl_stress/real_training/client.py")
MODEL_SCRIPT = REAL_TRAINING_DIR / "model.py"
if str(REAL_TRAINING_DIR) not in sys.path:
    sys.path.insert(0, str(REAL_TRAINING_DIR))

from config import RUN_MODES, TRAINABLE_TARGETS, RealTrainingConfig  # noqa: E402


def _define_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name-or-path", required=True, type=Path)
    parser.add_argument("--model-revision", default=None)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--export-root", required=True, type=Path)
    parser.add_argument("--nproc-per-node", type=int, default=4)
    parser.add_argument("--num-rounds", type=int, default=1)
    parser.add_argument("--local-steps", type=int, default=1)
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1.0e-5)
    parser.add_argument("--trainable-target", choices=TRAINABLE_TARGETS, default="last-layer")
    parser.add_argument("--run-mode", choices=RUN_MODES, default="train")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--validate-only", action="store_true")
    mode.add_argument("--export-only", action="store_true")
    return parser


def _config_from_args(args: argparse.Namespace) -> RealTrainingConfig:
    return RealTrainingConfig(
        model_path=args.model_name_or_path,
        workspace_root=args.workspace_root,
        export_root=args.export_root,
        nproc_per_node=args.nproc_per_node,
        num_rounds=args.num_rounds,
        local_steps=args.local_steps,
        max_length=args.max_length,
        learning_rate=args.learning_rate,
        trainable_target=args.trainable_target,
        run_mode=args.run_mode,
    )


def _quote_args(values: list[object]) -> str:
    if any(value is None for value in values):
        raise ValueError("client argument list contains None")
    return " ".join(shlex.quote(str(value)) for value in values)


def _client_args(args: argparse.Namespace) -> str:
    values: list[object] = [
        "--model-name-or-path",
        args.model_name_or_path,
        "--local-steps",
        args.local_steps,
        "--max-length",
        args.max_length,
        "--learning-rate",
        args.learning_rate,
        "--trainable-target",
        args.trainable_target,
        "--run-mode",
        args.run_mode,
        "--timeout-seconds",
        args.timeout_seconds,
    ]
    if args.model_revision:
        values.extend(["--model-revision", args.model_revision])
    return _quote_args(values)


def _build_recipe(args: argparse.Namespace):
    from nvflare.app_opt.pt.recipes.fedavg import FedAvgRecipe
    from nvflare.client.config import ExchangeFormat, TransferType

    model = {
        "class_path": "model.HFTextModel",
        "args": {
            "model_name_or_path": str(args.model_name_or_path),
            "revision": args.model_revision,
        },
    }
    command = (
        "python3 -m torch.distributed.run --standalone " f"--nproc_per_node={args.nproc_per_node} --max_restarts=0"
    )
    recipe = FedAvgRecipe(
        name="llm_fsdp2_real_training",
        model=model,
        min_clients=1,
        num_rounds=args.num_rounds,
        train_script=str(CLIENT_SCRIPT),
        train_args=_client_args(args),
        launch_external_process=True,
        command=command,
        server_expected_format=ExchangeFormat.PYTORCH,
        params_transfer_type=TransferType.FULL,
        launch_once=True,
        shutdown_timeout=60.0,
        key_metric="neg_loss",
        enable_tensor_disk_offload=True,
        server_memory_gc_rounds=1,
        client_memory_gc_rounds=1,
        cuda_empty_cache=True,
    )
    recipe.add_server_file(str(MODEL_SCRIPT))
    recipe.add_client_config(
        {
            "get_task_timeout": args.timeout_seconds,
            "submit_task_result_timeout": args.timeout_seconds,
            "tensor_min_download_timeout": args.timeout_seconds,
        }
    )
    recipe.add_server_config(
        {
            "streaming_per_request_timeout": args.timeout_seconds,
            "tensor_min_download_timeout": args.timeout_seconds,
        }
    )
    return recipe


def _validated_summary(args: argparse.Namespace, config: RealTrainingConfig) -> dict[str, object]:
    return {
        "event": "real_training_validation",
        "status": "PASS",
        "model_path": str(config.model_path),
        "workspace_root": str(config.workspace_root),
        "export_root": str(config.export_root),
        "nproc_per_node": config.nproc_per_node,
        "num_rounds": config.num_rounds,
        "local_steps": config.local_steps,
        "max_length": config.max_length,
        "trainable_target": config.trainable_target,
        "run_mode": config.run_mode,
        "client_command": (
            "python3 -m torch.distributed.run --standalone " f"--nproc_per_node={args.nproc_per_node} --max_restarts=0"
        ),
    }


def main() -> None:
    args = _define_parser().parse_args()
    config = _config_from_args(args)
    config.validate(require_model_files=True)
    summary = _validated_summary(args, config)

    if args.validate_only:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return

    config.workspace_root.mkdir(parents=True, exist_ok=True)
    config.export_root.mkdir(parents=True, exist_ok=True)
    recipe = _build_recipe(args)
    recipe.export(str(config.export_root))
    print(json.dumps({**summary, "job_exported": True}, indent=2, sort_keys=True))
    if args.export_only:
        return

    from nvflare.recipe import SimEnv

    gpu_config = "[" + ",".join(str(index) for index in range(args.nproc_per_node)) + "]"
    env = SimEnv(clients=["site-1"], num_threads=1, gpu_config=gpu_config, workspace_root=str(config.workspace_root))
    run = recipe.run(env)
    print(f"Job status: {run.get_status()}")
    print(f"Job result: {run.get_result()}")


if __name__ == "__main__":
    main()
