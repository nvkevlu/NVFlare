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
import threading
import time
from abc import abstractmethod
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from nvflare.fuel.f3.streaming.download_service import Consumer, Downloadable, DownloadService, ProduceRC
from nvflare.fuel.utils.log_utils import get_obj_logger
from nvflare.fuel.utils.validation_utils import check_non_negative_int


F3_CACHE_METRICS_PREFIX = "[F3_CACHE_METRICS]"


class _StateKey:
    START = "start"
    COUNT = "count"


class CacheableObject(Downloadable):
    """This class provides cache capability for managing chunks generated during streaming.
    When the object is to be sent to multiple receivers, each chunk is generated only once and cached for other
    receivers. Once all receivers received the chunk, it's removed from the cache.

    """

    def __init__(self, obj: Any, max_chunk_size: int):
        """Constructor of CacheableObject.

        Args:
            obj: the object to be downloaded.
            max_chunk_size: max number of bytes for each chunk.

        Notes: The object must be able to be divided into multiple items. A chunk is generated for each item.
        """
        super().__init__(obj)
        check_non_negative_int("max_chunk_size", max_chunk_size)
        self.max_chunk_size = max_chunk_size
        self.size = self.get_item_count()
        self.cache: list[tuple[Optional[bytes], int]] = [(None, 0)] * self.size
        self.lock = threading.Lock()
        self.num_receivers = 0
        self.logger = get_obj_logger(self)
        self.transaction_id = None
        self.ref_id = None
        self._metrics_logged = False
        self._cache_hits = 0
        self._production_attempts = 0
        self._duplicate_productions = 0
        self._unique_cache_fills = 0
        self._serialized_bytes = 0
        self._duplicate_serialized_bytes = 0
        self._serialization_seconds = 0.0
        self._cached_bytes_current = 0
        self._cached_bytes_peak = 0
        self._cache_evictions = 0
        self._receiver_ack_items = 0

    @abstractmethod
    def get_item_count(self) -> int:
        """The subclass must implement this method to return the number of items the object contains.

        Returns: the number of items the object contains

        """
        pass

    @abstractmethod
    def produce_item(self, index: int) -> bytes:
        """This method is called to produce the chunk for the specified item.

        Args:
            index: index of the item.

        Returns: a chunk for the item

        """
        pass

    def set_transaction(self, tx_id, ref_id):
        tx_info = DownloadService.get_transaction_info(tx_id)
        self.num_receivers = tx_info.num_receivers
        self.transaction_id = tx_id
        self.ref_id = ref_id
        self.logger.info(f"set transaction info: {tx_id=}, {ref_id=} {self.num_receivers=}")

    def downloaded_to_all(self):
        self.logger.info(f"object has been downloaded to all {self.num_receivers} receivers - clear cache")
        self.clear_cache()
        self._log_cache_metrics(reason="downloaded_to_all", status="completed")

    def transaction_done(self, transaction_id: str, status: str):
        self.clear_cache()
        self._log_cache_metrics(reason="transaction_done", status=status)

    def get_cache_metrics(self) -> dict:
        with self.lock:
            return {
                "event": "f3_cache_metrics",
                "source": "f3_cache",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "transaction_id": self.transaction_id,
                "ref_id": self.ref_id,
                "item_count": self.size,
                "receiver_count": self.num_receivers,
                "cache_hits": self._cache_hits,
                "production_attempts": self._production_attempts,
                "unique_cache_fills": self._unique_cache_fills,
                "duplicate_productions": self._duplicate_productions,
                "serialized_bytes": self._serialized_bytes,
                "duplicate_serialized_bytes": self._duplicate_serialized_bytes,
                "serialization_seconds": self._serialization_seconds,
                "cached_bytes_current": self._cached_bytes_current,
                "cached_bytes_peak": self._cached_bytes_peak,
                "cache_evictions": self._cache_evictions,
                "receiver_ack_items": self._receiver_ack_items,
            }

    def _log_cache_metrics(self, reason: str, status: str) -> None:
        with self.lock:
            if self._metrics_logged:
                return
            self._metrics_logged = True
        metrics = self.get_cache_metrics()
        metrics.update({"reason": reason, "status": status})
        self.logger.info(f"{F3_CACHE_METRICS_PREFIX}{json.dumps(metrics, sort_keys=True)}")

    def _produce_item_with_metrics(self, index: int) -> bytes:
        started_at = time.perf_counter()
        data = self.produce_item(index)
        elapsed = time.perf_counter() - started_at
        with self.lock:
            self._production_attempts += 1
            self._serialized_bytes += len(data)
            self._serialization_seconds += elapsed
        return data

    def clear_cache(self):
        """Clear the chunk cache only.

        Does NOT touch base_obj — the source object is released separately
        via release() after the transaction_done_cb has been invoked, so the
        callback can still observe the original data if needed.
        """
        with self.lock:
            self.cache = None
            self._cached_bytes_current = 0

    def release(self):
        """Drop the reference to the source object.

        Called by _Transaction.transaction_done() AFTER the transaction_done_cb
        fires.  Setting base_obj to None drops the last infrastructure reference
        to the source data (e.g. a 5 GiB numpy dict), allowing it to be
        reclaimed by the GC immediately rather than waiting for a future cycle.

        Overrides Downloadable.release() (which is a no-op by default).
        """
        with self.lock:
            self.base_obj = None

    def _get_item(self, index: int, requester: str) -> bytes:
        with self.lock:
            cache_available = bool(self.cache)
            data = None if not cache_available else self.cache[index][0]
            base_obj = self.base_obj  # snapshot under lock for thread-safety
            if data is not None:
                self._cache_hits += 1

        if not cache_available:
            if base_obj is None:
                # release() was already called — no new chunk requests should
                # arrive after transaction_done(), but guard defensively.
                raise RuntimeError(f"item {index} requested after base_obj released for {requester}")
            # produce_item() reads self.base_obj internally and is called outside
            # the lock.  A concurrent release() could set self.base_obj to None
            # between the guard above and produce_item's first read.  In practice
            # this window cannot open: release() is only invoked from
            # transaction_done_cb, which fires after the download service confirms
            # all chunks have been delivered — i.e. after this code path has
            # already returned.  The guard above handles the only truly invalid
            # state (request arriving after a completed transaction).
            return self._produce_item_with_metrics(index)

        if data is not None:
            self.logger.debug(f"got item {index} from cache for {requester}")
            return data

        # Produce outside the lock so concurrent receivers aren't blocked.
        # If two receivers produce the same item simultaneously, the first
        # to re-acquire the lock stores its result; the second uses it.
        data = self._produce_item_with_metrics(index)

        with self.lock:
            if self.cache:
                existing, count = self.cache[index]
                if existing is None:
                    self.cache[index] = (data, count)
                    self._unique_cache_fills += 1
                    self._cached_bytes_current += len(data)
                    self._cached_bytes_peak = max(self._cached_bytes_peak, self._cached_bytes_current)
                    self.logger.debug(f"created and cached item {index} for {requester}: {len(data)} bytes")
                else:
                    self._duplicate_productions += 1
                    self._duplicate_serialized_bytes += len(data)
                    data = existing
                    self.logger.debug(f"got item {index} from cache for {requester} (produced concurrently)")
        return data

    def _adjust_cache(self, start: int, count: int):
        with self.lock:
            if not self.cache:
                # cache has been cleared
                return

            for i in range(start, start + count):
                data, num_received = self.cache[i]
                num_received += 1
                self._receiver_ack_items += 1
                if num_received >= self.num_receivers:
                    self.logger.debug(f"item {i} was received by {num_received} receivers - clear cache")
                    if data is not None:
                        self._cached_bytes_current -= len(data)
                        self._cache_evictions += 1
                    self.cache[i] = (None, num_received)
                else:
                    self.cache[i] = (data, num_received)

    def produce(self, state: dict, requester: str) -> Tuple[str, Any, dict]:
        if not state:
            # first request
            start = 0
        else:
            received_start = state.get(_StateKey.START, 0)
            received_count = state.get(_StateKey.COUNT, 0)
            if received_count > 0:
                self._adjust_cache(received_start, received_count)

            start = received_start + received_count

        if start >= self.size:
            # already done
            return ProduceRC.EOF, None, {}

        result = []
        total_size = 0

        for i in range(start, self.size):
            item = self._get_item(i, requester)
            item_size = len(item)
            if not result or total_size + item_size < self.max_chunk_size:
                result.append(item)
                total_size += item_size
            else:
                break

        self.logger.debug(f"produced {len(result)} items for {requester}: {total_size} bytes")
        return ProduceRC.OK, result, {_StateKey.START: start, _StateKey.COUNT: len(result)}


class ItemConsumer(Consumer):

    def __init__(self):
        super().__init__()
        self.error = None
        self.result = None

    @abstractmethod
    def consume_items(self, items: List[Any], result: Any) -> Any:
        """Process items and return updated result."""
        pass

    def consume(self, ref_id: str, state: dict, data: Any) -> dict:
        assert isinstance(data, list)
        self.result = self.consume_items(data, self.result)
        return state

    def download_failed(self, ref_id, reason: str):
        self.logger.error(f"failed to download object with ref {ref_id}: {reason}")
        self.error = reason
        self.result = None

    def download_completed(self, ref_id: str):
        self.logger.debug(f"received object with ref {ref_id}")
