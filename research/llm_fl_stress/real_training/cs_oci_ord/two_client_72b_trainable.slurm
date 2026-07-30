#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=polar,polar3,polar4
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-72b-trainable
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=8
#SBATCH --mem=1600G
#SBATCH --time=04:00:00
#SBATCH --signal=TERM@300
#SBATCH --comment=fact_off
#SBATCH --output=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.out
#SBATCH --error=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.err

set -Eeuo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"
REPO_ROOT="${PROJECT_ROOT}/repos/NVFlare"
CONTAINER_IMAGE="${PROJECT_ROOT}/containers/pytorch-25.01-py3.sqsh"
VENV_DIR="${PROJECT_ROOT}/envs/nvflare-fsdp2"
GATE_MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-1.5B-8faed761d45a"
TARGET_MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-72B-efba10c8e54e"
QUALIFICATION_SCRIPT="${REPO_ROOT}/research/llm_fl_stress/real_training/cs_oci_ord/two_client_14b.slurm"

if [[ ! -f "${QUALIFICATION_SCRIPT}" ]]; then
    echo "Qualification launcher does not exist: ${QUALIFICATION_SCRIPT}" >&2
    exit 1
fi
for job_id_name in CONTROL_JOB_ID PREFLIGHT_JOB_ID GPU_PREFLIGHT_JOB_ID; do
    job_id_value="${!job_id_name:-}"
    if [[ ! "${job_id_value}" =~ ^[0-9]+$ ]]; then
        echo "${job_id_name} must name the passing gate used by the login-node readiness validator." >&2
        exit 1
    fi
done

export QUALIFICATION_PROFILE=trainable-72b
export CONTROL_JOB_ID
export PREFLIGHT_JOB_ID
export GPU_PREFLIGHT_JOB_ID
export CONTAINER_IMAGE
export REPO_ROOT
export VENV_DIR
export GATE_MODEL_PATH
export EXPECTED_GATE_REVISION=8faed761d45a263340a0528343f099c05c9a4323
export EXPECTED_TARGET_LABEL=Qwen2.5-72B
export EXPECTED_TARGET_REVISION=efba10c8e54e91e0d9570ab5f7b51a958474d4cb
export TARGET_MODEL_REVISION="${EXPECTED_TARGET_REVISION}"
export TARGET_MODEL_PATH
export EXPECTED_TARGET_HIDDEN_SIZE=8192
export EXPECTED_TARGET_INTERMEDIATE_SIZE=29568
export EXPECTED_TARGET_NUM_HIDDEN_LAYERS=80
export EXPECTED_TARGET_NUM_ATTENTION_HEADS=64
export EXPECTED_TARGET_NUM_KEY_VALUE_HEADS=8
export EXPECTED_TARGET_MIN_WEIGHT_BYTES=140000000000
export EXPECTED_TARGET_SAFETENSOR_FILES=37
export EXPECTED_TARGET_TENSOR_BYTES=145412407296
export EXPECTED_TARGET_PAYLOAD_BYTES=1755369472
export EXPECTED_GPU_NAME_SUBSTRING=A100-SXM4-80GB
export SERVICE_STARTUP_TIMEOUT=300
export GATE_READY_TIMEOUT=900
export GATE_STALL_TIMEOUT=900
export TARGET_READY_TIMEOUT=7200
export TARGET_STALL_TIMEOUT=1800

exec bash "${QUALIFICATION_SCRIPT}"
