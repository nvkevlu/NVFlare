import json
import tempfile
import unittest
from pathlib import Path

from research.llm_fl_stress.ops.transport_profiles import render_scenario

from test_config import PROJECT_DIR


class TransportProfilesTest(unittest.TestCase):
    def test_render_records_profile_and_one_round(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "scenario.json"
            render_scenario(
                PROJECT_DIR / "configs" / "qwen25-1.5b.json",
                output,
                "8m",
                "sweep-8m",
                "test profile",
            )
            scenario = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(1, scenario["federation"]["rounds"])
        self.assertEqual(8 * 1024 * 1024, scenario["transport"]["streaming_chunk_size"])
        self.assertEqual(256 * 1024 * 1024, scenario["transport"]["streaming_window_size"])


if __name__ == "__main__":
    unittest.main()
