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

from unittest.mock import MagicMock, patch

from nvflare.apis.fl_constant import FLContextKey, ReservedKey, ServerCommandKey
from nvflare.apis.fl_context import FLContext
from nvflare.apis.shareable import Shareable
from nvflare.fuel.f3.cellnet.defs import MessageHeaderKey, ReturnCode
from nvflare.fuel.f3.message import Message as CellMessage
from nvflare.private.defs import ClientRegMsgKey, SpecialTaskName
from nvflare.private.fed.client.communicator import Communicator
from nvflare.private.fed.resource_stats.f3_counter import F3Counter, F3TrafficClass


def test_get_site_config_for_registration_from_loaded_client_config():
    site_config = {"labels": {"region": "us-east"}}
    communicator = Communicator(client_config={"client_name": "site-1", ClientRegMsgKey.SITE_CONFIG: site_config})

    assert communicator._get_site_config_for_registration(FLContext()) == site_config


def test_get_site_config_for_registration_ignores_non_dict_config():
    communicator = Communicator(client_config={"client_name": "site-1", ClientRegMsgKey.SITE_CONFIG: ["bad"]})

    assert communicator._get_site_config_for_registration(FLContext()) is None


def test_hierarchical_task_forward_does_not_create_a_second_f3_origin():
    communicator = Communicator(client_config={"client_name": "site-1"})
    communicator.engine = MagicMock()

    pending_task = Shareable()
    pending_task.set_header(FLContextKey.TASK_ID, "task-1")
    pending_task.set_header(ServerCommandKey.TASK_NAME, "train")
    pending_task.set_header(ReservedKey.TASK_IS_READY, True)
    communicator.pending_task = pending_task

    request = CellMessage(payload=Shareable())
    request.set_header(MessageHeaderKey.ORIGIN, "site-1.child")

    with patch("nvflare.private.fed.client.communicator.attach_f3_context") as attach:
        response = communicator._process_get_task(request)

    assert response.payload.get_header(ServerCommandKey.TASK_NAME) == "train"
    assert response.get_logical_send_context() is None
    attach.assert_not_called()


def test_task_poll_request_is_not_included_in_f3():
    communicator = Communicator(client_config={"client_name": "site-1"})
    communicator.cell = MagicMock()
    response_payload = Shareable()
    response_payload.set_header(ServerCommandKey.TASK_NAME, SpecialTaskName.TRY_AGAIN)
    communicator.cell.send_request.return_value = CellMessage(
        headers={MessageHeaderKey.RETURN_CODE: ReturnCode.OK, MessageHeaderKey.PAYLOAD_LEN: 5},
        payload=response_payload,
    )
    fl_ctx = MagicMock()
    fl_ctx.get_job_id.return_value = "job-1"

    with patch("nvflare.private.fed.client.communicator.gen_new_peer_ctx", return_value=FLContext()):
        communicator.pull_task("project", "token", "session-1", fl_ctx)

    request = communicator.cell.send_request.call_args.kwargs["request"]
    assert request.get_logical_send_context() is None


def test_submit_update_attaches_task_result_context_at_the_producer():
    communicator = Communicator(client_config={"client_name": "site-1"})
    communicator.cell = MagicMock()
    communicator.ssid = "session-1"

    def send_request(**kwargs):
        kwargs["request"].set_header(MessageHeaderKey.PAYLOAD_LEN, 7)
        return CellMessage(headers={MessageHeaderKey.RETURN_CODE: ReturnCode.OK})

    communicator.cell.send_request.side_effect = send_request

    fl_ctx = MagicMock()
    fl_ctx.get_job_id.return_value = "job-1"
    fl_ctx.get_prop.side_effect = lambda key, default=None: "session-1" if key == FLContextKey.SSID else default
    result = Shareable()
    counter = F3Counter()

    with (
        patch("nvflare.private.fed.client.communicator.gen_new_peer_ctx", return_value=FLContext()),
        patch("nvflare.private.fed.client.communicator.get_job_f3_counter", return_value=counter),
    ):
        return_code = communicator.submit_update(
            project_name="project",
            token="token",
            ssid="session-1",
            fl_ctx=fl_ctx,
            client_name="site-1",
            shareable=result,
            execute_task_name="train",
        )

    assert return_code == ReturnCode.OK
    request = communicator.cell.send_request.call_args.kwargs["request"]
    context = request.get_logical_send_context()
    assert context is not None
    assert context._accounting is counter
    assert context._traffic_class is F3TrafficClass.TASK_RESULT
