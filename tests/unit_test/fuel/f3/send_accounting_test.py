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

import logging
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nvflare.fuel.f3.cellnet.core_cell import CoreCell
from nvflare.fuel.f3.cellnet.defs import MessageHeaderKey
from nvflare.fuel.f3.cellnet.fqcn import FqcnInfo
from nvflare.fuel.f3.endpoint import Endpoint
from nvflare.fuel.f3.message import Message
from nvflare.fuel.f3.send_accounting import attach_logical_send_context
from nvflare.fuel.f3.streaming.blob_streamer import BlobStream
from nvflare.fuel.f3.streaming.byte_streamer import STREAM_TYPE_BLOB, ByteStreamer, TxTask
from nvflare.fuel.f3.streaming.download_service import TransactionDoneStatus, _Transaction
from nvflare.private.fed.resource_stats.f3_counter import F3Counter, F3TrafficClass
from tests.unit_test.fuel.f3.streaming.download_test_utils import (
    MockDownloadable,
    make_isolated_download_service,
    pull_request,
)


def _counter_value(counter: F3Counter):
    return counter.freeze()["remote_accepted"]


def _core_cell(fqcn="origin"):
    cell = CoreCell.__new__(CoreCell)
    cell.my_info = FqcnInfo(fqcn)
    cell.logger = logging.getLogger(__name__)
    cell.fobs_ctx = {}
    cell.max_msg_size = 1024 * 1024
    cell.ALL_CELLS = {}
    cell.communicator = MagicMock()
    cell.sent_msg_size_pool = MagicMock()
    cell._stats_category = MagicMock(return_value="test")
    cell.log_error = MagicMock()
    return cell


def test_message_clone_preserves_context_without_serializing_it():
    message = Message(headers={"wire": "value"}, payload=b"payload")
    counter = F3Counter()
    context = attach_logical_send_context(message, counter, F3TrafficClass.TASK_RESULT)

    clone = message.clone(deep_copy_headers=True)

    assert clone.get_logical_send_context() is context
    assert clone.headers == {"wire": "value"}
    assert set(clone.__dict__) == {"headers", "payload", "_logical_send_context"}


def test_real_counter_counts_one_origin_send_per_destination():
    counter = F3Counter()
    context = attach_logical_send_context(Message(), counter, F3TrafficClass.TASK_RESULT)

    first = context.try_begin("origin", "site-1")
    second = context.try_begin("origin", "site-2")
    assert first is not None
    assert second is not None
    first.accepted(10)
    second.accepted(20)

    assert context.try_begin("origin", "site-1") is None
    assert context.try_begin("relay", "site-3") is None
    assert _counter_value(counter) == {"payload_bytes": "30", "messages": "2"}


def test_pre_admission_is_reused_once_by_transport():
    counter = F3Counter()
    context = attach_logical_send_context(Message(), counter, F3TrafficClass.TASK_RESPONSE)

    assert context.pre_admit("server/job", "client/job")
    assert counter.pending_count == 1

    attempt = context.try_begin("server/job", "client/job")
    assert attempt is not None
    assert counter.pending_count == 1
    assert context.try_begin("server/job", "client/job") is None
    attempt.accepted(17)

    assert _counter_value(counter) == {"payload_bytes": "17", "messages": "1"}


def test_pre_admission_allows_oob_registration_before_transport():
    counter = F3Counter()
    context = attach_logical_send_context(Message(), counter, F3TrafficClass.TASK_RESPONSE)

    assert context.pre_admit("server/job", "client/job")
    context.register_oob_transaction("tx-1", ("client/job",))
    main = context.try_begin("server/job", "client/job")
    assert main is not None
    main.accepted(7)
    contribution = context.make_oob_contribution_context("tx-1", "client/job", "chunk-1", 11)
    contribution.try_begin("server/job", "client/job").accepted(999)
    context.settle_oob_transaction("tx-1", {"client/job"})

    assert _counter_value(counter) == {"payload_bytes": "18", "messages": "1"}


def test_failed_pre_admission_marks_closed_owner_partial():
    counter = F3Counter()
    counter.close()
    context = attach_logical_send_context(Message(), counter, F3TrafficClass.TASK_RESPONSE)

    assert not context.pre_admit("server/job", "client/job")

    assert counter.freeze() == {
        "status": "partial",
        "issues": ["counter_gap"],
        "remote_accepted": {"payload_bytes": "0", "messages": "0"},
    }


def test_oob_bytes_complete_the_same_message_only_after_settlement():
    counter = F3Counter()
    context = attach_logical_send_context(Message(), counter, F3TrafficClass.TASK_RESULT)
    context.register_oob_transaction("tx-1", ("site-1",))

    main = context.try_begin("origin", "site-1")
    assert main is not None
    main.accepted(11)
    assert counter.pending_count == 1

    contribution = context.make_oob_contribution_context("tx-1", "site-1", "chunk-1", 101)
    assert contribution is not None
    chunk = contribution.try_begin("origin", "site-1")
    assert chunk is not None
    chunk.accepted(9999)  # encoded DownloadService reply size is deliberately ignored

    duplicate = contribution.try_begin("origin", "site-1")
    assert duplicate is None
    assert counter.pending_count == 1

    context.settle_oob_transaction("tx-1", {"site-1"})

    assert counter.pending_count == 0
    assert _counter_value(counter) == {"payload_bytes": "112", "messages": "1"}


def test_oob_settlement_waits_for_an_inflight_last_contribution():
    class BlockingAccounting:
        def __init__(self):
            self.counter = F3Counter()
            self.add_started = threading.Event()
            self.release_add = threading.Event()

        def __getattr__(self, name):
            return getattr(self.counter, name)

        def add_accepted_payload_bytes(self, admission, payload_bytes):
            self.add_started.set()
            assert self.release_add.wait(timeout=1.0)
            return self.counter.add_accepted_payload_bytes(admission, payload_bytes)

    accounting = BlockingAccounting()
    counter = accounting.counter
    context = attach_logical_send_context(Message(), accounting, F3TrafficClass.TASK_RESULT)
    context.register_oob_transaction("tx-1", ("site-1",))
    main = context.try_begin("origin", "site-1")
    main.accepted(7)

    contribution = context.make_oob_contribution_context("tx-1", "site-1", "last", 5)
    chunk = contribution.try_begin("origin", "site-1")
    send_thread = threading.Thread(target=chunk.accepted, args=(123,))
    send_thread.start()
    assert accounting.add_started.wait(timeout=1.0)

    context.settle_oob_transaction("tx-1", {"site-1"})
    assert counter.pending_count == 1

    accounting.release_add.set()
    send_thread.join(timeout=1.0)
    assert not send_thread.is_alive()

    assert counter.pending_count == 0
    assert _counter_value(counter) == {"payload_bytes": "12", "messages": "1"}


def test_failed_oob_settlement_marks_the_observation_partial():
    counter = F3Counter()
    context = attach_logical_send_context(Message(), counter, F3TrafficClass.TASK_RESULT)
    context.register_oob_transaction("tx-1", ("site-1",))
    main = context.try_begin("origin", "site-1")
    main.accepted(7)

    context.settle_oob_transaction("tx-1", set())

    snapshot = counter.freeze()
    assert snapshot["status"] == "partial"
    assert snapshot["issues"] == ["counter_gap"]
    assert snapshot["remote_accepted"] == {"payload_bytes": "0", "messages": "0"}


def test_multi_destination_oob_retains_successful_subtotal_when_another_destination_fails():
    counter = F3Counter()
    context = attach_logical_send_context(Message(), counter, F3TrafficClass.TASK_RESULT)
    context.register_oob_transaction("tx-1", ("site-1", "site-2"))

    site_1 = context.try_begin("origin", "site-1")
    site_2 = context.try_begin("origin", "site-2")
    site_1.accepted(7)
    site_2.accepted(9)
    site_1_chunk = context.make_oob_contribution_context("tx-1", "site-1", "site-1-chunk", 11)
    site_2_chunk = context.make_oob_contribution_context("tx-1", "site-2", "site-2-chunk", 13)
    site_1_chunk.try_begin("origin", "site-1").accepted(1000)
    site_2_chunk.try_begin("origin", "site-2").accepted(1000)

    context.settle_oob_transaction("tx-1", {"site-1"})

    snapshot = counter.freeze()
    assert snapshot["status"] == "partial"
    assert snapshot["issues"] == ["counter_gap"]
    assert snapshot["remote_accepted"] == {"payload_bytes": "18", "messages": "1"}


def test_unknown_oob_receivers_mark_the_main_send_partial():
    counter = F3Counter()
    context = attach_logical_send_context(Message(), counter, F3TrafficClass.TASK_RESULT)
    context.register_oob_transaction("tx-unknown", None)

    assert context.try_begin("origin", "site-1") is None

    snapshot = counter.freeze()
    assert snapshot["status"] == "partial"
    assert snapshot["issues"] == ["counter_gap"]
    assert snapshot["remote_accepted"] == {"payload_bytes": "0", "messages": "0"}


def test_late_oob_registration_marks_a_completed_send_partial():
    counter = F3Counter()
    context = attach_logical_send_context(Message(), counter, F3TrafficClass.TASK_RESULT)
    main = context.try_begin("origin", "site-1")
    main.accepted(7)

    context.register_oob_transaction("late-tx", ("site-1",))

    snapshot = counter.freeze()
    assert snapshot["status"] == "partial"
    assert snapshot["issues"] == ["counter_gap"]
    assert snapshot["remote_accepted"] == {"payload_bytes": "7", "messages": "1"}


def test_core_cell_counts_post_fobs_pre_encryption_size(monkeypatch):
    import nvflare.fuel.f3.cellnet.core_cell as core_cell_module

    cell = _core_cell()
    counter = F3Counter()
    message = Message(headers={MessageHeaderKey.DESTINATION: "site-1"}, payload={"large": "object"})
    attach_logical_send_context(message, counter, F3TrafficClass.TASK_RESULT)

    def encode(msg, fobs_ctx):
        msg.payload = b"encoded"
        return 7

    monkeypatch.setattr(core_cell_module, "encode_payload", encode)
    cell.encrypt_payload = lambda msg: setattr(msg, "payload", b"encrypted-payload-is-larger")

    assert cell._send_to_endpoint(Endpoint("site-1"), message) == ""
    assert cell.communicator.send.call_count == 1
    assert _counter_value(counter) == {"payload_bytes": "7", "messages": "1"}


def test_core_cell_reuses_pre_admission(monkeypatch):
    import nvflare.fuel.f3.cellnet.core_cell as core_cell_module

    cell = _core_cell("server/job")
    counter = F3Counter()
    message = Message(headers={MessageHeaderKey.DESTINATION: "client/job"}, payload=b"payload")
    context = attach_logical_send_context(message, counter, F3TrafficClass.TASK_RESPONSE)
    assert context.pre_admit("server/job", "client/job")
    monkeypatch.setattr(core_cell_module, "encode_payload", lambda _message, fobs_ctx: 7)
    cell.encrypt_payload = MagicMock()

    assert cell._send_to_endpoint(Endpoint("client/job"), message) == ""
    assert counter.pending_count == 0
    assert _counter_value(counter) == {"payload_bytes": "7", "messages": "1"}


def test_core_cell_excludes_direct_in_process_delivery(monkeypatch):
    import nvflare.fuel.f3.cellnet.core_cell as core_cell_module

    cell = _core_cell()
    cell.ALL_CELLS["site-1"] = object()
    cell._send_direct_message = MagicMock()
    counter = F3Counter()
    message = Message(headers={MessageHeaderKey.DESTINATION: "site-1"}, payload=b"payload")
    attach_logical_send_context(message, counter, F3TrafficClass.TASK_RESULT)
    monkeypatch.setattr(core_cell_module, "encode_payload", lambda _message, fobs_ctx: 7)
    cell.encrypt_payload = MagicMock()

    assert cell._send_to_endpoint(Endpoint("site-1"), message) == ""
    cell._send_direct_message.assert_called_once()
    assert _counter_value(counter) == {"payload_bytes": "0", "messages": "0"}


def test_core_cell_abandons_pre_admission_for_direct_final_delivery(monkeypatch):
    import nvflare.fuel.f3.cellnet.core_cell as core_cell_module

    cell = _core_cell("server/job")
    cell.ALL_CELLS["client/job"] = object()
    cell._send_direct_message = MagicMock()
    counter = F3Counter()
    message = Message(headers={MessageHeaderKey.DESTINATION: "client/job"}, payload=b"payload")
    context = attach_logical_send_context(message, counter, F3TrafficClass.TASK_RESPONSE)
    assert context.pre_admit("server/job", "client/job")
    monkeypatch.setattr(core_cell_module, "encode_payload", lambda _message, fobs_ctx: 7)
    cell.encrypt_payload = MagicMock()

    assert cell._send_to_endpoint(Endpoint("client/job"), message) == ""
    assert counter.pending_count == 0
    assert _counter_value(counter) == {"payload_bytes": "0", "messages": "0"}


def test_encode_failure_leaves_pre_admission_to_freeze_partial(monkeypatch):
    import nvflare.fuel.f3.cellnet.core_cell as core_cell_module

    cell = _core_cell("server/job")
    counter = F3Counter()
    message = Message(headers={MessageHeaderKey.DESTINATION: "client/job"}, payload=b"payload")
    context = attach_logical_send_context(message, counter, F3TrafficClass.TASK_RESPONSE)
    assert context.pre_admit("server/job", "client/job")

    def fail_encode(_message, fobs_ctx):
        raise RuntimeError("encode failed")

    monkeypatch.setattr(core_cell_module, "encode_payload", fail_encode)
    cell.encrypt_payload = MagicMock()

    assert cell._send_to_endpoint(Endpoint("client/job"), message)
    assert not counter.close_and_drain(0.0)
    assert counter.freeze() == {
        "status": "partial",
        "issues": ["counter_gap"],
        "remote_accepted": {"payload_bytes": "0", "messages": "0"},
    }


def test_core_cell_counts_a_local_first_hop_to_a_remote_destination(monkeypatch):
    import nvflare.fuel.f3.cellnet.core_cell as core_cell_module

    cell = _core_cell()
    cell.ALL_CELLS["relay"] = object()
    cell._send_direct_message = MagicMock()
    counter = F3Counter()
    message = Message(headers={MessageHeaderKey.DESTINATION: "site-1"}, payload=b"payload")
    attach_logical_send_context(message, counter, F3TrafficClass.TASK_RESULT)
    monkeypatch.setattr(core_cell_module, "encode_payload", lambda _message, fobs_ctx: 7)
    cell.encrypt_payload = MagicMock()

    assert cell._send_to_endpoint(Endpoint("relay"), message) == ""
    cell._send_direct_message.assert_called_once()
    assert _counter_value(counter) == {"payload_bytes": "7", "messages": "1"}


def test_accounting_exception_never_changes_core_transport(monkeypatch):
    import nvflare.fuel.f3.cellnet.core_cell as core_cell_module

    class BrokenAccounting:
        def __getattr__(self, _name):
            raise RuntimeError("accounting failed")

    cell = _core_cell()
    message = Message(headers={MessageHeaderKey.DESTINATION: "site-1"}, payload=b"payload")
    attach_logical_send_context(message, BrokenAccounting(), object())
    monkeypatch.setattr(core_cell_module, "encode_payload", lambda _message, fobs_ctx: 7)
    cell.encrypt_payload = MagicMock()

    assert cell._send_to_endpoint(Endpoint("site-1"), message) == ""
    cell.communicator.send.assert_called_once()


def test_context_exception_never_changes_core_transport(monkeypatch):
    import nvflare.fuel.f3.cellnet.core_cell as core_cell_module

    class BrokenContext:
        def is_origin(self, _origin):
            raise RuntimeError("context failed")

        def mark_counter_gap(self):
            raise RuntimeError("gap reporting also failed")

    cell = _core_cell()
    message = Message(headers={MessageHeaderKey.DESTINATION: "site-1"}, payload=b"payload")
    message.set_logical_send_context(BrokenContext())
    monkeypatch.setattr(core_cell_module, "encode_payload", lambda _message, fobs_ctx: 7)
    cell.encrypt_payload = MagicMock()

    assert cell._send_to_endpoint(Endpoint("site-1"), message) == ""
    cell.communicator.send.assert_called_once()


def test_terminal_accounting_exception_never_changes_core_transport(monkeypatch):
    import nvflare.fuel.f3.cellnet.core_cell as core_cell_module

    class BrokenAttempt:
        def accepted(self, _payload_bytes):
            raise RuntimeError("completion failed")

    context = MagicMock()
    context.is_origin.return_value = True
    context.try_begin.return_value = BrokenAttempt()
    cell = _core_cell()
    message = Message(headers={MessageHeaderKey.DESTINATION: "site-1"}, payload=b"payload")
    message.set_logical_send_context(context)
    monkeypatch.setattr(core_cell_module, "encode_payload", lambda _message, fobs_ctx: 7)
    cell.encrypt_payload = MagicMock()

    assert cell._send_to_endpoint(Endpoint("site-1"), message) == ""
    cell.communicator.send.assert_called_once()
    context.mark_counter_gap.assert_called_once()


def test_byte_streamer_accounts_one_whole_stream_at_terminal_success(monkeypatch):
    cell = SimpleNamespace(my_info=FqcnInfo("origin"))
    streamer = ByteStreamer.__new__(ByteStreamer)
    streamer.cell = cell
    streamer.chunk_size = 4
    counter = F3Counter()
    message = Message(payload=b"abcdef")
    context = attach_logical_send_context(message, counter, F3TrafficClass.TASK_RESULT)
    stream = BlobStream(message.payload, message.headers)

    def admit_task(task, _handler):
        task.task_future = object()

    monkeypatch.setattr(TxTask, "start_task_thread", admit_task)
    monkeypatch.setattr(ByteStreamer.sent_stream_counter_pool, "increment", lambda **_kwargs: None)
    monkeypatch.setattr(ByteStreamer.sent_stream_size_pool, "record_value", lambda **_kwargs: None)

    future = streamer.send(
        "channel",
        "topic",
        "site-1",
        message.headers,
        stream,
        STREAM_TYPE_BLOB,
        accounting_context=context,
    )
    with ByteStreamer.map_lock:
        ByteStreamer.tx_task_map.pop(future.stream_id, None)

    assert counter.pending_count == 1
    assert counter.snapshot()["remote_accepted"] == {"payload_bytes": "0", "messages": "0"}
    future.set_result(6)

    assert _counter_value(counter) == {"payload_bytes": "6", "messages": "1"}


@pytest.mark.parametrize("terminal", ("error", "cancel"))
def test_byte_streamer_abandons_accounting_on_async_failure_or_cancel(monkeypatch, terminal):
    from nvflare.fuel.f3.streaming.stream_types import StreamError

    cell = SimpleNamespace(my_info=FqcnInfo("origin"), ALL_CELLS={})
    streamer = ByteStreamer.__new__(ByteStreamer)
    streamer.cell = cell
    streamer.chunk_size = 4
    counter = F3Counter()
    context = attach_logical_send_context(Message(), counter, F3TrafficClass.TASK_RESULT)
    stream = BlobStream(b"abcdef", {})

    def admit_task(task, _handler):
        task.task_future = MagicMock()

    monkeypatch.setattr(TxTask, "start_task_thread", admit_task)
    monkeypatch.setattr(ByteStreamer.sent_stream_counter_pool, "increment", lambda **_kwargs: None)
    monkeypatch.setattr(ByteStreamer.sent_stream_size_pool, "record_value", lambda **_kwargs: None)

    future = streamer.send("channel", "topic", "site-1", {}, stream, accounting_context=context)
    with ByteStreamer.map_lock:
        ByteStreamer.tx_task_map.pop(future.stream_id, None)
    assert counter.pending_count == 1

    if terminal == "error":
        future.set_exception(StreamError("async send failed"))
    else:
        assert future.cancel()

    assert counter.pending_count == 0
    assert _counter_value(counter) == {"payload_bytes": "0", "messages": "0"}


def test_byte_streamer_excludes_direct_final_but_counts_remote_target_with_local_relay(monkeypatch):
    cell = SimpleNamespace(my_info=FqcnInfo("origin"), ALL_CELLS={"site-1": object(), "relay": object()})
    streamer = ByteStreamer.__new__(ByteStreamer)
    streamer.cell = cell
    streamer.chunk_size = 4
    direct_counter = F3Counter()
    direct_context = attach_logical_send_context(Message(), direct_counter, F3TrafficClass.TASK_RESULT)
    remote_counter = F3Counter()
    remote_context = attach_logical_send_context(Message(), remote_counter, F3TrafficClass.TASK_RESULT)

    def admit_task(task, _handler):
        task.task_future = object()

    monkeypatch.setattr(TxTask, "start_task_thread", admit_task)
    monkeypatch.setattr(ByteStreamer.sent_stream_counter_pool, "increment", lambda **_kwargs: None)
    monkeypatch.setattr(ByteStreamer.sent_stream_size_pool, "record_value", lambda **_kwargs: None)

    direct = streamer.send(
        "channel", "topic", "site-1", {}, BlobStream(b"local", {}), accounting_context=direct_context
    )
    remote = streamer.send(
        "channel", "topic", "site-2", {}, BlobStream(b"remote", {}), accounting_context=remote_context
    )
    with ByteStreamer.map_lock:
        ByteStreamer.tx_task_map.pop(direct.stream_id, None)
        ByteStreamer.tx_task_map.pop(remote.stream_id, None)
    direct.set_result(5)
    remote.set_result(6)

    assert _counter_value(direct_counter) == {"payload_bytes": "0", "messages": "0"}
    assert _counter_value(remote_counter) == {"payload_bytes": "6", "messages": "1"}


def test_context_exception_never_changes_byte_streamer_admission(monkeypatch):
    class BrokenContext:
        def try_begin(self, _origin, _destination):
            raise RuntimeError("context failed")

        def mark_counter_gap(self):
            raise RuntimeError("gap reporting also failed")

    cell = SimpleNamespace(my_info=FqcnInfo("origin"))
    streamer = ByteStreamer.__new__(ByteStreamer)
    streamer.cell = cell
    streamer.chunk_size = 4
    stream = BlobStream(b"abcdef", {})

    def admit_task(task, _handler):
        task.task_future = object()

    monkeypatch.setattr(TxTask, "start_task_thread", admit_task)
    monkeypatch.setattr(ByteStreamer.sent_stream_counter_pool, "increment", lambda **_kwargs: None)
    monkeypatch.setattr(ByteStreamer.sent_stream_size_pool, "record_value", lambda **_kwargs: None)

    future = streamer.send("channel", "topic", "site-1", {}, stream, accounting_context=BrokenContext())
    with ByteStreamer.map_lock:
        ByteStreamer.tx_task_map.pop(future.stream_id, None)

    assert future is not None


def test_terminal_accounting_exception_never_changes_byte_streamer_admission(monkeypatch):
    class BrokenAttempt:
        def accepted(self, _payload_bytes):
            raise RuntimeError("completion failed")

    context = MagicMock()
    context.try_begin.return_value = BrokenAttempt()
    cell = SimpleNamespace(my_info=FqcnInfo("origin"))
    streamer = ByteStreamer.__new__(ByteStreamer)
    streamer.cell = cell
    streamer.chunk_size = 4
    stream = BlobStream(b"abcdef", {})

    def admit_task(task, _handler):
        task.task_future = object()

    monkeypatch.setattr(TxTask, "start_task_thread", admit_task)
    monkeypatch.setattr(ByteStreamer.sent_stream_counter_pool, "increment", lambda **_kwargs: None)
    monkeypatch.setattr(ByteStreamer.sent_stream_size_pool, "record_value", lambda **_kwargs: None)

    future = streamer.send("channel", "topic", "site-1", {}, stream, accounting_context=context)
    with ByteStreamer.map_lock:
        ByteStreamer.tx_task_map.pop(future.stream_id, None)
    future.set_result(6)

    assert future is not None
    context.mark_counter_gap.assert_called_once()


def test_download_service_contribution_is_deduped_and_settled_after_transport_acceptance():
    service = make_isolated_download_service()
    counter = F3Counter()
    context = attach_logical_send_context(Message(), counter, F3TrafficClass.TASK_RESULT)
    tx_id = service.new_transaction(
        cell=MagicMock(),
        timeout=10.0,
        num_receivers=1,
        receiver_ids=("site-1",),
        send_accounting_context=context,
    )
    ref_id = service.add_object(tx_id, MockDownloadable([b"large-data"]))

    main = context.try_begin("origin", "site-1")
    assert main is not None
    main.accepted(4)
    first_reply = service._handle_download(pull_request(ref_id, "site-1"))
    retry_reply = service._handle_download(pull_request(ref_id, "site-1"))
    first_contribution = first_reply.get_logical_send_context()
    retry_contribution = retry_reply.get_logical_send_context()
    first_attempt = first_contribution.try_begin("origin", "site-1")
    assert retry_contribution.try_begin("origin", "site-1") is None

    eof_reply = service._handle_download(pull_request(ref_id, "site-1", state=first_reply.payload["state"]))
    assert eof_reply.payload["status"] == "eof"
    tx = service._tx_table[tx_id]
    tx.transaction_done(TransactionDoneStatus.FINISHED)
    assert counter.pending_count == 1

    first_attempt.accepted(9999)

    assert counter.pending_count == 0
    assert _counter_value(counter) == {"payload_bytes": "14", "messages": "1"}


def test_download_chunk_identity_canonicalizes_builtin_state_and_dedupes_retry():
    tx = _Transaction(timeout=10.0, num_receivers=1)
    ref = tx.add_object(MockDownloadable([b"data"]))

    first_state = {
        "nested": [None, True, 7, 1.25, b"bytes", bytearray(b"array"), memoryview(b"view")],
        "position": (3, {"phase": complex(2, -1)}),
    }
    reordered_equivalent_state = {
        "position": (3, {"phase": complex(2, -1)}),
        "nested": [None, True, 7, 1.25, b"bytes", bytearray(b"array"), memoryview(b"view")],
    }

    first_key = ref.accounting_chunk_key(first_state)
    retry_key = ref.accounting_chunk_key(reordered_equivalent_state)
    distinct_key = ref.accounting_chunk_key({"nested": tuple(first_state["nested"])})

    assert first_key == retry_key
    assert distinct_key != first_key
    assert len({first_key, retry_key, distinct_key}) == 2


def test_download_chunk_identity_rejects_unbounded_or_unsupported_state_without_allocating_ledger():
    from nvflare.fuel.f3.streaming import download_service as download_service_module

    tx = _Transaction(timeout=10.0, num_receivers=1)
    ref = tx.add_object(MockDownloadable([b"data"]))
    cyclic_state = []
    cyclic_state.append(cyclic_state)

    assert ref.accounting_chunk_key({"custom": object()}) is None
    assert ref.accounting_chunk_key(b"x" * (download_service_module._ACCOUNTING_STATE_MAX_SCALAR_BYTES + 1)) is None
    assert ref.accounting_chunk_key(cyclic_state) is None


def test_unaccounted_download_does_not_compute_a_chunk_identity(monkeypatch):
    from nvflare.fuel.f3.streaming import download_service as download_service_module

    canonicalize = MagicMock(side_effect=AssertionError("unaccounted download canonicalized state"))
    monkeypatch.setattr(download_service_module, "_canonical_accounting_state", canonicalize)
    service = make_isolated_download_service()
    tx_id = service.new_transaction(cell=MagicMock(), timeout=10.0, num_receivers=1)
    ref_id = service.add_object(tx_id, MockDownloadable([b"data"]))

    reply = service._handle_download(pull_request(ref_id, "site-1"))

    assert reply.payload["data"] == b"data"
    canonicalize.assert_not_called()


def test_unsupported_download_state_marks_f3_partial_without_changing_served_data():
    service = make_isolated_download_service()
    counter = F3Counter()
    context = attach_logical_send_context(Message(), counter, F3TrafficClass.TASK_RESULT)
    tx_id = service.new_transaction(
        cell=MagicMock(),
        timeout=10.0,
        num_receivers=1,
        receiver_ids=("site-1",),
        send_accounting_context=context,
    )
    ref_id = service.add_object(tx_id, MockDownloadable([b"data"]))
    main = context.try_begin("origin", "site-1")
    main.accepted(4)

    reply = service._handle_download(pull_request(ref_id, "site-1", state={"custom": object()}))

    assert reply.payload["data"] == b"data"
    assert reply.get_logical_send_context() is None
    snapshot = counter.freeze()
    assert snapshot["status"] == "partial"
    assert snapshot["issues"] == ["counter_gap"]
    assert snapshot["remote_accepted"] == {"payload_bytes": "0", "messages": "0"}


def test_large_download_chunk_identity_set_has_linear_size_without_prior_chunk_scans():
    """Exercise a realistic large ledger without a wall-clock assertion.

    LogicalSendContext uses a set of these keys. Its linear size and retry
    membership are the non-flaky complexity assertion: no per-ref history is
    scanned to create a later key.
    """

    tx = _Transaction(timeout=10.0, num_receivers=1)
    ref = tx.add_object(MockDownloadable([b"data"]))
    chunk_count = 20_000

    keys = set()
    for index in range(chunk_count):
        keys.add(ref.accounting_chunk_key({"received_bytes": index * 2 * 1024 * 1024}))

    assert len(keys) == chunk_count
    for index in (0, chunk_count // 2, chunk_count - 1):
        assert ref.accounting_chunk_key({"received_bytes": index * 2 * 1024 * 1024}) in keys


def test_download_service_accounting_callback_failures_do_not_change_serving_or_settlement():
    class BrokenContext:
        def __init__(self):
            self.gaps = 0

        def register_oob_transaction(self, _transaction_id, _receiver_ids):
            raise RuntimeError("registration failed")

        def make_oob_contribution_context(self, **_kwargs):
            raise RuntimeError("contribution failed")

        def mark_oob_incomplete(self, _destination):
            raise RuntimeError("incomplete failed")

        def settle_oob_transaction(self, _transaction_id, _successful_receivers):
            raise RuntimeError("settlement failed")

        def mark_counter_gap(self):
            self.gaps += 1

    service = make_isolated_download_service()
    context = BrokenContext()
    tx_id = service.new_transaction(
        cell=MagicMock(),
        timeout=10.0,
        num_receivers=1,
        receiver_ids=("site-1",),
        send_accounting_context=context,
    )
    ref_id = service.add_object(tx_id, MockDownloadable([b"data"]))

    reply = service._handle_download(pull_request(ref_id, "site-1"))
    assert reply.payload["data"] == b"data"
    assert reply.get_logical_send_context() is None
    tx = service._tx_table[tx_id]
    outcome = tx.transaction_done(TransactionDoneStatus.DELETED)

    assert outcome is not None
    assert tx._settlement_complete
    assert context.gaps >= 2
