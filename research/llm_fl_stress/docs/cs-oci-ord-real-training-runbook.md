# CS-OCI-ORD real-training runbook

This is the reproducible procedure used to qualify real Qwen2.5 training through NVFLARE on CS-OCI-ORD. One
NVFLARE client and server run in `SimEnv` on one Slurm node; four A100 80 GB GPUs run the client through PyTorch
FSDP2. Rank zero receives and loads the full BF16 global state, all ranks perform the selected work, and rank zero
exports and sends the full state back to the server.

The qualification uses a deterministic embedded text batch and updates only the last decoder block. It proves the
real model, forward/backward/optimizer path, FSDP2 state bridge, full-state NVFLARE exchange, aggregation, and
persistence. It is not yet a task-specific dataset experiment or a multi-node/multi-client deployment.

The measured July 22 results, including exact job IDs and resource telemetry, are in the
[qualification record](cs-oci-ord-real-training-qualification-2026-07-22.md).

## Operating rules

- Submit one stage manually, inspect it once, and only then advance to the next stage.
- Use Data Copier nodes for large transfers, container import, model download, and checksums.
- Use a CPU Slurm job for environment construction and compute allocations only for GPU validation/training.
- Keep GPU jobs offline: model, container, environment, and source must already exist on Lustre.
- Do not run an autonomous agent on a compute node or let one submit/requeue jobs.
- Do not use `watch squeue`, scheduler polling loops, `sbatch -W`, automatic requeue, or automatic chained
  submissions. CS-OCI-ORD rate-limits Slurm RPCs to a burst of 100 and a sustained refill of two per second.
- Do not request an exclusive node. The checked-in scripts use partial nodes and `--comment=fact_off`.
- Never put an HF/NVCR token in Git, a recipe argument, an exported job, an `sbatch` script, or a log.

## Qualified stack and fixed paths

The July 22 qualification used:

| Component | Qualified value |
| --- | --- |
| Cluster/account | `cs-oci-ord` / `coreai_edgeai_flresearch` |
| GPU | 4 x NVIDIA A100-SXM4-80GB |
| Container | `nvcr.io/nvidia/pytorch:25.01-py3` |
| Container file | `pytorch-25.01-py3.sqsh` (approximately 25 GB) |
| PyTorch | `2.12.0+cu126` |
| Torchvision | `0.27.0+cu126` |
| Transformers | `4.57.6` |
| NCCL in GPU gate | `2.29.3` |
| Slurm partitions | `polar,polar3,polar4` for GPU jobs; `cpu` for environment preparation |

A physical GPU node has eight A100 80 GB GPUs, 2 TB system RAM, third-generation NVLink, and local NVMe. These
jobs request four GPUs and 512 GB RAM on a partial node, so they do not reserve the unused half. CS-OCI-ORD uses
partition-based scheduling; no `--qos` is required. The general-use `polar`, `polar3`, and `polar4` partitions have
a four-hour maximum, while the qualification requests at most 30 minutes.

Set these variables in each new shell; exports do not survive SSH sessions:

```bash
export PROJECT_ACCOUNT=coreai_edgeai_flresearch
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
export VENV_DIR="$PROJECT_ROOT/envs/nvflare-fsdp2"
```

The project-level persistent path is:

```text
/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch
```

The observed quotas on July 22 were 250 TB and 25 million inodes for the user on `/lustre/fs11`, and 100 TB and
50 million inodes for the project directory. At that time, the project used 26.9 TB and 6.66 million inodes. By
contrast, `/home`, `/admin`, and `/lustre/fsw` each had only a 10 GB user quota, so none is suitable for this setup.

Each compute job uses `/raid/scratch/$USER/$SLURM_JOB_ID` for its live workspace. That local NVMe path is fast and
ephemeral: the cluster clears it between jobs. The batch trap copies the workspace back to persistent Lustre as
`$PROJECT_ROOT/artifacts/$SLURM_JOB_ID/run.tar`. A compute-node result that was not archived is not durable.

## 1. Confirm access and create the persistent layout

Use a login node for light administration and Slurm submission:

```bash
ssh kevlu@cs-oci-ord-login-03.nvidia.com
sacctmgr -nP show assoc where user="$(whoami)" format=account
fs-quota-status
```

CS-OCI-ORD provides four Data Copier endpoints. Spread work across healthy endpoints rather than always choosing
`-01`:

```text
cs-oci-ord-dc-01.nvidia.com
cs-oci-ord-dc-02.nvidia.com
cs-oci-ord-dc-03.nvidia.com
cs-oci-ord-dc-04.nvidia.com
```

Login nodes are limited to one CPU and 30 GB RAM; Data Copier and dedicated VS Code nodes are limited to two CPUs
and 60 GB RAM. Do not run VS Code on a login or Data Copier node. Use the dedicated VS Code nodes or the site's
NVPark workflow when interactive development is needed.

Create the layout from a Data Copier shell:

```bash
ssh kevlu@cs-oci-ord-dc-02.nvidia.com
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
mkdir -p "$PROJECT_ROOT"/{artifacts,cache/huggingface,containers,enroot/cache,enroot/images,envs,incoming,jobs,logs,models,repos}
chmod 700 "$PROJECT_ROOT"
df -h "$PROJECT_ROOT"
fs-quota-status
exit
```

Login nodes are for control-plane work. Data Copier nodes are the correct place for `rsync`, Hugging Face
downloads, large checksums, and Enroot import. Neither is a substitute for a Slurm compute allocation.

The cluster can block GPU submission when individual stale storage reaches 15 TiB. This qualification is far below
that threshold, but old model snapshots, 28 GB run archives, containers, and caches should still be reviewed and
removed through the approved storage-cleanup process when they are no longer needed.

## 2. Transfer the Git branch

### Initial transfer

A Git bundle is one resumable file and avoids transferring the repository as thousands of small files. On the
local Mac:

```bash
export LOCAL_REPO=/Users/kevlu/Documents/codex/worktrees/secondcopynvflare-14b
export BUNDLE=/private/tmp/nvflare-14b.bundle

git -C "$LOCAL_REPO" status --short --branch
git -C "$LOCAL_REPO" bundle create "$BUNDLE" codex/llm-fl-real-14b
git -C "$LOCAL_REPO" bundle verify "$BUNDLE"
(cd /private/tmp && shasum -a 256 nvflare-14b.bundle > nvflare-14b.bundle.sha256)

rsync -avP \
  "$BUNDLE" "$BUNDLE.sha256" \
  kevlu@cs-oci-ord-dc-02.nvidia.com:/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/incoming/
```

The macOS system `rsync` does not support `--append-verify` or `--info=progress2`. Use `-avP`; `-P` is the portable
form of `--partial --progress`. If interrupted, rerun the identical command and verify the checksum before use.

On the Data Copier:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
cd "$PROJECT_ROOT/incoming"
sha256sum --check nvflare-14b.bundle.sha256
git clone nvflare-14b.bundle "$PROJECT_ROOT/repos/NVFlare"
git -C "$PROJECT_ROOT/repos/NVFlare" switch codex/llm-fl-real-14b
git -C "$PROJECT_ROOT/repos/NVFlare" status --short --branch
git -C "$PROJECT_ROOT/repos/NVFlare" rev-parse HEAD
```

`warning: remote HEAD refers to nonexistent ref, unable to checkout` is expected when the bundle contains the
named branch but no default `HEAD`. The explicit `git switch` checks out the correct branch.

### Incremental updates

Do not resend the original 134 MB bundle for every change. Record the cluster's current commit, create a bundle
whose prerequisite is that commit, and give every update a new immutable filename.

On the local Mac, replace the two placeholders:

```bash
export LOCAL_REPO=/Users/kevlu/Documents/codex/worktrees/secondcopynvflare-14b
export CLUSTER_HEAD=<CURRENT_CLUSTER_COMMIT>
export UPDATE_NAME=nvflare-update-<NEW_SHORT_COMMIT>.bundle
export UPDATE_BUNDLE="/private/tmp/$UPDATE_NAME"

git -C "$LOCAL_REPO" bundle create \
  "$UPDATE_BUNDLE" codex/llm-fl-real-14b "^$CLUSTER_HEAD"
git -C "$LOCAL_REPO" bundle verify "$UPDATE_BUNDLE"
(cd /private/tmp && shasum -a 256 "$UPDATE_NAME" > "$UPDATE_NAME.sha256")

rsync -avP \
  "$UPDATE_BUNDLE" "$UPDATE_BUNDLE.sha256" \
  kevlu@cs-oci-ord-dc-02.nvidia.com:/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/incoming/
```

On the Data Copier or login node:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export UPDATE_NAME=nvflare-update-<NEW_SHORT_COMMIT>.bundle

cd "$PROJECT_ROOT/incoming"
sha256sum --check "$UPDATE_NAME.sha256"
git -C "$PROJECT_ROOT/repos/NVFlare" status --short --branch
git -C "$PROJECT_ROOT/repos/NVFlare" fetch \
  "$PROJECT_ROOT/incoming/$UPDATE_NAME" \
  refs/heads/codex/llm-fl-real-14b
git -C "$PROJECT_ROOT/repos/NVFlare" merge --ff-only FETCH_HEAD
git -C "$PROJECT_ROOT/repos/NVFlare" log -3 --oneline
git -C "$PROJECT_ROOT/repos/NVFlare" status --short --branch
```

The cluster branch can report `ahead N` of `origin/codex/llm-fl-real-14b`; the bundle clone's `origin` is a frozen
file, not a live remote. The important checks are the intended `HEAD` and a clean working tree. Investigate any
untracked file before continuing; for example, an accidental `?? awk` is not produced by Git and should not be
included in a commit.

## 3. Import and verify the container without a GPU

Import the image once on a Data Copier. The observed SquashFS was approximately 25 GB, so the import can take a
while even when it is healthy.

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
ls -lh "$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
```

If NVCR requires authentication, use the private Enroot credentials file described by the cluster container guide.
Do not pass a token on a command line that will enter shell history.

The base image contains NVIDIA's PyTorch `2.6.0a0...nv25.01`; the project environment deliberately overrides it
with the qualified PyTorch 2.12/cu126 packages. Always activate the environment before interpreting package output.

## 4. Build and qualify the Python environment on a CPU node

The checked-in job creates a Lustre environment, installs the local NVFLARE branch and pinned dependencies, runs
`pip check` and the real-training dependency check, and writes `requirements.lock`. It requests no GPU.

From a login node:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
cd "$PROJECT_ROOT/repos/NVFlare"
JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/prepare_env.slurm)
echo "$JOB_ID"
```

Check once after a reasonable interval; the qualified run took 12 minutes 53 seconds:

```bash
sacct -j "$JOB_ID" --format=JobID,State,Elapsed,ExitCode,MaxRSS -X
tail -n 100 "$PROJECT_ROOT/logs/"*"$JOB_ID".out
test -s "$PROJECT_ROOT/envs/nvflare-fsdp2/requirements.lock" \
  && echo "Environment lock exists"
```

The preparation script refuses to replace an existing environment. For a changed dependency lock, use a new
`VENV_DIR`, qualify it, and only then update the fixed path. Do not silently mutate a previously qualified
environment.

To inspect the environment interactively, enter the same container first:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
enroot start --mount "$PROJECT_ROOT:$PROJECT_ROOT" "$CONTAINER_IMAGE"

# Inside the container:
source "$PROJECT_ROOT/envs/nvflare-fsdp2/bin/activate"
cd "$PROJECT_ROOT/repos/NVFlare"
which python
python -m pip check
python research/llm_fl_stress/real_training/dependency_check.py
exit
```

Expected qualified versions are PyTorch `2.12.0+cu126`, Torchvision `0.27.0+cu126`, and Transformers `4.57.6`.
The dependency check also imports `Qwen2ForCausalLM` and verifies the compiled `torchvision::nms` operator.

## 5. Download immutable model snapshots on a Data Copier

Public Qwen2.5 snapshots download anonymously; no Hugging Face token is needed. Use the prepared environment inside
the container, pin the full revision, and write both a human-readable revision file and a content manifest.

The exact qualified snapshots are:

| Model | Full revision | Local directory | Approximate size |
| --- | --- | --- | --- |
| `Qwen/Qwen2.5-1.5B` | `8faed761d45a263340a0528343f099c05c9a4323` | `Qwen2.5-1.5B-8faed761d45a` | 2.9 GB |
| `Qwen/Qwen2.5-14B` | `97e1e76335b7017d8f67c08a19d103c0504298c9` | `Qwen2.5-14B-97e1e76335b7` | 30 GB |

Enter the container on a Data Copier:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
enroot start --mount "$PROJECT_ROOT:$PROJECT_ROOT" "$CONTAINER_IMAGE"

# Inside the container:
source "$PROJECT_ROOT/envs/nvflare-fsdp2/bin/activate"
export HF_HOME="$PROJECT_ROOT/cache/huggingface"
```

Download and manifest the 1.5B gate model:

```bash
export MODEL_ID=Qwen/Qwen2.5-1.5B
export MODEL_REVISION=8faed761d45a263340a0528343f099c05c9a4323
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-1.5B-8faed761d45a"

hf download "$MODEL_ID" \
  --revision "$MODEL_REVISION" \
  --local-dir "$MODEL_PATH"

printf '%s\n' "$MODEL_REVISION" > "$MODEL_PATH/REVISION"
(
  cd "$MODEL_PATH"
  find . -path './.cache' -prune -o \
    -type f ! -name MANIFEST.sha256 -print0 |
    LC_ALL=C sort -z |
    xargs -0 sha256sum > MANIFEST.sha256
)
du -sh "$MODEL_PATH"
```

Download and manifest the 14B model in the same container session:

```bash
export MODEL_ID=Qwen/Qwen2.5-14B
export MODEL_REVISION=97e1e76335b7017d8f67c08a19d103c0504298c9
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-14B-97e1e76335b7"

hf download "$MODEL_ID" \
  --revision "$MODEL_REVISION" \
  --local-dir "$MODEL_PATH"

printf '%s\n' "$MODEL_REVISION" > "$MODEL_PATH/REVISION"
(
  cd "$MODEL_PATH"
  find . -path './.cache' -prune -o \
    -type f ! -name MANIFEST.sha256 -print0 |
    LC_ALL=C sort -z |
    xargs -0 sha256sum > MANIFEST.sha256
)
du -sh "$MODEL_PATH"
exit
```

Manifest generation reads every model byte once and can therefore take time for 14B. It deliberately excludes the
Hugging Face `.cache` directory and its own output. To perform an additional full integrity read later:

```bash
(cd "$MODEL_PATH" && sha256sum --check MANIFEST.sha256)
```

Do not perform that extra 30 GB read before every job. The immutable path, revision file, manifest, and offline
loader provide repeatability without repeatedly burdening shared storage.

## 6. Validate and export the NVFLARE job without a GPU

Run these checks on a Data Copier or VS Code node inside the saved container. Validation rejects remote model IDs
and snapshots missing configuration, tokenizer, or weights. Include the revision in both commands; a 40-character
Git SHA can trigger NVFLARE's heuristic secret warning, but it is public model provenance, not a credential.

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-1.5B-8faed761d45a"
export MODEL_REVISION=8faed761d45a263340a0528343f099c05c9a4323

enroot start --mount "$PROJECT_ROOT:$PROJECT_ROOT" "$CONTAINER_IMAGE"

# Inside the container:
source "$PROJECT_ROOT/envs/nvflare-fsdp2/bin/activate"
cd "$PROJECT_ROOT/repos/NVFlare"

python research/llm_fl_stress/real_training/job.py \
  --model-name-or-path "$MODEL_PATH" \
  --model-revision "$MODEL_REVISION" \
  --workspace-root "$PROJECT_ROOT/jobs/qwen25-1.5b-validation-workspace" \
  --export-root "$PROJECT_ROOT/jobs/qwen25-1.5b-validation-export" \
  --nproc-per-node 4 \
  --run-mode train \
  --validate-only

python research/llm_fl_stress/real_training/job.py \
  --model-name-or-path "$MODEL_PATH" \
  --model-revision "$MODEL_REVISION" \
  --workspace-root "$PROJECT_ROOT/jobs/qwen25-1.5b-offline-workspace" \
  --export-root "$PROJECT_ROOT/jobs/qwen25-1.5b-export" \
  --nproc-per-node 4 \
  --run-mode train \
  --export-only
exit
```

Both commands must print a JSON record with `"status": "PASS"`. `PotentialSecretWarning` does not stop export;
it warns that parameter values are stored in clear text. A public model revision is safe there. Real HF, NVCR, or
other access tokens are not.

## 7. Run the manual GPU qualification ladder

Run all commands from the repository root on a login node:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
cd "$PROJECT_ROOT/repos/NVFlare"
```

Every command returns immediately with a job ID. A pending job consumes no GPU; Slurm allocates the requested
resources only when the job starts. `--immediate` applies to `srun`, not these batch jobs. If an interactive `srun`
reports `Requested nodes are busy`, the request ended without holding a GPU.

### 7.1 One-GPU container preflight

This checks the allocated GPU, CUDA visibility, NVFLARE, PyTorch, Torchvision, Transformers, and Qwen import:

```bash
JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/container_preflight.slurm)
echo "$JOB_ID"
```

Expected cost is one GPU for roughly two minutes. Advance only after the log contains
`"event": "real_training_environment_check"` and `"status": "PASS"`.

### 7.2 Four-GPU synthetic FSDP2 gate

This makes a small deterministic sharded model, runs an optimizer step, and tests full-state load/export on all four
GPUs before any large checkpoint is loaded:

```bash
JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/fsdp2_gate.slurm)
echo "$JOB_ID"
```

Expected cost is four GPUs for roughly 90 seconds. The `fsdp2_gpu_gate` JSON must report four A100s, positive
`selected_max_abs_change`, and `"status": "PASS"`.

### 7.3 1.5B real-training gate

```bash
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-1.5B-8faed761d45a"
export MODEL_REVISION=8faed761d45a263340a0528343f099c05c9a4323

JOB_ID=$(sbatch --parsable \
  --time=00:15:00 \
  --mem=128G \
  --cpus-per-task=16 \
  --export=ALL,MODEL_PATH="$MODEL_PATH",MODEL_REVISION="$MODEL_REVISION",RUN_MODE=train \
  research/llm_fl_stress/real_training/cs_oci_ord/real_training.slurm)
echo "$JOB_ID"
```

The qualified job finished in under four minutes. It performs a real forward/backward/optimizer step and full
3.55 GB state exchange.

### 7.4 14B exchange-only baseline

This constructs and shards the real 14B model, then exercises full receive/load/export/send without gradients or
optimizer state. It establishes CPU/GPU memory and transfer headroom at full scale.

```bash
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-14B-97e1e76335b7"
export MODEL_REVISION=97e1e76335b7017d8f67c08a19d103c0504298c9

JOB_ID=$(sbatch --parsable \
  --time=00:20:00 \
  --export=ALL,MODEL_PATH="$MODEL_PATH",MODEL_REVISION="$MODEL_REVISION",RUN_MODE=exchange-only \
  research/llm_fl_stress/real_training/cs_oci_ord/real_training.slurm)
echo "$JOB_ID"
```

The qualified job finished in 12 minutes 21 seconds. Expected loss and selected-parameter change are both zero in
exchange-only mode.

### 7.5 14B real training

Run this only after the 14B exchange-only job passes:

```bash
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-14B-97e1e76335b7"
export MODEL_REVISION=97e1e76335b7017d8f67c08a19d103c0504298c9

JOB_ID=$(sbatch --parsable \
  --time=00:30:00 \
  --export=ALL,MODEL_PATH="$MODEL_PATH",MODEL_REVISION="$MODEL_REVISION",RUN_MODE=train,LOCAL_STEPS=1,TRAINABLE_TARGET=last-layer \
  research/llm_fl_stress/real_training/cs_oci_ord/real_training.slurm)
echo "$JOB_ID"
```

The qualified job finished in 10 minutes 26 seconds. The 30-minute request is a safety cap, not reserved runtime;
Slurm releases all GPUs as soon as the job exits.

Never carry the leased-machine workaround `NCCL_P2P_DISABLE=1` into CS-OCI-ORD. The scripts fail closed if it is
present and otherwise retain the cluster's NCCL/NVLink defaults. Do not override the cluster-managed non-tunable
NCCL/RDMA variables in the job environment.

## 8. Inspect one result without polling

Wait a reasonable interval based on the measured durations, then make one accounting query:

```bash
sacct -j "$JOB_ID" \
  --format=JobID,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X
tail -n 100 "$PROJECT_ROOT/logs/"*"$JOB_ID".out
tail -n 100 "$PROJECT_ROOT/logs/"*"$JOB_ID".err
```

After a short interactive `srun` exits, `squeue -j <JOB_ID>` may say `Invalid job id specified` because the job is
no longer active. That does not mean it failed; `sacct` is the correct source for completed jobs.

For a real job, require exactly one rank-zero round-success record:

```bash
grep -F '"event": "real_training_round"' \
  "$PROJECT_ROOT/logs/"*"$JOB_ID".out
cat "$PROJECT_ROOT/artifacts/$JOB_ID/manifest.txt"
ls -lh "$PROJECT_ROOT/artifacts/$JOB_ID"
```

The batch job archives the NVFLARE workspace as `run.tar` only after a successful run. It leaves
`run.tar.partial` if archiving fails. The persisted global model is a raw PyTorch file inside the archive; locate it
without extracting the full multi-gigabyte tar:

```bash
tar -tf "$PROJECT_ROOT/artifacts/$JOB_ID/run.tar" |
  awk -F/ '$NF == "FL_global_model.pt" {print; exit}'
```

`PTFileModelPersistor` does not create an `FL_global_model.pt.metadata` sidecar. Its absence is expected and must
not be used as a pass/fail test.

Advance only when all applicable conditions hold:

- Slurm reports `COMPLETED` and exit code `0:0`.
- Preflight or FSDP2 gate contains a JSON `PASS` record and all requested GPUs are A100 80 GB devices.
- A real run contains one `real_training_round` record with the expected mode, full-state byte/tensor counts, and
  per-rank telemetry.
- Train mode reports a finite positive loss and positive `selected_max_abs_change`.
- Exchange-only mode reports zero loss and zero change.
- NVFLARE logs show aggregation of one of one client results and persistence of the global model.
- No CUDA OOM, NCCL failure, timeout, Python traceback, or NVFLARE run error appears.
- `manifest.txt` records status zero, the intended model path, and the intended Git commit.
- `run.tar`, not only a partial archive, exists and has a plausible model-scale size.

`SimEnv` may print `Job status: None`; that is benign. Use Slurm exit status, the round JSON, server aggregation and
persistence logs, manifest, and archive as the authoritative signals. A c10d barrier warning about inferring a GPU
when `device_id` is unspecified is also benign in the qualified single-node torchrun layout.

## 9. Interpret utilization and memory correctly

Low or intermittent GPU 0 utilization does not by itself indicate a problem. Full-state receive/send,
serialization, archive creation, tokenizer/CPU work, and barriers are CPU/storage/network phases. In exchange-only
mode there is no forward/backward compute at all. Sampled utilization can therefore show zero on one or all GPUs
even though every rank participates in the collective operations.

Rank zero intentionally uses much more host RAM and spends longer in load/export because it bridges NVFLARE's full
CPU state and the distributed FSDP2 ranks. The other ranks hold their shards and participate in collectives. The
July 22 14B run peaked near 62 GB RSS on rank zero, about 7.25 GB on each other rank, and about 15 GB allocated GPU
memory per rank during training. Those asymmetries are expected for this bridge design.

## 10. Troubleshooting guide

### `python` reports missing `GLIBC_2.3x`

The venv was created inside the Ubuntu-based container and its Python is linked to that container's glibc. It was
activated on the older Data Copier host without first entering Enroot. Activation alone is insufficient. Enter the
same SquashFS with the Lustre mount and then activate the venv.

### The base image shows PyTorch 2.6 and no Transformers

The container is running, but the project venv is not active. Run `source "$VENV_DIR/bin/activate"`, check
`which python`, and rerun the dependency check. The qualified environment must resolve Python and packages under
`$PROJECT_ROOT/envs/nvflare-fsdp2`.

### Qwen import fails with `operator torchvision::nms does not exist`

The environment contains a generic PyPI Torchvision wheel instead of the CUDA 12.6 wheel matching PyTorch. Current
requirements pin the correct build. For the originally affected environment, the repair was:

```bash
python -m pip install --force-reinstall --no-deps --no-cache-dir \
  --index-url https://download.pytorch.org/whl/cu126 \
  torchvision==0.27.0
python -m pip check
python research/llm_fl_stress/real_training/dependency_check.py
python -m pip freeze > "$PROJECT_ROOT/envs/nvflare-fsdp2/requirements.lock"
```

Do not treat this as a routine mutation: use it to diagnose/repair that known historical environment, then rebuild
a new environment from the corrected requirements for future qualification.

### NVFLARE prints `PotentialSecretWarning` for the model revision

The secret scanner treats the public 40-character revision SHA as a high-entropy value. It is a warning, not an
exception, and does not stop validation, export, or execution. Never dismiss the warning for an actual access token;
tokens must come from a site environment variable or mounted secret file and must not be recipe parameters.

### A completed job has no round JSON

Do not accept it as a training qualification. An early client implementation could catch a distributed failure and
send unchanged parameters with NaN metrics, allowing the outer job to exit successfully. Commit `a2fa5892` made
distributed errors fail closed and added the rank-zero `real_training_round` record. Confirm that commit or a
descendant is running, then diagnose the logs rather than trusting only Slurm status.

### The log pauses during package installation or a large download

`pip` may remain at `Installing collected packages` while unpacking multi-gigabyte CUDA/PyTorch wheels. HF transfer
may finish a 3.09 GB shard in seconds on the Data Copier, while manifesting or installing takes longer and emits no
progress. Check the job once with `sacct`; do not create an `squeue` loop. A completed environment-prep job and a
nonempty lock file are stronger signals than continuously tailed output.

### A job fails

Do not automatically resubmit. Read its saved stdout/stderr and manifest once, identify one cause, make one
controlled correction, and start a new manual submission. Preserve failed job IDs in the qualification notes when
the failure explains an important dependency or design correction.
