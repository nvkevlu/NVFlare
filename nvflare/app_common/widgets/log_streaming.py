# Copyright (c) 2024, NVIDIA CORPORATION.  All rights reserved.
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

import os
import threading
from builtins import dict as StreamContext

from nvflare.apis.event_type import EventType
from nvflare.apis.fl_constant import FLContextKey, ProcessType, ReturnCode, SystemComponents
from nvflare.apis.fl_context import FLContext
from nvflare.apis.workspace import Workspace
from nvflare.app_common.streamers.file_streamer import FileStreamer
from nvflare.widgets.widget import Widget

LOG_STREAM_EVENT_TYPE = "stream_log"


class LogConst(object):
    CLIENT_NAME = "client_name"
    JOB_ID = "job_id"


class LogChannels(object):
    ERROR_LOGS_CHANNEL = "log_streaming.error_logs"
    ERROR_LOG_LOG_TYPE = "ERRORLOG"


class LogSender(Widget):
    def __init__(self, event_type=EventType.JOB_COMPLETED, should_report_error_log: bool = True):
        """Sender for analytics data."""
        super().__init__()
        self.event_type = event_type
        self.should_report_error_log = should_report_error_log

    def _stream_log_file(self, fl_ctx: FLContext, log_path: str, channel: str):
        if os.path.exists(log_path):
            FileStreamer.stream_file(
                channel=channel,
                topic=LOG_STREAM_EVENT_TYPE,
                stream_ctx={
                    LogConst.CLIENT_NAME: fl_ctx.get_prop(FLContextKey.CLIENT_NAME),
                    LogConst.JOB_ID: fl_ctx.get_prop(FLContextKey.CURRENT_JOB_ID),
                },
                targets=["server"],
                file_name=log_path,
                fl_ctx=fl_ctx,
            )

    def handle_event(self, event_type: str, fl_ctx: FLContext):
        if event_type == self.event_type:
            if fl_ctx.get_process_type() == ProcessType.CLIENT_PARENT:
                if self.should_report_error_log:
                    workspace_root = fl_ctx.get_prop(FLContextKey.WORKSPACE_ROOT)
                    client_name = fl_ctx.get_prop(FLContextKey.CLIENT_NAME)
                    job_id = fl_ctx.get_prop(FLContextKey.CURRENT_JOB_ID)
                    workspace_object = Workspace(root_dir=workspace_root, site_name=client_name)
                    error_log_path = workspace_object.get_app_error_log_file_path(job_id=job_id)

                    if os.path.exists(error_log_path):
                        t = threading.Thread(
                            target=self._stream_log_file,
                            args=(fl_ctx, error_log_path, LogChannels.ERROR_LOGS_CHANNEL),
                            daemon=True,
                        )
                        t.start()
                        self.log_info(fl_ctx, f"Started streaming error log file for {client_name} for job {job_id}")
                    else:
                        self.log_info(fl_ctx, f"No error log file found for {client_name} for job {job_id}")


class LogReceiver(Widget):
    def __init__(self, log_channels=None):
        """Receives log data.

        By default, it receives error logs with the channel log_streaming.error_logs to save logs of type ERRORLOG. If adding
        additional log types, make sure nvflare.apis.storage.ComponentPrefixes has the corresponding log type.

        Args:
            log_channels: dict of channel to log type mapping
        """
        super().__init__()
        if log_channels is None:
            log_channels = {LogChannels.ERROR_LOGS_CHANNEL: LogChannels.ERROR_LOG_LOG_TYPE}
        if not isinstance(log_channels, dict):
            raise ValueError("log_channels should be a dict of channel name to log type mapping")
        self.log_channels = log_channels

    def process_log(self, stream_ctx: StreamContext, fl_ctx: FLContext):
        """Process the streamed log file."""
        peer_ctx = fl_ctx.get_peer_context()
        assert isinstance(peer_ctx, FLContext)
        peer_name = peer_ctx.get_identity_name()
        channel = FileStreamer.get_channel(stream_ctx)
        topic = FileStreamer.get_topic(stream_ctx)
        rc = FileStreamer.get_rc(stream_ctx)
        if rc != ReturnCode.OK:
            self.log_error(
                fl_ctx,
                f"Error in streaming log file from {peer_name} on channel {channel} and topic {topic} with rc {rc}",
            )
            return
        file_location = FileStreamer.get_file_location(stream_ctx)
        client = stream_ctx.get(LogConst.CLIENT_NAME)
        job_id = stream_ctx.get(LogConst.JOB_ID)
        job_manager = fl_ctx.get_engine().get_component(SystemComponents.JOB_MANAGER)
        log_type = self.log_channels.get(channel, "UNKNOWN")
        if log_type == "UNKNOWN":
            self.log_error(fl_ctx, f"Unknown log type for channel {channel}")
        else:
            self.log_info(fl_ctx, f"Saving {log_type} from {client} for {job_id}")
            job_manager.set_client_data(job_id, file_location, client, log_type, fl_ctx)

    def handle_event(self, event_type: str, fl_ctx: FLContext):
        if event_type == EventType.SYSTEM_START:
            for channel, log_type in self.log_channels.items():
                FileStreamer.register_stream_processing(
                    fl_ctx, channel=channel, topic="*", stream_done_cb=self.process_log
                )
