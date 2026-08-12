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

"""One-port mTLS tensor bulk-transfer discriminator.

This standalone benchmark deliberately bypasses Cell/SFM/ByteStreamer and the
Download Service.  A client first sends a bounded tensor manifest over a
control connection, then opens N client-initiated data connections to the same
listener.  The receiver reads each lane directly into non-overlapping ranges
of one preallocated bytearray.  The wire data is validated with a SHA-256 for
every tensor after the timed interval.

It is an architectural upper-bound experiment, not a production protocol:
there is no reconnect/resume, relay routing, mixed-version negotiation, or
application-level retry.  TCP and mutual TLS still provide ordered delivery,
integrity, confidentiality, and peer certificate authentication.
"""

import argparse
import gc
import hashlib
import json
import signal
import socket
import ssl
import struct
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import psutil
import torch


MAGIC = b"NVFTB001"
KIND_CONTROL = 1
KIND_DATA = 2
PREFACE = struct.Struct("!8sB16sHHQ")
LENGTH = struct.Struct("!I")
MAX_MANIFEST_BYTES = 1 << 20
MAX_TRANSFER_BYTES = 8 << 30
MAX_LANES = 4
HANDSHAKE_TIMEOUT = 15.0
IO_TIMEOUT = 600.0
MB = 1 << 20


def _recv_exact(sock: ssl.SSLSocket, size: int) -> bytes:
    result = bytearray(size)
    view = memoryview(result)
    offset = 0
    while offset < size:
        count = sock.recv_into(view[offset:])
        if count == 0:
            raise ConnectionError(f"peer closed after {offset:,} of {size:,} bytes")
        offset += count
    return bytes(result)


def _send_json(sock: ssl.SSLSocket, value: dict):
    data = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError(f"JSON message is too large: {len(data):,} bytes")
    sock.sendall(LENGTH.pack(len(data)))
    sock.sendall(data)


def _recv_json(sock: ssl.SSLSocket) -> dict:
    (size,) = LENGTH.unpack(_recv_exact(sock, LENGTH.size))
    if not 1 <= size <= MAX_MANIFEST_BYTES:
        raise ValueError(f"invalid JSON message size {size:,}")
    value = json.loads(_recv_exact(sock, size).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON message must be an object")
    return value


def _parse_url(value: str, *, listen: bool) -> tuple[str, int]:
    parsed = urlparse(value)
    if parsed.scheme != "ntls" or parsed.hostname is None or parsed.port is None:
        raise ValueError("URL must be ntls://host:port")
    if not listen and parsed.hostname in {"0.0.0.0", "::"}:
        raise ValueError("sender URL must name the certificate host")
    return parsed.hostname, parsed.port


def _server_context(credentials_dir: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(credentials_dir / "server.crt", credentials_dir / "server.key")
    context.load_verify_locations(cafile=credentials_dir / "rootCA.pem")
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _client_context(credentials_dir: Path) -> ssl.SSLContext:
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=credentials_dir / "rootCA.pem")
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.load_cert_chain(credentials_dir / "client.crt", credentials_dir / "client.key")
    return context


def _connect(host: str, port: int, context: ssl.SSLContext) -> ssl.SSLSocket:
    raw = socket.create_connection((host, port), timeout=HANDSHAKE_TIMEOUT)
    raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        result = context.wrap_socket(raw, server_hostname=host)
    except BaseException:
        raw.close()
        raise
    result.settimeout(IO_TIMEOUT)
    return result


class ResourceSampler:
    def __init__(self, interval: float = 0.05):
        self.interval = interval
        self.process = psutil.Process()
        self.baseline = self.process.memory_info().rss
        self.peak = self.baseline
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="native-bulk-rss", daemon=True)

    def start(self):
        self._thread.start()

    def _run(self):
        while not self._stop.wait(self.interval):
            self.peak = max(self.peak, self.process.memory_info().rss)

    def stop(self) -> dict:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self.peak = max(self.peak, self.process.memory_info().rss)
        return {
            "rss_baseline_bytes": self.baseline,
            "rss_peak_bytes": self.peak,
            "rss_peak_delta_bytes": max(0, self.peak - self.baseline),
        }


def _validate_manifest(manifest: dict) -> tuple[list[dict], int, int]:
    if manifest.get("version") != 1:
        raise ValueError("unsupported manifest version")
    lanes = manifest.get("lanes")
    total = manifest.get("total_bytes")
    tensors = manifest.get("tensors")
    if isinstance(lanes, bool) or not isinstance(lanes, int) or not 1 <= lanes <= MAX_LANES:
        raise ValueError(f"lanes must be in [1, {MAX_LANES}]")
    if isinstance(total, bool) or not isinstance(total, int) or not 1 <= total <= MAX_TRANSFER_BYTES:
        raise ValueError("invalid total_bytes")
    if not isinstance(tensors, list) or not tensors:
        raise ValueError("tensors must be a non-empty list")

    expected_offset = 0
    keys = set()
    for item in tensors:
        if not isinstance(item, dict):
            raise ValueError("tensor entries must be objects")
        key = item.get("key")
        size = item.get("size")
        offset = item.get("offset")
        lane = item.get("lane")
        digest = item.get("sha256")
        shape = item.get("shape")
        dtype = item.get("dtype")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("tensor keys must be unique non-empty strings")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError(f"invalid size for {key}")
        if offset != expected_offset:
            raise ValueError(f"non-canonical offset for {key}: {offset} != {expected_offset}")
        if isinstance(lane, bool) or not isinstance(lane, int) or not 0 <= lane < lanes:
            raise ValueError(f"invalid lane for {key}")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"invalid SHA-256 for {key}")
        if not isinstance(shape, list) or not all(isinstance(v, int) and v >= 0 for v in shape):
            raise ValueError(f"invalid shape for {key}")
        if not isinstance(dtype, str) or not dtype:
            raise ValueError(f"invalid dtype for {key}")
        keys.add(key)
        expected_offset += size
        if expected_offset > total:
            raise ValueError("tensor ranges exceed total_bytes")
    if expected_offset != total:
        raise ValueError(f"tensor ranges cover {expected_offset:,}, expected {total:,}")
    if set(item["lane"] for item in tensors) != set(range(lanes)):
        raise ValueError("every declared lane must own at least one tensor")
    return tensors, total, lanes


@dataclass
class RunState:
    token: bytes
    manifest: dict
    tensors: list[dict]
    total_bytes: int
    lane_count: int
    prefault_receive: bool

    def __post_init__(self):
        allocation_started = time.perf_counter()
        if self.prefault_receive:
            self.storage = bytearray(self.total_bytes)
            self.view = memoryview(self.storage)
        else:
            self.storage = torch.empty(self.total_bytes, dtype=torch.uint8)
            self.view = memoryview(self.storage.numpy()).cast("B")
        self.allocation_s = time.perf_counter() - allocation_started
        self.lane_registered = set()
        self.lane_done = set()
        self.lock = threading.Lock()
        self.start_event = threading.Event()
        self.done_event = threading.Event()
        self.start_ns = 0
        self.end_ns = 0
        self.error: Optional[str] = None

    def lane_items(self, lane: int) -> list[dict]:
        return [item for item in self.tensors if item["lane"] == lane]

    def register_lane(self, lane: int, expected_bytes: int):
        actual = sum(item["size"] for item in self.lane_items(lane))
        if expected_bytes != actual:
            raise ValueError(f"lane {lane} declares {expected_bytes:,} bytes, expected {actual:,}")
        with self.lock:
            if lane in self.lane_registered:
                raise ValueError(f"duplicate lane {lane}")
            self.lane_registered.add(lane)

    def start(self):
        with self.lock:
            if self.lane_registered != set(range(self.lane_count)):
                raise ValueError(f"only {len(self.lane_registered)} of {self.lane_count} lanes registered")
            self.start_ns = time.perf_counter_ns()
            self.start_event.set()

    def finish_lane(self, lane: int):
        with self.lock:
            self.lane_done.add(lane)
            if len(self.lane_done) == self.lane_count:
                self.end_ns = time.perf_counter_ns()
                self.done_event.set()

    def fail(self, error: BaseException):
        with self.lock:
            if self.error is None:
                self.error = f"{type(error).__name__}: {error}"
            self.start_event.set()
            self.done_event.set()

    def validate(self) -> tuple[bool, str, float]:
        started = time.perf_counter()
        for item in self.tensors:
            view = self.view[item["offset"] : item["offset"] + item["size"]]
            actual = hashlib.sha256(view).hexdigest()
            if actual != item["sha256"]:
                return False, f"hash mismatch for {item['key']}", time.perf_counter() - started
        return True, "", time.perf_counter() - started


class RunRegistry:
    def __init__(self, prefault_receive: bool):
        self.prefault_receive = prefault_receive
        self.lock = threading.Lock()
        self.states: dict[bytes, RunState] = {}

    def create(self, token: bytes, manifest: dict) -> RunState:
        tensors, total, lanes = _validate_manifest(manifest)
        state = RunState(token, manifest, tensors, total, lanes, self.prefault_receive)
        with self.lock:
            if token in self.states:
                raise ValueError("duplicate run token")
            self.states[token] = state
        return state

    def get(self, token: bytes) -> RunState:
        with self.lock:
            state = self.states.get(token)
        if state is None:
            raise ValueError("unknown run token")
        return state

    def remove(self, token: bytes):
        with self.lock:
            self.states.pop(token, None)


class NativeBulkReceiver:
    def __init__(self, host: str, port: int, credentials_dir: Path, max_workers: int, prefault_receive: bool):
        self.host = host
        self.port = port
        self.context = _server_context(credentials_dir)
        self.registry = RunRegistry(prefault_receive)
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="native-bulk")
        self.stop_event = threading.Event()
        self.listener: Optional[socket.socket] = None

    def stop(self, *_):
        self.stop_event.set()
        if self.listener:
            try:
                self.listener.close()
            except OSError:
                pass

    def serve(self):
        family = socket.AF_INET6 if ":" in self.host else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as listener:
            self.listener = listener
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen(32)
            listener.settimeout(0.5)
            print(f"[recv] listening url=ntls://{self.host}:{self.port} security=mtls", flush=True)
            while not self.stop_event.is_set():
                try:
                    raw, address = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self.stop_event.is_set():
                        break
                    raise
                self.executor.submit(self._handle, raw, address)
        self.executor.shutdown(wait=True, cancel_futures=True)
        print("[recv] stopping", flush=True)

    def _handle(self, raw: socket.socket, address):
        raw.settimeout(HANDSHAKE_TIMEOUT)
        try:
            with self.context.wrap_socket(raw, server_side=True) as sock:
                sock.settimeout(IO_TIMEOUT)
                magic, kind, token, lane, lane_count, value = PREFACE.unpack(_recv_exact(sock, PREFACE.size))
                if magic != MAGIC:
                    raise ValueError("bad protocol magic")
                if kind == KIND_CONTROL:
                    self._handle_control(sock, token, lane, lane_count, value)
                elif kind == KIND_DATA:
                    self._handle_data(sock, token, lane, lane_count, value)
                else:
                    raise ValueError(f"unknown connection kind {kind}")
        except BaseException as ex:
            try:
                self.registry.get(token).fail(ex)
            except (UnboundLocalError, ValueError):
                pass
            print(f"[recv] connection_error peer={address} error={type(ex).__name__}: {ex}", flush=True)
            raw.close()

    def _handle_control(self, sock: ssl.SSLSocket, token: bytes, lane: int, lane_count: int, value: int):
        if lane != 0xFFFF or not 1 <= lane_count <= MAX_LANES:
            raise ValueError("invalid control preface")
        if not 1 <= value <= MAX_MANIFEST_BYTES:
            raise ValueError("invalid manifest size")
        manifest = json.loads(_recv_exact(sock, value).decode("utf-8"))
        sampler = ResourceSampler()
        sampler.start()
        try:
            state = self.registry.create(token, manifest)
            if lane_count != state.lane_count:
                raise ValueError("control lane count does not match manifest")
            _send_json(sock, {"status": "ready", "token": token.hex()})
            if _recv_exact(sock, 1) != b"S":
                raise ValueError("expected start marker")
            state.start()
            sock.sendall(b"S")
            if not state.done_event.wait(IO_TIMEOUT):
                raise TimeoutError("timed out waiting for data lanes")
            if state.error:
                raise RuntimeError(state.error)
            valid, error, validation_s = state.validate()
            elapsed = (state.end_ns - state.start_ns) / 1e9
            metrics = sampler.stop()
            result = {
                "status": "ok" if valid else "error",
                "error": error,
                "bytes": state.total_bytes,
                "lanes": state.lane_count,
                "prefault_receive": state.prefault_receive,
                "transfer_s": elapsed,
                "rate_mib_s": state.total_bytes / MB / elapsed,
                "allocation_s": state.allocation_s,
                "validation_s": validation_s,
                **metrics,
            }
            _send_json(sock, result)
            print(
                f"[recv] RESULT token={token.hex()} lanes={state.lane_count} bytes={state.total_bytes} "
                f"transfer_s={elapsed:.6f} rate_mib_s={result['rate_mib_s']:.3f} "
                f"prefault_receive={state.prefault_receive} allocation_s={state.allocation_s:.6f} "
                f"validation_s={validation_s:.6f} "
                f"valid={valid} rss_peak_delta_bytes={metrics['rss_peak_delta_bytes']}",
                flush=True,
            )
        finally:
            sampler.stop()
            self.registry.remove(token)

    def _handle_data(self, sock: ssl.SSLSocket, token: bytes, lane: int, lane_count: int, value: int):
        state = self.registry.get(token)
        if lane_count != state.lane_count or not 0 <= lane < lane_count:
            raise ValueError("invalid data-lane preface")
        state.register_lane(lane, value)
        sock.sendall(b"R")
        if not state.start_event.wait(IO_TIMEOUT):
            raise TimeoutError("timed out waiting for run start")
        if state.error:
            raise RuntimeError(state.error)
        for item in state.lane_items(lane):
            view = state.view[item["offset"] : item["offset"] + item["size"]]
            offset = 0
            while offset < len(view):
                count = sock.recv_into(view[offset:])
                if count == 0:
                    raise ConnectionError(f"lane {lane} closed with {len(view) - offset:,} bytes remaining")
                offset += count
        state.finish_lane(lane)
        sock.sendall(b"D")


def _tensor_bytes(tensor: torch.Tensor) -> memoryview:
    if tensor.device.type != "cpu" or not tensor.is_contiguous():
        raise ValueError("native bulk benchmark requires contiguous CPU tensors")
    return memoryview(tensor.detach().numpy()).cast("B")


def _load_tensors(checkpoint_path: Path) -> dict[str, torch.Tensor]:
    value = torch.load(checkpoint_path, map_location="cpu", weights_only=True, mmap=True)
    if isinstance(value, dict) and isinstance(value.get("state_dict"), dict):
        value = value["state_dict"]
    if not isinstance(value, dict) or not value:
        raise ValueError("checkpoint must contain a non-empty tensor dictionary")
    tensors = {str(key): tensor for key, tensor in value.items() if isinstance(tensor, torch.Tensor)}
    if len(tensors) != len(value):
        raise ValueError("checkpoint contains non-tensor values")
    for key, tensor in tensors.items():
        if tensor.device.type != "cpu" or not tensor.is_contiguous():
            raise ValueError(f"tensor {key} is not contiguous CPU storage")
    return dict(sorted(tensors.items()))


def _build_manifest(tensors: dict[str, torch.Tensor], lanes: int) -> tuple[dict, dict[str, str]]:
    digests = {}
    entries = []
    offset = 0
    lane_sizes = [0] * lanes
    for key, tensor in tensors.items():
        view = _tensor_bytes(tensor)
        lane = min(range(lanes), key=lambda value: (lane_sizes[value], value))
        digest = hashlib.sha256(view).hexdigest()
        digests[key] = digest
        entries.append(
            {
                "key": key,
                "dtype": str(tensor.dtype),
                "shape": list(tensor.shape),
                "offset": offset,
                "size": len(view),
                "lane": lane,
                "sha256": digest,
            }
        )
        offset += len(view)
        lane_sizes[lane] += len(view)
    manifest = {"version": 1, "lanes": lanes, "total_bytes": offset, "tensors": entries}
    _validate_manifest(manifest)
    return manifest, digests


def _send_lane(sock: ssl.SSLSocket, items: list[dict], views: dict[str, memoryview], start_event: threading.Event):
    start_event.wait()
    for item in items:
        view = views[item["key"]]
        offset = 0
        while offset < len(view):
            count = sock.send(view[offset:])
            if count == 0:
                raise ConnectionError("socket send returned zero")
            offset += count
    if _recv_exact(sock, 1) != b"D":
        raise ValueError("invalid data completion marker")


def _run_sender_once(
    host: str,
    port: int,
    context: ssl.SSLContext,
    original: dict[str, torch.Tensor],
    base_manifest: dict,
    lanes: int,
    snapshot: bool,
    repeat_index: int,
):
    sampler = ResourceSampler()
    sampler.start()
    e2e_started = time.perf_counter()
    snapshot_started = time.perf_counter()
    tensors = {key: tensor.detach().clone() for key, tensor in original.items()} if snapshot else original
    snapshot_s = time.perf_counter() - snapshot_started
    views = {key: _tensor_bytes(tensor) for key, tensor in tensors.items()}
    manifest = dict(base_manifest)
    manifest["snapshot"] = snapshot
    manifest_data = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode("utf-8")
    token = uuid.uuid4().bytes

    control = _connect(host, port, context)
    data_sockets = []
    threads = []
    errors = []
    try:
        control.sendall(PREFACE.pack(MAGIC, KIND_CONTROL, token, 0xFFFF, lanes, len(manifest_data)))
        control.sendall(manifest_data)
        ready = _recv_json(control)
        if ready.get("status") != "ready" or ready.get("token") != token.hex():
            raise RuntimeError(f"receiver rejected manifest: {ready}")

        for lane in range(lanes):
            items = [item for item in manifest["tensors"] if item["lane"] == lane]
            lane_bytes = sum(item["size"] for item in items)
            sock = _connect(host, port, context)
            sock.sendall(PREFACE.pack(MAGIC, KIND_DATA, token, lane, lanes, lane_bytes))
            if _recv_exact(sock, 1) != b"R":
                raise RuntimeError(f"lane {lane} was not accepted")
            data_sockets.append((sock, items))

        start_event = threading.Event()

        def lane_target(sock, items):
            try:
                _send_lane(sock, items, views, start_event)
            except BaseException as ex:
                errors.append(ex)

        for lane, (sock, items) in enumerate(data_sockets):
            thread = threading.Thread(target=lane_target, args=(sock, items), name=f"native-bulk-lane-{lane}")
            thread.start()
            threads.append(thread)

        control.sendall(b"S")
        if _recv_exact(control, 1) != b"S":
            raise RuntimeError("receiver did not acknowledge start")
        transfer_started = time.perf_counter()
        start_event.set()
        for thread in threads:
            thread.join(timeout=IO_TIMEOUT)
        if any(thread.is_alive() for thread in threads):
            raise TimeoutError("a data-lane thread did not finish")
        if errors:
            raise errors[0]
        transfer_s = time.perf_counter() - transfer_started
        cold_transfer_s = time.perf_counter() - e2e_started
        result = _recv_json(control)
        if result.get("status") != "ok" or result.get("bytes") != manifest["total_bytes"]:
            raise RuntimeError(f"receiver validation failed: {result}")
        total_s = snapshot_s + transfer_s
        validated_e2e_s = time.perf_counter() - e2e_started
        metrics = sampler.stop()
        print(
            f"[send] RESULT repeat={repeat_index} token={token.hex()} lanes={lanes} snapshot={snapshot} "
            f"bytes={manifest['total_bytes']} transfer_s={transfer_s:.6f} "
            f"rate_mib_s={manifest['total_bytes'] / MB / transfer_s:.3f} snapshot_s={snapshot_s:.6f} "
            f"effective_s={total_s:.6f} effective_mib_s={manifest['total_bytes'] / MB / total_s:.3f} "
            f"cold_transfer_s={cold_transfer_s:.6f} "
            f"cold_mib_s={manifest['total_bytes'] / MB / cold_transfer_s:.3f} "
            f"receiver_transfer_s={result['transfer_s']:.6f} receiver_rate_mib_s={result['rate_mib_s']:.3f} "
            f"receiver_allocation_s={result['allocation_s']:.6f} receiver_validation_s={result['validation_s']:.6f} "
            f"validated_e2e_s={validated_e2e_s:.6f} "
            f"rss_peak_delta_bytes={metrics['rss_peak_delta_bytes']} valid=True",
            flush=True,
        )
    finally:
        start_event = locals().get("start_event")
        if start_event:
            start_event.set()
        for sock, _ in data_sockets:
            sock.close()
        control.close()
        sampler.stop()
        if snapshot:
            del tensors
            gc.collect()


def run_sender(args):
    host, port = _parse_url(args.url, listen=False)
    context = _client_context(args.credentials_dir)
    tensors = _load_tensors(args.checkpoint)
    manifest, _ = _build_manifest(tensors, args.lanes)
    print(
        f"[send] checkpoint={args.checkpoint} tensors={len(tensors)} bytes={manifest['total_bytes']} "
        f"lanes={args.lanes} snapshot={not args.borrow_input} security=mtls",
        flush=True,
    )
    for repeat_index in range(1, args.repeat + 1):
        _run_sender_once(
            host,
            port,
            context,
            tensors,
            manifest,
            args.lanes,
            not args.borrow_input,
            repeat_index,
        )


def run_receiver(args):
    host, port = _parse_url(args.url, listen=True)
    receiver = NativeBulkReceiver(host, port, args.credentials_dir, args.max_workers, args.prefault_receive)
    signal.signal(signal.SIGINT, receiver.stop)
    signal.signal(signal.SIGTERM, receiver.stop)
    receiver.serve()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    recv = subparsers.add_parser("recv", help="run the one-port mTLS receiver")
    recv.add_argument("--url", default="ntls://0.0.0.0:8002")
    recv.add_argument("--credentials-dir", type=Path, required=True)
    recv.add_argument("--max-workers", type=int, default=12)
    recv.add_argument(
        "--prefault-receive",
        action="store_true",
        help="zero/fault the complete receive buffer before transfer (higher setup cost, potentially higher wire rate)",
    )

    send = subparsers.add_parser("send", help="send an mmap-loaded PyTorch checkpoint")
    send.add_argument("--url", required=True)
    send.add_argument("--credentials-dir", type=Path, required=True)
    send.add_argument("--checkpoint", type=Path, required=True)
    send.add_argument("--lanes", type=int, choices=range(1, MAX_LANES + 1), default=2)
    send.add_argument("--repeat", type=int, default=3)
    send.add_argument(
        "--borrow-input",
        action="store_true",
        help="skip snapshot clones; caller must keep tensor storage immutable until completion",
    )

    args = parser.parse_args()
    if args.command == "recv":
        if not 4 <= args.max_workers <= 64:
            parser.error("--max-workers must be in [4, 64]")
        run_receiver(args)
    else:
        run_sender(args)


if __name__ == "__main__":
    main()
