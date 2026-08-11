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

import pytest

from nvflare.fuel.f3.endpoint import Endpoint
from nvflare.fuel.f3.sfm.sfm_endpoint import SfmEndpoint


def _connection(
    name: str,
    lane: int,
    pool_size: int = 3,
    connector_handle: str = "connector",
    pool_id: str = "pool",
):
    return SimpleNamespace(
        lane=lane,
        pool_size=pool_size,
        pool_id=pool_id,
        conn=SimpleNamespace(connector=SimpleNamespace(handle=connector_handle), close=lambda: None),
        get_name=lambda: name,
    )


def test_endpoint_becomes_ready_only_after_complete_lane_cohort():
    endpoint = SfmEndpoint(Endpoint("peer"), max_connections=3)
    lane_1 = _connection("lane-1", 1)
    lane_0 = _connection("lane-0", 0)
    lane_2 = _connection("lane-2", 2)

    endpoint.add_connection(lane_1)
    assert endpoint.is_ready() is False
    endpoint.add_connection(lane_0)
    assert endpoint.has_control_connection() is True
    assert endpoint.is_ready() is False
    endpoint.add_connection(lane_2)
    assert endpoint.is_ready() is True

    assert endpoint.get_connection(0, bulk=False) is lane_0
    assert endpoint.get_connection(0, bulk=True) is lane_1
    assert endpoint.get_connection(1, bulk=True) is lane_2


def test_replacing_lane_returns_old_connection_for_outside_lock_close():
    endpoint = SfmEndpoint(Endpoint("peer"), max_connections=2)
    old_lane = _connection("old", 1, pool_size=2)
    new_lane = _connection("new", 1, pool_size=2)

    assert endpoint.add_connection(old_lane) == []
    assert endpoint.add_connection(new_lane) == [old_lane]
    assert endpoint.get_connections() == [new_lane]


def test_new_connector_replaces_transport_group_instead_of_mixing_routes():
    endpoint = SfmEndpoint(Endpoint("peer"), max_connections=3)
    old_control = _connection("old-control", 0, connector_handle="old")
    old_bulk = _connection("old-bulk", 1, connector_handle="old")
    new_control = _connection("new-control", 0, pool_size=1, connector_handle="new")
    endpoint.add_connection(old_control)
    endpoint.add_connection(old_bulk)

    evicted = endpoint.add_connection(new_control)

    assert evicted == [old_control, old_bulk]
    assert endpoint.get_connections() == [new_control]
    assert endpoint.is_ready() is True


def test_new_pool_generation_cannot_mix_with_stale_lanes():
    endpoint = SfmEndpoint(Endpoint("peer"), max_connections=3)
    old = [_connection(f"old-{lane}", lane, pool_id="old") for lane in range(3)]
    for connection in old:
        endpoint.add_connection(connection)
    assert endpoint.is_ready() is True

    new_control = _connection("new-control", 0, pool_id="new")
    evicted = endpoint.add_connection(new_control)

    assert evicted == old
    assert endpoint.get_connections() == [new_control]
    assert endpoint.is_ready() is False


def test_same_connector_rejects_inconsistent_pool_size():
    endpoint = SfmEndpoint(Endpoint("peer"), max_connections=3)
    endpoint.add_connection(_connection("lane-0", 0, pool_size=3))

    with pytest.raises(ValueError, match="pool size changed"):
        endpoint.add_connection(_connection("lane-1", 1, pool_size=2))


def test_removing_any_required_lane_marks_cohort_not_ready():
    endpoint = SfmEndpoint(Endpoint("peer"), max_connections=2)
    control = _connection("control", 0, pool_size=2)
    bulk = _connection("bulk", 1, pool_size=2)
    endpoint.add_connection(control)
    endpoint.add_connection(bulk)
    assert endpoint.is_ready() is True

    endpoint.remove_connection(bulk)

    assert endpoint.is_ready() is False
    assert endpoint.has_control_connection() is True
    assert endpoint.get_connection(7, bulk=True) is None
