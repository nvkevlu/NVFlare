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

"""Bounded one-port native TLS bulk sessions used by negotiated tensor downloads."""

import logging
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from nvflare.fuel.f3.cellnet.identity import get_param, is_mtls_connection
from nvflare.fuel.f3.comm_error import CommError
from nvflare.fuel.f3.drivers.connector_info import ConnectorInfo, Mode
from nvflare.fuel.f3.drivers.driver_params import DriverParams
from nvflare.fuel.f3.drivers.net_utils import get_ssl_context, verify_hostname_required
from nvflare.fuel.hci.security import get_certificate_common_name
from nvflare.security.logging import secure_format_exception

log = logging.getLogger(__name__)

NATIVE_BULK_MAGIC = b"\xffNVFTB01"
NATIVE_BULK_VERSION = 1
NATIVE_BULK_PULL = 1
NATIVE_BULK_PUSH = 2
NATIVE_BULK_PREFACE = struct.Struct("!8sBB16sHHQ")
MAX_NATIVE_BULK_LANES = 4
DEFAULT_NATIVE_BULK_LANES = 3
DEFAULT_NATIVE_BULK_MAX_BYTES = 32 * 1024 * 1024 * 1024
MAX_NATIVE_BULK_BYTES = 64 * 1024 * 1024 * 1024
DEFAULT_NATIVE_BULK_MAX_SESSIONS = 2
DEFAULT_NATIVE_BULK_TIMEOUT = 300.0


def _byte_view(value) -> memoryview:
    view = value if isinstance(value, memoryview) else memoryview(value)
    if not view.c_contiguous:
        raise ValueError("native bulk buffers must be C-contiguous")
    if view.ndim != 1 or view.format != "B":
        view = view.cast("B")
    return view


def _recv_exact(sock, size: int) -> bytes:
    result = bytearray(size)
    view = memoryview(result)
    offset = 0
    while offset < size:
        count = sock.recv_into(view[offset:])
        if count == 0:
            raise CommError(CommError.CLOSED, f"native bulk peer closed after {offset} of {size} bytes")
        offset += count
    return bytes(result)


def _recv_into(sock, target: memoryview):
    offset = 0
    while offset < len(target):
        count = sock.recv_into(target[offset:])
        if count == 0:
            raise CommError(
                CommError.CLOSED,
                f"native bulk peer closed with {len(target) - offset} bytes remaining",
            )
        offset += count


def _send_all(sock, data):
    view = _byte_view(data)
    offset = 0
    while offset < len(view):
        count = sock.send(view[offset:])
        if count <= 0:
            raise CommError(CommError.CLOSED, "native bulk socket send returned zero")
        offset += count


@dataclass(frozen=True)
class NativeBulkSendSegment:
    lane: int
    size: int
    provider: Callable

    def __init__(self, lane: int, data=None, *, size: int = None, provider: Callable = None):
        if data is not None:
            if provider is not None or size is not None:
                raise ValueError("native bulk segment accepts data or size/provider, not both")
            view = _byte_view(data)
            size = len(view)

            def provider():
                return data, _byte_view(data)

        if type(size) is not int or size <= 0 or not callable(provider):
            raise ValueError("native bulk segment requires positive size and a provider")
        object.__setattr__(self, "lane", lane)
        object.__setattr__(self, "size", size)
        object.__setattr__(self, "provider", provider)

    def acquire(self):
        owner, data = self.provider()
        view = _byte_view(data)
        if len(view) != self.size:
            raise ValueError(f"native bulk provider returned {len(view)} bytes, expected {self.size}")
        return owner, view


@dataclass(frozen=True)
class NativeBulkReceiveSegment:
    lane: int
    target: memoryview

    def __init__(self, lane: int, target):
        view = _byte_view(target)
        if view.readonly:
            raise ValueError("native bulk receive buffers must be writable")
        if not view:
            raise ValueError("native bulk receive buffers must not be empty")
        object.__setattr__(self, "lane", lane)
        object.__setattr__(self, "target", view)


class _SendSession:
    def __init__(self, token: bytes, peer_cn: str, lanes: int, segments: list[NativeBulkSendSegment], timeout: float):
        self.token = token
        self.peer_cn = peer_cn
        self.lanes = lanes
        self.segments = segments
        self.timeout = timeout
        self.created_at = time.monotonic()
        self.lock = threading.Lock()
        self.start_event = threading.Event()
        self.done_event = threading.Event()
        self.active_lanes = set()
        self.done_lanes = set()
        self.error: Optional[str] = None
        self.completed = False

    @property
    def total_bytes(self):
        return sum(segment.size for segment in self.segments)

    def lane_segments(self, lane: int):
        return [segment for segment in self.segments if segment.lane == lane]

    def register_lane(self, lane: int, declared_bytes: int):
        expected = sum(segment.size for segment in self.lane_segments(lane))
        if declared_bytes != expected:
            raise ValueError(f"native bulk lane {lane} declares {declared_bytes} bytes but expected {expected}")
        with self.lock:
            if self.completed or self.error:
                raise ValueError("native bulk session is already terminal")
            if lane in self.active_lanes or lane in self.done_lanes:
                raise ValueError(f"duplicate native bulk lane {lane}")
            self.active_lanes.add(lane)

    def start(self):
        with self.lock:
            if self.active_lanes != set(range(self.lanes)):
                raise ValueError(f"native bulk session has {len(self.active_lanes)} of {self.lanes} lanes")
            self.start_event.set()

    def finish_lane(self, lane: int):
        with self.lock:
            self.active_lanes.discard(lane)
            self.done_lanes.add(lane)
            if self.done_lanes == set(range(self.lanes)):
                self.completed = True
                self.done_event.set()

    def fail(self, error: BaseException):
        with self.lock:
            if not self.completed and self.error is None:
                self.error = f"{type(error).__name__}: {error}"
            self.start_event.set()
            self.done_event.set()

    def expired(self, now: float) -> bool:
        return now - self.created_at > self.timeout


class _ReceiveSession:
    def __init__(
        self,
        token: bytes,
        peer_cn: str,
        lanes: int,
        segments: list[NativeBulkReceiveSegment],
        timeout: float,
    ):
        self.token = token
        self.peer_cn = peer_cn
        self.lanes = lanes
        self.segments = segments
        self.timeout = timeout
        self.created_at = time.monotonic()
        self.lock = threading.Lock()
        self.start_event = threading.Event()
        self.done_event = threading.Event()
        self.active_lanes = set()
        self.done_lanes = set()
        self.error: Optional[str] = None
        self.completed = False

    @property
    def total_bytes(self):
        return sum(len(segment.target) for segment in self.segments)

    def lane_segments(self, lane: int):
        return [segment for segment in self.segments if segment.lane == lane]

    def register_lane(self, lane: int, declared_bytes: int):
        expected = sum(len(segment.target) for segment in self.lane_segments(lane))
        if declared_bytes != expected:
            raise ValueError(f"native bulk lane {lane} declares {declared_bytes} bytes but expected {expected}")
        with self.lock:
            if self.completed or self.error:
                raise ValueError("native bulk session is already terminal")
            if lane in self.active_lanes or lane in self.done_lanes:
                raise ValueError(f"duplicate native bulk lane {lane}")
            self.active_lanes.add(lane)

    def start(self):
        with self.lock:
            if self.active_lanes != set(range(self.lanes)):
                raise ValueError(f"native bulk session has {len(self.active_lanes)} of {self.lanes} lanes")
            self.start_event.set()

    def finish_lane(self, lane: int):
        with self.lock:
            self.active_lanes.discard(lane)
            self.done_lanes.add(lane)
            if self.done_lanes == set(range(self.lanes)):
                self.completed = True
                self.done_event.set()

    def fail(self, error: BaseException):
        with self.lock:
            if not self.completed and self.error is None:
                self.error = f"{type(error).__name__}: {error}"
            self.start_event.set()
            self.done_event.set()

    def expired(self, now: float) -> bool:
        return now - self.created_at > self.timeout


class NativeBulkManager:
    """Own short-lived send sessions and receive matching bulk lanes."""

    def __init__(self, enabled: bool, lanes: int, max_bytes: int, max_sessions: int, timeout: float):
        if type(enabled) is not bool:
            raise CommError(CommError.BAD_CONFIG, f"tcp_tensor_bulk_enabled must be a bool, got {enabled!r}")
        if type(lanes) is not int or not 1 <= lanes <= MAX_NATIVE_BULK_LANES:
            raise CommError(
                CommError.BAD_CONFIG,
                f"tcp_tensor_bulk_lanes must be in [1, {MAX_NATIVE_BULK_LANES}], got {lanes!r}",
            )
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_NATIVE_BULK_BYTES:
            raise CommError(
                CommError.BAD_CONFIG,
                f"tcp_tensor_bulk_max_bytes must be in [1, {MAX_NATIVE_BULK_BYTES}], got {max_bytes!r}",
            )
        if type(max_sessions) is not int or not 1 <= max_sessions <= 16:
            raise CommError(
                CommError.BAD_CONFIG, f"tcp_tensor_bulk_max_sessions must be in [1, 16], got {max_sessions!r}"
            )
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1.0 <= timeout <= 3600.0:
            raise CommError(CommError.BAD_CONFIG, f"tcp_tensor_bulk_timeout must be in [1, 3600], got {timeout!r}")
        self.enabled = enabled
        self.lanes = lanes
        self.max_bytes = max_bytes
        self.max_sessions = max_sessions
        self.timeout = float(timeout)
        self.lock = threading.Lock()
        self.sessions: dict[bytes, object] = {}
        self.connection_slots = threading.BoundedSemaphore(max_sessions * lanes)

    def _expire_locked(self):
        now = time.monotonic()
        expired = [token for token, session in self.sessions.items() if session.expired(now)]
        for token in expired:
            session = self.sessions.pop(token)
            session.fail(TimeoutError("native bulk session expired"))

    def register_send(self, peer_cn: str, lanes: int, segments: Iterable[NativeBulkSendSegment]) -> str:
        if not self.enabled:
            raise CommError(CommError.NOT_SUPPORTED, "native tensor bulk is disabled")
        if not isinstance(peer_cn, str) or not peer_cn or peer_cn == "N/A":
            raise CommError(CommError.BAD_CONFIG, "native tensor bulk requires an authenticated peer identity")
        if type(lanes) is not int or not 1 <= lanes <= self.lanes:
            raise CommError(CommError.BAD_CONFIG, f"native bulk lanes must be in [1, {self.lanes}], got {lanes!r}")
        normalized = [
            segment if isinstance(segment, NativeBulkSendSegment) else NativeBulkSendSegment(*segment)
            for segment in segments
        ]
        if not normalized:
            raise ValueError("native bulk session requires at least one segment")
        if any(type(segment.lane) is not int or not 0 <= segment.lane < lanes for segment in normalized):
            raise ValueError("native bulk segment has an invalid lane")
        if set(segment.lane for segment in normalized) != set(range(lanes)):
            raise ValueError("every native bulk lane must have at least one segment")
        total_bytes = sum(segment.size for segment in normalized)
        if not 1 <= total_bytes <= self.max_bytes:
            raise ValueError(f"native bulk size {total_bytes} exceeds limit {self.max_bytes}")

        token = uuid.uuid4().bytes
        session = _SendSession(token, peer_cn, lanes, normalized, self.timeout)
        with self.lock:
            self._expire_locked()
            if len(self.sessions) >= self.max_sessions:
                raise CommError(CommError.NOT_READY, "native bulk session limit reached")
            self.sessions[token] = session
        return token.hex()

    def register_receive(
        self,
        peer_cn: str,
        lanes: int,
        segments: Iterable[NativeBulkReceiveSegment],
        token_hex: Optional[str] = None,
    ) -> str:
        if not self.enabled:
            raise CommError(CommError.NOT_SUPPORTED, "native tensor bulk is disabled")
        if not isinstance(peer_cn, str) or not peer_cn or peer_cn == "N/A":
            raise CommError(CommError.BAD_CONFIG, "native tensor bulk requires an authenticated peer identity")
        if type(lanes) is not int or not 1 <= lanes <= self.lanes:
            raise CommError(CommError.BAD_CONFIG, f"native bulk lanes must be in [1, {self.lanes}], got {lanes!r}")
        normalized = [
            segment if isinstance(segment, NativeBulkReceiveSegment) else NativeBulkReceiveSegment(*segment)
            for segment in segments
        ]
        if not normalized or set(segment.lane for segment in normalized) != set(range(lanes)):
            raise ValueError("native bulk receive segments must cover every lane")
        total_bytes = sum(len(segment.target) for segment in normalized)
        if not 1 <= total_bytes <= self.max_bytes:
            raise ValueError(f"native bulk receive size {total_bytes} exceeds limit {self.max_bytes}")
        token = self._parse_token(token_hex) if token_hex is not None else uuid.uuid4().bytes
        session = _ReceiveSession(token, peer_cn, lanes, normalized, self.timeout)
        with self.lock:
            self._expire_locked()
            if len(self.sessions) >= self.max_sessions:
                raise CommError(CommError.NOT_READY, "native bulk session limit reached")
            if token in self.sessions:
                raise ValueError("native bulk token is already registered")
            self.sessions[token] = session
        return token.hex()

    @staticmethod
    def new_token() -> str:
        return uuid.uuid4().hex

    def cancel(self, token_hex: str):
        try:
            token = bytes.fromhex(token_hex)
        except (TypeError, ValueError):
            return
        with self.lock:
            session = self.sessions.pop(token, None)
        if session:
            session.fail(RuntimeError("native bulk session cancelled"))

    def status(self, token_hex: str, peer_cn: str) -> tuple[bool, Optional[str]]:
        token = self._parse_token(token_hex)
        with self.lock:
            self._expire_locked()
            session = self.sessions.get(token)
        if not session or session.peer_cn != peer_cn:
            return False, "unknown native bulk session"
        return session.completed, session.error

    def wait_completed(
        self, token_hex: str, peer_cn: str, timeout: Optional[float] = None
    ) -> tuple[bool, Optional[str]]:
        token = self._parse_token(token_hex)
        with self.lock:
            self._expire_locked()
            session = self.sessions.get(token)
        if not session or session.peer_cn != peer_cn:
            return False, "unknown native bulk session"
        session.done_event.wait(self.timeout if timeout is None else timeout)
        return session.completed, session.error

    def pop_completed(self, token_hex: str, peer_cn: str) -> bool:
        token = self._parse_token(token_hex)
        with self.lock:
            session = self.sessions.get(token)
            if not session or session.peer_cn != peer_cn or not session.completed:
                return False
            self.sessions.pop(token, None)
        return True

    @staticmethod
    def _parse_token(token_hex: str) -> bytes:
        if not isinstance(token_hex, str) or len(token_hex) != 32:
            raise ValueError("invalid native bulk token")
        try:
            token = bytes.fromhex(token_hex)
        except ValueError as ex:
            raise ValueError("invalid native bulk token") from ex
        if len(token) != 16:
            raise ValueError("invalid native bulk token")
        return token

    def handle_connection(self, sock, peer_cn: str, first_magic: bytes):
        if not self.enabled:
            raise CommError(CommError.NOT_SUPPORTED, "native tensor bulk is disabled")
        if not self.connection_slots.acquire(blocking=False):
            raise CommError(CommError.NOT_READY, "native tensor bulk connection limit reached")
        try:
            self._handle_connection(sock, peer_cn, first_magic)
        finally:
            self.connection_slots.release()

    def _handle_connection(self, sock, peer_cn: str, first_magic: bytes):
        if first_magic != NATIVE_BULK_MAGIC:
            raise ValueError("invalid native bulk magic")
        rest = _recv_exact(sock, NATIVE_BULK_PREFACE.size - len(first_magic))
        magic, version, direction, token, lane, lanes, declared_bytes = NATIVE_BULK_PREFACE.unpack(first_magic + rest)
        if magic != NATIVE_BULK_MAGIC or version != NATIVE_BULK_VERSION:
            raise ValueError("unsupported native bulk protocol")
        with self.lock:
            self._expire_locked()
            session = self.sessions.get(token)
        if not session:
            raise ValueError("unknown native bulk token")
        if peer_cn != session.peer_cn:
            raise ValueError("native bulk peer identity does not match the control session")
        if lanes != session.lanes or not 0 <= lane < lanes:
            raise ValueError("invalid native bulk lane preface")

        if direction == NATIVE_BULK_PULL and not isinstance(session, _SendSession):
            raise ValueError("native bulk token is not a pull session")
        if direction == NATIVE_BULK_PUSH and not isinstance(session, _ReceiveSession):
            raise ValueError("native bulk token is not a push session")
        if direction not in (NATIVE_BULK_PULL, NATIVE_BULK_PUSH):
            raise ValueError("invalid native bulk direction")

        try:
            session.register_lane(lane, declared_bytes)
            sock.sendall(b"R")
            if lane == 0:
                if _recv_exact(sock, 1) != b"S":
                    raise ValueError("native bulk control lane did not send start")
                session.start()
            elif not session.start_event.wait(session.timeout):
                raise TimeoutError("native bulk lane timed out waiting for start")
            if session.error:
                raise RuntimeError(session.error)
            if direction == NATIVE_BULK_PULL:
                for segment in session.lane_segments(lane):
                    owner, data = segment.acquire()
                    try:
                        _send_all(sock, data)
                    finally:
                        del data
                        del owner
            else:
                for segment in session.lane_segments(lane):
                    _recv_into(sock, segment.target)
            if _recv_exact(sock, 1) != b"D":
                raise ValueError("native bulk lane did not acknowledge completion")
            sock.sendall(b"D")
            session.finish_lane(lane)
        except BaseException as ex:
            session.fail(ex)
            raise

    def pull(
        self,
        connector: ConnectorInfo,
        token_hex: str,
        lanes: int,
        segments: Iterable[NativeBulkReceiveSegment],
    ):
        if not self.enabled:
            raise CommError(CommError.NOT_SUPPORTED, "native tensor bulk is disabled")
        if connector.mode != Mode.ACTIVE:
            raise CommError(CommError.NOT_SUPPORTED, "native bulk lanes must be client-initiated")
        self._validate_active_connector(connector)
        token = self._parse_token(token_hex)
        if type(lanes) is not int or not 1 <= lanes <= self.lanes:
            raise ValueError(f"native bulk lanes must be in [1, {self.lanes}]")
        normalized = [
            segment if isinstance(segment, NativeBulkReceiveSegment) else NativeBulkReceiveSegment(*segment)
            for segment in segments
        ]
        if not normalized or set(segment.lane for segment in normalized) != set(range(lanes)):
            raise ValueError("native bulk receive segments must cover every lane")
        total_bytes = sum(len(segment.target) for segment in normalized)
        if total_bytes > self.max_bytes:
            raise ValueError(f"native bulk receive size {total_bytes} exceeds limit {self.max_bytes}")

        sockets = []
        errors = []
        threads = []
        start_event = threading.Event()

        def abort_siblings():
            for open_sock, _, _ in sockets:
                try:
                    open_sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        try:
            for lane in range(lanes):
                lane_segments = [segment for segment in normalized if segment.lane == lane]
                lane_bytes = sum(len(segment.target) for segment in lane_segments)
                sock = self._connect_socket(connector)
                sock.sendall(
                    NATIVE_BULK_PREFACE.pack(
                        NATIVE_BULK_MAGIC,
                        NATIVE_BULK_VERSION,
                        NATIVE_BULK_PULL,
                        token,
                        lane,
                        lanes,
                        lane_bytes,
                    )
                )
                if _recv_exact(sock, 1) != b"R":
                    raise CommError(CommError.ERROR, f"native bulk lane {lane} was not accepted")
                sockets.append((sock, lane, lane_segments))

            def receive_lane(sock, lane_segments):
                try:
                    start_event.wait()
                    for segment in lane_segments:
                        _recv_into(sock, segment.target)
                    sock.sendall(b"D")
                    if _recv_exact(sock, 1) != b"D":
                        raise ValueError("invalid native bulk lane completion")
                except BaseException as ex:
                    errors.append(ex)
                    abort_siblings()

            for sock, lane, lane_segments in sockets:
                thread = threading.Thread(
                    target=receive_lane,
                    args=(sock, lane_segments),
                    name=f"native_bulk_receive_{lane}",
                    daemon=True,
                )
                thread.start()
                threads.append(thread)

            sockets[0][0].sendall(b"S")
            start_event.set()
            deadline = time.monotonic() + self.timeout
            for thread in threads:
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
            if any(thread.is_alive() for thread in threads):
                raise CommError(CommError.TIMEOUT, "native bulk receive timed out")
            if errors:
                raise errors[0]
        finally:
            start_event.set()
            for sock, _, _ in sockets:
                try:
                    sock.close()
                except OSError:
                    pass

    def push(
        self,
        connector: ConnectorInfo,
        token_hex: str,
        lanes: int,
        segments: Iterable[NativeBulkSendSegment],
    ):
        if not self.enabled:
            raise CommError(CommError.NOT_SUPPORTED, "native tensor bulk is disabled")
        if connector.mode != Mode.ACTIVE:
            raise CommError(CommError.NOT_SUPPORTED, "native bulk lanes must be client-initiated")
        self._validate_active_connector(connector)
        token = self._parse_token(token_hex)
        if type(lanes) is not int or not 1 <= lanes <= self.lanes:
            raise ValueError(f"native bulk lanes must be in [1, {self.lanes}]")
        normalized = [
            segment if isinstance(segment, NativeBulkSendSegment) else NativeBulkSendSegment(*segment)
            for segment in segments
        ]
        if not normalized or set(segment.lane for segment in normalized) != set(range(lanes)):
            raise ValueError("native bulk send segments must cover every lane")
        total_bytes = sum(segment.size for segment in normalized)
        if total_bytes > self.max_bytes:
            raise ValueError(f"native bulk send size {total_bytes} exceeds limit {self.max_bytes}")

        sockets = []
        threads = []
        errors = []
        start_event = threading.Event()

        def abort_siblings():
            for open_sock, _, _ in sockets:
                try:
                    open_sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

        try:
            for lane in range(lanes):
                lane_segments = [segment for segment in normalized if segment.lane == lane]
                lane_bytes = sum(segment.size for segment in lane_segments)
                sock = self._connect_socket(connector)
                sock.sendall(
                    NATIVE_BULK_PREFACE.pack(
                        NATIVE_BULK_MAGIC,
                        NATIVE_BULK_VERSION,
                        NATIVE_BULK_PUSH,
                        token,
                        lane,
                        lanes,
                        lane_bytes,
                    )
                )
                if _recv_exact(sock, 1) != b"R":
                    raise CommError(CommError.ERROR, f"native bulk lane {lane} was not accepted")
                sockets.append((sock, lane, lane_segments))

            def send_lane(sock, lane_segments):
                try:
                    start_event.wait()
                    for segment in lane_segments:
                        owner, data = segment.acquire()
                        try:
                            _send_all(sock, data)
                        finally:
                            del data
                            del owner
                    sock.sendall(b"D")
                    if _recv_exact(sock, 1) != b"D":
                        raise ValueError("invalid native bulk lane completion")
                except BaseException as ex:
                    errors.append(ex)
                    abort_siblings()

            for sock, lane, lane_segments in sockets:
                thread = threading.Thread(
                    target=send_lane,
                    args=(sock, lane_segments),
                    name=f"native_bulk_send_{lane}",
                    daemon=True,
                )
                thread.start()
                threads.append(thread)
            sockets[0][0].sendall(b"S")
            start_event.set()
            deadline = time.monotonic() + self.timeout
            for thread in threads:
                thread.join(timeout=max(0.0, deadline - time.monotonic()))
            if any(thread.is_alive() for thread in threads):
                raise CommError(CommError.TIMEOUT, "native bulk send timed out")
            if errors:
                raise errors[0]
        finally:
            start_event.set()
            for sock, _, _ in sockets:
                try:
                    sock.close()
                except OSError:
                    pass

    def _connect_socket(self, connector: ConnectorInfo):
        params = connector.params
        host = get_param(params, DriverParams.HOST)
        port = int(get_param(params, DriverParams.PORT))
        context = get_ssl_context(params, ssl_server=False)
        if context is None or not context.check_hostname:
            raise CommError(CommError.BAD_CONFIG, "native tensor bulk requires verified TLS")
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.settimeout(min(self.timeout, 15.0))
        try:
            sock = context.wrap_socket(raw, server_hostname=host)
            sock.connect((host, port))
            sock.settimeout(self.timeout)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return sock
        except BaseException:
            raw.close()
            raise

    @staticmethod
    def can_use_connector(connector: ConnectorInfo) -> bool:
        if not connector or not is_mtls_connection(connector.params) or not verify_hostname_required(connector.params):
            return False
        return True

    @staticmethod
    def _validate_active_connector(connector: ConnectorInfo):
        if connector.mode != Mode.ACTIVE:
            raise CommError(CommError.NOT_SUPPORTED, "native bulk lanes must be client-initiated")
        if not is_mtls_connection(connector.params):
            raise CommError(CommError.BAD_CONFIG, "native tensor bulk requires mTLS")
        if not verify_hostname_required(connector.params):
            raise CommError(CommError.BAD_CONFIG, "native tensor bulk requires TLS hostname verification")

    def shutdown(self):
        with self.lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            session.fail(RuntimeError("native bulk manager stopped"))


class PrefixedSocket:
    """Replay bytes consumed while classifying a socket as ordinary SFM traffic."""

    def __init__(self, sock, prefix: bytes):
        self.sock = sock
        self.prefix = memoryview(bytes(prefix))

    def recv_into(self, buffer, nbytes=0, flags=0):
        target = _byte_view(buffer)
        limit = len(target) if not nbytes else min(len(target), nbytes)
        if self.prefix:
            count = min(limit, len(self.prefix))
            target[:count] = self.prefix[:count]
            self.prefix = self.prefix[count:]
            return count
        return self.sock.recv_into(buffer, nbytes, flags)

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def fileno(self):
        return self.sock.fileno()


def authenticated_peer_cn(sock) -> str:
    cert = sock.getpeercert()
    if not cert:
        return ""
    return get_certificate_common_name(cert) or ""


def log_bulk_connection_error(ex: BaseException):
    log.warning(f"Rejected native bulk connection: {secure_format_exception(ex)}")
