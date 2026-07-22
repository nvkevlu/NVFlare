# CS-OCI-ORD real-training runbook

This runbook qualifies one real Hugging Face causal language model as a one-client NVFLARE simulation on one
CS-OCI-ORD node. Four A100 80 GB GPUs run FSDP2. The server and rank-zero client exchange a full BF16 state;
training initially updates only the final decoder block using a short embedded deterministic text batch. This is a
real forward/backward/optimizer step for systems qualification, not yet a task-specific dataset experiment.

The workflow is deliberately serial. Submit one step, inspect its artifacts once, and only then submit the next.
Do not run an agent on a compute node, submit Slurm jobs from an agent, use `watch squeue`, create an `squeue`/`sinfo`
polling loop, use `sbatch -W`, or automatically requeue/chained-submit these qualification jobs.

## Fixed paths and endpoints

The quota result confirms this persistent project path:

```text
/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch
```

Use this private per-user root inside it:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
```

CS-OCI-ORD provides four Data Copier endpoints:

```text
cs-oci-ord-dc-01.nvidia.com
cs-oci-ord-dc-02.nvidia.com
cs-oci-ord-dc-03.nvidia.com
cs-oci-ord-dc-04.nvidia.com
```

Use a Data Copier directly for `rsync`, model download, checksums, and Enroot import. Do not stage large files
through a login node. The commands below use `dc-02`; any healthy DC host is equivalent.

## 1. Create the persistent layout

Run this from a local terminal, not from a compute allocation:

```bash
ssh kevlu@cs-oci-ord-dc-02.nvidia.com
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
mkdir -p "$PROJECT_ROOT"/{artifacts,cache/huggingface,containers,enroot/cache,enroot/images,envs,incoming,jobs,logs,models,repos}
chmod 700 "$PROJECT_ROOT"
df -h "$PROJECT_ROOT"
fs-quota-status
exit
```

Keep repositories, containers, environments, caches, models, logs, and results under `PROJECT_ROOT`. The user
quota on `/home`, `/admin`, and `/lustre/fsw` is only 10 GB.

## 2. Transfer this exact Git branch

A Git bundle is one resumable file and avoids creating thousands of small files during the network transfer.
After the implementation commit exists, run on the local Mac:

```bash
LOCAL_REPO=/Users/kevlu/Documents/codex/worktrees/secondcopynvflare-14b
BUNDLE=/private/tmp/nvflare-14b.bundle
git -C "$LOCAL_REPO" status --short
git -C "$LOCAL_REPO" bundle create "$BUNDLE" codex/llm-fl-real-14b
git -C "$LOCAL_REPO" bundle verify "$BUNDLE"
(cd /private/tmp && shasum -a 256 nvflare-14b.bundle > nvflare-14b.bundle.sha256)
rsync -ah --partial --append-verify --info=progress2 \
  "$BUNDLE" "$BUNDLE.sha256" \
  kevlu@cs-oci-ord-dc-02.nvidia.com:/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/incoming/
```

If interrupted, rerun the same `rsync`; the bundle is immutable and `--append-verify` resumes it. Then verify and
clone on the DC node:

```bash
ssh kevlu@cs-oci-ord-dc-02.nvidia.com
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
cd "$PROJECT_ROOT/incoming"
sha256sum --check nvflare-14b.bundle.sha256
git clone nvflare-14b.bundle "$PROJECT_ROOT/repos/NVFlare"
git -C "$PROJECT_ROOT/repos/NVFlare" switch codex/llm-fl-real-14b
git -C "$PROJECT_ROOT/repos/NVFlare" status --short --branch
git -C "$PROJECT_ROOT/repos/NVFlare" rev-parse HEAD
```

For a later update, create a new immutable bundle name containing the commit ID, transfer it, and fetch that bundle
into the existing clone. Do not overwrite a bundle while `rsync` is resuming it.

## 3. Import one x86 container on a Data Copier

The checked-in environment targets PyTorch 2.12 with cu126. The CUDA 12.x family is compatible with the cluster's
R535 data-center driver, but the one-GPU preflight below is the acceptance test. Importing once to Lustre prevents
each GPU job from pulling a registry image.

On a DC node with Enroot credentials already configured:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export ENROOT_CACHE_PATH="$PROJECT_ROOT/enroot/cache"
export ENROOT_DATA_PATH="$PROJECT_ROOT/enroot/images"
export ENROOT_TEMP_PATH=/tmp
mkdir -p "$ENROOT_CACHE_PATH" "$ENROOT_DATA_PATH"
enroot import \
  -o "$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh" \
  -- docker://nvcr.io#nvidia/pytorch:25.01-py3
sha256sum "$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh" \
  > "$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh.sha256"
```

Do not run `enroot import` on a login node. If NVCR requests authentication, add the token to the private Enroot
credentials file described by the MARS container guide; never put a token in this repository or an `sbatch` script.

## 4. Build the Python environment on a CPU node

The CPU preparation job creates a versioned environment on Lustre, installs the local NVFLARE branch, runs
`pip check`, and records `requirements.lock`. It requests no GPU.

From a login-node shell, run manually:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
cd "$PROJECT_ROOT/repos/NVFlare"
sbatch research/llm_fl_stress/real_training/cs_oci_ord/prepare_env.slurm
```

Record the returned job ID. Check it once after a reasonable interval rather than polling:

```bash
sacct -j <JOB_ID> --format=JobID,State,Elapsed,ExitCode,MaxRSS -X
sed -n '1,240p' "$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-env-<JOB_ID>.out"
```

The environment script refuses to replace an existing environment. Use a new `VENV_DIR` for a changed lock rather
than mutating a previously qualified environment.

## 5. Stage model snapshots without a GPU

Use the prepared environment inside the same container on a DC node. A virtual environment created inside the
container should not be executed directly on the DC host. Always pin a full Hugging Face revision SHA, and keep the
GPU jobs offline. Start with a small Qwen2.5 checkpoint for the end-to-end qualification, then download the 14B
snapshot.

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
enroot start --mount "$PROJECT_ROOT:$PROJECT_ROOT" "$CONTAINER_IMAGE"

# The remaining commands in this block run inside the container.
source "$PROJECT_ROOT/envs/nvflare-fsdp2/bin/activate"
export HF_HOME="$PROJECT_ROOT/cache/huggingface"

hf download Qwen/Qwen2.5-1.5B \
  --revision <FULL_1_5B_REVISION_SHA> \
  --local-dir "$PROJECT_ROOT/models/Qwen2.5-1.5B-<SHORT_SHA>"

hf download Qwen/Qwen2.5-14B \
  --revision <FULL_14B_REVISION_SHA> \
  --local-dir "$PROJECT_ROOT/models/Qwen2.5-14B-<SHORT_SHA>"
exit
```

Generate a manifest after each completed download:

```bash
MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-14B-<SHORT_SHA>"
(cd "$MODEL_PATH" && find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 sha256sum) \
  > "$MODEL_PATH/MANIFEST.sha256"
(cd "$MODEL_PATH" && sha256sum --check MANIFEST.sha256)
du -sh "$MODEL_PATH"
```

Qwen snapshots contain a small number of large shards, so leaving them unpacked is appropriate. Avoid copying an
expanded package cache or dataset containing millions of small files to Lustre.

## 6. Validate and export without allocating a GPU

Run on a DC or VS Code node inside the saved container:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-1.5B-<SHORT_SHA>"
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
enroot start --mount "$PROJECT_ROOT:$PROJECT_ROOT" "$CONTAINER_IMAGE"

# The remaining commands in this block run inside the container.
source "$PROJECT_ROOT/envs/nvflare-fsdp2/bin/activate"
cd "$PROJECT_ROOT/repos/NVFlare"

python research/llm_fl_stress/real_training/job.py \
  --model-name-or-path "$MODEL_PATH" \
  --workspace-root "$PROJECT_ROOT/jobs/offline-validation-workspace" \
  --export-root "$PROJECT_ROOT/jobs/offline-validation-export" \
  --nproc-per-node 4 \
  --run-mode train \
  --validate-only

python research/llm_fl_stress/real_training/job.py \
  --model-name-or-path "$MODEL_PATH" \
  --workspace-root "$PROJECT_ROOT/jobs/offline-export-workspace" \
  --export-root "$PROJECT_ROOT/jobs/offline-export" \
  --nproc-per-node 4 \
  --run-mode train \
  --export-only
exit
```

Validation rejects a remote model identifier or a snapshot missing config, tokenizer, or weight files. The GPU job
also sets `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`, so an allocation cannot be wasted waiting on a download.

## 7. Manual GPU qualification ladder

Every stage is a separate manual decision. The batch scripts use non-interactive `polar,polar3,polar4` partitions,
set `--comment=fact_off`, request partial nodes, specify GPU count, and never request `--exclusive`.

1. One GPU, three minutes: container, driver, Python, package, and CUDA visibility.

   ```bash
   sbatch research/llm_fl_stress/real_training/cs_oci_ord/container_preflight.slurm
   ```

2. Four GPUs, five minutes: tiny deterministic FSDP2 bridge load, optimizer step, export, and NVLink/NCCL defaults.

   ```bash
   sbatch research/llm_fl_stress/real_training/cs_oci_ord/fsdp2_gate.slurm
   ```

3. Four GPUs, small real model: one full NVFLARE round and one final-decoder-layer optimizer step. Override the
   requested walltime to 15 minutes until measured otherwise.

   ```bash
   export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-1.5B-<SHORT_SHA>"
   sbatch --time=00:15:00 --mem=128G --cpus-per-task=16 \
     --export=ALL,MODEL_PATH="$MODEL_PATH",RUN_MODE=train \
     research/llm_fl_stress/real_training/cs_oci_ord/real_training.slurm
   ```

4. Four GPUs, 14B exchange only: real model construction plus full rank-zero load/export, but no gradients or
   optimizer state. This provides the 14B CPU/GPU memory baseline.

   ```bash
   export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-14B-<SHORT_SHA>"
   sbatch --time=00:20:00 --export=ALL,MODEL_PATH="$MODEL_PATH",RUN_MODE=exchange-only \
     research/llm_fl_stress/real_training/cs_oci_ord/real_training.slurm
   ```

5. Four GPUs, 14B real training: one full NVFLARE round and one final-decoder-layer optimizer step. Set the walltime
   from the measured exchange-only duration plus a conservative training/archive margin; 30 minutes is the initial
   cap, not a reason to occupy the allocation after completion.

   ```bash
   export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-14B-<SHORT_SHA>"
   sbatch --time=00:30:00 --export=ALL,MODEL_PATH="$MODEL_PATH",RUN_MODE=train,LOCAL_STEPS=1,TRAINABLE_TARGET=last-layer \
     research/llm_fl_stress/real_training/cs_oci_ord/real_training.slurm
   ```

Never carry the leased A16 workaround `NCCL_P2P_DISABLE=1` into CS-OCI-ORD. The scripts fail closed if it is present
and otherwise preserve the cluster's NCCL defaults.

## 8. Decide whether a stage passed

For each job, use one accounting query and inspect its log/artifact directory:

```bash
sacct -j <JOB_ID> --format=JobID,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X
ls -lh "$PROJECT_ROOT/artifacts/<JOB_ID>"
tar -tf "$PROJECT_ROOT/artifacts/<JOB_ID>/run.tar" | head
```

Advance only when:

- the Slurm state is `COMPLETED` with exit code `0:0`;
- the environment check or FSDP2 gate prints a JSON `PASS` record;
- all requested GPUs have the expected A100 identity;
- no NCCL, CUDA OOM, timeout, or NVFLARE error is present;
- the real-training client reports finite loss in train mode and a positive `selected_max_abs_change`;
- rank-zero load/export payload size matches the model scale; and
- the archived workspace and manifest exist on Lustre.

If a job fails, do not automatically resubmit it. Diagnose from the saved log and artifact once, change one cause,
and then make a new manual submission.
