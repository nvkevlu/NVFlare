# Copyright (c) 2023, NVIDIA CORPORATION.  All rights reserved.
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

import multiprocessing as mp
import threading
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

from nvflare.fuel.f3.cellnet.core_cell import CoreCell
from nvflare.fuel.f3.cellnet.defs import Encoding
from nvflare.fuel.f3.message import Message
from nvflare.fuel.f3.stream_cell import StreamCell
from nvflare.fuel.f3.streaming.stream_const import StreamHeaderKey
from nvflare.fuel.f3.streaming.stream_types import StreamFuture
from nvflare.fuel.f3.streaming.tools.utils import TEST_CHANNEL, TEST_TOPIC, make_buffer

_STREAM_RX_CELL = "stream_test_server"
_STREAM_TX_CELL = "stream_test_sender"
from nvflare.fuel.utils.network_utils import get_open_ports

WAIT_SEC = 10


class State:
    def __init__(self):
        self.done = threading.Event()
        self.result = None


def _run_segmented_blob_server(port, ready, done, result_queue):
    cell = CoreCell("server", f"tcp://localhost:{port}", secure=False, credentials={})
    stream_cell = StreamCell(cell)

    def receive_blob(future: StreamFuture):
        try:
            result_queue.put(("ok", bytes(future.result())))
        except Exception as ex:
            result_queue.put(("error", repr(ex)))
        finally:
            done.set()

    stream_cell.register_blob_cb(TEST_CHANNEL, TEST_TOPIC, receive_blob)
    try:
        cell.start()
        ready.set()
        done.wait(30)
    except Exception as ex:
        result_queue.put(("error", repr(ex)))
        ready.set()
    finally:
        cell.stop()
        CoreCell.ALL_CELLS.pop("server", None)


class TestStreamCell:
    @pytest.fixture(scope="session")
    def port(self):
        return get_open_ports(1)[0]

    @pytest.fixture(scope="session")
    def state(self):
        return State()

    @pytest.fixture(scope="session")
    def server_cell(self, port, state):
        # Patch STREAM_ACK_WAIT in the byte_streamer module
        with patch("nvflare.fuel.f3.streaming.byte_streamer.STREAM_ACK_WAIT", 400):
            listening_url = f"tcp://localhost:{port}"
            cell = CoreCell(_STREAM_RX_CELL, listening_url, secure=False, credentials={})
            stream_cell = StreamCell(cell)
            stream_cell.register_blob_cb(TEST_CHANNEL, TEST_TOPIC, self.blob_cb, state=state)
            cell.start()

            yield stream_cell
            cell.stop()

    @pytest.fixture(scope="session")
    def client_cell(self, port, state):
        with patch("nvflare.fuel.f3.streaming.byte_streamer.STREAM_ACK_WAIT", 400):
            connect_url = f"tcp://localhost:{port}"
            cell = CoreCell(_STREAM_TX_CELL, connect_url, secure=False, credentials={})
            stream_cell = StreamCell(cell)
            cell.start()

            yield stream_cell
            cell.stop()

    def test_streaming_blob(self, server_cell, client_cell, state):

        size = 64 * 1024 * 1024 + 123
        buffer = make_buffer(size)

        send_future = client_cell.send_blob(TEST_CHANNEL, TEST_TOPIC, _STREAM_RX_CELL, Message(None, buffer))
        bytes_sent = send_future.result()
        assert bytes_sent == len(buffer)

        if not state.done.wait(timeout=30):
            raise Exception("Data not received after 30 seconds")

        assert buffer == state.result

    def test_streaming_buffer_list(self, server_cell, client_cell, state):

        size = 64 * 1024 * 1024 + 123
        buffer = make_buffer(size)
        buf_list = []
        interval = int(size / 4)
        buf_list.append(buffer[0:interval])
        buf_list.append(buffer[interval : 2 * interval])
        buf_list.append(buffer[2 * interval : 3 * interval])
        buf_list.append(buffer[3 * interval : size])

        send_future = client_cell.send_blob(TEST_CHANNEL, TEST_TOPIC, _STREAM_RX_CELL, Message(None, buf_list))
        bytes_sent = send_future.result()
        assert bytes_sent == len(buffer)

        if not state.done.wait(timeout=30):
            raise Exception("Data not received after 30 seconds")

        assert buffer == state.result

    def test_streaming_segmented_bytes_across_part_boundary(self, monkeypatch):
        prefix = b"direct-control"
        body = make_buffer(2 * 1024 * 1024 + 123)
        expected = prefix + body
        message = Message(
            headers={StreamHeaderKey.PAYLOAD_ENCODING: Encoding.BYTES},
            payload=[prefix, memoryview(body)],
        )

        context = mp.get_context("spawn")
        ready = context.Event()
        done = context.Event()
        result_queue = context.Queue()
        port = get_open_ports(1)[0]
        server = context.Process(target=_run_segmented_blob_server, args=(port, ready, done, result_queue))
        server.start()
        assert ready.wait(WAIT_SEC)

        client_name = f"segmented-client-{uuid.uuid4().hex[:8]}"
        sender_core = CoreCell(client_name, f"tcp://localhost:{port}", secure=False, credentials={})
        # Force remote resolution before start. A stale process-local test Cell
        # named "server" would otherwise suppress creation of the TCP connector.
        sender_core.ALL_CELLS = {}
        try:
            client_cell = StreamCell(sender_core)
            sender_core.start()
            deadline = time.monotonic() + WAIT_SEC
            while sender_core.agents.get("server") is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert sender_core.agents.get("server") is not None

            remote_send = MagicMock(wraps=sender_core.communicator.send)
            monkeypatch.setattr(sender_core.communicator, "send", remote_send)
            send_future = client_cell.send_blob(TEST_CHANNEL, TEST_TOPIC, "server", message, reliable=True)
            assert send_future.result() == len(expected)

            status, result = result_queue.get(timeout=30)
            assert status == "ok", result
            assert result == expected
            remote_send.assert_called()
        finally:
            done.set()
            sender_core.stop()
            sender_core.__dict__.pop("ALL_CELLS", None)
            CoreCell.ALL_CELLS.pop(client_name, None)
            server.join(timeout=10)
            if server.is_alive():
                server.terminate()
                server.join(timeout=5)
        assert server.exitcode == 0

    def blob_cb(self, future: StreamFuture, **kwargs):
        state = kwargs.get("state")
        state.result = future.result()
        state.done.set()
