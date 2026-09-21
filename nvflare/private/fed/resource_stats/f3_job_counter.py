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

"""Process-global F3Counter access for a job process (SJ or CJ).

Unlike a parent process (SP/CP, see ``f3_registry.py``), a job process
(``worker_process.py``/``runner_process.py``) only ever runs one job, so a
single counter for the whole process's lifetime is sufficient -- there is no
job_id to key by. A module-level singleton (rather than nesting this inside
``JobResourceCollector``) is deliberate: the code that will eventually record
into it (task pull, task result send, deep inside ``communicator.py`` and
friends -- F3_GAP.md steps 3-5) has no reference to the ``JobResourceCollector``
instance ``worker_process.py``/``runner_process.py`` construct locally, and
should not need one just to record a send.
"""

from __future__ import annotations

import threading
from typing import Optional

from .f3_counter import F3Counter

_lock = threading.Lock()
_counter: Optional[F3Counter] = None


def start_job_f3_counter() -> F3Counter:
    """Create this process's counter. Must be called before any job code can run."""

    global _counter
    with _lock:
        _counter = F3Counter()
        return _counter


def get_job_f3_counter() -> Optional[F3Counter]:
    """Return this process's counter, or ``None`` if it was never started."""

    with _lock:
        return _counter


def clear_job_f3_counter() -> None:
    """Drop the reference so a later, unrelated import of this module starts clean.

    Job processes are short-lived (one job per process), so this mainly
    matters for test isolation.
    """

    global _counter
    with _lock:
        _counter = None
