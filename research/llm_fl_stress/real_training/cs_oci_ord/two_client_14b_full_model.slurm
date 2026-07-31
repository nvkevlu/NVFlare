#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=polar,polar3,polar4
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-14b-full-model
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
GATE_MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-1.5B-8faed761d45a"
TARGET_MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-14B-97e1e76335b7"
QUALIFICATION_SCRIPT="${REPO_ROOT}/research/llm_fl_stress/real_training/cs_oci_ord/two_client_14b.slurm"
READINESS_SCRIPT="${REPO_ROOT}/research/llm_fl_stress/real_training/cs_oci_ord/validate_14b_full_model_readiness.py"
MINIMUM_SLURM_MEMORY_MIB=524288
MINIMUM_SLURM_REMAINING_SECONDS=6900
REQUIRED_SLURM_GPUS_ON_NODE=8
SLURM_ALLOCATION_MEMORY_MIB="${SLURM_MEM_PER_NODE:-UNSET}"
SLURM_ALLOCATION_GPUS_ON_NODE="${SLURM_GPUS_ON_NODE:-UNSET}"
SLURM_ALLOCATION_END_TIME_EPOCH="${SLURM_JOB_END_TIME:-UNSET}"
SLURM_ALLOCATION_CHECK_TIME_EPOCH=UNCOMPUTED
SLURM_ALLOCATION_REMAINING_SECONDS=UNCOMPUTED

validate_slurm_allocation() {
    if [[ ! "${SLURM_ALLOCATION_MEMORY_MIB}" =~ ^[0-9]+$ ]]; then
        echo "SLURM_MEM_PER_NODE must report the actual allocation in MiB." >&2
        exit 1
    fi
    if (( SLURM_ALLOCATION_MEMORY_MIB < MINIMUM_SLURM_MEMORY_MIB )); then
        echo "Full-model qualification requires at least ${MINIMUM_SLURM_MEMORY_MIB} MiB; got ${SLURM_ALLOCATION_MEMORY_MIB}." >&2
        exit 1
    fi
    if [[ "${SLURM_ALLOCATION_GPUS_ON_NODE}" != "${REQUIRED_SLURM_GPUS_ON_NODE}" ]]; then
        echo "Full-model qualification requires exactly ${REQUIRED_SLURM_GPUS_ON_NODE} allocated GPUs; got ${SLURM_ALLOCATION_GPUS_ON_NODE}." >&2
        exit 1
    fi
    if [[ ! "${SLURM_ALLOCATION_END_TIME_EPOCH}" =~ ^[0-9]+$ ]]; then
        echo "SLURM_JOB_END_TIME must report the allocation end as a Unix timestamp." >&2
        exit 1
    fi
    SLURM_ALLOCATION_CHECK_TIME_EPOCH="$(date +%s)"
    SLURM_ALLOCATION_REMAINING_SECONDS=$((SLURM_ALLOCATION_END_TIME_EPOCH - SLURM_ALLOCATION_CHECK_TIME_EPOCH))
    if (( SLURM_ALLOCATION_REMAINING_SECONDS < MINIMUM_SLURM_REMAINING_SECONDS )); then
        echo "Full-model qualification requires at least ${MINIMUM_SLURM_REMAINING_SECONDS} seconds remaining; got ${SLURM_ALLOCATION_REMAINING_SECONDS}." >&2
        exit 1
    fi
}

validate_slurm_allocation
export SLURM_ALLOCATION_MEMORY_MIB
export SLURM_ALLOCATION_GPUS_ON_NODE
export SLURM_ALLOCATION_END_TIME_EPOCH
export SLURM_ALLOCATION_CHECK_TIME_EPOCH
export SLURM_ALLOCATION_REMAINING_SECONDS

for path in \
    "${QUALIFICATION_SCRIPT}" \
    "${READINESS_SCRIPT}" \
    "${CONTAINER_IMAGE}" \
    "${VENV_DIR}" \
    "${GATE_MODEL_PATH}" \
    "${TARGET_MODEL_PATH}"; do
    if [[ ! -e "${path}" ]]; then
        echo "Required path does not exist: ${path}" >&2
        exit 1
    fi
done
for job_id_name in CONTROL_JOB_ID PREFLIGHT_JOB_ID GPU_PREFLIGHT_JOB_ID; do
    job_id_value="${!job_id_name:-}"
    if [[ ! "${job_id_value}" =~ ^[0-9]+$ ]]; then
        echo "${job_id_name} must name the passing gate checked by login-node readiness." >&2
        exit 1
    fi
done
if [[ "${NCCL_P2P_DISABLE+x}" == "x" ]]; then
    echo "Refusing inherited NCCL_P2P_DISABLE=${NCCL_P2P_DISABLE}; use cluster NCCL defaults." >&2
    exit 1
fi

export QUALIFICATION_PROFILE=full-model-14b
export CONTROL_JOB_ID
export PREFLIGHT_JOB_ID
export GPU_PREFLIGHT_JOB_ID
export PROJECT_ROOT
export CONTAINER_IMAGE
export REPO_ROOT
export VENV_DIR
export GATE_MODEL_PATH
export EXPECTED_GATE_REVISION=8faed761d45a263340a0528343f099c05c9a4323
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
export SERVICE_STARTUP_TIMEOUT=300
export GATE_READY_TIMEOUT=1800
export GATE_STALL_TIMEOUT=1800
export TARGET_READY_TIMEOUT=1800
export TARGET_STALL_TIMEOUT=1800

exec bash "${QUALIFICATION_SCRIPT}"
