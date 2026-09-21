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

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from nvflare.utils.job_launcher_utils import _JOB_PROCESS_BOOTSTRAP_PATH


@pytest.mark.parametrize("install_layout", ["source", "user-site"])
@pytest.mark.parametrize(
    ("process_type", "module_dir"),
    [("client", "client"), ("server", "server")],
)
def test_isolated_bootstrap_imports_install_tree_without_job_custom_code(
    tmp_path, install_layout, process_type, module_dir
):
    if install_layout == "source":
        package_parent = tmp_path / "checkout"
    else:
        package_parent = tmp_path / "userbase" / "lib" / "python" / "site-packages"

    app_dir = package_parent / "nvflare" / "private" / "fed" / "app"
    target_dir = app_dir / module_dir
    target_dir.mkdir(parents=True)
    for package_dir in (package_parent / "nvflare", *target_dir.parents[:4], target_dir):
        (package_dir / "__init__.py").touch()

    bootstrap = app_dir / "job_process_bootstrap.py"
    shutil.copyfile(_JOB_PROCESS_BOOTSTRAP_PATH, bootstrap)

    worker_marker = tmp_path / "worker-ran"
    module_name = "worker_process.py" if process_type == "client" else "runner_process.py"
    target = target_dir / module_name
    target.write_text(
        "import importlib.util\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "custom_visible = importlib.util.find_spec('job_custom_probe') is not None\n"
        "Path(os.environ['NVFL_TEST_WORKER_MARKER']).write_text(\n"
        "    f'{Path(__file__).resolve()}|{custom_visible}|{sys.argv[1:]!r}', encoding='utf-8'\n"
        ")\n",
        encoding="utf-8",
    )

    custom_dir = tmp_path / "job" / "custom"
    custom_dir.mkdir(parents=True)
    sitecustomize_marker = tmp_path / "sitecustomize-ran"
    (custom_dir / "sitecustomize.py").write_text(
        "import os\n" "from pathlib import Path\n" "Path(os.environ['NVFL_TEST_SITECUSTOMIZE_MARKER']).touch()\n",
        encoding="utf-8",
    )
    (custom_dir / "job_custom_probe.py").write_text("JOB_CONTROLLED = True\n", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(custom_dir)
    env["NVFL_TEST_WORKER_MARKER"] = str(worker_marker)
    env["NVFL_TEST_SITECUSTOMIZE_MARKER"] = str(sitecustomize_marker)
    completed = subprocess.run(
        [sys.executable, "-I", str(bootstrap), process_type, "sentinel"],
        cwd=custom_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    target_path, custom_visible, child_args = worker_marker.read_text(encoding="utf-8").split("|", 2)
    assert Path(target_path) == target.resolve()
    assert custom_visible == "False"
    assert child_args == "['sentinel']"
    assert not sitecustomize_marker.exists()


def test_isolated_bootstrap_rejects_arbitrary_module(tmp_path):
    marker = tmp_path / "arbitrary-module-ran"
    custom_dir = tmp_path / "custom"
    custom_dir.mkdir()
    (custom_dir / "arbitrary_module.py").write_text(
        "import os\nfrom pathlib import Path\nPath(os.environ['NVFL_TEST_MARKER']).touch()\n", encoding="utf-8"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(custom_dir)
    env["NVFL_TEST_MARKER"] = str(marker)

    completed = subprocess.run(
        [sys.executable, "-I", _JOB_PROCESS_BOOTSTRAP_PATH, "arbitrary_module"],
        cwd=custom_dir,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "fixed NVFlare job-process types" in completed.stderr
    assert not marker.exists()
