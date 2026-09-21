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

from nvflare.private.fed.resource_stats.f3_counter import F3Counter
from nvflare.private.fed.resource_stats.f3_registry import F3CounterRegistry


def test_start_job_creates_and_returns_the_same_counter():
    registry = F3CounterRegistry()

    first = registry.start_job("job-1")
    second = registry.start_job("job-1")

    assert isinstance(first, F3Counter)
    assert first is second
    assert registry.get("job-1") is first


def test_get_returns_none_for_unknown_job():
    registry = F3CounterRegistry()

    assert registry.get("no-such-job") is None


def test_forget_job_drops_the_counter_and_is_a_no_op_for_unknown_job():
    registry = F3CounterRegistry()
    registry.start_job("job-1")

    registry.forget_job("job-1")

    assert registry.get("job-1") is None
    registry.forget_job("job-1")
    registry.forget_job("no-such-job")


def test_two_jobs_get_independent_counters():
    registry = F3CounterRegistry()

    counter_a = registry.start_job("job-a")
    counter_b = registry.start_job("job-b")

    assert counter_a is not counter_b
    counter_a.freeze()
    assert counter_b.state == "collecting"
