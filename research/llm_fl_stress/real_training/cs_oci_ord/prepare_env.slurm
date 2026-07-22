#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=cpu
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-env
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=00:20:00
#SBATCH --comment=fact_off
#SBATCH --output=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.out
#SBATCH --error=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.err

set -Eeuo pipefail
umask 077

PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-${PROJECT_ROOT}/containers/pytorch-25.01-py3.sqsh}"
REPO_ROOT="${REPO_ROOT:-${PROJECT_ROOT}/repos/NVFlare}"
VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/envs/nvflare-fsdp2}"
REQUIREMENTS="${REPO_ROOT}/research/llm_fl_stress/real_training/requirements.txt"

for path in "${CONTAINER_IMAGE}" "${REPO_ROOT}" "${REQUIREMENTS}"; do
    if [[ ! -e "${path}" ]]; then
        echo "Required path does not exist: ${path}" >&2
        exit 1
    fi
done
if [[ -e "${VENV_DIR}" ]]; then
    echo "Refusing to replace existing environment: ${VENV_DIR}" >&2
    exit 1
fi

export PIP_CACHE_DIR="${PROJECT_ROOT}/cache/pip"
mkdir -p "${PIP_CACHE_DIR}" "$(dirname "${VENV_DIR}")"

srun \
    --container-image="${CONTAINER_IMAGE}" \
    --container-mounts="${PROJECT_ROOT}:${PROJECT_ROOT}" \
    bash -lc "
        set -Eeuo pipefail
        python3 -m venv --copies '${VENV_DIR}'
        source '${VENV_DIR}/bin/activate'
        python -m pip install --upgrade pip setuptools wheel
        python -m pip install -r '${REQUIREMENTS}'
        python -m pip install -e '${REPO_ROOT}[app_opt]'
        python -m pip check
        python '${REPO_ROOT}/research/llm_fl_stress/real_training/dependency_check.py'
        python -m pip freeze > '${VENV_DIR}/requirements.lock'
    "

echo "Prepared ${VENV_DIR}"
