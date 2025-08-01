# Copyright (c) 2021, NVIDIA CORPORATION.  All rights reserved.
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
import shutil
import threading
import time
from abc import ABC, abstractmethod
from threading import Lock
from typing import Dict, List, Optional

from nvflare.apis.client import Client
from nvflare.apis.event_type import EventType
from nvflare.apis.fl_component import FLComponent
from nvflare.apis.fl_constant import (
    ConfigVarName,
    ConnPropKey,
    FLContextKey,
    MachineStatus,
    RunProcessKey,
    SecureTrainConst,
    ServerCommandKey,
    ServerCommandNames,
    SiteType,
    SnapshotKey,
    SystemComponents,
    SystemConfigs,
)
from nvflare.apis.fl_context import FLContext
from nvflare.apis.fl_exception import NotAuthenticated
from nvflare.apis.job_def import JobMetaKey, RunStatus
from nvflare.apis.shareable import Shareable
from nvflare.apis.workspace import Workspace
from nvflare.fuel.common.exit_codes import ProcessExitCode
from nvflare.fuel.f3.cellnet.cell import Cell
from nvflare.fuel.f3.cellnet.core_cell import Message
from nvflare.fuel.f3.cellnet.core_cell import make_reply as make_cellnet_reply
from nvflare.fuel.f3.cellnet.defs import IdentityChallengeKey, MessageHeaderKey
from nvflare.fuel.f3.cellnet.defs import ReturnCode as F3ReturnCode
from nvflare.fuel.f3.cellnet.fqcn import FQCN
from nvflare.fuel.f3.cellnet.net_agent import NetAgent
from nvflare.fuel.f3.drivers.driver_params import DriverParams
from nvflare.fuel.f3.mpm import MainProcessMonitor as mpm
from nvflare.fuel.sec.authn import add_authentication_headers
from nvflare.fuel.utils.argument_utils import parse_vars
from nvflare.fuel.utils.config_service import ConfigService
from nvflare.fuel.utils.log_utils import get_obj_logger
from nvflare.fuel.utils.zip_utils import unzip_all_from_bytes
from nvflare.ha.overseer_agent import HttpOverseerAgent
from nvflare.private.defs import (
    CellChannel,
    CellChannelTopic,
    CellMessageHeaderKeys,
    ClientRegSession,
    ClientType,
    InternalFLContextKey,
    JobFailureMsgKey,
    new_cell_message,
)
from nvflare.private.fed.authenticator import validate_auth_headers
from nvflare.private.fed.server.cred_keeper import CredKeeper
from nvflare.private.fed.server.server_command_agent import ServerCommandAgent
from nvflare.private.fed.server.server_runner import ServerRunner
from nvflare.private.fed.utils.identity_utils import TokenVerifier
from nvflare.security.logging import secure_format_exception
from nvflare.widgets.fed_event import ServerFedEventRunner

from .client_manager import ClientManager
from .run_manager import RunManager
from .server_engine import ServerEngine
from .server_state import (
    ABORT_RUN,
    ACTION,
    MESSAGE,
    NIS,
    Cold2HotState,
    ColdState,
    Hot2ColdState,
    HotState,
    ServerState,
)
from .server_status import ServerStatus


class BaseServer(ABC):
    def __init__(
        self,
        project_name=None,
        min_num_clients=2,
        max_num_clients=10,
        heart_beat_timeout=600,
        handlers: Optional[List[FLComponent]] = None,
        shutdown_period=30.0,
    ):
        """Base server that provides the clients management and server deployment."""
        self.project_name = project_name
        self.min_num_clients = max(min_num_clients, 1)
        self.max_num_clients = max(max_num_clients, 1)

        self.heart_beat_timeout = heart_beat_timeout
        self.handlers = handlers

        self.client_manager = ClientManager(
            project_name=self.project_name, min_num_clients=self.min_num_clients, max_num_clients=self.max_num_clients
        )

        self.cell = None
        self.admin_server = None
        self.lock = Lock()
        self.snapshot_lock = Lock()
        self.fl_ctx = FLContext()
        self.platform = None
        self.shutdown_period = shutdown_period

        self.shutdown = False
        self.status = ServerStatus.NOT_STARTED

        self.abort_signal = None
        self.executor = None

        self.logger = get_obj_logger(self)

    def get_all_clients(self) -> Dict[str, Client]:
        """Get the list of registered clients.

        Returns:
            A dict of {client_token: client}
        """
        return self.client_manager.get_clients()

    def get_cell(self):
        return self.cell

    @abstractmethod
    def remove_client_data(self, token):
        pass

    def close(self):
        """Shutdown the server."""
        try:
            if self.lock:
                self.lock.release()
        except RuntimeError:
            self.logger.info("canceling sync locks")
        self.logger.info("server off")
        return 0

    def deploy(self, args, grpc_args=None, secure_train=False):
        """Start a grpc server and listening the designated port."""
        target = grpc_args["service"].get("target", "0.0.0.0:6007")
        scheme = grpc_args["service"].get("scheme", "grpc")

        if secure_train:
            root_cert = grpc_args[SecureTrainConst.SSL_ROOT_CERT]
            ssl_cert = grpc_args[SecureTrainConst.SSL_CERT]
            private_key = grpc_args[SecureTrainConst.PRIVATE_KEY]

            credentials = {
                DriverParams.CA_CERT.value: root_cert,
                DriverParams.SERVER_CERT.value: ssl_cert,
                DriverParams.SERVER_KEY.value: private_key,
            }

            conn_security = grpc_args.get(ConnPropKey.CONNECTION_SECURITY)
            if conn_security:
                credentials[DriverParams.CONNECTION_SECURITY.value] = conn_security
        else:
            credentials = {}
        parent_url = None

        parts = target.split(":")
        if len(parts) != 2:
            raise RuntimeError(f"bad service target: {target}")

        fl_port = int(parts[1])

        # get admin port
        admin_port = int(grpc_args.get("admin_port", fl_port))

        root_url = [f"{scheme}://0:{fl_port}"]
        if admin_port != fl_port:
            root_url.append(f"{scheme}://0:{admin_port}")

        my_fqcn = FQCN.ROOT_SERVER
        self.cell = Cell(
            fqcn=my_fqcn,
            root_url=root_url,
            secure=secure_train,
            credentials=credentials,
            create_internal_listener=True,
            parent_url=parent_url,
        )

        self.cell.start()
        mpm.add_cleanup_cb(self.cell.stop)

        # return self.start()
        cleanup_thread = threading.Thread(target=self.client_cleanup)
        # heartbeat_thread.daemon = True
        cleanup_thread.start()

    def client_cleanup(self):
        last_remove_time = 0.0
        remove_interval = 5.0
        check_interval = 0.2
        while not self.shutdown:
            now = time.time()
            if now - last_remove_time > remove_interval:
                self.remove_dead_clients()
                last_remove_time = now

            # We want to sleep very little to check the self.shutdown quickly
            # so that when self.shutdown is set we can return quickly.
            # Without this, when the server parent cell ends, this thread will not end until 15 secs later.
            # This will cause MPM's cleanup to fail!
            time.sleep(check_interval)

    def set_admin_server(self, admin_server):
        self.admin_server = admin_server

    def remove_dead_clients(self):
        # Clean and remove the dead client without heartbeat.
        self.logger.debug("trying to remove dead clients .......")
        delete = []
        for token, client in self.client_manager.get_clients().items():
            if client.last_connect_time < time.time() - self.heart_beat_timeout:
                delete.append(token)
        for token in delete:
            client = self.logout_client(token)
            self.logger.info(
                "Remove the dead Client. Name: {}\t Token: {}.  Total clients: {}".format(
                    client.name, token, len(self.client_manager.get_clients())
                )
            )

    def logout_client(self, token):
        client = self.client_manager.remove_client(token)
        self.remove_client_data(token)
        if self.admin_server:
            self.admin_server.client_dead(token)
        self.notify_dead_client(client)
        return client

    def notify_dead_client(self, client):
        """Called to do further processing of the dead client

        Args:
            client: the dead client

        Returns:

        """
        pass

    def fl_shutdown(self):
        self.shutdown = True
        start = time.time()
        while self.client_manager.clients:
            # Wait for the clients to shut down and quite first.
            time.sleep(0.1)
            if time.time() - start > self.shutdown_period:
                self.logger.info("There are still clients connected. But shutdown the server after timeout.")
                break
        self.close()
        if self.executor:
            self.executor.shutdown()


class FederatedServer(BaseServer):
    def __init__(
        self,
        project_name=None,
        min_num_clients=2,
        max_num_clients=10,
        cmd_modules=None,
        heart_beat_timeout=600,
        handlers: Optional[List[FLComponent]] = None,
        args=None,
        secure_train=False,
        snapshot_persistor=None,
        overseer_agent=None,
        shutdown_period=30.0,
        check_engine_frequency=3.0,
    ):
        """Federated server services.

        Args:
            project_name: server project name.
            min_num_clients: minimum number of contributors at each round.
            max_num_clients: maximum number of contributors at each round.
            cmd_modules: command modules.
            heart_beat_timeout: heartbeat timeout
            handlers: A list of handler
            args: arguments
            secure_train: whether to use secure communication
        """
        BaseServer.__init__(
            self,
            project_name=project_name,
            min_num_clients=min_num_clients,
            max_num_clients=max_num_clients,
            heart_beat_timeout=heart_beat_timeout,
            handlers=handlers,
            shutdown_period=shutdown_period,
        )

        self.contributed_clients = {}
        self.tokens = None
        self.round_started = time.time()

        with self.lock:
            self.reset_tokens()

        self.cmd_modules = cmd_modules

        self.builder = None

        self.engine = self._create_server_engine(args, snapshot_persistor)
        self.run_manager = None
        self.server_runner = None
        self.command_agent = None
        self.check_engine_frequency = check_engine_frequency

        self.processors = {}
        self.runner_config = None
        self.secure_train = secure_train

        self.workspace = args.workspace
        self.snapshot_location = None
        self.overseer_agent = overseer_agent
        self.server_state: ServerState = ColdState()
        self.snapshot_persistor = snapshot_persistor
        self.checking_server_state = False
        self.ha_mode = False

        self.reg_lock = threading.Lock()
        self.name_to_reg = {}
        self.cred_keeper = CredKeeper()

        # these are used when the server sends a message to itself.
        self.my_own_auth_client_name = "server"
        self.my_own_token = "server"
        self.my_own_token_signature = None

    def _register_cellnet_cbs(self):
        self.cell.register_request_cb(
            channel=CellChannel.SERVER_MAIN,
            topic=CellChannelTopic.Challenge,
            cb=self.client_challenge,
        )

        self.cell.register_request_cb(
            channel=CellChannel.SERVER_MAIN,
            topic=CellChannelTopic.Register,
            cb=self.register_client,
        )

        self.cell.register_request_cb(
            channel=CellChannel.SERVER_MAIN,
            topic=CellChannelTopic.Quit,
            cb=self.quit_client,
        )
        self.cell.register_request_cb(
            channel=CellChannel.SERVER_MAIN,
            topic=CellChannelTopic.HEART_BEAT,
            cb=self.client_heartbeat,
        )

        self.cell.register_request_cb(
            channel=CellChannel.SERVER_MAIN,
            topic=CellChannelTopic.REPORT_JOB_FAILURE,
            cb=self.process_job_failure,
        )

        self.cell.register_request_cb(
            channel=CellChannel.SERVER_PARENT_LISTENER,
            topic="*",
            cb=self._listen_command,
        )

        self.max_reg_duration = ConfigService.get_float_var(
            name=ConfigVarName.MAX_REG_DURATION,
            conf=SystemConfigs.RESOURCES_CONF,
            default=60.0,
        )

        self.logger.info(f"max_reg_duration={self.max_reg_duration}")

        # set up a thread to regularly check expired reg sessions
        reg_checker = threading.Thread(target=self._check_regs, daemon=True)
        reg_checker.start()

    def _add_auth_headers(self, message: Message):
        """Add auth headers to the messages sent by the server to itself.
        This is such that no one can fake a message to pretend it's from the server to the server.
        Args:
            message: the message for which to add the headers
        Returns: None
        """
        origin = message.get_header(MessageHeaderKey.ORIGIN)
        dest = message.get_header(MessageHeaderKey.DESTINATION)
        channel = message.get_header(MessageHeaderKey.CHANNEL)
        topic = message.get_header(MessageHeaderKey.TOPIC)
        if not self.my_own_token_signature:
            self.my_own_token_signature = self.sign_auth_token(self.my_own_auth_client_name, self.my_own_token)

        add_authentication_headers(
            message, self.my_own_auth_client_name, self.my_own_token, self.my_own_token_signature
        )
        self.logger.debug(f"added auth headers:  {origin=} {dest=} {channel=} {topic=}")

    def _validate_auth_headers(self, message: Message):
        """Validate auth headers from messages that go through the server.
        Args:
            message: the message to validate
        Returns:
        """
        id_asserter = self._get_id_asserter()
        if not id_asserter:
            return None

        token_verifier = TokenVerifier(id_asserter.cert)

        return validate_auth_headers(
            message=message,
            token_verifier=token_verifier,
            logger=self.logger,
        )

    def sign_auth_token(self, client_name: str, token: str):
        id_asserter = self._get_id_asserter()
        if not id_asserter:
            return "NA"
        return id_asserter.sign(client_name + token, return_str=True)

    def verify_auth_token(self, client_name: str, token: str, signature):
        id_asserter = self._get_id_asserter()
        if not id_asserter:
            return True

        token_verifier = TokenVerifier(id_asserter.cert)
        return token_verifier.verify(client_name, token, signature)

    def _check_regs(self):
        while True:
            with self.reg_lock:
                expired_regs = []
                now = time.time()
                for client_name, reg in self.name_to_reg.items():
                    if now - reg.reg_start_time > self.max_reg_duration:
                        self.logger.warning(f"dropped expired reg session: not done in {self.max_reg_duration} secs")
                        expired_regs.append(client_name)
                for c in expired_regs:
                    self.name_to_reg.pop(c, None)
            time.sleep(5.0)

    def _listen_command(self, request: Message) -> Message:
        job_id = request.get_header(CellMessageHeaderKeys.JOB_ID)
        command = request.get_header(MessageHeaderKey.TOPIC)
        data = request.payload

        if command == ServerCommandNames.GET_CLIENTS:
            if job_id in self.engine.run_processes:
                clients = self.engine.run_processes[job_id].get(RunProcessKey.PARTICIPANTS)
                return_data = {ServerCommandKey.CLIENTS: clients, ServerCommandKey.JOB_ID: job_id}
                for t, c in clients.items():
                    self.logger.debug(f"sending client {t}: {c.name=} {c.props=}")
            else:
                return_data = {ServerCommandKey.CLIENTS: None, ServerCommandKey.JOB_ID: job_id}

            return make_cellnet_reply(F3ReturnCode.OK, "", return_data)
        elif command == ServerCommandNames.UPDATE_RUN_STATUS:
            execution_error = data.get("execution_error")
            with self.lock:
                run_process_info = self.engine.run_processes.get(job_id)
                if run_process_info is not None:
                    if execution_error:
                        run_process_info[RunProcessKey.PROCESS_EXE_ERROR] = True
                        self.engine.exception_run_processes[job_id] = run_process_info
                    run_process_info[RunProcessKey.PROCESS_FINISHED] = True
                reply = make_cellnet_reply(F3ReturnCode.OK, "", None)
                return reply
        elif command == ServerCommandNames.HEARTBEAT:
            if job_id not in self.engine.run_processes:
                self.engine.abort_app_on_server(job_id)
                self._set_job_aborted(job_id)
                self.logger.info(
                    f"Job: {job_id} should not be running, but still sending the heartbeat calls. Abort the job."
                )
            return make_cellnet_reply(F3ReturnCode.OK, "", None)
        else:
            return make_cellnet_reply(F3ReturnCode.INVALID_REQUEST, "", None)

    def _set_job_aborted(self, job_id):
        job_manager = self.engine.get_component(SystemComponents.JOB_MANAGER)
        with self.engine.new_context() as fl_ctx:
            job = job_manager.get_job(job_id, fl_ctx)
            if job.meta.get(JobMetaKey.STATUS) == RunStatus.RUNNING:
                job_manager.set_status(job_id, RunStatus.FINISHED_ABORTED, fl_ctx)

    def _create_server_engine(self, args, snapshot_persistor):
        return ServerEngine(
            server=self, args=args, client_manager=self.client_manager, snapshot_persistor=snapshot_persistor
        )

    def create_job_cell(self, job_id, root_url, parent_url, secure_train, server_config) -> Cell:
        my_fqcn = FQCN.join([FQCN.ROOT_SERVER, job_id])
        if secure_train:
            root_cert = server_config[SecureTrainConst.SSL_ROOT_CERT]
            ssl_cert = server_config[SecureTrainConst.SSL_CERT]
            private_key = server_config[SecureTrainConst.PRIVATE_KEY]

            credentials = {
                DriverParams.CA_CERT.value: root_cert,
                DriverParams.SERVER_CERT.value: ssl_cert,
                DriverParams.SERVER_KEY.value: private_key,
            }

            conn_security = server_config.get(ConnPropKey.CONNECTION_SECURITY)
            if conn_security:
                credentials[DriverParams.CONNECTION_SECURITY.value] = conn_security
        else:
            credentials = {}

        cell = Cell(
            fqcn=my_fqcn,
            root_url=root_url,
            secure=secure_train,
            credentials=credentials,
            create_internal_listener=False,
            parent_url=parent_url,
        )

        cell.start()
        net_agent = NetAgent(cell)
        mpm.add_cleanup_cb(net_agent.close)
        mpm.add_cleanup_cb(cell.stop)

        self.command_agent = ServerCommandAgent(self.engine, cell)
        self.command_agent.start()

        return cell

    # @property
    def task_meta_info(self, client_name):
        """Task meta information.

        The model_meta_info uniquely defines the current model,
        it is used to reject outdated client's update.
        """
        meta_info = {
            CellMessageHeaderKeys.PROJECT_NAME: self.project_name,
            CellMessageHeaderKeys.CLIENT_NAME: client_name,
        }
        return meta_info

    def remove_client_data(self, token):
        self.tokens.pop(token, None)

    def reset_tokens(self):
        """Reset the token set.

        After resetting, each client can take a token
        and start fetching the current global model.
        This function is not thread-safe.
        """
        self.tokens = dict()
        for token, client in self.get_all_clients().items():
            self.tokens[token] = self.task_meta_info(client.name)

    def _before_service(self, fl_ctx: FLContext):
        # before the service processing
        fl_ctx.remove_prop(FLContextKey.COMMUNICATION_ERROR)
        fl_ctx.remove_prop(FLContextKey.UNAUTHENTICATED)

    def _generate_reply(self, headers, payload, fl_ctx: FLContext):
        # process after the service processing
        unauthenticated = fl_ctx.get_prop(FLContextKey.UNAUTHENTICATED)
        if unauthenticated:
            return make_cellnet_reply(rc=F3ReturnCode.UNAUTHENTICATED, error=unauthenticated)

        error = fl_ctx.get_prop(FLContextKey.COMMUNICATION_ERROR)
        if error:
            return make_cellnet_reply(rc=F3ReturnCode.COMM_ERROR, error=error)
        else:
            return_message = new_cell_message(headers, payload)
            return_message.set_header(MessageHeaderKey.RETURN_CODE, F3ReturnCode.OK)
            return return_message

    def _get_id_asserter(self):
        with self.engine.new_context() as fl_ctx:
            return self.cred_keeper.get_id_asserter(fl_ctx)

    def _ready_for_registration(self, fl_ctx: FLContext):
        self._before_service(fl_ctx)
        state_check = self.server_state.register(fl_ctx)
        return self._handle_state_check(state_check, fl_ctx)

    def client_challenge(self, request: Message) -> Message:
        with self.reg_lock:
            self.logger.debug(f"received challenge request from {request.headers}")
            with self.engine.new_context() as fl_ctx:
                error = self._ready_for_registration(fl_ctx)
                if error is not None:
                    self.logger.debug(f"not ready for reg: {error}")
                    return make_cellnet_reply(rc=F3ReturnCode.COMM_ERROR, error=error)

                secure_mode = fl_ctx.get_prop(FLContextKey.SECURE_MODE, False)
                if not secure_mode:
                    return make_cellnet_reply(rc=F3ReturnCode.UNAUTHENTICATED, error="server is not in secure mode")

            reg_origin = request.get_header(MessageHeaderKey.ORIGIN)
            self.logger.debug(f"received challenge request from {reg_origin}: me={id(self)}")
            reg = self.name_to_reg.pop(reg_origin, None)
            if reg:
                self.logger.warning(f"received duplicate challenge from client {reg_origin} without register")
            reg = ClientRegSession(reg_origin)
            self.name_to_reg[reg_origin] = reg
            client_nonce = request.get_header(IdentityChallengeKey.NONCE)
            id_asserter = self._get_id_asserter()
            signature = id_asserter.sign_common_name(client_nonce)
            reply = Shareable()
            reply[IdentityChallengeKey.NONCE] = reg.nonce
            reply[IdentityChallengeKey.SIGNATURE] = signature
            reply[IdentityChallengeKey.COMMON_NAME] = id_asserter.cn
            reply[IdentityChallengeKey.CERT] = id_asserter.cert_data
            self.logger.debug(f"challenge ok: {reply=}")
            return make_cellnet_reply(rc=F3ReturnCode.OK, body=reply)

    def register_client(self, request: Message) -> Message:
        """Register a new client.
        Each client must be registered before being able to run jobs.
        """

        with self.engine.new_context() as fl_ctx:
            error = self._ready_for_registration(fl_ctx)
            if error is not None:
                return make_cellnet_reply(rc=F3ReturnCode.COMM_ERROR, error=error)

            try:
                secure_mode = fl_ctx.get_prop(FLContextKey.SECURE_MODE, False)
                if secure_mode:
                    reg_origin = request.get_header(MessageHeaderKey.ORIGIN)
                    with self.reg_lock:
                        reg = self.name_to_reg.pop(reg_origin, None)
                        if not reg:
                            self.logger.error(f"no registration session for client {reg_origin}: me={id(self)}")
                            return make_cellnet_reply(rc=F3ReturnCode.UNAUTHENTICATED, error="no registration session")
                        fl_ctx.set_prop(
                            key=InternalFLContextKey.CLIENT_REG_SESSION, value=reg, private=True, sticky=False
                        )

                data = request.payload
                assert isinstance(data, Shareable)
                shared_fl_ctx = data.get_peer_context()
                fl_ctx.set_peer_context(shared_fl_ctx)

                self.engine.fire_event(EventType.CLIENT_REGISTER_RECEIVED, fl_ctx=fl_ctx)

                exceptions = fl_ctx.get_prop(FLContextKey.EXCEPTIONS)
                if exceptions:
                    for _, exception in exceptions.items():
                        if isinstance(exception, NotAuthenticated):
                            raise exception

                client = self.client_manager.authenticate(request, fl_ctx)
                if client and client.token:
                    client_type = request.get_header(CellMessageHeaderKeys.CLIENT_TYPE)
                    if client_type == ClientType.REGULAR:
                        self.tokens[client.token] = self.task_meta_info(client.name)
                        if self.admin_server:
                            self.admin_server.client_heartbeat(client.token, client.name, client.get_fqcn())

                    token_signature = self.sign_auth_token(client.name, client.token)
                    result = {
                        CellMessageHeaderKeys.TOKEN: client.token,
                        CellMessageHeaderKeys.TOKEN_SIGNATURE: token_signature,
                        CellMessageHeaderKeys.SSID: self.server_state.ssid,
                    }
                else:
                    result = {}
                self.engine.fire_event(EventType.CLIENT_REGISTER_PROCESSED, fl_ctx=fl_ctx)
                return self._generate_reply(headers={}, payload=result, fl_ctx=fl_ctx)
            except NotAuthenticated as e:
                self.logger.error(f"Failed to authenticate the register_client: {secure_format_exception(e)}")
                return make_cellnet_reply(rc=F3ReturnCode.UNAUTHENTICATED, error="register_client unauthenticated")

    def _handle_state_check(self, state_check, fl_ctx: FLContext):
        if state_check.get(ACTION) in [NIS, ABORT_RUN]:
            fl_ctx.set_prop(FLContextKey.COMMUNICATION_ERROR, state_check.get(MESSAGE), sticky=False)
            return state_check.get(MESSAGE)
        return None

    def quit_client(self, request: Message) -> Message:
        """Existing client quits the federated training process.

        Server will stop sharing the global model with the client,
        further contribution will be rejected.

        This function does not change min_num_clients and max_num_clients.
        """

        with self.engine.new_context() as fl_ctx:
            client = self.client_manager.validate_client(request, fl_ctx)
            if client:
                token = client.get_token()
                self.logout_client(token)

                data = request.payload
                assert isinstance(data, Shareable)
                shared_fl_ctx = data.get_peer_context()
                fl_ctx.set_peer_context(shared_fl_ctx)
                self.engine.fire_event(EventType.CLIENT_QUIT, fl_ctx=fl_ctx)

            headers = {CellMessageHeaderKeys.MESSAGE: "Removed client"}
            return self._generate_reply(headers=headers, payload=None, fl_ctx=fl_ctx)

    def process_job_failure(self, request: Message):
        payload = request.payload
        client = request.get_header(key=MessageHeaderKey.ORIGIN)
        if not isinstance(payload, dict):
            self.logger.error(
                f"dropped bad Job Failure report from {client}: expect payload to be dict but got {type(payload)}"
            )
            return
        job_id = payload.get(JobFailureMsgKey.JOB_ID)
        if not job_id:
            self.logger.error(f"dropped bad Job Failure report from {client}: no job_id")
            return

        code = payload.get(JobFailureMsgKey.CODE)
        reason = payload.get(JobFailureMsgKey.REASON, "?")
        if code == ProcessExitCode.UNSAFE_COMPONENT:
            with self.engine.new_context() as fl_ctx:
                self.logger.info(f"Aborting job {job_id} due to reported failure from {client}: {reason}")
                self.engine.job_runner.stop_run(job_id, fl_ctx)

    def client_heartbeat(self, request: Message) -> Message:

        with self.engine.new_context() as fl_ctx:
            self._before_service(fl_ctx)

            state_check = self.server_state.heartbeat(fl_ctx)
            error = self._handle_state_check(state_check, fl_ctx)
            if error is not None:
                return make_cellnet_reply(rc=F3ReturnCode.COMM_ERROR, error=error)

            data = request.payload
            assert isinstance(data, Shareable)
            shared_fl_ctx = data.get_peer_context()
            fl_ctx.set_peer_context(shared_fl_ctx)
            self.engine.fire_event(EventType.CLIENT_HEARTBEAT_RECEIVED, fl_ctx=fl_ctx)

            token = request.get_header(CellMessageHeaderKeys.TOKEN)
            client_name = request.get_header(CellMessageHeaderKeys.CLIENT_NAME)
            client_fqcn = request.get_header(MessageHeaderKey.ORIGIN)
            if self.client_manager.heartbeat(token, client_name, client_fqcn, fl_ctx):
                self.tokens[token] = self.task_meta_info(client_name)
            if self.admin_server:
                self.admin_server.client_heartbeat(token, client_name, client_fqcn)

            abort_runs = self._sync_client_jobs(request, token)
            reply = self._generate_reply(
                headers={CellMessageHeaderKeys.MESSAGE: "Heartbeat response"}, payload=None, fl_ctx=fl_ctx
            )

            if abort_runs:
                reply.set_header(CellMessageHeaderKeys.ABORT_JOBS, abort_runs)

                display_runs = ",".join(abort_runs)
                self.logger.debug(
                    f"These jobs: {display_runs} are not running on the server. "
                    f"Ask client: {client_name} to abort these runs."
                )
            self.engine.fire_event(EventType.CLIENT_HEARTBEAT_PROCESSED, fl_ctx=fl_ctx)
            return reply

    def _sync_client_jobs(self, request, client_token):
        # jobs that are running on client but not on server need to be aborted!
        client_jobs = request.get_header(CellMessageHeaderKeys.JOB_IDS)
        server_jobs = self.engine.run_processes.keys()
        jobs_need_abort = list(set(client_jobs).difference(server_jobs))

        # also check jobs that are running on server but not on the client
        jobs_on_server_but_not_on_client = list(set(server_jobs).difference(client_jobs))
        if jobs_on_server_but_not_on_client:
            # notify all the participating clients these jobs are not running on server anymore
            for job_id in jobs_on_server_but_not_on_client:
                job_info = self.engine.run_processes[job_id]
                participating_clients = job_info.get(RunProcessKey.PARTICIPANTS, None)
                if participating_clients:
                    # this is a dict: token => nvflare.apis.client.Client
                    client = participating_clients.get(client_token, None)
                    if client:
                        self._notify_dead_job(client, job_id, "missing job on client")

        return jobs_need_abort

    def _notify_dead_job(self, client, job_id: str, reason: str):
        try:
            self.engine.notify_dead_job(job_id, client.name, reason)
        except Exception as ex:
            self.logger.info(
                f"Failed to notify_dead_job to runner process of job {job_id}: {secure_format_exception(ex)}"
            )

    def notify_dead_client(self, client):
        """Called to do further processing of the dead client

        Args:
            client: the dead client

        Returns:

        """
        # find all RUNs that this client is participating
        if not self.engine.run_processes:
            return

        for job_id, process_info in self.engine.run_processes.items():
            assert isinstance(process_info, dict)
            participating_clients = process_info.get(RunProcessKey.PARTICIPANTS, None)
            if participating_clients and client.token in participating_clients:
                self._notify_dead_job(client, job_id, "client dead")

    def start_run(self, job_id, run_root, conf, args, snapshot):
        # Create the FL Engine
        workspace = Workspace(args.workspace, SiteType.SERVER, args.config_folder)
        self.run_manager = self.create_run_manager(workspace, job_id)
        self.engine.set_run_manager(self.run_manager)
        self.engine.set_configurator(conf)
        self.engine.asked_to_stop = False
        self.run_manager.cell = self.cell

        fed_event_runner = ServerFedEventRunner()
        self.run_manager.add_handler(fed_event_runner)

        try:
            self.server_runner = ServerRunner(config=self.runner_config, job_id=job_id, engine=self.engine)
            self.run_manager.add_handler(self.server_runner)
            self.run_manager.add_component("_Server_Runner", self.server_runner)

            with self.engine.new_context() as fl_ctx:

                if snapshot:
                    self.engine.restore_components(snapshot=snapshot, fl_ctx=FLContext())

                fl_ctx.set_prop(FLContextKey.APP_ROOT, run_root, sticky=True)
                fl_ctx.set_prop(FLContextKey.CURRENT_RUN, job_id, private=False, sticky=True)
                fl_ctx.set_prop(FLContextKey.WORKSPACE_ROOT, args.workspace, private=True, sticky=True)
                fl_ctx.set_prop(FLContextKey.ARGS, args, private=True, sticky=True)
                fl_ctx.set_prop(FLContextKey.WORKSPACE_OBJECT, workspace, private=True)
                fl_ctx.set_prop(FLContextKey.SECURE_MODE, self.secure_train, private=True, sticky=True)
                fl_ctx.set_prop(FLContextKey.RUNNER, self.server_runner, private=True, sticky=True)

            engine_thread = threading.Thread(target=self.run_engine)
            engine_thread.start()

            self.engine.engine_info.status = MachineStatus.STARTED
            while self.engine.engine_info.status != MachineStatus.STOPPED:
                if self.engine.asked_to_stop:
                    self.engine.engine_info.status = MachineStatus.STOPPED

                self._send_parent_heartbeat(job_id)
                time.sleep(self.check_engine_frequency)

        finally:
            self.engine.engine_info.status = MachineStatus.STOPPED
            self.run_manager = None

    def _send_parent_heartbeat(self, job_id):
        if self.cell:
            request = new_cell_message({CellMessageHeaderKeys.JOB_ID: job_id}, {})
            self.cell.fire_and_forget(
                targets=FQCN.ROOT_SERVER,
                channel=CellChannel.SERVER_PARENT_LISTENER,
                topic=ServerCommandNames.HEARTBEAT,
                message=request,
            )

    def create_run_manager(self, workspace, job_id):
        return RunManager(
            server_name=self.project_name,
            engine=self.engine,
            job_id=job_id,
            workspace=workspace,
            components=self.runner_config.components,
            client_manager=self.client_manager,
            handlers=self.runner_config.handlers,
        )

    def authentication_check(self, request: Message, state_check):
        error = None
        # server_state = self.engine.server.server_state
        if state_check.get(ACTION) in [NIS, ABORT_RUN]:
            # return make_reply(ReturnCode.AUTHENTICATION_ERROR, state_check.get(MESSAGE), fobs.dumps(None))
            error = state_check.get(MESSAGE)
        client_ssid = request.get_header(CellMessageHeaderKeys.SSID, None)
        if client_ssid != self.server_state.ssid:
            # return make_reply(ReturnCode.AUTHENTICATION_ERROR, "Request from invalid client SSID",
            #                   fobs.dumps(None))
            error = "Request from unknown client SSID"
        return error

    def abort_run(self):
        with self.engine.new_context() as fl_ctx:
            if self.server_runner:
                self.server_runner.abort(fl_ctx)

    def run_engine(self):
        self.engine.engine_info.status = MachineStatus.STARTED
        try:
            self.server_runner.run()
        except Exception as e:
            self.logger.error(f"FL server execution exception: {secure_format_exception(e)}")
        finally:
            # self.engine.update_job_run_status()
            self.stop_run_engine_cell()

        self.engine.engine_info.status = MachineStatus.STOPPED

    def stop_run_engine_cell(self):
        # self.cell.stop()
        # mpm.stop()
        pass

    def deploy(self, args, grpc_args=None, secure_train=False):
        super().deploy(args, grpc_args, secure_train)

        target = grpc_args["service"].get("target", "0.0.0.0:6007")
        with self.lock:
            self.server_state.host = target.split(":")[0]
            self.server_state.service_port = target.split(":")[1]

        self.overseer_agent = self._init_agent(args)
        if isinstance(self.overseer_agent, HttpOverseerAgent):
            self.ha_mode = True

        if secure_train:
            if self.overseer_agent:
                self.overseer_agent.set_secure_context(
                    ca_path=grpc_args["ssl_root_cert"],
                    cert_path=grpc_args["ssl_cert"],
                    prv_key_path=grpc_args["ssl_private_key"],
                )

        self.engine.initialize_comm(self.cell)
        self._register_cellnet_cbs()

        if secure_train:
            core_cell = self.cell.core_cell
            core_cell.add_incoming_filter(
                channel="*",
                topic="*",
                cb=self._validate_auth_headers,
            )

            # set filter to add additional auth headers
            core_cell.add_outgoing_reply_filter(channel="*", topic="*", cb=self._add_auth_headers)
            core_cell.add_outgoing_request_filter(channel="*", topic="*", cb=self._add_auth_headers)

        self.overseer_agent.start(self.overseer_callback)

    def _init_agent(self, args=None):
        kv_list = parse_vars(args.set)
        sp = kv_list.get("sp")

        if sp:
            with self.engine.new_context() as fl_ctx:
                fl_ctx.set_prop(FLContextKey.SP_END_POINT, sp)
                self.overseer_agent.initialize(fl_ctx)

        return self.overseer_agent

    def _check_server_state(self, overseer_agent):
        if self.status != ServerStatus.STARTED:
            return

        if overseer_agent.is_shutdown():
            self.engine.shutdown_server()
            return

        sp = overseer_agent.get_primary_sp()

        old_state_name = self.server_state.__class__.__name__
        with self.lock:
            with self.engine.new_context() as fl_ctx:
                self.server_state = self.server_state.handle_sd_callback(sp, fl_ctx)

        if isinstance(self.server_state, Cold2HotState):
            self._turn_to_hot()

        elif isinstance(self.server_state, Hot2ColdState):
            self._turn_to_cold(old_state_name)

    def _notify_state_change(self, old_state_name):
        new_state_name = self.server_state.__class__.__name__
        if new_state_name != old_state_name:
            self.logger.info(f"state changed from: {old_state_name} to: {new_state_name}")
            keys = list(self.engine.run_processes.keys())
            if keys:
                target_fqcns = []
                for job_id in keys:
                    target_fqcns.append(FQCN.join([FQCN.ROOT_SERVER, job_id]))
                cell_msg = new_cell_message(headers={}, payload=self.server_state)
                self.cell.broadcast_request(
                    channel=CellChannel.SERVER_COMMAND,
                    topic=ServerCommandNames.SERVER_STATE,
                    request=cell_msg,
                    targets=target_fqcns,
                    timeout=5.0,
                    optional=True,
                )

    def overseer_callback(self, overseer_agent):
        if self.checking_server_state:
            self.logger.debug("busy checking server state")
            return

        self.checking_server_state = True
        try:
            self._check_server_state(overseer_agent)
        except Exception as ex:
            self.logger.error(f"exception in checking server state: {secure_format_exception(ex)}")
        finally:
            self.checking_server_state = False

    def _turn_to_hot(self):
        # Restore Snapshot
        if self.ha_mode:
            restored_job_ids = []
            with self.snapshot_lock:
                fl_snapshot = self.snapshot_persistor.retrieve()
                if fl_snapshot:
                    for run_number, snapshot in fl_snapshot.run_snapshots.items():
                        if snapshot and not snapshot.completed:
                            # Restore the workspace
                            workspace_data = snapshot.get_component_snapshot(SnapshotKey.WORKSPACE).get("content")
                            ws = Workspace(self.workspace)
                            dst = ws.get_run_dir(str(run_number))
                            if os.path.exists(dst):
                                shutil.rmtree(dst, ignore_errors=True)

                            os.makedirs(dst, exist_ok=True)
                            unzip_all_from_bytes(workspace_data, dst)

                            job_id = snapshot.get_component_snapshot(SnapshotKey.JOB_INFO).get(SnapshotKey.JOB_ID)
                            job_clients = snapshot.get_component_snapshot(SnapshotKey.JOB_INFO).get(
                                SnapshotKey.JOB_CLIENTS
                            )
                            self.logger.info(f"Restore the previous snapshot. Run_number: {run_number}")
                            with self.engine.new_context() as fl_ctx:
                                self.engine.job_runner.restore_running_job(
                                    job_id=job_id,
                                    job_clients=job_clients,
                                    snapshot=snapshot,
                                    fl_ctx=fl_ctx,
                                )
                            restored_job_ids.append(job_id)
            with self.engine.new_context() as fl_ctx:
                self.engine.job_runner.update_abnormal_finished_jobs(restored_job_ids, fl_ctx=fl_ctx)
        else:
            with self.engine.new_context() as fl_ctx:
                self.snapshot_persistor.delete()
                self.engine.job_runner.update_unfinished_jobs(fl_ctx=fl_ctx)

        with self.lock:
            self.server_state = HotState(
                host=self.server_state.host, port=self.server_state.service_port, ssid=self.server_state.ssid
            )

    def _turn_to_cold(self, old_state_name):
        with self.lock:
            self.server_state = ColdState(host=self.server_state.host, port=self.server_state.service_port)
        self._notify_state_change(old_state_name)
        self.engine.pause_server_jobs()

    def stop_training(self):
        self.status = ServerStatus.STOPPED
        self.logger.info("Server app stopped.\n\n")

    def fl_shutdown(self):
        self.engine.stop_all_jobs()
        self.engine.fire_event(EventType.SYSTEM_END, self.engine.new_context())

        super().fl_shutdown()

    def close(self):
        """Shutdown the server."""
        self.logger.info("shutting down server")
        self.shutdown = True
        if self.overseer_agent:
            self.overseer_agent.end()
        return super().close()
