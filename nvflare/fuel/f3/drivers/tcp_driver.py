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
import logging
import os
import socket
import threading
import uuid
from socketserver import TCPServer, ThreadingTCPServer
from typing import Any, Dict, List, Optional

from nvflare.fuel.f3.comm_config import CommConfigurator
from nvflare.fuel.f3.comm_config_utils import requires_secure_connection
from nvflare.fuel.f3.comm_error import CommError
from nvflare.fuel.f3.drivers.base_driver import BaseDriver
from nvflare.fuel.f3.drivers.driver import ConnectorInfo, Driver
from nvflare.fuel.f3.drivers.driver_params import DriverCap, DriverParams
from nvflare.fuel.f3.drivers.native_bulk import (
    DEFAULT_NATIVE_BULK_LANES,
    DEFAULT_NATIVE_BULK_MAX_BYTES,
    DEFAULT_NATIVE_BULK_MAX_SESSIONS,
    DEFAULT_NATIVE_BULK_TIMEOUT,
    NativeBulkManager,
)
from nvflare.fuel.f3.drivers.net_utils import get_ssl_context, get_tcp_urls
from nvflare.fuel.f3.drivers.socket_conn import ConnectionHandler, SocketConnection
from nvflare.security.logging import secure_format_exception

log = logging.getLogger(__name__)

MAX_TCP_BULK_LANES = 4
DEFAULT_TCP_HANDSHAKE_TIMEOUT = 10.0


class TcpStreamServer(ThreadingTCPServer):

    TCPServer.allow_reuse_address = True
    daemon_threads = True

    def __init__(self, driver: Driver, connector: ConnectorInfo):
        self.driver = driver
        self.connector = connector

        params = connector.params
        self.ssl_context = get_ssl_context(params, ssl_server=True)
        self.handshake_timeout = driver.handshake_timeout

        host = params.get(DriverParams.HOST.value)
        port = int(params.get(DriverParams.PORT.value))
        self.local_addr = f"{host}:{port}"

        TCPServer.__init__(self, (host, port), ConnectionHandler, False)

        try:
            self.server_bind()
            self.server_activate()
        except Exception as ex:
            log.error(f"{os.getpid()}: Error binding to  {host}:{port}: {secure_format_exception(ex)}")
            self.server_close()
            raise


class TcpDriver(BaseDriver):
    def __init__(self):
        super().__init__()
        self.server = None
        config = CommConfigurator()
        self.async_send = config.get_tcp_async_send(False)
        if not isinstance(self.async_send, bool):
            raise CommError(CommError.BAD_CONFIG, f"tcp_async_send must be a bool, got {self.async_send!r}")
        self.bulk_lanes = config.get_tcp_bulk_lanes(0)
        if (
            isinstance(self.bulk_lanes, bool)
            or not isinstance(self.bulk_lanes, int)
            or not 0 <= self.bulk_lanes <= MAX_TCP_BULK_LANES
        ):
            raise CommError(
                CommError.BAD_CONFIG,
                f"tcp_bulk_lanes must be between 0 and {MAX_TCP_BULK_LANES}, got {self.bulk_lanes}",
            )
        if self.bulk_lanes and not self.async_send:
            raise CommError(CommError.BAD_CONFIG, "tcp_bulk_lanes requires tcp_async_send=true")
        self.connection_pool_size = 1 + self.bulk_lanes
        self.handshake_timeout = config.get_tcp_handshake_timeout(DEFAULT_TCP_HANDSHAKE_TIMEOUT)
        if (
            isinstance(self.handshake_timeout, bool)
            or not isinstance(self.handshake_timeout, (int, float))
            or self.handshake_timeout <= 0
        ):
            raise CommError(
                CommError.BAD_CONFIG,
                f"tcp_handshake_timeout must be positive, got {self.handshake_timeout}",
            )
        self.native_bulk = NativeBulkManager(
            enabled=config.get_tcp_tensor_bulk_enabled(False),
            lanes=config.get_tcp_tensor_bulk_lanes(DEFAULT_NATIVE_BULK_LANES),
            max_bytes=config.get_tcp_tensor_bulk_max_bytes(DEFAULT_NATIVE_BULK_MAX_BYTES),
            max_sessions=config.get_tcp_tensor_bulk_max_sessions(DEFAULT_NATIVE_BULK_MAX_SESSIONS),
            timeout=config.get_tcp_tensor_bulk_timeout(DEFAULT_NATIVE_BULK_TIMEOUT),
        )

    @staticmethod
    def supported_transports() -> List[str]:
        return ["tcp", "stcp"]

    @staticmethod
    def capabilities() -> Dict[str, Any]:
        return {DriverCap.SEND_HEARTBEAT.value: True, DriverCap.SUPPORT_SSL.value: True}

    def listen(self, connector: ConnectorInfo):
        self.connector = connector
        self.server = TcpStreamServer(self, connector)
        self.server.serve_forever()

    def connect(self, connector: ConnectorInfo):
        self.connector = connector
        pool_id = uuid.uuid4().hex
        if self.connection_pool_size == 1:
            self._run_client_connection(connector, lane=0, pool_done=None, pool_id=pool_id)
            return

        pool_done = threading.Event()
        threads = []
        for lane in range(self.connection_pool_size):
            thread = threading.Thread(
                target=self._run_client_connection,
                args=(connector, lane, pool_done, pool_id),
                name=f"tcp_lane_{lane}",
                daemon=True,
            )
            threads.append(thread)
            thread.start()

        pool_done.wait()
        self.close_all()
        for thread in threads:
            thread.join(timeout=max(1.0, self.handshake_timeout))

    def _run_client_connection(
        self,
        connector: ConnectorInfo,
        lane: int,
        pool_done: Optional[threading.Event],
        pool_id: Optional[str] = None,
    ):
        params = connector.params
        host = params.get(DriverParams.HOST.value)
        port = int(params.get(DriverParams.PORT.value))
        connection = None
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.handshake_timeout)

            context = get_ssl_context(params, ssl_server=False)
            if context:
                if context.check_hostname:
                    sock = context.wrap_socket(sock, server_hostname=host)
                else:
                    sock = context.wrap_socket(sock)

            sock.connect((host, port))
            sock.settimeout(None)

            connection = SocketConnection(sock, connector, bool(context))
            connection.conn_props[DriverParams.CONNECTION_LANE.value] = lane
            connection.conn_props[DriverParams.CONNECTION_POOL_SIZE.value] = self.connection_pool_size
            connection.conn_props[DriverParams.CONNECTION_POOL_ID.value] = pool_id
            if pool_done and pool_done.is_set():
                connection.close()
                return
            self.add_connection(connection)
            if pool_done and pool_done.is_set():
                connection.close()
            else:
                connection.read_loop()
        except Exception as ex:
            log.debug(f"TCP lane {lane} ended: {secure_format_exception(ex)}")
        finally:
            if connection:
                connection.close()
                self.close_connection(connection)
            elif sock:
                sock.close()
            if pool_done:
                pool_done.set()

    def get_max_connections_per_endpoint(self) -> int:
        return self.connection_pool_size

    def shutdown(self):
        self.native_bulk.shutdown()
        self.close_all()
        if self.server:
            self.server.shutdown()

    @staticmethod
    def get_urls(scheme: str, resources: dict) -> (str, str):
        secure = requires_secure_connection(resources)
        if secure:
            scheme = "stcp"

        return get_tcp_urls(scheme, resources)
