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
import errno
import logging
import select
import socket
import time
from socketserver import BaseRequestHandler
from typing import Any, Union

from nvflare.fuel.f3.comm_config import CommConfigurator
from nvflare.fuel.f3.comm_error import CommError
from nvflare.fuel.f3.connection import BytesAlike, Connection
from nvflare.fuel.f3.drivers.driver import ConnectorInfo
from nvflare.fuel.f3.drivers.driver_params import DriverParams
from nvflare.fuel.f3.drivers.native_bulk import (
    NATIVE_BULK_MAGIC,
    PrefixedSocket,
    authenticated_peer_cn,
    log_bulk_connection_error,
)
from nvflare.fuel.f3.drivers.net_utils import MAX_FRAME_SIZE
from nvflare.fuel.f3.sfm.prefix import PREFIX_LEN, Prefix
from nvflare.fuel.hci.security import get_certificate_common_name
from nvflare.security.logging import secure_format_exception

log = logging.getLogger(__name__)


class SocketConnection(Connection):
    def __init__(self, sock: Any, connector: ConnectorInfo, secure: bool = False):
        super().__init__(connector)
        self.sock = sock
        self.secure = secure
        self.closing = False
        config = CommConfigurator()
        if config.get_tcp_no_delay(True):
            self._set_tcp_no_delay()
        self.conn_props = self._get_socket_properties()
        self.send_timeout = config.get_streaming_send_timeout(30.0)

    def _set_tcp_no_delay(self):
        """Disable Nagle's algorithm.

        The cellnet request/reply pattern ping-pongs small frames (requests,
        final chunks, stream ACKs). With Nagle enabled, each such frame can
        stall behind the peer's delayed ACK (40-200ms), which dominates
        per-request latency on real networks. Bulk chunk frames are ~1MiB,
        so disabling Nagle does not increase small-packet load on the data
        path. Can be turned off with tcp_no_delay: false in comm_config.
        """
        if getattr(self.sock, "family", None) not in (socket.AF_INET, socket.AF_INET6):
            return
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as ex:
            log.debug(f"cannot set TCP_NODELAY on connection: {ex}")

    def get_conn_properties(self) -> dict:
        return self.conn_props

    def close(self):
        self.closing = True

        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError as error:
                log.debug(f"Connection {self} is already closed: {error}")

            self.sock.close()

    def send_frame(self, frame: BytesAlike):
        try:
            self._send_with_timeout(frame, self.send_timeout)
        except CommError as error:
            if not self.closing:
                # A send timeout may occur after partial bytes are already written to the stream.
                # Close the connection to avoid frame-boundary desync on subsequent sends.
                if error.code == CommError.TIMEOUT:
                    self.close()
                raise
        except Exception as ex:
            if not self.closing:
                if self._is_timeout_exception(ex):
                    self.close()
                    raise CommError(
                        CommError.TIMEOUT,
                        f"send_frame timeout on conn {self}: {secure_format_exception(ex)}",
                    )
                if self._is_closed_socket_exception(ex):
                    raise CommError(
                        CommError.CLOSED,
                        f"Connection {self.name} is closed while sending: {secure_format_exception(ex)}",
                    )
                raise CommError(CommError.ERROR, f"Error sending frame on conn {self}: {secure_format_exception(ex)}")

    @staticmethod
    def _is_timeout_exception(ex: Exception) -> bool:
        return isinstance(ex, (TimeoutError, socket.timeout))

    @staticmethod
    def _is_closed_socket_exception(ex: Exception) -> bool:
        if isinstance(ex, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return True

        if isinstance(ex, OSError):
            return ex.errno in {
                errno.EPIPE,
                errno.ECONNRESET,
                errno.ENOTCONN,
                errno.ECONNABORTED,
                errno.EBADF,
                errno.ESHUTDOWN,
            }

        return False

    def _send_with_timeout(self, frame: BytesAlike, timeout_sec: float):
        view = frame if isinstance(frame, memoryview) else memoryview(frame)
        deadline = time.monotonic() + timeout_sec
        while view:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CommError(CommError.TIMEOUT, f"send_frame timeout after {timeout_sec} seconds on {self.name}")

            _, writable, _ = select.select([], [self.sock], [], remaining)
            if not writable:
                raise CommError(CommError.TIMEOUT, f"send_frame timeout after {timeout_sec} seconds on {self.name}")

            sent = self.sock.send(view)
            if sent <= 0:
                raise CommError(CommError.CLOSED, f"Connection {self.name} is closed while sending")

            view = view[sent:]

    def read_loop(self):
        try:
            self.read_frame_loop()
        except CommError as error:
            if error.code == CommError.CLOSED:
                log.debug(f"Connection {self.name} is closed by peer")
            else:
                log.debug(f"Connection {self.name} is closed due to error: {error}")
        except Exception as ex:
            if self.closing:
                log.debug(f"Connection {self.name} is closed")
            else:
                log.debug(f"Connection {self.name} is closed due to error: {secure_format_exception(ex)}")

    def read_frame_loop(self):
        # read_frame throws exception on stale/bad connection so this is not a dead loop
        while not self.closing:
            frame = self.read_frame()
            self.process_frame(frame)

    def read_frame(self) -> BytesAlike:

        prefix_buf = bytearray(PREFIX_LEN)
        self.read_into(prefix_buf, 0, PREFIX_LEN)
        prefix = Prefix.from_bytes(prefix_buf)

        if prefix.length == PREFIX_LEN:
            return prefix_buf

        if prefix.length < PREFIX_LEN:
            raise CommError(CommError.BAD_DATA, f"Frame length below prefix size ({prefix.length} < {PREFIX_LEN})")

        if prefix.length > MAX_FRAME_SIZE:
            raise CommError(CommError.BAD_DATA, f"Frame exceeds limit ({prefix.length} > {MAX_FRAME_SIZE}")

        frame = bytearray(prefix.length)
        frame[0:PREFIX_LEN] = prefix_buf
        self.read_into(frame, PREFIX_LEN, prefix.length - PREFIX_LEN)

        return frame

    def read_into(self, buffer: BytesAlike, offset: int, length: int):
        view = buffer if isinstance(buffer, memoryview) else memoryview(buffer)
        if offset:
            view = view[offset:]

        remaining = length
        while remaining:
            n = self.sock.recv_into(view, remaining)
            if n == 0:
                raise CommError(CommError.CLOSED, f"Connection {self.name} is closed by peer")
            view = view[n:]
            remaining -= n

    @staticmethod
    def _format_address(addr: Union[str, tuple], fileno: int) -> str:

        if isinstance(addr, tuple):
            result = f"{addr[0]}:{addr[1]}"
        else:
            result = f"{addr}:{fileno}"

        return result

    def _get_socket_properties(self) -> dict:
        conn_props = {}

        try:
            peer = self.sock.getpeername()
            fileno = self.sock.fileno()
        except OSError as ex:
            peer = "N/A"
            fileno = 0
            log.debug(f"getpeername() error: {secure_format_exception(ex)}")

        conn_props[DriverParams.PEER_ADDR.value] = self._format_address(peer, fileno)

        local = self.sock.getsockname()
        conn_props[DriverParams.LOCAL_ADDR.value] = self._format_address(local, fileno)

        if self.secure:
            cert = self.sock.getpeercert()
            if cert:
                cn = get_certificate_common_name(cert)
            else:
                cn = "N/A"
            conn_props[DriverParams.PEER_CN.value] = cn

        return conn_props


class ConnectionHandler(BaseRequestHandler):
    def handle(self):

        # noinspection PyUnresolvedReferences
        driver = self.server.driver
        request = self.request
        ssl_context = self.server.ssl_context
        try:
            if ssl_context:
                request.settimeout(self.server.handshake_timeout)
                request = ssl_context.wrap_socket(request, server_side=True)
                request.settimeout(None)
        except Exception as ex:
            log.warning(f"Rejected TCP TLS connection: {secure_format_exception(ex)}")
            try:
                request.close()
            except OSError:
                pass
            return

        if driver.native_bulk.enabled and ssl_context:
            try:
                request.settimeout(min(driver.native_bulk.timeout, 15.0))
                first_magic = _read_connection_prefix(request, len(NATIVE_BULK_MAGIC))
                request.settimeout(None)
                if first_magic == NATIVE_BULK_MAGIC:
                    request.settimeout(driver.native_bulk.timeout)
                    peer_cn = authenticated_peer_cn(request)
                    driver.native_bulk.handle_connection(request, peer_cn, first_magic)
                    request.close()
                    return
                request = PrefixedSocket(request, first_magic)
            except Exception as ex:
                log_bulk_connection_error(ex)
                request.close()
                return

        # noinspection PyUnresolvedReferences
        connection = SocketConnection(request, self.server.connector, bool(ssl_context))
        added = False
        try:
            driver.add_connection(connection)
            added = True
            connection.read_loop()
        finally:
            connection.close()
            if added:
                driver.close_connection(connection)


def _read_connection_prefix(sock, length: int) -> bytes:
    prefix = bytearray(length)
    view = memoryview(prefix)
    offset = 0
    while offset < length:
        count = sock.recv_into(view[offset:])
        if count == 0:
            raise CommError(CommError.CLOSED, "connection closed while classifying native bulk preface")
        offset += count
    return bytes(prefix)
