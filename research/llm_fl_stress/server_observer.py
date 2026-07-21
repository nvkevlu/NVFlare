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

"""Server event observer that records memory at workflow phase boundaries."""

import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

import psutil
import torch

from nvflare.apis.event_type import EventType
from nvflare.apis.fl_context import FLContext
from nvflare.app_common.app_constant import AppConstants
from nvflare.app_common.app_event_type import AppEventType
from nvflare.fuel.utils.memory_utils import cleanup_memory
from nvflare.widgets.widget import Widget


EVENT_PREFIX = "[LLM_STRESS_EVENT]"
_EVENT_NAMES = {
    EventType.START_RUN: "server_run_start",
    AppEventType.ROUND_STARTED: "server_round_start",
    AppEventType.BEFORE_CONTRIBUTION_ACCEPT: "server_before_contribution_accept",
    AppEventType.AFTER_CONTRIBUTION_ACCEPT: "server_after_contribution_accept",
    AppEventType.BEFORE_AGGREGATION: "server_before_aggregation",
    AppEventType.AFTER_AGGREGATION: "server_after_aggregation",
    AppEventType.BEFORE_LEARNABLE_PERSIST: "server_before_persist",
    AppEventType.AFTER_LEARNABLE_PERSIST: "server_after_persist",
    EventType.END_RUN: "server_run_end",
}


def _read_int(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if value == "max":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _proc_status_snapshot() -> Dict[str, int]:
    result = {}
    field_names = {
        "RssAnon": "rss_anon_bytes",
        "RssFile": "rss_file_bytes",
        "RssShmem": "rss_shmem_bytes",
    }
    try:
        lines = Path("/proc/self/status").read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for line in lines:
        name, separator, value = line.partition(":")
        output_name = field_names.get(name)
        if not separator or output_name is None:
            continue
        parts = value.split()
        if parts:
            try:
                result[output_name] = int(parts[0]) * 1024
            except ValueError:
                continue
    return result


def _cgroup_snapshot() -> Dict[str, int | None]:
    try:
        cgroup_lines = Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    relative_path = None
    for line in cgroup_lines:
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0" and parts[1] == "":
            relative_path = parts[2]
            break
    if relative_path is None:
        return {}
    root = Path("/sys/fs/cgroup") / relative_path.lstrip("/")
    result = {
        "cgroup_memory_current_bytes": _read_int(root / "memory.current"),
        "cgroup_memory_high_bytes": _read_int(root / "memory.high"),
        "cgroup_memory_max_bytes": _read_int(root / "memory.max"),
    }
    try:
        stat_lines = (root / "memory.stat").read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    memory_stat = {}
    for line in stat_lines:
        name, separator, value = line.partition(" ")
        if separator:
            try:
                memory_stat[name] = int(value)
            except ValueError:
                continue
    result["cgroup_anon_bytes"] = memory_stat.get("anon")
    result["cgroup_file_bytes"] = memory_stat.get("file")
    return result


def _iter_tensors(value: Any, seen: set[int] | None = None) -> Iterable[torch.Tensor]:
    if seen is None:
        seen = set()
    if isinstance(value, torch.Tensor):
        yield value
        return
    value_id = id(value)
    if value_id in seen:
        return
    seen.add(value_id)
    if isinstance(value, torch.nn.Module):
        yield from value.parameters(recurse=True)
        yield from value.buffers(recurse=True)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_tensors(item, seen)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_tensors(item, seen)
    else:
        params = getattr(value, "params", None)
        if params is not None:
            yield from _iter_tensors(params, seen)


def _storage_identity(tensor: torch.Tensor) -> tuple[str, int, int]:
    storage = tensor.untyped_storage()
    return str(tensor.device), storage.data_ptr(), storage.nbytes()


def _summarize_tensor_owners(owners: Dict[str, Any]) -> Dict[str, Any]:
    unique_storages = {}
    storage_bytes_by_owner = {}
    logical_bytes_by_owner = {}
    storage_count_by_owner = {}
    for name, value in owners.items():
        owner_storages = {}
        logical_bytes = 0
        for tensor in _iter_tensors(value):
            logical_bytes += tensor.numel() * tensor.element_size()
            try:
                identity = _storage_identity(tensor)
            except RuntimeError:
                continue
            owner_storages[identity] = identity[2]
            unique_storages[identity] = identity[2]
        storage_bytes_by_owner[name] = sum(owner_storages.values())
        logical_bytes_by_owner[name] = logical_bytes
        storage_count_by_owner[name] = len(owner_storages)
    return {
        "unique_tensor_storage_bytes": sum(unique_storages.values()),
        "unique_tensor_storage_count": len(unique_storages),
        "tensor_storage_bytes_by_owner": storage_bytes_by_owner,
        "tensor_logical_bytes_by_owner": logical_bytes_by_owner,
        "tensor_storage_count_by_owner": storage_count_by_owner,
    }


def _tensor_snapshot(fl_ctx: FLContext) -> Dict[str, Any]:
    owners = {}
    engine = fl_ctx.get_engine()
    persistor = engine.get_component("persistor") if engine else None
    controller = engine.get_component("controller") if engine else None
    if persistor is not None:
        model = getattr(persistor, "model", None)
        if model is not None:
            owners["persistor_module"] = model
        persistence_manager = getattr(persistor, "persistence_manager", None)
        persisted_weights = getattr(persistence_manager, "var_dict", None)
        if persisted_weights is not None:
            owners["persisted_weights"] = persisted_weights
    global_model = fl_ctx.get_prop(AppConstants.GLOBAL_MODEL)
    if global_model is not None:
        owners["context_global_model"] = global_model
    aggregation_result = fl_ctx.get_prop(AppConstants.AGGREGATION_RESULT)
    if aggregation_result is not None:
        owners["aggregation_result"] = aggregation_result
    aggregation_helper = getattr(controller, "_aggr_helper", None)
    aggregation_total = getattr(aggregation_helper, "total", None)
    if aggregation_total is not None:
        owners["aggregation_total"] = aggregation_total
    return _summarize_tensor_owners(owners)


def _memory_snapshot(fl_ctx: FLContext | None = None) -> Dict[str, Any]:
    process = psutil.Process(os.getpid())
    memory = process.memory_info()
    system_memory = psutil.virtual_memory()
    try:
        io_counters = process.io_counters()
        read_bytes = io_counters.read_bytes
        write_bytes = io_counters.write_bytes
    except (AttributeError, OSError, psutil.Error):
        read_bytes = None
        write_bytes = None
    result = {
        "pid": process.pid,
        "rss_bytes": memory.rss,
        "vms_bytes": memory.vms,
        "num_threads": process.num_threads(),
        "read_bytes": read_bytes,
        "write_bytes": write_bytes,
        "system_available_bytes": system_memory.available,
        "system_memory_percent": system_memory.percent,
    }
    result.update(_proc_status_snapshot())
    result.update(_cgroup_snapshot())
    if fl_ctx is not None:
        result.update(_tensor_snapshot(fl_ctx))
    return result


class ServerResourceObserver(Widget):
    def __init__(self, trim_before_first_contribution: bool = False):
        super().__init__()
        if not isinstance(trim_before_first_contribution, bool):
            raise TypeError("trim_before_first_contribution must be a bool")
        self.trim_before_first_contribution = trim_before_first_contribution
        self._trimmed_rounds = set()

    def _log_record(
        self, fl_ctx: FLContext, event_name: str, memory_snapshot: Dict[str, Any] | None = None, **values
    ) -> Dict[str, Any]:
        if memory_snapshot is None:
            memory_snapshot = _memory_snapshot(fl_ctx)
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event": event_name,
            "source": "server",
            "round": fl_ctx.get_prop(AppConstants.CURRENT_ROUND),
            **memory_snapshot,
            **values,
        }
        self.log_info(fl_ctx, f"{EVENT_PREFIX}{json.dumps(record, sort_keys=True)}")
        return record

    def handle_event(self, event_type: str, fl_ctx: FLContext):
        event_name = _EVENT_NAMES.get(event_type)
        if event_name is None:
            return
        if event_type == EventType.START_RUN:
            self._trimmed_rounds.clear()
        values = {}
        if event_type == AppEventType.AFTER_AGGREGATION:
            aggregation_result = fl_ctx.get_prop(AppConstants.AGGREGATION_RESULT)
            aggregation_meta = getattr(aggregation_result, "meta", None) or {}
            values["aggregated_clients"] = aggregation_meta.get("nr_aggregated")
        before = self._log_record(fl_ctx, event_name, **values)
        round_number = fl_ctx.get_prop(AppConstants.CURRENT_ROUND)
        if (
            event_type == AppEventType.BEFORE_CONTRIBUTION_ACCEPT
            and self.trim_before_first_contribution
            and round_number not in self._trimmed_rounds
        ):
            self._trimmed_rounds.add(round_number)
            cleanup_memory()
            after_snapshot = _memory_snapshot(fl_ctx)
            self._log_record(
                fl_ctx,
                "server_allocator_trim_probe",
                memory_snapshot=after_snapshot,
                trigger="before_first_contribution",
                rss_before_trim_bytes=before["rss_bytes"],
                cgroup_before_trim_bytes=before.get("cgroup_memory_current_bytes"),
                tensor_storage_before_trim_bytes=before.get("unique_tensor_storage_bytes"),
                rss_released_by_trim_bytes=max(0, before["rss_bytes"] - after_snapshot["rss_bytes"]),
            )
