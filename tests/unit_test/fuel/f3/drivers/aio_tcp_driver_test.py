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

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from nvflare.fuel.f3.drivers import aio_tcp_driver


def test_aio_tcp_driver_supplies_server_hostname_when_verification_is_enabled(monkeypatch):
    context = MagicMock()
    context.check_hostname = True
    reader = MagicMock()
    writer = MagicMock()
    open_connection = AsyncMock(return_value=(reader, writer))
    monkeypatch.setattr(aio_tcp_driver, "get_ssl_context", lambda _params, ssl_server: context)
    monkeypatch.setattr(aio_tcp_driver.asyncio, "open_connection", open_connection)

    driver = object.__new__(aio_tcp_driver.AioTcpDriver)
    driver.connector = SimpleNamespace(params={})
    driver._create_connection = AsyncMock()
    asyncio.run(driver._tcp_connect("receiver.example.test", 8002))

    open_connection.assert_awaited_once_with(
        "receiver.example.test",
        8002,
        ssl=context,
        server_hostname="receiver.example.test",
    )
    driver._create_connection.assert_awaited_once_with(reader, writer)


def test_aio_tcp_driver_preserves_legacy_connection_without_server_hostname(monkeypatch):
    context = MagicMock()
    context.check_hostname = False
    open_connection = AsyncMock(return_value=(MagicMock(), MagicMock()))
    monkeypatch.setattr(aio_tcp_driver, "get_ssl_context", lambda _params, ssl_server: context)
    monkeypatch.setattr(aio_tcp_driver.asyncio, "open_connection", open_connection)

    driver = object.__new__(aio_tcp_driver.AioTcpDriver)
    driver.connector = SimpleNamespace(params={})
    driver._create_connection = AsyncMock()
    asyncio.run(driver._tcp_connect("receiver.example.test", 8002))

    open_connection.assert_awaited_once_with("receiver.example.test", 8002, ssl=context)
