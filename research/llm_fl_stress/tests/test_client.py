import unittest
from pathlib import Path

from research.llm_fl_stress.client import _client_api_config_path


class ClientConfigPathTest(unittest.TestCase):
    def test_config_path_is_resolved_from_deployed_app_layout(self):
        script_path = Path("/tmp/run/app_site-1/custom/client.py")

        config_path = _client_api_config_path(script_path)

        expected = Path("/tmp/run/app_site-1/config/client_api_config.json").resolve()
        self.assertEqual(expected, config_path)


if __name__ == "__main__":
    unittest.main()
