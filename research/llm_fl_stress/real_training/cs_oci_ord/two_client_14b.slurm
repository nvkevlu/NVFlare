#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=polar,polar3,polar4
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-14b-qualified
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=8
#SBATCH --mem=512G
#SBATCH --time=00:25:00
#SBATCH --signal=TERM@120
#SBATCH --comment=fact_off
#SBATCH --output=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.out
#SBATCH --error=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.err

set -Eeuo pipefail
umask 077

PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"
CONTAINER_IMAGE="${CONTAINER_IMAGE:-${PROJECT_ROOT}/containers/pytorch-25.01-py3.sqsh}"
REPO_ROOT="${REPO_ROOT:-${PROJECT_ROOT}/repos/NVFlare}"
VENV_DIR="${VENV_DIR:-${PROJECT_ROOT}/envs/nvflare-fsdp2}"
GATE_MODEL_PATH="${GATE_MODEL_PATH:-${PROJECT_ROOT}/models/Qwen2.5-1.5B-8faed761d45a}"
TARGET_MODEL_PATH="${TARGET_MODEL_PATH:-${MODEL_PATH:-${PROJECT_ROOT}/models/Qwen2.5-14B-97e1e76335b7}}"
EXPECTED_TARGET_REVISION="${EXPECTED_TARGET_REVISION:-97e1e76335b7017d8f67c08a19d103c0504298c9}"
TARGET_MODEL_REVISION="${TARGET_MODEL_REVISION:-${MODEL_REVISION:-${EXPECTED_TARGET_REVISION}}}"
EXPECTED_TARGET_LABEL="${EXPECTED_TARGET_LABEL:-Qwen2.5-14B}"
EXPECTED_TARGET_HIDDEN_SIZE="${EXPECTED_TARGET_HIDDEN_SIZE:-0}"
EXPECTED_TARGET_INTERMEDIATE_SIZE="${EXPECTED_TARGET_INTERMEDIATE_SIZE:-0}"
EXPECTED_TARGET_NUM_HIDDEN_LAYERS="${EXPECTED_TARGET_NUM_HIDDEN_LAYERS:-0}"
EXPECTED_TARGET_NUM_ATTENTION_HEADS="${EXPECTED_TARGET_NUM_ATTENTION_HEADS:-0}"
EXPECTED_TARGET_NUM_KEY_VALUE_HEADS="${EXPECTED_TARGET_NUM_KEY_VALUE_HEADS:-0}"
EXPECTED_TARGET_MIN_WEIGHT_BYTES="${EXPECTED_TARGET_MIN_WEIGHT_BYTES:-0}"
EXPECTED_TARGET_SAFETENSOR_FILES="${EXPECTED_TARGET_SAFETENSOR_FILES:-0}"
EXPECTED_TARGET_TENSOR_BYTES="${EXPECTED_TARGET_TENSOR_BYTES:-0}"
EXPECTED_TARGET_PAYLOAD_BYTES="${EXPECTED_TARGET_PAYLOAD_BYTES:-0}"
EXPECTED_TARGET_TENSOR_COUNT="${EXPECTED_TARGET_TENSOR_COUNT:-0}"
EXPECTED_TARGET_TRAINABLE_PARAMETERS="${EXPECTED_TARGET_TRAINABLE_PARAMETERS:-0}"
EXPECTED_GPU_NAME_SUBSTRING="${EXPECTED_GPU_NAME_SUBSTRING:-A100-SXM4-80GB}"
REQUIRED_BASE_COMMIT="1be715ed5bc97c83a6771b486c40b75f0b97e4fd"
EXPECTED_BRANCH="codex/llm-fl-real-14b"
REQUIRED_RELEASE="2026-07-31-full-model-14b-v12"
RELEASE_FILE="${REPO_ROOT}/research/llm_fl_stress/real_training/QUALIFICATION_RELEASE"
QUALIFICATION_PROFILE="${QUALIFICATION_PROFILE:-full-state}"

if [[ "${TARGET_MODEL_REVISION}" != "${EXPECTED_TARGET_REVISION}" ]]; then
    echo "The target is pinned to ${EXPECTED_TARGET_LABEL} revision ${EXPECTED_TARGET_REVISION}." >&2
    exit 1
fi
if [[ "${QUALIFICATION_PROFILE}" != "full-state" &&
    "${QUALIFICATION_PROFILE}" != "trainable-multiround" &&
    "${QUALIFICATION_PROFILE}" != "trainable-32b" &&
    "${QUALIFICATION_PROFILE}" != "trainable-72b" &&
    "${QUALIFICATION_PROFILE}" != "full-model-14b" &&
    "${QUALIFICATION_PROFILE}" != "full-model-14b-multiround" ]]; then
    echo "Unsupported qualification profile: ${QUALIFICATION_PROFILE}" >&2
    exit 1
fi
for path in "${CONTAINER_IMAGE}" "${REPO_ROOT}" "${VENV_DIR}" "${GATE_MODEL_PATH}" "${TARGET_MODEL_PATH}"; do
    if [[ ! -e "${path}" ]]; then
        echo "Required path does not exist: ${path}" >&2
        exit 1
    fi
done
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
for model_path in "${GATE_MODEL_PATH}" "${TARGET_MODEL_PATH}"; do
    if [[ ! -s "${model_path}/REVISION" ]]; then
        echo "Staged model is missing a non-empty REVISION file: ${model_path}/REVISION" >&2
        exit 1
    fi
done
if [[ -n "${EXPECTED_GATE_REVISION:-}" ]] &&
    [[ "$(<"${GATE_MODEL_PATH}/REVISION")" != "${EXPECTED_GATE_REVISION}" ]]; then
    echo "The staged gate model does not match ${EXPECTED_GATE_REVISION}." >&2
    exit 1
fi
if [[ "$(<"${TARGET_MODEL_PATH}/REVISION")" != "${EXPECTED_TARGET_REVISION}" ]]; then
    echo "The staged ${EXPECTED_TARGET_LABEL} model does not match ${EXPECTED_TARGET_REVISION}." >&2
    exit 1
fi
if [[ "${NCCL_P2P_DISABLE+x}" == "x" ]]; then
    echo "Refusing inherited NCCL_P2P_DISABLE=${NCCL_P2P_DISABLE}; use cluster NCCL defaults." >&2
    exit 1
fi
if [[ "${SLURM_GPUS_ON_NODE:-8}" =~ ^[0-9]+$ ]] && [[ "${SLURM_GPUS_ON_NODE:-8}" != "8" ]]; then
    echo "This qualification requires exactly 8 allocated GPUs." >&2
    exit 1
fi

GATE_MODEL_REVISION="$(<"${GATE_MODEL_PATH}/REVISION")"
SCRATCH_ROOT="/raid/scratch/${USER}/${SLURM_JOB_ID}"
PRIVATE_ROOT="${SCRATCH_ROOT}/private"
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/${SLURM_JOB_ID}"
mkdir -p "${ARTIFACT_ROOT}"

record_result() {
    status=$?
    trap - EXIT
    {
        printf 'job_id=%s\n' "${SLURM_JOB_ID}"
        printf 'status=%s\n' "${status}"
        printf 'host=%s\n' "$(hostname)"
        printf 'execution_environment=ProdEnv\n'
        printf 'service_topology=localhost-tls-server-plus-two-real-clients\n'
        printf 'qualification_profile=%s\n' "${QUALIFICATION_PROFILE}"
        printf 'gate_model_path=%s\n' "${GATE_MODEL_PATH}"
        printf 'gate_model_revision=%s\n' "${GATE_MODEL_REVISION}"
        printf 'target_model_path=%s\n' "${TARGET_MODEL_PATH}"
        printf 'target_model_revision=%s\n' "${TARGET_MODEL_REVISION}"
        printf 'num_clients=2\n'
        printf 'nproc_per_client=4\n'
        printf 'total_gpu_processes=8\n'
        printf 'transport_timeout_seconds=10800\n'
        if [[ "${QUALIFICATION_PROFILE}" == "full-model-14b-multiround" ]]; then
            printf 'num_rounds=5\n'
            printf 'local_steps=2\n'
            printf 'max_length=512\n'
            printf 'trainable_target=all\n'
            printf 'state_scope=full\n'
            printf 'gate_executed=false\n'
        fi
        if [[ "${QUALIFICATION_PROFILE}" == "full-model-14b" ||
            "${QUALIFICATION_PROFILE}" == "full-model-14b-multiround" ]]; then
            printf 'slurm_mem_per_node_mib=%s\n' "${SLURM_ALLOCATION_MEMORY_MIB:-UNSET}"
            printf 'slurm_gpus_on_node=%s\n' "${SLURM_ALLOCATION_GPUS_ON_NODE:-UNSET}"
            printf 'slurm_job_end_time_epoch=%s\n' "${SLURM_ALLOCATION_END_TIME_EPOCH:-UNSET}"
            printf 'slurm_allocation_check_time_epoch=%s\n' "${SLURM_ALLOCATION_CHECK_TIME_EPOCH:-UNSET}"
            printf 'slurm_remaining_seconds_at_check=%s\n' "${SLURM_ALLOCATION_REMAINING_SECONDS:-UNSET}"
        fi
        printf 'release=%s\n' "${REQUIRED_RELEASE}"
        printf 'git_commit=%s\n' "$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || true)"
    } > "${ARTIFACT_ROOT}/manifest.txt"
    if [[ -d "${PRIVATE_ROOT}" ]] &&
        [[ "${PRIVATE_ROOT}" == "/raid/scratch/${USER}/${SLURM_JOB_ID}/private" ]]; then
        chmod -R u+rwX "${PRIVATE_ROOT}" 2>/dev/null || true
        rm -rf -- "${PRIVATE_ROOT}"
    fi
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
# These low-level F3 flow-control/read/send guards must not undercut the
# reviewed qualification watchdogs. They are inherited by the provisioned
# server, both clients, and their training subprocesses.
export NVFLARE_STREAMING_ACK_WAIT=10800
export NVFLARE_STREAMING_ACK_PROGRESS_TIMEOUT=10800
export NVFLARE_STREAMING_READ_TIMEOUT=10800
export NVFLARE_STREAMING_SEND_TIMEOUT=10800

QUALIFICATION_ARGS=(
    --gate-model-path "${GATE_MODEL_PATH}"
    --gate-model-revision "${GATE_MODEL_REVISION}"
    --target-model-path "${TARGET_MODEL_PATH}"
    --target-model-revision "${TARGET_MODEL_REVISION}"
    --expected-target-hidden-size "${EXPECTED_TARGET_HIDDEN_SIZE}"
    --expected-target-intermediate-size "${EXPECTED_TARGET_INTERMEDIATE_SIZE}"
    --expected-target-num-hidden-layers "${EXPECTED_TARGET_NUM_HIDDEN_LAYERS}"
    --expected-target-num-attention-heads "${EXPECTED_TARGET_NUM_ATTENTION_HEADS}"
    --expected-target-num-key-value-heads "${EXPECTED_TARGET_NUM_KEY_VALUE_HEADS}"
    --expected-target-min-weight-bytes "${EXPECTED_TARGET_MIN_WEIGHT_BYTES}"
    --expected-target-safetensor-files "${EXPECTED_TARGET_SAFETENSOR_FILES}"
    --expected-target-tensor-bytes "${EXPECTED_TARGET_TENSOR_BYTES}"
    --expected-target-payload-bytes "${EXPECTED_TARGET_PAYLOAD_BYTES}"
    --expected-target-tensor-count "${EXPECTED_TARGET_TENSOR_COUNT}"
    --expected-target-trainable-parameters "${EXPECTED_TARGET_TRAINABLE_PARAMETERS}"
    --private-root "${PRIVATE_ROOT}"
    --evidence-root "${ARTIFACT_ROOT}"
    --expected-gpu-name-substring "${EXPECTED_GPU_NAME_SUBSTRING}"
    --profile "${QUALIFICATION_PROFILE}"
    --service-startup-timeout "${SERVICE_STARTUP_TIMEOUT:-90}"
    --gate-ready-timeout "${GATE_READY_TIMEOUT:-300}"
    --gate-stall-timeout "${GATE_STALL_TIMEOUT:-300}"
    --target-ready-timeout "${TARGET_READY_TIMEOUT:-300}"
    --target-stall-timeout "${TARGET_STALL_TIMEOUT:-300}"
)
printf -v QUOTED_QUALIFICATION_ARGS ' %q' "${QUALIFICATION_ARGS[@]}"

QUOTED_READINESS_COMMAND=""
if [[ "${QUALIFICATION_PROFILE}" == "trainable-72b" ||
    "${QUALIFICATION_PROFILE}" == "full-model-14b" ]]; then
    for job_id_name in CONTROL_JOB_ID PREFLIGHT_JOB_ID GPU_PREFLIGHT_JOB_ID; do
        job_id_value="${!job_id_name:-}"
        if [[ ! "${job_id_value}" =~ ^[0-9]+$ ]]; then
            echo "${job_id_name} must be a numeric passing-gate job ID for ${QUALIFICATION_PROFILE}." >&2
            exit 1
        fi
    done
    if [[ "${QUALIFICATION_PROFILE}" == "trainable-72b" ]]; then
        READINESS_SCRIPT=research/llm_fl_stress/real_training/cs_oci_ord/validate_72b_readiness.py
    else
        READINESS_SCRIPT=research/llm_fl_stress/real_training/cs_oci_ord/validate_14b_full_model_readiness.py
    fi
    READINESS_COMMAND=(
        python "${READINESS_SCRIPT}"
        --project-root "${PROJECT_ROOT}"
        --control-job-id "${CONTROL_JOB_ID}"
        --cpu-job-id "${PREFLIGHT_JOB_ID}"
        --gpu-job-id "${GPU_PREFLIGHT_JOB_ID}"
    )
    printf -v QUOTED_READINESS_COMMAND ' %q' "${READINESS_COMMAND[@]}"
fi

srun --kill-on-bad-exit=1 \
    --container-image="${CONTAINER_IMAGE}" \
    --container-mounts="${PROJECT_ROOT}:${PROJECT_ROOT},/raid/scratch:/raid/scratch" \
    bash -lc "
        set -Eeuo pipefail
        source '${VENV_DIR}/bin/activate'
        cd '${REPO_ROOT}'
        if [[ -n '${QUOTED_READINESS_COMMAND}' ]]; then
            ${QUOTED_READINESS_COMMAND} > '${ARTIFACT_ROOT}/allocation-start-readiness.json'
        fi
        python research/llm_fl_stress/real_training/dependency_check.py \
          > '${ARTIFACT_ROOT}/dependency-check.json'
        python research/llm_fl_stress/real_training/qualification.py${QUOTED_QUALIFICATION_ARGS}
    "
