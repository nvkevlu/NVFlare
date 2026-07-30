#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=polar,polar3,polar4
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-72b-trainable
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=8
#SBATCH --mem=1400G
#SBATCH --time=03:00:00
#SBATCH --signal=B:TERM@300
#SBATCH --comment=fact_off
#SBATCH --output=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.out
#SBATCH --error=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.err

set -Eeuo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"
REPO_ROOT="${REPO_ROOT:-${PROJECT_ROOT}/repos/NVFlare}"
QUALIFICATION_SCRIPT="${REPO_ROOT}/research/llm_fl_stress/real_training/cs_oci_ord/two_client_14b.slurm"

if [[ ! -f "${QUALIFICATION_SCRIPT}" ]]; then
    echo "Qualification launcher does not exist: ${QUALIFICATION_SCRIPT}" >&2
    exit 1
fi

export QUALIFICATION_PROFILE=trainable-72b
export EXPECTED_TARGET_LABEL=Qwen2.5-72B
export EXPECTED_TARGET_REVISION=efba10c8e54e91e0d9570ab5f7b51a958474d4cb
export TARGET_MODEL_REVISION="${EXPECTED_TARGET_REVISION}"
export TARGET_MODEL_PATH="${TARGET_MODEL_PATH:-${PROJECT_ROOT}/models/Qwen2.5-72B-efba10c8e54e}"
export EXPECTED_TARGET_HIDDEN_SIZE=8192
export EXPECTED_TARGET_INTERMEDIATE_SIZE=29568
export EXPECTED_TARGET_NUM_HIDDEN_LAYERS=80
export EXPECTED_TARGET_NUM_ATTENTION_HEADS=64
export EXPECTED_TARGET_NUM_KEY_VALUE_HEADS=8
export EXPECTED_TARGET_MIN_WEIGHT_BYTES=140000000000
export EXPECTED_TARGET_SAFETENSOR_FILES=37
export EXPECTED_TARGET_PAYLOAD_BYTES=1755369472
export TARGET_READY_TIMEOUT=3600
export TARGET_STALL_TIMEOUT=1800

exec bash "${QUALIFICATION_SCRIPT}"
