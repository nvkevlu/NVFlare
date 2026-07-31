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

"""Materialize and validate the exact CPU full-state server model before GPU use."""

from __future__ import annotations

import argparse
import json
import resource
import sys
from pathlib import Path
from typing import Any, Mapping

import torch

REAL_TRAINING_DIR = Path(__file__).resolve().parent
if str(REAL_TRAINING_DIR) not in sys.path:
    sys.path.insert(0, str(REAL_TRAINING_DIR))

from model import HFTextModel  # noqa: E402
from state_evidence import tensor_state_probe  # noqa: E402
from trainable_server_preflight import validate_indexed_safetensors  # noqa: E402


def _max_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def _validate_materialized_state(
    state: Mapping[str, Any],
    *,
    expected_payload_bytes: int,
    expected_tensor_count: int,
    expected_parameters: int,
) -> dict[str, Any]:
    if not state or not all(isinstance(key, str) and key.startswith("model.") for key in state):
        raise RuntimeError("full-state server keys must be non-empty and use the client-compatible model. prefix")
    non_bf16 = {key: str(value.dtype) for key, value in state.items() if value.dtype != torch.bfloat16}
    if non_bf16:
        raise RuntimeError(f"full-state server contains non-BF16 tensors: {non_bf16}")
    probe = tensor_state_probe(state)
    observed_parameters = sum(value.numel() for value in state.values())
    if probe["payload_bytes"] != expected_payload_bytes:
        raise RuntimeError(
            f"full-state payload mismatch: expected {expected_payload_bytes}, observed {probe['payload_bytes']}"
        )
    if probe["tensor_count"] != expected_tensor_count:
        raise RuntimeError(
            f"full-state tensor-count mismatch: expected {expected_tensor_count}, observed {probe['tensor_count']}"
        )
    if observed_parameters != expected_parameters:
        raise RuntimeError(
            f"full-state parameter-count mismatch: expected {expected_parameters}, observed {observed_parameters}"
        )
    return {**probe, "parameter_count": observed_parameters}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name-or-path", required=True, type=Path)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--expected-hidden-size", required=True, type=int)
    parser.add_argument("--expected-intermediate-size", required=True, type=int)
    parser.add_argument("--expected-num-hidden-layers", required=True, type=int)
    parser.add_argument("--expected-num-attention-heads", required=True, type=int)
    parser.add_argument("--expected-num-key-value-heads", required=True, type=int)
    parser.add_argument("--expected-safetensor-files", required=True, type=int)
    parser.add_argument("--expected-payload-bytes", required=True, type=int)
    parser.add_argument("--expected-tensor-count", required=True, type=int)
    parser.add_argument("--expected-parameters", required=True, type=int)
    args = parser.parse_args()

    revision_path = args.model_name_or_path / "REVISION"
    if revision_path.read_text(encoding="utf-8").strip() != args.model_revision:
        raise RuntimeError(f"staged model revision does not match {args.model_revision}")
    config = json.loads((args.model_name_or_path / "config.json").read_text(encoding="utf-8"))
    expected_config = {
        "architectures": ["Qwen2ForCausalLM"],
        "model_type": "qwen2",
        "torch_dtype": "bfloat16",
        "hidden_size": args.expected_hidden_size,
        "intermediate_size": args.expected_intermediate_size,
        "num_hidden_layers": args.expected_num_hidden_layers,
        "num_attention_heads": args.expected_num_attention_heads,
        "num_key_value_heads": args.expected_num_key_value_heads,
    }
    mismatches = {
        key: {"expected": expected, "observed": config.get(key)}
        for key, expected in expected_config.items()
        if config.get(key) != expected
    }
    if mismatches:
        raise RuntimeError(f"full-state model config mismatch: {mismatches}")
    safetensors = validate_indexed_safetensors(
        args.model_name_or_path,
        expected_safetensor_files=args.expected_safetensor_files,
        expected_tensor_bytes=args.expected_payload_bytes,
    )
    model = HFTextModel(str(args.model_name_or_path), revision=args.model_revision)
    state = model.state_dict()
    evidence = _validate_materialized_state(
        state,
        expected_payload_bytes=args.expected_payload_bytes,
        expected_tensor_count=args.expected_tensor_count,
        expected_parameters=args.expected_parameters,
    )
    print(
        json.dumps(
            {
                "event": "real_training_full_state_server_preflight",
                "status": "PASS",
                "model_path": str(args.model_name_or_path),
                "model_revision": args.model_revision,
                "config": expected_config,
                "safetensor_structure": safetensors,
                "state": evidence,
                "max_rss_bytes": _max_rss_bytes(),
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
