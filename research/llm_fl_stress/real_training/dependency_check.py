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

"""Validate pinned dependencies without forcing heavy imports when metadata is sufficient."""

import argparse
import importlib.metadata
import importlib.util
import json
import os
import sys
from pathlib import Path

PINNED_DISTRIBUTIONS = {
    "torch": "2.12.0+cu126",
    "torchvision": "0.27.0+cu126",
    "transformers": "4.57.6",
}


def metadata_check(expected_source_root: Path, expected_prefix: Path) -> dict:
    """Check the environment and import resolution without executing third-party packages."""

    expected_source_root = expected_source_root.resolve()
    expected_prefix = expected_prefix.resolve()
    expected_init = (expected_source_root / "nvflare" / "__init__.py").resolve()
    pythonpath = os.environ.get("PYTHONPATH")
    configured_source_root = os.environ.get("NVFLARE_EXPECTED_SOURCE_ROOT")
    if pythonpath != str(expected_source_root):
        raise RuntimeError(f"PYTHONPATH is {pythonpath!r}, expected {str(expected_source_root)!r}")
    if configured_source_root != str(expected_source_root):
        raise RuntimeError(
            f"NVFLARE_EXPECTED_SOURCE_ROOT is {configured_source_root!r}, expected {str(expected_source_root)!r}"
        )
    observed_prefix = Path(sys.prefix).resolve()
    if observed_prefix != expected_prefix:
        raise RuntimeError(f"Python prefix is {observed_prefix}, expected {expected_prefix}")
    spec = importlib.util.find_spec("nvflare")
    observed_init = Path(spec.origin).resolve() if spec and spec.origin else None
    if observed_init != expected_init:
        raise RuntimeError(f"NVFLARE resolves to {observed_init}, expected {expected_init}")
    versions = {name: importlib.metadata.version(name) for name in PINNED_DISTRIBUTIONS}
    if versions != PINNED_DISTRIBUTIONS:
        raise RuntimeError(f"dependency metadata mismatch: expected {PINNED_DISTRIBUTIONS}, observed {versions}")
    return {
        "event": "real_training_dependency_check",
        "status": "PASS",
        "mode": "metadata-only",
        "python_executable": sys.executable,
        "python_prefix": str(observed_prefix),
        "nvflare_source_root": str(expected_source_root),
        "nvflare_init": str(observed_init),
        "versions": versions,
    }


def full_check() -> dict:
    """Import and exercise the pinned distributed APIs for legacy preparation jobs."""

    import torch
    import torchvision
    import transformers
    from torch.distributed.checkpoint.state_dict import StateDictOptions, get_model_state_dict, set_model_state_dict
    from torch.distributed.fsdp import MixedPrecisionPolicy, fully_shard
    from transformers.models.qwen2.modeling_qwen2 import Qwen2ForCausalLM

    import nvflare
    from nvflare.app_opt.pt.fsdp2_state_bridge import FSDP2StateBridge

    required_apis = (
        StateDictOptions,
        get_model_state_dict,
        set_model_state_dict,
        MixedPrecisionPolicy,
        fully_shard,
        FSDP2StateBridge,
        Qwen2ForCausalLM,
    )
    if not all(required_apis):
        raise RuntimeError("one or more required FSDP2 state APIs are unavailable")
    if not torch.__version__.startswith("2.12.0"):
        raise RuntimeError(f"expected PyTorch 2.12.0, got {torch.__version__}")
    if torch.version.cuda != "12.6":
        raise RuntimeError(f"expected a cu126 PyTorch build, got torch.version.cuda={torch.version.cuda!r}")
    if not torchvision.__version__.startswith("0.27.0+cu126"):
        raise RuntimeError(f"expected torchvision 0.27.0+cu126, got {torchvision.__version__}")
    if not hasattr(torch.ops.torchvision, "nms"):
        raise RuntimeError("torchvision compiled operators did not register torchvision::nms")
    if transformers.__version__ != "4.57.6":
        raise RuntimeError(f"expected Transformers 4.57.6, got {transformers.__version__}")
    nvflare_source_root = Path(nvflare.__file__).resolve().parents[1]
    expected_source_root = os.environ.get("NVFLARE_EXPECTED_SOURCE_ROOT")
    if expected_source_root and nvflare_source_root != Path(expected_source_root).resolve():
        raise RuntimeError(
            f"NVFLARE imported from {nvflare_source_root}, expected immutable source {Path(expected_source_root).resolve()}"
        )
    return {
        "event": "real_training_dependency_check",
        "status": "PASS",
        "mode": "full-import",
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "torchvision_version": torchvision.__version__,
        "transformers_version": transformers.__version__,
        "qwen2_model_class": Qwen2ForCausalLM.__name__,
        "nvflare_version": nvflare.__version__,
        "nvflare_source_root": str(nvflare_source_root),
        "expected_nvflare_source_root": str(Path(expected_source_root).resolve()) if expected_source_root else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--expected-source-root", type=Path)
    parser.add_argument("--expected-prefix", type=Path)
    args = parser.parse_args()
    if args.metadata_only:
        if args.expected_source_root is None or args.expected_prefix is None:
            parser.error("--metadata-only requires --expected-source-root and --expected-prefix")
        result = metadata_check(args.expected_source_root, args.expected_prefix)
    else:
        result = full_check()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
