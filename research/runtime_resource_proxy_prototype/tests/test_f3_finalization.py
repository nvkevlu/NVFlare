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

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from f3_finalization import (  # noqa: E402
    F3FinalizationCounter,
    INCLUDED_JOB_TRAFFIC_CLASSES,
    JobTrafficClass,
    JobTrafficEvent,
)


class TestF3FinalizationCounter(unittest.TestCase):
    def test_explicit_allowlist_excludes_non_job_traffic(self):
        counter = F3FinalizationCounter()

        counter.send_remote(JobTrafficEvent(JobTrafficClass.TASK_REQUEST, 128), lambda: None)
        counter.send_remote(JobTrafficEvent(JobTrafficClass.WORKSPACE_TRANSFER, 64), lambda: None)
        counter.send_remote(JobTrafficEvent(JobTrafficClass.BULK_ENVELOPE, 32), lambda: None)

        snapshot = counter.snapshot()
        self.assertEqual(
            {
                JobTrafficClass.TASK_REQUEST,
                JobTrafficClass.TASK_RESPONSE,
                JobTrafficClass.TASK_RESULT,
                JobTrafficClass.JOB_APPLICATION,
                JobTrafficClass.JOB_STREAM_DATA,
            },
            INCLUDED_JOB_TRAFFIC_CLASSES,
        )
        self.assertEqual({"payload_bytes": 128, "message_count": 1}, snapshot["outcomes"]["remote_transport_accepted"])
        self.assertEqual({"payload_bytes": 96, "message_count": 2}, snapshot["diagnostics"]["excluded_traffic_class"])

    def test_remote_bytes_are_recorded_only_after_transport_accepts(self):
        counter = F3FinalizationCounter()
        event = JobTrafficEvent(JobTrafficClass.TASK_RESULT, 256)

        def reject_transport():
            raise RuntimeError("transport rejected the message")

        with self.assertRaisesRegex(RuntimeError, "rejected"):
            counter.send_remote(event, reject_transport)

        rejected = counter.snapshot()
        self.assertEqual({"payload_bytes": 0, "message_count": 0}, rejected["outcomes"]["remote_transport_accepted"])
        self.assertEqual(
            {"attempted_payload_bytes": 256, "attempted_message_count": 1},
            rejected["diagnostics"]["before_transport_acceptance_failed"],
        )

        self.assertEqual("accepted", counter.send_remote(event, lambda: "accepted"))
        accepted = counter.snapshot()
        self.assertEqual({"payload_bytes": 256, "message_count": 1}, accepted["outcomes"]["remote_transport_accepted"])

    def test_direct_delivery_is_not_added_to_remote_transport(self):
        counter = F3FinalizationCounter()
        event = JobTrafficEvent(JobTrafficClass.JOB_APPLICATION, 48, message_count=2)

        counter.deliver_direct(event, lambda: None)
        snapshot = counter.snapshot()

        self.assertEqual({"payload_bytes": 0, "message_count": 0}, snapshot["outcomes"]["remote_transport_accepted"])
        self.assertEqual({"payload_bytes": 48, "message_count": 2}, snapshot["outcomes"]["local_delivery"])

    def test_summary_publication_uses_an_opaque_platform_capability(self):
        counter = F3FinalizationCounter()
        summary_event = JobTrafficEvent(JobTrafficClass.JOB_APPLICATION, 512)

        # The event has the same included class as regular application traffic.
        # It is excluded only because the platform-owned publisher carries the
        # counter's opaque in-process capability.
        counter.summary_publisher().send_remote(summary_event, lambda: None)
        counter.send_remote(JobTrafficEvent(JobTrafficClass.JOB_APPLICATION, 128), lambda: None)
        snapshot = counter.snapshot()

        self.assertEqual({"payload_bytes": 128, "message_count": 1}, snapshot["outcomes"]["remote_transport_accepted"])
        self.assertEqual(
            {"payload_bytes": 512, "message_count": 1},
            snapshot["diagnostics"]["excluded_summary_publication"],
        )

    def test_frozen_cutoff_is_fixed_and_late_events_are_diagnostic_only(self):
        counter = F3FinalizationCounter()
        counter.send_remote(JobTrafficEvent(JobTrafficClass.TASK_REQUEST, 100), lambda: None)

        frozen = counter.freeze()
        self.assertEqual("frozen", frozen["finalization"]["state"])
        self.assertEqual(1, frozen["finalization"]["accepted_event_sequence_cutoff"])

        counter.send_remote(JobTrafficEvent(JobTrafficClass.TASK_RESULT, 25), lambda: None)
        counter.deliver_direct(JobTrafficEvent(JobTrafficClass.JOB_APPLICATION, 75), lambda: None)
        again = counter.freeze()

        self.assertEqual(1, again["finalization"]["accepted_event_sequence_cutoff"])
        self.assertEqual({"payload_bytes": 100, "message_count": 1}, again["outcomes"]["remote_transport_accepted"])
        self.assertEqual({"payload_bytes": 0, "message_count": 0}, again["outcomes"]["local_delivery"])
        self.assertEqual({"payload_bytes": 100, "message_count": 2}, again["diagnostics"]["late_after_cutoff"])


if __name__ == "__main__":
    unittest.main()
