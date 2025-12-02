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

"""Unit tests for SVM assembler."""

import pytest

from nvflare.app_opt.sklearn.svm_assembler import SVMAssembler


class TestSVMAssembler:
    """Tests for SVMAssembler."""

    def test_assembler_creation_with_valid_kernels(self):
        """Test creating assembler with all valid kernel types."""
        valid_kernels = ["linear", "poly", "rbf", "sigmoid"]
        for kernel in valid_kernels:
            assembler = SVMAssembler(kernel=kernel)
            assert assembler.kernel == kernel

    def test_assembler_with_invalid_kernel_raises_error(self):
        """Test that invalid kernel raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported kernel"):
            SVMAssembler(kernel="invalid_kernel")

    def test_assembler_get_model_params(self):
        """Test get_model_params returns correct structure."""
        from nvflare.apis.dxo import DXO, DataKind

        assembler = SVMAssembler(kernel="rbf")
        # Create a mock DXO with support vectors
        mock_dxo = DXO(data_kind=DataKind.WEIGHTS, data={"support_x": [[1, 2], [3, 4]], "support_y": [0, 1]})
        params = assembler.get_model_params(mock_dxo)
        assert isinstance(params, dict)
        assert "support_x" in params
        assert "support_y" in params

    def test_assembler_get_model_params_with_different_kernels(self):
        """Test assembler kernel attribute with different kernels."""
        for kernel in ["linear", "poly", "rbf", "sigmoid"]:
            assembler = SVMAssembler(kernel=kernel)
            assert assembler.kernel == kernel

    def test_assembler_default_kernel(self):
        """Test assembler default kernel is 'rbf'."""
        assembler = SVMAssembler()
        assert assembler.kernel == "rbf"
