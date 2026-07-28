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

"""Instantiate and validate the sparse trainable-state server model without a GPU."""

from __future__ import annotations

import argparse
import json

from model import HFTrainableStateModel
from state_evidence import tensor_state_summary

_PAYLOAD_CEILING_BYTES = 1024 * 1024 * 1024


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name-or-path", required=True)
    parser.add_argument("--model-revision", required=True)
    args = parser.parse_args()

    model = HFTrainableStateModel(args.model_name_or_path, revision=args.model_revision)
    state = model.state_dict()
    if not all(key.startswith("model.model.layers.") for key in state):
        raise RuntimeError(f"sparse server model contains unexpected keys: {sorted(state)}")
    summary = tensor_state_summary(state)
    if summary["payload_bytes"] > _PAYLOAD_CEILING_BYTES:
        raise RuntimeError(f"sparse server payload {summary['payload_bytes']} exceeds ceiling {_PAYLOAD_CEILING_BYTES}")
    print(
        json.dumps(
            {
                "event": "real_training_trainable_server_preflight",
                "status": "PASS",
                "model_path": args.model_name_or_path,
                "model_revision": args.model_revision,
                "state": summary,
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
