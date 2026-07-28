#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=cpu
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-control-plane
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:05:00
#SBATCH --comment=fact_off
#SBATCH --output=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.out
#SBATCH --error=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.err

set -Eeuo pipefail
umask 077

PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-${PROJECT_ROOT}/containers/pytorch-25.01-py3.sqsh}"
REPO_ROOT="${REPO_ROOT:-${PROJECT_ROOT}/repos/NVFlare}"
VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/envs/nvflare-fsdp2}"
GATE_MODEL_PATH="${GATE_MODEL_PATH:-${PROJECT_ROOT}/models/Qwen2.5-1.5B-8faed761d45a}"
TARGET_MODEL_PATH="${TARGET_MODEL_PATH:-${PROJECT_ROOT}/models/Qwen2.5-14B-97e1e76335b7}"
TARGET_MODEL_REVISION="${TARGET_MODEL_REVISION:-97e1e76335b7017d8f67c08a19d103c0504298c9}"
REQUIRED_BASE_COMMIT="1be715ed5bc97c83a6771b486c40b75f0b97e4fd"
EXPECTED_BRANCH="codex/llm-fl-real-14b"
PRIVATE_ROOT="/tmp/nvflare-control-plane-${SLURM_JOB_ID}"
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/control-plane-${SLURM_JOB_ID}"

for path in "${CONTAINER_IMAGE}" "${REPO_ROOT}" "${VENV_DIR}" "${GATE_MODEL_PATH}" "${TARGET_MODEL_PATH}"; do
    if [[ ! -e "${path}" ]]; then
        echo "Required path does not exist: ${path}" >&2
        exit 1
    fi
done
OBSERVED_BRANCH="$(git -C "${REPO_ROOT}" branch --show-current)"
if [[ "${OBSERVED_BRANCH}" != "${EXPECTED_BRANCH}" ]]; then
    echo "Expected branch ${EXPECTED_BRANCH}, found ${OBSERVED_BRANCH:-detached HEAD}." >&2
    exit 1
fi
if ! git -C "${REPO_ROOT}" merge-base --is-ancestor "${REQUIRED_BASE_COMMIT}" HEAD; then
    echo "Checkout does not contain required production qualification base ${REQUIRED_BASE_COMMIT}." >&2
    exit 1
fi
GIT_STATUS="$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=all)"
if [[ -n "${GIT_STATUS}" ]]; then
    echo "Refusing a dirty checkout:" >&2
    printf '%s\n' "${GIT_STATUS}" >&2
    exit 1
fi
for model_path in "${GATE_MODEL_PATH}" "${TARGET_MODEL_PATH}"; do
    if [[ ! -s "${model_path}/REVISION" ]]; then
        echo "Staged model is missing a non-empty REVISION file: ${model_path}/REVISION" >&2
        exit 1
    fi
done
if [[ "$(<"${TARGET_MODEL_PATH}/REVISION")" != "${TARGET_MODEL_REVISION}" ]]; then
    echo "The staged target model revision does not match ${TARGET_MODEL_REVISION}." >&2
    exit 1
fi
GATE_MODEL_REVISION="$(<"${GATE_MODEL_PATH}/REVISION")"
mkdir -p "${ARTIFACT_ROOT}"

srun --kill-on-bad-exit=1 \
    --container-image="${CONTAINER_IMAGE}" \
    --container-mounts="${PROJECT_ROOT}:${PROJECT_ROOT}" \
    bash -lc "
        set -Eeuo pipefail
        source '${VENV_DIR}/bin/activate'
        cd '${REPO_ROOT}'
        python research/llm_fl_stress/real_training/qualification.py \
          --gate-model-path '${GATE_MODEL_PATH}' \
          --gate-model-revision '${GATE_MODEL_REVISION}' \
          --target-model-path '${TARGET_MODEL_PATH}' \
          --target-model-revision '${TARGET_MODEL_REVISION}' \
          --private-root '${PRIVATE_ROOT}' \
          --evidence-root '${ARTIFACT_ROOT}' \
          --service-startup-timeout 90 \
          --control-plane-only
    "
