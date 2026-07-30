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
import struct
from pathlib import Path

from safetensors import safe_open

_DEFAULT_PAYLOAD_CEILING_BYTES = 1024 * 1024 * 1024


def _safetensor_header_tensor_bytes(path: Path, expected_keys: set[str]) -> int:
    """Validate one safetensor header and return its logical tensor bytes without loading tensors."""

    with path.open("rb") as stream:
        header_size_bytes = stream.read(8)
        if len(header_size_bytes) != 8:
            raise RuntimeError(f"safetensor shard has no complete header length: {path}")
        header_size = struct.unpack("<Q", header_size_bytes)[0]
        if header_size <= 0 or header_size > path.stat().st_size - 8:
            raise RuntimeError(f"safetensor shard has an invalid header size {header_size}: {path}")
        try:
            header = json.loads(stream.read(header_size))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"safetensor shard has an invalid JSON header: {path}") from exc

    if not isinstance(header, dict):
        raise RuntimeError(f"safetensor shard header is not an object: {path}")
    header_keys = set(header).difference({"__metadata__"})
    if header_keys != expected_keys:
        raise RuntimeError(
            f"safetensor shard header key mismatch for {path}: "
            f"missing={sorted(expected_keys - header_keys)}, unexpected={sorted(header_keys - expected_keys)}"
        )

    spans = []
    for key in sorted(header_keys):
        entry = header[key]
        offsets = entry.get("data_offsets") if isinstance(entry, dict) else None
        if (
            not isinstance(offsets, list)
            or len(offsets) != 2
            or not all(isinstance(offset, int) and not isinstance(offset, bool) for offset in offsets)
            or offsets[0] < 0
            or offsets[1] < offsets[0]
        ):
            raise RuntimeError(f"safetensor tensor {key!r} has invalid data_offsets={offsets!r} in {path}")
        spans.append((offsets[0], offsets[1], key))

    expected_start = 0
    tensor_bytes = 0
    for start, end, key in sorted(spans):
        if start != expected_start:
            raise RuntimeError(
                f"safetensor tensor data is not contiguous in {path}: "
                f"tensor={key!r}, expected_start={expected_start}, observed_start={start}"
            )
        tensor_bytes += end - start
        expected_start = end

    data_bytes = path.stat().st_size - 8 - header_size
    if tensor_bytes != data_bytes:
        raise RuntimeError(
            f"safetensor shard byte-layout mismatch for {path}: tensor_bytes={tensor_bytes}, data_bytes={data_bytes}"
        )
    return tensor_bytes


def validate_indexed_safetensors(
    model_path: Path,
    *,
    expected_safetensor_files: int = 0,
    expected_tensor_bytes: int = 0,
) -> dict:
    """Validate every checkpoint shard structurally without materializing tensor payloads."""

    if (
        not isinstance(expected_safetensor_files, int)
        or isinstance(expected_safetensor_files, bool)
        or expected_safetensor_files < 0
    ):
        raise ValueError("expected_safetensor_files must be a nonnegative integer")
    if (
        not isinstance(expected_tensor_bytes, int)
        or isinstance(expected_tensor_bytes, bool)
        or expected_tensor_bytes < 0
    ):
        raise ValueError("expected_tensor_bytes must be a nonnegative integer")

    index_path = model_path / "model.safetensors.index.json"
    on_disk_shards = {path.name for path in model_path.glob("model*.safetensors") if path.is_file()}
    if not index_path.is_file():
        if len(on_disk_shards) != 1:
            raise RuntimeError(
                f"an unindexed model must contain exactly one model*.safetensors file, "
                f"found {sorted(on_disk_shards)}"
            )
        if expected_safetensor_files and expected_safetensor_files != 1:
            raise RuntimeError(
                f"safetensor file-count mismatch: expected {expected_safetensor_files}, observed 1 without an index"
            )
        filename = next(iter(on_disk_shards))
        shard_path = model_path / filename
        try:
            with safe_open(shard_path, framework="pt", device="cpu") as stream:
                observed_keys = set(stream.keys())
        except Exception as exc:
            raise RuntimeError(f"cannot structurally open safetensor shard: {shard_path}") from exc
        if not observed_keys:
            raise RuntimeError(f"unindexed safetensor shard contains no tensors: {shard_path}")
        computed_tensor_bytes = _safetensor_header_tensor_bytes(shard_path, observed_keys)
        if expected_tensor_bytes and computed_tensor_bytes != expected_tensor_bytes:
            raise RuntimeError(
                f"safetensor tensor bytes mismatch: expected {expected_tensor_bytes}, observed {computed_tensor_bytes}"
            )
        return {
            "index_path": None,
            "indexed_tensor_count": len(observed_keys),
            "index_total_size_bytes": None,
            "computed_tensor_bytes": computed_tensor_bytes,
            "validated_safetensor_files": [filename],
            "validated_safetensor_file_count": 1,
        }

    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read a valid safetensor index: {index_path}") from exc
    if not isinstance(index, dict):
        raise RuntimeError(f"safetensor index is not an object: {index_path}")

    metadata = index.get("metadata")
    weight_map = index.get("weight_map")
    if not isinstance(metadata, dict):
        raise RuntimeError(f"safetensor index has invalid metadata: {index_path}")
    index_total_size = metadata.get("total_size")
    if not isinstance(index_total_size, int) or isinstance(index_total_size, bool) or index_total_size <= 0:
        raise RuntimeError(f"safetensor index has invalid metadata.total_size={index_total_size!r}: {index_path}")
    if not isinstance(weight_map, dict) or not weight_map:
        raise RuntimeError(f"safetensor index has an empty or invalid weight_map: {index_path}")

    expected_keys_by_shard: dict[str, set[str]] = {}
    for key, filename in weight_map.items():
        if not isinstance(key, str) or not key:
            raise RuntimeError(f"safetensor index contains an invalid tensor key {key!r}: {index_path}")
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
            or not filename.startswith("model")
            or not filename.endswith(".safetensors")
        ):
            raise RuntimeError(f"safetensor index contains an invalid shard name {filename!r}: {index_path}")
        expected_keys_by_shard.setdefault(filename, set()).add(key)

    indexed_shards = set(expected_keys_by_shard)
    if indexed_shards != on_disk_shards:
        raise RuntimeError(
            f"safetensor shard-set mismatch for {model_path}: "
            f"missing={sorted(indexed_shards - on_disk_shards)}, unexpected={sorted(on_disk_shards - indexed_shards)}"
        )
    if expected_safetensor_files and len(indexed_shards) != expected_safetensor_files:
        raise RuntimeError(
            f"safetensor file-count mismatch: expected {expected_safetensor_files}, observed {len(indexed_shards)}"
        )

    computed_tensor_bytes = 0
    for filename in sorted(indexed_shards):
        shard_path = model_path / filename
        expected_keys = expected_keys_by_shard[filename]
        try:
            with safe_open(shard_path, framework="pt", device="cpu") as stream:
                observed_keys = set(stream.keys())
        except Exception as exc:
            raise RuntimeError(f"cannot structurally open safetensor shard: {shard_path}") from exc
        if observed_keys != expected_keys:
            raise RuntimeError(
                f"safetensor shard key mismatch for {shard_path}: "
                f"missing={sorted(expected_keys - observed_keys)}, unexpected={sorted(observed_keys - expected_keys)}"
            )
        computed_tensor_bytes += _safetensor_header_tensor_bytes(shard_path, expected_keys)

    if computed_tensor_bytes != index_total_size:
        raise RuntimeError(
            f"safetensor index total-size mismatch: metadata.total_size={index_total_size}, "
            f"computed_tensor_bytes={computed_tensor_bytes}"
        )
    if expected_tensor_bytes and computed_tensor_bytes != expected_tensor_bytes:
        raise RuntimeError(
            f"safetensor tensor bytes mismatch: expected {expected_tensor_bytes}, observed {computed_tensor_bytes}"
        )

    return {
        "index_path": str(index_path),
        "indexed_tensor_count": len(weight_map),
        "index_total_size_bytes": index_total_size,
        "computed_tensor_bytes": computed_tensor_bytes,
        "validated_safetensor_files": sorted(indexed_shards),
        "validated_safetensor_file_count": len(indexed_shards),
    }


def main() -> None:
    try:
        from .model import HFTrainableStateModel
        from .state_evidence import tensor_state_summary
    except ImportError:
        from model import HFTrainableStateModel
        from state_evidence import tensor_state_summary

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
    parser.add_argument("--expected-tensor-bytes", type=int, default=0)
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
    safetensor_structure = validate_indexed_safetensors(
        model_path,
        expected_safetensor_files=args.expected_safetensor_files,
        expected_tensor_bytes=args.expected_tensor_bytes,
    )
    weight_files = [model_path / filename for filename in safetensor_structure["validated_safetensor_files"]]
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
                "safetensor_structure": safetensor_structure,
                "max_payload_bytes": args.max_payload_bytes,
                "state": summary,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
