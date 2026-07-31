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
from pathlib import Path
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("nvflare")

from research.llm_fl_stress.real_training.client import (  # noqa: E402
    _aggregate_training_evidence,
    _decoder_layers,
    _gradient_probe_evidence,
    _gradient_probe_parameters,
    _make_optimizer,
    _make_round_summary,
    _model_parameter_evidence,
    _optimizer_state_summary,
    _parameter_probe_change,
    _require_round_success,
    _round_metrics,
    _select_trainable_parameters,
    _snapshot_trainable,
    _training_text,
    _validate_args,
)


class TinyCausalLM(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.model = torch.nn.Module()
        self.model.layers = torch.nn.ModuleList([torch.nn.Linear(4, 4), torch.nn.Linear(4, 4), torch.nn.Linear(4, 4)])
        self.lm_head = torch.nn.Linear(4, 8, bias=False)
        self.is_gradient_checkpointing = False

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


def test_all_parameter_selection_and_evidence_are_explicit():
    model = TinyCausalLM()
    model.is_gradient_checkpointing = True

    selected = _select_trainable_parameters(model, "all")
    evidence = _model_parameter_evidence(model)

    assert selected == list(model.parameters())
    assert evidence == {
        "total_parameters": sum(param.numel() for param in model.parameters()),
        "trainable_parameters": sum(param.numel() for param in model.parameters()),
        "frozen_parameters": 0,
        "total_tensor_count": len(list(model.parameters())),
        "trainable_tensor_count": len(list(model.parameters())),
        "frozen_tensor_count": 0,
        "gradient_checkpointing_enabled": True,
    }


def test_parameter_snapshot_is_bounded_and_change_probe_is_fail_closed(monkeypatch):
    parameter = torch.nn.Parameter(torch.arange(4096, dtype=torch.float32))
    monkeypatch.setattr(torch.distributed, "all_reduce", lambda *_args, **_kwargs: None)

    before = _snapshot_trainable([parameter])
    unchanged = _parameter_probe_change([parameter], before, torch.device("cpu"))
    parameter.data[0] += 1.0
    changed = _parameter_probe_change([parameter], before, torch.device("cpu"))

    assert len(before) == 1
    assert before[0].numel() == 64
    assert unchanged["global_max_abs_change"] == 0.0
    assert unchanged["globally_changed_parameter_tensor_count"] == 0
    assert changed["global_max_abs_change"] == 1.0
    assert changed["globally_changed_parameter_tensor_count"] == 1
    assert changed["global_sampled_value_count"] == 64


def test_all_parameter_gradient_probes_span_decoder_depth(monkeypatch):
    model = TinyCausalLM()
    _select_trainable_parameters(model, "all")
    probes = _gradient_probe_parameters(model, "all")
    for _position, _layer_index, _name, parameter in probes:
        parameter.grad = torch.ones_like(parameter)
    monkeypatch.setattr(torch.distributed, "all_reduce", lambda *_args, **_kwargs: None)

    evidence = _gradient_probe_evidence(probes, torch.device("cpu"))

    assert [record["position"] for record in evidence] == ["early", "middle", "late"]
    assert [record["layer_index"] for record in evidence] == [0, 1, 2]
    assert all(record["finite"] and record["nonzero"] for record in evidence)
    assert all(record["global_l2_norm"] > 0.0 for record in evidence)


def test_optimizer_state_summary_reports_tensor_memory_and_dtype():
    layer = torch.nn.Linear(4, 4)
    optimizer = _make_optimizer(list(layer.parameters()), 1.0e-5)
    layer(torch.ones(1, 4)).sum().backward()
    optimizer.step()

    summary = _optimizer_state_summary(optimizer)

    assert summary["tensor_count"] == 6
    assert summary["tensor_numel"] == 42
    assert summary["tensor_bytes"] == 168
    assert summary["dtype_histogram"] == {
        "float32": {"tensor_count": 6, "numel": 42, "bytes": 168},
    }
    assert optimizer.defaults["foreach"] is False
    assert optimizer.defaults["fused"] is False


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
    args = Namespace(
        run_mode="train",
        trainable_target="last-layer",
        local_steps=1,
        max_length=128,
        model_name_or_path="/models/Qwen2.5-14B",
        model_revision="abc123",
        state_scope="full",
    )
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
        site_name="site-2",
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
        "site_name": "site-2",
        "model_path": "/models/Qwen2.5-14B",
        "model_revision": "abc123",
        "run_mode": "train",
        "state_scope": "full",
        "trainable_target": "last-layer",
        "local_steps": 1,
        "max_length": 128,
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


def test_rank_metrics_report_total_gpu_memory_and_reserved_headroom(monkeypatch):
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda _device: 400)
    monkeypatch.setattr(torch.cuda, "max_memory_reserved", lambda _device: 600)
    monkeypatch.setattr(torch.cuda, "get_device_properties", lambda _device: SimpleNamespace(total_memory=1000))
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda _device: "test-gpu")
    monkeypatch.setattr(torch.distributed, "get_world_size", lambda: 1)

    def gather(local, gathered, dst):
        assert dst == 0
        gathered[0] = local

    monkeypatch.setattr(torch.distributed, "gather_object", gather)

    _metrics, ranks = _round_metrics(
        rank=0,
        local_rank=0,
        device=torch.device("cpu"),
        loss=1.0,
        max_change=0.1,
        load_seconds=1.0,
        export_seconds=2.0,
        loss_trajectory=[1.0],
        sample_ids=["sample-0"],
    )

    assert ranks[0]["peak_gpu_reserved_bytes"] == 600
    assert ranks[0]["total_gpu_memory_bytes"] == 1000
    assert ranks[0]["reserved_headroom_bytes"] == 400


def test_received_full_state_is_released_before_training_starts():
    from research.llm_fl_stress.real_training import client

    source = Path(client.__file__).read_text(encoding="utf-8")
    run_source = source[source.index("def _run(args: argparse.Namespace)") :]

    load = run_source.index("load_result = bridge.load_full_state_dict(received_params)")
    release = run_source.index("input_model.params = None", load)
    training = run_source.index("_train_round(", load)

    assert load < release < training


def test_training_evidence_aggregation_keeps_rank_memory_separate():
    update_probe = {
        "strategy": "evenly-spaced-local-shard-values",
        "max_values_per_parameter_shard": 64,
        "parameter_tensor_count": 2,
        "global_sampled_value_count": 256,
        "globally_changed_parameter_tensor_count": 2,
        "global_max_abs_change": 0.001,
    }
    gradient_probes = [
        {
            "position": "early",
            "layer_index": 0,
            "parameter": "model.layers.0.weight",
            "global_l2_norm": 1.0,
            "finite": True,
            "nonzero": True,
        }
    ]
    rank_metrics = []
    for rank in (0, 1):
        rank_metrics.append(
            {
                "rank": rank,
                "training_evidence": {
                    "update_probe": update_probe,
                    "gradient_probes": gradient_probes,
                    "optimizer_state": {
                        "tensor_count": 3,
                        "tensor_numel": 21,
                        "tensor_bytes": 84,
                        "dtype_histogram": {
                            "float32": {"tensor_count": 3, "numel": 21, "bytes": 84},
                        },
                        "config": {
                            "name": "AdamW",
                            "learning_rate": 1.0e-5,
                            "foreach": False,
                            "fused": False,
                        },
                    },
                    "cuda_phases": [{"phase": "after_state_load", "allocated_bytes": rank + 1}],
                },
            }
        )

    evidence = _aggregate_training_evidence(rank_metrics)

    assert evidence["update_probe"] == update_probe
    assert evidence["gradient_probes"] == gradient_probes
    assert evidence["optimizer_state"]["global_tensor_count"] == 6
    assert evidence["optimizer_state"]["global_tensor_numel"] == 42
    assert evidence["optimizer_state"]["global_tensor_bytes"] == 168
    assert evidence["optimizer_state"]["global_dtype_histogram"] == {
        "float32": {"tensor_count": 6, "numel": 42, "bytes": 168},
    }
    assert [record["rank"] for record in evidence["cuda_phases"]] == [0, 1]
    json.dumps(evidence)


def test_training_evidence_aggregation_rejects_rank_optimizer_config_mismatch():
    rank_metrics = []
    for rank, foreach in ((0, False), (1, True)):
        rank_metrics.append(
            {
                "rank": rank,
                "training_evidence": {
                    "update_probe": {},
                    "gradient_probes": [],
                    "optimizer_state": {
                        "tensor_count": 1,
                        "tensor_numel": 1,
                        "tensor_bytes": 2,
                        "dtype_histogram": {"bfloat16": {"tensor_count": 1, "numel": 1, "bytes": 2}},
                        "config": {"name": "AdamW", "foreach": foreach, "fused": False},
                    },
                    "cuda_phases": [],
                },
            }
        )

    with pytest.raises(RuntimeError, match="different optimizer configuration"):
        _aggregate_training_evidence(rank_metrics)


def test_training_text_is_stable_and_distinguishes_two_clients():
    assert _training_text("site-1", 0) == _training_text("site-1", 0)
    assert _training_text("site-1", 0) != _training_text("site-2", 0)
    assert _training_text("site-1", 0) != _training_text("site-1", 1)


def test_flare_session_initializes_before_heavy_model_loading(monkeypatch):
    from research.llm_fl_stress.real_training import client

    events = []
    args = Namespace(timeout_seconds=2400)
    monkeypatch.setattr(
        client,
        "_setup_distributed",
        lambda _timeout: (0, 4, 0, torch.device("cpu")),
    )
    monkeypatch.setattr(client.flare, "init", lambda *, rank: events.append(("flare.init", rank)))

    def fail_after_recording(_args):
        events.append(("load_model", None))
        raise RuntimeError("stop after startup-order observation")

    monkeypatch.setattr(client, "_load_model_and_tokenizer", fail_after_recording)
    monkeypatch.setattr(client.dist, "is_initialized", lambda: False)

    with pytest.raises(RuntimeError, match="startup-order observation"):
        client._run(args)

    assert events == [("flare.init", 0), ("load_model", None)]


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
