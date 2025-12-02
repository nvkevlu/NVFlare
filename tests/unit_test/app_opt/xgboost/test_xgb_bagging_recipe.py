# Copyright (c) 2025, NVIDIA CORPORATION.  All rights reserved.
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

"""Unit tests for XGBoost Bagging Recipe."""

import pytest

from nvflare.app_opt.xgboost.recipes.bagging import XGBBaggingRecipe


class TestXGBBaggingRecipe:
    """Tests for XGBBaggingRecipe."""

    def test_recipe_creation_with_defaults(self):
        """Test creating recipe with default parameters."""
        recipe = XGBBaggingRecipe(
            name="test_xgb",
            min_clients=3,
            num_rounds=1,
            num_client_bagging=3,
        )
        assert recipe.name == "test_xgb"
        assert recipe.min_clients == 3
        assert recipe.num_rounds == 1

    def test_recipe_with_custom_xgboost_params(self):
        """Test recipe with custom XGBoost parameters."""
        recipe = XGBBaggingRecipe(
            name="test_xgb",
            min_clients=5,
            num_rounds=1,
            num_client_bagging=5,
            num_local_parallel_tree=10,
            local_subsample=0.8,
            learning_rate=0.2,
            max_depth=10,
            objective="binary:logistic",
            eval_metric="auc",
        )
        assert recipe.num_local_parallel_tree == 10
        assert recipe.local_subsample == 0.8
        assert recipe.learning_rate == 0.2
        assert recipe.max_depth == 10

    def test_recipe_with_gpu_support(self):
        """Test recipe with GPU configuration."""
        recipe = XGBBaggingRecipe(
            name="test_xgb_gpu",
            min_clients=3,
            num_rounds=1,
            num_client_bagging=3,
            use_gpus=True,
            tree_method="hist",
        )
        assert recipe.use_gpus is True
        assert recipe.tree_method == "hist"

    def test_recipe_num_client_bagging_default(self):
        """Test that num_client_bagging defaults to min_clients when not provided."""
        recipe = XGBBaggingRecipe(
            name="test_xgb",
            min_clients=5,
            num_rounds=1,
        )
        # num_client_bagging should default to min_clients
        assert recipe.num_client_bagging == 5

    def test_recipe_validation_subsample_range(self):
        """Test that subsample ratio validation works."""
        # Valid subsample values
        for subsample in [0.1, 0.5, 0.8, 1.0]:
            recipe = XGBBaggingRecipe(
                name="test_xgb",
                min_clients=3,
                num_rounds=1,
                num_client_bagging=3,
                local_subsample=subsample,
            )
            assert recipe.local_subsample == subsample

        # Invalid subsample values
        with pytest.raises(ValueError, match="local_subsample must be between 0 and 1"):
            XGBBaggingRecipe(
                name="test_xgb",
                min_clients=3,
                num_rounds=1,
                num_client_bagging=3,
                local_subsample=1.5,  # > 1.0
            )

        with pytest.raises(ValueError, match="local_subsample must be between 0 and 1"):
            XGBBaggingRecipe(
                name="test_xgb",
                min_clients=3,
                num_rounds=1,
                num_client_bagging=3,
                local_subsample=0.0,  # <= 0
            )

    def test_recipe_with_lr_modes(self):
        """Test recipe with different learning rate modes."""
        for lr_mode in ["uniform", "scaled"]:
            recipe = XGBBaggingRecipe(
                name=f"test_xgb_{lr_mode}",
                min_clients=3,
                num_rounds=1,
                num_client_bagging=3,
                lr_mode=lr_mode,
            )
            assert recipe.lr_mode == lr_mode

    def test_recipe_validation_invalid_lr_mode(self):
        """Test that invalid lr_mode raises error."""
        with pytest.raises(ValueError, match="lr_mode must be 'uniform' or 'scaled'"):
            XGBBaggingRecipe(
                name="test_xgb",
                min_clients=3,
                num_rounds=1,
                num_client_bagging=3,
                lr_mode="invalid_mode",
            )
