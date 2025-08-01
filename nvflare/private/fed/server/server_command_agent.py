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

from nvflare.apis.fl_constant import ServerCommandKey
from nvflare.apis.shareable import ReservedHeaderKey, Shareable
from nvflare.apis.utils.fl_context_utils import gen_new_peer_ctx
from nvflare.fuel.f3.cellnet.cell import Cell
from nvflare.fuel.f3.cellnet.core_cell import MessageHeaderKey, ReturnCode, make_reply
from nvflare.fuel.f3.message import Message as CellMessage
from nvflare.fuel.utils.log_utils import get_obj_logger
from nvflare.private.defs import CellChannel, CellMessageHeaderKeys, new_cell_message

from .server_commands import ServerCommands


class ServerCommandAgent(object):
    def __init__(self, engine, cell: Cell) -> None:
        """To init the CommandAgent.

        Args:
            listen_port: port to listen the command
        """
        self.logger = get_obj_logger(self)
        self.asked_to_stop = False
        self.engine = engine
        self.cell = cell

    def start(self):
        self.cell.register_request_cb(
            channel=CellChannel.SERVER_COMMAND,
            topic="*",
            cb=self.execute_command,
        )
        self.cell.register_request_cb(
            channel=CellChannel.AUX_COMMUNICATION,
            topic="*",
            cb=self.aux_communicate,
        )
        self.logger.info(f"ServerCommandAgent cell register_request_cb: {self.cell.get_fqcn()}")

    def execute_command(self, request: CellMessage) -> CellMessage:

        if not isinstance(request, CellMessage):
            raise RuntimeError("request must be CellMessage but got {}".format(type(request)))

        command_name = request.get_header(MessageHeaderKey.TOPIC)
        # data = fobs.loads(request.payload)
        data = request.payload

        token = request.get_header(CellMessageHeaderKeys.TOKEN, None)
        # client_name = request.get_header(CellMessageHeaderKeys.CLIENT_NAME, None)
        client = None
        if token:
            client = self._get_client(token)
            if client:
                data.set_header(ServerCommandKey.FL_CLIENT, client)

        command = ServerCommands.get_command(command_name)
        if command:
            if command_name in ServerCommands.client_request_commands_names:
                if not client:
                    return make_reply(
                        ReturnCode.AUTHENTICATION_ERROR,
                        "Request from client: missing client token",
                        None,
                    )

            with self.engine.new_context() as new_fl_ctx:
                if command_name in ServerCommands.client_request_commands_names:
                    state_check = command.get_state_check(new_fl_ctx)
                    error = self.engine.server.authentication_check(request, state_check)
                    if error:
                        return make_reply(ReturnCode.AUTHENTICATION_ERROR, error, None)

                reply = command.process(data=data, fl_ctx=new_fl_ctx)
                if reply is not None:
                    return_message = new_cell_message({}, reply)
                    return_message.set_header(MessageHeaderKey.RETURN_CODE, ReturnCode.OK)

                    if isinstance(reply, Shareable):
                        msg_root_id = reply.get_header(ReservedHeaderKey.MSG_ROOT_ID)
                        msg_root_ttl = reply.get_header(ReservedHeaderKey.MSG_ROOT_TTL)
                        if msg_root_id:
                            return_message.set_header(MessageHeaderKey.MSG_ROOT_ID, msg_root_id)
                        if msg_root_ttl:
                            return_message.set_header(MessageHeaderKey.MSG_ROOT_TTL, msg_root_ttl)
                else:
                    return_message = make_reply(ReturnCode.PROCESS_EXCEPTION, "No process results", None)
                return return_message
        else:
            return make_reply(ReturnCode.INVALID_REQUEST, "No server command found", None)

    def _get_client(self, token):
        fl_server = self.engine.server
        client_manager = fl_server.client_manager
        clients = client_manager.clients
        return clients.get(token)

    def aux_communicate(self, request: CellMessage) -> CellMessage:

        assert isinstance(request, CellMessage), "request must be CellMessage but got {}".format(type(request))
        data = request.payload

        topic = request.get_header(MessageHeaderKey.TOPIC)
        with self.engine.new_context() as fl_ctx:
            server_state = self.engine.server.server_state
            state_check = server_state.aux_communicate(fl_ctx)
            error = self.engine.server.authentication_check(request, state_check)
            if error:
                make_reply(ReturnCode.AUTHENTICATION_ERROR, error, None)

            engine = fl_ctx.get_engine()
            if not engine:
                # I (SJ) cannot process this request because my engine is not set yet.
                # This happens only when a CJ became ready quickly and send runner_sync request to the SJ.
                # I'll simply tell it that my service is not available, and it will retry.
                return make_reply(ReturnCode.SERVICE_UNAVAILABLE)

            reply = engine.dispatch(topic=topic, request=data, fl_ctx=fl_ctx)
            if reply:
                shared_fl_ctx = gen_new_peer_ctx(fl_ctx)
                reply.set_peer_context(shared_fl_ctx)
            return new_cell_message({MessageHeaderKey.RETURN_CODE: ReturnCode.OK}, reply)

    def shutdown(self):
        self.asked_to_stop = True
