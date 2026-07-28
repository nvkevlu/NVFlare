#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=polar,polar3,polar4
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-14b-qualified
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=8
#SBATCH --mem=512G
#SBATCH --time=00:25:00
#SBATCH --signal=B:TERM@120
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
TARGET_MODEL_PATH="${TARGET_MODEL_PATH:-${MODEL_PATH:-${PROJECT_ROOT}/models/Qwen2.5-14B-97e1e76335b7}}"
TARGET_MODEL_REVISION="${TARGET_MODEL_REVISION:-${MODEL_REVISION:-97e1e76335b7017d8f67c08a19d103c0504298c9}}"
EXPECTED_TARGET_REVISION="97e1e76335b7017d8f67c08a19d103c0504298c9"
EXPECTED_GPU_NAME_SUBSTRING="${EXPECTED_GPU_NAME_SUBSTRING:-A100-SXM4-80GB}"
REQUIRED_BASE_COMMIT="1be715ed5bc97c83a6771b486c40b75f0b97e4fd"
EXPECTED_BRANCH="codex/llm-fl-real-14b"
REQUIRED_RELEASE="2026-07-28-trainable-multiround-v3"
RELEASE_FILE="${REPO_ROOT}/research/llm_fl_stress/real_training/QUALIFICATION_RELEASE"
QUALIFICATION_PROFILE="${QUALIFICATION_PROFILE:-full-state}"

if [[ "${TARGET_MODEL_REVISION}" != "${EXPECTED_TARGET_REVISION}" ]]; then
    echo "The target is pinned to Qwen2.5-14B revision ${EXPECTED_TARGET_REVISION}." >&2
    exit 1
fi
if [[ "${QUALIFICATION_PROFILE}" != "full-state" &&
    "${QUALIFICATION_PROFILE}" != "trainable-multiround" ]]; then
    echo "Unsupported qualification profile: ${QUALIFICATION_PROFILE}" >&2
    exit 1
fi
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
if [[ ! -s "${RELEASE_FILE}" ]] || [[ "$(<"${RELEASE_FILE}")" != "${REQUIRED_RELEASE}" ]]; then
    echo "Checkout does not contain required qualification release ${REQUIRED_RELEASE}." >&2
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
if [[ "$(<"${TARGET_MODEL_PATH}/REVISION")" != "${EXPECTED_TARGET_REVISION}" ]]; then
    echo "The staged 14B model does not match ${EXPECTED_TARGET_REVISION}." >&2
    exit 1
fi
if [[ -n "${NCCL_P2P_DISABLE:-}" ]]; then
    echo "Refusing inherited NCCL_P2P_DISABLE=${NCCL_P2P_DISABLE}; use cluster NCCL defaults." >&2
    exit 1
fi
if [[ "${SLURM_GPUS_ON_NODE:-8}" =~ ^[0-9]+$ ]] && [[ "${SLURM_GPUS_ON_NODE:-8}" != "8" ]]; then
    echo "This qualification requires exactly 8 allocated GPUs." >&2
    exit 1
fi

GATE_MODEL_REVISION="$(<"${GATE_MODEL_PATH}/REVISION")"
SCRATCH_ROOT="/raid/scratch/${USER}/${SLURM_JOB_ID}"
PRIVATE_ROOT="${SCRATCH_ROOT}/private"
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/${SLURM_JOB_ID}"
mkdir -p "${ARTIFACT_ROOT}"

record_result() {
    status=$?
    trap - EXIT
    {
        printf 'job_id=%s\n' "${SLURM_JOB_ID}"
        printf 'status=%s\n' "${status}"
        printf 'host=%s\n' "$(hostname)"
        printf 'execution_environment=ProdEnv\n'
        printf 'service_topology=localhost-tls-server-plus-two-real-clients\n'
        printf 'qualification_profile=%s\n' "${QUALIFICATION_PROFILE}"
        printf 'gate_model_path=%s\n' "${GATE_MODEL_PATH}"
        printf 'gate_model_revision=%s\n' "${GATE_MODEL_REVISION}"
        printf 'target_model_path=%s\n' "${TARGET_MODEL_PATH}"
        printf 'target_model_revision=%s\n' "${TARGET_MODEL_REVISION}"
        printf 'num_clients=2\n'
        printf 'nproc_per_client=4\n'
        printf 'total_gpu_processes=8\n'
        printf 'git_commit=%s\n' "$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || true)"
    } > "${ARTIFACT_ROOT}/manifest.txt"
    if [[ -d "${PRIVATE_ROOT}" ]] &&
        [[ "${PRIVATE_ROOT}" == "/raid/scratch/${USER}/${SLURM_JOB_ID}/private" ]]; then
        chmod -R u+rwX "${PRIVATE_ROOT}" 2>/dev/null || true
        rm -rf -- "${PRIVATE_ROOT}"
    fi
    return "${status}"
}
trap record_result EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HOME="${PROJECT_ROOT}/cache/huggingface"
export TOKENIZERS_PARALLELISM=false
export WANDB_DISABLED=true
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

QUALIFICATION_ARGS=(
    --gate-model-path "${GATE_MODEL_PATH}"
    --gate-model-revision "${GATE_MODEL_REVISION}"
    --target-model-path "${TARGET_MODEL_PATH}"
    --target-model-revision "${TARGET_MODEL_REVISION}"
    --private-root "${PRIVATE_ROOT}"
    --evidence-root "${ARTIFACT_ROOT}"
    --expected-gpu-name-substring "${EXPECTED_GPU_NAME_SUBSTRING}"
    --profile "${QUALIFICATION_PROFILE}"
    --service-startup-timeout 90
    --gate-ready-timeout 120
    --gate-total-timeout 300
    --gate-completion-grace-timeout 60
    --target-ready-timeout 300
    --target-total-timeout 720
    --target-completion-grace-timeout 120
)
printf -v QUOTED_QUALIFICATION_ARGS ' %q' "${QUALIFICATION_ARGS[@]}"

srun --kill-on-bad-exit=1 \
    --container-image="${CONTAINER_IMAGE}" \
    --container-mounts="${PROJECT_ROOT}:${PROJECT_ROOT},/raid/scratch:/raid/scratch" \
    bash -lc "
        set -Eeuo pipefail
        source '${VENV_DIR}/bin/activate'
        cd '${REPO_ROOT}'
        python research/llm_fl_stress/real_training/qualification.py${QUOTED_QUALIFICATION_ARGS}
    "
