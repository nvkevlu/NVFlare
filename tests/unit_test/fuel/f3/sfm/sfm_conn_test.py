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

from types import SimpleNamespace

import msgpack
import pytest

from nvflare.fuel.f3.cellnet.defs import MessageHeaderKey
from nvflare.fuel.f3.endpoint import Endpoint, EndpointState
from nvflare.fuel.f3.sfm.constants import HandshakeKeys, Types
from nvflare.fuel.f3.sfm.prefix import PREFIX_LEN, Prefix
from nvflare.fuel.f3.sfm.sfm_conn import SfmConnection
from nvflare.fuel.f3.streaming.stream_const import STREAM_CHANNEL, STREAM_DATA_TOPIC


class _CaptureConnection:
    def __init__(self):
        self.frame = None
        self.name = "capture"

    def send_frame(self, frame):
        self.frame = frame

    def __str__(self):
        return self.name


@pytest.mark.parametrize(
    "payload",
    [
        b"payload",
        bytearray(b"payload"),
        memoryview(b"payload"),
        memoryview(b"p-a-y-l-o-a-d")[::2],
    ],
)
def test_send_data_builds_one_immutable_exact_frame(payload):
    conn = _CaptureConnection()
    sfm_conn = SfmConnection(conn=conn, local_endpoint=Endpoint("local"))

    sfm_conn.send_data(app_id=7, stream_id=11, headers={"key": "value"}, payload=payload)

    frame = conn.frame
    assert isinstance(frame, bytes)
    prefix = Prefix.from_bytes(frame)
    assert prefix.type == Types.DATA
    assert prefix.app_id == 7
    assert prefix.stream_id == 11
    assert prefix.length == len(frame)

    header_end = PREFIX_LEN + prefix.header_len
    assert msgpack.unpackb(frame[PREFIX_LEN:header_end]) == {"key": "value"}
    assert frame[header_end:] == b"payload"


def test_send_data_snapshots_mutable_payload():
    payload = bytearray(b"before")
    conn = _CaptureConnection()
    sfm_conn = SfmConnection(conn=conn, local_endpoint=Endpoint("local"))

    sfm_conn.send_data(app_id=7, stream_id=11, headers=None, payload=payload)
    payload[:] = b"after!"

    assert conn.frame[PREFIX_LEN:] == b"before"


def test_send_data_normalizes_multibyte_memoryview_size():
    payload = memoryview(bytearray(b"abcdefgh")).cast("I")
    conn = _CaptureConnection()
    sfm_conn = SfmConnection(conn=conn, local_endpoint=Endpoint("local"))

    sfm_conn.send_data(app_id=7, stream_id=11, headers=None, payload=payload)

    prefix = Prefix.from_bytes(conn.frame)
    assert prefix.length == PREFIX_LEN + payload.nbytes
    assert conn.frame[PREFIX_LEN:] == payload.cast("B").tobytes()


def test_send_data_assembles_mixed_buffer_list_once():
    payload = [
        b"one",
        bytearray(b"two"),
        memoryview(b"three"),
        memoryview(b"f-o-u-r")[::2],
        b"",
    ]
    conn = _CaptureConnection()
    sfm_conn = SfmConnection(conn=conn, local_endpoint=Endpoint("local"))

    sfm_conn.send_data(app_id=7, stream_id=11, headers=None, payload=payload)

    prefix = Prefix.from_bytes(conn.frame)
    assert prefix.length == len(conn.frame)
    assert conn.frame[PREFIX_LEN:] == b"onetwothreefour"


def test_send_data_rejects_invalid_buffer_list_member():
    conn = _CaptureConnection()
    sfm_conn = SfmConnection(conn=conn, local_endpoint=Endpoint("local"))

    with pytest.raises(TypeError, match="payload item must be bytes-like"):
        sfm_conn.send_data(app_id=7, stream_id=11, headers=None, payload=[b"valid", object()])

    assert conn.frame is None


def test_handshake_carries_native_connection_lane_and_pool_size():
    conn = _CaptureConnection()
    sfm_conn = SfmConnection(
        conn=conn,
        local_endpoint=Endpoint(
            "local",
            {
                HandshakeKeys.ENDPOINT_NAME: "spoofed",
                HandshakeKeys.CONNECTION_LANE: 99,
                HandshakeKeys.CONNECTION_POOL_SIZE: 100,
            },
        ),
    )
    sfm_conn.lane = 2
    sfm_conn.pool_size = 3
    sfm_conn.pool_id = "pool-generation"

    sfm_conn.send_handshake(Types.HELLO)

    prefix = Prefix.from_bytes(conn.frame)
    data = msgpack.unpackb(conn.frame[PREFIX_LEN : prefix.length])
    assert data[HandshakeKeys.ENDPOINT_NAME] == "local"
    assert data[HandshakeKeys.CONNECTION_LANE] == 2
    assert data[HandshakeKeys.CONNECTION_POOL_SIZE] == 3
    assert data[HandshakeKeys.CONNECTION_POOL_ID] == "pool-generation"


class _CaptureReceiver:
    def __init__(self):
        self.message = None

    def process_message(self, endpoint, connection, app_id, message):
        self.message = message


def test_remote_send_preserves_buffer_list_until_sfm():
    from nvflare.fuel.f3.sfm.conn_manager import ConnManager

    payload = [b"one", memoryview(b"two")]
    captured = {}
    sfm_conn = SimpleNamespace(
        conn=SimpleNamespace(connector=SimpleNamespace(driver=SimpleNamespace(get_name=lambda: "capture"))),
        send_data=lambda app_id, stream_id, headers, data: captured.update(
            app_id=app_id, stream_id=stream_id, headers=headers, payload=data
        ),
    )
    manager = ConnManager(Endpoint("local"))
    manager.sfm_endpoints["remote"] = SimpleNamespace(
        endpoint=SimpleNamespace(state=EndpointState.READY),
        next_stream_id=lambda: 11,
        get_connection=lambda stream_id, bulk=False: sfm_conn,
    )
    try:
        manager.send_message(Endpoint("remote"), 7, {"key": "value"}, payload)
    finally:
        manager.conn_mgr_executor.shutdown(wait=True)
        manager.frame_mgr_executor.shutdown(wait=True)

    assert captured == {"app_id": 7, "stream_id": 11, "headers": {"key": "value"}, "payload": payload}
    assert captured["payload"] is payload


@pytest.mark.parametrize(
    "headers,expected_bulk",
    [
        ({"key": "value"}, False),
        ({MessageHeaderKey.CHANNEL: STREAM_CHANNEL, MessageHeaderKey.TOPIC: STREAM_DATA_TOPIC}, True),
    ],
)
def test_remote_send_routes_only_stream_data_to_bulk_lanes(headers, expected_bulk):
    from nvflare.fuel.f3.sfm.conn_manager import ConnManager

    selections = []
    sfm_conn = SimpleNamespace(
        conn=SimpleNamespace(connector=SimpleNamespace(driver=SimpleNamespace(get_name=lambda: "capture"))),
        send_data=lambda *_args, **_kwargs: None,
    )
    manager = ConnManager(Endpoint("local"))
    manager.sfm_endpoints["remote"] = SimpleNamespace(
        endpoint=SimpleNamespace(state=EndpointState.READY),
        next_stream_id=lambda: 11,
        get_connection=lambda stream_id, bulk=False: selections.append((stream_id, bulk)) or sfm_conn,
    )
    try:
        manager.send_message(Endpoint("remote"), 7, headers, b"payload")
    finally:
        manager.conn_mgr_executor.shutdown(wait=True)
        manager.frame_mgr_executor.shutdown(wait=True)

    assert selections == [(11, expected_bulk)]


def test_loopback_send_keeps_flattened_payload_compatibility():
    from nvflare.fuel.f3.sfm.conn_manager import ConnManager

    payload = [b"one", memoryview(b"two")]
    captured = {}
    manager = ConnManager(Endpoint("local"))
    manager.send_loopback_message = lambda endpoint, app_id, headers, data: captured.update(
        endpoint=endpoint, app_id=app_id, headers=headers, payload=data
    )
    try:
        manager.send_message(Endpoint("local"), 7, {"key": "value"}, payload)
    finally:
        manager.conn_mgr_executor.shutdown(wait=True)
        manager.frame_mgr_executor.shutdown(wait=True)

    assert isinstance(captured["payload"], bytearray)
    assert captured["payload"] == b"onetwo"


def test_received_data_payload_is_bounded_view_with_owned_lifetime():
    from nvflare.fuel.f3.sfm.conn_manager import ConnManager

    sender = _CaptureConnection()
    sender_sfm = SfmConnection(conn=sender, local_endpoint=Endpoint("sender"))
    sender_sfm.send_data(
        app_id=7,
        stream_id=11,
        headers={MessageHeaderKey.CHANNEL: STREAM_CHANNEL, MessageHeaderKey.TOPIC: STREAM_DATA_TOPIC},
        payload=b"payload",
    )

    manager = ConnManager(Endpoint("receiver"))
    receiver = _CaptureReceiver()
    manager.receivers[7] = receiver
    incoming_sfm = SimpleNamespace(
        conn=SimpleNamespace(name="incoming"),
        sfm_endpoint=SimpleNamespace(endpoint=Endpoint("sender")),
        get_name=lambda: "incoming",
    )
    try:
        manager.process_frame_task(incoming_sfm, sender.frame)
    finally:
        manager.conn_mgr_executor.shutdown(wait=True)
        manager.frame_mgr_executor.shutdown(wait=True)

    payload = receiver.message.payload
    assert isinstance(payload, memoryview)
    assert payload.tobytes() == b"payload"
    del sender.frame
    assert payload.tobytes() == b"payload"


def test_received_generic_data_preserves_historical_payload_type():
    from nvflare.fuel.f3.sfm.conn_manager import ConnManager

    sender = _CaptureConnection()
    sender_sfm = SfmConnection(conn=sender, local_endpoint=Endpoint("sender"))
    sender_sfm.send_data(app_id=7, stream_id=11, headers={"key": "value"}, payload=b"payload")

    manager = ConnManager(Endpoint("receiver"))
    receiver = _CaptureReceiver()
    manager.receivers[7] = receiver
    incoming_sfm = SimpleNamespace(
        conn=SimpleNamespace(name="incoming"),
        sfm_endpoint=SimpleNamespace(endpoint=Endpoint("sender")),
        get_name=lambda: "incoming",
    )
    try:
        manager.process_frame_task(incoming_sfm, sender.frame)
    finally:
        manager.conn_mgr_executor.shutdown(wait=True)
        manager.frame_mgr_executor.shutdown(wait=True)

    assert isinstance(receiver.message.payload, bytes)
    assert receiver.message.payload == b"payload"


@pytest.mark.parametrize(
    "declared_length,header_length",
    [
        (PREFIX_LEN + 6, 0),
        (PREFIX_LEN + 8, 0),
        (PREFIX_LEN + 7, 8),
    ],
)
def test_received_data_rejects_invalid_frame_boundaries(declared_length, header_length):
    from nvflare.fuel.f3.sfm.conn_manager import ConnManager

    frame = bytearray(PREFIX_LEN + 7)
    Prefix(
        length=declared_length,
        header_len=header_length,
        type=Types.DATA,
        app_id=7,
        stream_id=11,
    ).to_buffer(frame, 0)
    frame[PREFIX_LEN:] = b"payload"

    manager = ConnManager(Endpoint("receiver"))
    receiver = _CaptureReceiver()
    manager.receivers[7] = receiver
    incoming_sfm = SimpleNamespace(
        conn=SimpleNamespace(name="incoming"),
        sfm_endpoint=SimpleNamespace(endpoint=Endpoint("sender")),
        get_name=lambda: "incoming",
    )
    try:
        manager.process_frame_task(incoming_sfm, frame)
    finally:
        manager.conn_mgr_executor.shutdown(wait=True)
        manager.frame_mgr_executor.shutdown(wait=True)

    assert receiver.message is None


def test_received_secure_stream_data_preserves_historical_payload_type():
    from nvflare.fuel.f3.sfm.conn_manager import ConnManager

    sender = _CaptureConnection()
    sender_sfm = SfmConnection(conn=sender, local_endpoint=Endpoint("sender"))
    sender_sfm.send_data(
        app_id=7,
        stream_id=11,
        headers={
            MessageHeaderKey.CHANNEL: STREAM_CHANNEL,
            MessageHeaderKey.TOPIC: STREAM_DATA_TOPIC,
            MessageHeaderKey.SECURE: True,
        },
        payload=b"payload",
    )

    manager = ConnManager(Endpoint("receiver"))
    receiver = _CaptureReceiver()
    manager.receivers[7] = receiver
    incoming_sfm = SimpleNamespace(
        conn=SimpleNamespace(name="incoming"),
        sfm_endpoint=SimpleNamespace(endpoint=Endpoint("sender")),
        get_name=lambda: "incoming",
    )
    try:
        manager.process_frame_task(incoming_sfm, sender.frame)
    finally:
        manager.conn_mgr_executor.shutdown(wait=True)
        manager.frame_mgr_executor.shutdown(wait=True)

    assert isinstance(receiver.message.payload, bytes)
    assert receiver.message.payload == b"payload"
