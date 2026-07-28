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

"""Tiny NumPy client used to qualify real two-client runner synchronization."""

import json

import numpy as np

import nvflare.client as flare
from nvflare.app_common.np.constants import NPConstants


def main() -> None:
    flare.init()
    site_name = flare.get_site_name()
    while flare.is_running():
        input_model = flare.receive()
        if input_model is None:
            break
        input_array = np.asarray(input_model.params[NPConstants.NUMPY_KEY])
        output_array = input_array + 1
        print(
            json.dumps(
                {
                    "current_round": input_model.current_round,
                    "event": "real_training_control_plane_round",
                    "site_name": site_name,
                    "status": "PASS",
                },
                sort_keys=True,
            ),
            flush=True,
        )
        flare.send(
            flare.FLModel(
                params={NPConstants.NUMPY_KEY: output_array},
                params_type=flare.ParamsType.FULL,
                metrics={"smoke_metric": float(output_array.mean())},
                current_round=input_model.current_round,
            )
        )


if __name__ == "__main__":
    main()
