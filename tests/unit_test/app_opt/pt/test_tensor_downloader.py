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

"""Unit tests for TensorDownloadable.

Note: Deep copy protection is now handled at broadcast level in WFCommServer,
not in TensorDownloadable itself. These tests verify the Downloadable's basic behavior.
"""

import gc
import json
import multiprocessing as mp
import time
import uuid
from types import SimpleNamespace

import pytest
import torch
from safetensors.torch import load as load_tensors

import nvflare.app_opt.pt.tensor_downloader as tensor_downloader
from nvflare.app_opt.pt.tensor_downloader import (
    DiskTensorConsumer,
    TensorConsumer,
    TensorDownloadable,
    _serialize_tensor_item,
    _StreamedTensorItem,
    add_tensors,
    download_tensors,
)
from nvflare.fuel.f3.cellnet.cell import Cell
from nvflare.fuel.f3.cellnet.core_cell import CoreCell
from nvflare.fuel.f3.streaming.download_service import DirectDownloadChunk, ProduceRC
from nvflare.fuel.f3.streaming.obj_downloader import ObjectDownloader
from nvflare.fuel.utils import fobs
from nvflare.fuel.utils.network_utils import get_open_ports


def _native_bulk_cell(transport, expected_fqcn=None):
    def require_match(fqcn, peer_cn, _description):
        if expected_fqcn is not None:
            assert fqcn == expected_fqcn
        assert peer_cn

    return SimpleNamespace(
        get_native_bulk_transport=transport,
        core_cell=SimpleNamespace(
            communicator=SimpleNamespace(
                conn_manager=SimpleNamespace(identity_resolver=SimpleNamespace(require_match=require_match))
            )
        ),
    )


def test_download_tensors_advertises_native_bulk_only_when_transport_is_usable(monkeypatch):
    captured = []

    def fake_download_object(**kwargs):
        captured.append(kwargs["consumer"].get_initial_state())

    monkeypatch.setattr(tensor_downloader, "download_object", fake_download_object)
    unavailable = SimpleNamespace(get_native_bulk_transport=lambda *_args: None)
    available = SimpleNamespace(get_native_bulk_transport=lambda *_args: (object(), object(), "peer"))

    download_tensors("source", "ref", 10, unavailable)
    download_tensors("source", "ref", 10, available)

    assert tensor_downloader._TENSOR_NATIVE_BULK_STATE_KEY not in captured[0]
    assert captured[1][tensor_downloader._TENSOR_NATIVE_BULK_STATE_KEY] == tensor_downloader._TENSOR_NATIVE_BULK_V1


def _materialize_item(item) -> bytes:
    """Apply the same FOBS externalize/internalize step used by Cell messages."""
    return fobs.loads(fobs.dumps(item, buffer_list=True))


def _run_batched_tensor_client(port: int, server_name: str, ref_id: str, result_queue):
    client_name = f"tensor-client-{uuid.uuid4().hex[:8]}"
    client = Cell(client_name, f"tcp://localhost:{port}", secure=False, credentials={})
    direct_calls = []
    original_consume_direct = TensorConsumer.consume_direct_chunk

    def track_direct_buffer(consumer, data):
        view = memoryview(data)
        items = original_consume_direct(consumer, data)
        direct_calls.append((len(items), view.readonly, view.c_contiguous, len(view)))
        return items

    TensorConsumer.consume_direct_chunk = track_direct_buffer
    try:
        client.core_cell.start()
        deadline = time.monotonic() + 10.0
        while not client.core_cell.is_cell_connected(server_name) and time.monotonic() < deadline:
            time.sleep(0.05)
        if not client.core_cell.is_cell_connected(server_name):
            raise RuntimeError(f"client did not connect to {server_name}")

        error, result = download_tensors(server_name, ref_id, 30.0, client)
        if error:
            raise RuntimeError(error)
        expected_keys = {f"weight_{index}" for index in range(3)}
        if set(result) != expected_keys:
            raise RuntimeError(f"unexpected tensor keys: {sorted(result)}")
        for index in range(3):
            tensor = result[f"weight_{index}"]
            if not torch.all(tensor == index):
                raise RuntimeError(f"tensor weight_{index} did not round-trip")

        retained = result["weight_0"]
        del result
        gc.collect()
        retained[0] = 7
        result_queue.put(("ok", direct_calls, int(retained[0])))
    except Exception as ex:
        result_queue.put(("error", repr(ex)))
    finally:
        TensorConsumer.consume_direct_chunk = original_consume_direct
        client.core_cell.stop()
        CoreCell.ALL_CELLS.pop(client_name, None)


class TestTensorDownloadableBasic:
    """Test basic TensorDownloadable functionality."""

    def test_basic_functionality(self):
        """Verify basic Downloadable creation and data access."""
        # Create tensors
        tensors = {
            "weights": torch.tensor([[1.0, 2.0], [3.0, 4.0]]),
            "bias": torch.tensor([0.5, 1.5]),
        }

        # Create downloadable
        downloadable = TensorDownloadable(tensors=tensors, max_chunk_size=1024)

        # Verify basic properties
        assert downloadable.size == 2
        assert set(downloadable.keys) == {"weights", "bias"}
        assert torch.allclose(downloadable.base_obj["weights"], tensors["weights"])
        assert torch.allclose(downloadable.base_obj["bias"], tensors["bias"])

    def test_shares_memory_with_original(self):
        """Verify that Downloadable references original tensors (no copy at this level)."""
        original = {"layer": torch.tensor([1.0, 2.0, 3.0])}

        downloadable = TensorDownloadable(tensors=original, max_chunk_size=1024)

        # Should share memory (snapshot is done at broadcast level, not here)
        assert (
            downloadable.base_obj["layer"].data_ptr() == original["layer"].data_ptr()
        ), "Downloadable should share memory with original (copy is done at broadcast level)"

    def test_modification_affects_downloadable(self):
        """Verify that modifications to original DO affect Downloadable (by design).

        Note: Protection against this is now handled at broadcast level in WFCommServer.
        """
        tensors = {"model": torch.tensor([1.0, 2.0])}

        downloadable = TensorDownloadable(tensors=tensors, max_chunk_size=1024)

        # Modify original
        tensors["model"][0] = 999.0

        # Downloadable IS affected (this is expected - protection is at broadcast level)
        assert downloadable.base_obj["model"][0].item() == 999.0

    def test_prefetches_next_tensor(self):
        tensors = {
            "first": torch.tensor([1.0]),
            "second": torch.tensor([2.0]),
        }
        downloadable = TensorDownloadable(tensors=tensors, max_chunk_size=1)

        rc, first_items, state = downloadable.produce({}, "receiver")

        assert rc == ProduceRC.OK
        assert load_tensors(_materialize_item(first_items[0]))["first"].item() == 1.0
        assert 1 in downloadable._prefetch_futures

        rc, second_items, state = downloadable.produce(state, "receiver")

        assert rc == ProduceRC.OK
        assert load_tensors(_materialize_item(second_items[0]))["second"].item() == 2.0
        assert not downloadable._prefetch_futures

    def test_prefetch_does_not_queue_two_oversized_tensors(self):
        tensors = {
            "first": torch.tensor([1.0]),
            "second": torch.zeros(1024),
            "third": torch.zeros(1024),
        }
        downloadable = TensorDownloadable(tensors=tensors, max_chunk_size=1)

        downloadable.produce({}, "receiver")

        assert 1 in downloadable._prefetch_futures
        assert 2 not in downloadable._prefetch_futures
        downloadable.release()

    def test_release_disables_prefetch_and_produce(self):
        tensors = {
            "first": torch.tensor([1.0]),
            "second": torch.tensor([2.0]),
        }
        downloadable = TensorDownloadable(tensors=tensors, max_chunk_size=1)

        downloadable.release()

        assert downloadable.base_obj is None
        downloadable.prefetch_item(1)
        assert not downloadable._prefetch_futures
        assert downloadable.get_item_size(0) is None
        with pytest.raises(RuntimeError, match="released"):
            downloadable.produce_item(0)

    def test_native_bulk_offer_is_idempotent_and_accounts_after_completion(self):
        class Manager:
            lanes = 2
            max_bytes = 1024 * 1024

            def __init__(self):
                self.registered = []
                self.cancelled = []

            def register_send(self, peer_cn, lanes, segments):
                self.registered.append((peer_cn, lanes, segments))
                return "01" * 16

            @staticmethod
            def wait_completed(token, peer_cn):
                return True, None

            @staticmethod
            def pop_completed(token, peer_cn):
                return True

            def cancel(self, token):
                self.cancelled.append(token)

        manager = Manager()
        cell = _native_bulk_cell(
            lambda requester, mode: (manager, SimpleNamespace(), "receiver-cert"), expected_fqcn="receiver"
        )
        tensors = {"a": torch.arange(4, dtype=torch.float32), "b": torch.arange(8, dtype=torch.int64)}
        downloadable = TensorDownloadable(tensors, max_chunk_size=1)
        downloadable.num_receivers = 1
        state = TensorConsumer(None, {}).get_initial_state()

        rc, offer, next_state, bytes_delta, items_delta = downloadable.produce_native_bulk(state, "receiver", cell)
        assert rc == ProduceRC.OK
        assert offer["direction"] == "pull"
        assert offer["lanes"] == 2
        assert bytes_delta == items_delta == 0
        assert len(manager.registered) == 1

        repeated = downloadable.produce_native_bulk(state, "receiver", cell)
        assert repeated[0] == ProduceRC.OK
        assert repeated[1] == offer
        assert len(manager.registered) == 1

        segments = manager.registered[0][2]
        acquired = []
        for segment in segments:
            owner, view = segment.acquire()
            acquired.append((owner, bytes(view)))
        assert torch.equal(acquired[0][0], tensors["a"])
        assert torch.equal(acquired[1][0], tensors["b"])

        terminal = downloadable.produce_native_bulk(next_state, "receiver", cell)
        assert terminal[:3] == (ProduceRC.EOF, None, {})
        assert terminal[3:] == (offer["total_bytes"], offer["item_count"])
        duplicate_terminal = downloadable.produce_native_bulk(next_state, "receiver", cell)
        assert duplicate_terminal[3:] == (0, 0)

    def test_native_bulk_active_source_offers_push_and_sends_after_receiver_registration(self):
        class Manager:
            lanes = 1
            max_bytes = 1024

            def __init__(self):
                self.pushed = None

            @staticmethod
            def new_token():
                return "03" * 16

            def push(self, connector, token, lanes, segments):
                self.pushed = (connector, token, lanes, segments)

            @staticmethod
            def cancel(token):
                return None

        manager = Manager()
        connector = SimpleNamespace()

        def transport(_requester, mode):
            return None if mode == tensor_downloader.Mode.PASSIVE else (manager, connector, "receiver-cert")

        cell = _native_bulk_cell(transport, expected_fqcn="receiver")
        downloadable = TensorDownloadable({"a": torch.arange(4, dtype=torch.float32)}, max_chunk_size=1)
        downloadable.num_receivers = 1
        state = TensorConsumer(None, {}).get_initial_state()

        rc, offer, next_state, _, _ = downloadable.produce_native_bulk(state, "receiver", cell)
        assert rc == ProduceRC.OK
        assert offer["direction"] == "push"
        assert manager.pushed is None

        terminal = downloadable.produce_native_bulk(next_state, "receiver", cell)
        assert terminal[0] == ProduceRC.EOF
        assert manager.pushed[:3] == (connector, "03" * 16, 1)

    def test_native_bulk_push_failure_is_terminal_and_not_retried(self):
        class Manager:
            lanes = 1
            max_bytes = 1024

            def __init__(self):
                self.pushes = 0
                self.cancelled = []

            @staticmethod
            def new_token():
                return "05" * 16

            def push(self, connector, token, lanes, segments):
                self.pushes += 1
                raise OSError("broken native lane")

            def cancel(self, token):
                self.cancelled.append(token)

        manager = Manager()

        def transport(_requester, mode):
            return None if mode == tensor_downloader.Mode.PASSIVE else (manager, SimpleNamespace(), "receiver-cert")

        downloadable = TensorDownloadable({"a": torch.arange(4, dtype=torch.float32)}, max_chunk_size=1)
        downloadable.num_receivers = 1
        state = TensorConsumer(None, {}).get_initial_state()
        rc, _, next_state, _, _ = downloadable.produce_native_bulk(
            state, "receiver", _native_bulk_cell(transport, expected_fqcn="receiver")
        )
        assert rc == ProduceRC.OK

        assert downloadable.produce_native_bulk(next_state, "receiver", SimpleNamespace())[0] == ProduceRC.ERROR
        assert downloadable.produce_native_bulk(next_state, "receiver", SimpleNamespace())[0] == ProduceRC.ERROR
        assert manager.pushes == 1
        assert manager.cancelled == ["05" * 16]

    def test_native_bulk_falls_back_for_secure_or_partial_download(self):
        downloadable = TensorDownloadable({"a": torch.ones(4)}, max_chunk_size=1)
        downloadable.num_receivers = 1
        state = TensorConsumer(None, {}).get_initial_state()
        cell = _native_bulk_cell(lambda requester, mode: (_ for _ in ()).throw(AssertionError()))

        assert downloadable.produce_native_bulk(state, "receiver", cell, secure=True) is None
        state["start"] = 1
        assert downloadable.produce_native_bulk(state, "receiver", cell) is None

    def test_native_bulk_falls_back_when_manifest_metadata_is_too_large(self, monkeypatch):
        monkeypatch.setattr(tensor_downloader, "_DIRECT_TENSOR_NATIVE_MAX_KEY_BYTES", 1)
        downloadable = TensorDownloadable({"too-long": torch.ones(4)}, max_chunk_size=1)
        downloadable.num_receivers = 1
        state = TensorConsumer(None, {}).get_initial_state()

        # An unsupported manifest falls back to the existing tensor path.
        transport_cell = _native_bulk_cell(
            lambda requester, mode: (SimpleNamespace(lanes=1, max_bytes=1024), SimpleNamespace(), "receiver-cert"),
            expected_fqcn="receiver",
        )
        assert downloadable.produce_native_bulk(state, "receiver", transport_cell) is None


def test_tensor_consumer_native_bulk_places_each_tensor_in_final_storage():
    class Manager:
        lanes = 2
        max_bytes = 1024

        @staticmethod
        def pull(connector, token, lanes, segments):
            assert connector == "connector"
            assert token == "02" * 16
            assert lanes == 2
            payloads = [
                memoryview(torch.tensor([1.0, 2.0], dtype=torch.float32).view(torch.uint8).numpy()),
                memoryview(torch.tensor([3, 4, 5], dtype=torch.int64).view(torch.uint8).numpy()),
            ]
            for segment, payload in zip(segments, payloads):
                segment.target[:] = payload.cast("B")

    manager = Manager()
    cell = _native_bulk_cell(lambda source, mode: (manager, "connector", "source-cert"), expected_fqcn="source")
    offer = {
        "version": tensor_downloader._TENSOR_NATIVE_BULK_V1,
        "direction": "pull",
        "token": "02" * 16,
        "lanes": 2,
        "total_bytes": 32,
        "item_count": 2,
        "tensors": [
            {"key": "a", "dtype": "F32", "shape": [2], "offset": 0, "size": 8, "lane": 0},
            {"key": "b", "dtype": "I64", "shape": [3], "offset": 8, "size": 24, "lane": 1},
        ],
    }
    state = {"next": True}
    consumer = TensorConsumer(None, {})

    assert consumer.consume_native_bulk("ref", state, offer, cell, "source") is state
    assert torch.equal(consumer.result["a"], torch.tensor([1.0, 2.0]))
    assert torch.equal(consumer.result["b"], torch.tensor([3, 4, 5]))
    consumer.result["a"][0] = 9.0
    assert consumer.result["a"][0].item() == 9.0


def test_tensor_consumer_native_bulk_push_materializes_only_after_completion():
    class Manager:
        lanes = 1
        max_bytes = 1024

        def __init__(self):
            self.segments = None

        def register_receive(self, peer_cn, lanes, segments, token_hex=None):
            self.segments = segments
            return token_hex

        def wait_completed(self, token, peer_cn):
            payload = memoryview(torch.tensor([7.0, 8.0], dtype=torch.float32).view(torch.uint8).numpy()).cast("B")
            self.segments[0].target[:] = payload
            return True, None

        @staticmethod
        def pop_completed(token, peer_cn):
            return True

    manager = Manager()
    cell = _native_bulk_cell(lambda source, mode: (manager, "connector", "source-cert"), expected_fqcn="source")
    offer = {
        "version": tensor_downloader._TENSOR_NATIVE_BULK_V1,
        "direction": "push",
        "token": "04" * 16,
        "lanes": 1,
        "total_bytes": 8,
        "item_count": 1,
        "tensors": [{"key": "a", "dtype": "F32", "shape": [2], "offset": 0, "size": 8, "lane": 0}],
    }
    consumer = TensorConsumer(None, {})

    consumer.consume_native_bulk("ref", {}, offer, cell, "source")
    assert consumer.result is None
    consumer.download_completed("ref")
    assert torch.equal(consumer.result["a"], torch.tensor([7.0, 8.0]))


def test_tensor_consumer_native_bulk_rejects_aggregate_metadata_over_limit(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "_DIRECT_TENSOR_NATIVE_MAX_KEY_BYTES", 1)
    consumer = TensorConsumer(None, {})
    offer = {
        "version": tensor_downloader._TENSOR_NATIVE_BULK_V1,
        "direction": "pull",
        "token": "06" * 16,
        "lanes": 1,
        "total_bytes": 8,
        "item_count": 1,
        "tensors": [{"key": "too-long", "dtype": "F32", "shape": [2], "offset": 0, "size": 8, "lane": 0}],
    }
    manager = SimpleNamespace(lanes=1, max_bytes=1024)
    cell = _native_bulk_cell(lambda source, mode: (manager, "connector", "source-cert"), expected_fqcn="source")

    with pytest.raises(ValueError, match="metadata exceeds"):
        consumer.consume_native_bulk("ref", {}, offer, cell, "source")


@pytest.mark.parametrize(
    "dtype",
    [
        torch.float64,
        torch.float32,
        torch.float16,
        torch.bfloat16,
        torch.int64,
        torch.int32,
        torch.int16,
        torch.int8,
        torch.uint8,
        torch.bool,
    ],
)
def test_direct_tensor_round_trip(dtype, monkeypatch):
    tensor = torch.arange(12, dtype=torch.int64).to(dtype).reshape(3, 4)
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    consumer = TensorConsumer(None, {})

    item = _serialize_tensor_item('weight "\N{SNOWMAN}"', tensor, stream_tensor=True)
    payload = bytearray(b"".join(item.data))
    received = consumer.consume_direct_chunk(payload)[0]

    assert isinstance(item, DirectDownloadChunk)
    assert isinstance(received, _StreamedTensorItem)
    assert received.key == 'weight "\N{SNOWMAN}"'
    assert torch.equal(received.tensor, tensor)
    assert len(received) == len(payload)


def test_direct_tensor_handles_scalar(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    tensor = torch.tensor(3.5)
    item = _serialize_tensor_item("weight", tensor, stream_tensor=True)
    payload = bytearray(b"".join(item.data))
    restored = TensorConsumer(None, {}).consume_direct_chunk(payload)[0]

    assert isinstance(restored, _StreamedTensorItem)
    assert torch.equal(restored.tensor, tensor)


def test_direct_tensor_handles_empty_tensor(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    tensor = torch.empty(0, dtype=torch.float32)
    item = _serialize_tensor_item("weight", tensor, stream_tensor=True)
    payload = bytearray(b"".join(item.data))
    restored = TensorConsumer(None, {}).consume_direct_chunk(payload)[0]

    assert restored.tensor.shape == (0,)
    assert restored.tensor.dtype == torch.float32


def test_direct_tensor_snapshots_before_streaming(monkeypatch):
    tensor = torch.tensor([1.0, 2.0, 3.0])
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)

    item = _serialize_tensor_item("weight", tensor, stream_tensor=True)
    tensor.fill_(99.0)

    payload = bytearray(b"".join(item.data))
    restored = TensorConsumer(None, {}).consume_direct_chunk(payload)[0]
    assert torch.equal(restored.tensor, torch.tensor([1.0, 2.0, 3.0]))


def test_direct_tensor_uses_received_writable_buffer_without_copy(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    item = _serialize_tensor_item("weight", torch.arange(4, dtype=torch.float32), stream_tensor=True)
    payload = bytearray(b"".join(item.data))
    received = TensorConsumer(None, {}).consume_direct_chunk(payload)[0]

    received.tensor[0] = 99.0
    body_offset = tensor_downloader._DIRECT_TENSOR_HEADER.unpack_from(payload)[2]

    assert torch.frombuffer(payload, dtype=torch.float32, count=1, offset=body_offset).item() == 99.0


def test_direct_tensor_retains_received_buffer_ownership(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    item = _serialize_tensor_item("weight", torch.arange(4, dtype=torch.float32), stream_tensor=True)
    payload = bytearray(b"".join(item.data))
    tensor = TensorConsumer(None, {}).consume_direct_chunk(payload)[0].tensor

    del item
    del payload
    gc.collect()

    assert torch.equal(tensor, torch.arange(4, dtype=torch.float32))
    tensor.add_(1)
    assert torch.equal(tensor, torch.arange(1, 5, dtype=torch.float32))


def test_bounded_direct_batch_round_trip_is_writable_owned_and_byte_accounted(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    tensors = {
        "odd_uint8": torch.tensor([1, 2, 3], dtype=torch.uint8),
        "matrix": torch.arange(6, dtype=torch.float64).reshape(2, 3),
        "vector": torch.arange(5, dtype=torch.float32),
    }
    expected = {key: tensor.clone() for key, tensor in tensors.items()}
    downloadable = TensorDownloadable(tensors, max_chunk_size=1)
    downloadable.num_receivers = 1
    consumer = TensorConsumer(None, {})

    rc, chunks, state = downloadable.produce(consumer.get_initial_state(), "receiver")

    assert rc == ProduceRC.OK
    assert state["count"] == 3
    assert state[tensor_downloader._TENSOR_BATCH_STATE_KEY] == tensor_downloader._TENSOR_BATCH_BOUNDED_V1
    assert len(chunks) == 1
    assert isinstance(chunks[0], DirectDownloadChunk)
    assert chunks[0].item_count == 3
    assert chunks[0].reliable_retry_safe is True
    payload = bytearray(b"".join(chunks[0].data))
    received = consumer.consume_direct_chunk(payload)
    assert [item.key for item in received] == list(tensors)
    assert sum(len(item) for item in received) == len(payload)
    for item in received:
        assert torch.equal(item.tensor, expected[item.key])

    first = received[0].tensor
    del chunks
    del payload
    del received
    gc.collect()
    first[0] = 9
    assert first[0].item() == 9


def test_direct_batch_retry_safety_is_fail_closed():
    safe = DirectDownloadChunk(b"safe", reliable_retry_safe=True)
    unsafe = DirectDownloadChunk(b"unsafe")

    batch = tensor_downloader._serialize_direct_tensor_batch([safe, unsafe])

    assert batch.reliable_retry_safe is False


def test_direct_batch_retry_reuses_cached_snapshots_and_advances_logical_count(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    tensors = {f"weight_{index}": torch.arange(8, dtype=torch.float32) + index for index in range(3)}
    expected = {key: tensor.clone() for key, tensor in tensors.items()}
    downloadable = TensorDownloadable(tensors, max_chunk_size=1)
    downloadable.num_receivers = 1
    initial_state = TensorConsumer(None, {}).get_initial_state()

    rc, first, next_state = downloadable.produce(initial_state, "receiver")
    first_wire = b"".join(first[0].data)
    for tensor in tensors.values():
        tensor.fill_(99)
    rc_retry, retry, retry_state = downloadable.produce(initial_state, "receiver")

    assert rc == rc_retry == ProduceRC.OK
    assert retry_state == next_state
    assert b"".join(retry[0].data) == first_wire
    decoded = TensorConsumer(None, {}).consume_direct_chunk(bytearray(first_wire))
    assert all(torch.equal(item.tensor, expected[item.key]) for item in decoded)

    rc_eof, data, state = downloadable.produce(next_state, "receiver")
    assert rc_eof == ProduceRC.EOF
    assert data is None
    assert state == {}


def test_v1_only_consumer_keeps_single_tensor_replies(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    tensors = {f"weight_{index}": torch.arange(8, dtype=torch.float32) for index in range(3)}
    downloadable = TensorDownloadable(tensors, max_chunk_size=1)
    downloadable.num_receivers = 1
    consumer = TensorConsumer(None, {}, enable_direct_batch=False)

    rc, chunks, state = downloadable.produce(consumer.get_initial_state(), "receiver")

    assert rc == ProduceRC.OK
    assert len(chunks) == 1
    assert chunks[0].item_count == 1
    assert state["count"] == 1
    assert tensor_downloader._TENSOR_BATCH_STATE_KEY not in state

    batch = tensor_downloader._serialize_direct_tensor_batch(
        [
            _serialize_tensor_item("one", torch.arange(8, dtype=torch.float32), stream_tensor=True),
            _serialize_tensor_item("two", torch.arange(8, dtype=torch.float32), stream_tensor=True),
        ]
    )
    with pytest.raises(ValueError, match="without negotiating"):
        consumer.consume_direct_chunk(bytearray(b"".join(batch.data)))


def test_bounded_direct_batch_never_mixes_legacy_items(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 1024)
    tensors = {
        "small_before": torch.ones(8),
        "direct_one": torch.ones(512),
        "direct_two": torch.ones(512),
        "small_after": torch.ones(8),
    }
    downloadable = TensorDownloadable(tensors, max_chunk_size=1024 * 1024)
    downloadable.num_receivers = 1
    state = TensorConsumer(None, {}).get_initial_state()

    _, first, state = downloadable.produce(state, "receiver")
    _, second, state = downloadable.produce(state, "receiver")
    _, third, _ = downloadable.produce(state, "receiver")

    assert len(first) == 1 and isinstance(first[0], bytes)
    assert len(second) == 1 and second[0].item_count == 2
    assert len(third) == 1 and isinstance(third[0], bytes)


def test_direct_batch_respects_exact_byte_cap(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    tensors = {f"weight_{index}": torch.arange(100, dtype=torch.uint8) for index in range(4)}
    sample_items = [_serialize_tensor_item(key, tensor, stream_tensor=True) for key, tensor in tensors.items()]
    three_item_cap = tensor_downloader._direct_tensor_batch_size([len(item) for item in sample_items[:3]])
    monkeypatch.setattr(tensor_downloader, "_DIRECT_TENSOR_BATCH_MAX_BYTES", three_item_cap)
    downloadable = TensorDownloadable(tensors, max_chunk_size=1)
    downloadable.num_receivers = 1
    state = TensorConsumer(None, {}).get_initial_state()

    _, first, state = downloadable.produce(state, "receiver")
    _, second, _ = downloadable.produce(state, "receiver")

    assert first[0].item_count == 3
    assert len(first[0]) == three_item_cap
    assert second[0].item_count == 1


def test_direct_batch_respects_item_cap(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    monkeypatch.setattr(tensor_downloader, "_DIRECT_TENSOR_BATCH_MAX_ITEMS", 3)
    tensors = {f"weight_{index}": torch.arange(8, dtype=torch.float32) for index in range(5)}
    downloadable = TensorDownloadable(tensors, max_chunk_size=1)
    downloadable.num_receivers = 1
    state = TensorConsumer(None, {}).get_initial_state()

    _, first, state = downloadable.produce(state, "receiver")
    _, second, _ = downloadable.produce(state, "receiver")

    assert first[0].item_count == 3
    assert second[0].item_count == 2


def test_direct_tensor_larger_than_batch_cap_remains_v1(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    monkeypatch.setattr(tensor_downloader, "_DIRECT_TENSOR_BATCH_MAX_BYTES", 128)
    tensors = {
        "oversized": torch.arange(256, dtype=torch.float32),
        "next": torch.arange(8, dtype=torch.float32),
    }
    downloadable = TensorDownloadable(tensors, max_chunk_size=1)
    downloadable.num_receivers = 1

    _, first, state = downloadable.produce(TensorConsumer(None, {}).get_initial_state(), "receiver")

    assert len(first) == 1
    assert first[0].item_count == 1
    assert len(first[0]) > tensor_downloader._DIRECT_TENSOR_BATCH_MAX_BYTES
    assert state["count"] == 1


def test_direct_batch_rejects_malformed_envelopes(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    first = _serialize_tensor_item("one", torch.arange(3, dtype=torch.uint8), stream_tensor=True)
    second = _serialize_tensor_item("two", torch.arange(4, dtype=torch.float32), stream_tensor=True)
    batch = tensor_downloader._serialize_direct_tensor_batch([first, second])
    valid = bytearray(b"".join(batch.data))
    consumer = TensorConsumer(None, {})

    with pytest.raises(ValueError, match="writable"):
        consumer.consume_direct_chunk(bytes(valid))

    with monkeypatch.context() as patch:
        patch.setattr(tensor_downloader, "_DIRECT_TENSOR_BATCH_MAX_BYTES", len(valid) - 1)
        with pytest.raises(ValueError, match="byte limit"):
            consumer.consume_direct_chunk(bytearray(valid))

    bad_count = bytearray(valid)
    magic, _count, header_size = tensor_downloader._DIRECT_TENSOR_BATCH_HEADER.unpack_from(bad_count)
    tensor_downloader._DIRECT_TENSOR_BATCH_HEADER.pack_into(bad_count, 0, magic, 1, header_size)
    with pytest.raises(ValueError, match="item count"):
        consumer.consume_direct_chunk(bad_count)

    for item_count in (0, tensor_downloader._DIRECT_TENSOR_BATCH_MAX_ITEMS + 1):
        bad_count = bytearray(valid)
        tensor_downloader._DIRECT_TENSOR_BATCH_HEADER.pack_into(bad_count, 0, magic, item_count, header_size)
        with pytest.raises(ValueError, match="item count"):
            consumer.consume_direct_chunk(bad_count)

    bad_header_size = bytearray(valid)
    tensor_downloader._DIRECT_TENSOR_BATCH_HEADER.pack_into(
        bad_header_size, 0, magic, 2, header_size + tensor_downloader._DIRECT_TENSOR_ALIGNMENT
    )
    with pytest.raises(ValueError, match="header size"):
        consumer.consume_direct_chunk(bad_header_size)

    bad_length = bytearray(valid)
    tensor_downloader._DIRECT_TENSOR_BATCH_LENGTH.pack_into(
        bad_length, tensor_downloader._DIRECT_TENSOR_BATCH_HEADER.size, len(valid)
    )
    with pytest.raises(ValueError, match="segment exceeds"):
        consumer.consume_direct_chunk(bad_length)

    huge_length = bytearray(valid)
    tensor_downloader._DIRECT_TENSOR_BATCH_LENGTH.pack_into(
        huge_length, tensor_downloader._DIRECT_TENSOR_BATCH_HEADER.size, (1 << 64) - 1
    )
    with pytest.raises(ValueError, match="segment exceeds"):
        consumer.consume_direct_chunk(huge_length)

    with pytest.raises(ValueError, match="segment exceeds"):
        consumer.consume_direct_chunk(bytearray(valid[:-1]))

    empty_segment = bytearray(valid)
    tensor_downloader._DIRECT_TENSOR_BATCH_LENGTH.pack_into(
        empty_segment, tensor_downloader._DIRECT_TENSOR_BATCH_HEADER.size, 0
    )
    with pytest.raises(ValueError, match="empty segment"):
        consumer.consume_direct_chunk(empty_segment)

    bad_header_padding = bytearray(valid)
    table_end = (
        tensor_downloader._DIRECT_TENSOR_BATCH_HEADER.size + 2 * tensor_downloader._DIRECT_TENSOR_BATCH_LENGTH.size
    )
    bad_header_padding[table_end] = 1
    with pytest.raises(ValueError, match="header padding"):
        consumer.consume_direct_chunk(bad_header_padding)

    nested = bytearray(valid)
    nested[header_size : header_size + len(tensor_downloader._DIRECT_TENSOR_BATCH_MAGIC)] = (
        tensor_downloader._DIRECT_TENSOR_BATCH_MAGIC
    )
    with pytest.raises(ValueError, match="direct tensor magic"):
        consumer.consume_direct_chunk(nested)

    malformed_second = bytearray(valid)
    first_size = tensor_downloader._DIRECT_TENSOR_BATCH_LENGTH.unpack_from(
        malformed_second, tensor_downloader._DIRECT_TENSOR_BATCH_HEADER.size
    )[0]
    second_start = header_size + tensor_downloader._align_direct_size(first_size)
    malformed_second[second_start : second_start + len(tensor_downloader._DIRECT_TENSOR_MAGIC)] = b"BADMAGIC"
    with pytest.raises(ValueError, match="direct tensor magic"):
        consumer.consume_direct_chunk(malformed_second)

    trailing = bytearray(valid + b"x")
    with pytest.raises(ValueError, match="trailing data"):
        consumer.consume_direct_chunk(trailing)

    duplicate = tensor_downloader._serialize_direct_tensor_batch(
        [first, _serialize_tensor_item("one", torch.arange(5, dtype=torch.uint8), stream_tensor=True)]
    )
    with pytest.raises(ValueError, match="duplicate"):
        consumer.consume_direct_chunk(bytearray(b"".join(duplicate.data)))

    nonzero_padding = bytearray(valid)
    first_size = tensor_downloader._DIRECT_TENSOR_BATCH_LENGTH.unpack_from(
        nonzero_padding, tensor_downloader._DIRECT_TENSOR_BATCH_HEADER.size
    )[0]
    first_padding = header_size + first_size
    assert first_padding < header_size + tensor_downloader._align_direct_size(first_size)
    nonzero_padding[first_padding] = 1
    with pytest.raises(ValueError, match="segment padding"):
        consumer.consume_direct_chunk(nonzero_padding)


def test_direct_tensor_rejects_readonly_or_malformed_payload(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    item = _serialize_tensor_item("weight", torch.arange(4, dtype=torch.float32), stream_tensor=True)
    payload = b"".join(item.data)
    consumer = TensorConsumer(None, {})

    with pytest.raises(ValueError, match="writable"):
        consumer.consume_direct_chunk(payload)

    malformed = bytearray(payload)
    malformed[:8] = b"BADMAGIC"
    with pytest.raises(ValueError, match="magic"):
        consumer.consume_direct_chunk(malformed)

    oversized_header = bytearray(
        b"".join(_serialize_tensor_item("weight", torch.arange(100, dtype=torch.float32), stream_tensor=True).data)
    )
    magic, metadata_size, header_size = tensor_downloader._DIRECT_TENSOR_HEADER.unpack_from(oversized_header)
    tensor_downloader._DIRECT_TENSOR_HEADER.pack_into(
        oversized_header, 0, magic, metadata_size, header_size + tensor_downloader._DIRECT_TENSOR_ALIGNMENT
    )
    with pytest.raises(ValueError, match="header size"):
        consumer.consume_direct_chunk(oversized_header)


def test_direct_tensor_rejects_shape_larger_than_payload():
    metadata = json.dumps(
        {"key": "weight", "dtype": "F32", "shape": [2**1000], "size": 0}, separators=(",", ":")
    ).encode()
    unpadded_size = tensor_downloader._DIRECT_TENSOR_HEADER.size + len(metadata)
    header_size = (
        (unpadded_size + tensor_downloader._DIRECT_TENSOR_ALIGNMENT - 1)
        // tensor_downloader._DIRECT_TENSOR_ALIGNMENT
        * tensor_downloader._DIRECT_TENSOR_ALIGNMENT
    )
    payload = bytearray(
        tensor_downloader._DIRECT_TENSOR_HEADER.pack(tensor_downloader._DIRECT_TENSOR_MAGIC, len(metadata), header_size)
        + metadata
        + bytes(header_size - unpadded_size)
    )

    with pytest.raises(ValueError, match="exceeds the payload size"):
        TensorConsumer(None, {}).consume_direct_chunk(payload)


def test_small_tensor_stays_on_legacy_inline_path():
    item = _serialize_tensor_item("weight", torch.arange(1024, dtype=torch.float32), stream_tensor=True)

    assert isinstance(item, bytes)


def test_negotiated_single_receiver_produces_direct_large_tensor():
    tensor = torch.arange(3 * 1024 * 1024, dtype=torch.float32)
    downloadable = TensorDownloadable({"weight": tensor}, max_chunk_size=1024)
    downloadable.num_receivers = 1
    consumer = TensorConsumer(None, {})

    rc, items, state = downloadable.produce(consumer.get_initial_state(), "receiver")
    payload = bytearray(b"".join(items[0].data))
    received = consumer.consume_direct_chunk(payload)
    result = consumer.consume_items(received, None)

    assert rc == ProduceRC.OK
    assert torch.equal(result["weight"], tensor)
    assert isinstance(received[0], _StreamedTensorItem)
    assert items[0].reliable_retry_safe is True
    assert state[tensor_downloader._TENSOR_STREAM_STATE_KEY] == tensor_downloader._TENSOR_STREAM_MEMORY_V1


def test_multi_receiver_stays_on_legacy_path():
    tensor = torch.arange(3 * 1024 * 1024, dtype=torch.float32)
    downloadable = TensorDownloadable({"weight": tensor}, max_chunk_size=1024)
    downloadable.num_receivers = 2

    rc, items, state = downloadable.produce(TensorConsumer(None, {}).get_initial_state(), "receiver")

    assert rc == ProduceRC.OK
    assert isinstance(items[0], bytes)
    assert tensor_downloader._TENSOR_STREAM_STATE_KEY not in state
    assert tensor_downloader._TENSOR_BATCH_STATE_KEY not in state


def test_legacy_receiver_state_keeps_new_sender_on_legacy_path():
    tensor = torch.arange(3 * 1024 * 1024, dtype=torch.float32)
    downloadable = TensorDownloadable({"weight": tensor}, max_chunk_size=1024)
    downloadable.num_receivers = 1

    _, items, _ = downloadable.produce(None, "receiver")

    assert isinstance(items[0], bytes)


def test_unsupported_dtype_stays_on_legacy_path(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 0)
    tensor = torch.arange(4, dtype=torch.float32).to(torch.complex64)

    item = _serialize_tensor_item("weight", tensor, stream_tensor=True)

    assert isinstance(item, bytes)


def test_disk_consumer_does_not_advertise_direct_memory(tmp_path):
    consumer = DiskTensorConsumer(str(tmp_path))
    assert consumer.get_initial_state() is None
    consumer.release()


def test_direct_item_is_exclusive_with_large_chunk_budget(monkeypatch):
    monkeypatch.setattr(tensor_downloader, "TEN_MEGA", 1024)
    tensors = {
        "small_before": torch.ones(8),
        "large": torch.ones(1024),
        "small_after": torch.ones(8),
    }
    downloadable = TensorDownloadable(tensors, max_chunk_size=1024 * 1024)
    downloadable.num_receivers = 1
    state = TensorConsumer(None, {}).get_initial_state()

    _, first, state = downloadable.produce(state, "receiver")
    _, second, state = downloadable.produce(state, "receiver")
    _, third, _ = downloadable.produce(state, "receiver")

    assert len(first) == 1 and isinstance(first[0], bytes)
    assert len(second) == 1 and isinstance(second[0], DirectDownloadChunk)
    assert len(third) == 1 and isinstance(third[0], bytes)


def test_non_contiguous_tensor_retains_safetensors_validation():
    tensor = torch.arange(12, dtype=torch.float32).reshape(3, 4).t()

    with pytest.raises(ValueError, match="non contiguous"):
        _serialize_tensor_item("weight", tensor, stream_tensor=True)


@pytest.mark.timeout(60)
def test_direct_tensor_batch_round_trip_over_remote_cell_is_writable_and_owned():
    port = get_open_ports(1)[0]
    # The passive root endpoint identity used by the TCP driver is "server".
    # The peer is still guaranteed remote because it lives in a spawned process.
    server_name = "server"
    server = Cell(server_name, f"tcp://localhost:{port}", secure=False, credentials={})
    downloader = None
    client_process = None
    context = mp.get_context("spawn")
    result_queue = context.Queue()
    server.core_cell.start()
    try:
        # This ~30 MiB NVTDIR02 envelope crosses many 1 MiB F3 frames.
        # Odd tensor lengths also exercise padding between child slots.
        source = {
            f"weight_{index}": torch.full(
                (tensor_downloader.TEN_MEGA + index + 1,),
                index,
                dtype=torch.uint8,
            )
            for index in range(3)
        }
        downloader = ObjectDownloader(cell=server, timeout=20.0, num_receivers=1)
        ref_id = add_tensors(downloader, source, max_chunk_size=1024)
        client_process = context.Process(
            target=_run_batched_tensor_client,
            args=(port, server_name, ref_id, result_queue),
        )
        client_process.start()

        status, *details = result_queue.get(timeout=45)
        assert status == "ok", details
        direct_calls, retained_value = details
        assert len(direct_calls) == 1
        item_count, readonly, contiguous, wire_size = direct_calls[0]
        assert (item_count, readonly, contiguous) == (3, False, True)
        assert wire_size > 3 * tensor_downloader.TEN_MEGA
        assert retained_value == 7
    finally:
        if downloader is not None:
            downloader.delete_transaction()
        if client_process is not None:
            client_process.join(timeout=10)
            if client_process.is_alive():
                client_process.terminate()
                client_process.join(timeout=5)
        server.core_cell.stop()
        CoreCell.ALL_CELLS.pop(server.core_cell.get_fqcn(), None)
    assert client_process is not None and client_process.exitcode == 0
