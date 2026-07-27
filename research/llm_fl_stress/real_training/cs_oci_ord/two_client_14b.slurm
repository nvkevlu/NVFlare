#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=polar,polar3,polar4
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-14b-2client
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=8
#SBATCH --mem=512G
#SBATCH --time=00:30:00
#SBATCH --signal=B:TERM@300
#SBATCH --comment=fact_off
#SBATCH --output=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.out
#SBATCH --error=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.err

set -Eeuo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"
REPO_ROOT="${REPO_ROOT:-${PROJECT_ROOT}/repos/NVFlare}"
RUNNER="${REPO_ROOT}/research/llm_fl_stress/real_training/cs_oci_ord/real_training.slurm"
MODEL_PATH="${MODEL_PATH:?Set MODEL_PATH to the staged Qwen2.5-14B snapshot}"
MODEL_REVISION="${MODEL_REVISION:?Set MODEL_REVISION to the full Qwen2.5-14B commit}"
EXPECTED_MODEL_REVISION="97e1e76335b7017d8f67c08a19d103c0504298c9"

if [[ "${NUM_CLIENTS:-2}" != "2" ]]; then
    echo "This wrapper is fixed to two clients; unset NUM_CLIENTS or set it to 2." >&2
    exit 1
fi
if [[ "${NPROC_PER_NODE:-4}" != "4" ]]; then
    echo "This wrapper is fixed to four ranks per client; unset NPROC_PER_NODE or set it to 4." >&2
    exit 1
fi
if [[ "${MODEL_REVISION}" != "${EXPECTED_MODEL_REVISION}" ]]; then
    echo "This qualification is pinned to Qwen2.5-14B revision ${EXPECTED_MODEL_REVISION}." >&2
    exit 1
fi
if [[ ! -f "${MODEL_PATH}/REVISION" ]]; then
    echo "The staged model is missing its REVISION file: ${MODEL_PATH}/REVISION" >&2
    exit 1
fi
if [[ "$(<"${MODEL_PATH}/REVISION")" != "${EXPECTED_MODEL_REVISION}" ]]; then
    echo "The staged model REVISION does not match ${EXPECTED_MODEL_REVISION}." >&2
    exit 1
fi
if [[ ! -f "${RUNNER}" ]]; then
    echo "Real-training runner does not exist: ${RUNNER}" >&2
    exit 1
fi

export NUM_CLIENTS=2
export NPROC_PER_NODE=4
exec bash "${RUNNER}"
