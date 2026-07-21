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

"""Exchange-only FLARE client with an end-to-end aggregation sentinel."""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import psutil
import torch

import nvflare.client as flare


EVENT_PREFIX = "[LLM_STRESS_EVENT]"


def _client_api_config_path(script_path: Path = Path(__file__)) -> Path:
    return script_path.resolve().parent.parent / "config" / "client_api_config.json"


def _memory_snapshot() -> Dict[str, Any]:
    process = psutil.Process(os.getpid())
    memory = process.memory_info()
    system_memory = psutil.virtual_memory()
    return {
        "pid": process.pid,
        "rss_bytes": memory.rss,
        "vms_bytes": memory.vms,
        "num_threads": process.num_threads(),
        "system_available_bytes": system_memory.available,
        "system_memory_percent": system_memory.percent,
    }


def _emit(event: str, site: str, round_number: int | None = None, **data: Any) -> None:
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "source": "client",
        "site": site,
        **_memory_snapshot(),
        **data,
    }
    if round_number is not None:
        record["round"] = round_number
    print(f"{EVENT_PREFIX}{json.dumps(record, sort_keys=True)}", flush=True)


def _site_delta(site: str) -> float:
    match = re.search(r"(\d+)$", site)
    if match is None:
        raise ValueError(f"site name must end in a positive integer: {site}")
    value = int(match.group(1))
    if value <= 0:
        raise ValueError(f"site name must end in a positive integer: {site}")
    return float(value)


def _sentinel_tensor(params: Dict[str, torch.Tensor]) -> torch.Tensor:
    for tensor in params.values():
        if isinstance(tensor, torch.Tensor) and tensor.numel() > 0:
            return tensor.reshape(-1)
    raise ValueError("received model contains no non-empty PyTorch tensors")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an exchange-only LLM stress client.")
    parser.add_argument("--n-clients", type=int, required=True)
    parser.add_argument("--sentinel-tolerance", type=float, default=0.01)
    args = parser.parse_args()
    if args.n_clients <= 0:
        raise ValueError("--n-clients must be positive")

    flare.init(config_file=str(_client_api_config_path()))
    site = flare.system_info()["site_name"]
    site_delta = _site_delta(site)
    mean_delta = (args.n_clients + 1) / 2.0
    _emit("client_started", site)

    next_round = 0
    while flare.is_running():
        _emit("client_receive_start", site, next_round)
        input_model = flare.receive()
        if input_model is None:
            break
        round_number = int(input_model.current_round)
        sentinel = _sentinel_tensor(input_model.params)
        observed = float(sentinel[0].item())
        expected = round_number * mean_delta
        sentinel_ok = abs(observed - expected) <= args.sentinel_tolerance
        _emit(
            "client_receive_end",
            site,
            round_number,
            sentinel_observed=observed,
            sentinel_expected=expected,
            sentinel_ok=sentinel_ok,
        )

        sentinel[0].add_(site_delta)
        output_model = flare.FLModel(
            params=input_model.params,
            metrics={"sentinel_ok": float(sentinel_ok)},
            meta={"NUM_STEPS_CURRENT_ROUND": 1},
        )
        _emit("client_send_start", site, round_number, sentinel_delta=site_delta)
        flare.send(output_model)
        _emit("client_send_end", site, round_number, sentinel_delta=site_delta)
        next_round = round_number + 1

    _emit("client_finished", site)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
