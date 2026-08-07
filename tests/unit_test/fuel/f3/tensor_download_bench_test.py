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

import argparse
import hashlib
from unittest.mock import MagicMock

import pytest
import torch

from dev_tools.f3 import tensor_download_bench
from dev_tools.f3.tensor_download_bench import (
    DIRECT_NEGOTIATION_KEY,
    DIRECT_TENSOR_MIN_BYTES,
    MODE_DISK,
    MODE_MEMORY,
    DirectPathTracker,
    build_transfer_payload,
    direct_path_manifest,
    direct_tensor_fingerprint,
    parse_modes,
    select_tensors,
    tensor_nbytes,
    unique_tensor_stats,
    unwrap_state_dict,
    validate_received_payload,
    validate_sender_fingerprints,
)
from nvflare.apis.fl_constant import ConnectionSecurity
from nvflare.fuel.f3.drivers.driver_params import DriverParams


class FakeLazyTensorRef:
    def __init__(self, tensor, file_path=None, key=None):
        self.tensor = tensor
        self.file_path = file_path
        self.key = key

    def materialize(self):
        return self.tensor


def test_parse_modes():
    assert parse_modes("memory,disk") == (MODE_MEMORY, MODE_DISK)
    assert parse_modes(" disk, memory, disk ") == (MODE_DISK, MODE_MEMORY)
    with pytest.raises(argparse.ArgumentTypeError):
        parse_modes("gpu")


def test_unwrap_and_select_tensors_by_binary_size():
    state_dict = {
        "large": torch.zeros(32, dtype=torch.float32),
        "medium": torch.zeros(8, dtype=torch.float32),
        "small": torch.zeros(2, dtype=torch.float32),
        "metadata": "ignored",
    }
    assert unwrap_state_dict({"state_dict": state_dict}) is state_dict

    selected = select_tensors(state_dict, max_bytes=40)
    assert list(selected) == ["small", "medium"]
    assert sum(tensor_nbytes(tensor) for tensor in selected.values()) == 40


def test_aliases_only_count_once_toward_selection_limit():
    shared = torch.zeros(8, dtype=torch.float32)
    state_dict = {
        "a_shared": shared,
        "b_shared": shared,
        "z_other": torch.zeros(8, dtype=torch.float32),
    }

    selected = select_tensors(state_dict, max_bytes=32)
    assert list(selected) == ["a_shared", "b_shared"]
    assert unique_tensor_stats(selected) == (1, 32)


def test_memory_and_disk_payload_validation(tmp_path):
    tensors = {
        "weight": torch.arange(12, dtype=torch.float32).reshape(3, 4),
        "bias": torch.tensor([1.0, 2.0]),
    }
    payload = build_transfer_payload(tmp_path / "model.pt", tensors)

    memory_result = validate_received_payload(payload, MODE_MEMORY)
    assert memory_result["tensor_count"] == 2
    assert memory_result["tensor_bytes"] == 56
    assert memory_result["transfer_bytes"] == 56

    disk_payload = {**payload, "tensors": {key: FakeLazyTensorRef(value) for key, value in tensors.items()}}
    disk_result = validate_received_payload(disk_payload, MODE_DISK)
    assert disk_result["tensor_count"] == 2
    assert disk_result["sample_materialized_bytes"] == 8


def test_disk_validation_counts_aliases_by_file_and_key(tmp_path):
    shared = torch.arange(4, dtype=torch.float32)
    tensors = {"shared_a": shared, "shared_b": shared}
    payload = build_transfer_payload(tmp_path / "model.pt", tensors)
    payload["tensors"] = {
        key: FakeLazyTensorRef(shared, file_path="/tmp/chunk.safetensors", key="T0") for key in tensors
    }

    result = validate_received_payload(payload, MODE_DISK)
    assert result["tensor_count"] == 2
    assert result["unique_tensor_count"] == 1


def test_direct_path_counts_and_hashes_large_direct_sample(tmp_path):
    large = torch.arange(
        DIRECT_TENSOR_MIN_BYTES // torch.empty((), dtype=torch.float32).element_size(), dtype=torch.float32
    )
    small = torch.tensor([7.0])
    tensors = {"large_weight": large, "small_bias": small}

    manifest = direct_path_manifest(tensors)
    assert manifest["eligible_items"] == 1
    assert manifest["eligible_bytes"] == DIRECT_TENSOR_MIN_BYTES
    assert manifest["fallback_items"] == 1
    assert manifest["fallback_bytes"] == tensor_nbytes(small)
    assert manifest["sample"]["key"] == "large_weight"
    assert manifest["sample"]["num_bytes"] >= DIRECT_TENSOR_MIN_BYTES

    payload = build_transfer_payload(tmp_path / "model.pt", tensors)
    tracker = DirectPathTracker()
    tracker.reset("run-1")

    class DirectItem:
        tensor = large

        def __len__(self):
            return tensor_nbytes(self.tensor) + 128

    tracker.record([DirectItem()])
    result = validate_received_payload(payload, MODE_MEMORY, tracker.snapshot("run-1"))

    assert result["sample_key"] == "small_bias"
    assert result["direct_items"] == 1
    assert result["direct_bytes"] == DIRECT_TENSOR_MIN_BYTES
    assert result["direct_wire_bytes"] == DIRECT_TENSOR_MIN_BYTES + 128
    assert result["fallback_items"] == 1
    assert result["fallback_bytes"] == tensor_nbytes(small)
    assert result["direct_sample_key"] == "large_weight"
    assert result["direct_sample_materialized_bytes"] >= DIRECT_TENSOR_MIN_BYTES


def test_disabled_direct_control_reports_eligibility_and_zero_direct_items(tmp_path):
    large = torch.arange(DIRECT_TENSOR_MIN_BYTES, dtype=torch.uint8)
    small = torch.tensor([7.0])
    payload = build_transfer_payload(tmp_path / "model.pt", {"large": large, "small": small})

    result = validate_received_payload(
        payload,
        MODE_MEMORY,
        direct_negotiation_enabled=False,
    )

    assert result[DIRECT_NEGOTIATION_KEY] is False
    assert result["direct_eligible_items"] == 1
    assert result["direct_eligible_bytes"] == DIRECT_TENSOR_MIN_BYTES
    assert result["direct_items"] == 0
    assert result["direct_bytes"] == 0
    assert result["fallback_items"] == 2
    assert result["fallback_bytes"] == DIRECT_TENSOR_MIN_BYTES + tensor_nbytes(small)
    assert result["direct_sample_sha256"] == direct_tensor_fingerprint(large)


def test_disabled_direct_control_rejects_observed_direct_item(tmp_path):
    large = torch.zeros(DIRECT_TENSOR_MIN_BYTES, dtype=torch.uint8)
    payload = build_transfer_payload(tmp_path / "model.pt", {"large": large})
    direct_stats = {
        "items": 1,
        "tensor_bytes": tensor_nbytes(large),
        "wire_bytes": tensor_nbytes(large),
        "tensor_ids": {id(large)},
    }

    with pytest.raises(ValueError, match=r"expected 0 item\(s\) / 0 bytes"):
        validate_received_payload(
            payload,
            MODE_MEMORY,
            direct_stats,
            direct_negotiation_enabled=False,
        )


def test_direct_tracking_suppresses_capability_advertisement_for_control(monkeypatch):
    tracker = DirectPathTracker()
    original_consume_direct_chunk = tensor_download_bench.TensorConsumer.consume_direct_chunk
    original_get_initial_state = tensor_download_bench.TensorConsumer.get_initial_state

    with monkeypatch.context() as patch:
        patch.setattr(tensor_download_bench, "_DIRECT_PATH_TRACKER", tracker)
        patch.setattr(tensor_download_bench, "_DIRECT_PATH_TRACKING_INSTALLED", False)
        # Register undo entries for the production methods that the installer
        # deliberately replaces for the lifetime of the benchmark receiver.
        patch.setattr(
            tensor_download_bench.TensorConsumer,
            "consume_direct_chunk",
            original_consume_direct_chunk,
        )
        patch.setattr(tensor_download_bench.TensorConsumer, "get_initial_state", original_get_initial_state)
        tensor_download_bench.install_direct_path_tracking()
        consumer = tensor_download_bench.TensorConsumer(None, {})

        tracker.reset("control", direct_negotiation_enabled=False)
        assert consumer.get_initial_state() is None

        tracker.reset("candidate", direct_negotiation_enabled=True)
        assert consumer.get_initial_state() == original_get_initial_state(consumer)


@pytest.mark.parametrize(
    ("extra_args", "expected_enabled"),
    [([], True), (["--disable-direct"], False)],
)
def test_sender_cli_coordinates_direct_negotiation(monkeypatch, extra_args, expected_enabled):
    captured = {}
    monkeypatch.setattr(
        tensor_download_bench,
        "resolve_cell_security",
        lambda *args, **kwargs: (False, {}),
    )
    monkeypatch.setattr(tensor_download_bench, "f3_config_summary", lambda: "test config")
    monkeypatch.setattr(tensor_download_bench, "run_sender", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr("sys.argv", ["tensor_download_bench.py", "send", *extra_args])

    tensor_download_bench.main()

    assert captured[DIRECT_NEGOTIATION_KEY] is expected_enabled


def test_direct_tensor_fingerprint_hashes_raw_storage():
    tensor = torch.arange(DIRECT_TENSOR_MIN_BYTES, dtype=torch.uint8)
    expected = hashlib.sha256(memoryview(tensor.numpy())).hexdigest()

    assert direct_tensor_fingerprint(tensor) == expected


def test_sender_fingerprint_detects_direct_tensor_corruption(tmp_path):
    sender_large = torch.arange(
        DIRECT_TENSOR_MIN_BYTES // torch.empty((), dtype=torch.float32).element_size(), dtype=torch.float32
    )
    sender_tensors = {"small": torch.tensor([1.0]), "large": sender_large}
    payload = build_transfer_payload(tmp_path / "model.pt", sender_tensors)
    receiver_large = sender_large.clone()
    receiver_large[0] = -1
    payload["tensors"] = {"small": sender_tensors["small"].clone(), "large": receiver_large}

    direct_stats = {
        "items": 1,
        "tensor_bytes": tensor_nbytes(receiver_large),
        "wire_bytes": tensor_nbytes(receiver_large),
        "tensor_ids": {id(receiver_large)},
    }
    result = validate_received_payload(payload, MODE_MEMORY, direct_stats)

    with pytest.raises(ValueError, match="direct sample tensor sha256 mismatch"):
        validate_sender_fingerprints(result, payload, sender_tensors, MODE_MEMORY)


def test_disk_mode_reports_all_items_as_fallback(tmp_path):
    large = torch.zeros(
        DIRECT_TENSOR_MIN_BYTES // torch.empty((), dtype=torch.float32).element_size(), dtype=torch.float32
    )
    small = torch.tensor([1.0])
    tensors = {"large": large, "small": small}
    payload = build_transfer_payload(tmp_path / "model.pt", tensors)
    payload["tensors"] = {
        key: FakeLazyTensorRef(value, file_path=f"/tmp/{key}.safetensors", key=key) for key, value in tensors.items()
    }

    result = validate_received_payload(payload, MODE_DISK)

    assert result["direct_eligible_items"] == 1
    assert result["direct_items"] == 0
    assert result["fallback_items"] == 2
    assert result["fallback_bytes"] == tensor_nbytes(large) + tensor_nbytes(small)
    assert result["direct_sample_key"] == "large"
    assert result["direct_sample_materialized_bytes"] == 0
    assert result["direct_sample_sha256"] is None


def test_payload_construction_does_not_hash_or_warm_tensor_storage(monkeypatch, tmp_path):
    large = torch.zeros(DIRECT_TENSOR_MIN_BYTES, dtype=torch.uint8)
    monkeypatch.setattr(
        tensor_download_bench,
        "tensor_fingerprint",
        lambda _tensor: (_ for _ in ()).throw(AssertionError("unexpected pre-transfer hash")),
    )

    payload = build_transfer_payload(tmp_path / "model.pt", {"large": large})

    assert payload["direct_path"]["sample"]["key"] == "large"


def test_memory_run_requires_a_direct_eligible_tensor(tmp_path):
    cell = MagicMock()

    with pytest.raises(ValueError, match="requires at least one direct-path eligible tensor"):
        tensor_download_bench.run_one_sender_mode(
            cell=cell,
            url="tcp://receiver:8002",
            checkpoint=tmp_path / "model.pt",
            tensors={"small": torch.tensor([1.0])},
            mode=MODE_MEMORY,
            repetition=1,
            timeout=10,
        )

    cell.send_request.assert_not_called()


def test_tensor_sender_passes_tls_credentials(monkeypatch, tmp_path):
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

    monkeypatch.setattr(tensor_download_bench, "Cell", FakeCell)
    monkeypatch.setattr(tensor_download_bench, "register_tensor_decomposer", lambda: None)
    monkeypatch.setattr(tensor_download_bench, "load_checkpoint", lambda *args, **kwargs: {})
    credentials_dir = tmp_path / "credentials"
    credentials_dir.mkdir()
    (credentials_dir / "rootCA.pem").write_text("placeholder rootCA.pem", encoding="utf-8")

    tensor_download_bench.run_sender(
        url="grpc://receiver:8002",
        checkpoint=tmp_path / "model.pt",
        modes=(),
        repeat=1,
        timeout=10,
        connect_timeout=1,
        max_bytes=None,
        connection_security=ConnectionSecurity.TLS,
        credentials_dir=credentials_dir,
    )

    assert FakeCell.instance.stopped
    assert FakeCell.instance.args == (tensor_download_bench.TX_FQCN, "grpc://receiver:8002")
    assert FakeCell.instance.kwargs["secure"] is True
    assert FakeCell.instance.kwargs["credentials"] == {
        DriverParams.CONNECTION_SECURITY.value: ConnectionSecurity.TLS,
        DriverParams.CA_CERT.value: str(credentials_dir / "rootCA.pem"),
    }


def test_tensor_receiver_passes_tls_server_credentials(monkeypatch, tmp_path):
    class FakeCell:
        instance = None

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.stopped = False
            FakeCell.instance = self

        def register_request_cb(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            self.stopped = True

    def stop_receiver(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(tensor_download_bench, "Cell", FakeCell)
    monkeypatch.setattr(tensor_download_bench, "install_direct_path_tracking", lambda: None)
    monkeypatch.setattr(tensor_download_bench, "register_tensor_decomposer", lambda: None)
    monkeypatch.setattr(tensor_download_bench.time, "sleep", stop_receiver)
    credentials_dir = tmp_path / "credentials"
    credentials_dir.mkdir()
    for name in ("rootCA.pem", "server.crt", "server.key"):
        (credentials_dir / name).write_text(f"placeholder {name}", encoding="utf-8")

    tensor_download_bench.run_receiver(
        url="grpc://0.0.0.0:8002",
        offload_dir=tmp_path / "offload",
        sample_interval=0.1,
        connection_security=ConnectionSecurity.TLS,
        credentials_dir=credentials_dir,
    )

    assert FakeCell.instance.stopped
    assert FakeCell.instance.args == (tensor_download_bench.RX_FQCN, "grpc://0.0.0.0:8002")
    assert FakeCell.instance.kwargs["secure"] is True
    assert FakeCell.instance.kwargs["credentials"] == {
        DriverParams.CONNECTION_SECURITY.value: ConnectionSecurity.TLS,
        DriverParams.CA_CERT.value: str(credentials_dir / "rootCA.pem"),
        DriverParams.SERVER_CERT.value: str(credentials_dir / "server.crt"),
        DriverParams.SERVER_KEY.value: str(credentials_dir / "server.key"),
    }
