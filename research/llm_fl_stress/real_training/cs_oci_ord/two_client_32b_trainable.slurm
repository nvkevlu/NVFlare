#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=polar,polar3,polar4
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-32b-trainable
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=8
#SBATCH --mem=512G
#SBATCH --time=02:00:00
#SBATCH --signal=B:TERM@300
#SBATCH --comment=fact_off
#SBATCH --output=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.out
#SBATCH --error=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.err

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"

export QUALIFICATION_PROFILE=trainable-32b
export EXPECTED_TARGET_LABEL=Qwen2.5-32B
export EXPECTED_TARGET_REVISION=1818d35814b8319459f4bd55ed1ac8709630f003
export TARGET_MODEL_REVISION="${EXPECTED_TARGET_REVISION}"
export TARGET_MODEL_PATH="${TARGET_MODEL_PATH:-${PROJECT_ROOT}/models/Qwen2.5-32B-1818d35814b8}"
export EXPECTED_TARGET_HIDDEN_SIZE=5120
export EXPECTED_TARGET_NUM_HIDDEN_LAYERS=64
export EXPECTED_TARGET_MIN_WEIGHT_BYTES=60000000000
export EXPECTED_TARGET_SAFETENSOR_FILES=17
export EXPECTED_TARGET_PAYLOAD_BYTES=975210496
export TARGET_READY_TIMEOUT=1800
export TARGET_STALL_TIMEOUT=900

exec bash "${SCRIPT_DIR}/two_client_14b.slurm"
