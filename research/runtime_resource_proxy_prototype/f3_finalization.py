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

"""Prototype-only model for a finalizable, job-scoped F3 sender counter.

This module intentionally does not import or modify NVFlare's production F3
transport.  It fixes the contract a production hook must preserve:

* only a small, explicit allowlist of trusted job traffic classes contributes
  to the primary counter;
* a remote counter increment happens only after the transport-send callable
  returned normally, while direct delivery is kept in a separate bucket;
* summary publication is suppressed by an opaque in-process capability, never
  by a payload, topic, channel, or user-controlled label; and
* the first ``freeze()`` records a fixed event-sequence cutoff.  Events that
  complete after that cutoff remain visible only as post-publication diagnostics,
  never as circular fields inside the immutable participant summary.

The opaque capability is an integration boundary, not a sandbox against code
that can introspect arbitrary Python objects in the same process.  A product
implementation would keep it in platform-owned delivery code and bind traffic
classes from a trusted lifecycle registry rather than from message headers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import Any, Callable, TypeVar


class JobTrafficClass(str, Enum):
    """Bounded logical classes supplied by trusted platform integration."""

    TASK_REQUEST = "task_request"
    TASK_RESPONSE = "task_response"
    TASK_RESULT = "task_result"
    JOB_APPLICATION = "job_application"
    JOB_STREAM_DATA = "job_stream_data"

    # These are deliberately modeled so an explicit allowlist—not an implicit
    # catch-all—can reject them from the primary resource proxy.
    JOB_STREAM_CONTROL = "job_stream_control"
    BULK_ENVELOPE = "bulk_envelope"
    WORKSPACE_TRANSFER = "workspace_transfer"
    PLATFORM_CONTROL = "platform_control"
    LOG_EXPORT = "log_export"


INCLUDED_JOB_TRAFFIC_CLASSES = frozenset(
    {
        JobTrafficClass.TASK_REQUEST,
        JobTrafficClass.TASK_RESPONSE,
        JobTrafficClass.TASK_RESULT,
        JobTrafficClass.JOB_APPLICATION,
        JobTrafficClass.JOB_STREAM_DATA,
    }
)


@dataclass(frozen=True)
class JobTrafficEvent:
    """A post-serialization/encryption payload observation for one logical hop."""

    traffic_class: JobTrafficClass
    payload_bytes: int
    message_count: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.traffic_class, JobTrafficClass):
            raise TypeError("traffic_class must be a JobTrafficClass")
        if isinstance(self.payload_bytes, bool) or not isinstance(self.payload_bytes, int):
            raise TypeError("payload_bytes must be an integer")
        if self.payload_bytes < 0:
            raise ValueError("payload_bytes must not be negative")
        if isinstance(self.message_count, bool) or not isinstance(self.message_count, int):
            raise TypeError("message_count must be an integer")
        if self.message_count <= 0:
            raise ValueError("message_count must be positive")


@dataclass
class _Totals:
    payload_bytes: int = 0
    message_count: int = 0

    def add(self, event: JobTrafficEvent) -> None:
        self.payload_bytes += event.payload_bytes
        self.message_count += event.message_count

    def as_payload_totals(self) -> dict[str, int]:
        return {"payload_bytes": self.payload_bytes, "message_count": self.message_count}

    def as_attempt_totals(self) -> dict[str, int]:
        return {
            "attempted_payload_bytes": self.payload_bytes,
            "attempted_message_count": self.message_count,
        }


T = TypeVar("T")


class _SummaryPublicationSender:
    """Platform-owned summary-delivery facade carrying the opaque capability."""

    __slots__ = ("_counter", "_capability")

    def __init__(self, counter: "F3FinalizationCounter", capability: object):
        self._counter = counter
        self._capability = capability

    def send_remote(self, event: JobTrafficEvent, transport_send: Callable[[], T]) -> T:
        """Deliver a terminal summary without adding it to the job F3 proxy."""

        return self._counter._send_remote(event, transport_send, capability=self._capability)

    def deliver_direct(self, event: JobTrafficEvent, direct_delivery: Callable[[], T]) -> T:
        """Deliver a local terminal summary without adding it to the job proxy."""

        return self._counter._deliver_direct(event, direct_delivery, capability=self._capability)


class F3FinalizationCounter:
    """Thread-safe model of one logical participant's F3 finalization boundary.

    ``send_remote`` considers a transport accepted only when ``transport_send``
    returns normally.  This mirrors the current F3 ``communicator.send``
    boundary, whose failure signal is an exception.  It is intentionally not a
    receiver-delivery acknowledgement.  The counter belongs to the durable
    participant lifecycle owner so it can span zero or more transient compute
    attempts and the GPU-free gaps between them.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._summary_publication_capability = object()
        self._event_sequence = 0
        self._cutoff_sequence: int | None = None

        self._remote_accepted = _Totals()
        self._local_delivery = _Totals()
        self._before_transport_acceptance_failed = _Totals()
        self._direct_delivery_failed = _Totals()
        self._excluded_summary_publication = _Totals()
        self._excluded_traffic_class = _Totals()
        self._late_after_cutoff = _Totals()

    @property
    def included_traffic_classes(self) -> frozenset[JobTrafficClass]:
        """The exact classes that can contribute before the cutoff."""

        return INCLUDED_JOB_TRAFFIC_CLASSES

    def summary_publisher(self) -> _SummaryPublicationSender:
        """Return the sole facade that can mark a send as summary publication."""

        return _SummaryPublicationSender(self, self._summary_publication_capability)

    def send_remote(self, event: JobTrafficEvent, transport_send: Callable[[], T]) -> T:
        """Send remotely and count only a transport-accepted outcome."""

        return self._send_remote(event, transport_send, capability=None)

    def deliver_direct(self, event: JobTrafficEvent, direct_delivery: Callable[[], T]) -> T:
        """Deliver directly and retain it separately from remote transport."""

        return self._deliver_direct(event, direct_delivery, capability=None)

    def freeze(self) -> dict[str, Any]:
        """Fix the first cutoff; repeated calls leave that cutoff unchanged."""

        with self._lock:
            if self._cutoff_sequence is None:
                self._cutoff_sequence = self._event_sequence
            return self._snapshot_locked()

    def snapshot(self) -> dict[str, Any]:
        """Return JSON-safe primary totals, diagnostics, and cutoff state."""

        with self._lock:
            return self._snapshot_locked()

    def _send_remote(
        self,
        event: JobTrafficEvent,
        transport_send: Callable[[], T],
        *,
        capability: object | None,
    ) -> T:
        try:
            result = transport_send()
        except Exception:
            self._record(event, accepted=False, direct=False, capability=capability)
            raise
        self._record(event, accepted=True, direct=False, capability=capability)
        return result

    def _deliver_direct(
        self,
        event: JobTrafficEvent,
        direct_delivery: Callable[[], T],
        *,
        capability: object | None,
    ) -> T:
        try:
            result = direct_delivery()
        except Exception:
            self._record(event, accepted=False, direct=True, capability=capability)
            raise
        self._record(event, accepted=True, direct=True, capability=capability)
        return result

    def _record(self, event: JobTrafficEvent, *, accepted: bool, direct: bool, capability: object | None) -> None:
        with self._lock:
            self._event_sequence += 1

            if event.traffic_class not in INCLUDED_JOB_TRAFFIC_CLASSES:
                self._excluded_traffic_class.add(event)
                return
            if capability is self._summary_publication_capability:
                self._excluded_summary_publication.add(event)
                return
            if self._cutoff_sequence is not None:
                self._late_after_cutoff.add(event)
                return

            if accepted and direct:
                self._local_delivery.add(event)
            elif accepted:
                self._remote_accepted.add(event)
            elif direct:
                self._direct_delivery_failed.add(event)
            else:
                self._before_transport_acceptance_failed.add(event)

    def _snapshot_locked(self) -> dict[str, Any]:
        return {
            "included_traffic_classes": sorted(traffic_class.value for traffic_class in INCLUDED_JOB_TRAFFIC_CLASSES),
            "finalization": {
                "state": "frozen" if self._cutoff_sequence is not None else "collecting",
                "accepted_event_sequence_cutoff": self._cutoff_sequence,
            },
            "outcomes": {
                "remote_transport_accepted": self._remote_accepted.as_payload_totals(),
                "local_delivery": self._local_delivery.as_payload_totals(),
            },
            "diagnostics": {
                "before_transport_acceptance_failed": self._before_transport_acceptance_failed.as_attempt_totals(),
                "direct_delivery_failed": self._direct_delivery_failed.as_attempt_totals(),
                "excluded_summary_publication": self._excluded_summary_publication.as_payload_totals(),
                "excluded_traffic_class": self._excluded_traffic_class.as_payload_totals(),
                "late_after_cutoff": self._late_after_cutoff.as_payload_totals(),
            },
        }
