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

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nvflare.fuel.f3.comm_config import CommConfigurator
from nvflare.fuel.f3.comm_error import CommError
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


def _configure_native_pool(monkeypatch, *, async_send: bool, bulk_lanes: int):
    monkeypatch.setattr(CommConfigurator, "get_tcp_async_send", lambda self, default: async_send)
    monkeypatch.setattr(CommConfigurator, "get_tcp_bulk_lanes", lambda self, default: bulk_lanes)
    monkeypatch.setattr(CommConfigurator, "get_tcp_handshake_timeout", lambda self, default: 1.0)


def test_tcp_bulk_lanes_require_async_send(monkeypatch):
    _configure_native_pool(monkeypatch, async_send=False, bulk_lanes=1)

    with pytest.raises(CommError, match="requires tcp_async_send"):
        tcp_driver.TcpDriver()


def test_tcp_async_send_requires_boolean(monkeypatch):
    _configure_native_pool(monkeypatch, async_send="yes", bulk_lanes=0)

    with pytest.raises(CommError, match="tcp_async_send must be a bool"):
        tcp_driver.TcpDriver()


@pytest.mark.parametrize("bulk_lanes", [-1, 5, True])
def test_tcp_bulk_lane_count_is_bounded(monkeypatch, bulk_lanes):
    _configure_native_pool(monkeypatch, async_send=True, bulk_lanes=bulk_lanes)

    with pytest.raises(CommError, match="tcp_bulk_lanes"):
        tcp_driver.TcpDriver()


def test_tcp_driver_starts_one_control_and_configured_bulk_lanes(monkeypatch):
    _configure_native_pool(monkeypatch, async_send=True, bulk_lanes=2)
    driver = tcp_driver.TcpDriver()
    started_lanes = []
    barrier = threading.Barrier(3)

    def _run_lane(_connector, lane, pool_done, _pool_id):
        started_lanes.append(lane)
        barrier.wait(timeout=1.0)
        pool_done.set()

    monkeypatch.setattr(driver, "_run_client_connection", _run_lane)
    monkeypatch.setattr(driver, "close_all", lambda: None)

    driver.connect(SimpleNamespace())

    assert sorted(started_lanes) == [0, 1, 2]
    assert driver.get_max_connections_per_endpoint() == 3


@pytest.mark.parametrize("timeout", [0, -1, True, "10"])
def test_tcp_handshake_timeout_is_validated(monkeypatch, timeout):
    _configure_native_pool(monkeypatch, async_send=False, bulk_lanes=0)
    monkeypatch.setattr(CommConfigurator, "get_tcp_handshake_timeout", lambda self, default: timeout)

    with pytest.raises(CommError, match="tcp_handshake_timeout"):
        tcp_driver.TcpDriver()
