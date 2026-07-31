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
CONTAINER_IMAGE="${PROJECT_ROOT}/containers/pytorch-25.01-py3.sqsh"
REPO_ROOT="${PROJECT_ROOT}/repos/NVFlare"
VENV_DIR="${PROJECT_ROOT}/envs/nvflare-fsdp2"
MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-72B-efba10c8e54e"
MODEL_REVISION=efba10c8e54e91e0d9570ab5f7b51a958474d4cb
REQUIRED_RELEASE=2026-07-31-full-model-14b-v12
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
CONTAINER_CHECKSUM="${CONTAINER_IMAGE}.sha256"
CONTAINER_VERIFICATION_MARKER="${CONTAINER_CHECKSUM}.verified"
for path in "${CONTAINER_CHECKSUM}" "${CONTAINER_VERIFICATION_MARKER}"; do
    if [[ ! -s "${path}" ]]; then
        echo "Required container verification file is missing or empty: ${path}" >&2
        exit 1
    fi
done
EXPECTED_CONTAINER_MANIFEST_SHA256="$(awk 'NR == 1 {print $1}' "${CONTAINER_VERIFICATION_MARKER}")"
OBSERVED_CONTAINER_MANIFEST_SHA256="$(sha256sum "${CONTAINER_CHECKSUM}" | awk '{print $1}')"
if [[ ! "${EXPECTED_CONTAINER_MANIFEST_SHA256}" =~ ^[0-9a-f]{64}$ ]] ||
    [[ "${EXPECTED_CONTAINER_MANIFEST_SHA256}" != "${OBSERVED_CONTAINER_MANIFEST_SHA256}" ]]; then
    echo "Container verification marker does not match ${CONTAINER_CHECKSUM}." >&2
    exit 1
fi
CONTAINER_CHECKSUM_TARGET="$(awk 'NR == 1 {print $2}' "${CONTAINER_CHECKSUM}")"
CONTAINER_CHECKSUM_TARGET="${CONTAINER_CHECKSUM_TARGET#\*}"
if [[ "${CONTAINER_CHECKSUM_TARGET##*/}" != "${CONTAINER_IMAGE##*/}" ]]; then
    echo "Container checksum does not name ${CONTAINER_IMAGE##*/}." >&2
    exit 1
fi
if [[ "${CONTAINER_IMAGE}" -nt "${CONTAINER_VERIFICATION_MARKER}" ]] ||
    [[ "${CONTAINER_CHECKSUM}" -nt "${CONTAINER_VERIFICATION_MARKER}" ]]; then
    echo "Container image or checksum changed after verification." >&2
    exit 1
fi
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
MANIFEST_VERIFICATION_MARKER="${MODEL_PATH}/MANIFEST.sha256.verified"
if [[ ! -s "${MANIFEST_VERIFICATION_MARKER}" ]]; then
    echo "The staged Qwen2.5-72B model is missing ${MANIFEST_VERIFICATION_MARKER}." >&2
    exit 1
fi
EXPECTED_MANIFEST_SHA256="$(awk 'NR == 1 {print $1}' "${MANIFEST_VERIFICATION_MARKER}")"
OBSERVED_MANIFEST_SHA256="$(sha256sum "${MODEL_PATH}/MANIFEST.sha256" | awk '{print $1}')"
if [[ ! "${EXPECTED_MANIFEST_SHA256}" =~ ^[0-9a-f]{64}$ ]] ||
    [[ "${EXPECTED_MANIFEST_SHA256}" != "${OBSERVED_MANIFEST_SHA256}" ]]; then
    echo "The Qwen2.5-72B manifest verification marker does not match MANIFEST.sha256." >&2
    exit 1
fi
if [[ "${MODEL_PATH}/MANIFEST.sha256" -nt "${MANIFEST_VERIFICATION_MARKER}" ]]; then
    echo "MANIFEST.sha256 changed after manifest verification." >&2
    exit 1
fi
declare -A VERIFIED_MODEL_PATHS=()
while IFS= read -r manifest_line; do
    manifest_digest="${manifest_line%%  *}"
    manifest_relative_path="${manifest_line#*  }"
    if [[ "${manifest_digest}" == "${manifest_line}" ]] ||
        [[ ! "${manifest_digest}" =~ ^[0-9a-f]{64}$ ]]; then
        echo "Invalid line in MANIFEST.sha256: ${manifest_line}" >&2
        exit 1
    fi
    manifest_relative_path="${manifest_relative_path#./}"
    case "${manifest_relative_path}" in
        "" | /* | .. | ../* | */../* | */..)
            echo "Unsafe path in MANIFEST.sha256: ${manifest_relative_path}" >&2
            exit 1
            ;;
    esac
    if [[ -n "${VERIFIED_MODEL_PATHS[${manifest_relative_path}]+x}" ]]; then
        echo "Duplicate path in MANIFEST.sha256: ${manifest_relative_path}" >&2
        exit 1
    fi
    VERIFIED_MODEL_PATHS["${manifest_relative_path}"]=1
    manifest_model_file="${MODEL_PATH}/${manifest_relative_path}"
    if [[ ! -f "${manifest_model_file}" ]] || [[ -L "${manifest_model_file}" ]] ||
        [[ ! -s "${manifest_model_file}" ]]; then
        echo "Manifest entry is not a non-empty regular file: ${manifest_model_file}" >&2
        exit 1
    fi
    if [[ "${manifest_model_file}" -nt "${MANIFEST_VERIFICATION_MARKER}" ]]; then
        echo "Model file changed after manifest verification: ${manifest_model_file}" >&2
        exit 1
    fi
done < "${MODEL_PATH}/MANIFEST.sha256"
while IFS= read -r -d '' staged_model_file; do
    staged_relative_path="${staged_model_file#"${MODEL_PATH}/"}"
    if [[ -z "${VERIFIED_MODEL_PATHS[${staged_relative_path}]+x}" ]]; then
        echo "Unverified model file is not listed in MANIFEST.sha256: ${staged_model_file}" >&2
        exit 1
    fi
done < <(
    find "${MODEL_PATH}" \
        -path "${MODEL_PATH}/.cache" -prune -o \
        \( -type f -o -type l \) \
        ! -path "${MODEL_PATH}/MANIFEST.sha256" \
        ! -path "${MANIFEST_VERIFICATION_MARKER}" \
        -print0
)
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
          --expected-tensor-bytes 145412407296 \
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
          --timeout-seconds 10800 \
          --export-only \
          > '${ARTIFACT_ROOT}/job-export.json'
        test -s '${EXPORT_ROOT}/job/llm_fsdp2_real_training/app_site-1/custom/data/site-1.jsonl'
        test -s '${EXPORT_ROOT}/job/llm_fsdp2_real_training/app_site-2/custom/data/site-2.jsonl'
        python research/llm_fl_stress/real_training/exported_job_preflight.py \
          --job-root '${EXPORT_ROOT}/job/llm_fsdp2_real_training' \
          --timeout-seconds 10800 \
          > '${ARTIFACT_ROOT}/exported-job-preflight.json'
        grep -R -q -- '--state-scope trainable' '${EXPORT_ROOT}/job'
        grep -R -q -- '--timeout-seconds 10800' '${EXPORT_ROOT}/job'
    "

printf '%s\n' \
    "{\"event\":\"real_training_model_manifest_verification\",\"manifest_sha256\":\"${OBSERVED_MANIFEST_SHA256}\",\"status\":\"PASS\"}" \
    > "${ARTIFACT_ROOT}/model-manifest-verification.json"

{
    printf 'job_id=%s\n' "${SLURM_JOB_ID}"
    printf 'status=PASS\n'
    printf 'model_path=%s\n' "${MODEL_PATH}"
    printf 'model_revision=%s\n' "${MODEL_REVISION}"
    printf 'expected_payload_bytes=1755369472\n'
    printf 'max_payload_bytes=2147483648\n'
    printf 'exported_job_timeout_seconds=10800\n'
    printf 'model_manifest_verified=PASS\n'
    printf 'model_manifest_sha256=%s\n' "${OBSERVED_MANIFEST_SHA256}"
    printf 'git_commit=%s\n' "$(git -C "${REPO_ROOT}" rev-parse HEAD)"
} > "${ARTIFACT_ROOT}/manifest.txt"
