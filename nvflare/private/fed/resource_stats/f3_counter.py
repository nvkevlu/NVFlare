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

"""Thread-safe, job-scoped F3 sender counter (step 1 of F3_GAP.md's plan).

This is the state machine the rest of the F3 work builds on. It is not yet
wired to any real NVFlare send path -- ``collector.py`` still hardcodes the
public ``f3`` field to ``unavailable/not_bound`` (see F3_GAP.md step 8: the
hardcoding is removed only after call sites are bound and integration-tested,
steps 2-7). Landing the counter on its own, fully tested against the exact
production schema, keeps that follow-up work from also having to get this
concurrency-sensitive class right at the same time.

One counter instance covers one contributing process (SP, CP, SJ, or CJ; see
F3_GAP.md "Missing production bindings"). A participant's final ``f3`` value
is the checked sum of its job-process counter and its parent-process counter,
which is a later step (F3_GAP.md step 6) done in ``assemble_participant_summary``.

State machine
-------------
``collecting`` -> ``closing`` -> ``frozen``, one-way, coordinated by a single
lock:

* ``begin()`` (admission) only succeeds while ``collecting``. Once
  ``close()`` has been called, no new operation is classified/counted, but
  the caller must still perform the underlying send -- this counter only
  decides whether to count it, never whether to send it.
* An operation admitted before ``close()`` is allowed to finish counting
  during ``closing`` (the caller's own bounded drain window; this class does
  not implement a timer -- see F3_GAP.md "five seconds is an internal bound,
  not configuration", which lives in the parent-process caller).
* ``freeze()`` is the one-way transition into ``frozen`` and fixes the
  published snapshot forever: if anything was still admitted-but-incomplete
  at that moment, the snapshot is ``partial`` with issue ``counter_gap``.
  Anything that completes after ``freeze()`` is silently discarded -- "a
  callback that linearizes after the freeze cannot change the canonical
  snapshot."
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

_COLLECTING = "collecting"
_CLOSING = "closing"
_FROZEN = "frozen"

_BUCKET_REMOTE_ACCEPTED = "remote_accepted"
_BUCKET_LOCAL_DELIVERED = "local_delivered"
_BUCKET_REMOTE_FAILED = "remote_failed_before_acceptance"


class F3TrafficClass(str, Enum):
    """The closed allowlist of NVFlare traffic classes this field measures.

    Only a trusted NVFlare call site that already owns the operation may
    assign one of these; a wire header, topic, or job-supplied label is never
    sufficient authority (F3_GAP.md "the low-level channel, topic, or a
    job-supplied header cannot assign an included class").
    """

    TASK_REQUEST = "task_request"
    TASK_RESPONSE = "task_response"
    TASK_RESULT = "task_result"
    JOB_APPLICATION = "job_application"
    JOB_STREAM_DATA = "job_stream_data"


INCLUDED_F3_TRAFFIC_CLASSES = frozenset(F3TrafficClass)

T = TypeVar("T")


@dataclass
class _Bucket:
    payload_bytes: int = 0
    messages: int = 0

    def add(self, payload_bytes: int, messages: int) -> None:
        self.payload_bytes += payload_bytes
        self.messages += messages

    def as_dict(self) -> dict[str, str]:
        return {"payload_bytes": str(self.payload_bytes), "messages": str(self.messages)}


class F3Admission:
    """An opaque token returned by :meth:`F3Counter.begin`.

    Callers should treat this as opaque; it exists only so ``begin()``/the
    completion call can be separated by an arbitrary amount of caller code
    (typically the transport send itself) without losing which traffic class
    was admitted.
    """

    __slots__ = ("traffic_class", "_completed")

    def __init__(self, traffic_class: F3TrafficClass):
        self.traffic_class = traffic_class
        self._completed = False


def _validate_payload(payload_bytes: int, messages: int) -> None:
    if isinstance(payload_bytes, bool) or not isinstance(payload_bytes, int) or payload_bytes < 0:
        raise ValueError("payload_bytes must be a non-negative integer")
    if isinstance(messages, bool) or not isinstance(messages, int) or messages <= 0:
        raise ValueError("messages must be a positive integer")


class F3Counter:
    """One process-local, job-scoped F3 sender counter."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = _COLLECTING
        self._pending = 0
        self._had_gap = False
        self._buckets = {
            _BUCKET_REMOTE_ACCEPTED: _Bucket(),
            _BUCKET_LOCAL_DELIVERED: _Bucket(),
            _BUCKET_REMOTE_FAILED: _Bucket(),
        }
        self._frozen_snapshot: Optional[dict[str, Any]] = None

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def pending_count(self) -> int:
        """Operations admitted but not yet completed; used by a parent-process drain loop."""

        with self._lock:
            return self._pending

    def begin(self, traffic_class: F3TrafficClass) -> Optional[F3Admission]:
        """Admit one operation for counting if it is still possible to count it.

        Returns ``None`` (not an error) when the class is not in the included
        allowlist or admission has already been closed; the caller must still
        perform the send either way, just without counting it.
        """

        if not isinstance(traffic_class, F3TrafficClass):
            raise TypeError("traffic_class must be an F3TrafficClass")
        with self._lock:
            if self._state != _COLLECTING or traffic_class not in INCLUDED_F3_TRAFFIC_CLASSES:
                return None
            self._pending += 1
            return F3Admission(traffic_class)

    def record_remote_send(
        self,
        traffic_class: F3TrafficClass,
        payload_bytes: int,
        transport_send: Callable[[], T],
        *,
        messages: int = 1,
    ) -> T:
        """Send remotely; count only a transport-accepted outcome.

        Mirrors the current F3 ``communicator.send`` boundary, whose failure
        signal is an exception -- this is not a receiver-delivery
        acknowledgement.
        """

        _validate_payload(payload_bytes, messages)
        admission = self.begin(traffic_class)
        try:
            result = transport_send()
        except BaseException:
            # BaseException, not Exception: an admission must always be released
            # (even on KeyboardInterrupt/SystemExit) or pending_count leaks and
            # every later freeze() would report a phantom counter_gap forever.
            self._complete(admission, _BUCKET_REMOTE_FAILED, payload_bytes, messages)
            raise
        self._complete(admission, _BUCKET_REMOTE_ACCEPTED, payload_bytes, messages)
        return result

    def record_local_delivery(
        self,
        traffic_class: F3TrafficClass,
        payload_bytes: int,
        direct_delivery: Callable[[], T],
        *,
        messages: int = 1,
    ) -> T:
        """Deliver directly (same process); only a successful delivery is counted.

        There is no public bucket for a failed direct delivery (see the
        three-bucket production schema in contract.py); a failure is simply
        not counted, matching how ``remote_failed_before_acceptance`` is
        reserved for the remote-transport boundary only.
        """

        _validate_payload(payload_bytes, messages)
        admission = self.begin(traffic_class)
        try:
            result = direct_delivery()
        except BaseException:
            self._discard(admission)
            raise
        self._complete(admission, _BUCKET_LOCAL_DELIVERED, payload_bytes, messages)
        return result

    def close(self) -> None:
        """Stop admitting new operations; already-admitted ones may still complete."""

        with self._lock:
            if self._state == _COLLECTING:
                self._state = _CLOSING

    def freeze(self) -> dict[str, Any]:
        """Fix the immutable, publishable snapshot. Idempotent: returns the same dict every call."""

        with self._lock:
            if self._frozen_snapshot is None:
                if self._pending > 0:
                    self._had_gap = True
                self._state = _FROZEN
                self._frozen_snapshot = self._snapshot_locked()
            return self._frozen_snapshot

    def snapshot(self) -> dict[str, Any]:
        """Return the current f3-shaped totals without fixing the cutoff.

        Once :meth:`freeze` has been called, this always returns that same
        frozen dict. Before that, it is a live diagnostic view: an operation
        still admitted-but-incomplete makes it ``partial``/``counter_gap``,
        exactly like a real freeze taken at this instant would.
        """

        with self._lock:
            if self._frozen_snapshot is not None:
                return self._frozen_snapshot
            return self._snapshot_locked()

    def _complete(self, admission: Optional[F3Admission], bucket: str, payload_bytes: int, messages: int) -> None:
        if admission is None:
            return
        with self._lock:
            if admission._completed:
                raise RuntimeError("this F3Admission has already been completed once")
            admission._completed = True
            self._pending -= 1
            if self._frozen_snapshot is not None:
                # Linearized after freeze(): diagnostic-only, never mutates the
                # already-published snapshot.
                return
            self._buckets[bucket].add(payload_bytes, messages)

    def _discard(self, admission: Optional[F3Admission]) -> None:
        """Release an admission whose outcome is not counted in any public bucket."""

        if admission is None:
            return
        with self._lock:
            if admission._completed:
                raise RuntimeError("this F3Admission has already been completed once")
            admission._completed = True
            self._pending -= 1

    def _snapshot_locked(self) -> dict[str, Any]:
        gap = self._had_gap or self._pending > 0
        result: dict[str, Any] = {"status": "partial" if gap else "reported"}
        if gap:
            result["issues"] = ["counter_gap"]
        for bucket_name, bucket in self._buckets.items():
            result[bucket_name] = bucket.as_dict()
        return result
