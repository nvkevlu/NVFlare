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

"""Build job-process traffic reports from independent CellNet counters."""

import threading
import weakref

from .contract import normalize_measurement

_LOCK = threading.Lock()
_TRAINERS = weakref.WeakKeyDictionary()


class _TrainerTraffic:
    def __init__(self):
        self.pending = {}
        self.sent = 0
        self.received = 0
        self.observed = False
        self.incomplete = False


def register_external_trainer(job_cell, trainer_fqcn):
    """Expect one snapshot from an already launched, managed trainer."""
    try:
        with _LOCK:
            state = _TRAINERS.setdefault(job_cell, _TrainerTraffic())
            state.pending.setdefault(trainer_fqcn, None)
    except Exception:
        # Statistics must not affect trainer launch or communication.
        pass


def record_external_trainer_traffic(job_cell, trainer_fqcn, traffic, *, incomplete=False):
    """Accept cumulative totals only after the existing session checks succeed."""
    try:
        checked = normalize_measurement("message_traffic", traffic)
        values = (
            int(checked["sent_bytes"]),
            int(checked["received_bytes"]),
            incomplete or checked.get("status") == "partial",
        )
        with _LOCK:
            state = _TRAINERS.get(job_cell)
            if state is None or trainer_fqcn not in state.pending:
                return
            previous = state.pending[trainer_fqcn]
            if previous is not None:
                # A retried or delayed notification must not count a source twice
                # or overwrite newer cumulative counts with older values.
                advances = all(new >= old for old, new in zip(previous[:2], values[:2])) and any(
                    new > old for old, new in zip(previous[:2], values[:2])
                )
                incomplete = values[2] or (previous[2] and not advances)
                values = tuple(max(old, new) for old, new in zip(previous[:2], values[:2])) + (incomplete,)
            state.pending[trainer_fqcn] = values
    except Exception:
        try:
            with _LOCK:
                state = _TRAINERS.get(job_cell)
                if state is not None and trainer_fqcn in state.pending:
                    state.incomplete = True
        except Exception:
            pass


def retire_external_trainer(job_cell, trainer_fqcn, *, incomplete=False):
    """Fold a stopped trainer into totals and release launch-specific state."""
    try:
        with _LOCK:
            state = _TRAINERS.get(job_cell)
            if state is None or trainer_fqcn not in state.pending:
                return
            values = state.pending.pop(trainer_fqcn)
            if values is None:
                state.incomplete = True
            else:
                state.sent += values[0]
                state.received += values[1]
                state.observed = True
                state.incomplete = state.incomplete or incomplete or values[2]
    except Exception:
        pass


def snapshot_message_traffic(cell, *, incomplete=False):
    """Sum observed job-cell and managed-trainer sent/received payload bytes.

    The snapshot is immediate: no counter reset, transfer drain, or new request.
    Shared parent-process traffic is not attributed to this job. Each endpoint's
    traffic counts separately, including real transfers between local processes.
    """
    values = []
    try:
        raw = cell.get_traffic_stats()
        peers = raw["peers"]
        counters = [*peers.values(), raw["unattributed"]]
        if any(
            type(item[name]) is not int or item[name] < 0
            for item in counters
            for name in ("sent_bytes", "received_bytes")
        ):
            raise ValueError("invalid CellNet byte counter")
        values.append(
            (
                sum(item["sent_bytes"] for item in counters),
                sum(item["received_bytes"] for item in counters),
            )
        )
    except Exception:
        incomplete = True
    try:
        with _LOCK:
            state = _TRAINERS.get(cell)
            if state is not None:
                if state.observed:
                    values.append((state.sent, state.received))
                incomplete = incomplete or state.incomplete
                for observation in state.pending.values():
                    if observation is None:
                        incomplete = True
                    else:
                        values.append(observation[:2])
                        incomplete = incomplete or observation[2]
    except Exception:
        incomplete = True
    if not values:
        return {"status": "unavailable", "issues": ["observation_incomplete"]}
    result = {
        "sent_bytes": str(sum(value[0] for value in values)),
        "received_bytes": str(sum(value[1] for value in values)),
    }
    if incomplete:
        result.update(status="partial", issues=["observation_incomplete"])
    try:
        return normalize_measurement("message_traffic", result)
    except Exception:
        return {"status": "unavailable", "issues": ["observation_incomplete"]}
