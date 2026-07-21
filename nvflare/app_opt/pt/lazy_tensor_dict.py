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

"""PT lazy tensor references used by tensor disk offload.

When `enable_tensor_disk_offload=True`, incoming streamed tensor payloads are written
to temporary safetensors files instead of being fully deserialized into memory.
`LazyTensorDict` maps item IDs to on-disk files, and `_LazyRef` defers loading until
`materialize()` is called by aggregation code.

This keeps peak memory lower for large models while still allowing deterministic
explicit cleanup via `cleanup()`, with GC as a fallback through `_TempDirRef`.
"""

import json
import logging
import os
import shutil
import threading
import time
from datetime import datetime, timezone

from safetensors import safe_open

logger = logging.getLogger(__name__)
TENSOR_OFFLOAD_METRICS_PREFIX = "[TENSOR_OFFLOAD_METRICS]"


def _cleanup_temp_dir(path: str) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return
    except Exception as e:
        logger.warning("failed to cleanup tensor offload temp dir '%s': %s", path, e)


class _TempDirRef:
    """Reference-counted sentinel for a temp directory.

    Shared between LazyTensorDict and all _LazyRef instances created from it.
    The directory is deleted only when ALL holders are garbage collected.
    """

    def __init__(self, temp_dir: str, file_paths: set[str]):
        self.path = temp_dir
        self._deleted = False
        self._lock = threading.Lock()
        self._started_at = time.perf_counter()
        self._file_count = len(file_paths)
        self._on_disk_bytes = sum(os.path.getsize(path) for path in file_paths)
        self._materialization_count = 0
        self._materialized_bytes = 0
        self._materialization_seconds = 0.0

    def record_materialization(self, tensor, elapsed_seconds: float) -> None:
        with self._lock:
            self._materialization_count += 1
            self._materialized_bytes += tensor.numel() * tensor.element_size()
            self._materialization_seconds += elapsed_seconds

    def get_metrics(self) -> dict:
        with self._lock:
            return {
                "event": "tensor_offload_lifecycle",
                "source": "tensor_offload",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "file_count": self._file_count,
                "on_disk_bytes": self._on_disk_bytes,
                "materialization_count": self._materialization_count,
                "materialized_bytes": self._materialized_bytes,
                "materialization_seconds": self._materialization_seconds,
                "lifetime_seconds": time.perf_counter() - self._started_at,
            }

    def cleanup(self):
        with self._lock:
            if self._deleted:
                return
            self._deleted = True
        logger.info("%s%s", TENSOR_OFFLOAD_METRICS_PREFIX, json.dumps(self.get_metrics(), sort_keys=True))
        _cleanup_temp_dir(self.path)

    def __del__(self):
        self.cleanup()


class _LazyRef:
    """Lightweight placeholder for an on-disk tensor.

    Carries only file_path + key (~100 bytes). The tensor is loaded from disk
    only when materialize() is called, keeping memory near zero until then.

    Holds a reference to _TempDirRef to prevent premature cleanup.
    """

    def __init__(self, file_path: str, key: str, temp_ref: _TempDirRef):
        self.file_path = file_path
        self.key = key
        self._temp_ref = temp_ref

    def materialize(self):
        """Load tensor from safetensors file. Opens mmap, copies data out, closes mmap."""
        started_at = time.perf_counter()
        with safe_open(self.file_path, framework="pt") as f:
            tensor = f.get_tensor(self.key)
        self._temp_ref.record_materialization(tensor, time.perf_counter() - started_at)
        return tensor

    def __repr__(self):
        return f"_LazyRef({self.file_path!r}, key={self.key!r})"


class LazyTensorDict:
    """Dict-like mapping of FOBS item_ids to on-disk safetensors files.

    Each entry maps an item_id to a (file_path, key) pair. Tensors are loaded
    via safetensors safe_open (mmap) on access.
    """

    def __init__(self, key_to_file: dict[str, tuple[str, str]], temp_dir: str):
        self._key_to_file = key_to_file
        self._temp_ref = _TempDirRef(temp_dir, {file_path for file_path, _ in key_to_file.values()})

    def __getitem__(self, key):
        file_path, st_key = self._key_to_file[key]
        started_at = time.perf_counter()
        with safe_open(file_path, framework="pt") as f:
            tensor = f.get_tensor(st_key)
        self._temp_ref.record_materialization(tensor, time.perf_counter() - started_at)
        return tensor

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def keys(self):
        return self._key_to_file.keys()

    def __iter__(self):
        return iter(self._key_to_file)

    def items(self):
        for key in self._key_to_file:
            yield key, self[key]

    def values(self):
        for key in self._key_to_file:
            yield self[key]

    def __len__(self):
        return len(self._key_to_file)

    def __contains__(self, key):
        return key in self._key_to_file

    def make_lazy_ref(self, key) -> "_LazyRef":
        file_path, st_key = self._key_to_file[key]
        return _LazyRef(file_path=file_path, key=st_key, temp_ref=self._temp_ref)

    def cleanup(self):
        self._temp_ref.cleanup()
