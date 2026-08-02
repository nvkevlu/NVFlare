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

import sys
from types import SimpleNamespace

import pytest

from research.llm_fl_stress.real_training import dependency_check


def _metadata_environment(tmp_path, monkeypatch):
    source_root = tmp_path / "NVFlare-release"
    nvflare_init = source_root / "nvflare" / "__init__.py"
    nvflare_init.parent.mkdir(parents=True)
    nvflare_init.write_text("", encoding="utf-8")
    prefix = tmp_path / "venv"
    prefix.mkdir()
    monkeypatch.setenv("PYTHONPATH", str(source_root))
    monkeypatch.setenv("NVFLARE_EXPECTED_SOURCE_ROOT", str(source_root))
    monkeypatch.setattr(sys, "prefix", str(prefix))
    monkeypatch.setattr(
        dependency_check.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(nvflare_init)) if name == "nvflare" else None,
    )
    monkeypatch.setattr(
        dependency_check.importlib.metadata,
        "version",
        lambda name: dependency_check.PINNED_DISTRIBUTIONS[name],
    )
    return source_root, prefix, nvflare_init


def test_metadata_check_passes_without_importing_heavy_packages(tmp_path, monkeypatch):
    source_root, prefix, nvflare_init = _metadata_environment(tmp_path, monkeypatch)
    heavy_modules = ("torch", "torchvision", "transformers", "nvflare")
    before = {name: sys.modules.get(name) for name in heavy_modules}

    result = dependency_check.metadata_check(source_root, prefix)

    assert result["status"] == "PASS"
    assert result["mode"] == "metadata-only"
    assert result["nvflare_init"] == str(nvflare_init.resolve())
    assert result["versions"] == dependency_check.PINNED_DISTRIBUTIONS
    assert {name: sys.modules.get(name) for name in heavy_modules} == before


@pytest.mark.parametrize("variable", ["PYTHONPATH", "NVFLARE_EXPECTED_SOURCE_ROOT"])
def test_metadata_check_rejects_wrong_source_environment(tmp_path, monkeypatch, variable):
    source_root, prefix, _ = _metadata_environment(tmp_path, monkeypatch)
    monkeypatch.setenv(variable, str(tmp_path / "wrong-source"))

    with pytest.raises(RuntimeError, match=variable):
        dependency_check.metadata_check(source_root, prefix)


def test_metadata_check_rejects_wrong_python_prefix(tmp_path, monkeypatch):
    source_root, prefix, _ = _metadata_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "wrong-venv"))

    with pytest.raises(RuntimeError, match="Python prefix"):
        dependency_check.metadata_check(source_root, prefix)


def test_metadata_check_rejects_wrong_nvflare_resolution(tmp_path, monkeypatch):
    source_root, prefix, _ = _metadata_environment(tmp_path, monkeypatch)
    wrong_init = tmp_path / "shared-checkout" / "nvflare" / "__init__.py"
    monkeypatch.setattr(dependency_check.importlib.util, "find_spec", lambda name: SimpleNamespace(origin=wrong_init))

    with pytest.raises(RuntimeError, match="NVFLARE resolves"):
        dependency_check.metadata_check(source_root, prefix)


def test_metadata_check_rejects_distribution_mismatch(tmp_path, monkeypatch):
    source_root, prefix, _ = _metadata_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(
        dependency_check.importlib.metadata,
        "version",
        lambda name: "wrong" if name == "torch" else dependency_check.PINNED_DISTRIBUTIONS[name],
    )

    with pytest.raises(RuntimeError, match="dependency metadata mismatch"):
        dependency_check.metadata_check(source_root, prefix)
