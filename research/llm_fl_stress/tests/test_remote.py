import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from research.llm_fl_stress.harness.config import load_scenario
from research.llm_fl_stress.harness.artifacts import RunArtifacts
from research.llm_fl_stress.harness.remote import (
    ArtifactCheckpointWorker,
    ManagedCgroup,
    RemoteHost,
    RemoteTelemetry,
    build_remote_hosts,
)

from test_config import PROJECT_DIR


class RemoteTelemetryTest(unittest.TestCase):
    def test_default_aliases_follow_site_names(self):
        scenario = load_scenario(PROJECT_DIR / "configs" / "smoke.json")

        hosts = build_remote_hosts(scenario, "flare-server")

        self.assertEqual(["server", "site-1", "site-2"], [host.label for host in hosts])
        self.assertEqual(["flare-server", "flare-site-1", "flare-site-2"], [host.ssh_alias for host in hosts])

    def test_explicit_client_aliases_are_validated(self):
        scenario = load_scenario(PROJECT_DIR / "configs" / "smoke.json")

        with self.assertRaisesRegex(ValueError, "unknown clients"):
            build_remote_hosts(scenario, "flare-server", ["site-3=other-host"])

    def test_absolute_opt_paths_are_supported(self):
        path = "/opt/nvflare-stress/local-kevlu/source"

        self.assertEqual(path, RemoteTelemetry._validate_remote_path(path, "source root"))
        self.assertEqual(path, RemoteTelemetry._shell_path(path))

    def test_remote_path_traversal_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsafe source root"):
            RemoteTelemetry._validate_remote_path("/opt/nvflare/../other", "source root")

    def test_managed_memory_events_include_unexpected_oom_hosts(self):
        telemetry = RemoteTelemetry.__new__(RemoteTelemetry)
        telemetry.hosts = [RemoteHost("server", "flare-server", "server", "server_train")]
        telemetry.expected_oom_hosts = set()
        telemetry._managed_cgroups = {
            "server": ManagedCgroup("server", "/sys/fs/cgroup/test", "/sys/fs/cgroup/original", 123, 55, 55)
        }

        with patch.object(telemetry, "_ssh", return_value="high 0\nmax 4\noom 1\noom_kill 3\n"):
            observed = telemetry.managed_memory_events()

        self.assertEqual(3, observed["server"]["oom_kill"])

    def test_service_environment_reports_mismatch(self):
        telemetry = RemoteTelemetry.__new__(RemoteTelemetry)
        telemetry.hosts = [RemoteHost("server", "flare-server", "server", "server_train")]

        with patch.object(telemetry, "_service_pid", return_value=123), patch.object(
            telemetry,
            "_ssh",
            return_value="NVFLARE_STREAMING_CHUNK_SIZE=1048576\n",
        ):
            result = telemetry.check_service_environment({"NVFLARE_STREAMING_CHUNK_SIZE": "4194304"})

        self.assertFalse(result["passed"])
        self.assertEqual("1048576", result["mismatches"][0]["observed"])

    def test_absolute_memory_high_does_not_lower_memory_max(self):
        telemetry = RemoteTelemetry.__new__(RemoteTelemetry)
        telemetry.run_id = "test-run"
        telemetry.memory_max_by_host = {}
        telemetry.memory_high_by_host = {"server": 320 * 1024**3}
        telemetry.memory_high_ratio = 0.9
        telemetry._managed_cgroups = {}
        host = RemoteHost("server", "flare-server", "server", "server_train")

        with patch.object(telemetry, "_ssh", side_effect=["0::/system.slice/flare.service", ""]) as ssh:
            managed = telemetry._configure_cgroup(host, 123)

        configure_command = ssh.call_args_list[1].args[1]
        self.assertIn("/memory.high", configure_command)
        self.assertNotIn("/memory.max", configure_command)
        self.assertIsNone(managed.memory_max_bytes)
        self.assertEqual(320 * 1024**3, managed.memory_high_bytes)

    def test_checkpoint_worker_records_recovery_result(self):
        class FakeTelemetry:
            @staticmethod
            def checkpoint_collect(_artifacts):
                return ["site-2 unavailable"]

        scenario = load_scenario(PROJECT_DIR / "configs" / "smoke.json")
        with TemporaryDirectory() as temporary_directory:
            artifacts = RunArtifacts.create(
                output_root=Path(temporary_directory),
                scenario=scenario,
                source_scenario_path=PROJECT_DIR / "configs" / "smoke.json",
                repo_root=PROJECT_DIR.parents[1],
                command=["test"],
            )
            worker = ArtifactCheckpointWorker(FakeTelemetry(), artifacts, interval_seconds=0)

            worker._record_checkpoint("test")

            self.assertEqual("test", worker.records[0]["reason"])
            self.assertEqual(["site-2 unavailable"], worker.records[0]["errors"])


if __name__ == "__main__":
    unittest.main()
