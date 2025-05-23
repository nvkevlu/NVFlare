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

import re

from nvflare.apis.executor import Executor
from nvflare.apis.fl_component import FLComponent
from nvflare.apis.fl_constant import ConnPropKey, SystemConfigs, SystemVarName
from nvflare.apis.workspace import Workspace
from nvflare.fuel.data_event.utils import get_scope_property
from nvflare.fuel.utils.argument_utils import parse_vars
from nvflare.fuel.utils.config_service import ConfigService
from nvflare.fuel.utils.json_scanner import Node
from nvflare.private.fed_json_config import FedJsonConfigurator
from nvflare.private.json_configer import ConfigContext, ConfigError

from .client_runner import ClientRunnerConfig, TaskRouter


class _ExecutorDef(object):
    def __init__(self):
        self.tasks = []
        self.executor = None


FL_PACKAGES = ["nvflare"]
FL_MODULES = ["apis", "app_common", "widgets"]


class ClientJsonConfigurator(FedJsonConfigurator):
    def __init__(
        self, workspace_obj: Workspace, config_file_name: str, args, app_root: str, kv_list=None, exclude_libs=True
    ):
        """To init the ClientJsonConfigurator.

        Args:
            config_file_name: config file name
            exclude_libs: True/False to exclude the libs folder
        """
        self.args = args
        self.app_root = app_root

        base_pkgs = FL_PACKAGES
        module_names = FL_MODULES

        if kv_list:
            assert isinstance(kv_list, list), "cmd_vars must be list, but got {}".format(type(kv_list))
            self.cmd_vars = parse_vars(kv_list)
        else:
            self.cmd_vars = {}

        # determine the values of variables that can be used in job config.
        sp_scheme = args.sp_scheme
        sp_target = args.sp_target
        sp_url = f"{sp_scheme}://{sp_target}"

        # determine relay URL
        # if relay is not used, use the root URL as relay URL
        relay_conn_props = get_scope_property(args.client_name, ConnPropKey.RELAY_CONN_PROPS)
        relay_url = None
        if relay_conn_props:
            relay_url = relay_conn_props.get(ConnPropKey.URL)
        if not relay_url:
            relay_url = sp_url

        if hasattr(args, "parent_url") and args.parent_url:
            parent_url = args.parent_url
        else:
            parent_url = sp_url

        sys_vars = {
            SystemVarName.JOB_ID: args.job_id,
            SystemVarName.SITE_NAME: args.client_name,
            SystemVarName.WORKSPACE: args.workspace,
            SystemVarName.ROOT_URL: sp_url,
            SystemVarName.CP_URL: parent_url,
            SystemVarName.RELAY_URL: relay_url,
            SystemVarName.SECURE_MODE: self.cmd_vars.get("secure_train", True),
            SystemVarName.JOB_CUSTOM_DIR: workspace_obj.get_app_custom_dir(args.job_id),
            SystemVarName.JOB_CONFIG_DIR: workspace_obj.get_app_config_dir(args.job_id),
        }

        FedJsonConfigurator.__init__(
            self,
            config_file_name=config_file_name,
            base_pkgs=base_pkgs,
            module_names=module_names,
            exclude_libs=exclude_libs,
            is_server=False,
            sys_vars=sys_vars,
        )

        self.config_files = [config_file_name]

        self.runner_config = None
        self.executors = []
        self.current_exe = None
        self._default_task_fetch_interval = 0.5

    def process_config_element(self, config_ctx: ConfigContext, node: Node):
        FedJsonConfigurator.process_config_element(self, config_ctx, node)

        element = node.element
        path = node.path()

        # default task fetch interval
        if re.search(r"default_task_fetch_interval", path):
            if not isinstance(element, int) and not isinstance(element, float):
                raise ConfigError('"default_task_fetch_interval" must be a number, but got {}'.format(type(element)))

            if element <= 0:
                raise ConfigError('"default_task_fetch_interval" must > 0, but got {}'.format(element))

            self._default_task_fetch_interval = element
            return

        # executors
        if re.search(r"^executors\.#[0-9]+$", path):
            self.current_exe = _ExecutorDef()
            node.props["data"] = self.current_exe
            node.exit_cb = self._process_executor_def
            return

        if re.search(r"^executors\.#[0-9]+\.tasks$", path):
            self.current_exe.tasks = element
            return

        if re.search(r"^executors\.#[0-9]+\.executor$", path):
            self.current_exe.executor = self.authorize_and_build_component(element, config_ctx, node)
            return

    def build_component(self, config_dict):
        t = super().build_component(config_dict)
        if isinstance(t, FLComponent):
            self.handlers.append(t)
        return t

    def _process_executor_def(self, node: Node):
        e = node.props["data"]
        if not isinstance(e, _ExecutorDef):
            raise TypeError("e must be _ExecutorDef but got {}".format(type(e)))
        self.validate_tasks(e.tasks)

        if not isinstance(e.executor, Executor):
            raise ConfigError('"executor" must be an Executor object but got {}'.format(type(e.executor)))

        self.executors.append(e)

    def finalize_config(self, config_ctx: ConfigContext):
        FedJsonConfigurator.finalize_config(self, config_ctx)

        if len(self.executors) <= 0:
            raise ConfigError("executors are not specified")

        task_router = TaskRouter()
        for e in self.executors:
            task_router.add_executor(e.tasks, e.executor)

        self.runner_config = ClientRunnerConfig(
            task_router=task_router,
            task_data_filters=self.data_filter_table,
            task_result_filters=self.result_filter_table,
            components=self.components,
            handlers=self.handlers,
            default_task_fetch_interval=self._default_task_fetch_interval,
        )

        ConfigService.initialize(
            section_files={},
            config_path=[self.app_root],
            parsed_args=self.args,
            var_dict=self.cmd_vars,
        )

        ConfigService.add_section(
            section_name=SystemConfigs.APPLICATION_CONF,
            data=self.config_data,
        )
