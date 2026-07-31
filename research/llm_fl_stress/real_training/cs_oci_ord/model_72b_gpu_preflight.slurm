#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=polar,polar3,polar4
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-72b-gpu-gate
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --gpus-per-node=4
#SBATCH --mem=900G
#SBATCH --time=02:00:00
#SBATCH --signal=TERM@300
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
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/72b-gpu-preflight-${SLURM_JOB_ID}"
RESULT_PATH="${ARTIFACT_ROOT}/capacity-gate.json"

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
MODEL_MANIFEST="${MODEL_PATH}/MANIFEST.sha256"
MODEL_VERIFICATION_MARKER="${MODEL_MANIFEST}.verified"
for path in "${MODEL_MANIFEST}" "${MODEL_VERIFICATION_MARKER}"; do
    if [[ ! -s "${path}" ]]; then
        echo "Required model verification file is missing or empty: ${path}" >&2
        exit 1
    fi
done
EXPECTED_MODEL_MANIFEST_SHA256="$(awk 'NR == 1 {print $1}' "${MODEL_VERIFICATION_MARKER}")"
OBSERVED_MODEL_MANIFEST_SHA256="$(sha256sum "${MODEL_MANIFEST}" | awk '{print $1}')"
if [[ ! "${EXPECTED_MODEL_MANIFEST_SHA256}" =~ ^[0-9a-f]{64}$ ]] ||
    [[ "${EXPECTED_MODEL_MANIFEST_SHA256}" != "${OBSERVED_MODEL_MANIFEST_SHA256}" ]]; then
    echo "Model verification marker does not match ${MODEL_MANIFEST}." >&2
    exit 1
fi
if [[ "${MODEL_MANIFEST}" -nt "${MODEL_VERIFICATION_MARKER}" ]]; then
    echo "Model manifest changed after verification." >&2
    exit 1
fi
while IFS= read -r manifest_line; do
    manifest_digest="${manifest_line%%  *}"
    manifest_relative_path="${manifest_line#*  }"
    if [[ "${manifest_digest}" == "${manifest_line}" ]] ||
        [[ ! "${manifest_digest}" =~ ^[0-9a-f]{64}$ ]]; then
        echo "Invalid line in model manifest: ${manifest_line}" >&2
        exit 1
    fi
    manifest_relative_path="${manifest_relative_path#./}"
    case "${manifest_relative_path}" in
        "" | /* | .. | ../* | */../* | */..)
            echo "Unsafe path in model manifest: ${manifest_relative_path}" >&2
            exit 1
            ;;
    esac
    manifest_model_file="${MODEL_PATH}/${manifest_relative_path}"
    if [[ ! -f "${manifest_model_file}" ]] || [[ -L "${manifest_model_file}" ]] ||
        [[ ! -s "${manifest_model_file}" ]]; then
        echo "Manifest entry is not a non-empty regular file: ${manifest_model_file}" >&2
        exit 1
    fi
    if [[ "${manifest_model_file}" -nt "${MODEL_VERIFICATION_MARKER}" ]]; then
        echo "Model file changed after verification: ${manifest_model_file}" >&2
        exit 1
    fi
done < "${MODEL_MANIFEST}"
UNVERIFIED_MODEL_FILE="$(
    find "${MODEL_PATH}" \
        -path "${MODEL_PATH}/.cache" -prune -o \
        \( -type f -o -type l \) \
        ! -path "${MODEL_MANIFEST}" \
        ! -path "${MODEL_VERIFICATION_MARKER}" \
        -newer "${MODEL_VERIFICATION_MARKER}" \
        -print -quit
)"
if [[ -n "${UNVERIFIED_MODEL_FILE}" ]]; then
    echo "Model path changed after verification: ${UNVERIFIED_MODEL_FILE}" >&2
    exit 1
fi
if [[ ! -s "${RELEASE_FILE}" ]] || [[ "$(<"${RELEASE_FILE}")" != "${REQUIRED_RELEASE}" ]]; then
    echo "Checkout does not contain required qualification release ${REQUIRED_RELEASE}." >&2
    exit 1
fi
if [[ "$(git -C "${REPO_ROOT}" branch --show-current)" != "${EXPECTED_BRANCH}" ]]; then
    echo "GPU preflight requires branch ${EXPECTED_BRANCH}." >&2
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
if [[ "${NCCL_P2P_DISABLE+x}" == "x" ]]; then
    echo "Refusing inherited NCCL_P2P_DISABLE=${NCCL_P2P_DISABLE}; use cluster NCCL defaults." >&2
    exit 1
fi
if [[ "${SLURM_GPUS_ON_NODE:-4}" =~ ^[0-9]+$ ]] && [[ "${SLURM_GPUS_ON_NODE:-4}" != "4" ]]; then
    echo "The real-model capacity gate requires exactly 4 allocated GPUs." >&2
    exit 1
fi

mkdir -p "${ARTIFACT_ROOT}"

record_result() {
    status=$?
    trap - EXIT
    if [[ "${status}" == "0" ]]; then
        result=PASS
    else
        result=FAIL
    fi
    {
        printf 'job_id=%s\n' "${SLURM_JOB_ID}"
        printf 'status=%s\n' "${result}"
        printf 'exit_code=%s\n' "${status}"
        printf 'host=%s\n' "$(hostname)"
        printf 'model_path=%s\n' "${MODEL_PATH}"
        printf 'model_revision=%s\n' "${MODEL_REVISION}"
        printf 'world_size=4\n'
        printf 'expected_payload_bytes=1755369472\n'
        printf 'required_headroom_mib=16384\n'
        printf 'full_job_memory_gib=1600\n'
        printf 'full_job_client_count=2\n'
        printf 'required_fixed_host_headroom_gib=128\n'
        printf 'max_model_ready_seconds=2400\n'
        printf 'max_work_seconds=1200\n'
        printf 'git_commit=%s\n' "$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || true)"
    } > "${ARTIFACT_ROOT}/manifest.txt"
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

srun --kill-on-bad-exit=1 \
    --container-image="${CONTAINER_IMAGE}" \
    --container-mounts="${PROJECT_ROOT}:${PROJECT_ROOT}" \
    bash -lc "
        set -Eeuo pipefail
        source '${VENV_DIR}/bin/activate'
        cd '${REPO_ROOT}'
        python -m torch.distributed.run \
          --standalone \
          --nproc_per_node=4 \
          --max_restarts=0 \
          research/llm_fl_stress/real_training/real_model_fsdp2_gpu_gate.py \
          --model-name-or-path '${MODEL_PATH}' \
          --model-revision '${MODEL_REVISION}' \
          --expected-payload-bytes 1755369472 \
          --expected-gpu-name-substring A100-SXM4-80GB \
          --local-steps 2 \
          --max-length 128 \
          --timeout-seconds 7200 \
          --required-headroom-mib 16384 \
          --full-job-memory-gib 1600 \
          --full-job-client-count 2 \
          --required-fixed-host-headroom-gib 128 \
          --max-model-ready-seconds 2400 \
          --max-work-seconds 1200 \
          | tee '${RESULT_PATH}'
        grep -q '\"status\": \"PASS\"' '${RESULT_PATH}'
    "
