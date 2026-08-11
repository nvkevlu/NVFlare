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

from dev_tools.f3 import grpc_lane_bench
from nvflare.apis.fl_constant import ConnectionSecurity
from nvflare.lighter.utils import Identity, generate_cert, generate_keys, serialize_cert, serialize_pri_key

MB = 1024 * 1024


def _spec(**overrides):
    values = {
        "run_token": b"0123456789abcdef",
        "lane_index": 0,
        "channel_index": 0,
        "rpc_index": 0,
        "channel_count": 1,
        "rpcs_per_channel": 1,
        "lane_count": 1,
        "direction": grpc_lane_bench.DIRECTION_SERVER_TO_CLIENT,
        "pattern": 1,
        "warmup_bytes": MB,
        "measured_bytes": 4 * MB,
        "chunk_size": 64 * 1024,
        "ack_interval": 256 * 1024,
        "window_size": MB,
    }
    values.update(overrides)
    return grpc_lane_bench.LaneSpec(**values)


@pytest.mark.parametrize(
    "total,count,expected",
    [
        (0, 1, [0]),
        (10, 3, [4, 3, 3]),
        (3, 5, [1, 1, 1, 0, 0]),
    ],
)
def test_partition_is_exact_and_balanced(total, count, expected):
    result = grpc_lane_bench._partition(total, count)

    assert result == expected
    assert sum(result) == total
    assert max(result, default=0) - min(result, default=0) <= 1


@pytest.mark.parametrize("total,count", [(-1, 1), (1, 0), (True, 1), (1, False)])
def test_partition_rejects_invalid_values(total, count):
    with pytest.raises(ValueError):
        grpc_lane_bench._partition(total, count)


def test_lane_spec_round_trip():
    spec = _spec(
        lane_index=5,
        channel_index=2,
        rpc_index=1,
        channel_count=3,
        rpcs_per_channel=2,
        lane_count=6,
        pattern=251,
    )

    assert grpc_lane_bench.LaneSpec.decode(spec.encode()) == spec


@pytest.mark.parametrize(
    "overrides,error",
    [
        ({"channel_count": 0}, "channel_count"),
        ({"rpcs_per_channel": 0}, "rpcs_per_channel"),
        ({"channel_count": 2, "lane_count": 1}, "lane_count"),
        ({"lane_index": 1}, "lane_index"),
        ({"direction": 99}, "direction"),
        ({"pattern": 256}, "pattern"),
        ({"measured_bytes": 0}, "byte counts"),
        ({"warmup_bytes": grpc_lane_bench.MAX_LANE_BYTES + 1}, "byte counts"),
        ({"measured_bytes": grpc_lane_bench.MAX_LANE_BYTES + 1}, "byte counts"),
        ({"chunk_size": grpc_lane_bench.MAX_CHUNK_SIZE + 1}, "chunk_size"),
        ({"ack_interval": grpc_lane_bench.MAX_ACK_INTERVAL + 1}, "ack_interval"),
        ({"window_size": grpc_lane_bench.MAX_WINDOW_SIZE + 1}, "window_size"),
        ({"window_size": 32 * 1024}, "chunk-rounded"),
        ({"chunk_size": 64 * 1024, "ack_interval": 96 * 1024, "window_size": 96 * 1024}, "chunk-rounded"),
    ],
)
def test_lane_spec_rejects_invalid_metadata(overrides, error):
    spec = _spec(**overrides)

    with pytest.raises(ValueError, match=error):
        grpc_lane_bench.LaneSpec.decode(spec.encode())


def test_ack_round_trip_and_bounds():
    ack = grpc_lane_bench.Ack(
        kind=grpc_lane_bench.ACK_DONE,
        cumulative_bytes=123456,
        elapsed_ns=987654,
        text="ipv4:127.0.0.1:54321",
    )

    assert grpc_lane_bench.Ack.decode(ack.encode()) == ack
    with pytest.raises(ValueError, match="truncated"):
        grpc_lane_bench.Ack.decode(b"short")
    with pytest.raises(ValueError, match="too large"):
        grpc_lane_bench.Ack(grpc_lane_bench.ACK_ERROR, text="x" * 5000).encode()


def _fake_lane(channel_index, rpc_index, rpcs_per_channel, peer):
    return SimpleNamespace(
        peer=peer,
        spec=SimpleNamespace(
            lane_index=channel_index * rpcs_per_channel + rpc_index,
            channel_index=channel_index,
        ),
    )


def test_peer_topology_distinguishes_rpcs_from_physical_channels():
    shared = [
        _fake_lane(0, 0, 2, "ipv4:127.0.0.1:10001"),
        _fake_lane(0, 1, 2, "ipv4:127.0.0.1:10001"),
    ]
    physical = [
        _fake_lane(0, 0, 1, "ipv4:127.0.0.1:10001"),
        _fake_lane(1, 0, 1, "ipv4:127.0.0.1:10002"),
    ]

    assert grpc_lane_bench._validate_peer_topology(shared, 1, 2) == {0: "ipv4:127.0.0.1:10001"}
    assert grpc_lane_bench._validate_peer_topology(physical, 2, 1) == {
        0: "ipv4:127.0.0.1:10001",
        1: "ipv4:127.0.0.1:10002",
    }


def test_peer_topology_rejects_silently_shared_channels():
    lanes = [
        _fake_lane(0, 0, 1, "ipv4:127.0.0.1:10001"),
        _fake_lane(1, 0, 1, "ipv4:127.0.0.1:10001"),
    ]

    with pytest.raises(RuntimeError, match="requested 2 physical channels but observed 1"):
        grpc_lane_bench._validate_peer_topology(lanes, 2, 1)


def test_multi_channel_options_force_local_subchannel_pools():
    source = [
        ("grpc.max_send_message_length", 123),
        (grpc_lane_bench.LOCAL_SUBCHANNEL_POOL_OPTION, 0),
    ]

    assert grpc_lane_bench._client_channel_options(source, 1) == [("grpc.max_send_message_length", 123)]
    assert grpc_lane_bench._client_channel_options(source, 2) == [
        ("grpc.max_send_message_length", 123),
        (grpc_lane_bench.LOCAL_SUBCHANNEL_POOL_OPTION, 1),
    ]
    assert source[-1] == (grpc_lane_bench.LOCAL_SUBCHANNEL_POOL_OPTION, 0)


def _run_loopback(
    server_url,
    sender_url,
    channels,
    rpcs_per_channel,
    security,
    receiver_creds,
    sender_creds,
    direction=grpc_lane_bench.DIRECTION_SERVER_TO_CLIENT,
    measured_bytes=4 * MB,
    warmup_bytes=MB,
    chunk_size=64 * 1024,
    window_size=MB,
    ack_interval=512 * 1024,
):
    server, servicer, port = grpc_lane_bench._start_server(server_url, security, receiver_creds)
    target = sender_url.format(port=port)
    try:
        results = grpc_lane_bench.run_sender(
            url=target,
            channel_count=channels,
            rpcs_per_channel=rpcs_per_channel,
            measured_bytes=measured_bytes,
            warmup_bytes=warmup_bytes,
            chunk_size=chunk_size,
            window_size=window_size,
            ack_interval=ack_interval,
            repeat=1,
            timeout=20,
            direction=direction,
            connection_security=security,
            credentials_dir=sender_creds,
        )
        assert not servicer.registry.records
    finally:
        server.stop(grace=0).wait(timeout=5)
        servicer.registry.stop()
    assert not [thread.name for thread in threading.enumerate() if thread.name.startswith("grpc_lane_")]
    assert results[0]["rss_peak_bytes"] >= results[0]["rss_after_warmup_bytes"]
    return results[0]


@pytest.mark.parametrize(
    "direction",
    [grpc_lane_bench.DIRECTION_CLIENT_TO_SERVER, grpc_lane_bench.DIRECTION_SERVER_TO_CLIENT],
)
def test_clear_loopback_proves_shared_rpc_and_physical_channel_topologies(direction):
    shared = _run_loopback(
        "grpc://127.0.0.1:0",
        "grpc://127.0.0.1:{port}",
        channels=1,
        rpcs_per_channel=2,
        security=ConnectionSecurity.CLEAR,
        receiver_creds=None,
        sender_creds=None,
        direction=direction,
    )
    physical = _run_loopback(
        "grpc://127.0.0.1:0",
        "grpc://127.0.0.1:{port}",
        channels=2,
        rpcs_per_channel=1,
        security=ConnectionSecurity.CLEAR,
        receiver_creds=None,
        sender_creds=None,
        direction=direction,
    )

    assert shared["logical_rpcs"] == 2
    assert shared["unique_peer_sockets"] == 1
    assert physical["logical_rpcs"] == 2
    assert physical["unique_peer_sockets"] == 2
    assert shared["peak_outstanding_bytes"] <= shared["window_bytes"]
    assert physical["peak_outstanding_bytes"] <= physical["window_bytes"]
    assert shared["direction"] == grpc_lane_bench.DIRECTION_NAMES[direction]
    assert shared["transport_security"] == ["insecure"]


def _make_tls_credentials(tmp_path):
    ca_key, ca_public = generate_keys()
    ca_identity = Identity("grpc-lane-test-ca")
    ca_cert = generate_cert(ca_identity, ca_identity, ca_key, ca_public, ca=True)
    server_key, server_public = generate_keys()
    server_identity = Identity("localhost")
    server_cert = generate_cert(
        server_identity,
        ca_identity,
        ca_key,
        server_public,
        server_default_host="localhost",
        server_additional_hosts=["127.0.0.1"],
    )

    receiver = tmp_path / "receiver"
    sender = tmp_path / "sender"
    receiver.mkdir()
    sender.mkdir()
    root_ca = serialize_cert(ca_cert)
    (receiver / "rootCA.pem").write_bytes(root_ca)
    (receiver / "server.crt").write_bytes(serialize_cert(server_cert))
    (receiver / "server.key").write_bytes(serialize_pri_key(server_key))
    (sender / "rootCA.pem").write_bytes(root_ca)
    return receiver, sender


def test_tls_loopback_uses_two_physical_connections_on_one_listener(tmp_path):
    receiver_creds, sender_creds = _make_tls_credentials(tmp_path)

    result = _run_loopback(
        "grpc://127.0.0.1:0",
        "grpc://127.0.0.1:{port}",
        channels=2,
        rpcs_per_channel=1,
        security=ConnectionSecurity.TLS,
        receiver_creds=receiver_creds,
        sender_creds=sender_creds,
    )

    assert result["unique_peer_sockets"] == 2
    assert result["peak_outstanding_bytes"] <= result["window_bytes"]
    assert result["direction"] == "server-to-client"
    assert result["transport_security"] == ["ssl"]


def test_lane_flow_limits_keep_ack_work_fixed_and_reject_chunk_deadlock():
    windows, acknowledgements = grpc_lane_bench._lane_flow_limits(4, 64 * MB, 16 * MB, 2 * MB)

    assert windows == [16 * MB] * 4
    assert acknowledgements == [16 * MB] * 4
    with pytest.raises(ValueError, match="cannot reach"):
        grpc_lane_bench._lane_flow_limits(1, 3 * MB, int(2.5 * MB), 2 * MB)


def test_server_to_client_handles_zero_warmup_and_partial_final_chunk():
    result = _run_loopback(
        "grpc://127.0.0.1:0",
        "grpc://127.0.0.1:{port}",
        channels=1,
        rpcs_per_channel=1,
        security=ConnectionSecurity.CLEAR,
        receiver_creds=None,
        sender_creds=None,
        warmup_bytes=0,
        measured_bytes=MB + 123,
        chunk_size=64 * 1024,
        window_size=64 * 1024,
        ack_interval=64 * 1024,
    )

    assert result["bytes"] == MB + 123
    assert result["peak_outstanding_bytes"] <= 64 * 1024


class _DeadlineContext:
    def __init__(self, remaining):
        self.remaining = remaining

    def time_remaining(self):
        return self.remaining

    def abort(self, _, details):
        raise RuntimeError(details)


@pytest.mark.parametrize("remaining", [None, grpc_lane_bench.MAX_SERVER_RPC_SECONDS + 1])
def test_server_rejects_unbounded_deadline_without_registering_run(remaining):
    servicer = grpc_lane_bench.LaneBenchServicer()
    context = _DeadlineContext(remaining)
    try:
        responses = list(servicer.Stream(iter([grpc_lane_bench.Frame(seq=0, data=_spec().encode())]), context))

        assert grpc_lane_bench._decode_control(responses[0]).kind == grpc_lane_bench.ACK_ERROR
        assert not servicer.registry.records
    finally:
        servicer.registry.stop()


def test_incomplete_topology_has_no_per_run_threads_and_is_reaped():
    registry = grpc_lane_bench.RunRegistry()
    spec = _spec(channel_count=2, lane_count=2)
    try:
        record = registry.register(spec, "ipv4:127.0.0.1:12345", ttl=100)

        assert record.sampler is None
        with registry.lock:
            record.expires_at = 0
        registry.reap_expired()
        assert not registry.records
    finally:
        registry.stop()
    assert not registry.reaper.is_alive()


def test_lane_cannot_complete_before_declared_topology_registers():
    registry = grpc_lane_bench.RunRegistry()
    spec = _spec(channel_count=2, lane_count=2)
    try:
        registry.register(spec, "ipv4:127.0.0.1:12345", ttl=100)

        with pytest.raises(ValueError, match="declared topology"):
            registry.complete(spec, spec.measured_bytes, 1)
        assert not registry.records
    finally:
        registry.stop()


@pytest.mark.parametrize(
    "direction,lane_type",
    [
        (grpc_lane_bench.DIRECTION_CLIENT_TO_SERVER, grpc_lane_bench.LaneClient),
        (grpc_lane_bench.DIRECTION_SERVER_TO_CLIENT, grpc_lane_bench.ServerToClientLaneClient),
    ],
)
def test_request_generator_close_does_not_mask_rpc_status_with_generator_exit(direction, lane_type):
    spec = _spec(direction=direction)
    common = {
        "stub": None,
        "spec": spec,
        "measure_event": threading.Event(),
        "outstanding": grpc_lane_bench.OutstandingTracker(),
        "timeout": 1,
    }
    if lane_type is grpc_lane_bench.LaneClient:
        lane = lane_type(lane_window=MB, payload_block=b"x" * spec.chunk_size, **common)
    else:
        lane = lane_type(**common)
    requests = lane.requests()

    assert next(requests).seq == 0
    requests.close()

    assert lane.error is None
