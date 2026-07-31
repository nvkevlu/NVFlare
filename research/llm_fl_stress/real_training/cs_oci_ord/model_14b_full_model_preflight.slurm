#!/usr/bin/env bash
#SBATCH --account=coreai_edgeai_flresearch
#SBATCH --partition=cpu
#SBATCH --job-name=coreai_edgeai_flresearch-kevlu:nvflare-14b-full-model-preflight
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
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
ARTIFACT_ROOT="${PROJECT_ROOT}/artifacts/14b-full-model-preflight-${SLURM_JOB_ID}"
EXPORT_ROOT="/tmp/nvflare-14b-full-model-export-${SLURM_JOB_ID}"
READINESS_SCRIPT="${REPO_ROOT}/research/llm_fl_stress/real_training/cs_oci_ord/validate_14b_full_model_readiness.py"
MINIMUM_SLURM_MEMORY_MIB=131072
MINIMUM_SLURM_REMAINING_SECONDS=3300
SLURM_ALLOCATION_MEMORY_MIB="${SLURM_MEM_PER_NODE:-UNSET}"
SLURM_ALLOCATION_END_TIME_EPOCH="${SLURM_JOB_END_TIME:-UNSET}"
SLURM_ALLOCATION_CHECK_TIME_EPOCH=UNCOMPUTED
SLURM_ALLOCATION_REMAINING_SECONDS=UNCOMPUTED

mkdir -p "${ARTIFACT_ROOT}"

record_result() {
    status=$?
    trap - EXIT
    rm -rf -- "${EXPORT_ROOT}"
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
        printf 'trainable_target=all\n'
        printf 'state_scope=full\n'
        printf 'expected_trainable_parameters=14770033664\n'
        printf 'expected_tensor_count=579\n'
        printf 'expected_payload_bytes=29540067328\n'
        printf 'local_steps=8\n'
        printf 'max_length=512\n'
        printf 'exported_job_timeout_seconds=10800\n'
        printf 'slurm_mem_per_node_mib=%s\n' "${SLURM_ALLOCATION_MEMORY_MIB}"
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
        echo "CPU full-model preflight requires at least ${MINIMUM_SLURM_MEMORY_MIB} MiB; got ${SLURM_ALLOCATION_MEMORY_MIB}." >&2
        exit 1
    fi
    if [[ ! "${SLURM_ALLOCATION_END_TIME_EPOCH}" =~ ^[0-9]+$ ]]; then
        echo "SLURM_JOB_END_TIME must report the allocation end as a Unix timestamp." >&2
        exit 1
    fi
    SLURM_ALLOCATION_CHECK_TIME_EPOCH="$(date +%s)"
    SLURM_ALLOCATION_REMAINING_SECONDS=$((SLURM_ALLOCATION_END_TIME_EPOCH - SLURM_ALLOCATION_CHECK_TIME_EPOCH))
    if (( SLURM_ALLOCATION_REMAINING_SECONDS < MINIMUM_SLURM_REMAINING_SECONDS )); then
        echo "CPU full-model preflight requires at least ${MINIMUM_SLURM_REMAINING_SECONDS} seconds remaining; got ${SLURM_ALLOCATION_REMAINING_SECONDS}." >&2
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
        python research/llm_fl_stress/real_training/dependency_check.py \
          > '${ARTIFACT_ROOT}/dependency-check.json'
        python research/llm_fl_stress/real_training/full_state_server_preflight.py \
          --model-name-or-path '${MODEL_PATH}' \
          --model-revision '${MODEL_REVISION}' \
          --expected-hidden-size 5120 \
          --expected-intermediate-size 13824 \
          --expected-num-hidden-layers 48 \
          --expected-num-attention-heads 40 \
          --expected-num-key-value-heads 8 \
          --expected-safetensor-files 8 \
          --expected-payload-bytes 29540067328 \
          --expected-tensor-count 579 \
          --expected-parameters 14770033664 \
          > '${ARTIFACT_ROOT}/full-state-server-preflight.json'
        python research/llm_fl_stress/real_training/job.py \
          --model-name-or-path '${MODEL_PATH}' \
          --model-revision '${MODEL_REVISION}' \
          --workspace-root '${EXPORT_ROOT}/unused-workspace' \
          --export-root '${EXPORT_ROOT}/job' \
          --num-clients 2 \
          --nproc-per-node 4 \
          --num-rounds 1 \
          --local-steps 8 \
          --max-length 512 \
          --trainable-target all \
          --run-mode train \
          --state-scope full \
          --timeout-seconds 10800 \
          --export-only \
          > '${ARTIFACT_ROOT}/job-export.json'
        JOB_ROOT='${EXPORT_ROOT}/job/llm_fsdp2_real_training'
        test -s \"\${JOB_ROOT}/app_site-1/custom/data/site-1.jsonl\"
        test -s \"\${JOB_ROOT}/app_site-2/custom/data/site-2.jsonl\"
        if cmp -s \
          \"\${JOB_ROOT}/app_site-1/custom/data/site-1.jsonl\" \
          \"\${JOB_ROOT}/app_site-2/custom/data/site-2.jsonl\"; then
            echo 'The two exported site datasets must be distinct.' >&2
            exit 1
        fi
        python research/llm_fl_stress/real_training/exported_job_preflight.py \
          --job-root \"\${JOB_ROOT}\" \
          --timeout-seconds 10800 \
          --expected-trainable-target all \
          --expected-state-scope full \
          --expected-local-steps 8 \
          --expected-max-length 512 \
          --expected-model-revision '${MODEL_REVISION}' \
          > '${ARTIFACT_ROOT}/exported-job-preflight.json'
        grep -R -q -- '--trainable-target all' \"\${JOB_ROOT}\"
        grep -R -q -- '--state-scope full' \"\${JOB_ROOT}\"
        grep -R -q -- '--local-steps 8' \"\${JOB_ROOT}\"
        grep -R -q -- '--max-length 512' \"\${JOB_ROOT}\"
        grep -R -q -- '--timeout-seconds 10800' \"\${JOB_ROOT}\"
        grep -q -- 'model.HFTextModel' \"\${JOB_ROOT}/app_server/config/config_fed_server.json\"
    "
