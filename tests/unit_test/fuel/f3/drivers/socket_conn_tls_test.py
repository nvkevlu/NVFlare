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
from unittest.mock import MagicMock

from nvflare.fuel.f3.drivers.socket_conn import ConnectionHandler


def _handler(server, request):
    handler = object.__new__(ConnectionHandler)
    handler.server = server
    handler.request = request
    handler.client_address = ("127.0.0.1", 12345)
    return handler


def test_connection_handler_wraps_only_accepted_socket(monkeypatch):
    raw_socket = MagicMock()
    tls_socket = MagicMock()
    context = MagicMock()
    context.wrap_socket.return_value = tls_socket
    connection = MagicMock()
    socket_connection = MagicMock(return_value=connection)
    monkeypatch.setattr("nvflare.fuel.f3.drivers.socket_conn.SocketConnection", socket_connection)
    driver = MagicMock()
    driver.native_bulk.enabled = False
    server = SimpleNamespace(
        ssl_context=context,
        handshake_timeout=3.0,
        connector=MagicMock(),
        driver=driver,
    )

    _handler(server, raw_socket).handle()

    raw_socket.settimeout.assert_called_once_with(3.0)
    context.wrap_socket.assert_called_once_with(raw_socket, server_side=True)
    tls_socket.settimeout.assert_called_once_with(None)
    socket_connection.assert_called_once_with(tls_socket, server.connector, True)
    driver.add_connection.assert_called_once_with(connection)
    connection.read_loop.assert_called_once_with()
    connection.close.assert_called_once_with()
    driver.close_connection.assert_called_once_with(connection)


def test_connection_handler_closes_failed_tls_handshake():
    raw_socket = MagicMock()
    context = MagicMock()
    context.wrap_socket.side_effect = TimeoutError("slow client hello")
    driver = MagicMock()
    driver.native_bulk.enabled = False
    server = SimpleNamespace(
        ssl_context=context,
        handshake_timeout=2.0,
        connector=MagicMock(),
        driver=driver,
    )

    _handler(server, raw_socket).handle()

    raw_socket.settimeout.assert_called_once_with(2.0)
    raw_socket.close.assert_called_once_with()
    driver.add_connection.assert_not_called()
