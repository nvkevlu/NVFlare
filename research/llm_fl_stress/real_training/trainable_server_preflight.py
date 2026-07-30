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

"""Instantiate and validate the sparse trainable-state server model without a GPU."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from model import HFTrainableStateModel
from state_evidence import tensor_state_summary

_DEFAULT_PAYLOAD_CEILING_BYTES = 1024 * 1024 * 1024


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name-or-path", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--expected-hidden-size", type=int, default=0)
    parser.add_argument("--expected-intermediate-size", type=int, default=0)
    parser.add_argument("--expected-num-hidden-layers", type=int, default=0)
    parser.add_argument("--expected-num-attention-heads", type=int, default=0)
    parser.add_argument("--expected-num-key-value-heads", type=int, default=0)
    parser.add_argument("--expected-min-weight-bytes", type=int, default=0)
    parser.add_argument("--expected-safetensor-files", type=int, default=0)
    parser.add_argument("--expected-payload-bytes", type=int, default=0)
    parser.add_argument("--max-payload-bytes", type=int, default=_DEFAULT_PAYLOAD_CEILING_BYTES)
    args = parser.parse_args()
    if args.max_payload_bytes <= 0:
        raise ValueError("--max-payload-bytes must be greater than zero")

    model_path = Path(args.model_name_or_path)
    config = json.loads((model_path / "config.json").read_text(encoding="utf-8"))
    if args.expected_hidden_size and config.get("hidden_size") != args.expected_hidden_size:
        raise RuntimeError(
            f"hidden_size mismatch: expected {args.expected_hidden_size}, observed {config.get('hidden_size')}"
        )
    if args.expected_num_hidden_layers and config.get("num_hidden_layers") != args.expected_num_hidden_layers:
        raise RuntimeError(
            "num_hidden_layers mismatch: "
            f"expected {args.expected_num_hidden_layers}, observed {config.get('num_hidden_layers')}"
        )
    for name, expected in (
        ("intermediate_size", args.expected_intermediate_size),
        ("num_attention_heads", args.expected_num_attention_heads),
        ("num_key_value_heads", args.expected_num_key_value_heads),
    ):
        if expected and config.get(name) != expected:
            raise RuntimeError(f"{name} mismatch: expected {expected}, observed {config.get(name)}")
    if args.expected_hidden_size or args.expected_num_hidden_layers:
        observed_identity = {
            "architectures": config.get("architectures"),
            "model_type": config.get("model_type"),
            "torch_dtype": config.get("torch_dtype"),
        }
        if observed_identity != {
            "architectures": ["Qwen2ForCausalLM"],
            "model_type": "qwen2",
            "torch_dtype": "bfloat16",
        }:
            raise RuntimeError(f"target architecture or dtype mismatch: {observed_identity}")
    weight_files = sorted(model_path.glob("model*.safetensors"))
    if args.expected_safetensor_files and len(weight_files) != args.expected_safetensor_files:
        raise RuntimeError(
            f"safetensor file-count mismatch: expected {args.expected_safetensor_files}, observed {len(weight_files)}"
        )
    weight_bytes = sum(path.stat().st_size for path in weight_files)
    if args.expected_min_weight_bytes and weight_bytes < args.expected_min_weight_bytes:
        raise RuntimeError(
            f"safetensor bytes below minimum: expected at least {args.expected_min_weight_bytes}, "
            f"observed {weight_bytes}"
        )

    model = HFTrainableStateModel(args.model_name_or_path, revision=args.model_revision)
    state = model.state_dict()
    if not all(key.startswith("model.model.layers.") for key in state):
        raise RuntimeError(f"sparse server model contains unexpected keys: {sorted(state)}")
    summary = tensor_state_summary(state)
    if summary["payload_bytes"] > args.max_payload_bytes:
        raise RuntimeError(f"sparse server payload {summary['payload_bytes']} exceeds ceiling {args.max_payload_bytes}")
    if args.expected_payload_bytes and summary["payload_bytes"] != args.expected_payload_bytes:
        raise RuntimeError(
            f"sparse server payload mismatch: expected {args.expected_payload_bytes}, "
            f"observed {summary['payload_bytes']}"
        )
    print(
        json.dumps(
            {
                "event": "real_training_trainable_server_preflight",
                "status": "PASS",
                "model_path": args.model_name_or_path,
                "model_revision": args.model_revision,
                "safetensor_bytes": weight_bytes,
                "safetensor_file_count": len(weight_files),
                "max_payload_bytes": args.max_payload_bytes,
                "state": summary,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
