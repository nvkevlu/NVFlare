# Copyright (c) 2025, NVIDIA CORPORATION.  All rights reserved.
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
import json
import os
import struct
import sys
import tempfile
import threading
import weakref
from typing import Any, List, Optional, Tuple

import torch
from safetensors.torch import load as load_tensors
from safetensors.torch import save as save_tensors

from nvflare.app_common.utils.tensor_disk_offload_context import _TENSOR_DISK_OFFLOAD_ROOT_DIR
from nvflare.fuel.f3.cellnet.cell import Cell
from nvflare.fuel.f3.drivers.connector_info import Mode
from nvflare.fuel.f3.drivers.native_bulk import NativeBulkReceiveSegment, NativeBulkSendSegment
from nvflare.fuel.f3.streaming.cacheable import CacheableObject, ItemConsumer
from nvflare.fuel.f3.streaming.download_service import DirectDownloadChunk, ProduceRC, download_object
from nvflare.fuel.f3.streaming.obj_downloader import ObjectDownloader
from nvflare.fuel.f3.streaming.stream_utils import stream_thread_pool
from nvflare.fuel.utils.fobs.datum import TEN_MEGA

from .lazy_tensor_dict import LazyTensorDict, _cleanup_temp_dir

_TWO_MB = 2 * 1024 * 1024
_ACTIVE_DISK_TENSOR_CONSUMERS = weakref.WeakSet()
_ACTIVE_DISK_TENSOR_CONSUMERS_LOCK = threading.Lock()
_TENSOR_STREAM_STATE_KEY = "__nvflare_tensor_stream__"
_TENSOR_STREAM_MEMORY_V1 = "direct_memory_v1"
_TENSOR_BATCH_STATE_KEY = "__nvflare_tensor_batch__"
_TENSOR_BATCH_BOUNDED_V1 = "bounded_direct_v1"
_TENSOR_NATIVE_BULK_STATE_KEY = "__nvflare_tensor_native_bulk__"
_TENSOR_NATIVE_BULK_V1 = "native_tls_v1"
_TENSOR_NATIVE_BULK_TOKEN_KEY = "__nvflare_tensor_native_bulk_token__"
_DIRECT_TENSOR_MAGIC = b"NVTDIR01"
_DIRECT_TENSOR_HEADER = struct.Struct("<8sII")
_DIRECT_TENSOR_ALIGNMENT = 64
_DIRECT_TENSOR_MAX_METADATA = 1024 * 1024
_DIRECT_TENSOR_BATCH_MAGIC = b"NVTDIR02"
_DIRECT_TENSOR_BATCH_HEADER = struct.Struct("<8sII")
_DIRECT_TENSOR_BATCH_LENGTH = struct.Struct("<Q")
_DIRECT_TENSOR_BATCH_MAX_ITEMS = 8
_DIRECT_TENSOR_BATCH_MAX_BYTES = 256 * 1024 * 1024
_DIRECT_TENSOR_NATIVE_MAX_ITEMS = 65536

_SAFETENSORS_DTYPE_NAMES = (
    ("float64", "F64"),
    ("float32", "F32"),
    ("float16", "F16"),
    ("bfloat16", "BF16"),
    ("int64", "I64"),
    ("int32", "I32"),
    ("int16", "I16"),
    ("int8", "I8"),
    ("uint8", "U8"),
    ("bool", "BOOL"),
)
_SAFETENSORS_DTYPES = {
    dtype: code
    for torch_name, code in _SAFETENSORS_DTYPE_NAMES
    if (dtype := getattr(torch, torch_name, None)) is not None
}


class _StreamedTensorItem:
    """Receiver-created marker that cannot be supplied as an ordinary data item."""

    __slots__ = ("key", "tensor", "wire_size")

    def __init__(self, key: str, tensor: torch.Tensor, wire_size: int):
        self.key = key
        self.tensor = tensor
        self.wire_size = wire_size

    def __len__(self) -> int:
        return self.wire_size


def _reject_duplicate_json_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate direct tensor metadata key {key!r}")
        result[key] = value
    return result


def _can_stream_tensor_directly(tensor: torch.Tensor) -> bool:
    """Whether a tensor can be represented by the direct-memory protocol."""
    return (
        sys.byteorder == "little"
        and tensor.layout == torch.strided
        and tensor.device.type == "cpu"
        and tensor.is_contiguous()
        and tensor.dtype in _SAFETENSORS_DTYPES
        and not tensor.is_conj()
        and not getattr(tensor, "is_neg", lambda: False)()
    )


def _align_direct_size(size: int) -> int:
    return (size + _DIRECT_TENSOR_ALIGNMENT - 1) // _DIRECT_TENSOR_ALIGNMENT * _DIRECT_TENSOR_ALIGNMENT


def _direct_tensor_prefix(key: str, tensor: torch.Tensor) -> Optional[bytes]:
    if (
        not isinstance(key, str)
        or key == "__metadata__"
        or tensor.numel() * tensor.element_size() < TEN_MEGA
        or not _can_stream_tensor_directly(tensor)
    ):
        return None

    metadata = {
        "key": key,
        "dtype": _SAFETENSORS_DTYPES[tensor.dtype],
        "shape": list(tensor.shape),
        "size": tensor.numel() * tensor.element_size(),
    }
    metadata_bytes = json.dumps(metadata, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(metadata_bytes) > _DIRECT_TENSOR_MAX_METADATA:
        return None
    unpadded_size = _DIRECT_TENSOR_HEADER.size + len(metadata_bytes)
    header_size = _align_direct_size(unpadded_size)
    return (
        _DIRECT_TENSOR_HEADER.pack(_DIRECT_TENSOR_MAGIC, len(metadata_bytes), header_size)
        + metadata_bytes
        + bytes(header_size - unpadded_size)
    )


def _direct_tensor_batch_size(segment_sizes: List[int]) -> int:
    header_size = _align_direct_size(
        _DIRECT_TENSOR_BATCH_HEADER.size + len(segment_sizes) * _DIRECT_TENSOR_BATCH_LENGTH.size
    )
    return header_size + sum(_align_direct_size(size) for size in segment_sizes)


def _serialize_direct_tensor_batch(items: List[DirectDownloadChunk]) -> DirectDownloadChunk:
    if not 2 <= len(items) <= _DIRECT_TENSOR_BATCH_MAX_ITEMS:
        raise ValueError(f"direct tensor batch must contain 2-{_DIRECT_TENSOR_BATCH_MAX_ITEMS} items")
    if any(not isinstance(item, DirectDownloadChunk) or item.item_count != 1 for item in items):
        raise TypeError("direct tensor batches can contain only single-tensor direct chunks")

    segment_sizes = [len(item) for item in items]
    header_unpadded_size = _DIRECT_TENSOR_BATCH_HEADER.size + len(items) * _DIRECT_TENSOR_BATCH_LENGTH.size
    header_size = _align_direct_size(header_unpadded_size)
    header = _DIRECT_TENSOR_BATCH_HEADER.pack(_DIRECT_TENSOR_BATCH_MAGIC, len(items), header_size)
    header += b"".join(_DIRECT_TENSOR_BATCH_LENGTH.pack(size) for size in segment_sizes)
    header += bytes(header_size - header_unpadded_size)

    buffers = [header]
    for item, segment_size in zip(items, segment_sizes):
        buffers.extend(item.data)
        padding_size = _align_direct_size(segment_size) - segment_size
        if padding_size:
            buffers.append(bytes(padding_size))

    result = DirectDownloadChunk(
        buffers,
        item_count=len(items),
        reliable_retry_safe=all(item.reliable_retry_safe for item in items),
    )
    if len(result) > _DIRECT_TENSOR_BATCH_MAX_BYTES:
        raise ValueError(f"direct tensor batch exceeds {_DIRECT_TENSOR_BATCH_MAX_BYTES} bytes")
    return result


def _serialize_tensor_item(key: str, tensor: torch.Tensor, stream_tensor: bool = False):
    """Create a snapshot for one tensor download item.

    Negotiated large tensors use a raw bytes-like reply so F3 receives directly
    into writable storage. Legacy peers and small/unsupported tensors retain
    the existing safetensors representation.
    """
    if not stream_tensor:
        return save_tensors({key: tensor})

    prefix = _direct_tensor_prefix(key, tensor)
    if prefix is None:
        return save_tensors({key: tensor})
    snapshot = tensor.detach().clone(memory_format=torch.contiguous_format)
    body = memoryview(snapshot.reshape(-1).view(torch.uint8).numpy())
    return DirectDownloadChunk([prefix, body], reliable_retry_safe=True)


def _writable_direct_buffer(data) -> memoryview:
    buffer = memoryview(data)
    if not buffer.c_contiguous:
        raise ValueError("direct tensor payload must be C-contiguous")
    if buffer.readonly:
        raise ValueError("direct tensor payload must be writable")
    return buffer.cast("B")


def _deserialize_direct_tensor_v1(buffer: memoryview) -> _StreamedTensorItem:
    if len(buffer) < _DIRECT_TENSOR_HEADER.size:
        raise ValueError("direct tensor payload is too short")
    magic, metadata_size, header_size = _DIRECT_TENSOR_HEADER.unpack_from(buffer)
    if magic != _DIRECT_TENSOR_MAGIC:
        raise ValueError("invalid direct tensor magic")
    expected_header_size = _align_direct_size(_DIRECT_TENSOR_HEADER.size + metadata_size)
    if metadata_size > _DIRECT_TENSOR_MAX_METADATA or header_size != expected_header_size or header_size > len(buffer):
        raise ValueError("invalid direct tensor header size")
    if any(buffer[_DIRECT_TENSOR_HEADER.size + metadata_size : header_size]):
        raise ValueError("invalid direct tensor header padding")
    try:
        metadata = json.loads(
            bytes(buffer[_DIRECT_TENSOR_HEADER.size : _DIRECT_TENSOR_HEADER.size + metadata_size]),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise ValueError("invalid direct tensor metadata") from ex
    if not isinstance(metadata, dict) or set(metadata) != {"key", "dtype", "shape", "size"}:
        raise ValueError("invalid direct tensor metadata schema")

    key = metadata.get("key")
    if not isinstance(key, str) or key == "__metadata__":
        raise ValueError(f"invalid direct tensor key {key!r}")
    dtype_code = metadata.get("dtype")
    dtype_by_code = {code: dtype for dtype, code in _SAFETENSORS_DTYPES.items()}
    dtype = dtype_by_code.get(dtype_code)
    if dtype is None:
        raise ValueError(f"unsupported direct tensor dtype {dtype_code!r}")

    shape = metadata.get("shape")
    if not isinstance(shape, list) or len(shape) > 64 or any(type(dim) is not int or dim < 0 for dim in shape):
        raise ValueError(f"invalid direct tensor shape {shape!r}")

    body_size = len(buffer) - header_size
    if type(metadata.get("size")) is not int or metadata["size"] != body_size:
        raise ValueError(f"direct tensor size {metadata.get('size')!r} does not match {body_size}-byte payload")

    element_size = torch.empty((), dtype=dtype).element_size()
    max_numel = body_size // element_size
    numel = 0 if 0 in shape else 1
    if numel:
        for dim in shape:
            if dim and numel > max_numel // dim:
                raise ValueError("direct tensor shape exceeds the payload size")
            numel *= dim
    expected_size = numel * element_size
    if expected_size != body_size:
        raise ValueError(f"direct tensor shape and dtype require {expected_size} bytes but payload has {body_size}")

    try:
        if numel:
            tensor = torch.frombuffer(buffer, dtype=dtype, count=numel, offset=header_size).reshape(tuple(shape))
        else:
            tensor = torch.empty(tuple(shape), dtype=dtype)
    except (RuntimeError, ValueError) as ex:
        raise ValueError(f"invalid direct tensor shape {shape!r}") from ex
    return _StreamedTensorItem(key, tensor, len(buffer))


def _deserialize_direct_tensor_batch(buffer: memoryview) -> List[_StreamedTensorItem]:
    if len(buffer) > _DIRECT_TENSOR_BATCH_MAX_BYTES:
        raise ValueError("direct tensor batch exceeds the negotiated byte limit")
    if len(buffer) < _DIRECT_TENSOR_BATCH_HEADER.size:
        raise ValueError("direct tensor batch is too short")

    magic, item_count, header_size = _DIRECT_TENSOR_BATCH_HEADER.unpack_from(buffer)
    if magic != _DIRECT_TENSOR_BATCH_MAGIC:
        raise ValueError("invalid direct tensor batch magic")
    if not 2 <= item_count <= _DIRECT_TENSOR_BATCH_MAX_ITEMS:
        raise ValueError("invalid direct tensor batch item count")
    table_end = _DIRECT_TENSOR_BATCH_HEADER.size + item_count * _DIRECT_TENSOR_BATCH_LENGTH.size
    expected_header_size = _align_direct_size(table_end)
    if header_size != expected_header_size or header_size > len(buffer):
        raise ValueError("invalid direct tensor batch header size")
    if any(buffer[table_end:header_size]):
        raise ValueError("invalid direct tensor batch header padding")

    segment_sizes = [
        _DIRECT_TENSOR_BATCH_LENGTH.unpack_from(
            buffer, _DIRECT_TENSOR_BATCH_HEADER.size + index * _DIRECT_TENSOR_BATCH_LENGTH.size
        )[0]
        for index in range(item_count)
    ]
    if any(size == 0 for size in segment_sizes):
        raise ValueError("direct tensor batch contains an empty segment")

    items = []
    keys = set()
    cursor = header_size
    for segment_size in segment_sizes:
        slot_size = _align_direct_size(segment_size)
        if slot_size > len(buffer) - cursor:
            raise ValueError("direct tensor batch segment exceeds payload size")
        segment_end = cursor + segment_size
        slot_end = cursor + slot_size
        item = _deserialize_direct_tensor_v1(buffer[cursor:segment_end])
        if item.key in keys:
            raise ValueError(f"duplicate direct tensor batch key {item.key!r}")
        keys.add(item.key)
        if any(buffer[segment_end:slot_end]):
            raise ValueError("invalid direct tensor batch segment padding")
        item.wire_size = slot_size
        items.append(item)
        cursor = slot_end

    if cursor != len(buffer):
        raise ValueError("direct tensor batch has trailing data")
    items[0].wire_size += header_size
    return items


def cleanup_active_disk_tensor_downloads(reason: str = "download aborted") -> None:
    """Clean partial tensor offload dirs still owned by active disk consumers."""
    with _ACTIVE_DISK_TENSOR_CONSUMERS_LOCK:
        consumers = list(_ACTIVE_DISK_TENSOR_CONSUMERS)

    for consumer in consumers:
        consumer.download_failed("active_disk_tensor_download", reason)


class TensorDownloadable(CacheableObject):

    def __init__(self, tensors: dict[str, torch.Tensor], max_chunk_size: int):
        self.size = len(tensors)
        self.keys = list(tensors.keys())
        self._prefetch_lock = threading.Lock()
        self._prefetch_futures = {}
        self._released = False
        self._stream_tensors = None
        self._batch_tensors = None
        self._native_bulk_lock = threading.Lock()
        self._native_bulk_session = None
        super().__init__(tensors, max_chunk_size)

    def get_item_count(self) -> int:
        return self.size

    def produce(self, state: dict, requester: str):
        requested_mode = state.get(_TENSOR_STREAM_STATE_KEY) if isinstance(state, dict) else None
        requested_batch = state.get(_TENSOR_BATCH_STATE_KEY) if isinstance(state, dict) else None
        with self._prefetch_lock:
            if self._stream_tensors is None:
                self._stream_tensors = bool(self.num_receivers == 1 and requested_mode == _TENSOR_STREAM_MEMORY_V1)
            if self._batch_tensors is None:
                self._batch_tensors = bool(
                    self._stream_tensors and self.num_receivers == 1 and requested_batch == _TENSOR_BATCH_BOUNDED_V1
                )
            stream_tensors = self._stream_tensors
            batch_tensors = self._batch_tensors

        rc, data, new_state = super().produce(state, requester)
        if (
            batch_tensors
            and rc == ProduceRC.OK
            and isinstance(data, list)
            and len(data) >= 2
            and all(isinstance(item, DirectDownloadChunk) for item in data)
        ):
            data = [_serialize_direct_tensor_batch(data)]
        if stream_tensors and rc == ProduceRC.OK:
            new_state = dict(new_state)
            new_state[_TENSOR_STREAM_STATE_KEY] = _TENSOR_STREAM_MEMORY_V1
            if batch_tensors:
                new_state[_TENSOR_BATCH_STATE_KEY] = _TENSOR_BATCH_BOUNDED_V1
        return rc, data, new_state

    def produce_native_bulk(self, state: dict, requester: str, cell: Cell, secure: bool = False):
        if secure or self.num_receivers != 1 or sys.byteorder != "little" or not isinstance(state, dict):
            return None
        if state.get(_TENSOR_NATIVE_BULK_STATE_KEY) != _TENSOR_NATIVE_BULK_V1:
            return None

        token = state.get(_TENSOR_NATIVE_BULK_TOKEN_KEY)
        if token is not None:
            with self._native_bulk_lock:
                session = self._native_bulk_session
            if not session or token != session["token"] or requester != session["requester"]:
                return ProduceRC.ERROR, None, {}, 0, 0
            manager = session["manager"]
            peer_cn = session["peer_cn"]
            with session["complete_lock"]:
                if session["error"]:
                    return ProduceRC.ERROR, None, {}, 0, 0
                try:
                    if not session["completed"]:
                        if session["direction"] == "pull":
                            completed, error = manager.wait_completed(token, peer_cn)
                            if error or not completed or not manager.pop_completed(token, peer_cn):
                                raise RuntimeError(error or "native tensor bulk pull did not complete")
                        else:
                            manager.push(session["connector"], token, session["lanes"], session["segments"])
                        session["completed"] = True
                except Exception as ex:
                    session["error"] = f"{type(ex).__name__}: {ex}"
                    manager.cancel(token)
                    return ProduceRC.ERROR, None, {}, 0, 0
            with self._native_bulk_lock:
                if session["accounted"]:
                    bytes_delta = 0
                    items_delta = 0
                else:
                    bytes_delta = session["total_bytes"]
                    items_delta = session["item_count"]
                    session["accounted"] = True
            return ProduceRC.EOF, None, {}, bytes_delta, items_delta

        with self._native_bulk_lock:
            session = self._native_bulk_session
        if session:
            if requester != session["requester"]:
                return ProduceRC.ERROR, None, {}, 0, 0
            return ProduceRC.OK, session["offer"], dict(session["next_state"]), 0, 0

        # Never switch protocols after any ordinary item has already been returned.
        if state.get("start", 0) or state.get("count", 0):
            return None
        transport = cell.get_native_bulk_transport(requester, Mode.PASSIVE)
        direction = "pull"
        if not transport:
            transport = cell.get_native_bulk_transport(requester, Mode.ACTIVE)
            direction = "push"
        if not transport:
            return None
        manager, connector, peer_cn = transport
        # The peer certificate is already checked against the endpoint FQCN
        # during the SFM handshake. Re-resolve it here before minting a bearer
        # token so the bulk path cannot weaken that binding.
        try:
            cell.core_cell.communicator.conn_manager.identity_resolver.require_match(
                requester, peer_cn, "native tensor bulk control connection"
            )
        except (AttributeError, ValueError):
            return None

        base_obj = self.base_obj
        if base_obj is None:
            return ProduceRC.ERROR, None, {}, 0, 0
        if not 1 <= self.size <= _DIRECT_TENSOR_NATIVE_MAX_ITEMS:
            return None
        lanes = min(manager.lanes, self.size)
        if lanes <= 0:
            return None

        lane_sizes = [0] * lanes
        manifest = []
        segments = []
        offset = 0
        for key in self.keys:
            tensor = base_obj.get(key)
            if (
                not isinstance(key, str)
                or key == "__metadata__"
                or len(key.encode("utf-8")) > _DIRECT_TENSOR_MAX_METADATA
                or not isinstance(tensor, torch.Tensor)
                or len(tensor.shape) > 64
                or not _can_stream_tensor_directly(tensor)
            ):
                return None
            size = tensor.numel() * tensor.element_size()
            if size <= 0:
                return None
            lane = min(range(lanes), key=lambda lane_index: lane_sizes[lane_index])
            lane_sizes[lane] += size

            expected_dtype = tensor.dtype
            expected_shape = tuple(tensor.shape)

            def provide_tensor(
                tensor_key=key,
                tensor_size=size,
                tensor_dtype=expected_dtype,
                tensor_shape=expected_shape,
            ):
                current = self.base_obj
                if current is None:
                    raise RuntimeError(f"tensor {tensor_key!r} requested after source release")
                source = current[tensor_key]
                if (
                    not isinstance(source, torch.Tensor)
                    or source.dtype != tensor_dtype
                    or tuple(source.shape) != tensor_shape
                    or source.numel() * source.element_size() != tensor_size
                    or not _can_stream_tensor_directly(source)
                ):
                    raise RuntimeError(f"tensor {tensor_key!r} changed representation during native bulk transfer")
                snapshot = source.detach().clone(memory_format=torch.contiguous_format)
                return snapshot, memoryview(snapshot.reshape(-1).view(torch.uint8).numpy())

            segments.append(NativeBulkSendSegment(lane, size=size, provider=provide_tensor))
            manifest.append(
                {
                    "key": key,
                    "dtype": _SAFETENSORS_DTYPES[tensor.dtype],
                    "shape": list(tensor.shape),
                    "offset": offset,
                    "size": size,
                    "lane": lane,
                }
            )
            offset += size

        if offset > manager.max_bytes:
            return None
        token = manager.register_send(peer_cn, lanes, segments) if direction == "pull" else manager.new_token()
        next_state = {
            "start": 0,
            "count": self.size,
            _TENSOR_NATIVE_BULK_STATE_KEY: _TENSOR_NATIVE_BULK_V1,
            _TENSOR_NATIVE_BULK_TOKEN_KEY: token,
        }
        offer = {
            "version": _TENSOR_NATIVE_BULK_V1,
            "direction": direction,
            "token": token,
            "lanes": lanes,
            "total_bytes": offset,
            "item_count": self.size,
            "tensors": manifest,
        }
        new_session = {
            "manager": manager,
            "connector": connector,
            "direction": direction,
            "lanes": lanes,
            "segments": segments,
            "token": token,
            "peer_cn": peer_cn,
            "requester": requester,
            "total_bytes": offset,
            "item_count": self.size,
            "offer": offer,
            "next_state": next_state,
            "completed": False,
            "error": None,
            "accounted": False,
            "complete_lock": threading.Lock(),
        }
        with self._native_bulk_lock:
            existing = self._native_bulk_session
            if existing is None:
                self._native_bulk_session = new_session
            else:
                manager.cancel(token)
                if requester != existing["requester"]:
                    return ProduceRC.ERROR, None, {}, 0, 0
                return ProduceRC.OK, existing["offer"], dict(existing["next_state"]), 0, 0
        return ProduceRC.OK, offer, next_state, 0, 0

    def produce_item(self, index: int):
        key = self.keys[index]
        with self._prefetch_lock:
            future = self._prefetch_futures.pop(index, None)
            stream_tensors = bool(self._stream_tensors)
        if future:
            return future.result()
        base_obj = self.base_obj
        if base_obj is None:
            raise RuntimeError(f"item {index} requested after tensors were released")
        return _serialize_tensor_item(key, base_obj[key], stream_tensors)

    def prefetch_item(self, index: int):
        with self._prefetch_lock:
            if self._released or index in self._prefetch_futures:
                return
            base_obj = self.base_obj
            if base_obj is None:
                return
            key = self.keys[index]
            tensor = base_obj[key]
            future = stream_thread_pool.submit(_serialize_tensor_item, key, tensor, bool(self._stream_tensors))
            if future:
                self._prefetch_futures[index] = future

    def get_item_size(self, index: int) -> Optional[int]:
        base_obj = self.base_obj
        if base_obj is None:
            return None
        tensor = base_obj[self.keys[index]]
        return tensor.numel() * tensor.element_size()

    def _direct_item_size(self, index: int) -> Optional[int]:
        base_obj = self.base_obj
        if base_obj is None:
            return None
        key = self.keys[index]
        tensor = base_obj[key]
        prefix = _direct_tensor_prefix(key, tensor)
        if prefix is None:
            return None
        return len(prefix) + tensor.numel() * tensor.element_size()

    def can_add_item(self, index: int, current_items: list, current_size: int, item: Any = None) -> bool:
        with self._prefetch_lock:
            batch_tensors = bool(self._batch_tensors)
        if not batch_tensors or not current_items:
            return super().can_add_item(index, current_items, current_size, item)

        current_items_are_direct = all(isinstance(current, DirectDownloadChunk) for current in current_items)
        if item is None:
            candidate_size = self._direct_item_size(index)
            candidate_is_direct = candidate_size is not None
        else:
            candidate_is_direct = isinstance(item, DirectDownloadChunk)
            candidate_size = len(item) if candidate_is_direct else None

        if current_items_are_direct != candidate_is_direct:
            return False
        if not current_items_are_direct:
            return super().can_add_item(index, current_items, current_size, item)
        if len(current_items) >= _DIRECT_TENSOR_BATCH_MAX_ITEMS:
            return False

        segment_sizes = [len(current) for current in current_items]
        segment_sizes.append(candidate_size)
        return _direct_tensor_batch_size(segment_sizes) <= _DIRECT_TENSOR_BATCH_MAX_BYTES

    def is_item_exclusive(self, index: int, item: Any = None) -> bool:
        with self._prefetch_lock:
            batch_tensors = bool(self._batch_tensors)
        if batch_tensors:
            if isinstance(item, DirectDownloadChunk):
                return False
            if item is None and self._direct_item_size(index) is not None:
                return False

        if item is not None:
            return isinstance(item, DirectDownloadChunk)

        base_obj = self.base_obj
        if base_obj is None:
            return False
        key = self.keys[index]
        tensor = base_obj[key]
        size = tensor.numel() * tensor.element_size()
        with self._prefetch_lock:
            stream_tensors = bool(self._stream_tensors)
        return bool(
            stream_tensors
            and isinstance(key, str)
            and key != "__metadata__"
            and size >= TEN_MEGA
            and _can_stream_tensor_directly(tensor)
        )

    def release(self):
        with self._prefetch_lock:
            self._released = True
            futures = list(self._prefetch_futures.values())
            self._prefetch_futures.clear()
        for future in futures:
            future.cancel()
        with self._native_bulk_lock:
            session = self._native_bulk_session
            self._native_bulk_session = None
        if session:
            session["manager"].cancel(session["token"])
        super().release()


class TensorConsumer(ItemConsumer):

    def __init__(
        self,
        tensors_received_cb,
        cb_kwargs,
        enable_direct_batch: bool = True,
        enable_native_bulk: bool = True,
    ):
        ItemConsumer.__init__(self)
        self.tensors_received_cb = tensors_received_cb
        self.cb_kwargs = cb_kwargs
        self.enable_direct_batch = enable_direct_batch
        self.enable_native_bulk = enable_native_bulk
        self._native_bulk_receive_session = None
        self._native_bulk_pending_items = None
        if tensors_received_cb is not None and not callable(tensors_received_cb):
            raise ValueError("tensors_received_cb must be callable")

    def get_initial_state(self) -> Optional[dict]:
        if sys.byteorder != "little":
            return None
        state = {_TENSOR_STREAM_STATE_KEY: _TENSOR_STREAM_MEMORY_V1}
        if self.enable_direct_batch:
            state[_TENSOR_BATCH_STATE_KEY] = _TENSOR_BATCH_BOUNDED_V1
        if self.enable_native_bulk:
            state[_TENSOR_NATIVE_BULK_STATE_KEY] = _TENSOR_NATIVE_BULK_V1
        return state

    def consume_native_bulk(self, ref_id: str, state: dict, offer: dict, cell: Cell, from_fqcn: str) -> dict:
        if not self.enable_native_bulk or sys.byteorder != "little":
            raise ValueError("received native tensor bulk without negotiating support")
        if not isinstance(offer, dict) or set(offer) != {
            "version",
            "direction",
            "token",
            "lanes",
            "total_bytes",
            "item_count",
            "tensors",
        }:
            raise ValueError("invalid native tensor bulk offer")
        if offer["version"] != _TENSOR_NATIVE_BULK_V1 or offer["direction"] not in ("pull", "push"):
            raise ValueError("unsupported native tensor bulk offer")
        token = offer["token"]
        lanes = offer["lanes"]
        total_bytes = offer["total_bytes"]
        item_count = offer["item_count"]
        tensors = offer["tensors"]
        if (
            not isinstance(token, str)
            or len(token) != 32
            or type(lanes) is not int
            or not 1 <= lanes <= 4
            or type(total_bytes) is not int
            or total_bytes <= 0
            or type(item_count) is not int
            or not 1 <= item_count <= _DIRECT_TENSOR_NATIVE_MAX_ITEMS
            or not isinstance(tensors, list)
            or len(tensors) != item_count
        ):
            raise ValueError("invalid native tensor bulk bounds")

        mode = Mode.ACTIVE if offer["direction"] == "pull" else Mode.PASSIVE
        transport = cell.get_native_bulk_transport(from_fqcn, mode)
        if not transport:
            raise ValueError("native tensor bulk requires a direct active mTLS connection")
        manager, connector, peer_cn = transport
        try:
            cell.core_cell.communicator.conn_manager.identity_resolver.require_match(
                from_fqcn, peer_cn, "native tensor bulk control connection"
            )
        except (AttributeError, ValueError) as ex:
            raise ValueError("native tensor bulk peer identity does not match its endpoint") from ex
        if lanes > manager.lanes or total_bytes > manager.max_bytes:
            raise ValueError("native tensor bulk offer exceeds local limits")

        dtype_by_code = {code: dtype for dtype, code in _SAFETENSORS_DTYPES.items()}
        keys = set()
        cursor = 0
        parsed = []
        segments = []
        lane_counts = [0] * lanes
        for metadata in tensors:
            if not isinstance(metadata, dict) or set(metadata) != {"key", "dtype", "shape", "offset", "size", "lane"}:
                raise ValueError("invalid native tensor metadata schema")
            key = metadata["key"]
            dtype = dtype_by_code.get(metadata["dtype"])
            shape = metadata["shape"]
            offset = metadata["offset"]
            size = metadata["size"]
            lane = metadata["lane"]
            if not isinstance(key, str) or key == "__metadata__" or key in keys:
                raise ValueError(f"invalid native tensor key {key!r}")
            if dtype is None:
                raise ValueError(f"unsupported native tensor dtype {metadata['dtype']!r}")
            if not isinstance(shape, list) or len(shape) > 64 or any(type(dim) is not int or dim < 0 for dim in shape):
                raise ValueError(f"invalid native tensor shape {shape!r}")
            if type(offset) is not int or offset != cursor or type(size) is not int or size <= 0:
                raise ValueError("native tensor offsets must form one canonical bounded range")
            if type(lane) is not int or not 0 <= lane < lanes or size > total_bytes - offset:
                raise ValueError("invalid native tensor lane or size")
            element_size = torch.empty((), dtype=dtype).element_size()
            max_numel = size // element_size
            numel = 0 if 0 in shape else 1
            if numel:
                for dim in shape:
                    if dim and numel > max_numel // dim:
                        raise ValueError("native tensor shape exceeds its payload")
                    numel *= dim
            if numel * element_size != size:
                raise ValueError("native tensor shape and dtype do not match its payload")
            keys.add(key)
            lane_counts[lane] += 1
            tensor = torch.empty(tuple(shape), dtype=dtype)
            target = memoryview(tensor.reshape(-1).view(torch.uint8).numpy()).cast("B")
            if len(target) != size:
                raise ValueError("native tensor allocation does not match its declared payload")
            segments.append(NativeBulkReceiveSegment(lane, target))
            parsed.append((key, tensor, size))
            cursor += size
        if cursor != total_bytes or any(count == 0 for count in lane_counts):
            raise ValueError("native tensor manifest does not cover the declared storage and lanes")

        items = [_StreamedTensorItem(key, tensor, size) for key, tensor, size in parsed]
        if offer["direction"] == "pull":
            manager.pull(connector, token, lanes, segments)
            self.result = self.consume_items(items, self.result)
        else:
            manager.register_receive(peer_cn, lanes, segments, token_hex=token)
            self._native_bulk_receive_session = (manager, token, peer_cn)
            self._native_bulk_pending_items = items
        return state

    def download_completed(self, ref_id: str):
        session = self._native_bulk_receive_session
        self._native_bulk_receive_session = None
        if session:
            manager, token, peer_cn = session
            completed, error = manager.wait_completed(token, peer_cn)
            if error or not completed or not manager.pop_completed(token, peer_cn):
                raise RuntimeError(error or "native tensor bulk push did not complete")
        pending_items = self._native_bulk_pending_items
        self._native_bulk_pending_items = None
        if pending_items:
            self.result = self.consume_items(pending_items, self.result)
        super().download_completed(ref_id)

    def download_failed(self, ref_id, reason: str):
        session = self._native_bulk_receive_session
        self._native_bulk_receive_session = None
        self._native_bulk_pending_items = None
        if session:
            session[0].cancel(session[1])
        super().download_failed(ref_id, reason)

    def consume_direct_chunk(self, data) -> List[_StreamedTensorItem]:
        if sys.byteorder != "little":
            raise ValueError("direct tensor replies require a little-endian receiver")

        buffer = _writable_direct_buffer(data)
        if len(buffer) < len(_DIRECT_TENSOR_MAGIC):
            raise ValueError("direct tensor payload is too short")
        magic = bytes(buffer[: len(_DIRECT_TENSOR_MAGIC)])
        if magic == _DIRECT_TENSOR_MAGIC:
            return [_deserialize_direct_tensor_v1(buffer)]
        if magic == _DIRECT_TENSOR_BATCH_MAGIC:
            if not self.enable_direct_batch:
                raise ValueError("received a direct tensor batch without negotiating batch support")
            return _deserialize_direct_tensor_batch(buffer)
        raise ValueError("invalid direct tensor magic")

    def consume_items(self, items: List[Any], result: Any) -> Any:
        if not isinstance(items, list):
            raise TypeError(f"items must be list but got {type(items)}")
        if result is None:
            result = {}

        tensors = {}
        for item in items:
            if isinstance(item, _StreamedTensorItem):
                td = {item.key: item.tensor}
            else:
                td = load_tensors(item)
            if not isinstance(td, dict):
                raise ValueError("cannot load received bytes to tensors")
            tensors.update(td)

        if self.tensors_received_cb:
            cb_result = self.tensors_received_cb(tensors, **self.cb_kwargs)
            if isinstance(cb_result, dict):
                result.update(cb_result)
        else:
            result.update(tensors)
        return result


def add_tensors(
    downloader: ObjectDownloader,
    tensors: dict[str, torch.Tensor],
    max_chunk_size: int = _TWO_MB,
) -> str:
    """Add tensors to be downloaded to the specified downloader.

    Args:
        downloader: the downloader to add tensors to.
        tensors: state dict to be downloaded
        max_chunk_size: max chunk size

    Returns: reference id for the state dict.

    """
    obj = TensorDownloadable(tensors, max_chunk_size)
    return downloader.add_object(obj)


def download_tensors(
    from_fqcn: str,
    ref_id: str,
    per_request_timeout: float,
    cell: Cell,
    secure=False,
    optional=False,
    abort_signal=None,
    tensors_received_cb=None,
    progress_cb=None,
    enable_native_bulk: bool = True,
    **cb_kwargs,
) -> Tuple[str, Optional[dict[str, torch.Tensor]]]:
    """Download the referenced state dict from the source.

    Args:
        from_fqcn: FQCN of the data source.
        ref_id: reference ID of the state dict to be downloaded.
        per_request_timeout: timeout for requests sent to the data source.
        cell: cell to be used for communicating to the data source.
        secure: P2P private mode for communication
        optional: supress log messages of communication
        abort_signal: signal for aborting download.
        tensors_received_cb: the callback to be called when one set of tensors are received

    Returns: tuple of (error message if any, downloaded state dict).

    """
    consumer = TensorConsumer(tensors_received_cb, cb_kwargs, enable_native_bulk=enable_native_bulk)
    download_object(
        from_fqcn=from_fqcn,
        ref_id=ref_id,
        consumer=consumer,
        per_request_timeout=per_request_timeout,
        cell=cell,
        secure=secure,
        optional=optional,
        abort_signal=abort_signal,
        progress_cb=progress_cb,
    )
    return consumer.error, consumer.result


def _extract_safetensors_keys(data: bytes) -> list[str]:
    """Extract tensor key names from safetensors header without deserializing tensors."""
    if len(data) < 8:
        raise ValueError("Invalid safetensors data: too short")

    header_size = struct.unpack("<Q", data[:8])[0]
    if header_size == 0:
        raise ValueError("Invalid safetensors data: empty header")

    header_end = 8 + header_size
    if header_end > len(data):
        raise ValueError("Invalid safetensors data: header size exceeds payload length")

    try:
        header = json.loads(data[8:header_end])
    except Exception as e:
        raise ValueError("Invalid safetensors data: invalid JSON header") from e

    if not isinstance(header, dict):
        raise ValueError("Invalid safetensors data: header must be JSON object")

    return [k for k in header.keys() if k != "__metadata__"]


class DiskTensorConsumer(ItemConsumer):
    """Writes raw safetensors bytes to disk without deserializing to tensors."""

    def __init__(self, temp_dir: str):
        ItemConsumer.__init__(self)
        self._temp_dir = temp_dir
        self._cleaned = False
        self._file_counter = 0
        self._io_lock = threading.Lock()
        with _ACTIVE_DISK_TENSOR_CONSUMERS_LOCK:
            _ACTIVE_DISK_TENSOR_CONSUMERS.add(self)

    def release(self) -> None:
        with _ACTIVE_DISK_TENSOR_CONSUMERS_LOCK:
            _ACTIVE_DISK_TENSOR_CONSUMERS.discard(self)
            self._cleaned = True

    def cleanup(self) -> None:
        # Pipelined downloads can have a chunk write in progress while workflow
        # finalization aborts active consumers. Wait for that write to finish so
        # rmtree cannot race an open/create operation and leave a partial directory.
        with self._io_lock:
            with _ACTIVE_DISK_TENSOR_CONSUMERS_LOCK:
                if self._cleaned:
                    return
                self._cleaned = True
                _ACTIVE_DISK_TENSOR_CONSUMERS.discard(self)

            _cleanup_temp_dir(self._temp_dir)

    def consume_items(self, items: List[Any], result: Any) -> Any:
        if not isinstance(items, list):
            raise TypeError(f"items must be list but got {type(items)}")
        if result is None:
            result = {}

        with self._io_lock:
            for item in items:
                keys = _extract_safetensors_keys(item)
                file_path = os.path.join(self._temp_dir, f"chunk_{self._file_counter}.safetensors")
                self._file_counter += 1
                with open(file_path, "wb") as f:
                    f.write(item)
                for key in keys:
                    if key in result:
                        raise ValueError(
                            f"Duplicate tensor key '{key}' seen in multiple safetensors chunks; "
                            "streaming data may be malformed."
                        )
                    result[key] = (file_path, key)

        return result

    def download_failed(self, ref_id, reason: str):
        super().download_failed(ref_id, reason)
        # Eager cleanup on download callback error; the outer caller may also
        # attempt cleanup via consumer.error path. Double cleanup is intentional
        # and safe because _cleanup_temp_dir handles already-removed paths.
        self.cleanup()


def download_tensors_to_disk(
    from_fqcn: str,
    ref_id: str,
    per_request_timeout: float,
    cell: Cell,
    secure=False,
    optional=False,
    abort_signal=None,
    progress_cb=None,
    root_dir: Optional[str] = None,
) -> Tuple[str, Optional[LazyTensorDict]]:
    """Download tensors to disk instead of memory.

    Args:
        root_dir: optional call-scoped destination root. When omitted, use the
            root configured on the Cell for backward compatibility.

    Returns: tuple of (error message if any, LazyTensorDict for lazy access).
    """
    if root_dir is None:
        root_dir = cell.get_fobs_context().get(_TENSOR_DISK_OFFLOAD_ROOT_DIR)
    if not root_dir:
        raise RuntimeError(f"{_TENSOR_DISK_OFFLOAD_ROOT_DIR} is not set in FOBS context")
    temp_dir = tempfile.mkdtemp(prefix="nvflare_tensors_", dir=root_dir)

    consumer = DiskTensorConsumer(temp_dir)
    try:
        download_object(
            from_fqcn=from_fqcn,
            ref_id=ref_id,
            consumer=consumer,
            per_request_timeout=per_request_timeout,
            cell=cell,
            secure=secure,
            optional=optional,
            abort_signal=abort_signal,
            progress_cb=progress_cb,
        )
    except Exception:
        consumer.cleanup()
        raise

    if consumer.error:
        consumer.cleanup()
        return consumer.error, None

    key_to_file = consumer.result if consumer.result is not None else {}
    consumer.release()
    return None, LazyTensorDict(key_to_file=key_to_file, temp_dir=temp_dir)
