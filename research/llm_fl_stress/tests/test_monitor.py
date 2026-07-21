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

import tempfile
import unittest
from pathlib import Path

from research.llm_fl_stress.harness.monitor import _read_cgroup_root


class CgroupMonitorTest(unittest.TestCase):
    def test_reads_memory_stat_events_and_pressure(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "memory.current").write_text("100\n", encoding="utf-8")
            (root / "memory.peak").write_text("120\n", encoding="utf-8")
            (root / "memory.max").write_text("200\n", encoding="utf-8")
            (root / "memory.high").write_text("180\n", encoding="utf-8")
            (root / "memory.swap.current").write_text("0\n", encoding="utf-8")
            (root / "memory.swap.max").write_text("0\n", encoding="utf-8")
            (root / "memory.events").write_text("low 0\nhigh 3\nmax 2\noom 1\noom_kill 1\n", encoding="utf-8")
            (root / "memory.stat").write_text(
                "anon 80\nfile 10\nkernel 5\nsock 2\nshmem 1\npagetables 3\nslab 4\n",
                encoding="utf-8",
            )
            (root / "memory.pressure").write_text(
                "some avg10=1.00 avg60=0.50 avg300=0.25 total=1234\n"
                "full avg10=0.20 avg60=0.10 avg300=0.05 total=234\n",
                encoding="utf-8",
            )

            snapshot = _read_cgroup_root(root)

            self.assertEqual(80, snapshot["memory_stat_anon_bytes"])
            self.assertEqual(10, snapshot["memory_stat_file_bytes"])
            self.assertEqual(3, snapshot["memory_events_high"])
            self.assertEqual(1, snapshot["memory_events_oom_kill"])
            self.assertEqual(1234, snapshot["pressure_some_total_usec"])
            self.assertEqual(0.2, snapshot["pressure_full_avg10"])


if __name__ == "__main__":
    unittest.main()
