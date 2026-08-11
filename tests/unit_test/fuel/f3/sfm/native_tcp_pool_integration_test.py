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
import time
from types import SimpleNamespace

from nvflare.fuel.f3.cellnet.defs import MessageHeaderKey
from nvflare.fuel.f3.comm_config import CommConfigurator
from nvflare.fuel.f3.drivers.connector_info import Mode
from nvflare.fuel.f3.drivers.driver_params import DriverParams
from nvflare.fuel.f3.drivers.socket_conn import SocketConnection
from nvflare.fuel.f3.endpoint import Endpoint, EndpointState
from nvflare.fuel.f3.sfm.conn_manager import ConnManager
from nvflare.fuel.f3.streaming.stream_const import STREAM_CHANNEL, STREAM_DATA_TOPIC


class _Receiver:
    def __init__(self):
        self.messages = []
        self.lock = threading.Lock()

    def process_message(self, _endpoint, connection, _app_id, message):
        with self.lock:
            self.messages.append((connection.name, message.headers, bytes(message.payload)))


def _wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _connector(handle, mode, driver):
    return SimpleNamespace(handle=handle, mode=mode, driver=driver, params={})


def test_native_pool_uses_control_lane_and_stripes_stream_data(monkeypatch):
    monkeypatch.setattr(CommConfigurator, "get_tcp_no_delay", lambda self, default: False)
    monkeypatch.setattr(CommConfigurator, "get_streaming_send_timeout", lambda self, default: 1.0)
    monkeypatch.setattr(CommConfigurator, "get_tcp_async_send", lambda self, default: True)
    monkeypatch.setattr(CommConfigurator, "get_tcp_send_queue_bytes", lambda self, default: 1024 * 1024)

    driver = SimpleNamespace(
        get_name=lambda: "native-tcp-test",
        get_max_connections_per_endpoint=lambda: 3,
    )
    active_connector = _connector("active", Mode.ACTIVE, driver)
    passive_connector = _connector("passive", Mode.PASSIVE, driver)
    sender = ConnManager(Endpoint("sender"))
    receiver = ConnManager(Endpoint("receiver"))
    capture = _Receiver()
    receiver.receivers[7] = capture
    connections = []
    readers = []

    try:
        pool_id = "integration-pool"
        for lane in range(3):
            active_socket, passive_socket = socket.socketpair()
            active = SocketConnection(active_socket, active_connector, secure=False)
            passive = SocketConnection(passive_socket, passive_connector, secure=False)
            active.conn_props[DriverParams.CONNECTION_LANE.value] = lane
            active.conn_props[DriverParams.CONNECTION_POOL_SIZE.value] = 3
            active.conn_props[DriverParams.CONNECTION_POOL_ID.value] = pool_id
            connections.extend((active, passive))

            receiver.handle_new_connection(passive)
            passive_reader = threading.Thread(target=passive.read_loop, daemon=True)
            passive_reader.start()
            readers.append(passive_reader)

            sender.handle_new_connection(active)
            active_reader = threading.Thread(target=active.read_loop, daemon=True)
            active_reader.start()
            readers.append(active_reader)

        assert _wait_for(
            lambda: sender.sfm_endpoints.get("receiver")
            and sender.sfm_endpoints["receiver"].endpoint.state == EndpointState.READY
            and receiver.sfm_endpoints.get("sender")
            and receiver.sfm_endpoints["sender"].endpoint.state == EndpointState.READY
        )

        sender.send_message(Endpoint("receiver"), 7, {"kind": "control"}, b"control")
        stream_headers = {
            MessageHeaderKey.CHANNEL: STREAM_CHANNEL,
            MessageHeaderKey.TOPIC: STREAM_DATA_TOPIC,
        }
        for index in range(6):
            sender.send_message(Endpoint("receiver"), 7, stream_headers, f"bulk-{index}".encode())

        assert _wait_for(lambda: len(capture.messages) == 7)
        receiver_lanes = {name: sfm_conn.lane for name, sfm_conn in receiver.sfm_conns.items()}
        control = next(message for message in capture.messages if message[2] == b"control")
        bulk = [message for message in capture.messages if message[2].startswith(b"bulk-")]

        assert receiver_lanes[control[0]] == 0
        assert {receiver_lanes[message[0]] for message in bulk} == {1, 2}
        assert sorted(message[2] for message in bulk) == [f"bulk-{index}".encode() for index in range(6)]
    finally:
        for connection in connections:
            connection.close()
        for reader in readers:
            reader.join(timeout=1.0)
        sender.conn_mgr_executor.shutdown(wait=True)
        sender.frame_mgr_executor.shutdown(wait=True)
        receiver.conn_mgr_executor.shutdown(wait=True)
        receiver.frame_mgr_executor.shutdown(wait=True)
