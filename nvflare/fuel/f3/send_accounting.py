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

"""Process-local accounting context for one logical F3 send.

The context deliberately contains no wire representation.  A trusted caller
attaches it to a :class:`Message`, and the F3 send path carries the same Python
object through explicit local clones.  Serialization still sees only the
message headers and payload.

The accounting object is structural so this package does not depend on the
private resource-statistics implementation.  Its traffic-class value is also
opaque here: classification belongs to the trusted semantic caller.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Collection, Hashable, Optional, Protocol

log = logging.getLogger(__name__)
_CALL_FAILED = object()


class LogicalSendAccounting(Protocol):
    """Callback surface supplied by the job-scoped accounting owner."""

    def try_begin(self, traffic_class: object) -> Optional[object]:
        pass

    def complete_remote_accepted(self, admission: object, payload_bytes: int) -> bool:
        pass

    def add_accepted_payload_bytes(self, admission: object, payload_bytes: int) -> bool:
        pass

    def abandon(self, admission: object) -> bool:
        pass

    def mark_incomplete(self, admission: object) -> bool:
        pass

    def mark_counter_gap(self) -> bool:
        pass


@dataclass
class _DestinationState:
    begun: bool = False
    admission: Optional[object] = None
    main_accepted: bool = False
    main_payload_bytes: int = 0
    completed: bool = False
    abandoned: bool = False
    incomplete: bool = False
    pending_transactions: set[str] = field(default_factory=set)
    successful_transactions: set[str] = field(default_factory=set)
    inflight_contributions: set[Hashable] = field(default_factory=set)
    accepted_contributions: set[Hashable] = field(default_factory=set)
    queued_contributions: list[tuple[Hashable, int]] = field(default_factory=list)


class _SendAttempt:
    """One transport attempt admitted by a process-local context."""

    def __init__(self, accepted_cb, abandoned_cb):
        self._accepted_cb = accepted_cb
        self._abandoned_cb = abandoned_cb
        self._lock = threading.Lock()
        self._finished = False

    def accepted(self, payload_bytes: int) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
        self._accepted_cb(payload_bytes)

    def abandon(self) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
        self._abandoned_cb()


class _OobContributionContext:
    """A byte-only DownloadService response tied to a parent logical send."""

    def __init__(
        self,
        parent: "LogicalSendContext",
        destination: str,
        contribution_id: Hashable,
        payload_bytes: int,
    ):
        self._parent = parent
        self._destination = destination
        self._contribution_id = contribution_id
        self._payload_bytes = payload_bytes

    def is_origin(self, origin: str) -> bool:
        return self._parent.is_origin(origin)

    def try_begin(self, origin: str, destination: str) -> Optional[_SendAttempt]:
        if destination != self._destination:
            return None
        return self._parent._try_begin_contribution(
            origin=origin,
            destination=destination,
            contribution_id=self._contribution_id,
            payload_bytes=self._payload_bytes,
        )

    def mark_counter_gap(self) -> None:
        self._parent.mark_counter_gap()


class LogicalSendContext:
    """Origin-owned state for one logical message and all of its destinations."""

    def __init__(self, accounting: LogicalSendAccounting, traffic_class: object):
        self._accounting = accounting
        self._traffic_class = traffic_class
        self._origin: Optional[str] = None
        self._lock = threading.RLock()
        self._destinations: dict[str, _DestinationState] = {}
        self._transaction_receivers: dict[str, Optional[frozenset[str]]] = {}
        self._transaction_results: dict[str, frozenset[str]] = {}

    def is_origin(self, origin: str) -> bool:
        """Whether ``origin`` may originate this still-local context."""

        with self._lock:
            return self._origin is None or self._origin == origin

    def mark_counter_gap(self) -> None:
        """Record a pre-admission instrumentation failure without raising."""

        self._safe_call("mark_counter_gap")

    def try_begin(self, origin: str, destination: str) -> Optional[_SendAttempt]:
        """Admit the main logical send once for this origin and destination."""

        if not origin or not destination:
            return None

        with self._lock:
            if self._origin is None:
                self._origin = origin
            elif self._origin != origin:
                # A process-local direct delivery can retain the Python attribute.
                # Only the Cell that first originated this logical send may count it.
                return None

            state = self._destinations.setdefault(destination, _DestinationState())
            if state.begun:
                return None
            state.begun = True
            state.pending_transactions = {
                tx_id
                for tx_id, receivers in self._transaction_receivers.items()
                if receivers is not None and destination in receivers and tx_id not in self._transaction_results
            }
            unknown_transaction = any(receivers is None for receivers in self._transaction_receivers.values())
            destination_has_transaction = any(
                receivers is not None and destination in receivers for receivers in self._transaction_receivers.values()
            )
            unbound_destination = bool(self._transaction_receivers) and not destination_has_transaction

        admission = self._safe_call("try_begin", self._traffic_class, failed_value=_CALL_FAILED)
        if admission is _CALL_FAILED or admission is None:
            if admission is _CALL_FAILED:
                self._safe_call("mark_counter_gap")
            return None

        with self._lock:
            state.admission = admission
            queued_contributions = tuple(state.queued_contributions)
            state.queued_contributions.clear()
            already_failed = any(
                tx_id in self._transaction_results
                and destination not in self._transaction_results[tx_id]
                and self._transaction_receivers.get(tx_id) is not None
                and destination in self._transaction_receivers[tx_id]
                for tx_id in self._transaction_results
            )
            should_mark_incomplete = state.incomplete or unknown_transaction or unbound_destination or already_failed
            if should_mark_incomplete:
                state.incomplete = True

        if should_mark_incomplete:
            self._safe_call("mark_incomplete", admission)
            return None

        for contribution_id, payload_bytes in queued_contributions:
            added = self._add_payload_bytes(destination, payload_bytes)
            with self._lock:
                state.inflight_contributions.discard(contribution_id)
            if not added:
                return None

        return _SendAttempt(
            accepted_cb=lambda payload_bytes: self._main_accepted(destination, payload_bytes),
            abandoned_cb=lambda: self._main_abandoned(destination),
        )

    def register_oob_transaction(self, transaction_id: str, receiver_ids: Optional[Collection[str]]) -> None:
        """Register a FOBS DownloadService transaction before transport admission."""

        try:
            receivers = None if not receiver_ids else frozenset(str(receiver) for receiver in receiver_ids)
        except BaseException as ex:
            log.warning("logical-send accounting could not normalize DownloadService receivers: %s", ex)
            receivers = None

        incomplete_destinations = []
        duplicate = False
        with self._lock:
            existing = self._transaction_receivers.get(transaction_id)
            if existing is not None or transaction_id in self._transaction_receivers:
                if existing != receivers:
                    incomplete_destinations.extend(self._destinations)
                duplicate = True
            else:
                self._transaction_receivers[transaction_id] = receivers
                if receivers is None:
                    incomplete_destinations.extend(self._destinations)
                else:
                    for destination, state in self._destinations.items():
                        if destination in receivers:
                            if state.begun:
                                # FOBS finalizers run during encoding, before transport
                                # admission.  A later registration cannot be proven complete.
                                incomplete_destinations.append(destination)
                            else:
                                state.pending_transactions.add(transaction_id)

        for destination in incomplete_destinations:
            self._mark_incomplete(destination)
        if duplicate:
            return

    def make_oob_contribution_context(
        self,
        transaction_id: str,
        destination: str,
        contribution_id: Hashable,
        payload_bytes: int,
    ) -> Optional[_OobContributionContext]:
        """Create a byte-only context for one DownloadService data response."""

        if isinstance(payload_bytes, bool) or not isinstance(payload_bytes, int) or payload_bytes < 0:
            return None
        with self._lock:
            receivers = self._transaction_receivers.get(transaction_id)
            if receivers is None or destination not in receivers:
                return None
        return _OobContributionContext(self, destination, contribution_id, payload_bytes)

    def mark_oob_incomplete(self, destination: str) -> None:
        """Fail safe when a DownloadService contribution cannot be identified."""

        self._mark_incomplete(destination)

    def settle_oob_transaction(self, transaction_id: str, successful_receivers: Collection[str]) -> None:
        """Settle one registered transaction using its per-receiver terminal truth."""

        try:
            successful = frozenset(str(receiver) for receiver in successful_receivers)
        except BaseException as ex:
            log.warning("logical-send accounting could not normalize DownloadService outcome: %s", ex)
            successful = frozenset()

        to_incomplete = []
        to_complete = []
        with self._lock:
            if transaction_id in self._transaction_results:
                return
            self._transaction_results[transaction_id] = successful
            receivers = self._transaction_receivers.get(transaction_id)
            if receivers is None:
                to_incomplete.extend(self._destinations)
            else:
                for destination in receivers:
                    state = self._destinations.setdefault(destination, _DestinationState())
                    state.pending_transactions.discard(transaction_id)
                    if destination in successful:
                        state.successful_transactions.add(transaction_id)
                        completion = self._take_completion_locked(destination, state)
                        if completion:
                            to_complete.append(completion)
                    else:
                        to_incomplete.append(destination)

        for destination in to_incomplete:
            self._mark_incomplete(destination)
        for admission, payload_bytes in to_complete:
            self._safe_call("complete_remote_accepted", admission, payload_bytes)

    def _try_begin_contribution(
        self,
        origin: str,
        destination: str,
        contribution_id: Hashable,
        payload_bytes: int,
    ) -> Optional[_SendAttempt]:
        with self._lock:
            if self._origin is None or self._origin != origin:
                return None
            state = self._destinations.setdefault(destination, _DestinationState())
            if state.completed or state.abandoned or state.incomplete:
                return None
            if contribution_id in state.accepted_contributions or contribution_id in state.inflight_contributions:
                return None
            state.inflight_contributions.add(contribution_id)

        return _SendAttempt(
            accepted_cb=lambda _encoded_size: self._contribution_accepted(destination, contribution_id, payload_bytes),
            abandoned_cb=lambda: self._contribution_abandoned(destination, contribution_id),
        )

    def _main_accepted(self, destination: str, payload_bytes: int) -> None:
        if isinstance(payload_bytes, bool) or not isinstance(payload_bytes, int) or payload_bytes < 0:
            self._mark_incomplete(destination)
            return

        completion = None
        with self._lock:
            state = self._destinations[destination]
            if state.completed or state.abandoned or state.incomplete:
                return
            state.main_accepted = True
            state.main_payload_bytes = payload_bytes
            completion = self._take_completion_locked(destination, state)

        if completion:
            self._safe_call("complete_remote_accepted", *completion)

    def _main_abandoned(self, destination: str) -> None:
        admission = None
        with self._lock:
            state = self._destinations[destination]
            if state.completed or state.abandoned or state.incomplete:
                return
            state.abandoned = True
            admission = state.admission
        if admission is not None:
            self._safe_call("abandon", admission)

    def _contribution_accepted(self, destination: str, contribution_id: Hashable, payload_bytes: int) -> None:
        queue_only = False
        with self._lock:
            state = self._destinations[destination]
            if state.completed or state.abandoned or state.incomplete:
                state.inflight_contributions.discard(contribution_id)
                return
            if contribution_id in state.accepted_contributions:
                state.inflight_contributions.discard(contribution_id)
                return
            state.accepted_contributions.add(contribution_id)
            if state.admission is None:
                state.queued_contributions.append((contribution_id, payload_bytes))
                queue_only = True
        if queue_only:
            return

        added = self._add_payload_bytes(destination, payload_bytes)
        with self._lock:
            state.inflight_contributions.discard(contribution_id)
        if added:
            self._complete_if_ready(destination)

    def _contribution_abandoned(self, destination: str, contribution_id: Hashable) -> None:
        admission = None
        with self._lock:
            state = self._destinations[destination]
            state.inflight_contributions.discard(contribution_id)
            if state.completed or state.abandoned or state.incomplete:
                return
            state.incomplete = True
            admission = state.admission
        if admission is not None:
            self._safe_call("mark_incomplete", admission)

    def _add_payload_bytes(self, destination: str, payload_bytes: int) -> bool:
        with self._lock:
            state = self._destinations[destination]
            if state.completed or state.abandoned or state.incomplete or state.admission is None:
                return False
            admission = state.admission
        result = self._safe_call("add_accepted_payload_bytes", admission, payload_bytes, failed_value=_CALL_FAILED)
        if result is not True:
            self._mark_incomplete(destination)
            return False
        return True

    def _complete_if_ready(self, destination: str) -> None:
        completion = None
        with self._lock:
            state = self._destinations[destination]
            completion = self._take_completion_locked(destination, state)
        if completion:
            self._safe_call("complete_remote_accepted", *completion)

    def _take_completion_locked(self, destination: str, state: _DestinationState):
        if not self._ready_to_complete_locked(destination, state):
            return None
        state.completed = True
        return state.admission, state.main_payload_bytes

    def _mark_incomplete(self, destination: str) -> None:
        admission = None
        mark_counter_gap = False
        with self._lock:
            state = self._destinations.setdefault(destination, _DestinationState())
            if state.abandoned or state.incomplete:
                return
            if state.completed:
                # The operation has already been published.  A valid FOBS path
                # registers before admission, so late evidence can only be
                # represented as an aggregate counter gap.
                mark_counter_gap = True
            else:
                state.incomplete = True
                admission = state.admission
        if mark_counter_gap:
            self._safe_call("mark_counter_gap")
            return
        if admission is not None:
            self._safe_call("mark_incomplete", admission)

    def _ready_to_complete_locked(self, destination: str, state: _DestinationState) -> bool:
        if (
            not state.main_accepted
            or state.admission is None
            or state.completed
            or state.abandoned
            or state.incomplete
            or state.pending_transactions
            or state.inflight_contributions
        ):
            return False

        for transaction_id, receivers in self._transaction_receivers.items():
            if receivers is None:
                return False
            if destination in receivers and transaction_id not in state.successful_transactions:
                return False
        return True

    def _safe_call(self, method_name: str, *args, failed_value=None):
        try:
            method = getattr(self._accounting, method_name)
            return method(*args)
        except BaseException as ex:
            # Accounting is observational.  Even a malformed callback must not
            # change the transport result or suppress delivery.
            log.warning("logical-send accounting callback %s failed: %s", method_name, ex)
            return failed_value


def attach_logical_send_context(
    message, accounting: LogicalSendAccounting, traffic_class: object
) -> LogicalSendContext:
    """Attach one trusted, process-local logical-send context to ``message``."""

    context = LogicalSendContext(accounting=accounting, traffic_class=traffic_class)
    message.set_logical_send_context(context)
    return context
