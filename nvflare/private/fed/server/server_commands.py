# Copyright (c) 2022, NVIDIA CORPORATION.  All rights reserved.
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

"""FL Admin commands."""

import time
from abc import ABC, abstractmethod
from typing import List

from nvflare.apis.fl_constant import (
    AdminCommandNames,
    FLContextKey,
    MachineStatus,
    ReturnCode,
    ServerCommandKey,
    ServerCommandNames,
)
from nvflare.apis.fl_context import FLContext
from nvflare.apis.shareable import Shareable, make_reply
from nvflare.apis.utils.fl_context_utils import gen_new_peer_ctx
from nvflare.fuel.utils.log_utils import dynamic_log_config, get_obj_logger
from nvflare.private.defs import SpecialTaskName, TaskConstant
from nvflare.security.logging import secure_format_exception, secure_format_traceback
from nvflare.widgets.widget import WidgetID

NO_OP_REPLY = "__no_op_reply"


class CommandProcessor(ABC):
    """The CommandProcessor is responsible for processing a command from parent process."""

    def __init__(self) -> None:
        self.logger = get_obj_logger(self)

    @abstractmethod
    def get_command_name(self) -> str:
        """Gets the command name that this processor will handle.

        Returns:
            name of the command
        """
        pass

    @abstractmethod
    def process(self, data: Shareable, fl_ctx: FLContext):
        """Processes the data.

        Args:
            data: process data
            fl_ctx: FLContext

        Return:
            A reply message
        """
        pass


class ServerStateCheck(ABC):
    """Server command requires the server state check"""

    @abstractmethod
    def get_state_check(self, fl_ctx: FLContext) -> dict:
        """Get the state check data for the server command.

        Args:
            fl_ctx: FLContext

        Returns: server state check dict data

        """
        pass


class AbortCommand(CommandProcessor):
    """To implement the abort command."""

    def get_command_name(self) -> str:
        """To get the command name.

        Returns: AdminCommandNames.ABORT

        """
        return AdminCommandNames.ABORT

    def process(self, data: Shareable, fl_ctx: FLContext):
        """Called to process the abort command.

        Args:
            data: process data
            fl_ctx: FLContext

        Returns: abort command message

        """
        server_runner = fl_ctx.get_prop(FLContextKey.RUNNER)
        # for HA server switch over
        turn_to_cold = data.get_header(ServerCommandKey.TURN_TO_COLD, False)
        if server_runner:
            server_runner.abort(fl_ctx=fl_ctx, turn_to_cold=turn_to_cold)
            # wait for the runner process gracefully abort the run.
            engine = fl_ctx.get_engine()
            start_time = time.time()
            while engine.engine_info.status != MachineStatus.STOPPED:
                time.sleep(1.0)
                if time.time() - start_time > 30.0:
                    break
        return "Aborted the run"


class GetRunInfoCommand(CommandProcessor):
    """Implements the GET_RUN_INFO command."""

    def get_command_name(self) -> str:
        return ServerCommandNames.GET_RUN_INFO

    def process(self, data: Shareable, fl_ctx: FLContext):
        engine = fl_ctx.get_engine()
        run_info = engine.get_run_info()
        if run_info:
            return run_info
        return NO_OP_REPLY


class GetTaskCommand(CommandProcessor, ServerStateCheck):
    """To implement the server GetTask command."""

    def get_command_name(self) -> str:
        """To get the command name.

        Returns: ServerCommandNames.GET_TASK

        """
        return ServerCommandNames.GET_TASK

    def process(self, data: Shareable, fl_ctx: FLContext):
        """Called to process the GetTask command.

        Args:
            data: process data
            fl_ctx: FLContext

        Returns: task data

        """

        start_time = time.time()
        shared_fl_ctx = data.get_peer_context()
        data.set_peer_context(FLContext())
        client = data.get_header(ServerCommandKey.FL_CLIENT)
        self.logger.debug(f"Got the GET_TASK request from client: {client.name}")
        fl_ctx.set_peer_context(shared_fl_ctx)
        server_runner = fl_ctx.get_prop(FLContextKey.RUNNER)
        if not server_runner:
            # this is possible only when the client request is received before the
            # server_app_runner.start_server_app is called in runner_process.py
            # We ask the client to try again later.
            taskname = SpecialTaskName.TRY_AGAIN
            task_id = ""
            shareable = Shareable()
            shareable.set_header(TaskConstant.WAIT_TIME, 1.0)
        else:
            taskname, task_id, shareable = server_runner.process_task_request(client, fl_ctx)

        # we need TASK_ID back as a cookie
        if not shareable:
            shareable = Shareable()
        shareable.add_cookie(name=FLContextKey.TASK_ID, data=task_id)

        # we also need to make TASK_ID available to the client
        shareable.set_header(key=FLContextKey.TASK_ID, value=task_id)

        shareable.set_header(key=ServerCommandKey.TASK_NAME, value=taskname)

        shared_fl_ctx = gen_new_peer_ctx(fl_ctx)
        shareable.set_peer_context(shared_fl_ctx)

        if taskname != SpecialTaskName.TRY_AGAIN:
            self.logger.info(
                f"return task to client.  client_name: {client.name}  task_name: {taskname}   task_id: {task_id}  "
                f"sharable_header_task_id: {shareable.get_header(key=FLContextKey.TASK_ID)}"
            )
        self.logger.debug(f"Get_task processing time: {time.time() - start_time} for client: {client.name}")
        return shareable

    def get_state_check(self, fl_ctx: FLContext) -> dict:
        engine = fl_ctx.get_engine()
        server_state = engine.server.server_state
        return server_state.get_task(fl_ctx)


class SubmitUpdateCommand(CommandProcessor, ServerStateCheck):
    """To implement the server GetTask command."""

    def get_command_name(self) -> str:
        """To get the command name.

        Returns: ServerCommandNames.SUBMIT_UPDATE

        """
        return ServerCommandNames.SUBMIT_UPDATE

    def process(self, data: Shareable, fl_ctx: FLContext):
        """Called to process the abort command.

        Args:
            data: process data
            fl_ctx: FLContext

        Returns:

        """

        start_time = time.time()
        shared_fl_ctx = data.get_peer_context()
        data.set_peer_context(FLContext())
        shared_fl_ctx.set_prop(FLContextKey.SHAREABLE, data, private=True)

        client = data.get_header(ServerCommandKey.FL_CLIENT)
        fl_ctx.set_peer_context(shared_fl_ctx)
        contribution_task_name = data.get_header(FLContextKey.TASK_NAME)
        task_id = data.get_cookie(FLContextKey.TASK_ID)
        server_runner = fl_ctx.get_prop(FLContextKey.RUNNER)
        server_runner.process_submission(client, contribution_task_name, task_id, data, fl_ctx)
        self.logger.info(f"submit_update process. client_name:{client.name}   task_id:{task_id}")

        self.logger.debug(f"Submit_result processing time: {time.time() - start_time} for client: {client.name}")
        return ""

    def get_state_check(self, fl_ctx: FLContext) -> dict:
        engine = fl_ctx.get_engine()
        server_state = engine.server.server_state
        return server_state.submit_result(fl_ctx)


class HandleDeadJobCommand(CommandProcessor):
    """To implement the server HandleDeadJob command."""

    def get_command_name(self) -> str:
        """To get the command name.

        Returns: ServerCommandNames.SUBMIT_UPDATE

        """
        return ServerCommandNames.HANDLE_DEAD_JOB

    def process(self, data: Shareable, fl_ctx: FLContext):
        """Called to process the HandleDeadJob command.

        Args:
            data: process data
            fl_ctx: FLContext

        Returns:

        """
        client_name = data.get_header(ServerCommandKey.FL_CLIENT)
        reason = data.get_header(ServerCommandKey.REASON)
        self.logger.warning(f"received dead job notification: {reason=}")
        server_runner = fl_ctx.get_prop(FLContextKey.RUNNER)
        if server_runner:
            server_runner.handle_dead_job(client_name, fl_ctx)
        return ""


class ShowStatsCommand(CommandProcessor):
    """To implement the show_stats command."""

    def get_command_name(self) -> str:
        """To get the command name.

        Returns: ServerCommandNames.SHOW_STATS

        """
        return ServerCommandNames.SHOW_STATS

    def process(self, data: Shareable, fl_ctx: FLContext):
        """Called to process the abort command.

        Args:
            data: process data
            fl_ctx: FLContext

        Returns: Engine run_info

        """
        engine = fl_ctx.get_engine()
        collector = engine.get_widget(WidgetID.INFO_COLLECTOR)
        return collector.get_run_stats()


class GetErrorsCommand(CommandProcessor):
    """To implement the show_errors command."""

    def get_command_name(self) -> str:
        """To get the command name.

        Returns: ServerCommandNames.GET_ERRORS

        """
        return ServerCommandNames.GET_ERRORS

    def process(self, data: Shareable, fl_ctx: FLContext):
        """Called to process the abort command.

        Args:
            data: process data
            fl_ctx: FLContext

        Returns: Engine run_info

        """
        engine = fl_ctx.get_engine()
        collector = engine.get_widget(WidgetID.INFO_COLLECTOR)
        errors = collector.get_errors()
        if not errors:
            errors = "No Error"
        return errors


class ResetErrorsCommand(CommandProcessor):
    """To implement the show_errors command."""

    def get_command_name(self) -> str:
        """To get the command name.

        Returns: ServerCommandNames.GET_ERRORS

        """
        return ServerCommandNames.RESET_ERRORS

    def process(self, data: Shareable, fl_ctx: FLContext):
        """Called to process the abort command.

        Args:
            data: process data
            fl_ctx: FLContext

        """
        engine = fl_ctx.get_engine()
        collector = engine.get_widget(WidgetID.INFO_COLLECTOR)
        collector.reset_errors()
        return None


class ByeCommand(CommandProcessor):
    """To implement the ShutdownCommand."""

    def get_command_name(self) -> str:
        """To get the command name.

        Returns: AdminCommandNames.SHUTDOWN

        """
        return AdminCommandNames.SHUTDOWN

    def process(self, data: Shareable, fl_ctx: FLContext):
        """Called to process the Shutdown command.

        Args:
            data: process data
            fl_ctx: FLContext

        Returns: Shutdown command message

        """
        return None


class HeartbeatCommand(CommandProcessor):
    """To implement the HEARTBEATCommand."""

    def get_command_name(self) -> str:
        """To get the command name.

        Returns: AdminCommandNames.HEARTBEAT

        """
        return ServerCommandNames.HEARTBEAT

    def process(self, data: Shareable, fl_ctx: FLContext):
        """Called to process the HEARTBEAT command.

        Args:
            data: process data
            fl_ctx: FLContext

        """
        return None


class ServerStateCommand(CommandProcessor):
    """To implement the ServerStateCommand."""

    def get_command_name(self) -> str:
        """To get the command name.

        Returns: AdminCommandNames.SERVER_STATE

        """
        return ServerCommandNames.SERVER_STATE

    def process(self, data: Shareable, fl_ctx: FLContext):
        """Called to process the SERVER_STATE command.

        Args:
            data: ServerState object
            fl_ctx: FLContext

        """
        engine = fl_ctx.get_engine()
        engine.server.server_state = data
        return "Success"


class ConfigureJobLogCommand(CommandProcessor):
    """To implement the configure_job_log command."""

    def get_command_name(self) -> str:
        """To get the command name.

        Returns: AdminCommandNames.CONFIGURE_JOB_LOG

        """
        return AdminCommandNames.CONFIGURE_JOB_LOG

    def process(self, data: Shareable, fl_ctx: FLContext):
        """Called to process the configure_job_log command.

        Args:
            data: process data
            fl_ctx: FLContext

        """
        engine = fl_ctx.get_engine()
        workspace = engine.get_workspace()
        try:
            dynamic_log_config(
                config=data,
                dir_path=workspace.get_run_dir(fl_ctx.get_job_id()),
                reload_path=workspace.get_log_config_file_path(),
            )
        except Exception as e:
            return secure_format_exception(e)


class AppCommandProcessor(CommandProcessor):
    def get_command_name(self) -> str:
        """To get the command name.

        Returns: AdminCommandNames.SERVER_STATE

        """
        return ServerCommandNames.APP_COMMAND

    def process(self, data: Shareable, fl_ctx: FLContext):
        topic = data.get(ServerCommandKey.TOPIC)
        if not topic:
            return make_reply(ReturnCode.BAD_REQUEST_DATA, headers={ServerCommandKey.REASON: "no topic"})

        reg = ServerCommands.get_app_command(topic)
        if reg is None:
            self.logger.error(f"no app command func for topic {topic}")
            return make_reply(
                ReturnCode.BAD_REQUEST_DATA, headers={ServerCommandKey.REASON: f"no app command func for topic {topic}"}
            )

        cmd_func, cmd_args, cmd_kwargs = reg
        cmd_data = data.get(ServerCommandKey.DATA)
        try:
            result = cmd_func(topic, cmd_data, fl_ctx, *cmd_args, **cmd_kwargs)
        except Exception as ex:
            self.logger.error(f"exception processing app command '{topic}': {secure_format_traceback()}")
            return make_reply(
                ReturnCode.EXECUTION_EXCEPTION, headers={ServerCommandKey.REASON: {secure_format_exception(ex)}}
            )

        if not isinstance(result, dict):
            self.logger.error(f"bad result from app command '{topic}': expect dict but got {type(result)}")
            return make_reply(
                ReturnCode.EXECUTION_EXCEPTION, headers={ServerCommandKey.REASON: f"bad result type {type(result)}"}
            )

        reply = Shareable()
        reply[ServerCommandKey.DATA] = result
        return reply


class ServerCommands(object):
    """AdminCommands contains all the commands for processing the commands from the parent process."""

    commands: List[CommandProcessor] = [
        AbortCommand(),
        ByeCommand(),
        GetRunInfoCommand(),
        GetTaskCommand(),
        SubmitUpdateCommand(),
        HandleDeadJobCommand(),
        ShowStatsCommand(),
        GetErrorsCommand(),
        ResetErrorsCommand(),
        HeartbeatCommand(),
        ServerStateCommand(),
        ConfigureJobLogCommand(),
        AppCommandProcessor(),
    ]

    client_request_commands_names = [
        ServerCommandNames.GET_TASK,
        ServerCommandNames.SUBMIT_UPDATE,
    ]

    app_cmd_registry = {}

    @classmethod
    def get_command(cls, command_name):
        """Call to return the AdminCommand object.

        Args:
            command_name: AdminCommand name

        Returns: AdminCommand object

        """
        for command in cls.commands:
            if command_name == command.get_command_name():
                return command
        return None

    @classmethod
    def register_app_command(cls, topic: str, cmd_func, *args, **kwargs):
        """Called to register an app command.

        Args:
            topic: topic that the command will process
            cmd_func: the function to process the command
        """
        if not isinstance(topic, str):
            raise RuntimeError(f"invalid topic: expect str but got {type(topic)}")

        if not callable(cmd_func):
            raise RuntimeError(f"command func is not callable for topic {topic}")

        if topic in cls.app_cmd_registry:
            raise RuntimeError(f"duplicate app command topic {topic}")

        cls.app_cmd_registry[topic] = (cmd_func, args, kwargs)

    @classmethod
    def get_app_command(cls, topic: str):
        reg = cls.app_cmd_registry.get(topic)
        if reg is not None:
            return reg

        # see whether a default func is registered
        return cls.app_cmd_registry.get("*")
