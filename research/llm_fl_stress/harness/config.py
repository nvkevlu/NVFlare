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

"""Scenario schema and validation."""

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Dict, Optional, Type, TypeVar


_DTYPE_BYTES = {"float16": 2, "bfloat16": 2, "float32": 4}
_SCHEMA_VERSION = 1
_DataclassType = TypeVar("_DataclassType")


@dataclass(frozen=True)
class ModelSpec:
    name: str
    parameter_count: int
    dtype: str
    tensor_shard_mib: int = 256


@dataclass(frozen=True)
class FederationSpec:
    clients: list[str]
    rounds: int = 2
    simulator_threads: int = 2
    launch_external_process: bool = True
    server_memory_gc_rounds: int = 1
    client_memory_gc_rounds: int = 1
    server_trim_before_first_contribution: bool = False


@dataclass(frozen=True)
class TransportSpec:
    enable_tensor_disk_offload: bool = True
    tensor_download_chunk_size: int = 2097152
    streaming_chunk_size: Optional[int] = None
    streaming_window_size: Optional[int] = None
    streaming_ack_interval: Optional[int] = None
    streaming_max_out_seq_chunks: Optional[int] = None
    streaming_per_request_timeout: int = 900
    tensor_min_download_timeout: int = 900
    get_task_timeout: int = 1800
    submit_task_result_timeout: int = 1800
    max_resends: int = 3

    @property
    def f3_service_environment(self) -> Dict[str, str]:
        values = {
            "NVFLARE_STREAMING_CHUNK_SIZE": self.streaming_chunk_size,
            "NVFLARE_STREAMING_WINDOW_SIZE": self.streaming_window_size,
            "NVFLARE_STREAMING_ACK_INTERVAL": self.streaming_ack_interval,
            "NVFLARE_STREAMING_MAX_OUT_SEQ_CHUNKS": self.streaming_max_out_seq_chunks,
        }
        return {name: str(value) for name, value in values.items() if value is not None}


@dataclass(frozen=True)
class MonitoringSpec:
    sample_interval_seconds: float = 0.5
    gpu_sample_interval_seconds: float = 1.0


@dataclass(frozen=True)
class SuccessCriteria:
    require_job_success: bool = True
    require_monitor_samples: bool = True
    minimum_monitor_coverage: float = 0.9
    require_sentinel_checks: bool = True
    max_peak_process_tree_rss_gib: Optional[float] = None
    max_server_round_end_growth_percent: float = 10.0
    live_model_copy_factor: float = 6.0
    simulation_client_copy_factor: float = 2.5
    fixed_server_overhead_gib: float = 1.0
    fixed_client_overhead_gib: float = 0.5
    fixed_simulation_overhead_gib: float = 2.0
    disk_payload_factor: float = 5.0
    free_memory_reserve_fraction: float = 0.2
    required_artifacts: tuple[str, ...] = (
        "manifest.json",
        "scenario.json",
        "events.jsonl",
        "metrics/process_samples.csv",
        "result.json",
    )


@dataclass(frozen=True)
class Scenario:
    schema_version: int
    name: str
    description: str
    model: ModelSpec
    federation: FederationSpec
    transport: TransportSpec
    monitoring: MonitoringSpec
    success_criteria: SuccessCriteria

    @property
    def dtype_bytes(self) -> int:
        return _DTYPE_BYTES[self.model.dtype]

    @property
    def payload_bytes(self) -> int:
        return self.model.parameter_count * self.dtype_bytes

    @property
    def payload_gib(self) -> float:
        return self.payload_bytes / (1024**3)

    @property
    def expected_wire_bytes_per_round(self) -> int:
        return self.payload_bytes * len(self.federation.clients) * 2

    @property
    def planned_server_capacity_bytes(self) -> int:
        criteria = self.success_criteria
        fixed_bytes = criteria.fixed_server_overhead_gib * (1024**3)
        live_bytes = self.payload_bytes * criteria.live_model_copy_factor
        return int((fixed_bytes + live_bytes) / (1.0 - criteria.free_memory_reserve_fraction))

    @property
    def planned_client_capacity_bytes(self) -> int:
        criteria = self.success_criteria
        fixed_bytes = criteria.fixed_client_overhead_gib * (1024**3)
        live_bytes = self.payload_bytes * criteria.simulation_client_copy_factor
        return int((fixed_bytes + live_bytes) / (1.0 - criteria.free_memory_reserve_fraction))

    @property
    def planned_simulation_capacity_bytes(self) -> int:
        criteria = self.success_criteria
        copy_factor = criteria.live_model_copy_factor + (
            len(self.federation.clients) * criteria.simulation_client_copy_factor
        )
        fixed_bytes = criteria.fixed_simulation_overhead_gib * (1024**3)
        return int((fixed_bytes + self.payload_bytes * copy_factor) / (1.0 - criteria.free_memory_reserve_fraction))

    @property
    def planned_disk_capacity_bytes(self) -> int:
        return int(self.payload_bytes * self.success_criteria.disk_payload_factor)

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["success_criteria"]["required_artifacts"] = list(self.success_criteria.required_artifacts)
        return result


def _build_dataclass(dataclass_type: Type[_DataclassType], data: Dict[str, Any], path: str) -> _DataclassType:
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    allowed = {field.name for field in fields(dataclass_type)}
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ValueError(f"{path} contains unknown field(s): {unknown}")
    return dataclass_type(**data)


def _positive_int(value: int, path: str, allow_zero: bool = False) -> None:
    minimum = 0 if allow_zero else 1
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        comparator = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{path} must be a {comparator} integer")


def _validate(scenario: Scenario) -> None:
    if scenario.schema_version != _SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {_SCHEMA_VERSION}")
    if not scenario.name.strip():
        raise ValueError("name must not be empty")
    if scenario.model.dtype not in _DTYPE_BYTES:
        raise ValueError(f"model.dtype must be one of {sorted(_DTYPE_BYTES)}")
    _positive_int(scenario.model.parameter_count, "model.parameter_count")
    _positive_int(scenario.model.tensor_shard_mib, "model.tensor_shard_mib")
    if not scenario.federation.clients or len(set(scenario.federation.clients)) != len(scenario.federation.clients):
        raise ValueError("federation.clients must contain unique client names")
    if any(not isinstance(client, str) or not client.strip() for client in scenario.federation.clients):
        raise ValueError("federation.clients must contain non-empty strings")
    expected_clients = [f"site-{index}" for index in range(1, len(scenario.federation.clients) + 1)]
    if scenario.federation.clients != expected_clients:
        raise ValueError(f"federation.clients must be sequential site names: {expected_clients}")
    _positive_int(scenario.federation.rounds, "federation.rounds")
    _positive_int(scenario.federation.simulator_threads, "federation.simulator_threads")
    _positive_int(scenario.federation.server_memory_gc_rounds, "federation.server_memory_gc_rounds", True)
    _positive_int(scenario.federation.client_memory_gc_rounds, "federation.client_memory_gc_rounds", True)
    if not isinstance(scenario.federation.server_trim_before_first_contribution, bool):
        raise ValueError("federation.server_trim_before_first_contribution must be a boolean")
    _positive_int(scenario.transport.tensor_download_chunk_size, "transport.tensor_download_chunk_size")
    for field_name in ("streaming_chunk_size", "streaming_window_size", "streaming_ack_interval"):
        value = getattr(scenario.transport, field_name)
        if value is not None:
            _positive_int(value, f"transport.{field_name}")
    stream_chunk_size = scenario.transport.streaming_chunk_size
    stream_window_size = scenario.transport.streaming_window_size
    stream_ack_interval = scenario.transport.streaming_ack_interval
    if stream_chunk_size is not None and stream_window_size is not None and stream_chunk_size > stream_window_size:
        raise ValueError("transport.streaming_chunk_size must not exceed streaming_window_size")
    if stream_ack_interval is not None and stream_window_size is not None and stream_ack_interval > stream_window_size:
        raise ValueError("transport.streaming_ack_interval must not exceed streaming_window_size")
    _positive_int(scenario.transport.streaming_per_request_timeout, "transport.streaming_per_request_timeout")
    _positive_int(scenario.transport.tensor_min_download_timeout, "transport.tensor_min_download_timeout")
    _positive_int(scenario.transport.get_task_timeout, "transport.get_task_timeout")
    _positive_int(scenario.transport.submit_task_result_timeout, "transport.submit_task_result_timeout")
    _positive_int(scenario.transport.max_resends, "transport.max_resends", True)
    if scenario.transport.get_task_timeout < scenario.transport.streaming_per_request_timeout:
        raise ValueError("transport.get_task_timeout must be at least streaming_per_request_timeout")
    if scenario.transport.tensor_min_download_timeout < scenario.transport.streaming_per_request_timeout:
        raise ValueError("transport.tensor_min_download_timeout must be at least streaming_per_request_timeout")
    if scenario.monitoring.sample_interval_seconds <= 0:
        raise ValueError("monitoring.sample_interval_seconds must be positive")
    if scenario.monitoring.gpu_sample_interval_seconds <= 0:
        raise ValueError("monitoring.gpu_sample_interval_seconds must be positive")
    criteria = scenario.success_criteria
    if not 0 < criteria.minimum_monitor_coverage <= 1:
        raise ValueError("success_criteria.minimum_monitor_coverage must be in (0, 1]")
    if criteria.max_peak_process_tree_rss_gib is not None and criteria.max_peak_process_tree_rss_gib <= 0:
        raise ValueError("success_criteria.max_peak_process_tree_rss_gib must be positive or null")
    if criteria.max_server_round_end_growth_percent < 0:
        raise ValueError("success_criteria.max_server_round_end_growth_percent must be non-negative")
    if criteria.live_model_copy_factor < 1:
        raise ValueError("success_criteria.live_model_copy_factor must be at least 1")
    if criteria.simulation_client_copy_factor < 1:
        raise ValueError("success_criteria.simulation_client_copy_factor must be at least 1")
    if criteria.fixed_server_overhead_gib < 0:
        raise ValueError("success_criteria.fixed_server_overhead_gib must be non-negative")
    if criteria.fixed_client_overhead_gib < 0:
        raise ValueError("success_criteria.fixed_client_overhead_gib must be non-negative")
    if criteria.fixed_simulation_overhead_gib < 0:
        raise ValueError("success_criteria.fixed_simulation_overhead_gib must be non-negative")
    if criteria.disk_payload_factor < 1:
        raise ValueError("success_criteria.disk_payload_factor must be at least 1")
    if not 0 <= criteria.free_memory_reserve_fraction < 1:
        raise ValueError("success_criteria.free_memory_reserve_fraction must be in [0, 1)")


def load_scenario(path: Path | str) -> Scenario:
    scenario_path = Path(path)
    with scenario_path.open(encoding="utf-8") as file:
        raw = json.load(file)
    if not isinstance(raw, dict):
        raise ValueError("scenario root must be a JSON object")
    allowed = {
        "schema_version",
        "name",
        "description",
        "model",
        "federation",
        "transport",
        "monitoring",
        "success_criteria",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"scenario contains unknown field(s): {unknown}")
    required = allowed - {"description"}
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"scenario is missing required field(s): {missing}")
    success_data = dict(raw["success_criteria"])
    if "required_artifacts" in success_data:
        success_data["required_artifacts"] = tuple(success_data["required_artifacts"])
    scenario = Scenario(
        schema_version=raw["schema_version"],
        name=raw["name"],
        description=raw.get("description", ""),
        model=_build_dataclass(ModelSpec, raw["model"], "model"),
        federation=_build_dataclass(FederationSpec, raw["federation"], "federation"),
        transport=_build_dataclass(TransportSpec, raw["transport"], "transport"),
        monitoring=_build_dataclass(MonitoringSpec, raw["monitoring"], "monitoring"),
        success_criteria=_build_dataclass(SuccessCriteria, success_data, "success_criteria"),
    )
    _validate(scenario)
    return scenario
