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

from nvflare.fuel.f3.drivers import tcp_driver
from nvflare.fuel.f3.drivers.driver_params import DriverParams


def _connect_with_context(monkeypatch, check_hostname: bool):
    raw_socket = MagicMock()
    tls_socket = MagicMock()
    context = MagicMock()
    context.check_hostname = check_hostname
    context.wrap_socket.return_value = tls_socket
    connection = MagicMock()

    monkeypatch.setattr(tcp_driver.socket, "socket", lambda *_args, **_kwargs: raw_socket)
    monkeypatch.setattr(tcp_driver, "get_ssl_context", lambda _params, ssl_server: context)
    socket_connection = MagicMock(return_value=connection)
    monkeypatch.setattr(tcp_driver, "SocketConnection", socket_connection)

    driver = tcp_driver.TcpDriver()
    driver.add_connection = MagicMock()
    driver.close_connection = MagicMock()
    connector = SimpleNamespace(
        params={
            DriverParams.HOST.value: "receiver.example.test",
            DriverParams.PORT.value: "8002",
        }
    )
    driver.connect(connector)
    return driver, connector, raw_socket, tls_socket, context, connection, socket_connection


def test_tcp_driver_supplies_server_hostname_when_verification_is_enabled(monkeypatch):
    driver, connector, raw_socket, tls_socket, context, connection, socket_connection = _connect_with_context(
        monkeypatch, True
    )

    context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="receiver.example.test")
    tls_socket.connect.assert_called_once_with(("receiver.example.test", 8002))
    socket_connection.assert_called_once_with(tls_socket, connector, True)
    driver.add_connection.assert_called_once_with(connection)
    connection.read_loop.assert_called_once_with()
    driver.close_connection.assert_called_once_with(connection)


def test_tcp_driver_preserves_legacy_wrap_without_hostname(monkeypatch):
    _, _, raw_socket, _, context, _, _ = _connect_with_context(monkeypatch, False)

    context.wrap_socket.assert_called_once_with(raw_socket)
