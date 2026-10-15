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

from typing import Callable, Optional

from nvflare.fuel.f3.streaming.shutdown import shutdown_f3_streaming
from nvflare.private.fed.utils.fed_utils import security_close
from nvflare.security.logging import secure_format_exception

_COMMAND_CALLBACK_DRAIN_TIMEOUT = 5.0


def shutdown_job_process_runtime(
    stop_command_admission: Optional[Callable[[], None]],
    wait_for_command_callbacks: Optional[Callable[[float], bool]],
    stop_cell: Optional[Callable[[], None]],
    logger,
    before_streaming_shutdown: Optional[Callable[[], None]] = None,
    mark_callback_drain_incomplete: Optional[Callable[[], None]] = None,
) -> None:
    """Drain job-process communication before closing process security state."""

    def _run_stage(name: str, action: Optional[Callable[[], None]]) -> None:
        if action is None:
            return
        try:
            action()
        except Exception as e:
            if logger:
                logger.warning(f"failed to stop {name}: {secure_format_exception(e)}")

    def _wait_for_callbacks(*, before_publication: bool) -> bool:
        try:
            drained = wait_for_command_callbacks(_COMMAND_CALLBACK_DRAIN_TIMEOUT)
            if not drained and logger:
                suffix = " before resource-statistics publication" if before_publication else ""
                logger.warning(
                    f"timed out after {_COMMAND_CALLBACK_DRAIN_TIMEOUT} seconds waiting for command callbacks{suffix}"
                )
            return drained
        except Exception as e:
            if logger:
                suffix = " before resource-statistics publication" if before_publication else ""
                logger.warning(f"failed to drain command callbacks{suffix}: {secure_format_exception(e)}")
            return False

    # Reject new app commands, then let every callback already admitted through
    # that gate finish while Cell and F3 streaming are still usable. Otherwise
    # one of those callbacks could originate traffic after the F3 snapshot was
    # frozen. A failed bounded drain makes the snapshot explicitly partial.
    _run_stage("command admission", stop_command_admission)
    callbacks_drained = True
    if wait_for_command_callbacks:
        callbacks_drained = _wait_for_callbacks(before_publication=True)
        if not callbacks_drained:
            _run_stage("F3 callback completeness", mark_callback_drain_incomplete)

    # Publication uses the process-global F3 pools, so it must complete before
    # those pools are irreversibly stopped. Teardown still runs if publication
    # raises, and the original publication error remains visible to the caller.
    try:
        if before_streaming_shutdown:
            before_streaming_shutdown()
    finally:
        # Stop transport so any callback blocked on Cell communication wakes.
        # If the live-transport drain did not finish, retain the existing
        # bounded post-stop wait before closing audit/security state.
        _run_stage("F3 streaming", shutdown_f3_streaming)
        _run_stage("Cell", stop_cell)
        if wait_for_command_callbacks and not callbacks_drained:
            _wait_for_callbacks(before_publication=False)
        _run_stage("security services", security_close)
