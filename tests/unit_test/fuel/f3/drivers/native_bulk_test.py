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

import socket
import threading

import pytest

from nvflare.fuel.f3.drivers.native_bulk import (
    NATIVE_BULK_MAGIC,
    NATIVE_BULK_PREFACE,
    NATIVE_BULK_PULL,
    NATIVE_BULK_PUSH,
    NATIVE_BULK_VERSION,
    NativeBulkManager,
    NativeBulkReceiveSegment,
    NativeBulkSendSegment,
    PrefixedSocket,
    _recv_exact,
)


def _manager(lanes=3, max_bytes=1024 * 1024):
    return NativeBulkManager(enabled=True, lanes=lanes, max_bytes=max_bytes, max_sessions=2, timeout=5.0)


def test_native_bulk_pull_transfers_each_lane_and_binds_peer_identity():
    manager = _manager(lanes=2)
    token_hex = manager.register_send(
        "receiver",
        2,
        [
            NativeBulkSendSegment(0, b"lane-zero"),
            NativeBulkSendSegment(1, b"lane-one"),
        ],
    )
    token = bytes.fromhex(token_hex)
    pairs = [socket.socketpair() for _ in range(2)]
    server_errors = []

    def serve(sock, lane):
        try:
            first = _recv_exact(sock, len(NATIVE_BULK_MAGIC))
            manager.handle_connection(sock, "receiver", first)
        except BaseException as ex:
            server_errors.append(ex)
        finally:
            sock.close()

    threads = []
    for lane, (server_sock, client_sock) in enumerate(pairs):
        thread = threading.Thread(target=serve, args=(server_sock, lane))
        thread.start()
        threads.append(thread)
        expected = len(b"lane-zero" if lane == 0 else b"lane-one")
        client_sock.sendall(
            NATIVE_BULK_PREFACE.pack(
                NATIVE_BULK_MAGIC,
                NATIVE_BULK_VERSION,
                NATIVE_BULK_PULL,
                token,
                lane,
                2,
                expected,
            )
        )
        assert _recv_exact(client_sock, 1) == b"R"

    pairs[0][1].sendall(b"S")
    received = []
    for lane, (_, client_sock) in enumerate(pairs):
        expected = b"lane-zero" if lane == 0 else b"lane-one"
        received.append(_recv_exact(client_sock, len(expected)))
        client_sock.sendall(b"D")
        assert _recv_exact(client_sock, 1) == b"D"
        client_sock.close()
    for thread in threads:
        thread.join(timeout=2.0)

    assert received == [b"lane-zero", b"lane-one"]
    assert not server_errors
    assert manager.status(token_hex, "attacker") == (False, "unknown native bulk session")
    assert manager.status(token_hex, "receiver") == (True, None)
    assert manager.pop_completed(token_hex, "receiver") is True


def test_native_bulk_bounds_and_writable_targets_are_enforced():
    manager = _manager(lanes=2, max_bytes=8)
    with pytest.raises(ValueError, match="every native bulk lane"):
        manager.register_send("peer", 2, [NativeBulkSendSegment(0, b"a")])
    with pytest.raises(ValueError, match="exceeds limit"):
        manager.register_send("peer", 1, [NativeBulkSendSegment(0, b"123456789")])
    with pytest.raises(ValueError, match="writable"):
        NativeBulkReceiveSegment(0, b"readonly")
    with pytest.raises(ValueError, match="must not be empty"):
        NativeBulkReceiveSegment(0, bytearray())


def test_native_bulk_connection_admission_is_bounded():
    manager = NativeBulkManager(enabled=True, lanes=2, max_bytes=1024, max_sessions=2, timeout=5.0)

    assert [manager.connection_slots.acquire(blocking=False) for _ in range(4)] == [True] * 4
    assert manager.connection_slots.acquire(blocking=False) is False
    for _ in range(4):
        manager.connection_slots.release()


def test_native_bulk_push_receives_each_lane_into_registered_targets():
    manager = _manager(lanes=2)
    targets = [bytearray(len(b"lane-zero")), bytearray(len(b"lane-one"))]
    token_hex = manager.register_receive(
        "sender",
        2,
        [NativeBulkReceiveSegment(0, targets[0]), NativeBulkReceiveSegment(1, targets[1])],
    )
    token = bytes.fromhex(token_hex)
    pairs = [socket.socketpair() for _ in range(2)]
    server_errors = []

    def serve(sock):
        try:
            manager.handle_connection(sock, "sender", _recv_exact(sock, len(NATIVE_BULK_MAGIC)))
        except BaseException as ex:
            server_errors.append(ex)
        finally:
            sock.close()

    threads = []
    for lane, (server_sock, client_sock) in enumerate(pairs):
        thread = threading.Thread(target=serve, args=(server_sock,))
        thread.start()
        threads.append(thread)
        payload = b"lane-zero" if lane == 0 else b"lane-one"
        client_sock.sendall(
            NATIVE_BULK_PREFACE.pack(
                NATIVE_BULK_MAGIC,
                NATIVE_BULK_VERSION,
                NATIVE_BULK_PUSH,
                token,
                lane,
                2,
                len(payload),
            )
        )
        assert _recv_exact(client_sock, 1) == b"R"

    pairs[0][1].sendall(b"S")
    for lane, (_, client_sock) in enumerate(pairs):
        client_sock.sendall(b"lane-zero" if lane == 0 else b"lane-one")
        client_sock.sendall(b"D")
        assert _recv_exact(client_sock, 1) == b"D"
        client_sock.close()
    for thread in threads:
        thread.join(timeout=2.0)

    assert not server_errors
    assert targets == [bytearray(b"lane-zero"), bytearray(b"lane-one")]
    assert manager.status(token_hex, "sender") == (True, None)


def test_prefixed_socket_replays_classifier_bytes_before_socket_data():
    server_sock, client_sock = socket.socketpair()
    try:
        client_sock.sendall(b"tail")
        wrapped = PrefixedSocket(server_sock, b"head")
        target = bytearray(8)
        assert wrapped.recv_into(memoryview(target)[:4]) == 4
        assert wrapped.recv_into(memoryview(target)[4:]) == 4
        assert bytes(target) == b"headtail"
    finally:
        server_sock.close()
        client_sock.close()
