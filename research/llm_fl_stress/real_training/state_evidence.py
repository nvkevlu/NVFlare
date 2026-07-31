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

"""Auditable datasets and compact tensor-state evidence for real LLM training."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_SAMPLES_PER_TENSOR = 4


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_text_partition(path: Path, *, expected_sha256: str | None = None) -> list[dict[str, str]]:
    """Load and validate a fixed JSONL text partition."""

    if not path.is_file():
        raise ValueError(f"dataset partition does not exist: {path}")
    observed_sha256 = file_sha256(path)
    if expected_sha256 and observed_sha256 != expected_sha256:
        raise ValueError(
            f"dataset partition checksum mismatch for {path}: "
            f"expected {expected_sha256}, observed {observed_sha256}"
        )

    records = []
    seen_ids = set()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON in {path} at line {line_number}: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"dataset record {line_number} in {path} is not an object")
            record_id = record.get("id")
            text = record.get("text")
            if not isinstance(record_id, str) or not record_id:
                raise ValueError(f"dataset record {line_number} in {path} has an invalid id")
            if record_id in seen_ids:
                raise ValueError(f"dataset partition {path} contains duplicate id {record_id!r}")
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"dataset record {record_id!r} in {path} has empty text")
            if set(record) != {"id", "text"}:
                raise ValueError(f"dataset record {record_id!r} in {path} must contain only id and text")
            seen_ids.add(record_id)
            records.append({"id": record_id, "text": text})
    if not records:
        raise ValueError(f"dataset partition is empty: {path}")
    return records


def select_partition_record(
    records: list[dict[str, str]],
    *,
    current_round: int,
    local_step: int,
    rank: int,
    world_size: int,
    local_steps: int,
) -> dict[str, str]:
    """Select one deterministic rank-local record without random sampler state."""

    index = current_round * local_steps * world_size + local_step * world_size + rank
    return records[index % len(records)]


def tensor_state_summary(state_dict: Mapping[str, Any]) -> dict[str, Any]:
    """Hash a CPU tensor state and retain a small set of linear sample coordinates."""

    import torch

    if not isinstance(state_dict, Mapping) or not state_dict:
        raise ValueError("tensor state must be a non-empty mapping")

    digest = hashlib.sha256()
    samples = []
    tensor_count = 0
    payload_bytes = 0
    for key in sorted(state_dict):
        value = state_dict[key]
        if not isinstance(key, str):
            raise TypeError(f"tensor state key must be str, got {type(key).__name__}")
        if not torch.is_tensor(value):
            raise TypeError(f"tensor state value for {key!r} must be a tensor, got {type(value).__name__}")
        if value.device.type != "cpu":
            raise ValueError(f"tensor state value for {key!r} must be on CPU, got {value.device}")

        tensor = value.detach().contiguous()
        shape = list(tensor.shape)
        dtype = str(tensor.dtype)
        digest.update(len(key).to_bytes(8, "big"))
        digest.update(key.encode("utf-8"))
        encoded_metadata = json.dumps({"dtype": dtype, "shape": shape}, sort_keys=True).encode("utf-8")
        digest.update(len(encoded_metadata).to_bytes(8, "big"))
        digest.update(encoded_metadata)
        byte_view = tensor.view(torch.uint8).numpy()
        digest.update(memoryview(byte_view))

        tensor_count += 1
        payload_bytes += tensor.numel() * tensor.element_size()
        if tensor.numel():
            flat = tensor.reshape(-1)
            indices = sorted(
                {
                    0,
                    tensor.numel() // 3,
                    (2 * tensor.numel()) // 3,
                    tensor.numel() - 1,
                }
            )
            for index in indices[:_SAMPLES_PER_TENSOR]:
                samples.append({"key": key, "index": index, "value": float(flat[index].item())})

    if tensor_count == 0:
        raise ValueError("tensor state does not contain tensors")
    return {
        "sha256": digest.hexdigest(),
        "tensor_count": tensor_count,
        "payload_bytes": payload_bytes,
        "samples": samples,
    }


def tensor_state_probe(state_dict: Mapping[str, Any]) -> dict[str, Any]:
    """Record exact tensor schema and bounded values without hashing every tensor byte."""

    import torch

    if not isinstance(state_dict, Mapping) or not state_dict:
        raise ValueError("tensor state must be a non-empty mapping")

    schema_digest = hashlib.sha256()
    samples = []
    tensor_count = 0
    payload_bytes = 0
    for key in sorted(state_dict):
        value = state_dict[key]
        if not isinstance(key, str):
            raise TypeError(f"tensor state key must be str, got {type(key).__name__}")
        if not torch.is_tensor(value):
            raise TypeError(f"tensor state value for {key!r} must be a tensor, got {type(value).__name__}")
        if value.device.type != "cpu":
            raise ValueError(f"tensor state value for {key!r} must be on CPU, got {value.device}")
        metadata = json.dumps(
            {"dtype": str(value.dtype), "key": key, "shape": list(value.shape)},
            sort_keys=True,
        ).encode("utf-8")
        schema_digest.update(len(metadata).to_bytes(8, "big"))
        schema_digest.update(metadata)
        tensor_count += 1
        payload_bytes += value.numel() * value.element_size()
        if value.numel():
            flat = value.detach().reshape(-1)
            indices = sorted({0, value.numel() // 3, (2 * value.numel()) // 3, value.numel() - 1})
            for index in indices[:_SAMPLES_PER_TENSOR]:
                samples.append({"key": key, "index": index, "value": float(flat[index].item())})
    return {
        "strategy": "schema-sha256-plus-bounded-values",
        "schema_sha256": schema_digest.hexdigest(),
        "tensor_count": tensor_count,
        "payload_bytes": payload_bytes,
        "samples": samples,
    }


def inspect_persisted_checkpoint(path: Path) -> dict[str, Any]:
    """Reload a persisted trainable-state checkpoint and summarize its model tensors."""

    import torch

    payload = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(payload, Mapping):
        raise TypeError(f"persisted checkpoint must be a mapping, got {type(payload).__name__}")
    state = payload.get("model", payload)
    if not isinstance(state, Mapping):
        raise TypeError(f"persisted checkpoint model must be a mapping, got {type(state).__name__}")
    summary = tensor_state_summary(state)
    return {
        "reload_status": "PASS",
        "checkpoint_keys": sorted(payload),
        "state": summary,
    }
