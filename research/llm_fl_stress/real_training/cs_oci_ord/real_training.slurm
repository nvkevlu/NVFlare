#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=polar,polar3,polar4
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-14b
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --gpus-per-node=4
#SBATCH --mem=512G
#SBATCH --time=00:30:00
#SBATCH --signal=B:TERM@300
#SBATCH --comment=fact_off
#SBATCH --output=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.out
#SBATCH --error=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.err

set -Eeuo pipefail
umask 077

PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-${PROJECT_ROOT}/containers/pytorch-25.01-py3.sqsh}"
REPO_ROOT="${REPO_ROOT:-${PROJECT_ROOT}/repos/NVFlare}"
VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/envs/nvflare-fsdp2}"
MODEL_PATH="${MODEL_PATH:?Set MODEL_PATH to the absolute local Hugging Face snapshot directory}"
MODEL_REVISION="${MODEL_REVISION:-}"
NUM_CLIENTS="${NUM_CLIENTS:-1}"
NPROC_PER_NODE="${NPROC_PER_NODE:-4}"
LOCAL_STEPS="${LOCAL_STEPS:-1}"
TRAINABLE_TARGET="${TRAINABLE_TARGET:-last-layer}"
RUN_MODE="${RUN_MODE:-train}"
EXPECTED_GPU_NAME_SUBSTRING="${EXPECTED_GPU_NAME_SUBSTRING:-A100-SXM4-80GB}"

if ! [[ "${NUM_CLIENTS}" =~ ^[1-9][0-9]*$ ]]; then
    echo "NUM_CLIENTS must be a positive integer, got ${NUM_CLIENTS}." >&2
    exit 1
fi
if ! [[ "${NPROC_PER_NODE}" =~ ^[1-9][0-9]*$ ]]; then
    echo "NPROC_PER_NODE must be a positive integer, got ${NPROC_PER_NODE}." >&2
    exit 1
fi
EXPECTED_GPU_PROCESSES=$((NUM_CLIENTS * NPROC_PER_NODE))
if [[ "${SLURM_GPUS_ON_NODE:-}" =~ ^[0-9]+$ ]] && [[ "${SLURM_GPUS_ON_NODE}" != "${EXPECTED_GPU_PROCESSES}" ]]; then
    echo "Allocation exposes ${SLURM_GPUS_ON_NODE} GPUs, but clients require ${EXPECTED_GPU_PROCESSES}." >&2
    exit 1
fi
if [[ -n "${NCCL_P2P_DISABLE:-}" ]]; then
    echo "Refusing inherited NCCL_P2P_DISABLE=${NCCL_P2P_DISABLE}; use the cluster's NCCL defaults." >&2
    exit 1
fi
for path in "${CONTAINER_IMAGE}" "${REPO_ROOT}" "${VENV_DIR}" "${MODEL_PATH}"; do
    if [[ ! -e "${path}" ]]; then
        echo "Required path does not exist: ${path}" >&2
        exit 1
    fi
done

SCRATCH_ROOT="/raid/scratch/${USER}/${SLURM_JOB_ID}"
WORKSPACE_ROOT="${SCRATCH_ROOT}/workspace"
EXPORT_ROOT="${SCRATCH_ROOT}/exported_job"
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/${SLURM_JOB_ID}"
mkdir -p "${WORKSPACE_ROOT}" "${EXPORT_ROOT}" "${ARTIFACT_ROOT}"

archive_results() {
    status=$?
    trap - EXIT
    manifest="${ARTIFACT_ROOT}/manifest.txt"
    {
        printf 'job_id=%s\n' "${SLURM_JOB_ID}"
        printf 'status=%s\n' "${status}"
        printf 'host=%s\n' "$(hostname)"
        printf 'model_path=%s\n' "${MODEL_PATH}"
        printf 'model_revision=%s\n' "${MODEL_REVISION}"
        printf 'num_clients=%s\n' "${NUM_CLIENTS}"
        printf 'nproc_per_client=%s\n' "${NPROC_PER_NODE}"
        printf 'total_gpu_processes=%s\n' "${EXPECTED_GPU_PROCESSES}"
        printf 'run_mode=%s\n' "${RUN_MODE}"
        printf 'git_commit=%s\n' "$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || true)"
    } > "${manifest}"
    if [[ -d "${SCRATCH_ROOT}" ]]; then
        if tar -cf "${ARTIFACT_ROOT}/run.tar.partial" -C "${SCRATCH_ROOT}" .; then
            mv "${ARTIFACT_ROOT}/run.tar.partial" "${ARTIFACT_ROOT}/run.tar"
        else
            echo "Result archive failed; preserving run.tar.partial for diagnosis." >&2
        fi
    fi
    return "${status}"
}
trap archive_results EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HOME="${PROJECT_ROOT}/cache/huggingface"
export TOKENIZERS_PARALLELISM=false
export WANDB_DISABLED=true
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

JOB_ARGS=(
    --model-name-or-path "${MODEL_PATH}"
    --workspace-root "${WORKSPACE_ROOT}"
    --export-root "${EXPORT_ROOT}"
    --num-clients "${NUM_CLIENTS}"
    --nproc-per-node "${NPROC_PER_NODE}"
    --num-rounds 1
    --local-steps "${LOCAL_STEPS}"
    --max-length 128
    --learning-rate 1e-5
    --trainable-target "${TRAINABLE_TARGET}"
    --run-mode "${RUN_MODE}"
    --timeout-seconds 1800
)
if [[ -n "${EXPECTED_GPU_NAME_SUBSTRING}" ]]; then
    JOB_ARGS+=(--expected-gpu-name-substring "${EXPECTED_GPU_NAME_SUBSTRING}")
fi
if [[ -n "${MODEL_REVISION}" ]]; then
    JOB_ARGS+=(--model-revision "${MODEL_REVISION}")
fi
printf -v QUOTED_JOB_ARGS ' %q' "${JOB_ARGS[@]}"

srun --kill-on-bad-exit=1 \
    --container-image="${CONTAINER_IMAGE}" \
    --container-mounts="${PROJECT_ROOT}:${PROJECT_ROOT},/raid/scratch:/raid/scratch" \
    bash -lc "
        set -Eeuo pipefail
        source '${VENV_DIR}/bin/activate'
        cd '${REPO_ROOT}'
        python research/llm_fl_stress/real_training/job.py${QUOTED_JOB_ARGS}
    "
