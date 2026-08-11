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

import pytest

from nvflare.fuel.f3.comm_error import CommError
from nvflare.fuel.f3.drivers.connector_info import Mode
from nvflare.fuel.f3.endpoint import Endpoint, EndpointState
from nvflare.fuel.f3.sfm.conn_manager import ConnManager
from nvflare.fuel.f3.sfm.constants import HandshakeKeys


class _Monitor:
    def __init__(self):
        self.states = []

    def state_change(self, endpoint):
        self.states.append(endpoint.state)


def _sfm_connection(name: str, lane: int, pool_size: int = 3, max_connections: int = 3):
    closed = []
    driver = SimpleNamespace(get_max_connections_per_endpoint=lambda: max_connections)
    connector = SimpleNamespace(handle="connector", driver=driver, mode=Mode.ACTIVE, params={})
    connection = SimpleNamespace(
        name=name,
        connector=connector,
        close=lambda: closed.append(True),
        get_conn_properties=lambda: {},
    )
    return (
        SimpleNamespace(
            lane=lane,
            pool_size=pool_size,
            pool_id="pool",
            conn=connection,
            sfm_endpoint=None,
            get_name=lambda: name,
        ),
        closed,
    )


def _shutdown(manager):
    manager.conn_mgr_executor.shutdown(wait=True)
    manager.frame_mgr_executor.shutdown(wait=True)


def test_concurrent_handshakes_retain_complete_lane_cohort_and_notify_ready_once():
    manager = ConnManager(Endpoint("local"))
    monitor = _Monitor()
    manager.monitors.append(monitor)
    connections = [_sfm_connection(f"lane-{lane}", lane)[0] for lane in range(3)]
    barrier = threading.Barrier(3)
    errors = []

    def _update(sfm_conn):
        try:
            barrier.wait(timeout=1.0)
            manager.update_endpoint(
                sfm_conn,
                {
                    HandshakeKeys.ENDPOINT_NAME: "remote",
                    HandshakeKeys.CONNECTION_LANE: sfm_conn.lane,
                    HandshakeKeys.CONNECTION_POOL_SIZE: sfm_conn.pool_size,
                    HandshakeKeys.CONNECTION_POOL_ID: sfm_conn.pool_id,
                },
            )
        except Exception as ex:
            errors.append(ex)

    threads = [threading.Thread(target=_update, args=(conn,)) for conn in connections]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2.0)

    try:
        assert not errors
        endpoint = manager.sfm_endpoints["remote"]
        assert sorted(conn.lane for conn in endpoint.get_connections()) == [0, 1, 2]
        assert endpoint.endpoint.state == EndpointState.READY
        assert monitor.states == [EndpointState.READY]
    finally:
        _shutdown(manager)


def test_invalid_peer_pool_is_rejected_and_closed():
    manager = ConnManager(Endpoint("local"))
    sfm_conn, closed = _sfm_connection("lane-0", lane=0, pool_size=4, max_connections=3)

    try:
        with pytest.raises(CommError, match="exceeds local endpoint limit"):
            manager.update_endpoint(
                sfm_conn,
                {
                    HandshakeKeys.ENDPOINT_NAME: "remote",
                    HandshakeKeys.CONNECTION_LANE: 0,
                    HandshakeKeys.CONNECTION_POOL_SIZE: 4,
                    HandshakeKeys.CONNECTION_POOL_ID: "pool",
                },
            )
        assert closed == [True]
        assert "remote" not in manager.sfm_endpoints
    finally:
        _shutdown(manager)


def test_multi_lane_peer_without_pool_generation_is_rejected():
    manager = ConnManager(Endpoint("local"))
    sfm_conn, closed = _sfm_connection("lane-0", lane=0, pool_size=2, max_connections=2)
    sfm_conn.pool_id = None

    try:
        with pytest.raises(CommError, match="Missing connection pool ID"):
            manager.update_endpoint(
                sfm_conn,
                {
                    HandshakeKeys.ENDPOINT_NAME: "remote",
                    HandshakeKeys.CONNECTION_LANE: 0,
                    HandshakeKeys.CONNECTION_POOL_SIZE: 2,
                },
            )
        assert closed == [True]
    finally:
        _shutdown(manager)


def test_losing_bulk_lane_marks_cohort_disconnected_until_replaced():
    manager = ConnManager(Endpoint("local"))
    monitor = _Monitor()
    manager.monitors.append(monitor)
    connections = [_sfm_connection(f"lane-{lane}", lane, pool_size=2, max_connections=2)[0] for lane in range(2)]

    try:
        for sfm_conn in connections:
            manager.sfm_conns[sfm_conn.conn.name] = sfm_conn
            manager.update_endpoint(
                sfm_conn,
                {
                    HandshakeKeys.ENDPOINT_NAME: "remote",
                    HandshakeKeys.CONNECTION_LANE: sfm_conn.lane,
                    HandshakeKeys.CONNECTION_POOL_SIZE: sfm_conn.pool_size,
                    HandshakeKeys.CONNECTION_POOL_ID: sfm_conn.pool_id,
                },
            )
        manager.close_connection(connections[1].conn)

        endpoint = manager.sfm_endpoints["remote"]
        assert endpoint.endpoint.state == EndpointState.DISCONNECTED
        assert monitor.states == [EndpointState.READY, EndpointState.DISCONNECTED]
    finally:
        _shutdown(manager)
