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
from unittest.mock import MagicMock

import pytest

from dev_tools.f3 import cellnet_bench
from nvflare.apis.fl_constant import ConnectionSecurity
from nvflare.fuel.f3.drivers.driver_params import DriverParams
from nvflare.fuel.f3.streaming.byte_receiver import ACK_INTERVAL
from nvflare.fuel.f3.streaming.byte_streamer import STREAM_CHUNK_SIZE, STREAM_WINDOW_SIZE
from nvflare.fuel.f3.streaming.stream_const import STREAM_ACK_INTERVAL, STREAM_RETRY_MAX_PENDING_BYTES


def test_benchmark_defaults_match_f3_streaming_defaults():
    assert cellnet_bench.DEFAULT_F3_CHUNK_SIZE == STREAM_CHUNK_SIZE == 1024**2
    assert cellnet_bench.DEFAULT_F3_WINDOW_SIZE == STREAM_WINDOW_SIZE == 64 * 1024**2
    assert STREAM_ACK_INTERVAL == 16 * 1024**2
    assert ACK_INTERVAL == 4 * 1024**2
    assert STREAM_RETRY_MAX_PENDING_BYTES == 128 * 1024**2


@pytest.mark.parametrize(
    "url, expected",
    [
        ("tcp://127.0.0.1:8002", ("127.0.0.1", 8002)),
        ("tcp://example.test:1234/", ("example.test", 1234)),
        ("tcp://[::1]:9000", ("::1", 9000)),
    ],
)
def test_parse_tcp_url(url, expected):
    assert cellnet_bench.parse_tcp_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8002",
        "tcp://127.0.0.1",
        "tcp://127.0.0.1:invalid",
        "tcp://127.0.0.1:8002/path",
    ],
)
def test_parse_tcp_url_rejects_invalid_url(url):
    with pytest.raises(ValueError):
        cellnet_bench.parse_tcp_url(url)


def test_raw_tcp_sender_reports_end_to_end_baseline(capsys):
    buffer_size = 256 * 1024
    warmup_size = buffer_size * 2 + 17
    payload_size = buffer_size * 8 + 123
    listener = cellnet_bench._open_tcp_listener("127.0.0.1", 0)
    port = listener.getsockname()[1]
    receiver_result = {}
    receiver_error = []

    def receive_once():
        try:
            with listener:
                conn, _ = listener.accept()
                with conn:
                    receiver_result["value"] = cellnet_bench._receive_tcp_payload(conn, buffer_size)
        except Exception as ex:
            receiver_error.append(ex)

    receiver = threading.Thread(target=receive_once)
    receiver.start()
    cellnet_bench.run_tcp_sender(
        f"tcp://127.0.0.1:{port}",
        payload_size,
        buffer_size,
        warmup_size=warmup_size,
    )
    receiver.join(timeout=10)

    assert not receiver.is_alive()
    assert not receiver_error
    assert receiver_result["value"][0] == payload_size
    output = capsys.readouterr().out
    assert "[tcp-send] TCP_BASELINE_NO_F3" in output
    assert f"warmup_bytes={warmup_size}" in output
    assert f"bytes={payload_size}" in output
    assert "mib_per_sec=" in output
    assert "gbit_per_sec=" in output
    assert "receiver_mib_per_sec=" in output
    assert "target_gbit_per_sec=25.000" in output
    assert "target_utilization_pct=" in output


@pytest.mark.parametrize(
    "value, expected",
    [
        (1024, 1024),
        ("1024", 1024),
        ("128K", 128 * 1024),
        ("16M", 16 * 1024**2),
        ("2G", 2 * 1024**3),
        ("1.5M", 1_572_864),
        ("2GiB", 2 * 1024**3),
        ("16mb", 16 * 1024**2),
    ],
)
def test_parse_byte_size_uses_binary_units(value, expected):
    assert cellnet_bench.parse_byte_size(value) == expected


def test_configure_f3_loads_chunk_and_window_sizes(tmp_path):
    config_file = tmp_path / "comm_config.yml"
    config_file.write_text(
        "\n".join(
            [
                "streaming_chunk_size: 4M",
                "streaming_window_size: 256M",
                "streaming_ack_interval: 64M",
                "tcp_async_send: true",
                "tcp_bulk_lanes: 2",
                "tcp_send_queue_bytes: 32M",
                "grpc:",
                "  max_workers: 32",
                "  options:",
                "    - [grpc.max_send_message_length, 2G]",
            ]
        ),
        encoding="utf-8",
    )

    try:
        loaded_path, config = cellnet_bench.configure_f3(str(config_file))
        configurator = cellnet_bench.CommConfigurator()

        assert loaded_path == config_file
        assert config["grpc"]["max_workers"] == 32
        assert config["grpc"]["options"][0][1] == 2 * 1024**3
        assert configurator.get_streaming_chunk_size(1) == 4194304
        assert configurator.get_streaming_window_size(1) == 268435456
        assert configurator.get_tcp_async_send(False) is True
        assert configurator.get_tcp_bulk_lanes(0) == 2
        assert configurator.get_tcp_send_queue_bytes(1) == 32 * 1024**2
        assert "streaming_chunk_size=4,194,304" in cellnet_bench.f3_config_summary()
    finally:
        cellnet_bench.ConfigService.reset()
        cellnet_bench.CommConfigurator.reset()


@pytest.mark.parametrize(
    "config_text, error",
    [
        ("- not-a-mapping\n", "must be a YAML mapping"),
        ("streaming_chunk_size: 0\n", "streaming_chunk_size must be a positive integer"),
        ("streaming_chunk_size: 16Mbps\n", "has invalid byte size"),
        ("streaming_chunk_size: 0.1K\n", "does not resolve to a whole number of bytes"),
        (
            "streaming_chunk_size: 4194304\nstreaming_window_size: 1048576\n",
            "streaming_window_size .* must be at least streaming_chunk_size",
        ),
        (
            "streaming_window_size: 16777216\nstreaming_ack_interval: 33554432\n",
            "streaming_ack_interval .* must not exceed streaming_window_size",
        ),
        ("tcp_async_send: yes-please\n", "tcp_async_send must be a boolean"),
        ("tcp_async_send: false\ntcp_bulk_lanes: 2\n", "requires tcp_async_send"),
        ("tcp_async_send: true\ntcp_bulk_lanes: 5\n", "tcp_bulk_lanes must be between"),
        (
            "streaming_chunk_size: 2M\ntcp_async_send: true\ntcp_send_queue_bytes: 2M\n",
            "tcp_send_queue_bytes .* must exceed streaming_chunk_size",
        ),
        ("tcp_handshake_timeout: 0\n", "tcp_handshake_timeout must be positive"),
    ],
)
def test_configure_f3_rejects_invalid_streaming_settings(tmp_path, config_text, error):
    config_file = tmp_path / "comm_config.yml"
    config_file.write_text(config_text, encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        cellnet_bench.configure_f3(str(config_file))


def test_generated_stream_uses_configured_block_size():
    block_size = 2 * cellnet_bench.MB
    stream = cellnet_bench.GeneratedStream(block_size + 17, block_size=block_size)

    assert len(stream.read(block_size)) == block_size
    assert len(stream.read(block_size)) == 17


def _make_credentials_dir(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_text(f"placeholder {name}", encoding="utf-8")
    return tmp_path


def test_build_cell_credentials_clear_does_not_use_credentials():
    assert cellnet_bench.build_cell_credentials(cellnet_bench.TX_FQCN, ConnectionSecurity.CLEAR, None) == (False, {})


@pytest.mark.parametrize(
    "role,security,files,expected_keys",
    [
        (
            cellnet_bench.RX_FQCN,
            ConnectionSecurity.TLS,
            ("rootCA.pem", "server.crt", "server.key"),
            (DriverParams.CA_CERT, DriverParams.SERVER_CERT, DriverParams.SERVER_KEY),
        ),
        (
            cellnet_bench.TX_FQCN,
            ConnectionSecurity.TLS,
            ("rootCA.pem",),
            (DriverParams.CA_CERT,),
        ),
        (
            cellnet_bench.RX_FQCN,
            ConnectionSecurity.MTLS,
            ("rootCA.pem", "server.crt", "server.key"),
            (DriverParams.CA_CERT, DriverParams.SERVER_CERT, DriverParams.SERVER_KEY),
        ),
        (
            cellnet_bench.TX_FQCN,
            ConnectionSecurity.MTLS,
            ("rootCA.pem", "client.crt", "client.key"),
            (DriverParams.CA_CERT, DriverParams.CLIENT_CERT, DriverParams.CLIENT_KEY),
        ),
    ],
)
def test_build_cell_credentials_resolves_role_files(tmp_path, role, security, files, expected_keys):
    credential_dir = _make_credentials_dir(tmp_path, *files)

    secure, credentials = cellnet_bench.build_cell_credentials(role, security, credential_dir)

    assert secure is True
    assert credentials[DriverParams.CONNECTION_SECURITY.value] == security
    assert set(credentials) == {DriverParams.CONNECTION_SECURITY.value, *(key.value for key in expected_keys)}
    for key in expected_keys:
        assert credentials[key.value].startswith(str(credential_dir))


def test_build_cell_credentials_reports_missing_role_files(tmp_path):
    _make_credentials_dir(tmp_path, "rootCA.pem")

    with pytest.raises(ValueError, match=r"missing: server\.crt, server\.key"):
        cellnet_bench.build_cell_credentials(cellnet_bench.RX_FQCN, ConnectionSecurity.TLS, tmp_path)


def test_grpc_tls_profile_selects_synchronous_grpc():
    profile = cellnet_bench.Path(cellnet_bench.__file__).with_name("grpc_tls") / "comm_config.yml"
    with profile.open(encoding="utf-8") as stream:
        config = cellnet_bench.normalize_f3_config(cellnet_bench.yaml.safe_load(stream))

    cellnet_bench.validate_f3_config(config)
    assert config["adhoc_conn_scheme"] == "grpc"
    assert config["internal_conn_scheme"] == "grpc"
    assert config["use_aio_grpc"] is False
    assert config["grpc"]["max_workers"] == 100
    assert config["streaming_chunk_size"] == cellnet_bench.MB
    assert config["streaming_window_size"] == 64 * cellnet_bench.MB


def test_native_tls_profile_enables_two_bulk_lanes_on_one_stcp_listener():
    profile = cellnet_bench.Path(cellnet_bench.__file__).with_name("native_tls") / "comm_config.yml"
    with profile.open(encoding="utf-8") as stream:
        config = cellnet_bench.normalize_f3_config(cellnet_bench.yaml.safe_load(stream))

    cellnet_bench.validate_f3_config(config)
    assert config["adhoc_conn_scheme"] == "stcp"
    assert config["internal_conn_scheme"] == "stcp"
    assert config["tcp_async_send"] is True
    assert config["tcp_bulk_lanes"] == 2
    assert config["tcp_send_queue_bytes"] == 64 * cellnet_bench.MB
    assert config["streaming_window_size"] == 64 * cellnet_bench.MB


@pytest.mark.parametrize(
    "role,url,security,credentials_dir,error",
    [
        (cellnet_bench.TX_FQCN, "tcp://receiver:8002", ConnectionSecurity.TLS, None, "requires a grpc"),
        (cellnet_bench.TX_FQCN, "grpcs://receiver:8002", ConnectionSecurity.CLEAR, None, "requires"),
        (cellnet_bench.TX_FQCN, "stcp://receiver:8002", ConnectionSecurity.CLEAR, None, "requires"),
        (cellnet_bench.TX_FQCN, "grpc://receiver:8002", ConnectionSecurity.TLS, None, "is required"),
    ],
)
def test_resolve_cell_security_rejects_inconsistent_configuration(role, url, security, credentials_dir, error):
    with pytest.raises(ValueError, match=error):
        cellnet_bench.resolve_cell_security(role, url, security, credentials_dir)


def test_resolve_cell_security_enables_stcp_hostname_verification(tmp_path):
    credentials_dir = _make_credentials_dir(tmp_path, "rootCA.pem")

    secure, credentials = cellnet_bench.resolve_cell_security(
        cellnet_bench.TX_FQCN,
        "stcp://receiver.example.test:8002",
        ConnectionSecurity.TLS,
        credentials_dir,
    )

    assert secure is True
    assert credentials == {
        DriverParams.CONNECTION_SECURITY.value: ConnectionSecurity.TLS,
        DriverParams.CA_CERT.value: str(credentials_dir / "rootCA.pem"),
        DriverParams.VERIFY_HOSTNAME.value: True,
    }


def test_cellnet_sender_passes_tls_credentials_and_cleans_up_on_failure(monkeypatch, tmp_path):
    class FakeCell:
        instance = None

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.connected_cb = None
            self.stopped = False
            FakeCell.instance = self

        def set_cell_connected_cb(self, cb):
            self.connected_cb = cb

        def start(self):
            self.connected_cb(None)

        def stop(self):
            self.stopped = True

    class FakeStreamCell:
        def __init__(self, cell):
            pass

        def get_chunk_size(self):
            return 1024

        def send_stream(self, *args, **kwargs):
            raise RuntimeError("send failed")

    sampler = MagicMock()
    monkeypatch.setattr(cellnet_bench, "CoreCell", FakeCell)
    monkeypatch.setattr(cellnet_bench, "StreamCell", FakeStreamCell)
    monkeypatch.setattr(cellnet_bench, "MemSampler", lambda: sampler)
    monkeypatch.setattr(cellnet_bench.time, "sleep", lambda _seconds: None)
    credentials_dir = _make_credentials_dir(tmp_path, "rootCA.pem")

    with pytest.raises(RuntimeError, match="send failed"):
        cellnet_bench.run_sender(
            "grpc://receiver:8002",
            1024,
            reliable=True,
            connection_security=ConnectionSecurity.TLS,
            credentials_dir=credentials_dir,
        )

    sampler.start.assert_called_once_with()
    sampler.stop.assert_called_once_with()
    assert FakeCell.instance.stopped
    assert FakeCell.instance.args == (cellnet_bench.TX_FQCN, "grpc://receiver:8002")
    assert FakeCell.instance.kwargs["secure"] is True
    assert FakeCell.instance.kwargs["credentials"] == {
        DriverParams.CONNECTION_SECURITY.value: ConnectionSecurity.TLS,
        DriverParams.CA_CERT.value: str(credentials_dir / "rootCA.pem"),
    }


def test_cellnet_receiver_passes_tls_server_credentials(monkeypatch, tmp_path):
    class FakeCell:
        instance = None

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.stopped = False
            FakeCell.instance = self

        def start(self):
            pass

        def stop(self):
            self.stopped = True

    class FakeStreamCell:
        def __init__(self, cell):
            pass

        def register_stream_cb(self, *args, **kwargs):
            pass

    monkeypatch.setattr(cellnet_bench, "CoreCell", FakeCell)
    monkeypatch.setattr(cellnet_bench, "StreamCell", FakeStreamCell)

    def stop_receiver(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(cellnet_bench.time, "sleep", stop_receiver)
    credentials_dir = _make_credentials_dir(tmp_path, "rootCA.pem", "server.crt", "server.key")

    cellnet_bench.run_receiver(
        "grpc://0.0.0.0:8002",
        connection_security=ConnectionSecurity.TLS,
        credentials_dir=credentials_dir,
    )

    assert FakeCell.instance.stopped
    assert FakeCell.instance.args == (cellnet_bench.RX_FQCN, "grpc://0.0.0.0:8002")
    assert FakeCell.instance.kwargs["secure"] is True
    assert FakeCell.instance.kwargs["credentials"] == {
        DriverParams.CONNECTION_SECURITY.value: ConnectionSecurity.TLS,
        DriverParams.CA_CERT.value: str(credentials_dir / "rootCA.pem"),
        DriverParams.SERVER_CERT.value: str(credentials_dir / "server.crt"),
        DriverParams.SERVER_KEY.value: str(credentials_dir / "server.key"),
    }
