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
"""Measure gRPC stream and physical-channel scaling on one listener.

This is a transport diagnostic, not an F3 data path.  It deliberately uses
the same synchronous ``streamer.Streamer/Stream`` RPC and ``Frame`` protobuf
as the F3 gRPC driver, while varying only the RPC/channel layout:

* ``--channels 1 --rpcs-per-channel 1``: current driver topology.
* ``--channels 1 --rpcs-per-channel 2``: two RPCs on one HTTP/2 connection.
* ``--channels 2 --rpcs-per-channel 1``: two physical connections.
* ``--channels 4 --rpcs-per-channel 1``: four physical connections.

All channel layouts use the same listener URL, port, and TLS credentials.
Aggregate payload, warm-up, and flow-control window stay fixed, while every
lane keeps the same ACK threshold so aggregate ACK count remains comparable.
Both RPC directions are measured; server-to-client matches model download.
The receiver returns ``context.peer()`` for every RPC, and a run fails unless
observed peer-socket cardinality matches the requested topology.
"""

import argparse
import json
import logging
import queue
import struct
import threading
import time
import uuid
from concurrent import futures
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import grpc
import psutil
import yaml

from nvflare.apis.fl_constant import ConnectionSecurity
from nvflare.fuel.f3.comm_config import CommConfigurator
from nvflare.fuel.f3.drivers.driver_params import DriverParams
from nvflare.fuel.f3.drivers.grpc.streamer_pb2 import Frame
from nvflare.fuel.f3.drivers.grpc.streamer_pb2_grpc import (
    StreamerServicer,
    StreamerStub,
    add_StreamerServicer_to_server,
)
from nvflare.fuel.f3.drivers.grpc.utils import get_grpc_client_credentials, get_grpc_server_credentials
from nvflare.fuel.f3.drivers.grpc_driver import GRPC_DEFAULT_OPTIONS
from nvflare.fuel.f3.drivers.net_utils import get_address, parse_url

try:
    from .cellnet_bench import GB, MB, add_cell_security_args, configure_f3, f3_config_summary, resolve_cell_security
except ImportError:
    from cellnet_bench import GB, MB, add_cell_security_args, configure_f3, f3_config_summary, resolve_cell_security


RX_FQCN = "server"
TX_FQCN = "sender"

MAGIC = b"NVGLN002"
ACK_MAGIC = b"NVGLNA01"
HEADER = struct.Struct("!8s16sIIIIIIIIQQQQQ")
ACK_HEADER = struct.Struct("!8sBQQH")

ACK_READY = 1
ACK_WARM_PROGRESS = 2
ACK_WARM_DONE = 3
ACK_MEASURE_PROGRESS = 4
ACK_DONE = 5
ACK_ERROR = 6
ACK_MEASURE_START = 7

DIRECTION_CLIENT_TO_SERVER = 1
DIRECTION_SERVER_TO_CLIENT = 2
DIRECTION_NAMES = {
    DIRECTION_CLIENT_TO_SERVER: "client-to-server",
    DIRECTION_SERVER_TO_CLIENT: "server-to-client",
}
DIRECTION_CODES = {name: code for code, name in DIRECTION_NAMES.items()}

DEFAULT_CHUNK_SIZE = 2 * MB
DEFAULT_WINDOW_SIZE = 64 * MB
DEFAULT_ACK_INTERVAL = 16 * MB
DEFAULT_SIZE = 8 * GB
DEFAULT_WARMUP_SIZE = GB
DEFAULT_TIMEOUT = 300.0
LOCAL_SUBCHANNEL_POOL_OPTION = "grpc.use_local_subchannel_pool"
MAX_CHANNELS = 4
MAX_RPCS_PER_CHANNEL = 4
MAX_LANES = 16
MAX_ACK_TEXT = 4096
MAX_LANE_BYTES = 1024 * GB
MAX_CHUNK_SIZE = 64 * MB
MAX_ACK_INTERVAL = GB
MAX_WINDOW_SIZE = 4 * GB
MAX_ACTIVE_RUNS = 64
MAX_SERVER_RPC_SECONDS = 600
MAX_GRPC_FRAME_BYTES = MAX_CHUNK_SIZE + MB
INCOMPLETE_RUN_TTL = 30.0


def _partition(total: int, count: int) -> list[int]:
    """Partition an integer exactly, assigning at most one extra byte per lane."""
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError(f"total must be a non-negative integer, got {total!r}")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError(f"count must be a positive integer, got {count!r}")
    quotient, remainder = divmod(total, count)
    return [quotient + (1 if index < remainder else 0) for index in range(count)]


def _grpc_settings() -> tuple[int, list[tuple]]:
    config = CommConfigurator().get_config() or {}
    grpc_config = config.get("grpc") or {}
    if not isinstance(grpc_config, dict):
        raise ValueError(f"grpc configuration must be a mapping, got {type(grpc_config).__name__}")
    max_workers = grpc_config.get("max_workers", 100)
    if isinstance(max_workers, bool) or not isinstance(max_workers, int) or max_workers <= 0:
        raise ValueError(f"grpc.max_workers must be a positive integer, got {max_workers!r}")
    configured_options = grpc_config.get("options")
    if configured_options is None:
        options = list(GRPC_DEFAULT_OPTIONS)
    else:
        if not isinstance(configured_options, list):
            raise ValueError("grpc.options must be a list of [name, value] entries")
        options = []
        for entry in configured_options:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2 or not isinstance(entry[0], str):
                raise ValueError(f"invalid grpc option {entry!r}; expected [name, value]")
            options.append((entry[0], entry[1]))
    return max_workers, options


def _client_channel_options(options: list[tuple], channel_count: int) -> list[tuple]:
    result = [entry for entry in options if entry[0] != LOCAL_SUBCHANNEL_POOL_OPTION]
    if channel_count > 1:
        # Multiple Python Channel objects otherwise share a C-core subchannel
        # and silently collapse to one TCP connection.
        result.append((LOCAL_SUBCHANNEL_POOL_OPTION, 1))
    return result


def _validate_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"grpc", "grpcs"}:
        raise ValueError(f"gRPC lane benchmark requires a grpc:// or grpcs:// URL, got {url!r}")
    if not parsed.hostname:
        raise ValueError(f"gRPC URL is missing a host: {url!r}")
    try:
        if parsed.port is None:
            raise ValueError(f"gRPC URL is missing a port: {url!r}")
    except ValueError as ex:
        raise ValueError(f"invalid gRPC URL {url!r}") from ex
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError(f"gRPC URL must contain only a host and port, got {url!r}")


def _connection_params(url: str, credentials: dict, secure: bool) -> dict:
    _validate_url(url)
    params = parse_url(url)
    params.update(credentials)
    params[DriverParams.SECURE.value] = secure
    return params


@dataclass(frozen=True)
class LaneSpec:
    run_token: bytes
    lane_index: int
    channel_index: int
    rpc_index: int
    channel_count: int
    rpcs_per_channel: int
    lane_count: int
    direction: int
    pattern: int
    warmup_bytes: int
    measured_bytes: int
    chunk_size: int
    ack_interval: int
    window_size: int

    def encode(self) -> bytes:
        self.validate()
        if len(self.run_token) != 16:
            raise ValueError("run token must contain exactly 16 bytes")
        return HEADER.pack(
            MAGIC,
            self.run_token,
            self.lane_index,
            self.channel_index,
            self.rpc_index,
            self.channel_count,
            self.rpcs_per_channel,
            self.lane_count,
            self.direction,
            self.pattern,
            self.warmup_bytes,
            self.measured_bytes,
            self.chunk_size,
            self.ack_interval,
            self.window_size,
        )

    @classmethod
    def decode(cls, data: bytes) -> "LaneSpec":
        if len(data) != HEADER.size:
            raise ValueError(f"lane header has {len(data)} bytes, expected {HEADER.size}")
        values = HEADER.unpack(data)
        if values[0] != MAGIC:
            raise ValueError("invalid lane header magic")
        spec = cls(*values[1:])
        spec.validate()
        return spec

    def validate(self):
        if not 1 <= self.channel_count <= MAX_CHANNELS:
            raise ValueError(f"channel_count must be in [1, {MAX_CHANNELS}]")
        if not 1 <= self.rpcs_per_channel <= MAX_RPCS_PER_CHANNEL:
            raise ValueError(f"rpcs_per_channel must be in [1, {MAX_RPCS_PER_CHANNEL}]")
        if self.lane_count != self.channel_count * self.rpcs_per_channel or self.lane_count > MAX_LANES:
            raise ValueError("lane_count does not match the channel/RPC topology")
        if not 0 <= self.lane_index < self.lane_count:
            raise ValueError("lane_index is outside the configured topology")
        if not 0 <= self.channel_index < self.channel_count:
            raise ValueError("channel_index is outside the configured topology")
        if not 0 <= self.rpc_index < self.rpcs_per_channel:
            raise ValueError("rpc_index is outside the configured topology")
        if self.lane_index != self.channel_index * self.rpcs_per_channel + self.rpc_index:
            raise ValueError("lane_index does not match channel_index/rpc_index")
        if self.direction not in DIRECTION_NAMES:
            raise ValueError("invalid transfer direction")
        if not 0 <= self.pattern <= 255:
            raise ValueError("pattern must fit in one byte")
        if self.warmup_bytes < 0 or self.measured_bytes <= 0:
            raise ValueError("lane byte counts must be non-negative and measured_bytes must be positive")
        if self.warmup_bytes > MAX_LANE_BYTES or self.measured_bytes > MAX_LANE_BYTES:
            raise ValueError(f"lane byte counts must not exceed {MAX_LANE_BYTES:,}")
        if self.chunk_size <= 0 or self.ack_interval <= 0:
            raise ValueError("chunk_size and ack_interval must be positive")
        if self.chunk_size > MAX_CHUNK_SIZE:
            raise ValueError(f"chunk_size must not exceed {MAX_CHUNK_SIZE:,}")
        if self.ack_interval > MAX_ACK_INTERVAL:
            raise ValueError(f"ack_interval must not exceed {MAX_ACK_INTERVAL:,}")
        if self.window_size <= 0 or self.window_size > MAX_WINDOW_SIZE:
            raise ValueError(f"window_size must be in [1, {MAX_WINDOW_SIZE:,}]")
        rounded_ack = ((self.ack_interval + self.chunk_size - 1) // self.chunk_size) * self.chunk_size
        if self.window_size < self.chunk_size or rounded_ack > self.window_size:
            raise ValueError("window_size cannot reach the chunk-rounded ACK threshold")


@dataclass(frozen=True)
class Ack:
    kind: int
    cumulative_bytes: int = 0
    elapsed_ns: int = 0
    text: str = ""

    def encode(self) -> bytes:
        encoded_text = self.text.encode("utf-8")
        if len(encoded_text) > MAX_ACK_TEXT:
            raise ValueError("ACK text is too large")
        return (
            ACK_HEADER.pack(ACK_MAGIC, self.kind, self.cumulative_bytes, self.elapsed_ns, len(encoded_text))
            + encoded_text
        )

    @classmethod
    def decode(cls, data: bytes) -> "Ack":
        if len(data) < ACK_HEADER.size:
            raise ValueError("truncated ACK")
        magic, kind, cumulative_bytes, elapsed_ns, text_size = ACK_HEADER.unpack(data[: ACK_HEADER.size])
        if magic != ACK_MAGIC:
            raise ValueError("invalid ACK magic")
        if text_size > MAX_ACK_TEXT or len(data) != ACK_HEADER.size + text_size:
            raise ValueError("invalid ACK text length")
        try:
            text = data[ACK_HEADER.size :].decode("utf-8")
        except UnicodeDecodeError as ex:
            raise ValueError("ACK text is not UTF-8") from ex
        return cls(kind=kind, cumulative_bytes=cumulative_bytes, elapsed_ns=elapsed_ns, text=text)


def _control_frame(ack: Ack) -> Frame:
    return Frame(seq=-ack.kind, data=ack.encode())


def _decode_control(frame: Frame) -> Ack:
    ack = Ack.decode(frame.data)
    if frame.seq != -ack.kind:
        raise ValueError("control frame sequence does not match control kind")
    return ack


class OutstandingTracker:
    def __init__(self):
        self.current = 0
        self.peak = 0
        self.lock = threading.Lock()

    def add(self, amount: int):
        with self.lock:
            self.current += amount
            self.peak = max(self.peak, self.current)

    def release(self, amount: int):
        with self.lock:
            self.current -= amount
            if self.current < 0:
                raise RuntimeError("flow-control accounting became negative")


class ProcessSampler:
    def __init__(self, interval: float = 0.05):
        self.process = psutil.Process()
        self.interval = interval
        self.baseline = self.process.memory_info().rss
        self.peak = self.baseline
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._sample, name="grpc_lane_rss", daemon=True)

    def _sample(self):
        while not self.stop_event.wait(self.interval):
            self.observe()

    def observe(self) -> int:
        current = self.process.memory_info().rss
        with self.lock:
            self.peak = max(self.peak, current)
        return current

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)
        self.observe()


class RunRegistry:
    """Receiver-side evidence that all RPCs reached the expected peer sockets."""

    @dataclass
    class Record:
        channel_count: int
        rpcs_per_channel: int
        lane_count: int
        direction: int
        peers: dict[int, str] = field(default_factory=dict)
        completed: dict[int, tuple[int, int]] = field(default_factory=dict)
        active: set[int] = field(default_factory=set)
        outstanding: OutstandingTracker = field(default_factory=OutstandingTracker)
        sampler: Optional[ProcessSampler] = None
        cpu_started: float = 0.0
        expires_at: float = 0.0

    def __init__(self):
        self.lock = threading.Lock()
        self.records: dict[bytes, RunRegistry.Record] = {}
        self.stop_event = threading.Event()
        self.reaper = threading.Thread(target=self._reap, name="grpc_lane_reaper", daemon=True)
        self.reaper.start()

    def _reap(self):
        while not self.stop_event.wait(1.0):
            self.reap_expired()

    def reap_expired(self):
        expired = []
        now = time.monotonic()
        with self.lock:
            for run_token, record in list(self.records.items()):
                if record.expires_at <= now:
                    expired.append(self.records.pop(run_token))
        for record in expired:
            if record.sampler is not None:
                record.sampler.stop()

    def register(self, spec: LaneSpec, peer: str, ttl: float):
        with self.lock:
            record = self.records.get(spec.run_token)
            if record is None:
                if len(self.records) >= MAX_ACTIVE_RUNS:
                    raise ValueError(f"receiver already has {MAX_ACTIVE_RUNS} active benchmark runs")
                record = self.Record(spec.channel_count, spec.rpcs_per_channel, spec.lane_count, spec.direction)
                record.expires_at = time.monotonic() + min(ttl, INCOMPLETE_RUN_TTL)
                self.records[spec.run_token] = record
            topology = (record.channel_count, record.rpcs_per_channel, record.lane_count, record.direction)
            if topology != (spec.channel_count, spec.rpcs_per_channel, spec.lane_count, spec.direction):
                raise ValueError("RPCs with one run token declared different topologies")
            if spec.lane_index in record.peers:
                raise ValueError(f"duplicate lane_index {spec.lane_index}")
            record.peers[spec.lane_index] = peer
            record.active.add(spec.lane_index)
            if len(record.peers) == record.lane_count:
                record.sampler = ProcessSampler()
                record.sampler.start()
                record.cpu_started = time.process_time()
                record.expires_at = time.monotonic() + ttl
            return record

    def complete(self, spec: LaneSpec, measured_bytes: int, elapsed_ns: int):
        result = None
        incomplete = None
        with self.lock:
            record = self.records.get(spec.run_token)
            if record is None:
                return
            if len(record.peers) != record.lane_count:
                incomplete = self.records.pop(spec.run_token)
            else:
                record.completed[spec.lane_index] = (measured_bytes, elapsed_ns)
                record.active.discard(spec.lane_index)
                if len(record.completed) == record.lane_count:
                    result = record
                    del self.records[spec.run_token]
        if incomplete is not None:
            if incomplete.sampler is not None:
                incomplete.sampler.stop()
            raise ValueError("lane completed before the declared topology registered")
        if result is not None:
            result.sampler.stop()
            cpu_seconds = time.process_time() - result.cpu_started
            total_bytes = sum(value[0] for value in result.completed.values())
            elapsed = max(value[1] for value in result.completed.values()) / 1_000_000_000
            peers = [result.peers[index] for index in sorted(result.peers)]
            print(
                f"[recv] RESULT run={spec.run_token.hex()} channels={result.channel_count} "
                f"rpcs_per_channel={result.rpcs_per_channel} logical_rpcs={result.lane_count} "
                f"direction={DIRECTION_NAMES[result.direction]} "
                f"data_sender={'server' if result.direction == DIRECTION_SERVER_TO_CLIENT else 'client'} "
                f"unique_peer_sockets={len(set(peers))} bytes={total_bytes} "
                f"max_lane_seconds={elapsed:.6f} cpu_run_seconds={cpu_seconds:.6f} "
                f"rss_baseline_bytes={result.sampler.baseline} rss_peak_bytes={result.sampler.peak} "
                f"rss_delta_bytes={result.sampler.peak - result.sampler.baseline} "
                f"server_send_peak_outstanding_bytes={result.outstanding.peak} peers={peers}",
                flush=True,
            )

    def abort(self, run_token: bytes):
        with self.lock:
            record = self.records.pop(run_token, None)
        if record is not None and record.sampler is not None:
            record.sampler.stop()

    def stop(self):
        self.stop_event.set()
        self.reaper.join(timeout=5)
        with self.lock:
            records = list(self.records.values())
            self.records.clear()
        for record in records:
            if record.sampler is not None:
                record.sampler.stop()


class ServerToClientState:
    """Server-side sender state for one response-stream lane."""

    def __init__(self, request_iterator, context, spec: LaneSpec, record: RunRegistry.Record):
        self.request_iterator = request_iterator
        self.context = context
        self.spec = spec
        self.record = record
        self.payload_block = bytes([spec.pattern]) * spec.chunk_size
        self.condition = threading.Condition()
        self.error: Optional[BaseException] = None
        self.sent = {"warm": 0, "measure": 0}
        self.acked = {"warm": 0, "measure": 0}
        self.warm_done = threading.Event()
        self.measure_start = threading.Event()
        self.measure_done = threading.Event()
        self.reader = threading.Thread(
            target=self._read_controls,
            name=f"grpc_lane_control_{spec.lane_index}",
            daemon=True,
        )

    def fail(self, error: BaseException):
        with self.condition:
            if self.error is None:
                self.error = error
            self.condition.notify_all()
        self.warm_done.set()
        self.measure_start.set()
        self.measure_done.set()

    def _check_error(self):
        if self.error is not None:
            raise self.error
        if not self.context.is_active():
            raise RuntimeError(f"lane {self.spec.lane_index} RPC is no longer active")

    def _wait(self, event: threading.Event, name: str):
        remaining = self.context.time_remaining()
        budget = MAX_SERVER_RPC_SECONDS if remaining is None else min(remaining, MAX_SERVER_RPC_SECONDS)
        deadline = time.monotonic() + budget
        while not event.wait(0.25):
            self._check_error()
            if time.monotonic() >= deadline:
                raise TimeoutError(f"lane {self.spec.lane_index} timed out waiting for {name}")
        self._check_error()

    def _record_ack(self, phase: str, cumulative_bytes: int):
        with self.condition:
            if cumulative_bytes < self.acked[phase] or cumulative_bytes > self.sent[phase]:
                raise ValueError(f"invalid {phase} ACK {cumulative_bytes}")
            delta = cumulative_bytes - self.acked[phase]
            self.acked[phase] = cumulative_bytes
            self.record.outstanding.release(delta)
            self.condition.notify_all()

    def _read_controls(self):
        try:
            for frame in self.request_iterator:
                ack = _decode_control(frame)
                if ack.kind == ACK_WARM_PROGRESS:
                    if self.warm_done.is_set():
                        raise ValueError("warm-up progress arrived after WARM_DONE")
                    self._record_ack("warm", ack.cumulative_bytes)
                elif ack.kind == ACK_WARM_DONE:
                    self._record_ack("warm", ack.cumulative_bytes)
                    if ack.cumulative_bytes != self.spec.warmup_bytes:
                        raise ValueError("WARM_DONE did not acknowledge the exact warm-up size")
                    self.warm_done.set()
                elif ack.kind == ACK_MEASURE_START:
                    if not self.warm_done.is_set() or ack.cumulative_bytes != 0:
                        raise ValueError("MEASURE_START arrived before exact WARM_DONE")
                    self.measure_start.set()
                elif ack.kind == ACK_MEASURE_PROGRESS:
                    if not self.measure_start.is_set() or self.measure_done.is_set():
                        raise ValueError("measurement progress arrived outside the measurement phase")
                    self._record_ack("measure", ack.cumulative_bytes)
                elif ack.kind == ACK_DONE:
                    if not self.measure_start.is_set():
                        raise ValueError("DONE arrived before MEASURE_START")
                    self._record_ack("measure", ack.cumulative_bytes)
                    if ack.cumulative_bytes != self.spec.measured_bytes:
                        raise ValueError("DONE did not acknowledge the exact measured size")
                    self.measure_done.set()
                    return
                elif ack.kind == ACK_ERROR:
                    raise RuntimeError(f"client rejected lane {self.spec.lane_index}: {ack.text}")
                else:
                    raise ValueError(f"unexpected client control kind {ack.kind}")
            if not self.measure_done.is_set():
                raise RuntimeError(f"lane {self.spec.lane_index} request stream ended before DONE")
        except BaseException as ex:
            self.fail(ex)

    def _data_frames(self, phase: str, byte_count: int, start_seq: int):
        sent = 0
        seq = start_seq
        while sent < byte_count:
            size = min(self.spec.chunk_size, byte_count - sent)
            with self.condition:
                while self.sent[phase] - self.acked[phase] + size > self.spec.window_size and self.error is None:
                    remaining = self.context.time_remaining()
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError(f"lane {self.spec.lane_index} flow-control timeout")
                    self.condition.wait(min(remaining, 1.0) if remaining is not None else 1.0)
                self._check_error()
                self.sent[phase] += size
                self.record.outstanding.add(size)
            yield Frame(seq=seq, data=self.payload_block[:size])
            sent += size
            seq += 1
        return seq

    def responses(self, ready: str):
        self.reader.start()
        yield _control_frame(Ack(ACK_READY, text=ready))
        next_seq = yield from self._data_frames("warm", self.spec.warmup_bytes, 1)
        self._wait(self.warm_done, "warm-up acknowledgement")
        self._wait(self.measure_start, "measurement start")
        measured_started = time.perf_counter_ns()
        yield from self._data_frames("measure", self.spec.measured_bytes, next_seq)
        self._wait(self.measure_done, "measurement acknowledgement")
        elapsed_ns = time.perf_counter_ns() - measured_started
        self.reader.join(timeout=5)
        if self.reader.is_alive():
            raise RuntimeError(f"lane {self.spec.lane_index} control reader did not stop")
        details = json.dumps(
            {"peak_outstanding_bytes": self.record.outstanding.peak},
            separators=(",", ":"),
        )
        return elapsed_ns, _control_frame(
            Ack(ACK_DONE, cumulative_bytes=self.spec.measured_bytes, elapsed_ns=elapsed_ns, text=details)
        )


class LaneBenchServicer(StreamerServicer):
    def __init__(self):
        self.registry = RunRegistry()

    @staticmethod
    def _data_frames(request_iterator, spec: LaneSpec, byte_count: int, start_seq: int):
        received = 0
        expected_seq = start_seq
        last_ack = 0
        while received < byte_count:
            try:
                frame = next(request_iterator)
            except StopIteration as ex:
                raise ValueError(f"lane ended after {received} of {byte_count} bytes") from ex
            if frame.seq != expected_seq:
                raise ValueError(f"lane frame sequence {frame.seq}, expected {expected_seq}")
            size = len(frame.data)
            if size <= 0 or size > spec.chunk_size or size > byte_count - received:
                raise ValueError(f"invalid lane payload size {size}")
            if frame.data[0] != spec.pattern or frame.data[-1] != spec.pattern:
                raise ValueError("lane payload pattern mismatch")
            received += size
            expected_seq += 1
            if received - last_ack >= spec.ack_interval:
                last_ack = received
                yield received, expected_seq
        return received, expected_seq

    def _client_to_server(self, request_iterator, spec: LaneSpec, ready: str):
        yield _control_frame(Ack(ACK_READY, text=ready))
        warm_received = 0
        next_seq = 1
        warm_frames = self._data_frames(request_iterator, spec, spec.warmup_bytes, next_seq)
        try:
            while True:
                warm_received, next_seq = next(warm_frames)
                yield _control_frame(Ack(ACK_WARM_PROGRESS, cumulative_bytes=warm_received))
        except StopIteration as done:
            if done.value is not None:
                warm_received, next_seq = done.value
        yield _control_frame(Ack(ACK_WARM_DONE, cumulative_bytes=warm_received))

        measured_received = 0
        measured_started = None
        measured_frames = self._data_frames(request_iterator, spec, spec.measured_bytes, next_seq)
        try:
            while True:
                if measured_started is None:
                    measured_started = time.perf_counter_ns()
                measured_received, next_seq = next(measured_frames)
                yield _control_frame(Ack(ACK_MEASURE_PROGRESS, cumulative_bytes=measured_received))
        except StopIteration as done:
            if measured_started is None:
                measured_started = time.perf_counter_ns()
            if done.value is not None:
                measured_received, next_seq = done.value

        elapsed_ns = time.perf_counter_ns() - measured_started
        if measured_received != spec.measured_bytes:
            raise ValueError(f"received {measured_received}, expected {spec.measured_bytes} measured bytes")
        return (
            measured_received,
            elapsed_ns,
            _control_frame(Ack(ACK_DONE, cumulative_bytes=measured_received, elapsed_ns=elapsed_ns)),
        )

    def Stream(self, request_iterator, context):
        run_token = None
        completed = False
        try:
            remaining = context.time_remaining()
            if remaining is None or remaining > MAX_SERVER_RPC_SECONDS:
                raise ValueError(f"RPC deadline must be set and no greater than {MAX_SERVER_RPC_SECONDS} seconds")
            first = next(request_iterator)
            if first.seq != 0:
                raise ValueError("first lane frame must have sequence zero")
            spec = LaneSpec.decode(first.data)
            run_token = spec.run_token
            peer = context.peer()
            record = self.registry.register(spec, peer, ttl=max(1.0, remaining + 1.0))
            auth_context = context.auth_context()
            transport_values = auth_context.get("transport_security_type", ())
            transport = transport_values[0].decode("utf-8") if transport_values else "insecure"
            ready = json.dumps({"peer": peer, "transport": transport}, separators=(",", ":"))
            if spec.direction == DIRECTION_CLIENT_TO_SERVER:
                measured_received, elapsed_ns, final_frame = yield from self._client_to_server(
                    request_iterator, spec, ready
                )
            else:
                lane = ServerToClientState(request_iterator, context, spec, record)
                elapsed_ns, final_frame = yield from lane.responses(ready)
                measured_received = spec.measured_bytes
            self.registry.complete(spec, measured_received, elapsed_ns)
            completed = True
            yield final_frame
        except Exception as ex:
            logging.getLogger(__name__).exception("gRPC lane failed")
            try:
                yield _control_frame(Ack(ACK_ERROR, text=str(ex)))
            except Exception:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(ex))
        finally:
            if run_token is not None and not completed:
                self.registry.abort(run_token)


class LaneClient:
    def __init__(
        self,
        stub: StreamerStub,
        spec: LaneSpec,
        lane_window: int,
        payload_block: bytes,
        measure_event: threading.Event,
        outstanding: OutstandingTracker,
        timeout: float,
    ):
        self.stub = stub
        self.spec = spec
        self.lane_window = lane_window
        self.payload_block = payload_block
        self.measure_event = measure_event
        self.outstanding = outstanding
        self.timeout = timeout
        self.ready = threading.Event()
        self.warm_done = threading.Event()
        self.done = threading.Event()
        self.condition = threading.Condition()
        self.error: Optional[BaseException] = None
        self.peer = None
        self.server_elapsed_ns = 0
        self.transport_security = None
        self.sent = {"warm": 0, "measure": 0}
        self.acked = {"warm": 0, "measure": 0}
        self.call = None
        self.response_thread = None

    def fail(self, error: BaseException):
        with self.condition:
            if self.error is None:
                self.error = error
            self.condition.notify_all()
        self.ready.set()
        self.warm_done.set()
        self.done.set()
        self.measure_event.set()

    def _wait(self, event: threading.Event, name: str):
        if not event.wait(self.timeout):
            raise TimeoutError(f"lane {self.spec.lane_index} timed out waiting for {name}")
        if self.error is not None:
            raise self.error

    def _payload_frames(self, phase: str, byte_count: int, start_seq: int):
        sent = 0
        seq = start_seq
        while sent < byte_count:
            size = min(self.spec.chunk_size, byte_count - sent)
            deadline = time.monotonic() + self.timeout
            with self.condition:
                while self.sent[phase] - self.acked[phase] + size > self.lane_window and self.error is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"lane {self.spec.lane_index} flow-control timeout")
                    self.condition.wait(remaining)
                if self.error is not None:
                    raise self.error
                self.sent[phase] += size
                self.outstanding.add(size)
            yield Frame(seq=seq, data=self.payload_block[:size])
            sent += size
            seq += 1
        return seq

    def requests(self):
        try:
            yield Frame(seq=0, data=self.spec.encode())
            self._wait(self.ready, "receiver readiness")
            warm_frames = self._payload_frames("warm", self.spec.warmup_bytes, 1)
            try:
                while True:
                    yield next(warm_frames)
            except StopIteration as done:
                next_seq = done.value
            self._wait(self.warm_done, "warm-up completion")
            self._wait(self.measure_event, "shared measurement start")
            measured_frames = self._payload_frames("measure", self.spec.measured_bytes, next_seq)
            try:
                while True:
                    yield next(measured_frames)
            except StopIteration:
                return
        except Exception as ex:
            self.fail(ex)
            raise

    def _record_ack(self, phase: str, cumulative_bytes: int):
        with self.condition:
            if cumulative_bytes < self.acked[phase] or cumulative_bytes > self.sent[phase]:
                raise ValueError(f"invalid {phase} ACK {cumulative_bytes}")
            delta = cumulative_bytes - self.acked[phase]
            self.acked[phase] = cumulative_bytes
            self.outstanding.release(delta)
            self.condition.notify_all()

    def responses(self):
        try:
            for response in self.call:
                ack = _decode_control(response)
                if ack.kind == ACK_READY:
                    ready = json.loads(ack.text)
                    self.peer = ready["peer"]
                    self.transport_security = ready["transport"]
                    self.ready.set()
                elif ack.kind == ACK_WARM_PROGRESS:
                    self._record_ack("warm", ack.cumulative_bytes)
                elif ack.kind == ACK_WARM_DONE:
                    self._record_ack("warm", ack.cumulative_bytes)
                    self.warm_done.set()
                elif ack.kind == ACK_MEASURE_PROGRESS:
                    self._record_ack("measure", ack.cumulative_bytes)
                elif ack.kind == ACK_DONE:
                    self._record_ack("measure", ack.cumulative_bytes)
                    self.server_elapsed_ns = ack.elapsed_ns
                    self.done.set()
                elif ack.kind == ACK_ERROR:
                    raise RuntimeError(f"receiver rejected lane {self.spec.lane_index}: {ack.text}")
                else:
                    raise ValueError(f"unknown ACK kind {ack.kind}")
            if not self.done.is_set() and self.error is None:
                raise RuntimeError(f"lane {self.spec.lane_index} RPC ended before DONE")
        except BaseException as ex:
            self.fail(ex)

    def start(self):
        self.call = self.stub.Stream(self.requests(), timeout=self.timeout)
        self.response_thread = threading.Thread(
            target=self.responses,
            name=f"grpc_lane_response_{self.spec.lane_index}",
            daemon=True,
        )
        self.response_thread.start()

    def cancel(self):
        self.measure_event.set()
        if self.call is not None:
            self.call.cancel()
        self.fail(RuntimeError(f"lane {self.spec.lane_index} cancelled"))


_QUEUE_EOF = object()


class ServerToClientLaneClient:
    """Client-side receiver state for one response-stream lane."""

    def __init__(
        self,
        stub: StreamerStub,
        spec: LaneSpec,
        measure_event: threading.Event,
        outstanding: OutstandingTracker,
        timeout: float,
    ):
        self.stub = stub
        self.spec = spec
        self.measure_event = measure_event
        self.outstanding = outstanding
        self.timeout = timeout
        self.controls: queue.Queue = queue.Queue()
        self.ready = threading.Event()
        self.warm_done = threading.Event()
        self.done = threading.Event()
        self.error: Optional[BaseException] = None
        self.peer = None
        self.server_elapsed_ns = 0
        self.server_peak_outstanding = 0
        self.transport_security = None
        self.call = None
        self.response_thread = None

    def fail(self, error: BaseException):
        if self.error is None:
            self.error = error
        self.ready.set()
        self.warm_done.set()
        self.done.set()
        self.measure_event.set()
        self.controls.put(_QUEUE_EOF)

    def _wait(self, event: threading.Event, name: str):
        if not event.wait(self.timeout):
            raise TimeoutError(f"lane {self.spec.lane_index} timed out waiting for {name}")
        if self.error is not None:
            raise self.error

    def _queue_control(self, ack: Ack, eof: bool = False):
        self.controls.put(_control_frame(ack))
        if eof:
            self.controls.put(_QUEUE_EOF)

    def requests(self):
        try:
            yield Frame(seq=0, data=self.spec.encode())
            while True:
                control = self.controls.get(timeout=self.timeout)
                if control is _QUEUE_EOF:
                    return
                yield control
        except queue.Empty as ex:
            error = TimeoutError(f"lane {self.spec.lane_index} timed out waiting for outbound control")
            self.fail(error)
            raise error from ex
        except Exception as ex:
            self.fail(ex)
            raise

    def _ack_received(self, phase: str, cumulative_bytes: int, kind: int, eof: bool = False):
        previous = getattr(self, f"_{phase}_acked", 0)
        delta = cumulative_bytes - previous
        if delta < 0:
            raise ValueError(f"{phase} receive accounting moved backwards")
        setattr(self, f"_{phase}_acked", cumulative_bytes)
        self.outstanding.release(delta)
        self._queue_control(Ack(kind, cumulative_bytes=cumulative_bytes), eof=eof)

    def responses(self):
        phase = "ready"
        received = {"warm": 0, "measure": 0}
        last_ack = {"warm": 0, "measure": 0}
        expected_seq = 1
        self._warm_acked = 0
        self._measure_acked = 0
        try:
            for response in self.call:
                if response.seq < 0:
                    ack = _decode_control(response)
                    if ack.kind == ACK_READY:
                        if phase != "ready":
                            raise ValueError("duplicate or late READY")
                        ready = json.loads(ack.text)
                        self.peer = ready["peer"]
                        self.transport_security = ready["transport"]
                        phase = "warm"
                        self.ready.set()
                        if self.spec.warmup_bytes == 0:
                            self._queue_control(Ack(ACK_WARM_DONE, cumulative_bytes=0))
                            self.warm_done.set()
                            self._wait(self.measure_event, "shared measurement start")
                            phase = "measure"
                            self._queue_control(Ack(ACK_MEASURE_START))
                    elif ack.kind == ACK_DONE:
                        if phase != "measure_done" or ack.cumulative_bytes != self.spec.measured_bytes:
                            raise ValueError("server DONE arrived before exact measured data")
                        details = json.loads(ack.text) if ack.text else {}
                        self.server_peak_outstanding = int(details.get("peak_outstanding_bytes", 0))
                        self.server_elapsed_ns = ack.elapsed_ns
                        self.done.set()
                    elif ack.kind == ACK_ERROR:
                        raise RuntimeError(f"receiver rejected lane {self.spec.lane_index}: {ack.text}")
                    else:
                        raise ValueError(f"unexpected server control kind {ack.kind}")
                    continue

                if phase not in {"warm", "measure"}:
                    raise ValueError(f"data arrived during {phase} phase")
                if response.seq != expected_seq:
                    raise ValueError(f"lane frame sequence {response.seq}, expected {expected_seq}")
                expected_seq += 1
                size = len(response.data)
                target = self.spec.warmup_bytes if phase == "warm" else self.spec.measured_bytes
                if size <= 0 or size > self.spec.chunk_size or size > target - received[phase]:
                    raise ValueError(f"invalid lane payload size {size}")
                if response.data[0] != self.spec.pattern or response.data[-1] != self.spec.pattern:
                    raise ValueError("lane payload pattern mismatch")
                received[phase] += size
                self.outstanding.add(size)
                if received[phase] == target:
                    kind = ACK_WARM_DONE if phase == "warm" else ACK_DONE
                    self._ack_received(phase, received[phase], kind, eof=phase == "measure")
                    last_ack[phase] = received[phase]
                    if phase == "warm":
                        self.warm_done.set()
                        self._wait(self.measure_event, "shared measurement start")
                        phase = "measure"
                        self._queue_control(Ack(ACK_MEASURE_START))
                    else:
                        phase = "measure_done"
                elif received[phase] - last_ack[phase] >= self.spec.ack_interval:
                    kind = ACK_WARM_PROGRESS if phase == "warm" else ACK_MEASURE_PROGRESS
                    self._ack_received(phase, received[phase], kind)
                    last_ack[phase] = received[phase]
            if not self.done.is_set() and self.error is None:
                raise RuntimeError(f"lane {self.spec.lane_index} RPC ended before DONE")
        except BaseException as ex:
            self.fail(ex)

    def start(self):
        self.call = self.stub.Stream(self.requests(), timeout=self.timeout)
        self.response_thread = threading.Thread(
            target=self.responses,
            name=f"grpc_lane_response_{self.spec.lane_index}",
            daemon=True,
        )
        self.response_thread.start()

    def cancel(self):
        self.measure_event.set()
        self.controls.put(_QUEUE_EOF)
        if self.call is not None:
            self.call.cancel()
        self.fail(RuntimeError(f"lane {self.spec.lane_index} cancelled"))


def _validate_peer_topology(
    lanes: list[LaneClient | ServerToClientLaneClient], channel_count: int, rpcs_per_channel: int
) -> dict:
    peer_by_channel = {}
    for lane in lanes:
        if not lane.peer:
            raise RuntimeError(f"lane {lane.spec.lane_index} did not report a peer socket")
        peers = peer_by_channel.setdefault(lane.spec.channel_index, set())
        peers.add(lane.peer)
    split_channels = {channel: peers for channel, peers in peer_by_channel.items() if len(peers) != 1}
    if split_channels:
        raise RuntimeError(f"RPCs on one Channel used multiple peer sockets: {split_channels}")
    channel_peers = {channel: next(iter(peers)) for channel, peers in peer_by_channel.items()}
    unique_peers = set(channel_peers.values())
    if len(channel_peers) != channel_count or len(unique_peers) != channel_count:
        raise RuntimeError(
            f"requested {channel_count} physical channels but observed {len(unique_peers)} peer sockets: "
            f"{channel_peers}"
        )
    if len(lanes) != channel_count * rpcs_per_channel:
        raise RuntimeError("logical RPC count does not match requested topology")
    return channel_peers


def _lane_flow_limits(lane_count: int, window_size: int, ack_interval: int, chunk_size: int):
    lane_windows = _partition(window_size, lane_count)
    # Keep total ACK work constant: each lane carries 1/N of the bytes but uses
    # the original ACK threshold, producing about 1/N as many ACKs.
    lane_ack_intervals = [ack_interval] * lane_count
    for lane_window, lane_ack in zip(lane_windows, lane_ack_intervals):
        chunk_rounded_ack = ((lane_ack + chunk_size - 1) // chunk_size) * chunk_size
        if lane_window < chunk_size:
            raise ValueError(
                f"aggregate window {window_size:,} is too small for {lane_count} lanes with "
                f"{chunk_size:,}-byte chunks"
            )
        if chunk_rounded_ack > lane_window:
            raise ValueError(
                f"per-lane window {lane_window:,} cannot reach the {lane_ack:,}-byte ACK threshold "
                f"with {chunk_size:,}-byte chunks"
            )
    return lane_windows, lane_ack_intervals


def _make_channels(url: str, channel_count: int, secure: bool, credentials: dict, options: list[tuple]):
    params = _connection_params(url, credentials, secure)
    address = get_address(params)
    channel_options = _client_channel_options(options, channel_count)
    channels = []
    for _ in range(channel_count):
        if secure:
            channel = grpc.secure_channel(
                address,
                credentials=get_grpc_client_credentials(params),
                options=channel_options,
            )
        else:
            channel = grpc.insecure_channel(address, options=channel_options)
        channels.append(channel)
    return channels


def run_one_sender(
    stubs: list[StreamerStub],
    channel_count: int,
    rpcs_per_channel: int,
    measured_bytes: int,
    warmup_bytes: int,
    chunk_size: int,
    window_size: int,
    ack_interval: int,
    timeout: float,
    direction: int = DIRECTION_SERVER_TO_CLIENT,
) -> dict:
    if direction not in DIRECTION_NAMES:
        raise ValueError(f"invalid transfer direction {direction!r}")
    lane_count = channel_count * rpcs_per_channel
    lane_measured = _partition(measured_bytes, lane_count)
    lane_warmup = _partition(warmup_bytes, lane_count)
    lane_windows, lane_ack_intervals = _lane_flow_limits(lane_count, window_size, ack_interval, chunk_size)
    if min(lane_measured) <= 0:
        raise ValueError("measured payload must assign at least one byte to every RPC")
    run_token = uuid.uuid4().bytes
    measure_event = threading.Event()
    outstanding = OutstandingTracker()
    lanes = []
    for channel_index, stub in enumerate(stubs):
        for rpc_index in range(rpcs_per_channel):
            lane_index = channel_index * rpcs_per_channel + rpc_index
            pattern = (lane_index % 251) + 1
            spec = LaneSpec(
                run_token=run_token,
                lane_index=lane_index,
                channel_index=channel_index,
                rpc_index=rpc_index,
                channel_count=channel_count,
                rpcs_per_channel=rpcs_per_channel,
                lane_count=lane_count,
                direction=direction,
                pattern=pattern,
                warmup_bytes=lane_warmup[lane_index],
                measured_bytes=lane_measured[lane_index],
                chunk_size=chunk_size,
                ack_interval=lane_ack_intervals[lane_index],
                window_size=lane_windows[lane_index],
            )
            spec.validate()
            if direction == DIRECTION_CLIENT_TO_SERVER:
                lane = LaneClient(
                    stub=stub,
                    spec=spec,
                    lane_window=lane_windows[lane_index],
                    payload_block=bytes([pattern]) * chunk_size,
                    measure_event=measure_event,
                    outstanding=outstanding,
                    timeout=timeout,
                )
            else:
                lane = ServerToClientLaneClient(
                    stub=stub,
                    spec=spec,
                    measure_event=measure_event,
                    outstanding=outstanding,
                    timeout=timeout,
                )
            lanes.append(lane)

    sampler = ProcessSampler()
    sampler.start()
    cpu_total_started = time.process_time()
    rss_after_warmup = None
    caught = None
    try:
        for lane in lanes:
            lane.start()
        for lane in lanes:
            lane._wait(lane.ready, "receiver readiness")
        channel_peers = _validate_peer_topology(lanes, channel_count, rpcs_per_channel)
        for lane in lanes:
            lane._wait(lane.warm_done, "warm-up completion")
        if outstanding.current != 0:
            raise RuntimeError(f"warm-up left {outstanding.current:,} bytes unacknowledged")

        rss_after_warmup = sampler.observe()
        process_started = time.process_time()
        started = time.perf_counter()
        measure_event.set()
        for lane in lanes:
            lane._wait(lane.done, "measurement completion")
        elapsed = time.perf_counter() - started
        cpu_seconds = time.process_time() - process_started
        if outstanding.current != 0:
            raise RuntimeError(f"measurement left {outstanding.current:,} bytes unacknowledged")
    except BaseException as ex:
        caught = ex
        measure_event.set()
        for lane in lanes:
            lane.cancel()
    finally:
        cleanup_deadline = time.monotonic() + 5
        for lane in lanes:
            if lane.response_thread is not None:
                lane.response_thread.join(timeout=max(0, cleanup_deadline - time.monotonic()))
        sampler.stop()

    stuck_threads = [
        lane.spec.lane_index for lane in lanes if lane.response_thread is not None and lane.response_thread.is_alive()
    ]
    late_errors = [lane.error for lane in lanes if lane.error is not None]
    if caught is None and late_errors:
        caught = late_errors[0]
    if stuck_threads:
        error = RuntimeError(f"lane response threads did not stop: {stuck_threads}")
        if caught is not None:
            raise error from caught
        raise error
    if caught is not None:
        raise caught.with_traceback(caught.__traceback__)

    return {
        "run_token": run_token.hex(),
        "bytes": measured_bytes,
        "seconds": elapsed,
        "mib_per_second": measured_bytes / MB / elapsed,
        "gbit_per_second": measured_bytes * 8 / 1_000_000_000 / elapsed,
        "channels": channel_count,
        "rpcs_per_channel": rpcs_per_channel,
        "logical_rpcs": lane_count,
        "unique_peer_sockets": len(set(channel_peers.values())),
        "peer_sockets": channel_peers,
        "direction": DIRECTION_NAMES[direction],
        "peak_outstanding_bytes": (
            outstanding.peak
            if direction == DIRECTION_CLIENT_TO_SERVER
            else max(lane.server_peak_outstanding for lane in lanes)
        ),
        "window_bytes": window_size,
        "cpu_measurement_seconds": cpu_seconds,
        "cpu_run_seconds": time.process_time() - cpu_total_started,
        "rss_baseline_bytes": sampler.baseline,
        "rss_after_warmup_bytes": rss_after_warmup,
        "rss_peak_bytes": sampler.peak,
        "transport_security": sorted({lane.transport_security for lane in lanes}),
    }


def _start_server(url: str, connection_security: str, credentials_dir: Optional[Path]):
    secure, credentials = resolve_cell_security(RX_FQCN, url, connection_security, credentials_dir)
    params = _connection_params(url, credentials, secure)
    max_workers, options = _grpc_settings()
    server_options = [entry for entry in options if entry[0] != "grpc.max_receive_message_length"]
    server_options.append(("grpc.max_receive_message_length", MAX_GRPC_FRAME_BYTES))
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers),
        options=server_options,
        maximum_concurrent_rpcs=min(max_workers, MAX_LANES),
    )
    servicer = LaneBenchServicer()
    add_StreamerServicer_to_server(servicer, server)
    address = get_address(params)
    if secure:
        port = server.add_secure_port(address, get_grpc_server_credentials(params))
    else:
        port = server.add_insecure_port(address)
    if port == 0:
        raise RuntimeError(f"could not bind gRPC lane receiver to {address}")
    server.start()
    return server, servicer, port


def run_receiver(
    url: str,
    connection_security: str = ConnectionSecurity.CLEAR,
    credentials_dir: Optional[Path] = None,
):
    server, servicer, port = _start_server(url, connection_security, credentials_dir)
    print(
        f"[recv] listening on {url} bound_port={port} connection_security={connection_security}; "
        "waiting for gRPC lane runs (Ctrl-C to stop)",
        flush=True,
    )
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("[recv] stopping", flush=True)
    finally:
        server.stop(grace=0.5).wait(timeout=5)
        servicer.registry.stop()


def run_sender(
    url: str,
    channel_count: int,
    rpcs_per_channel: int,
    measured_bytes: int,
    warmup_bytes: int,
    chunk_size: int,
    window_size: int,
    ack_interval: int,
    repeat: int,
    timeout: float,
    direction: int = DIRECTION_SERVER_TO_CLIENT,
    connection_security: str = ConnectionSecurity.CLEAR,
    credentials_dir: Optional[Path] = None,
) -> list[dict]:
    secure, credentials = resolve_cell_security(TX_FQCN, url, connection_security, credentials_dir)
    _, options = _grpc_settings()
    process = psutil.Process()
    rss_before_channels = process.memory_info().rss
    channels = _make_channels(url, channel_count, secure, credentials, options)
    try:
        for channel in channels:
            grpc.channel_ready_future(channel).result(timeout=timeout)
        rss_after_channels = process.memory_info().rss
        stubs = [StreamerStub(channel) for channel in channels]
        print(
            f"[send] connected to {url}, connection_security={connection_security}, channels={channel_count}, "
            f"rpcs_per_channel={rpcs_per_channel}, logical_rpcs={channel_count * rpcs_per_channel}, "
            f"direction={DIRECTION_NAMES[direction]}, "
            f"chunk={chunk_size / MB:,.1f} MiB, aggregate_window={window_size / MB:,.1f} MiB, "
            f"per_lane_ack={ack_interval / MB:,.1f} MiB",
            flush=True,
        )
        results = []
        for repetition in range(1, repeat + 1):
            result = run_one_sender(
                stubs=stubs,
                channel_count=channel_count,
                rpcs_per_channel=rpcs_per_channel,
                measured_bytes=measured_bytes,
                warmup_bytes=warmup_bytes,
                chunk_size=chunk_size,
                window_size=window_size,
                ack_interval=ack_interval,
                timeout=timeout,
                direction=direction,
            )
            result["rss_before_channels_bytes"] = rss_before_channels
            result["rss_after_channels_bytes"] = rss_after_channels
            expected_transport = ["ssl"] if secure else ["insecure"]
            if result["transport_security"] != expected_transport:
                raise RuntimeError(
                    f"expected transport security {expected_transport}, observed {result['transport_security']}"
                )
            results.append(result)
            print(
                f"[send] RESULT repetition={repetition} run={result['run_token']} bytes={result['bytes']} "
                f"seconds={result['seconds']:.6f} mib_per_sec={result['mib_per_second']:.1f} "
                f"gbit_per_sec={result['gbit_per_second']:.3f} channels={result['channels']} "
                f"rpcs_per_channel={result['rpcs_per_channel']} logical_rpcs={result['logical_rpcs']} "
                f"direction={result['direction']} "
                f"unique_peer_sockets={result['unique_peer_sockets']} "
                f"peak_outstanding_bytes={result['peak_outstanding_bytes']} "
                f"window_bytes={result['window_bytes']} "
                f"cpu_measurement_seconds={result['cpu_measurement_seconds']:.6f} "
                f"cpu_run_seconds={result['cpu_run_seconds']:.6f} "
                f"rss_before_channels_bytes={result['rss_before_channels_bytes']} "
                f"rss_after_channels_bytes={result['rss_after_channels_bytes']} "
                f"rss_run_baseline_bytes={result['rss_baseline_bytes']} "
                f"rss_after_warmup_bytes={result['rss_after_warmup_bytes']} "
                f"rss_peak_bytes={result['rss_peak_bytes']} "
                f"transport_security={result['transport_security']} "
                f"peers={result['peer_sockets']}",
                flush=True,
            )
        return results
    finally:
        for channel in channels:
            channel.close()


def _positive_bytes(value: float, unit: int, name: str) -> int:
    result = int(value * unit)
    if result <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return result


def _nonnegative_bytes(value: float, unit: int, name: str) -> int:
    result = int(value * unit)
    if result < 0:
        raise ValueError(f"{name} must not be negative")
    return result


def main():
    parser = argparse.ArgumentParser(description="gRPC stream/channel scaling benchmark")
    parser.add_argument("--log-level", default="WARNING", help="Python log level")
    sub = parser.add_subparsers(dest="role", required=True)

    receiver = sub.add_parser("recv", help="run the receiver")
    receiver.add_argument("--url", default="grpc://0.0.0.0:8002", help="listening gRPC URL")
    receiver.add_argument("--f3-config", help="optional comm_config.yml supplying gRPC server options")
    add_cell_security_args(receiver)

    sender = sub.add_parser("send", help="run the sender")
    sender.add_argument("--url", required=True, help="receiver gRPC URL")
    sender.add_argument("--channels", type=int, choices=range(1, MAX_CHANNELS + 1), default=1)
    sender.add_argument("--rpcs-per-channel", type=int, choices=range(1, MAX_RPCS_PER_CHANNEL + 1), default=1)
    sender.add_argument(
        "--direction",
        choices=tuple(DIRECTION_CODES),
        default="server-to-client",
        help="bulk-byte direction; server-to-client matches model download",
    )
    sender.add_argument("--size-gb", type=float, default=DEFAULT_SIZE / GB, help="aggregate measured GiB")
    sender.add_argument("--warmup-gb", type=float, default=DEFAULT_WARMUP_SIZE / GB, help="aggregate warm-up GiB")
    sender.add_argument("--chunk-mb", type=float, default=None, help="protobuf payload size in MiB")
    sender.add_argument("--window-mb", type=float, default=None, help="aggregate application window in MiB")
    sender.add_argument("--ack-mb", type=float, default=None, help="per-lane ACK threshold in MiB")
    sender.add_argument("--repeat", type=int, default=1)
    sender.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    sender.add_argument("--f3-config", help="optional comm_config.yml supplying gRPC and streaming options")
    add_cell_security_args(sender)

    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.WARNING))
    if args.f3_config:
        try:
            config_path, _ = configure_f3(args.f3_config)
        except (OSError, ValueError, yaml.YAMLError) as ex:
            parser.error(str(ex))
        print(f"[config] loaded {config_path}: {f3_config_summary()}", flush=True)
    try:
        _validate_url(args.url)
        role = RX_FQCN if args.role == "recv" else TX_FQCN
        resolve_cell_security(role, args.url, args.connection_security, args.credentials_dir)
        if args.role == "recv":
            run_receiver(args.url, args.connection_security, args.credentials_dir)
            return

        if args.repeat <= 0:
            raise ValueError("--repeat must be greater than zero")
        if args.timeout <= 0:
            raise ValueError("--timeout must be greater than zero")
        config = CommConfigurator()
        chunk_size = (
            _positive_bytes(args.chunk_mb, MB, "--chunk-mb")
            if args.chunk_mb is not None
            else config.get_streaming_chunk_size(DEFAULT_CHUNK_SIZE)
        )
        window_size = (
            _positive_bytes(args.window_mb, MB, "--window-mb")
            if args.window_mb is not None
            else config.get_streaming_window_size(DEFAULT_WINDOW_SIZE)
        )
        ack_interval = (
            _positive_bytes(args.ack_mb, MB, "--ack-mb")
            if args.ack_mb is not None
            else config.get_streaming_ack_interval(DEFAULT_ACK_INTERVAL)
        )
        run_sender(
            url=args.url,
            channel_count=args.channels,
            rpcs_per_channel=args.rpcs_per_channel,
            measured_bytes=_positive_bytes(args.size_gb, GB, "--size-gb"),
            warmup_bytes=_nonnegative_bytes(args.warmup_gb, GB, "--warmup-gb"),
            chunk_size=chunk_size,
            window_size=window_size,
            ack_interval=ack_interval,
            repeat=args.repeat,
            timeout=args.timeout,
            direction=DIRECTION_CODES[args.direction],
            connection_security=args.connection_security,
            credentials_dir=args.credentials_dir,
        )
    except (OSError, RuntimeError, ValueError, grpc.RpcError) as ex:
        parser.error(str(ex))


if __name__ == "__main__":
    main()
