#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=polar,polar3,polar4
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-14b-5round
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=8
#SBATCH --mem=512G
#SBATCH --time=02:00:00
#SBATCH --signal=TERM@300
#SBATCH --no-requeue
#SBATCH --comment=fact_off
#SBATCH --output=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.out
#SBATCH --error=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.err

set -Eeuo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"
REPO_ROOT="${PROJECT_ROOT}/repos/NVFlare"
CONTAINER_IMAGE="${PROJECT_ROOT}/containers/pytorch-25.01-py3.sqsh"
VENV_DIR="${PROJECT_ROOT}/envs/nvflare-fsdp2"
TARGET_MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-14B-97e1e76335b7"
QUALIFICATION_SCRIPT="${REPO_ROOT}/research/llm_fl_stress/real_training/cs_oci_ord/two_client_14b.slurm"
MINIMUM_SLURM_MEMORY_MIB=524288
MINIMUM_SLURM_REMAINING_SECONDS=6900
REQUIRED_SLURM_GPUS_ON_NODE=8
SLURM_ALLOCATION_MEMORY_MIB="${SLURM_MEM_PER_NODE:-UNSET}"
SLURM_ALLOCATION_GPUS_ON_NODE="${SLURM_GPUS_ON_NODE:-UNSET}"
SLURM_ALLOCATION_END_TIME_EPOCH="${SLURM_JOB_END_TIME:-UNSET}"
SLURM_ALLOCATION_CHECK_TIME_EPOCH=UNCOMPUTED
SLURM_ALLOCATION_REMAINING_SECONDS=UNCOMPUTED
EXPECTED_HEAD="${EXPECTED_HEAD:-}"

if [[ ! "${SLURM_ALLOCATION_MEMORY_MIB}" =~ ^[0-9]+$ ]] ||
    (( SLURM_ALLOCATION_MEMORY_MIB < MINIMUM_SLURM_MEMORY_MIB )); then
    echo "Five-round 14B training requires at least ${MINIMUM_SLURM_MEMORY_MIB} MiB; got ${SLURM_ALLOCATION_MEMORY_MIB}." >&2
    exit 1
fi
if [[ "${SLURM_ALLOCATION_GPUS_ON_NODE}" != "${REQUIRED_SLURM_GPUS_ON_NODE}" ]]; then
    echo "Five-round 14B training requires exactly 8 allocated GPUs; got ${SLURM_ALLOCATION_GPUS_ON_NODE}." >&2
    exit 1
fi
if [[ ! "${SLURM_ALLOCATION_END_TIME_EPOCH}" =~ ^[0-9]+$ ]]; then
    echo "SLURM_JOB_END_TIME must report the allocation end as a Unix timestamp." >&2
    exit 1
fi
SLURM_ALLOCATION_CHECK_TIME_EPOCH="$(date +%s)"
SLURM_ALLOCATION_REMAINING_SECONDS=$((SLURM_ALLOCATION_END_TIME_EPOCH - SLURM_ALLOCATION_CHECK_TIME_EPOCH))
if (( SLURM_ALLOCATION_REMAINING_SECONDS < MINIMUM_SLURM_REMAINING_SECONDS )); then
    echo "Five-round 14B training requires at least ${MINIMUM_SLURM_REMAINING_SECONDS} seconds remaining; got ${SLURM_ALLOCATION_REMAINING_SECONDS}." >&2
    exit 1
fi

for path in "${QUALIFICATION_SCRIPT}" "${CONTAINER_IMAGE}" "${VENV_DIR}" "${TARGET_MODEL_PATH}"; do
    if [[ ! -e "${path}" ]]; then
        echo "Required path does not exist: ${path}" >&2
        exit 1
    fi
done
if [[ ! "${EXPECTED_HEAD}" =~ ^[0-9a-f]{40}$ ]] ||
    [[ "$(git -C "${REPO_ROOT}" rev-parse HEAD)" != "${EXPECTED_HEAD}" ]]; then
    echo "EXPECTED_HEAD must pin the exact reviewed checkout used for this queued job." >&2
    exit 1
fi
if [[ "${NCCL_P2P_DISABLE+x}" == "x" ]]; then
    echo "Refusing inherited NCCL_P2P_DISABLE=${NCCL_P2P_DISABLE}; use cluster NCCL defaults." >&2
    exit 1
fi

export QUALIFICATION_PROFILE=full-model-14b-multiround
export PROJECT_ROOT REPO_ROOT CONTAINER_IMAGE VENV_DIR
export TARGET_MODEL_PATH
export TARGET_MODEL_REVISION=97e1e76335b7017d8f67c08a19d103c0504298c9
export EXPECTED_TARGET_LABEL=Qwen2.5-14B
export EXPECTED_TARGET_REVISION="${TARGET_MODEL_REVISION}"
export EXPECTED_TARGET_HIDDEN_SIZE=5120
export EXPECTED_TARGET_INTERMEDIATE_SIZE=13824
export EXPECTED_TARGET_NUM_HIDDEN_LAYERS=48
export EXPECTED_TARGET_NUM_ATTENTION_HEADS=40
export EXPECTED_TARGET_NUM_KEY_VALUE_HEADS=8
export EXPECTED_TARGET_MIN_WEIGHT_BYTES=29540067328
export EXPECTED_TARGET_SAFETENSOR_FILES=8
export EXPECTED_TARGET_TENSOR_BYTES=29540067328
export EXPECTED_TARGET_PAYLOAD_BYTES=29540067328
export EXPECTED_TARGET_TENSOR_COUNT=579
export EXPECTED_TARGET_TRAINABLE_PARAMETERS=14770033664
export EXPECTED_GPU_NAME_SUBSTRING=A100-SXM4-80GB

# The qualification parser still accepts gate-model arguments for older
# profiles. Point them at the target, but the multiround profile never runs a
# gate phase and never submits a 1.5B job.
export GATE_MODEL_PATH="${TARGET_MODEL_PATH}"
export EXPECTED_GATE_REVISION="${TARGET_MODEL_REVISION}"

export SERVICE_STARTUP_TIMEOUT=300
export GATE_READY_TIMEOUT=3600
export GATE_STALL_TIMEOUT=3600
export TARGET_READY_TIMEOUT=7200
export TARGET_STALL_TIMEOUT=7200
export SLURM_ALLOCATION_MEMORY_MIB
export SLURM_ALLOCATION_GPUS_ON_NODE
export SLURM_ALLOCATION_END_TIME_EPOCH
export SLURM_ALLOCATION_CHECK_TIME_EPOCH
export SLURM_ALLOCATION_REMAINING_SECONDS

exec bash "${QUALIFICATION_SCRIPT}"
