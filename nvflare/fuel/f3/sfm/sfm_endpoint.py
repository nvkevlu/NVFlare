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
import threading
from typing import List, Optional

from nvflare.fuel.f3.endpoint import Endpoint
from nvflare.fuel.f3.sfm.sfm_conn import SfmConnection

# Hard-coded stream ID to be used by packets before handshake
RESERVED_STREAM_ID = 16

log = logging.getLogger(__name__)


class SfmEndpoint:
    """An endpoint wrapper to keep SFM internal data"""

    def __init__(self, endpoint: Endpoint, max_connections: int = 1):
        self.endpoint = endpoint
        self.stream_id: int = RESERVED_STREAM_ID
        self.lock = threading.Lock()
        self.connections: List[SfmConnection] = []
        self.max_connections = max(1, max_connections)
        self.connection_group = None
        self.expected_pool_size = 1

    def add_connection(self, sfm_conn: SfmConnection):
        evicted = []
        with self.lock:
            connection_group = (getattr(sfm_conn.conn.connector, "handle", None), getattr(sfm_conn, "pool_id", None))
            if self.connection_group is None:
                self.connection_group = connection_group
                self.expected_pool_size = sfm_conn.pool_size
            elif connection_group != self.connection_group:
                evicted.extend(self.connections)
                self.connections = []
                self.connection_group = connection_group
                self.expected_pool_size = sfm_conn.pool_size
            elif self.connections and sfm_conn.pool_size != self.expected_pool_size:
                raise ValueError(
                    f"Connection pool size changed from {self.expected_pool_size} to {sfm_conn.pool_size} "
                    f"for endpoint {self.endpoint.name}"
                )

            same_lane = next((conn for conn in self.connections if conn.lane == sfm_conn.lane), None)
            if same_lane:
                self.connections.remove(same_lane)
                evicted.append(same_lane)

            while len(self.connections) >= self.max_connections:
                evicted.append(self.connections.pop(0))

            self.connections.append(sfm_conn)

        for old_conn in evicted:
            log.info(
                f"Connection {old_conn.get_name()} is evicted for {sfm_conn.get_name()} "
                f"from endpoint {self.endpoint.name} for lane {sfm_conn.lane} "
                f"or exceeding limit {self.max_connections}"
            )
        return evicted

    def remove_connection(self, sfm_conn: SfmConnection):

        with self.lock:
            if not self.connections:
                log.debug(
                    f"Connection {sfm_conn.get_name()} is already removed. "
                    f"No connections for endpoint {self.endpoint.name}"
                )
                return

            found_index = next(
                (index for index, conn in enumerate(self.connections) if conn.get_name() == sfm_conn.get_name()), None
            )

            if found_index is not None:
                self.connections.pop(found_index)
                if not self.connections:
                    self.connection_group = None
                    self.expected_pool_size = 1
                log.debug(f"Connection {sfm_conn.get_name()} is removed from endpoint {self.endpoint.name}")
            else:
                log.debug(f"Connection {sfm_conn.get_name()} is already removed from endpoint {self.endpoint.name}")

    def get_connection(self, stream_id: int, bulk: bool = False) -> Optional[SfmConnection]:
        with self.lock:
            if not self.connections:
                return None

            lanes = {conn.lane for conn in self.connections}
            if self.expected_pool_size > 1 and not set(range(self.expected_pool_size)).issubset(lanes):
                return None

            control = [conn for conn in self.connections if conn.lane == 0]
            bulk_connections = [conn for conn in self.connections if conn.lane > 0]
            candidates = bulk_connections if bulk and bulk_connections else control
            if not candidates:
                candidates = self.connections
            index = stream_id % len(candidates)
            return candidates[index]

    def get_connections(self) -> List[SfmConnection]:
        with self.lock:
            return list(self.connections)

    def has_control_connection(self) -> bool:
        with self.lock:
            return any(conn.lane == 0 for conn in self.connections)

    def is_ready(self) -> bool:
        with self.lock:
            lanes = {conn.lane for conn in self.connections}
            return set(range(self.expected_pool_size)).issubset(lanes)

    def next_stream_id(self) -> int:
        """Get next stream_id for the endpoint
        stream_id is used to assemble fragmented data
        """

        with self.lock:
            self.stream_id = (self.stream_id + 1) & 0xFFFF
            return self.stream_id
