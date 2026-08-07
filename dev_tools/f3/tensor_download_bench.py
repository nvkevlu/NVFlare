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
"""Benchmark PyTorch tensor transfer through TensorDecomposer and Download Service.

Start the receiver on the destination host:

    python dev_tools/f3/tensor_download_bench.py recv \
        --url tcp://0.0.0.0:8002 --offload-dir /fast/local/disk

Run the sender on the host containing the checkpoint:

    python dev_tools/f3/tensor_download_bench.py send \
        --url tcp://<receiver-host>:8002 \
        --checkpoint /tmp/gpt-j-6b/pytorch_model.bin

The sender runs both memory and disk-offload modes by default. The timed result
includes FOBS decomposition, Download Service transfer, receiver reconstruction,
and validation. Use the same optional comm_config.yml on both hosts to tune F3.
For production-equivalent transport TLS, use grpc:// URLs with the synchronous
gRPC profile plus --connection-security tls and role-specific --credentials-dir
paths. Cell end-to-end message encryption remains disabled.
"""

import argparse
import gc
import hashlib
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Optional

import psutil
import torch

import nvflare.fuel.utils.fobs as fobs
from nvflare.apis.fl_constant import ConnectionSecurity

# This repository-local benchmark intentionally follows the internal disk-offload
# context keys so it exercises the same path as production workflows.
from nvflare.app_common.utils.tensor_disk_offload_context import (
    _ENABLE_TENSOR_DISK_OFFLOAD,
    _TENSOR_DISK_OFFLOAD_ROOT_DIR,
)
from nvflare.app_opt.pt.decomposers import TensorDecomposer
from nvflare.app_opt.pt.tensor_downloader import TensorConsumer, _can_stream_tensor_directly
from nvflare.fuel.f3.cellnet.cell import Cell
from nvflare.fuel.f3.cellnet.defs import MessageHeaderKey, ReturnCode
from nvflare.fuel.f3.cellnet.utils import make_reply
from nvflare.fuel.f3.message import Message
from nvflare.fuel.utils.fobs.datum import TEN_MEGA

try:
    from .cellnet_bench import (
        GB,
        MB,
        add_cell_security_args,
        configure_f3,
        f3_config_summary,
        parse_byte_size,
        resolve_cell_security,
    )
except ImportError:
    from cellnet_bench import (
        GB,
        MB,
        add_cell_security_args,
        configure_f3,
        f3_config_summary,
        parse_byte_size,
        resolve_cell_security,
    )

CHANNEL = "tensor_download_bench"
CONFIGURE_TOPIC = "configure"
TRANSFER_TOPIC = "transfer"
RX_FQCN = "server"
TX_FQCN = "sender"

MODE_MEMORY = "memory"
MODE_DISK = "disk"
MODES = (MODE_MEMORY, MODE_DISK)

MODE_HEADER = "tensor_bench_mode"
RUN_ID_HEADER = "tensor_bench_run_id"
DIRECT_NEGOTIATION_KEY = "direct_negotiation_enabled"

DEFAULT_CHECKPOINT = "/tmp/gpt-j-6b/pytorch_model.bin"
DEFAULT_TIMEOUT = 3600.0
DEFAULT_CONNECT_TIMEOUT = 30.0
DEFAULT_SAMPLE_INTERVAL = 0.05
DIRECT_TENSOR_MIN_BYTES = TEN_MEGA


def format_bytes(num_bytes: int) -> str:
    if num_bytes >= GB:
        return f"{num_bytes / GB:,.2f} GiB"
    return f"{num_bytes / MB:,.2f} MiB"


def throughput(num_bytes: int, seconds: float) -> tuple[float, float]:
    if seconds <= 0:
        return 0.0, 0.0
    return num_bytes / MB / seconds, num_bytes * 8 / 1_000_000_000 / seconds


def parse_modes(value: str) -> tuple[str, ...]:
    modes = tuple(dict.fromkeys(part.strip().lower() for part in value.split(",") if part.strip()))
    if not modes:
        raise argparse.ArgumentTypeError("at least one mode is required")
    invalid = [mode for mode in modes if mode not in MODES]
    if invalid:
        raise argparse.ArgumentTypeError(f"invalid mode(s) {', '.join(invalid)}; use memory, disk, or memory,disk")
    return modes


def byte_size_arg(value: str) -> int:
    try:
        size = parse_byte_size(value, "--max-bytes")
    except ValueError as ex:
        raise argparse.ArgumentTypeError(str(ex)) from ex
    if size <= 0:
        raise argparse.ArgumentTypeError("--max-bytes must be greater than zero")
    return size


def tensor_nbytes(tensor: torch.Tensor) -> int:
    return tensor.numel() * tensor.element_size()


def unique_tensor_stats(tensors: Mapping[str, torch.Tensor]) -> tuple[int, int]:
    unique_tensors = {id(tensor): tensor for tensor in tensors.values()}
    return len(unique_tensors), sum(tensor_nbytes(tensor) for tensor in unique_tensors.values())


def unique_tensor_items(tensors: Mapping[str, torch.Tensor]):
    """Yield one deterministic key/tensor pair for each transfer item."""
    seen = set()
    for key, tensor in sorted(tensors.items()):
        tensor_id = id(tensor)
        if tensor_id in seen:
            continue
        seen.add(tensor_id)
        yield key, tensor


def tensor_key_digest(keys) -> str:
    digest = hashlib.sha256()
    for key in sorted(keys):
        digest.update(key.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def tensor_fingerprint(tensor: torch.Tensor) -> str:
    """Hash contiguous tensor storage without serializing or copying it."""
    tensor = tensor.detach().cpu()
    if not tensor.is_contiguous():
        tensor = tensor.contiguous()
    byte_view = tensor.reshape(-1).view(torch.uint8).numpy()
    return hashlib.sha256(memoryview(byte_view)).hexdigest()


def direct_tensor_fingerprint(tensor: torch.Tensor) -> str:
    """Hash direct-path tensor bytes without serializing or copying the payload."""
    if not _can_stream_tensor_directly(tensor):
        raise ValueError("direct tensor fingerprint requires a supported contiguous CPU tensor")
    return tensor_fingerprint(tensor)


def direct_path_manifest(tensors: Mapping[str, torch.Tensor]) -> dict:
    """Describe the unique transfer items that can use the direct-memory path."""
    eligible = []
    fallback = []
    for key, tensor in unique_tensor_items(tensors):
        item = (key, tensor, tensor_nbytes(tensor))
        if key != "__metadata__" and item[2] >= DIRECT_TENSOR_MIN_BYTES and _can_stream_tensor_directly(tensor):
            eligible.append(item)
        else:
            fallback.append(item)

    # Select the smallest eligible item for post-transfer direct-path validation.
    direct_sample = None
    if eligible:
        sample_key, sample_tensor, sample_bytes = min(eligible, key=lambda item: (item[2], item[0]))
        direct_sample = {
            "key": sample_key,
            "shape": list(sample_tensor.shape),
            "dtype": str(sample_tensor.dtype),
            "num_bytes": sample_bytes,
        }

    return {
        "eligible_items": len(eligible),
        "eligible_bytes": sum(item[2] for item in eligible),
        "fallback_items": len(fallback),
        "fallback_bytes": sum(item[2] for item in fallback),
        "sample": direct_sample,
    }


def unwrap_state_dict(checkpoint) -> Mapping:
    if not isinstance(checkpoint, Mapping):
        raise TypeError(f"checkpoint must contain a mapping, got {type(checkpoint).__name__}")
    for key in ("state_dict", "model_state_dict"):
        candidate = checkpoint.get(key)
        if isinstance(candidate, Mapping):
            return candidate
    return checkpoint


def select_tensors(state_dict: Mapping, max_bytes: Optional[int] = None) -> dict[str, torch.Tensor]:
    tensors = {str(key): value for key, value in state_dict.items() if isinstance(value, torch.Tensor)}
    if not tensors:
        raise ValueError("checkpoint does not contain any PyTorch tensors")

    if max_bytes is not None:
        selected = {}
        selected_bytes = 0
        selected_ids = set()
        for key, tensor in sorted(tensors.items(), key=lambda item: (tensor_nbytes(item[1]), item[0])):
            tensor_id = id(tensor)
            additional_bytes = 0 if tensor_id in selected_ids else tensor_nbytes(tensor)
            if not selected or selected_bytes + additional_bytes <= max_bytes:
                selected[key] = tensor
                selected_bytes += additional_bytes
                selected_ids.add(tensor_id)
        tensors = selected

    non_contiguous = [key for key, tensor in tensors.items() if not tensor.is_contiguous()]
    if non_contiguous:
        print(f"[send] making {len(non_contiguous)} non-contiguous tensor(s) contiguous for safetensors")
        contiguous_by_id = {}
        for key in non_contiguous:
            source = tensors[key]
            source_id = id(source)
            if source_id not in contiguous_by_id:
                contiguous_by_id[source_id] = source.contiguous()
            tensors[key] = contiguous_by_id[source_id]
    return tensors


def load_checkpoint(path: Path, max_bytes: Optional[int] = None) -> dict[str, torch.Tensor]:
    if not path.is_file():
        raise FileNotFoundError(f"checkpoint does not exist: {path}")
    print(f"[send] loading checkpoint metadata with mmap: {path} ({format_bytes(path.stat().st_size)})")
    checkpoint = torch.load(path, map_location="cpu", weights_only=True, mmap=True)
    tensors = select_tensors(unwrap_state_dict(checkpoint), max_bytes=max_bytes)
    logical_bytes = sum(tensor_nbytes(tensor) for tensor in tensors.values())
    unique_count, transfer_bytes = unique_tensor_stats(tensors)
    print(
        f"[send] selected {len(tensors):,} tensor references totaling {format_bytes(logical_bytes)}; "
        f"{unique_count:,} unique tensors require {format_bytes(transfer_bytes)} of transfer"
    )
    if max_bytes is not None:
        print(f"[send] --max-bytes={format_bytes(max_bytes)} is active; this is a smoke test, not the full checkpoint")
    return tensors


def build_transfer_payload(checkpoint: Path, tensors: dict[str, torch.Tensor]) -> dict:
    sample_key, sample_tensor = min(tensors.items(), key=lambda item: (tensor_nbytes(item[1]), item[0]))
    unique_count, transfer_bytes = unique_tensor_stats(tensors)
    return {
        "checkpoint": checkpoint.name,
        "tensor_count": len(tensors),
        "tensor_bytes": sum(tensor_nbytes(tensor) for tensor in tensors.values()),
        "unique_tensor_count": unique_count,
        "transfer_bytes": transfer_bytes,
        "tensor_key_digest": tensor_key_digest(tensors),
        "sample": {
            "key": sample_key,
            "shape": list(sample_tensor.shape),
            "dtype": str(sample_tensor.dtype),
            "num_bytes": tensor_nbytes(sample_tensor),
        },
        "direct_path": direct_path_manifest(tensors),
        "tensors": tensors,
    }


def directory_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except FileNotFoundError:
                pass
    return total


class ResourceSampler:
    def __init__(self, interval: float = DEFAULT_SAMPLE_INTERVAL):
        self.interval = interval
        self.process = psutil.Process()
        self.baseline = self.process.memory_info().rss
        self.peak = self.baseline
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._sample, name="tensor-bench-rss", daemon=True)
        self._thread.start()

    def _sample(self):
        while not self._stop.wait(self.interval):
            self.peak = max(self.peak, self.process.memory_info().rss)

    def stop(self) -> dict:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(1.0, self.interval * 2))
        self.peak = max(self.peak, self.process.memory_info().rss)
        return {
            "rss_baseline_bytes": self.baseline,
            "rss_peak_bytes": self.peak,
            "rss_peak_delta_bytes": max(0, self.peak - self.baseline),
        }


def materialize_tensor(value):
    if isinstance(value, torch.Tensor):
        return value
    materialize = getattr(value, "materialize", None)
    if not callable(materialize):
        raise TypeError(f"expected a tensor or lazy tensor reference, got {type(value).__name__}")
    return materialize()


def received_unique_tensor_count(tensors: Mapping, mode: str) -> int:
    if mode == MODE_MEMORY:
        return len({id(value) for value in tensors.values()})

    # Disk mode creates a lightweight _LazyRef for each occurrence. Aliases are
    # distinct Python reference objects but point to the same safetensors key.
    identities = set()
    for value in tensors.values():
        file_path = getattr(value, "file_path", None)
        key = getattr(value, "key", None)
        identities.add((file_path, key) if file_path is not None and key is not None else id(value))
    return len(identities)


class DirectPathTracker:
    """Per-run receiver evidence recorded by TensorConsumer's direct decoder."""

    def __init__(self):
        self._lock = threading.Lock()
        self._run_id = None
        self._direct_negotiation_enabled = True
        self._items = 0
        self._tensor_bytes = 0
        self._wire_bytes = 0
        self._tensor_ids = set()

    def reset(self, run_id: str, direct_negotiation_enabled: bool = True):
        if type(direct_negotiation_enabled) is not bool:
            raise TypeError("direct_negotiation_enabled must be a bool")
        with self._lock:
            self._run_id = run_id
            self._direct_negotiation_enabled = direct_negotiation_enabled
            self._items = 0
            self._tensor_bytes = 0
            self._wire_bytes = 0
            self._tensor_ids = set()

    def negotiation_enabled(self) -> bool:
        with self._lock:
            return self._direct_negotiation_enabled

    def record(self, items):
        with self._lock:
            if self._run_id is None:
                return
            for item in items:
                tensor = getattr(item, "tensor", None)
                if not isinstance(tensor, torch.Tensor):
                    continue
                self._items += 1
                self._tensor_bytes += tensor_nbytes(tensor)
                self._wire_bytes += len(item)
                self._tensor_ids.add(id(tensor))

    def snapshot(self, run_id: str) -> dict:
        with self._lock:
            if run_id != self._run_id:
                raise ValueError(f"direct-path metrics are for run {self._run_id!r}, not {run_id!r}")
            return {
                "items": self._items,
                "tensor_bytes": self._tensor_bytes,
                "wire_bytes": self._wire_bytes,
                "tensor_ids": frozenset(self._tensor_ids),
            }


_DIRECT_PATH_TRACKER = DirectPathTracker()
_DIRECT_PATH_TRACKING_INSTALLED = False


def install_direct_path_tracking():
    """Instrument direct decoding and apply the benchmark's per-run negotiation policy."""
    global _DIRECT_PATH_TRACKING_INSTALLED
    if _DIRECT_PATH_TRACKING_INSTALLED:
        return

    original_consume_direct_chunk = TensorConsumer.consume_direct_chunk
    original_get_initial_state = TensorConsumer.get_initial_state

    def tracked_consume_direct_chunk(consumer, data):
        items = original_consume_direct_chunk(consumer, data)
        _DIRECT_PATH_TRACKER.record(items)
        return items

    def benchmark_get_initial_state(consumer):
        if not _DIRECT_PATH_TRACKER.negotiation_enabled():
            return None
        return original_get_initial_state(consumer)

    TensorConsumer.consume_direct_chunk = tracked_consume_direct_chunk
    TensorConsumer.get_initial_state = benchmark_get_initial_state
    _DIRECT_PATH_TRACKING_INSTALLED = True


def _validate_tensor_sample(tensors: Mapping, sample: dict, label: str) -> torch.Tensor:
    if not isinstance(sample, dict):
        raise TypeError(f"{label} must be a dict")
    sample_key = sample.get("key")
    if sample_key not in tensors:
        raise ValueError(f"{label} tensor {sample_key!r} is missing")
    sample_tensor = materialize_tensor(tensors[sample_key])
    actual = {
        "shape": list(sample_tensor.shape),
        "dtype": str(sample_tensor.dtype),
        "num_bytes": tensor_nbytes(sample_tensor),
    }
    for field, value in actual.items():
        if value != sample.get(field):
            raise ValueError(f"{label} tensor {field} mismatch: received {value!r}, expected {sample.get(field)!r}")
    return sample_tensor


def validate_received_payload(
    payload: dict,
    mode: str,
    direct_path_stats: Optional[dict] = None,
    direct_negotiation_enabled: bool = True,
) -> dict:
    if type(direct_negotiation_enabled) is not bool:
        raise TypeError("direct_negotiation_enabled must be a bool")
    if not isinstance(payload, dict):
        raise TypeError(f"transfer payload must be a dict, got {type(payload).__name__}")
    tensors = payload.get("tensors")
    if not isinstance(tensors, dict):
        raise TypeError(f"payload tensors must be a dict, got {type(tensors).__name__}")

    expected_count = payload.get("tensor_count")
    if len(tensors) != expected_count:
        raise ValueError(f"received {len(tensors)} tensors but expected {expected_count}")
    if tensor_key_digest(tensors) != payload.get("tensor_key_digest"):
        raise ValueError("received tensor keys do not match the sender")
    actual_unique_count = received_unique_tensor_count(tensors, mode)
    if actual_unique_count != payload.get("unique_tensor_count"):
        raise ValueError(
            f"received {actual_unique_count} unique tensor objects but expected {payload.get('unique_tensor_count')}"
        )

    if mode == MODE_MEMORY:
        invalid = [key for key, value in tensors.items() if not isinstance(value, torch.Tensor)]
    else:
        invalid = [
            key
            for key, value in tensors.items()
            if isinstance(value, torch.Tensor) or not callable(getattr(value, "materialize", None))
        ]
    if invalid:
        raise TypeError(f"{mode} mode produced unexpected values for {len(invalid)} tensor(s), first={invalid[0]!r}")

    sample = payload.get("sample", {})
    sample_key = sample.get("key")
    sample_tensor = _validate_tensor_sample(tensors, sample, "sample")
    sample_sha256 = tensor_fingerprint(sample_tensor)

    direct_path = payload.get("direct_path")
    if not isinstance(direct_path, dict):
        raise TypeError("payload direct_path must be a dict")
    eligible_items = direct_path.get("eligible_items")
    eligible_bytes = direct_path.get("eligible_bytes")
    eligibility_fallback_items = direct_path.get("fallback_items")
    eligibility_fallback_bytes = direct_path.get("fallback_bytes")
    for name, value in (
        ("eligible_items", eligible_items),
        ("eligible_bytes", eligible_bytes),
        ("fallback_items", eligibility_fallback_items),
        ("fallback_bytes", eligibility_fallback_bytes),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"direct_path {name} must be a non-negative integer")
    if eligible_items + eligibility_fallback_items != actual_unique_count:
        raise ValueError("direct-path eligible/fallback item counts do not match unique tensor count")
    if eligible_bytes + eligibility_fallback_bytes != payload.get("transfer_bytes"):
        raise ValueError("direct-path eligible/fallback bytes do not match transfer bytes")

    direct_path_stats = direct_path_stats or {}
    direct_items = direct_path_stats.get("items", 0)
    direct_bytes = direct_path_stats.get("tensor_bytes", 0)
    direct_wire_bytes = direct_path_stats.get("wire_bytes", 0)
    direct_tensor_ids = direct_path_stats.get("tensor_ids", frozenset())
    expect_direct = mode == MODE_MEMORY and direct_negotiation_enabled
    expected_direct_items = eligible_items if expect_direct else 0
    expected_direct_bytes = eligible_bytes if expect_direct else 0
    if direct_items != expected_direct_items or direct_bytes != expected_direct_bytes:
        raise ValueError(
            f"{mode} mode used the direct path for {direct_items} item(s) / {direct_bytes} bytes; "
            f"expected {expected_direct_items} item(s) / {expected_direct_bytes} bytes"
        )

    direct_sample = direct_path.get("sample")
    direct_sample_key = None
    direct_sample_bytes = 0
    direct_sample_sha256 = None
    if eligible_items:
        direct_sample_key = direct_sample.get("key")
        direct_sample_bytes = direct_sample.get("num_bytes")
        if type(direct_sample_bytes) is not int:
            raise ValueError("direct sample num_bytes must be an integer")
        if direct_sample_bytes < DIRECT_TENSOR_MIN_BYTES:
            raise ValueError(
                f"direct sample is only {direct_sample_bytes} bytes; expected at least {DIRECT_TENSOR_MIN_BYTES}"
            )
        if mode == MODE_MEMORY:
            direct_sample_tensor = _validate_tensor_sample(tensors, direct_sample, "direct sample")
            if direct_negotiation_enabled and id(direct_sample_tensor) not in direct_tensor_ids:
                raise ValueError(f"direct sample tensor {direct_sample_key!r} was not observed on the direct path")
            direct_sample_sha256 = (
                sample_sha256
                if direct_sample_tensor is sample_tensor
                else direct_tensor_fingerprint(direct_sample_tensor)
            )
    elif direct_sample is not None:
        raise ValueError("direct_path sample must be absent when there are no eligible tensors")

    fallback_items = actual_unique_count - direct_items
    fallback_bytes = payload.get("transfer_bytes") - direct_bytes

    return {
        "tensor_count": len(tensors),
        "tensor_bytes": payload.get("tensor_bytes"),
        "unique_tensor_count": actual_unique_count,
        "transfer_bytes": payload.get("transfer_bytes"),
        "sample_key": sample_key,
        "sample_materialized_bytes": tensor_nbytes(sample_tensor),
        "sample_sha256": sample_sha256,
        DIRECT_NEGOTIATION_KEY: direct_negotiation_enabled,
        "direct_eligible_items": eligible_items,
        "direct_eligible_bytes": eligible_bytes,
        "direct_items": direct_items,
        "direct_bytes": direct_bytes,
        "direct_wire_bytes": direct_wire_bytes,
        "fallback_items": fallback_items,
        "fallback_bytes": fallback_bytes,
        "direct_sample_key": direct_sample_key,
        "direct_sample_bytes": direct_sample_bytes,
        "direct_sample_materialized_bytes": direct_sample_bytes if mode == MODE_MEMORY else 0,
        "direct_sample_sha256": direct_sample_sha256,
    }


def check_reply(reply: Message, action: str) -> dict:
    rc = reply.get_header(MessageHeaderKey.RETURN_CODE, ReturnCode.OK)
    if rc != ReturnCode.OK:
        error = reply.get_header(MessageHeaderKey.ERROR, "no error details")
        raise RuntimeError(f"{action} failed: {rc}: {error}")
    if not isinstance(reply.payload, dict):
        raise RuntimeError(f"{action} returned an invalid response: {type(reply.payload).__name__}")
    return reply.payload


def validate_sender_fingerprints(result: dict, payload: dict, tensors: Mapping[str, torch.Tensor], mode: str):
    """Compare receiver digests after the timed transfer has completed."""
    sample_key = payload["sample"]["key"]
    sample_sha256 = tensor_fingerprint(tensors[sample_key])
    if sample_sha256 != result.get("sample_sha256"):
        raise ValueError(
            f"sample tensor sha256 mismatch: receiver {result.get('sample_sha256')!r}, sender {sample_sha256!r}"
        )

    if mode == MODE_MEMORY:
        direct_sample_key = payload["direct_path"]["sample"]["key"]
        direct_sha256 = direct_tensor_fingerprint(tensors[direct_sample_key])
        if direct_sha256 != result.get("direct_sample_sha256"):
            raise ValueError(
                "direct sample tensor sha256 mismatch: "
                f"receiver {result.get('direct_sample_sha256')!r}, sender {direct_sha256!r}"
            )
    elif result.get("direct_sample_sha256") is not None:
        raise ValueError("disk mode must not materialize or hash the direct sample")


class TensorBenchmarkReceiver:
    def __init__(self, cell: Cell, offload_root: Path, sample_interval: float):
        self.cell = cell
        self.offload_root = offload_root
        self.sample_interval = sample_interval
        self._lock = threading.Lock()
        self._run_id = None
        self._mode = None
        self._direct_negotiation_enabled = True
        self._sampler = None
        self._configured_at = None

    def configure(self, request: Message) -> Message:
        try:
            payload = request.payload
            if not isinstance(payload, dict):
                raise TypeError("configuration payload must be a dict")
            run_id = payload.get("run_id")
            mode = payload.get("mode")
            direct_negotiation_enabled = payload.get(DIRECT_NEGOTIATION_KEY, True)
            if not isinstance(run_id, str) or not run_id:
                raise ValueError("run_id must be a non-empty string")
            if mode not in MODES:
                raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
            if type(direct_negotiation_enabled) is not bool:
                raise ValueError(f"{DIRECT_NEGOTIATION_KEY} must be a bool")

            with self._lock:
                if self._sampler is not None:
                    self._sampler.stop()
                self.cell.update_fobs_context(
                    {
                        _ENABLE_TENSOR_DISK_OFFLOAD: mode == MODE_DISK,
                        _TENSOR_DISK_OFFLOAD_ROOT_DIR: str(self.offload_root),
                    }
                )
                self._run_id = run_id
                self._mode = mode
                self._direct_negotiation_enabled = direct_negotiation_enabled
                _DIRECT_PATH_TRACKER.reset(run_id, direct_negotiation_enabled)
                self._sampler = ResourceSampler(self.sample_interval)
                self._sampler.start()
                self._configured_at = time.perf_counter()
            direct_status = "enabled" if direct_negotiation_enabled else "disabled-control"
            print(f"[recv] ready for run={run_id} mode={mode} direct-negotiation={direct_status}")
            return make_reply(
                ReturnCode.OK,
                body={
                    "status": "ready",
                    "run_id": run_id,
                    "mode": mode,
                    DIRECT_NEGOTIATION_KEY: direct_negotiation_enabled,
                },
            )
        except Exception as ex:
            return make_reply(ReturnCode.INVALID_REQUEST, error=str(ex))

    def transfer(self, request: Message) -> Message:
        callback_started = time.perf_counter()
        mode = request.get_header(MODE_HEADER)
        run_id = request.get_header(RUN_ID_HEADER)
        try:
            with self._lock:
                if run_id != self._run_id or mode != self._mode or self._sampler is None:
                    raise ValueError(
                        f"transfer run/mode ({run_id!r}, {mode!r}) does not match "
                        f"configuration ({self._run_id!r}, {self._mode!r})"
                    )
                sampler = self._sampler
                configured_at = self._configured_at
                direct_negotiation_enabled = self._direct_negotiation_enabled
                self._sampler = None
                self._configured_at = None

            memory = sampler.stop()
            receiver_observed_seconds = callback_started - configured_at
            validation_started = time.perf_counter()
            direct_path_stats = _DIRECT_PATH_TRACKER.snapshot(run_id)
            validation = validate_received_payload(
                request.payload,
                mode,
                direct_path_stats,
                direct_negotiation_enabled=direct_negotiation_enabled,
            )
            validation_seconds = time.perf_counter() - validation_started
            disk_bytes = directory_size(self.offload_root) if mode == MODE_DISK else 0
            callback_seconds = time.perf_counter() - callback_started
            result = {
                "status": "ok",
                "run_id": run_id,
                "mode": mode,
                "receiver_callback_seconds": callback_seconds,
                "receiver_observed_seconds": receiver_observed_seconds,
                "receiver_validation_seconds": validation_seconds,
                "disk_offload_bytes": disk_bytes,
                **memory,
                **validation,
            }
            mib_s, gbit_s = throughput(validation["transfer_bytes"], receiver_observed_seconds)
            print(
                f"[recv] RESULT mode={mode} tensors={validation['tensor_count']:,} "
                f"unique={validation['unique_tensor_count']:,} "
                f"transfer={format_bytes(validation['transfer_bytes'])} "
                f"logical={format_bytes(validation['tensor_bytes'])} observed={receiver_observed_seconds:,.3f}s "
                f"({mib_s:,.1f} MiB/s, {gbit_s:,.3f} Gbit/s) "
                f"validation={validation_seconds:,.3f}s callback={callback_seconds:,.3f}s "
                f"rss_delta={format_bytes(memory['rss_peak_delta_bytes'])} "
                f"disk={format_bytes(disk_bytes)} "
                f"direct-negotiation={'enabled' if direct_negotiation_enabled else 'disabled-control'} "
                f"direct={validation['direct_items']:,}/{format_bytes(validation['direct_bytes'])} "
                f"eligible={validation['direct_eligible_items']:,}/"
                f"{format_bytes(validation['direct_eligible_bytes'])} "
                f"fallback={validation['fallback_items']:,}/{format_bytes(validation['fallback_bytes'])} "
                f"direct_sample={validation['direct_sample_key']!r}"
            )

            # Release materialized tensors or lazy references. Lazy-reference
            # cleanup removes the per-transfer nvflare_tensors_* directory.
            request.payload["tensors"].clear()
            request.payload = None
            gc.collect()
            result["disk_offload_bytes_after_cleanup"] = directory_size(self.offload_root) if mode == MODE_DISK else 0
            return make_reply(ReturnCode.OK, body=result)
        except Exception as ex:
            with self._lock:
                sampler = self._sampler
                self._sampler = None
                self._configured_at = None
            if sampler is not None:
                sampler.stop()
            request.payload = None
            gc.collect()
            return make_reply(ReturnCode.PROCESS_EXCEPTION, error=str(ex))


def register_tensor_decomposer():
    fobs.register(TensorDecomposer)


def run_receiver(
    url: str,
    offload_dir: Optional[Path],
    sample_interval: float,
    connection_security: str = ConnectionSecurity.CLEAR,
    credentials_dir: Optional[Path] = None,
):
    secure, credentials = resolve_cell_security(RX_FQCN, url, connection_security, credentials_dir)
    install_direct_path_tracking()
    register_tensor_decomposer()
    base_dir = None
    if offload_dir is not None:
        base_dir = offload_dir.expanduser().resolve()
        base_dir.mkdir(parents=True, exist_ok=True)
    offload_root = Path(tempfile.mkdtemp(prefix="nvflare_tensor_bench_", dir=base_dir))

    cell = Cell(RX_FQCN, url, secure=secure, credentials=credentials)
    receiver = TensorBenchmarkReceiver(cell, offload_root, sample_interval)
    cell.register_request_cb(channel=CHANNEL, topic=CONFIGURE_TOPIC, cb=receiver.configure)
    cell.register_request_cb(channel=CHANNEL, topic=TRANSFER_TOPIC, cb=receiver.transfer)
    cell.start()
    print(f"[recv] listening on {url}, connection_security={connection_security}")
    print(f"[recv] disk-offload root: {offload_root}")
    print("[recv] waiting for memory and disk benchmark runs (Ctrl-C to stop)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("[recv] stopping")
    finally:
        cell.stop()
        shutil.rmtree(offload_root, ignore_errors=True)


def run_one_sender_mode(
    cell: Cell,
    url: str,
    checkpoint: Path,
    tensors: dict[str, torch.Tensor],
    mode: str,
    repetition: int,
    timeout: float,
    direct_negotiation_enabled: bool = True,
) -> dict:
    run_id = f"{mode}-{repetition}-{uuid.uuid4().hex[:8]}"
    payload = build_transfer_payload(checkpoint, tensors)
    direct_path = payload["direct_path"]
    if mode == MODE_MEMORY and direct_path["eligible_items"] == 0:
        raise ValueError(
            "memory mode requires at least one direct-path eligible tensor; "
            "increase --max-bytes or use the full checkpoint"
        )

    config_reply = cell.send_request(
        channel=CHANNEL,
        topic=CONFIGURE_TOPIC,
        target=RX_FQCN,
        request=Message(
            payload={
                "run_id": run_id,
                "mode": mode,
                DIRECT_NEGOTIATION_KEY: direct_negotiation_enabled,
            }
        ),
        timeout=timeout,
    )
    configured = check_reply(config_reply, f"configure {mode} mode")
    if configured.get(DIRECT_NEGOTIATION_KEY) is not direct_negotiation_enabled:
        raise RuntimeError("receiver did not acknowledge the requested direct-negotiation setting")

    request = Message(
        headers={MODE_HEADER: mode, RUN_ID_HEADER: run_id},
        payload=payload,
    )
    tensor_bytes = request.payload["tensor_bytes"]
    transfer_bytes = request.payload["transfer_bytes"]
    unique_count = request.payload["unique_tensor_count"]
    print(
        f"[send] starting mode={mode} repetition={repetition}: "
        f"{len(tensors):,} tensor references ({unique_count:,} unique), "
        f"{format_bytes(transfer_bytes)} transfer / {format_bytes(tensor_bytes)} logical to {url}; "
        f"direct-negotiation={'enabled' if direct_negotiation_enabled else 'disabled-control'}, "
        f"direct-eligible={direct_path['eligible_items']:,}/{format_bytes(direct_path['eligible_bytes'])}, "
        f"eligibility-fallback={direct_path['fallback_items']:,}/"
        f"{format_bytes(direct_path['fallback_bytes'])}"
    )
    sampler = ResourceSampler()
    sampler.start()
    started = time.perf_counter()
    try:
        reply = cell.send_request(
            channel=CHANNEL,
            topic=TRANSFER_TOPIC,
            target=RX_FQCN,
            request=request,
            timeout=timeout,
        )
    finally:
        sender_memory = sampler.stop()
    response_seconds = time.perf_counter() - started
    result = check_reply(reply, f"{mode} transfer")
    if result.get(DIRECT_NEGOTIATION_KEY) is not direct_negotiation_enabled:
        raise RuntimeError("receiver result does not match the requested direct-negotiation setting")
    sender_validation_started = time.perf_counter()
    validate_sender_fingerprints(result, payload, tensors, mode)
    sender_validation_seconds = time.perf_counter() - sender_validation_started
    validated_end_to_end_seconds = response_seconds + sender_validation_seconds
    transfer_seconds = result["receiver_observed_seconds"]
    mib_s, gbit_s = throughput(transfer_bytes, transfer_seconds)
    result.update(
        {
            "end_to_end_seconds": validated_end_to_end_seconds,
            "transfer_seconds": transfer_seconds,
            "response_seconds": response_seconds,
            "sender_validation_seconds": sender_validation_seconds,
            "mib_per_second": mib_s,
            "gbit_per_second": gbit_s,
            "sender_rss_baseline_bytes": sender_memory["rss_baseline_bytes"],
            "sender_rss_peak_bytes": sender_memory["rss_peak_bytes"],
            "sender_rss_peak_delta_bytes": sender_memory["rss_peak_delta_bytes"],
        }
    )
    print(
        f"[send] RESULT mode={mode} repetition={repetition}: {format_bytes(transfer_bytes)} transferred "
        f"in {transfer_seconds:,.3f}s ({mib_s:,.1f} MiB/s, {gbit_s:,.3f} Gbit/s) "
        f"validated_e2e={validated_end_to_end_seconds:,.3f}s "
        f"validation=recv:{result['receiver_validation_seconds']:,.3f}s/"
        f"send:{sender_validation_seconds:,.3f}s "
        f"sender_rss_delta={format_bytes(sender_memory['rss_peak_delta_bytes'])} "
        f"receiver_rss_delta={format_bytes(result['rss_peak_delta_bytes'])} "
        f"receiver_disk={format_bytes(result['disk_offload_bytes'])} "
        f"direct-negotiation={'enabled' if direct_negotiation_enabled else 'disabled-control'} "
        f"direct={result['direct_items']:,}/{format_bytes(result['direct_bytes'])} "
        f"fallback={result['fallback_items']:,}/{format_bytes(result['fallback_bytes'])} "
        f"direct_sample={result['direct_sample_key']!r}"
    )
    return result


def print_summary(results: list[dict]):
    print("\nSUMMARY (end-to-end TensorDecomposer + Download Service)")
    print("mode       run transfer_s      MiB/s    Gbit/s   sender RSS Δ  receiver RSS Δ  receiver disk")
    for index, result in enumerate(results, start=1):
        print(
            f"{result['mode']:<10} {index:>3} "
            f"{result['transfer_seconds']:>10.3f} "
            f"{result['mib_per_second']:>10.1f} "
            f"{result['gbit_per_second']:>9.3f} "
            f"{format_bytes(result['sender_rss_peak_delta_bytes']):>14} "
            f"{format_bytes(result['rss_peak_delta_bytes']):>15} "
            f"{format_bytes(result['disk_offload_bytes']):>14}"
        )


def run_sender(
    url: str,
    checkpoint: Path,
    modes: tuple[str, ...],
    repeat: int,
    timeout: float,
    connect_timeout: float,
    max_bytes: Optional[int],
    connection_security: str = ConnectionSecurity.CLEAR,
    credentials_dir: Optional[Path] = None,
    direct_negotiation_enabled: bool = True,
):
    secure, credentials = resolve_cell_security(TX_FQCN, url, connection_security, credentials_dir)
    register_tensor_decomposer()
    tensors = load_checkpoint(checkpoint, max_bytes=max_bytes)

    connected = threading.Event()
    cell = Cell(TX_FQCN, url, secure=secure, credentials=credentials)
    cell.set_cell_connected_cb(lambda agent: connected.set())
    cell.start()
    print(f"[send] connecting to {url}, connection_security={connection_security} ...")
    if not connected.wait(timeout=connect_timeout):
        cell.stop()
        raise RuntimeError(f"could not connect to receiver at {url} within {connect_timeout:g} seconds")

    results = []
    try:
        for repetition in range(1, repeat + 1):
            for mode in modes:
                results.append(
                    run_one_sender_mode(
                        cell,
                        url,
                        checkpoint,
                        tensors,
                        mode,
                        repetition,
                        timeout,
                        direct_negotiation_enabled=direct_negotiation_enabled,
                    )
                )
        print_summary(results)
    finally:
        cell.stop()


def main():
    parser = argparse.ArgumentParser(
        description="benchmark TensorDecomposer and Download Service with memory and disk offload"
    )
    parser.add_argument("--log-level", default="WARNING", help="Python log level for F3 internals")
    subparsers = parser.add_subparsers(dest="role", required=True)

    receiver = subparsers.add_parser("recv", help="run the receiver (start this first)")
    receiver.add_argument("--url", default="tcp://0.0.0.0:8002", help="listening URL")
    receiver.add_argument(
        "--offload-dir",
        type=Path,
        help="existing or creatable local directory for disk offload (default: system temporary directory)",
    )
    receiver.add_argument(
        "--sample-interval",
        type=float,
        default=DEFAULT_SAMPLE_INTERVAL,
        help=f"RSS sampling interval in seconds (default {DEFAULT_SAMPLE_INTERVAL})",
    )
    receiver.add_argument("--f3-config", help="optional native F3 comm_config.yml")
    add_cell_security_args(receiver)

    sender = subparsers.add_parser("send", help="transfer a PyTorch checkpoint to the receiver")
    sender.add_argument("--url", default="tcp://localhost:8002", help="receiver URL")
    sender.add_argument(
        "--checkpoint",
        type=Path,
        default=Path(DEFAULT_CHECKPOINT),
        help=f"PyTorch checkpoint (default {DEFAULT_CHECKPOINT})",
    )
    sender.add_argument(
        "--modes",
        type=parse_modes,
        default=MODES,
        help="comma-separated modes: memory,disk (default both)",
    )
    sender.add_argument("--repeat", type=int, default=1, help="number of repetitions per mode (default 1)")
    sender.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"F3 progress timeout in seconds (default {DEFAULT_TIMEOUT:g})",
    )
    sender.add_argument(
        "--connect-timeout",
        type=float,
        default=DEFAULT_CONNECT_TIMEOUT,
        help=f"connection timeout in seconds (default {DEFAULT_CONNECT_TIMEOUT:g})",
    )
    sender.add_argument(
        "--max-bytes",
        type=byte_size_arg,
        help="select the smallest tensors up to this binary size for a smoke test, e.g. 128M or 2G",
    )
    sender.add_argument(
        "--disable-direct",
        action="store_true",
        help="disable direct tensor negotiation for a legacy-path control run (receiver is configured automatically)",
    )
    sender.add_argument("--f3-config", help="optional native F3 comm_config.yml")
    add_cell_security_args(sender)

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.WARNING),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.role == "recv":
        if args.sample_interval <= 0:
            parser.error("--sample-interval must be greater than zero")
    else:
        if args.repeat <= 0:
            parser.error("--repeat must be greater than zero")
        if args.timeout <= 0:
            parser.error("--timeout must be greater than zero")
        if args.connect_timeout <= 0:
            parser.error("--connect-timeout must be greater than zero")

    if args.f3_config:
        try:
            config_path, _ = configure_f3(args.f3_config)
        except ValueError as ex:
            parser.error(str(ex))
        print(f"[config] loaded F3 settings from {config_path}")
    print(f"[config] {f3_config_summary()}")

    try:
        role = RX_FQCN if args.role == "recv" else TX_FQCN
        resolve_cell_security(role, args.url, args.connection_security, args.credentials_dir)
    except ValueError as ex:
        parser.error(str(ex))

    if args.role == "recv":
        run_receiver(
            args.url,
            args.offload_dir,
            args.sample_interval,
            args.connection_security,
            args.credentials_dir,
        )
    else:
        run_sender(
            url=args.url,
            checkpoint=args.checkpoint.expanduser().resolve(),
            modes=args.modes,
            repeat=args.repeat,
            timeout=args.timeout,
            connect_timeout=args.connect_timeout,
            max_bytes=args.max_bytes,
            connection_security=args.connection_security,
            credentials_dir=args.credentials_dir,
            direct_negotiation_enabled=not args.disable_direct,
        )


if __name__ == "__main__":
    main()
