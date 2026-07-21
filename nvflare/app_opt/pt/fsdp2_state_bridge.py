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

"""Rank-zero full-state exchange for a PyTorch FSDP2 model.

This bridge owns only the transition between an exchanged full model state and
an FSDP2-sharded model. The caller remains responsible for NVFLARE receive/send
operations and for clearing the exchanged payload after it has been handed off.

All ranks in the process group must call ``load_full_state_dict`` and
``export_full_state_dict`` in the same order. Only rank zero supplies or receives
the full state dict. Small control metadata is broadcast to keep validation
failures synchronized; the full Python state object is never object-broadcast.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Optional

import torch
import torch.distributed as dist
import torch.nn as nn
from torch.distributed.checkpoint.state_dict import StateDictOptions, get_model_state_dict, set_model_state_dict
from torch.distributed.fsdp import FSDPModule

from nvflare.security.logging import secure_format_exception


@dataclass(frozen=True)
class FSDP2StateDictStats:
    """Size and elapsed-time telemetry for one full-state transition."""

    tensor_count: int
    payload_bytes: int
    duration_seconds: float
    world_size: int


@dataclass(frozen=True)
class FSDP2LoadResult:
    """Result of loading a rank-zero full state into an FSDP2 model."""

    stats: FSDP2StateDictStats
    missing_keys: tuple[str, ...]
    unexpected_keys: tuple[str, ...]


@dataclass(frozen=True)
class FSDP2ExportResult:
    """Result of gathering an FSDP2 model into a rank-zero CPU full state."""

    state_dict: Optional[dict[str, Any]]
    stats: FSDP2StateDictStats


class FSDP2StateBridge:
    """Load and export full model state at an FSDP2 federated boundary.

    The model must already have been sharded with FSDP2 ``fully_shard`` and the
    default distributed process group must already be initialized. The bridge
    uses PyTorch Distributed Checkpoint state-dict APIs because their
    ``broadcast_from_rank0`` path distributes full tensors directly into the
    model's DTensor shards.

    Args:
        model: The FSDP2-sharded root model on every rank.
        exchange_prefix: Optional wrapper prefix present in exchanged keys but
            absent from the FSDP2 model, for example ``"model."``. It is removed
            on load and restored on export.
    """

    def __init__(self, model: nn.Module, exchange_prefix: str = ""):
        if not isinstance(model, nn.Module):
            raise TypeError(f"model must be a torch.nn.Module, got {type(model).__name__}")
        if not isinstance(exchange_prefix, str):
            raise TypeError(f"exchange_prefix must be a string, got {type(exchange_prefix).__name__}")
        if exchange_prefix and not exchange_prefix.endswith("."):
            raise ValueError("exchange_prefix must end with '.'")

        self.model = model
        self.exchange_prefix = exchange_prefix

    def load_full_state_dict(self, full_state_dict: Optional[Mapping[str, Any]]) -> FSDP2LoadResult:
        """Collectively load a full CPU state supplied only on rank zero.

        ``full_state_dict`` is ignored on nonzero ranks. The input tensors are
        not cloned, and a shallow working dict is cleared as soon as PyTorch has
        distributed the full tensors into local DTensor shards.
        """

        rank, world_size = _require_process_group()
        _require_fsdp2_model(self.model)
        started_at = time.perf_counter()
        prepared_state: dict[str, Any] = {}
        preparation_error = None
        tensor_count = 0
        payload_bytes = 0

        if rank == 0:
            try:
                prepared_state = _prepare_rank_zero_state(full_state_dict, self.exchange_prefix)
                tensor_count, payload_bytes = _state_dict_metrics(prepared_state, require_cpu=True)
            except Exception as e:
                preparation_error = f"{type(e).__name__}: {secure_format_exception(e)}"

        control = _broadcast_rank_zero_control((preparation_error, tensor_count, payload_bytes), rank)
        preparation_error, tensor_count, payload_bytes = control
        if preparation_error:
            raise RuntimeError(f"rank-zero full-state validation failed: {preparation_error}")

        try:
            incompatible_keys = set_model_state_dict(
                self.model,
                prepared_state,
                options=StateDictOptions(
                    full_state_dict=True,
                    broadcast_from_rank0=True,
                    strict=True,
                ),
            )
        finally:
            prepared_state.clear()

        stats = FSDP2StateDictStats(
            tensor_count=tensor_count,
            payload_bytes=payload_bytes,
            duration_seconds=time.perf_counter() - started_at,
            world_size=world_size,
        )
        return FSDP2LoadResult(
            stats=stats,
            missing_keys=tuple(incompatible_keys.missing_keys),
            unexpected_keys=tuple(incompatible_keys.unexpected_keys),
        )

    def export_full_state_dict(self) -> FSDP2ExportResult:
        """Collectively gather a full CPU state and return it only on rank zero."""

        rank, world_size = _require_process_group()
        _require_fsdp2_model(self.model)
        started_at = time.perf_counter()
        gathered_state = get_model_state_dict(
            self.model,
            options=StateDictOptions(full_state_dict=True, cpu_offload=True),
        )

        export_state = None
        export_error = None
        tensor_count = 0
        payload_bytes = 0
        if rank == 0:
            try:
                export_state = _prepare_export_state(gathered_state, self.exchange_prefix)
                tensor_count, payload_bytes = _state_dict_metrics(export_state, require_cpu=True)
            except Exception as e:
                export_error = f"{type(e).__name__}: {secure_format_exception(e)}"

        control = _broadcast_rank_zero_control((export_error, tensor_count, payload_bytes), rank)
        export_error, tensor_count, payload_bytes = control
        if export_error:
            raise RuntimeError(f"rank-zero full-state export failed: {export_error}")

        stats = FSDP2StateDictStats(
            tensor_count=tensor_count,
            payload_bytes=payload_bytes,
            duration_seconds=time.perf_counter() - started_at,
            world_size=world_size,
        )
        return FSDP2ExportResult(state_dict=export_state, stats=stats)


def _require_process_group() -> tuple[int, int]:
    if not dist.is_available() or not dist.is_initialized():
        raise RuntimeError("FSDP2StateBridge requires an initialized torch.distributed process group on every rank")
    return dist.get_rank(), dist.get_world_size()


def _require_fsdp2_model(model: nn.Module) -> None:
    if not isinstance(model, FSDPModule):
        raise RuntimeError(
            "FSDP2StateBridge requires the root model to be sharded with torch.distributed.fsdp.fully_shard"
        )


def _broadcast_rank_zero_control(value: tuple, rank: int) -> tuple:
    objects = [value if rank == 0 else None]
    dist.broadcast_object_list(objects, src=0)
    return objects[0]


def _prepare_rank_zero_state(full_state_dict: Optional[Mapping[str, Any]], exchange_prefix: str) -> dict[str, Any]:
    if full_state_dict is None:
        raise ValueError("rank zero must supply a full state dict")
    if not isinstance(full_state_dict, Mapping):
        raise TypeError(f"full_state_dict must be a mapping, got {type(full_state_dict).__name__}")
    if not full_state_dict:
        raise ValueError("rank-zero full state dict is empty")

    prepared_state = {}
    for key, value in full_state_dict.items():
        if not isinstance(key, str):
            raise TypeError(f"state-dict keys must be strings, got {type(key).__name__}")
        if exchange_prefix:
            if not key.startswith(exchange_prefix):
                raise ValueError(f"state-dict key {key!r} does not start with {exchange_prefix!r}")
            key = key[len(exchange_prefix) :]
            if not key:
                raise ValueError("exchange prefix cannot consume an entire state-dict key")
        if key in prepared_state:
            raise ValueError(f"duplicate state-dict key after removing exchange prefix: {key!r}")
        prepared_state[key] = value
    return prepared_state


def _prepare_export_state(state_dict: Mapping[str, Any], exchange_prefix: str) -> dict[str, Any]:
    if not isinstance(state_dict, Mapping):
        raise TypeError(f"PyTorch full-state export must be a mapping, got {type(state_dict).__name__}")
    if not state_dict:
        raise ValueError("PyTorch returned an empty full state dict on rank zero")

    export_state = {}
    for key, value in state_dict.items():
        if not isinstance(key, str):
            raise TypeError(f"state-dict keys must be strings, got {type(key).__name__}")
        external_key = f"{exchange_prefix}{key}"
        if external_key in export_state:
            raise ValueError(f"duplicate exported state-dict key: {external_key!r}")
        export_state[external_key] = value
    return export_state


def _state_dict_metrics(state_dict: Mapping[str, Any], require_cpu: bool) -> tuple[int, int]:
    tensor_count = 0
    payload_bytes = 0
    for key, value in state_dict.items():
        if not torch.is_tensor(value):
            continue
        if require_cpu and value.device.type != "cpu":
            raise ValueError(f"state-dict tensor {key!r} must be on CPU, got device {value.device}")
        tensor_count += 1
        payload_bytes += value.numel() * value.element_size()
    return tensor_count, payload_bytes
