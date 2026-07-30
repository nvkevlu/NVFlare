#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=cpu
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-72b-preflight
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --comment=fact_off
#SBATCH --output=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.out
#SBATCH --error=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.err

set -Eeuo pipefail
umask 077

PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-${PROJECT_ROOT}/containers/pytorch-25.01-py3.sqsh}"
REPO_ROOT="${REPO_ROOT:-${PROJECT_ROOT}/repos/NVFlare}"
VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/envs/nvflare-fsdp2}"
MODEL_PATH="${MODEL_PATH:-${PROJECT_ROOT}/models/Qwen2.5-72B-efba10c8e54e}"
MODEL_REVISION=efba10c8e54e91e0d9570ab5f7b51a958474d4cb
REQUIRED_RELEASE=2026-07-30-trainable-72b-v10
REQUIRED_BASE_COMMIT=1be715ed5bc97c83a6771b486c40b75f0b97e4fd
EXPECTED_BRANCH=codex/llm-fl-real-14b
RELEASE_FILE="${REPO_ROOT}/research/llm_fl_stress/real_training/QUALIFICATION_RELEASE"
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/72b-preflight-${SLURM_JOB_ID}"
EXPORT_ROOT="/tmp/nvflare-72b-export-${SLURM_JOB_ID}"

for path in "${CONTAINER_IMAGE}" "${REPO_ROOT}" "${VENV_DIR}" "${MODEL_PATH}"; do
    if [[ ! -e "${path}" ]]; then
        echo "Required path does not exist: ${path}" >&2
        exit 1
    fi
done
if [[ ! -s "${MODEL_PATH}/REVISION" ]] || [[ "$(<"${MODEL_PATH}/REVISION")" != "${MODEL_REVISION}" ]]; then
    echo "The staged Qwen2.5-72B revision is not ${MODEL_REVISION}." >&2
    exit 1
fi
for required_file in config.json model.safetensors.index.json MANIFEST.sha256; do
    if [[ ! -s "${MODEL_PATH}/${required_file}" ]]; then
        echo "The staged Qwen2.5-72B model is missing ${required_file}." >&2
        exit 1
    fi
done
if [[ ! -s "${RELEASE_FILE}" ]] || [[ "$(<"${RELEASE_FILE}")" != "${REQUIRED_RELEASE}" ]]; then
    echo "Checkout does not contain required qualification release ${REQUIRED_RELEASE}." >&2
    exit 1
fi
if [[ "$(git -C "${REPO_ROOT}" branch --show-current)" != "${EXPECTED_BRANCH}" ]]; then
    echo "Preflight requires branch ${EXPECTED_BRANCH}." >&2
    exit 1
fi
if ! git -C "${REPO_ROOT}" merge-base --is-ancestor "${REQUIRED_BASE_COMMIT}" HEAD; then
    echo "Checkout does not contain the required production qualification base." >&2
    exit 1
fi
if [[ -n "$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=all)" ]]; then
    echo "Refusing a dirty checkout." >&2
    git -C "${REPO_ROOT}" status --short >&2
    exit 1
fi

mkdir -p "${ARTIFACT_ROOT}"
trap 'rm -rf -- "${EXPORT_ROOT}"' EXIT

srun --kill-on-bad-exit=1 \
    --container-image="${CONTAINER_IMAGE}" \
    --container-mounts="${PROJECT_ROOT}:${PROJECT_ROOT}" \
    bash -lc "
        set -Eeuo pipefail
        source '${VENV_DIR}/bin/activate'
        cd '${REPO_ROOT}'
        python research/llm_fl_stress/real_training/dependency_check.py \
          > '${ARTIFACT_ROOT}/dependency-check.json'
        python research/llm_fl_stress/real_training/trainable_server_preflight.py \
          --model-name-or-path '${MODEL_PATH}' \
          --model-revision '${MODEL_REVISION}' \
          --expected-hidden-size 8192 \
          --expected-intermediate-size 29568 \
          --expected-num-hidden-layers 80 \
          --expected-num-attention-heads 64 \
          --expected-num-key-value-heads 8 \
          --expected-min-weight-bytes 140000000000 \
          --expected-safetensor-files 37 \
          --expected-payload-bytes 1755369472 \
          --max-payload-bytes 2147483648 \
          > '${ARTIFACT_ROOT}/trainable-server-preflight.json'
        python research/llm_fl_stress/real_training/job.py \
          --model-name-or-path '${MODEL_PATH}' \
          --model-revision '${MODEL_REVISION}' \
          --workspace-root '${EXPORT_ROOT}/unused-workspace' \
          --export-root '${EXPORT_ROOT}/job' \
          --num-clients 2 \
          --nproc-per-node 4 \
          --num-rounds 1 \
          --local-steps 2 \
          --trainable-target last-layer \
          --run-mode train \
          --state-scope trainable \
          --timeout-seconds 2400 \
          --export-only \
          > '${ARTIFACT_ROOT}/job-export.json'
        test -s '${EXPORT_ROOT}/job/llm_fsdp2_real_training/app_site-1/custom/data/site-1.jsonl'
        test -s '${EXPORT_ROOT}/job/llm_fsdp2_real_training/app_site-2/custom/data/site-2.jsonl'
        python research/llm_fl_stress/real_training/exported_job_preflight.py \
          --job-root '${EXPORT_ROOT}/job/llm_fsdp2_real_training' \
          --timeout-seconds 2400 \
          > '${ARTIFACT_ROOT}/exported-job-preflight.json'
        grep -R -q -- '--state-scope trainable' '${EXPORT_ROOT}/job'
        grep -R -q -- '--timeout-seconds 2400' '${EXPORT_ROOT}/job'
    "

{
    printf 'job_id=%s\n' "${SLURM_JOB_ID}"
    printf 'status=PASS\n'
    printf 'model_path=%s\n' "${MODEL_PATH}"
    printf 'model_revision=%s\n' "${MODEL_REVISION}"
    printf 'expected_payload_bytes=1755369472\n'
    printf 'max_payload_bytes=2147483648\n'
    printf 'git_commit=%s\n' "$(git -C "${REPO_ROOT}" rev-parse HEAD)"
} > "${ARTIFACT_ROOT}/manifest.txt"
