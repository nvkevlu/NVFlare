#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=polar,polar3,polar4
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-32b-single-client
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=64
#SBATCH --gpus-per-node=8
#SBATCH --mem=900G
#SBATCH --time=02:00:00
#SBATCH --signal=TERM@300
#SBATCH --no-requeue
#SBATCH --comment=fact_off
#SBATCH --output=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.out
#SBATCH --error=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/logs/%x-%j.err

set -Eeuo pipefail
umask 077

PROJECT_ROOT="${PROJECT_ROOT:-/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b}"
CONTAINER_IMAGE="${PROJECT_ROOT}/containers/pytorch-25.01-py3.sqsh"
RUN_REPO_ROOT="${RUN_REPO_ROOT:-}"
REPO_ROOT="${RUN_REPO_ROOT}"
VENV_DIR="${PROJECT_ROOT}/envs/nvflare-fsdp2"
REQUIREMENTS_LOCK="${VENV_DIR}/requirements.lock"
MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-32B-1818d35814b8"
MODEL_REVISION=1818d35814b8319459f4bd55ed1ac8709630f003
DATASET_PATH="${REPO_ROOT}/research/llm_fl_stress/real_training/data/site-1.jsonl"
EXPERIMENT_RELEASE=2026-07-31-single-client-full-model-32b-v2
REQUIRED_BASE_RELEASE=2026-07-31-full-model-14b-v12
REQUIRED_BASE_COMMIT=27c39f637506f7589c8b4536fd3c8b4e4664b82f
RELEASE_FILE="${REPO_ROOT}/research/llm_fl_stress/real_training/QUALIFICATION_RELEASE"
STATIC_PREFLIGHT_SCRIPT="${REPO_ROOT}/research/llm_fl_stress/real_training/model_structure_preflight.py"
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/32b-full-model-single-client-${SLURM_JOB_ID}"
RESULT_PATH="${ARTIFACT_ROOT}/capacity-experiment.json"
SCRATCH_ROOT="/raid/scratch/${USER}/${SLURM_JOB_ID}/32b-single-client"
EXPECTED_PARAMETERS=32763876352
EXPECTED_TENSOR_COUNT=771
EXPECTED_STATE_PAYLOAD_BYTES=65527752704
EXPECTED_CHECKPOINT_FILE_BYTES=65527841752
MINIMUM_SLURM_MEMORY_MIB=921600
MINIMUM_SLURM_REMAINING_SECONDS=6900
REQUIRED_SLURM_GPUS_ON_NODE=8
SLURM_ALLOCATION_MEMORY_MIB="${SLURM_MEM_PER_NODE:-UNSET}"
SLURM_ALLOCATION_GPUS_ON_NODE="${SLURM_GPUS_ON_NODE:-UNSET}"
SLURM_ALLOCATION_END_TIME_EPOCH="${SLURM_JOB_END_TIME:-UNSET}"
SLURM_ALLOCATION_CHECK_TIME_EPOCH=UNCOMPUTED
SLURM_ALLOCATION_REMAINING_SECONDS=UNCOMPUTED
EXPECTED_HEAD="${EXPECTED_HEAD:-}"
READINESS_ARTIFACT="${READINESS_ARTIFACT:-}"
STATIC_RESULT="${STATIC_RESULT:-${PROJECT_ROOT}/artifacts/32b-single-client-static-${EXPECTED_HEAD}.json}"

mkdir -p "${ARTIFACT_ROOT}"

record_result() {
    status=$?
    trap - EXIT
    if [[ "${status}" == "0" ]]; then
        result=PASS
    else
        result=FAIL
    fi
    model_manifest_sha256="$(sha256sum "${MODEL_PATH}/MANIFEST.sha256" 2>/dev/null | awk '{print $1}' || true)"
    container_manifest_sha256="$(sha256sum "${CONTAINER_IMAGE}.sha256" 2>/dev/null | awk '{print $1}' || true)"
    {
        printf 'job_id=%s\n' "${SLURM_JOB_ID}"
        printf 'status=%s\n' "${result}"
        printf 'exit_code=%s\n' "${status}"
        printf 'host=%s\n' "$(hostname)"
        printf 'model_path=%s\n' "${MODEL_PATH}"
        printf 'model_revision=%s\n' "${MODEL_REVISION}"
        printf 'world_size=8\n'
        printf 'trainable_target=all\n'
        printf 'state_scope=full\n'
        printf 'expected_trainable_parameters=%s\n' "${EXPECTED_PARAMETERS}"
        printf 'expected_tensor_count=%s\n' "${EXPECTED_TENSOR_COUNT}"
        printf 'expected_state_payload_bytes=%s\n' "${EXPECTED_STATE_PAYLOAD_BYTES}"
        printf 'expected_checkpoint_file_bytes=%s\n' "${EXPECTED_CHECKPOINT_FILE_BYTES}"
        printf 'local_steps=6\n'
        printf 'max_length=512\n'
        printf 'required_headroom_mib=0\n'
        printf 'host_projection_mode=report-only\n'
        printf 'experiment_scope=single-client-fsdp2-capacity\n'
        printf 'full_job_memory_gib=900\n'
        printf 'full_job_client_count=1\n'
        printf 'required_fixed_host_headroom_gib=64\n'
        printf 'server_state_copies=1\n'
        printf 'max_model_ready_seconds=0\n'
        printf 'max_work_seconds=0\n'
        printf 'slurm_mem_per_node_mib=%s\n' "${SLURM_ALLOCATION_MEMORY_MIB}"
        printf 'slurm_gpus_on_node=%s\n' "${SLURM_ALLOCATION_GPUS_ON_NODE}"
        printf 'slurm_job_end_time_epoch=%s\n' "${SLURM_ALLOCATION_END_TIME_EPOCH}"
        printf 'slurm_allocation_check_time_epoch=%s\n' "${SLURM_ALLOCATION_CHECK_TIME_EPOCH}"
        printf 'slurm_remaining_seconds_at_check=%s\n' "${SLURM_ALLOCATION_REMAINING_SECONDS}"
        printf 'model_manifest_sha256=%s\n' "${model_manifest_sha256}"
        printf 'container_manifest_sha256=%s\n' "${container_manifest_sha256}"
        printf 'experiment_release=%s\n' "${EXPERIMENT_RELEASE}"
        printf 'required_base_release=%s\n' "${REQUIRED_BASE_RELEASE}"
        printf 'required_base_commit=%s\n' "${REQUIRED_BASE_COMMIT}"
        printf 'expected_head=%s\n' "${EXPECTED_HEAD}"
        printf 'run_repo_root=%s\n' "${RUN_REPO_ROOT}"
        printf 'pythonpath=%s\n' "${PYTHONPATH:-UNSET}"
        printf 'nvflare_expected_source_root=%s\n' "${NVFLARE_EXPECTED_SOURCE_ROOT:-UNSET}"
        printf 'readiness_artifact=%s\n' "${READINESS_ARTIFACT}"
        printf 'readiness_artifact_sha256=%s\n' "$(sha256sum "${READINESS_ARTIFACT}" 2>/dev/null | awk '{print $1}' || true)"
        printf 'static_result=%s\n' "${STATIC_RESULT}"
        printf 'static_result_sha256=%s\n' "$(sha256sum "${STATIC_RESULT}" 2>/dev/null | awk '{print $1}' || true)"
        printf 'requirements_lock_sha256=%s\n' "$(sha256sum "${REQUIREMENTS_LOCK}" 2>/dev/null | awk '{print $1}' || true)"
        printf 'git_commit=%s\n' "$(git -C "${REPO_ROOT}" rev-parse HEAD 2>/dev/null || true)"
    } > "${ARTIFACT_ROOT}/manifest.txt"
    return "${status}"
}
trap record_result EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

validate_slurm_allocation() {
    if [[ ! "${SLURM_ALLOCATION_MEMORY_MIB}" =~ ^[0-9]+$ ]]; then
        echo "SLURM_MEM_PER_NODE must report the actual allocation in MiB." >&2
        exit 1
    fi
    if (( SLURM_ALLOCATION_MEMORY_MIB < MINIMUM_SLURM_MEMORY_MIB )); then
        echo "GPU full-model preflight requires at least ${MINIMUM_SLURM_MEMORY_MIB} MiB; got ${SLURM_ALLOCATION_MEMORY_MIB}." >&2
        exit 1
    fi
    if [[ "${SLURM_ALLOCATION_GPUS_ON_NODE}" != "${REQUIRED_SLURM_GPUS_ON_NODE}" ]]; then
        echo "GPU full-model preflight requires exactly ${REQUIRED_SLURM_GPUS_ON_NODE} allocated GPUs; got ${SLURM_ALLOCATION_GPUS_ON_NODE}." >&2
        exit 1
    fi
    if [[ ! "${SLURM_ALLOCATION_END_TIME_EPOCH}" =~ ^[0-9]+$ ]]; then
        echo "SLURM_JOB_END_TIME must report the allocation end as a Unix timestamp." >&2
        exit 1
    fi
    SLURM_ALLOCATION_CHECK_TIME_EPOCH="$(date +%s)"
    SLURM_ALLOCATION_REMAINING_SECONDS=$((SLURM_ALLOCATION_END_TIME_EPOCH - SLURM_ALLOCATION_CHECK_TIME_EPOCH))
    if (( SLURM_ALLOCATION_REMAINING_SECONDS < MINIMUM_SLURM_REMAINING_SECONDS )); then
        echo "GPU full-model preflight requires at least ${MINIMUM_SLURM_REMAINING_SECONDS} seconds remaining; got ${SLURM_ALLOCATION_REMAINING_SECONDS}." >&2
        exit 1
    fi
}

validate_slurm_allocation

case "${RUN_REPO_ROOT}" in
    "${PROJECT_ROOT}"/repos/NVFlare-runs/*) ;;
    *)
        echo "RUN_REPO_ROOT must name an immutable release worktree under ${PROJECT_ROOT}/repos/NVFlare-runs/." >&2
        exit 1
        ;;
esac
if [[ ! -d "${RUN_REPO_ROOT}" ]]; then
    echo "Immutable release worktree does not exist: ${RUN_REPO_ROOT}" >&2
    exit 1
fi

for path in \
    "${CONTAINER_IMAGE}" \
    "${REPO_ROOT}" \
    "${VENV_DIR}/bin/python" \
    "${REQUIREMENTS_LOCK}" \
    "${MODEL_PATH}" \
    "${DATASET_PATH}" \
    "${STATIC_PREFLIGHT_SCRIPT}"; do
    if [[ ! -e "${path}" ]]; then
        echo "Required path does not exist: ${path}" >&2
        exit 1
    fi
done
if [[ ! "${EXPECTED_HEAD}" =~ ^[0-9a-f]{40}$ ]] ||
    [[ "$(git -C "${REPO_ROOT}" rev-parse HEAD)" != "${EXPECTED_HEAD}" ]]; then
    echo "EXPECTED_HEAD must pin the exact reviewed checkout used for this queued job." >&2
    exit 1
fi
if [[ -n "$(git -C "${REPO_ROOT}" branch --show-current)" ]]; then
    echo "RUN_REPO_ROOT must remain a detached immutable release worktree." >&2
    exit 1
fi
if [[ ! -s "${READINESS_ARTIFACT}" ]]; then
    echo "READINESS_ARTIFACT must name the passing zero-GPU readiness artifact." >&2
    exit 1
fi
if [[ ! -s "${STATIC_RESULT}" ]]; then
    echo "STATIC_RESULT must name the exact passing zero-GPU structure result." >&2
    exit 1
fi
for required_readiness_value in \
    '"status": "PASS"' \
    '"safe_to_submit": true' \
    "\"git_commit\": \"${EXPECTED_HEAD}\"" \
    "\"repo_root\": \"${RUN_REPO_ROOT}\"" \
    "\"pythonpath\": \"${RUN_REPO_ROOT}\"" \
    "\"nvflare_expected_source_root\": \"${RUN_REPO_ROOT}\"" \
    "\"required_base_commit\": \"${REQUIRED_BASE_COMMIT}\""; do
    if ! grep -Fq "${required_readiness_value}" "${READINESS_ARTIFACT}"; then
        echo "Readiness artifact is not bound to this exact release: ${required_readiness_value}" >&2
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
    echo "The staged Qwen2.5-32B revision is not ${MODEL_REVISION}." >&2
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

STATIC_RESULT_SHA256="$(sha256sum "${STATIC_RESULT}" | awk '{print $1}')"
MODEL_MANIFEST_SHA256="$(sha256sum "${MODEL_MANIFEST}" | awk '{print $1}')"
CONTAINER_MANIFEST_SHA256="$(sha256sum "${CONTAINER_CHECKSUM}" | awk '{print $1}')"
REQUIREMENTS_LOCK_SHA256="$(sha256sum "${REQUIREMENTS_LOCK}" | awk '{print $1}')"
for required_readiness_value in \
    "\"static_result_sha256\": \"${STATIC_RESULT_SHA256}\"" \
    "\"model_manifest_sha256\": \"${MODEL_MANIFEST_SHA256}\"" \
    "\"container_manifest_sha256\": \"${CONTAINER_MANIFEST_SHA256}\"" \
    "\"requirements_lock_sha256\": \"${REQUIREMENTS_LOCK_SHA256}\""; do
    if ! grep -Fq "${required_readiness_value}" "${READINESS_ARTIFACT}"; then
        echo "Readiness artifact input changed after validation: ${required_readiness_value}" >&2
        exit 1
    fi
done

if [[ ! -s "${RELEASE_FILE}" ]] || [[ "$(<"${RELEASE_FILE}")" != "${REQUIRED_BASE_RELEASE}" ]]; then
    echo "Checkout does not contain required base qualification release ${REQUIRED_BASE_RELEASE}." >&2
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

export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HOME="${PROJECT_ROOT}/cache/huggingface"
export TOKENIZERS_PARALLELISM=false
export WANDB_DISABLED=true
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export PYTHONPATH="${REPO_ROOT}"
export NVFLARE_EXPECTED_SOURCE_ROOT="${REPO_ROOT}"

srun --kill-on-bad-exit=1 \
    --container-image="${CONTAINER_IMAGE}" \
    --container-mounts="${PROJECT_ROOT}:${PROJECT_ROOT},/raid/scratch:/raid/scratch" \
    bash -lc "
        set -Eeuo pipefail
        source '${VENV_DIR}/bin/activate'
        export PYTHONPATH='${REPO_ROOT}'
        export NVFLARE_EXPECTED_SOURCE_ROOT='${REPO_ROOT}'
        cd '${REPO_ROOT}'
        mkdir -p '${SCRATCH_ROOT}'
        python -c 'from pathlib import Path; import nvflare, sys; observed = Path(nvflare.__file__).resolve().parents[1]; expected = Path(sys.argv[1]).resolve(); assert observed == expected, (observed, expected)' '${REPO_ROOT}'
        python research/llm_fl_stress/real_training/dependency_check.py \
          > '${ARTIFACT_ROOT}/dependency-check.json'
        python '${STATIC_PREFLIGHT_SCRIPT}' \
          --model-name-or-path '${MODEL_PATH}' \
          --model-revision '${MODEL_REVISION}' \
          --expected-hidden-size 5120 \
          --expected-intermediate-size 27648 \
          --expected-num-hidden-layers 64 \
          --expected-num-attention-heads 40 \
          --expected-num-key-value-heads 8 \
          --expected-safetensor-files 17 \
          --expected-tensor-count '${EXPECTED_TENSOR_COUNT}' \
          --expected-parameters '${EXPECTED_PARAMETERS}' \
          --expected-tensor-bytes '${EXPECTED_STATE_PAYLOAD_BYTES}' \
          --expected-checkpoint-file-bytes '${EXPECTED_CHECKPOINT_FILE_BYTES}' \
          --dataset-file '${DATASET_PATH}' \
          --minimum-dataset-records 48 \
          > '${ARTIFACT_ROOT}/static-model-preflight.json'
        grep -q '\"status\": \"PASS\"' '${ARTIFACT_ROOT}/static-model-preflight.json'
        grep -q '\"indexed_tensor_count\": 771' '${ARTIFACT_ROOT}/static-model-preflight.json'
        grep -q '\"physical_checkpoint_file_bytes\": 65527841752' '${ARTIFACT_ROOT}/static-model-preflight.json'
        python research/llm_fl_stress/real_training/capacity_experiment.py \
          --artifact-root '${ARTIFACT_ROOT}' \
          --scratch-root '${SCRATCH_ROOT}' \
          --gpu-count 8 \
          -- \
          python -m torch.distributed.run \
            --standalone \
            --nproc_per_node=8 \
            --max_restarts=0 \
            research/llm_fl_stress/real_training/real_model_fsdp2_gpu_gate.py \
            --model-name-or-path '${MODEL_PATH}' \
            --model-revision '${MODEL_REVISION}' \
            --expected-world-size 8 \
            --trainable-target all \
            --state-scope full \
            --expected-trainable-parameters '${EXPECTED_PARAMETERS}' \
            --expected-tensor-count '${EXPECTED_TENSOR_COUNT}' \
            --expected-payload-bytes '${EXPECTED_STATE_PAYLOAD_BYTES}' \
            --expected-gpu-name-substring A100-SXM4-80GB \
            --local-steps 6 \
            --max-length 512 \
            --timeout-seconds 10800 \
            --required-headroom-mib 0 \
            --full-job-memory-gib 900 \
            --full-job-client-count 1 \
            --required-fixed-host-headroom-gib 64 \
            --server-state-copies 1 \
            --host-projection-mode report-only \
            --max-model-ready-seconds 0 \
            --max-work-seconds 0 \
            --result-path '${RESULT_PATH}'
        grep -q '\"status\": \"PASS\"' '${RESULT_PATH}'
        grep -q '\"status\": \"PASS\"' '${ARTIFACT_ROOT}/qualification.json'
    "
