#!/usr/bin/env bash
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

set -Eeuo pipefail
umask 077

PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"
PROJECT_PARENT="$(dirname "${PROJECT_ROOT}")"

if [[ ! -d "${PROJECT_PARENT}" || ! -w "${PROJECT_PARENT}" ]]; then
    echo "Project user directory is missing or not writable: ${PROJECT_PARENT}" >&2
    echo "Confirm the project path before creating any data." >&2
    exit 1
fi

mkdir -p \
    "${PROJECT_ROOT}/artifacts" \
    "${PROJECT_ROOT}/cache/huggingface" \
    "${PROJECT_ROOT}/containers" \
    "${PROJECT_ROOT}/enroot/cache" \
    "${PROJECT_ROOT}/enroot/images" \
    "${PROJECT_ROOT}/envs" \
    "${PROJECT_ROOT}/incoming" \
    "${PROJECT_ROOT}/jobs" \
    "${PROJECT_ROOT}/logs" \
    "${PROJECT_ROOT}/models" \
    "${PROJECT_ROOT}/repos"

chmod 700 "${PROJECT_ROOT}"
printf 'PROJECT_ROOT=%s\n' "${PROJECT_ROOT}"
du -sh "${PROJECT_ROOT}"
