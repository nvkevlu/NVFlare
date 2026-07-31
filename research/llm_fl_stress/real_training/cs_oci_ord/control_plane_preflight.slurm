#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=cpu
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-control-plane
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:15:00
#SBATCH --no-requeue
#SBATCH --comment=fact_off
#SBATCH --output=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.out
#SBATCH --error=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.err

set -Eeuo pipefail
umask 077

PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"
CONTAINER_IMAGE="${PROJECT_ROOT}/containers/pytorch-25.01-py3.sqsh"
REPO_ROOT="${PROJECT_ROOT}/repos/NVFlare"
VENV_DIR="${PROJECT_ROOT}/envs/nvflare-fsdp2"
GATE_MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-1.5B-8faed761d45a"
GATE_MODEL_REVISION=8faed761d45a263340a0528343f099c05c9a4323
# A control-plane-only qualification does not load a target model. The
# parser's required target arguments reuse the pinned gate snapshot.
TARGET_MODEL_PATH="${GATE_MODEL_PATH}"
TARGET_MODEL_REVISION="${GATE_MODEL_REVISION}"
REQUIRED_BASE_COMMIT="1be715ed5bc97c83a6771b486c40b75f0b97e4fd"
EXPECTED_BRANCH="codex/llm-fl-real-14b"
REQUIRED_RELEASE="2026-07-31-full-model-14b-v12"
RELEASE_FILE="${REPO_ROOT}/research/llm_fl_stress/real_training/QUALIFICATION_RELEASE"
PRIVATE_ROOT="/tmp/nvflare-control-plane-${SLURM_JOB_ID}"
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/control-plane-${SLURM_JOB_ID}"
EXPORT_ROOT="/tmp/nvflare-trainable-export-${SLURM_JOB_ID}"

for path in "${CONTAINER_IMAGE}" "${REPO_ROOT}" "${VENV_DIR}" "${GATE_MODEL_PATH}"; do
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
OBSERVED_BRANCH="$(git -C "${REPO_ROOT}" branch --show-current)"
if [[ "${OBSERVED_BRANCH}" != "${EXPECTED_BRANCH}" ]]; then
    echo "Expected branch ${EXPECTED_BRANCH}, found ${OBSERVED_BRANCH:-detached HEAD}." >&2
    exit 1
fi
if ! git -C "${REPO_ROOT}" merge-base --is-ancestor "${REQUIRED_BASE_COMMIT}" HEAD; then
    echo "Checkout does not contain required production qualification base ${REQUIRED_BASE_COMMIT}." >&2
    exit 1
fi
if [[ ! -s "${RELEASE_FILE}" ]] || [[ "$(<"${RELEASE_FILE}")" != "${REQUIRED_RELEASE}" ]]; then
    echo "Checkout does not contain required qualification release ${REQUIRED_RELEASE}." >&2
    exit 1
fi
GIT_STATUS="$(git -C "${REPO_ROOT}" status --porcelain --untracked-files=all)"
if [[ -n "${GIT_STATUS}" ]]; then
    echo "Refusing a dirty checkout:" >&2
    printf '%s\n' "${GIT_STATUS}" >&2
    exit 1
fi
if [[ ! -s "${GATE_MODEL_PATH}/REVISION" ]] ||
    [[ "$(<"${GATE_MODEL_PATH}/REVISION")" != "${GATE_MODEL_REVISION}" ]]; then
    echo "The staged gate model revision does not match ${GATE_MODEL_REVISION}." >&2
    exit 1
fi
mkdir -p "${ARTIFACT_ROOT}"

export NVFLARE_STREAMING_ACK_WAIT=10800
export NVFLARE_STREAMING_ACK_PROGRESS_TIMEOUT=10800
export NVFLARE_STREAMING_READ_TIMEOUT=10800
export NVFLARE_STREAMING_SEND_TIMEOUT=10800

record_result() {
    status=$?
    trap - EXIT
    rm -rf -- "${EXPORT_ROOT}"
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
        printf 'model_path=%s\n' "${GATE_MODEL_PATH}"
        printf 'model_revision=%s\n' "${GATE_MODEL_REVISION}"
        printf 'operation_timeout_seconds=10800\n'
        printf 'transport_timeout_seconds=10800\n'
        printf 'service_startup_timeout_seconds=300\n'
        printf 'git_commit=%s\n' "$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || true)"
    } > "${ARTIFACT_ROOT}/manifest.txt"
    return "${status}"
}
trap record_result EXIT

srun --kill-on-bad-exit=1 \
    --container-image="${CONTAINER_IMAGE}" \
    --container-mounts="${PROJECT_ROOT}:${PROJECT_ROOT}" \
    bash -lc "
        set -Eeuo pipefail
        source '${VENV_DIR}/bin/activate'
        cd '${REPO_ROOT}'
        python research/llm_fl_stress/real_training/fsdp2_trainable_cpu_gate.py \
          > '${ARTIFACT_ROOT}/fsdp2-trainable-cpu-gate.json'
        python research/llm_fl_stress/real_training/trainable_server_preflight.py \
          --model-name-or-path '${GATE_MODEL_PATH}' \
          --model-revision '${GATE_MODEL_REVISION}' \
          > '${ARTIFACT_ROOT}/trainable-server-preflight.json'
        python research/llm_fl_stress/real_training/job.py \
          --model-name-or-path '${GATE_MODEL_PATH}' \
          --model-revision '${GATE_MODEL_REVISION}' \
          --workspace-root '${EXPORT_ROOT}/unused-workspace' \
          --export-root '${EXPORT_ROOT}/job' \
          --num-clients 2 \
          --nproc-per-node 4 \
          --num-rounds 2 \
          --local-steps 4 \
          --trainable-target last-layer \
          --run-mode train \
          --state-scope trainable \
          --timeout-seconds 10800 \
          --export-only \
          > '${ARTIFACT_ROOT}/trainable-export-validation.json'
        test -s '${EXPORT_ROOT}/job/llm_fsdp2_real_training/app_site-1/custom/data/site-1.jsonl'
        test -s '${EXPORT_ROOT}/job/llm_fsdp2_real_training/app_site-2/custom/data/site-2.jsonl'
        python research/llm_fl_stress/real_training/exported_job_preflight.py \
          --job-root '${EXPORT_ROOT}/job/llm_fsdp2_real_training' \
          --timeout-seconds 10800 \
          > '${ARTIFACT_ROOT}/exported-job-preflight.json'
        python research/llm_fl_stress/real_training/qualification.py \
          --gate-model-path '${GATE_MODEL_PATH}' \
          --gate-model-revision '${GATE_MODEL_REVISION}' \
          --target-model-path '${TARGET_MODEL_PATH}' \
          --target-model-revision '${TARGET_MODEL_REVISION}' \
          --private-root '${PRIVATE_ROOT}' \
          --evidence-root '${ARTIFACT_ROOT}' \
          --service-startup-timeout 300 \
          --control-plane-only
    "
