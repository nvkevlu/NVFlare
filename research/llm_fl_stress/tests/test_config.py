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

import json
import tempfile
import unittest
from pathlib import Path

from research.llm_fl_stress.harness.config import load_scenario
from research.llm_fl_stress.harness.preflight import assess_capacity, assess_distributed_capacity


PROJECT_DIR = Path(__file__).resolve().parents[1]


class ScenarioConfigTest(unittest.TestCase):
    def test_all_scenarios_load(self):
        scenarios = [load_scenario(path) for path in sorted((PROJECT_DIR / "configs").glob("*.json"))]

        self.assertEqual(23, len(scenarios))
        self.assertTrue(all(scenario.payload_bytes > 0 for scenario in scenarios))
        self.assertTrue(all(scenario.planned_server_capacity_bytes > scenario.payload_bytes for scenario in scenarios))
        self.assertTrue(all(scenario.monitoring.sample_interval_seconds == 0.5 for scenario in scenarios))

    def test_trim_probe_is_explicitly_enabled(self):
        scenario = load_scenario(PROJECT_DIR / "configs" / "qwen25-32b-trim-probe.json")

        self.assertTrue(scenario.federation.server_trim_before_first_contribution)

    def test_three_client_probe_has_expected_topology_and_wire_volume(self):
        scenario = load_scenario(PROJECT_DIR / "configs" / "qwen25-32b-3client-trim-probe.json")

        self.assertEqual(["site-1", "site-2", "site-3"], scenario.federation.clients)
        self.assertEqual(390_000_000_000, scenario.expected_wire_bytes_per_round)
        self.assertTrue(scenario.federation.server_trim_before_first_contribution)
        self.assertEqual(
            {
                "NVFLARE_STREAMING_ACK_INTERVAL": "33554432",
                "NVFLARE_STREAMING_CHUNK_SIZE": "4194304",
                "NVFLARE_STREAMING_MAX_OUT_SEQ_CHUNKS": "64",
                "NVFLARE_STREAMING_WINDOW_SIZE": "134217728",
            },
            scenario.transport.f3_service_environment,
        )

    def test_f3_tuned_probe_records_service_environment(self):
        scenario = load_scenario(PROJECT_DIR / "configs" / "qwen25-32b-f3-tuned-1r.json")

        self.assertEqual(
            {
                "NVFLARE_STREAMING_ACK_INTERVAL": "33554432",
                "NVFLARE_STREAMING_CHUNK_SIZE": "4194304",
                "NVFLARE_STREAMING_WINDOW_SIZE": "134217728",
            },
            scenario.transport.f3_service_environment,
        )

    def test_smoke_payload_is_exact(self):
        scenario = load_scenario(PROJECT_DIR / "configs" / "smoke.json")

        self.assertEqual(67_108_864, scenario.payload_bytes)
        self.assertEqual(268_435_456, scenario.expected_wire_bytes_per_round)
        self.assertEqual(1_845_493_760, scenario.planned_server_capacity_bytes)
        self.assertEqual(880_803_840, scenario.planned_client_capacity_bytes)
        self.assertEqual(3_607_101_440, scenario.planned_simulation_capacity_bytes)
        self.assertEqual(335_544_320, scenario.planned_disk_capacity_bytes)

    def test_capacity_preflight_reports_specific_risks(self):
        scenario = load_scenario(PROJECT_DIR / "configs" / "smoke.json")

        result = assess_capacity(
            scenario,
            available_memory_bytes=scenario.planned_simulation_capacity_bytes - 1,
            free_disk_bytes=scenario.planned_disk_capacity_bytes,
        )

        self.assertFalse(result["passed"])
        self.assertEqual(["memory"], result["risks"])

    def test_distributed_capacity_checks_each_role(self):
        scenario = load_scenario(PROJECT_DIR / "configs" / "smoke.json")
        snapshots = {
            "server": {
                "available_memory_bytes": scenario.planned_server_capacity_bytes,
                "free_disk_bytes": scenario.planned_disk_capacity_bytes,
            },
            "site-1": {
                "available_memory_bytes": scenario.planned_client_capacity_bytes - 1,
                "free_disk_bytes": scenario.payload_bytes * 2,
            },
            "site-2": {
                "available_memory_bytes": scenario.planned_client_capacity_bytes,
                "free_disk_bytes": scenario.payload_bytes * 2,
            },
        }

        result = assess_distributed_capacity(scenario, snapshots, "server", ["site-1", "site-2"])

        self.assertFalse(result["passed"])
        self.assertEqual(["site-1.memory"], result["risks"])

    def test_unknown_field_is_rejected(self):
        source = json.loads((PROJECT_DIR / "configs" / "smoke.json").read_text(encoding="utf-8"))
        source["model"]["unexpected"] = True
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid.json"
            path.write_text(json.dumps(source), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "unknown field"):
                load_scenario(path)

    def test_transfer_timeout_relationship_is_enforced(self):
        source = json.loads((PROJECT_DIR / "configs" / "smoke.json").read_text(encoding="utf-8"))
        source["transport"]["get_task_timeout"] = 10
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid.json"
            path.write_text(json.dumps(source), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "get_task_timeout"):
                load_scenario(path)

    def test_clients_must_match_sentinel_sequence(self):
        source = json.loads((PROJECT_DIR / "configs" / "smoke.json").read_text(encoding="utf-8"))
        source["federation"]["clients"] = ["alpha", "beta"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid.json"
            path.write_text(json.dumps(source), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "sequential site names"):
                load_scenario(path)


if __name__ == "__main__":
    unittest.main()
