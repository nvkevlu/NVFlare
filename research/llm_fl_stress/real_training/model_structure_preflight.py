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

"""Validate a staged Qwen checkpoint structurally without materializing its tensors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .state_evidence import file_sha256, load_text_partition
    from .trainable_server_preflight import validate_indexed_safetensors
except ImportError:
    from state_evidence import file_sha256, load_text_partition
    from trainable_server_preflight import validate_indexed_safetensors


def validate_model_structure(
    model_path: Path,
    *,
    model_revision: str,
    expected_hidden_size: int,
    expected_intermediate_size: int,
    expected_num_hidden_layers: int,
    expected_num_attention_heads: int,
    expected_num_key_value_heads: int,
    expected_safetensor_files: int,
    expected_tensor_count: int,
    expected_parameters: int,
    expected_tensor_bytes: int,
    expected_checkpoint_file_bytes: int,
) -> dict:
    revision_path = model_path / "REVISION"
    if not revision_path.is_file() or revision_path.read_text(encoding="utf-8").strip() != model_revision:
        raise RuntimeError(f"staged model revision does not match {model_revision}")
    config = json.loads((model_path / "config.json").read_text(encoding="utf-8"))
    expected_config = {
        "architectures": ["Qwen2ForCausalLM"],
        "model_type": "qwen2",
        "torch_dtype": "bfloat16",
        "hidden_size": expected_hidden_size,
        "intermediate_size": expected_intermediate_size,
        "num_hidden_layers": expected_num_hidden_layers,
        "num_attention_heads": expected_num_attention_heads,
        "num_key_value_heads": expected_num_key_value_heads,
    }
    mismatches = {
        key: {"expected": expected, "observed": config.get(key)}
        for key, expected in expected_config.items()
        if config.get(key) != expected
    }
    if mismatches:
        raise RuntimeError(f"model config mismatch: {mismatches}")
    if expected_tensor_bytes != expected_parameters * 2:
        raise RuntimeError(
            "expected BF16 tensor bytes do not equal two bytes per parameter: "
            f"{expected_tensor_bytes} != {expected_parameters} * 2"
        )

    structure = validate_indexed_safetensors(
        model_path,
        expected_safetensor_files=expected_safetensor_files,
        expected_tensor_bytes=expected_tensor_bytes,
    )
    if structure["indexed_tensor_count"] != expected_tensor_count:
        raise RuntimeError(
            f"indexed tensor-count mismatch: expected {expected_tensor_count}, "
            f"observed {structure['indexed_tensor_count']}"
        )
    checkpoint_file_bytes = sum(path.stat().st_size for path in model_path.glob("model*.safetensors") if path.is_file())
    if checkpoint_file_bytes != expected_checkpoint_file_bytes:
        raise RuntimeError(
            f"physical checkpoint byte mismatch: expected {expected_checkpoint_file_bytes}, "
            f"observed {checkpoint_file_bytes}"
        )
    return {
        "event": "real_training_model_structure_preflight",
        "status": "PASS",
        "model_path": str(model_path),
        "model_revision": model_revision,
        "config": expected_config,
        "parameter_count": expected_parameters,
        "parameter_dtype": "bfloat16",
        "logical_state_payload_bytes": expected_tensor_bytes,
        "physical_checkpoint_file_bytes": checkpoint_file_bytes,
        "safetensor_structure": structure,
        "tensor_payload_materialized": False,
        "gpu_required": False,
    }


def validate_dataset(path: Path, *, minimum_records: int) -> dict:
    if minimum_records <= 0:
        raise ValueError("minimum_records must be greater than zero")
    records = load_text_partition(path)
    if len(records) < minimum_records:
        raise RuntimeError(f"dataset has {len(records)} records but the experiment requires at least {minimum_records}")
    return {
        "path": str(path),
        "sha256": file_sha256(path),
        "record_count": len(records),
        "minimum_records": minimum_records,
        "unique_ids": len({record["id"] for record in records}),
    }


def _define_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name-or-path", required=True, type=Path)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--expected-hidden-size", required=True, type=int)
    parser.add_argument("--expected-intermediate-size", required=True, type=int)
    parser.add_argument("--expected-num-hidden-layers", required=True, type=int)
    parser.add_argument("--expected-num-attention-heads", required=True, type=int)
    parser.add_argument("--expected-num-key-value-heads", required=True, type=int)
    parser.add_argument("--expected-safetensor-files", required=True, type=int)
    parser.add_argument("--expected-tensor-count", required=True, type=int)
    parser.add_argument("--expected-parameters", required=True, type=int)
    parser.add_argument("--expected-tensor-bytes", required=True, type=int)
    parser.add_argument("--expected-checkpoint-file-bytes", required=True, type=int)
    parser.add_argument("--dataset-file", type=Path)
    parser.add_argument("--minimum-dataset-records", type=int, default=1)
    return parser


def main() -> None:
    args = _define_parser().parse_args()
    for name, value in vars(args).items():
        if name.startswith("expected_") and isinstance(value, int) and value <= 0:
            raise ValueError(f"--{name.replace('_', '-')} must be greater than zero")
    result = validate_model_structure(
        args.model_name_or_path,
        model_revision=args.model_revision,
        expected_hidden_size=args.expected_hidden_size,
        expected_intermediate_size=args.expected_intermediate_size,
        expected_num_hidden_layers=args.expected_num_hidden_layers,
        expected_num_attention_heads=args.expected_num_attention_heads,
        expected_num_key_value_heads=args.expected_num_key_value_heads,
        expected_safetensor_files=args.expected_safetensor_files,
        expected_tensor_count=args.expected_tensor_count,
        expected_parameters=args.expected_parameters,
        expected_tensor_bytes=args.expected_tensor_bytes,
        expected_checkpoint_file_bytes=args.expected_checkpoint_file_bytes,
    )
    if args.dataset_file is not None:
        result["dataset"] = validate_dataset(
            args.dataset_file,
            minimum_records=args.minimum_dataset_records,
        )
    print(
        json.dumps(
            result,
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
