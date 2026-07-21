import unittest

from research.llm_fl_stress.ops.deploy_services import build_streaming_environment


class DeployServicesTest(unittest.TestCase):
    def test_streaming_environment_uses_nvflare_names(self):
        self.assertEqual(
            {
                "NVFLARE_STREAMING_ACK_INTERVAL": "33554432",
                "NVFLARE_STREAMING_CHUNK_SIZE": "4194304",
                "NVFLARE_STREAMING_MAX_OUT_SEQ_CHUNKS": "64",
                "NVFLARE_STREAMING_WINDOW_SIZE": "134217728",
            },
            build_streaming_environment(4194304, 134217728, 33554432, 64),
        )


if __name__ == "__main__":
    unittest.main()
