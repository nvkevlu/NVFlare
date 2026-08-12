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

import pytest

from nvflare.fuel.f3.comm_config import CommConfigurator
from nvflare.fuel.f3.comm_error import CommError
from nvflare.fuel.f3.drivers import tcp_driver
from nvflare.fuel.f3.drivers.connector_info import Mode
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
        },
        mode=Mode.ACTIVE,
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


@pytest.mark.parametrize("timeout", [0, -1, True, "10"])
def test_tcp_driver_rejects_invalid_handshake_timeout(monkeypatch, timeout):
    monkeypatch.setattr(CommConfigurator, "get_tcp_handshake_timeout", lambda self, default: timeout)

    with pytest.raises(CommError, match="tcp_handshake_timeout must be positive"):
        tcp_driver.TcpDriver()


def test_tcp_stream_server_keeps_listener_unwrapped(monkeypatch):
    context = MagicMock()
    connector = SimpleNamespace(params={DriverParams.HOST.value: "127.0.0.1", DriverParams.PORT.value: "8002"})
    driver = SimpleNamespace(handshake_timeout=4.0)
    monkeypatch.setattr(tcp_driver, "get_ssl_context", lambda _params, ssl_server: context)
    monkeypatch.setattr(tcp_driver.TCPServer, "__init__", lambda self, *_args, **_kwargs: None)
    monkeypatch.setattr(tcp_driver.TcpStreamServer, "server_bind", lambda self: None)
    monkeypatch.setattr(tcp_driver.TcpStreamServer, "server_activate", lambda self: None)

    server = tcp_driver.TcpStreamServer(driver, connector)

    context.wrap_socket.assert_not_called()
    assert server.ssl_context is context
    assert server.handshake_timeout == 4.0


def test_tcp_driver_applies_hostname_policy_to_connectors(monkeypatch):
    monkeypatch.setattr(CommConfigurator, "get_tcp_verify_hostname", lambda self, default: True)
    driver = tcp_driver.TcpDriver()
    connector = SimpleNamespace(params={}, mode=Mode.ACTIVE)

    driver._configure_connector_security(connector)

    assert connector.params[DriverParams.VERIFY_HOSTNAME.value] is True


def test_native_bulk_accepts_explicit_connector_hostname_verification(monkeypatch):
    monkeypatch.setattr(CommConfigurator, "get_tcp_tensor_bulk_enabled", lambda self, default: True)
    monkeypatch.setattr(CommConfigurator, "get_tcp_verify_hostname", lambda self, default: False)
    driver = tcp_driver.TcpDriver()
    connector = SimpleNamespace(
        params={
            DriverParams.CONNECTION_SECURITY.value: "mtls",
            DriverParams.VERIFY_HOSTNAME.value: True,
            DriverParams.SCHEME.value: "stcp",
        },
        mode=Mode.ACTIVE,
    )

    driver._configure_connector_security(connector)

    assert connector.params[DriverParams.VERIFY_HOSTNAME.value] is True


def test_native_bulk_leaves_non_mtls_connector_ineligible_for_fallback(monkeypatch):
    monkeypatch.setattr(CommConfigurator, "get_tcp_tensor_bulk_enabled", lambda self, default: True)
    monkeypatch.setattr(CommConfigurator, "get_tcp_verify_hostname", lambda self, default: True)
    driver = tcp_driver.TcpDriver()
    connector = SimpleNamespace(
        params={DriverParams.CONNECTION_SECURITY.value: "tls"},
        mode=Mode.ACTIVE,
    )

    driver._configure_connector_security(connector)

    assert not driver.native_bulk.can_use_connector(connector)
