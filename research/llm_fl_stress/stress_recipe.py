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

"""Stress-harness extensions to the public FedAvg recipe surface."""

from nvflare.app_opt.pt.recipes.fedavg import FedAvgRecipe
from nvflare.widgets.widget import Widget


class StressFedAvgRecipe(FedAvgRecipe):
    def add_server_observer(self, observer: Widget, observer_id: str = "stress_resource_observer") -> None:
        self.job.to_server(observer, id=observer_id)
