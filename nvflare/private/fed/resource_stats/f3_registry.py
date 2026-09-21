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

"""Per-job :class:`F3Counter` ownership for a long-lived parent process.

A job process (SJ/CJ) only ever runs one job, so it can own a single
process-global counter. A parent process (SP: the root server; CP: a client
parent) is long-lived and handles many jobs over its lifetime -- often
concurrently on the server side -- so it needs one counter per job_id, kept
alive from job start through finalization and discarded afterward. This is
that per-job registry; it owns no traffic-classification logic itself (that
lives at the trusted NVFlare call sites that will use ``get()``).
"""

from __future__ import annotations

import threading
from typing import Optional

from .f3_counter import F3Counter


class F3CounterRegistry:
    """Thread-safe job_id -> F3Counter registry for one parent process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, F3Counter] = {}

    def start_job(self, job_id: str) -> F3Counter:
        """Create (or return the existing) counter for a job.

        Idempotent so a caller does not need to track whether it already
        started this job's counter.
        """

        with self._lock:
            counter = self._counters.get(job_id)
            if counter is None:
                counter = F3Counter()
                self._counters[job_id] = counter
            return counter

    def get(self, job_id: str) -> Optional[F3Counter]:
        """Return the job's counter, or ``None`` if it was never started (or already forgotten)."""

        with self._lock:
            return self._counters.get(job_id)

    def close_and_freeze(self, job_id: str) -> Optional[dict]:
        """Stop admission and fix the immutable snapshot for a job's counter, if one exists.

        Callers that need a bounded drain between admission close and freeze
        (F3_GAP.md's "allows already-classified sends to drain for at most
        five seconds" for a parent process) should call ``get(job_id).close()``
        themselves, poll ``pending_count``, and only then call this -- or
        ``F3Counter.freeze()`` directly. This convenience method is for the
        no-drain-needed case (nothing is bound to the counter yet).
        """

        counter = self.get(job_id)
        if counter is None:
            return None
        counter.close()
        return counter.freeze()

    def forget_job(self, job_id: str) -> None:
        """Drop the registry's reference to a job's counter. Safe to call on an unknown job_id."""

        with self._lock:
            self._counters.pop(job_id, None)
