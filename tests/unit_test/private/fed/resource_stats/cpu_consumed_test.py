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

"""Lifecycle CPU accounting: no periodic sampler or shared-parent CPU."""

import json
import subprocess
import sys
import time
from concurrent import futures
from decimal import Decimal

import pytest

from nvflare.private.fed.resource_stats import cpu_consumed as cpu_module
from nvflare.private.fed.resource_stats.cpu_consumed import CpuConsumedAccountant, resource


def _snapshots(start, end):
    values = iter((tuple(Decimal(item) for item in start), tuple(Decimal(item) for item in end)))
    return lambda: next(values)


class _Child:
    def __init__(self, returncode):
        self.returncode = returncode

    def poll(self):
        return self.returncode


def test_self_and_waited_children_are_added_once_without_parent_cpu():
    # The first delta is SELF, the second is the OS's already-inclusive
    # RUSAGE_CHILDREN. Individual worker reports must not be added again.
    accountant = CpuConsumedAccountant(usage_reader=_snapshots(("100", "40"), ("101.5", "42.25")))
    accountant.register_child(_Child(0))
    accountant.register_child(_Child(0))
    assert accountant.finish() == {"seconds": "3.75"}


def test_known_live_or_unwaited_worker_is_not_reported_as_complete():
    accountant = CpuConsumedAccountant(usage_reader=_snapshots(("0", "0"), ("1", "0.25")))
    accountant.register_child(_Child(None))
    assert accountant.finish() == {
        "status": "partial",
        "issues": ["attribution_incomplete"],
        "seconds": "1.25",
    }

    accountant = CpuConsumedAccountant(usage_reader=_snapshots(("0", "0"), ("1", "1")))
    accountant.register_child(_Child(0), descendants_may_be_unwaited=True)
    assert accountant.finish() == {
        "status": "partial",
        "issues": ["attribution_incomplete"],
        "seconds": "2",
    }


def test_missing_counter_and_prior_attempt_have_independent_status():
    def broken():
        raise OSError("counter unavailable")

    assert CpuConsumedAccountant(usage_reader=broken).finish() == {
        "status": "unavailable",
        "issues": ["observation_incomplete"],
    }
    restored = CpuConsumedAccountant(usage_reader=_snapshots(("0", "0"), ("1", "0")), prior_observation_incomplete=True)
    assert restored.finish() == {"status": "partial", "issues": ["observation_incomplete"], "seconds": "1"}


@pytest.mark.parametrize("pool_kind", ["encryptor", "adder", "decrypter"])
def test_xgboost_process_pools_do_not_claim_complete_cpu(monkeypatch, pool_kind):
    pytest.importorskip("xgboost")
    from nvflare.app_opt.xgboost.histogram_based_v2.sec.partial_he.adder import Adder
    from nvflare.app_opt.xgboost.histogram_based_v2.sec.partial_he.decrypter import Decrypter
    from nvflare.app_opt.xgboost.histogram_based_v2.sec.partial_he.encryptor import Encryptor

    accountant = CpuConsumedAccountant(usage_reader=_snapshots(("0", "0"), ("1", "0")))
    monkeypatch.setattr(cpu_module, "_active", accountant)
    monkeypatch.setattr(futures, "ProcessPoolExecutor", lambda **_kwargs: object())
    if pool_kind == "encryptor":
        Encryptor(pubkey="test")
    elif pool_kind == "adder":
        Adder()
    else:
        Decrypter(private_key="test")

    assert accountant.finish() == {"status": "partial", "issues": ["attribution_incomplete"], "seconds": "1"}


@pytest.mark.skipif(resource is None, reason="waited-child CPU accounting requires Unix")
def test_cpu_work_vs_sleep_and_short_lived_waited_children():
    sleeping = CpuConsumedAccountant()
    time.sleep(0.06)
    sleep_cpu = Decimal(sleeping.finish()["seconds"])

    working = CpuConsumedAccountant()
    sum(range(18_000_000))
    work_cpu = Decimal(working.finish()["seconds"])
    assert work_cpu > sleep_cpu + Decimal("0.02")

    # Both workers have exited before the one and only final measurement.
    children = CpuConsumedAccountant()
    for _ in range(2):
        subprocess.run([sys.executable, "-c", "sum(range(12000000))"], check=True)
    child_cpu = Decimal(children.finish()["seconds"])
    assert child_cpu > Decimal("0.05")


@pytest.mark.skipif(resource is None, reason="waited-child CPU accounting requires Unix")
def test_two_concurrent_job_processes_do_not_count_shared_parent_cpu():
    program = (
        "import json,time; "
        "from nvflare.private.fed.resource_stats.cpu_consumed import CpuConsumedAccountant; "
        "a=CpuConsumedAccountant(); "
        "sum(range(12000000)); "
        "print(json.dumps(a.finish()))"
    )
    processes = [subprocess.Popen([sys.executable, "-c", program], stdout=subprocess.PIPE, text=True) for _ in range(2)]
    outputs = [process.communicate(timeout=10)[0] for process in processes]
    assert all(process.returncode == 0 for process in processes)
    records = [json.loads(output) for output in outputs]
    assert all("status" not in record and Decimal(record["seconds"]) > 0 for record in records)
