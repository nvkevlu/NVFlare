#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=polar,polar3,polar4
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-14b-full-model-gpu-gate
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --gpus-per-node=4
#SBATCH --mem=256G
#SBATCH --time=01:00:00
#SBATCH --signal=TERM@300
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
MODEL_PATH="${PROJECT_ROOT}/models/Qwen2.5-14B-97e1e76335b7"
MODEL_REVISION=97e1e76335b7017d8f67c08a19d103c0504298c9
REQUIRED_RELEASE=2026-07-31-full-model-14b-v12
REQUIRED_BASE_COMMIT=a98b517ea63c8181719ff8fd92ab2ca079d915e8
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/14b-full-model-gpu-preflight-${SLURM_JOB_ID}"
RESULT_PATH="${ARTIFACT_ROOT}/capacity-gate.json"
READINESS_SCRIPT="${REPO_ROOT}/research/llm_fl_stress/real_training/cs_oci_ord/validate_14b_full_model_readiness.py"
MINIMUM_SLURM_MEMORY_MIB=262144
MINIMUM_SLURM_REMAINING_SECONDS=3300
REQUIRED_SLURM_GPUS_ON_NODE=4
SLURM_ALLOCATION_MEMORY_MIB="${SLURM_MEM_PER_NODE:-UNSET}"
SLURM_ALLOCATION_GPUS_ON_NODE="${SLURM_GPUS_ON_NODE:-UNSET}"
SLURM_ALLOCATION_END_TIME_EPOCH="${SLURM_JOB_END_TIME:-UNSET}"
SLURM_ALLOCATION_CHECK_TIME_EPOCH=UNCOMPUTED
SLURM_ALLOCATION_REMAINING_SECONDS=UNCOMPUTED

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
        printf 'world_size=4\n'
        printf 'trainable_target=all\n'
        printf 'state_scope=full\n'
        printf 'expected_trainable_parameters=14770033664\n'
        printf 'expected_tensor_count=579\n'
        printf 'expected_payload_bytes=29540067328\n'
        printf 'local_steps=8\n'
        printf 'max_length=512\n'
        printf 'required_headroom_mib=16384\n'
        printf 'full_job_memory_gib=512\n'
        printf 'full_job_client_count=2\n'
        printf 'required_fixed_host_headroom_gib=128\n'
        printf 'server_state_copies=3\n'
        printf 'max_model_ready_seconds=0\n'
        printf 'max_work_seconds=0\n'
        printf 'slurm_mem_per_node_mib=%s\n' "${SLURM_ALLOCATION_MEMORY_MIB}"
        printf 'slurm_gpus_on_node=%s\n' "${SLURM_ALLOCATION_GPUS_ON_NODE}"
        printf 'slurm_job_end_time_epoch=%s\n' "${SLURM_ALLOCATION_END_TIME_EPOCH}"
        printf 'slurm_allocation_check_time_epoch=%s\n' "${SLURM_ALLOCATION_CHECK_TIME_EPOCH}"
        printf 'slurm_remaining_seconds_at_check=%s\n' "${SLURM_ALLOCATION_REMAINING_SECONDS}"
        printf 'model_manifest_sha256=%s\n' "${model_manifest_sha256}"
        printf 'container_manifest_sha256=%s\n' "${container_manifest_sha256}"
        printf 'release=%s\n' "${REQUIRED_RELEASE}"
        printf 'required_base_commit=%s\n' "${REQUIRED_BASE_COMMIT}"
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

for path in "${CONTAINER_IMAGE}" "${REPO_ROOT}" "${VENV_DIR}" "${MODEL_PATH}" "${READINESS_SCRIPT}"; do
    if [[ ! -e "${path}" ]]; then
        echo "Required path does not exist: ${path}" >&2
        exit 1
    fi
done
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

srun --kill-on-bad-exit=1 \
    --container-image="${CONTAINER_IMAGE}" \
    --container-mounts="${PROJECT_ROOT}:${PROJECT_ROOT}" \
    bash -lc "
        set -Eeuo pipefail
        source '${VENV_DIR}/bin/activate'
        cd '${REPO_ROOT}'
        python '${READINESS_SCRIPT}' \
          --project-root '${PROJECT_ROOT}' \
          --static-only \
          > '${ARTIFACT_ROOT}/static-readiness.json'
        python -m torch.distributed.run \
          --standalone \
          --nproc_per_node=4 \
          --max_restarts=0 \
          research/llm_fl_stress/real_training/real_model_fsdp2_gpu_gate.py \
          --model-name-or-path '${MODEL_PATH}' \
          --model-revision '${MODEL_REVISION}' \
          --trainable-target all \
          --state-scope full \
          --expected-trainable-parameters 14770033664 \
          --expected-tensor-count 579 \
          --expected-payload-bytes 29540067328 \
          --expected-gpu-name-substring A100-SXM4-80GB \
          --local-steps 8 \
          --max-length 512 \
          --timeout-seconds 10800 \
          --required-headroom-mib 16384 \
          --full-job-memory-gib 512 \
          --full-job-client-count 2 \
          --required-fixed-host-headroom-gib 128 \
          --server-state-copies 3 \
          --max-model-ready-seconds 0 \
          --max-work-seconds 0 \
          | tee '${RESULT_PATH}'
        grep -q '\"status\": \"PASS\"' '${RESULT_PATH}'
    "
