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

import json
import signal
from argparse import Namespace
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("nvflare")

from research.llm_fl_stress.real_training.client import (  # noqa: E402
    _decoder_layers,
    _make_round_summary,
    _require_round_success,
    _select_trainable_parameters,
    _validate_args,
)


class TinyCausalLM(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.model = torch.nn.Module()
        self.model.layers = torch.nn.ModuleList([torch.nn.Linear(4, 4), torch.nn.Linear(4, 4)])
        self.lm_head = torch.nn.Linear(4, 8, bias=False)

    def get_output_embeddings(self):
        return self.lm_head


def test_last_layer_selection_freezes_every_other_parameter():
    model = TinyCausalLM()

    selected = _select_trainable_parameters(model, "last-layer")

    assert selected
    assert all(param.requires_grad for param in model.model.layers[-1].parameters())
    assert not any(param.requires_grad for param in model.model.layers[0].parameters())
    assert not any(param.requires_grad for param in model.lm_head.parameters())


def test_lm_head_selection_only_unfreezes_output_embeddings():
    model = TinyCausalLM()

    selected = _select_trainable_parameters(model, "lm-head")

    assert selected == list(model.lm_head.parameters())
    assert all(param.requires_grad for param in model.lm_head.parameters())
    assert not any(param.requires_grad for param in model.model.layers.parameters())


def test_unsupported_architecture_is_rejected():
    model = torch.nn.Linear(4, 4)
    model.config = SimpleNamespace(model_type="tiny-unsupported")

    with pytest.raises(RuntimeError, match="tiny-unsupported"):
        _decoder_layers(model)


def test_client_validation_requires_local_absolute_model_dir(tmp_path):
    args = Namespace(
        model_name_or_path=str(tmp_path),
        local_steps=1,
        max_length=128,
        timeout_seconds=60,
        learning_rate=1.0e-5,
    )

    _validate_args(args)

    args.model_name_or_path = "Qwen/Qwen2.5-14B"
    with pytest.raises(ValueError, match="absolute local path"):
        _validate_args(args)


def test_distributed_round_error_fails_closed():
    with pytest.raises(RuntimeError, match="distributed round failed: rank 2 train: CUDA out of memory"):
        _require_round_success("rank 2 train: CUDA out of memory")

    _require_round_success(None)


def test_round_summary_exposes_training_and_rank_metrics():
    args = Namespace(run_mode="train", trainable_target="last-layer", local_steps=1)
    metrics = {
        "loss": 1.25,
        "neg_loss": -1.25,
        "selected_max_abs_change": 0.0001,
        "load_seconds": 2.0,
        "export_seconds": 3.0,
    }
    ranks = [{"rank": 0, "peak_gpu_allocated_bytes": 1024}]

    summary = _make_round_summary(
        current_round=0,
        args=args,
        world_size=4,
        metrics=metrics,
        rank_metrics=ranks,
        payload_bytes=3554202488,
        tensor_count=339,
        round_seconds=8.0,
    )

    assert summary == {
        "event": "real_training_round",
        "status": "PASS",
        "current_round": 0,
        "run_mode": "train",
        "trainable_target": "last-layer",
        "local_steps": 1,
        "world_size": 4,
        "loss": 1.25,
        "selected_max_abs_change": 0.0001,
        "load_seconds": 2.0,
        "export_seconds": 3.0,
        "payload_bytes": 3554202488,
        "tensor_count": 339,
        "round_seconds": 8.0,
        "ranks": ranks,
    }
    json.dumps(summary)


def test_sigterm_handler_uses_failure_exit_code(monkeypatch, tmp_path):
    from research.llm_fl_stress.real_training import client

    handlers = {}
    args = Namespace(
        model_name_or_path=str(tmp_path),
        local_steps=1,
        max_length=128,
        timeout_seconds=60,
        learning_rate=1.0e-5,
    )
    monkeypatch.setattr(client, "_parse_args", lambda: args)
    monkeypatch.setattr(client.signal, "signal", lambda signum, handler: handlers.setdefault(signum, handler))

    def invoke_handler(_args):
        handlers[signal.SIGTERM](signal.SIGTERM, None)

    monkeypatch.setattr(client, "_run", invoke_handler)

    with pytest.raises(SystemExit) as exc_info:
        client.main()

    assert exc_info.value.code == 143
