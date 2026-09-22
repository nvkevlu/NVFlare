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

"""Fail-safe bridge from trusted NVFlare call sites to F3 transport accounting."""

from __future__ import annotations

from nvflare.fuel.f3.send_accounting import attach_logical_send_context

from .f3_counter import F3Counter, F3TrafficClass


def attach_f3_context(message, counter: F3Counter | None, traffic_class: F3TrafficClass) -> bool:
    """Attach process-local accounting without ever changing send behavior.

    Traffic classification is deliberately supplied only by the trusted
    semantic call site.  It is not placed in a wire header.  If accounting
    itself fails, keep the application send working and prevent the eventual
    snapshot from claiming complete attribution.
    """

    if counter is None:
        return False
    try:
        attach_logical_send_context(message, accounting=counter, traffic_class=traffic_class)
        return True
    except BaseException:
        try:
            counter.mark_counter_gap()
        except BaseException:
            pass
        return False
