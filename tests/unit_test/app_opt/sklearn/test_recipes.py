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

"""Unit tests for sklearn recipes."""

import pytest

from nvflare.app_opt.sklearn import SklearnFedAvgRecipe
from nvflare.app_opt.sklearn.recipes.kmeans import KMeansFedAvgRecipe
from nvflare.app_opt.sklearn.recipes.svm import SVMFedAvgRecipe


class TestSklearnFedAvgRecipe:
    """Tests for SklearnFedAvgRecipe."""

    def test_recipe_creation_with_defaults(self, tmp_path):
        """Test creating recipe with default parameters."""
        # Create a dummy client script
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        recipe = SklearnFedAvgRecipe(
            name="test_sklearn",
            min_clients=3,
            num_rounds=10,
            train_script=str(client_script),
        )
        assert recipe.name == "test_sklearn"
        assert recipe.min_clients == 3
        assert recipe.num_rounds == 10

    def test_recipe_with_string_train_args(self, tmp_path):
        """Test recipe with single string train_args (shared across clients)."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        recipe = SklearnFedAvgRecipe(
            name="test_sklearn",
            min_clients=3,
            num_rounds=10,
            train_script=str(client_script),
            train_args="--data_path /tmp/data.csv",
        )
        assert recipe.train_args == "--data_path /tmp/data.csv"

    def test_recipe_with_dict_train_args(self, tmp_path):
        """Test recipe with per-client train_args dictionary."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        train_args = {
            "site-1": "--data_path /tmp/data.csv --train_start 0 --train_end 100",
            "site-2": "--data_path /tmp/data.csv --train_start 100 --train_end 200",
            "site-3": "--data_path /tmp/data.csv --train_start 200 --train_end 300",
        }
        recipe = SklearnFedAvgRecipe(
            name="test_sklearn",
            min_clients=3,
            num_rounds=10,
            train_script=str(client_script),
            train_args=train_args,
        )
        assert recipe.train_args == train_args
        assert "site-1" in recipe.train_args
        assert "--train_start 0" in recipe.train_args["site-1"]

    def test_recipe_with_model_params(self, tmp_path):
        """Test recipe with model hyperparameters."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        model_params = {
            "n_classes": 2,
            "learning_rate": "constant",
            "eta0": 1e-4,
            "loss": "log_loss",
        }
        recipe = SklearnFedAvgRecipe(
            name="test_sklearn",
            min_clients=3,
            num_rounds=10,
            train_script=str(client_script),
            model_params=model_params,
        )
        assert recipe.model_params == model_params

    def test_recipe_with_none_model_params(self, tmp_path):
        """Test recipe with None model_params."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        recipe = SklearnFedAvgRecipe(
            name="test_sklearn",
            min_clients=3,
            num_rounds=10,
            train_script=str(client_script),
            model_params=None,
        )
        assert recipe.model_params is None


class TestKMeansFedAvgRecipe:
    """Tests for KMeansFedAvgRecipe."""

    def test_recipe_creation_with_defaults(self, tmp_path):
        """Test creating K-Means recipe with default parameters."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        recipe = KMeansFedAvgRecipe(
            name="test_kmeans",
            min_clients=3,
            num_rounds=5,
            n_clusters=3,
            train_script=str(client_script),
        )
        assert recipe.name == "test_kmeans"
        assert recipe.min_clients == 3
        assert recipe.num_rounds == 5
        assert recipe.n_clusters == 3

    def test_recipe_with_dict_train_args(self, tmp_path):
        """Test K-Means recipe with per-client train_args."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        train_args = {
            "site-1": "--data_path /tmp/iris.csv --train_start 0 --train_end 50",
            "site-2": "--data_path /tmp/iris.csv --train_start 50 --train_end 100",
            "site-3": "--data_path /tmp/iris.csv --train_start 100 --train_end 120",
        }
        recipe = KMeansFedAvgRecipe(
            name="test_kmeans",
            min_clients=3,
            num_rounds=5,
            n_clusters=3,
            train_script=str(client_script),
            train_args=train_args,
        )
        assert recipe.train_args == train_args

    def test_recipe_with_different_cluster_counts(self, tmp_path):
        """Test K-Means recipe with various cluster counts."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        for n_clusters in [2, 3, 5, 10]:
            recipe = KMeansFedAvgRecipe(
                name=f"test_kmeans_{n_clusters}",
                min_clients=3,
                num_rounds=5,
                n_clusters=n_clusters,
                train_script=str(client_script),
            )
            assert recipe.n_clusters == n_clusters


class TestSVMFedAvgRecipe:
    """Tests for SVMFedAvgRecipe."""

    def test_recipe_creation_with_defaults(self, tmp_path):
        """Test creating SVM recipe with default parameters."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        recipe = SVMFedAvgRecipe(
            name="test_svm",
            min_clients=3,
            train_script=str(client_script),
        )
        assert recipe.name == "test_svm"
        assert recipe.min_clients == 3
        assert recipe.kernel == "rbf"  # default kernel
        assert recipe.backend == "sklearn"  # default backend

    def test_recipe_with_valid_kernels(self, tmp_path):
        """Test SVM recipe with all valid kernel types."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        valid_kernels = ["linear", "poly", "rbf", "sigmoid"]
        for kernel in valid_kernels:
            recipe = SVMFedAvgRecipe(
                name=f"test_svm_{kernel}",
                min_clients=3,
                train_script=str(client_script),
                kernel=kernel,
            )
            assert recipe.kernel == kernel

    def test_recipe_with_invalid_kernel_raises_error(self, tmp_path):
        """Test that invalid kernel raises validation error."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        with pytest.raises(ValueError, match="Input should be 'linear', 'poly', 'rbf' or 'sigmoid'"):
            SVMFedAvgRecipe(
                name="test_svm",
                min_clients=3,
                train_script=str(client_script),
                kernel="invalid_kernel",
            )

    def test_recipe_with_valid_backends(self, tmp_path):
        """Test SVM recipe with valid backend types."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        valid_backends = ["sklearn", "cuml"]
        for backend in valid_backends:
            recipe = SVMFedAvgRecipe(
                name=f"test_svm_{backend}",
                min_clients=3,
                train_script=str(client_script),
                backend=backend,
            )
            assert recipe.backend == backend

    def test_recipe_with_invalid_backend_raises_error(self, tmp_path):
        """Test that invalid backend raises validation error."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        with pytest.raises(ValueError, match="Input should be 'sklearn' or 'cuml'"):
            SVMFedAvgRecipe(
                name="test_svm",
                min_clients=3,
                train_script=str(client_script),
                backend="invalid_backend",
            )

    def test_recipe_with_dict_train_args(self, tmp_path):
        """Test SVM recipe with per-client train_args."""
        client_script = tmp_path / "client.py"
        client_script.write_text("# Dummy client script")

        train_args = {
            "site-1": "--data_path /tmp/cancer.csv --train_start 0 --train_end 150",
            "site-2": "--data_path /tmp/cancer.csv --train_start 150 --train_end 300",
            "site-3": "--data_path /tmp/cancer.csv --train_start 300 --train_end 455",
        }
        recipe = SVMFedAvgRecipe(
            name="test_svm",
            min_clients=3,
            train_script=str(client_script),
            train_args=train_args,
        )
        assert recipe.train_args == train_args
