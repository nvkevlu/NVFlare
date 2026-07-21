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

import unittest
from pathlib import Path

import torch

from research.llm_fl_stress.harness.config import load_scenario
from research.llm_fl_stress.harness.report import _event_metrics
from research.llm_fl_stress.server_observer import ServerResourceObserver, _summarize_tensor_owners


PROJECT_DIR = Path(__file__).resolve().parents[1]


class ServerObserverTest(unittest.TestCase):
    def test_tensor_storage_summary_deduplicates_aliases_and_owners(self):
        shared = torch.zeros(16, dtype=torch.float32)
        alias = shared.view(4, 4)
        independent = torch.zeros(8, dtype=torch.float32)

        result = _summarize_tensor_owners(
            {
                "shared_owner": {"shared": shared, "alias": alias},
                "mixed_owner": {"shared": shared, "independent": independent},
            }
        )

        self.assertEqual(96, result["unique_tensor_storage_bytes"])
        self.assertEqual(2, result["unique_tensor_storage_count"])
        self.assertEqual(64, result["tensor_storage_bytes_by_owner"]["shared_owner"])
        self.assertEqual(96, result["tensor_storage_bytes_by_owner"]["mixed_owner"])
        self.assertEqual(128, result["tensor_logical_bytes_by_owner"]["shared_owner"])

    def test_trim_probe_flag_requires_boolean(self):
        with self.assertRaisesRegex(TypeError, "must be a bool"):
            ServerResourceObserver(trim_before_first_contribution=1)

    def test_report_surfaces_allocator_trim_probe(self):
        scenario = load_scenario(PROJECT_DIR / "configs" / "qwen25-32b-trim-probe.json")
        metrics = _event_metrics(
            [
                {
                    "event": "server_allocator_trim_probe",
                    "round": 1,
                    "trigger": "before_first_contribution",
                    "rss_before_trim_bytes": 200,
                    "rss_bytes": 140,
                    "rss_released_by_trim_bytes": 60,
                    "cgroup_before_trim_bytes": 220,
                    "cgroup_memory_current_bytes": 160,
                    "tensor_storage_before_trim_bytes": 120,
                    "unique_tensor_storage_bytes": 120,
                    "tensor_storage_bytes_by_owner": {"persisted_weights": 60},
                }
            ],
            scenario,
        )

        self.assertEqual(60, metrics["allocator_trim_probes"][0]["rss_released_by_trim_bytes"])
        self.assertEqual(120, metrics["allocator_trim_probes"][0]["tensor_storage_after_trim_bytes"])


if __name__ == "__main__":
    unittest.main()
