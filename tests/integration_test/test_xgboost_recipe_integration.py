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

"""Integration tests for XGBoost bagging recipe.

These tests verify recipe configuration and validation without requiring XGBoost installation.
"""

import pytest

from nvflare.app_opt.xgboost.recipes.bagging import XGBBaggingRecipe


class TestXGBoostRecipeIntegration:
    """Integration tests for XGBoost bagging recipe."""

    def test_random_forest_recipe_configuration(self):
        """Test end-to-end Random Forest recipe configuration."""
        n_clients = 5
        recipe = XGBBaggingRecipe(
            name="random_forest_test",
            min_clients=n_clients,
            num_rounds=1,
            num_client_bagging=n_clients,
            num_local_parallel_tree=5,
            local_subsample=0.5,
            learning_rate=0.1,
            max_depth=8,
            objective="binary:logistic",
            eval_metric="auc",
            tree_method="hist",
            use_gpus=False,
            nthread=16,
            lr_mode="uniform",
        )

        # Verify all parameters are correctly set
        assert recipe.name == "random_forest_test"
        assert recipe.min_clients == n_clients
        assert recipe.num_client_bagging == n_clients
        assert recipe.num_local_parallel_tree == 5
        assert recipe.local_subsample == 0.5
        assert recipe.lr_mode == "uniform"

    def test_recipe_with_scaled_learning_rate(self):
        """Test recipe configuration with scaled learning rate mode."""
        recipe = XGBBaggingRecipe(
            name="rf_scaled_lr",
            min_clients=5,
            num_rounds=1,
            num_client_bagging=5,
            lr_mode="scaled",
        )
        assert recipe.lr_mode == "scaled"

    def test_recipe_with_gpu_configuration(self):
        """Test recipe configuration for GPU training."""
        recipe = XGBBaggingRecipe(
            name="rf_gpu",
            min_clients=3,
            num_rounds=1,
            num_client_bagging=3,
            use_gpus=True,
            tree_method="hist",
        )
        assert recipe.use_gpus is True
        assert recipe.tree_method == "hist"

    def test_recipe_with_different_objectives(self):
        """Test recipe with different XGBoost objectives."""
        objectives = ["binary:logistic", "reg:squarederror", "multi:softmax"]

        for objective in objectives:
            recipe = XGBBaggingRecipe(
                name=f"rf_{objective.replace(':', '_')}",
                min_clients=3,
                num_rounds=1,
                num_client_bagging=3,
                objective=objective,
            )
            assert recipe.objective == objective

    def test_recipe_parameter_validation_enforced(self):
        """Test that recipe validation catches configuration errors."""
        # Test num_client_bagging < min_clients
        with pytest.raises(ValueError, match="num_client_bagging must be >= min_clients"):
            XGBBaggingRecipe(
                name="invalid_bagging",
                min_clients=5,
                num_rounds=1,
                num_client_bagging=3,
            )

        # Test invalid subsample
        with pytest.raises(ValueError):
            XGBBaggingRecipe(
                name="invalid_subsample",
                min_clients=3,
                num_rounds=1,
                num_client_bagging=3,
                local_subsample=1.5,
            )

        # Test invalid lr_mode
        with pytest.raises(ValueError, match="lr_mode must be either 'uniform' or 'scaled'"):
            XGBBaggingRecipe(
                name="invalid_lr_mode",
                min_clients=3,
                num_rounds=1,
                num_client_bagging=3,
                lr_mode="invalid",
            )

    def test_recipe_with_varying_client_counts(self):
        """Test recipe configuration with different client counts."""
        for n_clients in [2, 5, 10, 20]:
            recipe = XGBBaggingRecipe(
                name=f"rf_{n_clients}clients",
                min_clients=n_clients,
                num_rounds=1,
                num_client_bagging=n_clients,
            )
            assert recipe.min_clients == n_clients
            assert recipe.num_client_bagging == n_clients

    def test_recipe_with_custom_tree_parameters(self):
        """Test recipe with various tree hyperparameters."""
        recipe = XGBBaggingRecipe(
            name="rf_custom_tree",
            min_clients=3,
            num_rounds=1,
            num_client_bagging=3,
            num_local_parallel_tree=10,
            max_depth=12,
            learning_rate=0.05,
            local_subsample=0.7,
        )
        assert recipe.num_local_parallel_tree == 10
        assert recipe.max_depth == 12
        assert recipe.learning_rate == 0.05
        assert recipe.local_subsample == 0.7
