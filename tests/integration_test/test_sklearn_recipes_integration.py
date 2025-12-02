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

"""Integration tests for sklearn recipes.

These tests verify that recipes can be properly configured and jobs generated,
without requiring actual data or execution.
"""

from nvflare.app_opt.sklearn import SklearnFedAvgRecipe
from nvflare.app_opt.sklearn.recipes.kmeans import KMeansFedAvgRecipe
from nvflare.app_opt.sklearn.recipes.svm import SVMFedAvgRecipe


class TestSklearnRecipesIntegration:
    """Integration tests for sklearn recipes."""

    def test_sklearn_linear_recipe_with_per_client_args(self):
        """Test end-to-end configuration of linear model recipe with per-client data splits."""
        n_clients = 3
        train_args = {
            f"site-{i+1}": f"--data_path /tmp/data.csv --train_start {i*100} --train_end {(i+1)*100}"
            for i in range(n_clients)
        }

        recipe = SklearnFedAvgRecipe(
            name="sklearn_linear_integration",
            min_clients=n_clients,
            num_rounds=10,
            model_params={
                "n_classes": 2,
                "learning_rate": "constant",
                "eta0": 1e-4,
                "loss": "log_loss",
            },
            train_script="client.py",
            train_args=train_args,
        )

        # Verify recipe is properly configured
        assert recipe.name == "sklearn_linear_integration"
        assert len(recipe.train_args) == n_clients
        assert all(f"site-{i+1}" in recipe.train_args for i in range(n_clients))
        assert all("--train_start" in args for args in recipe.train_args.values())

    def test_kmeans_recipe_with_per_client_args(self):
        """Test end-to-end configuration of K-Means recipe with per-client data splits."""
        n_clients = 3
        train_args = {
            f"site-{i+1}": f"--data_path /tmp/iris.csv --train_start {i*40} --train_end {(i+1)*40}"
            for i in range(n_clients)
        }

        recipe = KMeansFedAvgRecipe(
            name="kmeans_integration",
            min_clients=n_clients,
            num_rounds=5,
            n_clusters=3,
            train_script="client.py",
            train_args=train_args,
        )

        # Verify recipe is properly configured
        assert recipe.name == "kmeans_integration"
        assert recipe.n_clusters == 3
        assert len(recipe.train_args) == n_clients

    def test_svm_recipe_with_all_kernels(self):
        """Test SVM recipe configuration with all supported kernels."""
        kernels = ["linear", "poly", "rbf", "sigmoid"]
        n_clients = 3

        for kernel in kernels:
            train_args = {
                f"site-{i+1}": f"--data_path /tmp/cancer.csv --train_start {i*150} --train_end {(i+1)*150}"
                for i in range(n_clients)
            }

            recipe = SVMFedAvgRecipe(
                name=f"svm_integration_{kernel}",
                min_clients=n_clients,
                kernel=kernel,
                train_script="client.py",
                train_args=train_args,
            )

            # Verify recipe is properly configured
            assert recipe.name == f"svm_integration_{kernel}"
            assert recipe.kernel == kernel
            assert len(recipe.train_args) == n_clients

    def test_svm_recipe_with_both_backends(self):
        """Test SVM recipe configuration with different backends."""
        backends = ["sklearn", "cuml"]
        n_clients = 3

        for backend in backends:
            train_args = {
                f"site-{i+1}": f"--data_path /tmp/cancer.csv --backend {backend} --train_start {i*150}"
                for i in range(n_clients)
            }

            recipe = SVMFedAvgRecipe(
                name=f"svm_integration_{backend}",
                min_clients=n_clients,
                backend=backend,
                train_script="client.py",
                train_args=train_args,
            )

            # Verify recipe is properly configured
            assert recipe.backend == backend
            assert all(f"--backend {backend}" in args for args in recipe.train_args.values())

    def test_recipe_with_shared_train_args(self):
        """Test that recipes can use shared train_args (single string) across all clients."""
        shared_args = "--data_path /tmp/shared_data.csv"

        # Test with linear model
        recipe_linear = SklearnFedAvgRecipe(
            name="sklearn_linear_shared",
            min_clients=3,
            num_rounds=10,
            train_script="client.py",
            train_args=shared_args,
        )
        assert recipe_linear.train_args == shared_args

        # Test with K-Means
        recipe_kmeans = KMeansFedAvgRecipe(
            name="kmeans_shared",
            min_clients=3,
            num_rounds=5,
            n_clusters=3,
            train_script="client.py",
            train_args=shared_args,
        )
        assert recipe_kmeans.train_args == shared_args

        # Test with SVM
        recipe_svm = SVMFedAvgRecipe(
            name="svm_shared",
            min_clients=3,
            train_script="client.py",
            train_args=shared_args,
        )
        assert recipe_svm.train_args == shared_args

    def test_recipe_configurations_are_independent(self):
        """Test that multiple recipe instances don't interfere with each other."""
        recipe1 = SklearnFedAvgRecipe(
            name="recipe1",
            min_clients=3,
            num_rounds=10,
            train_script="client.py",
            train_args="--data_path /path1",
        )

        recipe2 = SklearnFedAvgRecipe(
            name="recipe2",
            min_clients=5,
            num_rounds=20,
            train_script="client.py",
            train_args="--data_path /path2",
        )

        # Verify they are independent
        assert recipe1.name != recipe2.name
        assert recipe1.min_clients != recipe2.min_clients
        assert recipe1.num_rounds != recipe2.num_rounds
        assert recipe1.train_args != recipe2.train_args
