# CS-OCI-ORD two-client 14B runbook

This is the prepared follow-up to the successful
[one-client 14B qualification](cs-oci-ord-real-training-qualification-2026-07-22.md). It keeps the proven custom
`sbatch`/Pyxis/Enroot workflow and tests the largest remaining federation question with one controlled allocation:
can two real four-rank Qwen2.5-14B clients train concurrently, return two full 29.54 GB states, aggregate both
results, and persist the global model?

This test has not passed on CS-OCI-ORD until a job produces the evidence defined below. Do not describe a local
export or queued allocation as a qualification result.

## Fixed topology and resource request

```text
One CS-OCI-ORD GPU node / one Slurm allocation

NVFLARE SimEnv server (CPU)
├── site-1: CUDA_VISIBLE_DEVICES=0,1,2,3
│   └── torchrun: four FSDP2 ranks
└── site-2: CUDA_VISIBLE_DEVICES=4,5,6,7
    └── torchrun: four FSDP2 ranks
```

The dedicated wrapper requests:

| Resource | Request | Reason |
| --- | ---: | --- |
| Nodes | 1 | Both clients and the server must remain colocated |
| GPUs | 8 x A100 80 GB | Two disjoint four-rank FSDP2 groups |
| CPUs | 64 | Two concurrent model-load, serialization, and torchrun groups |
| System RAM | 512 GB | Two measured ~62 GB rank-zero processes, server aggregation, and transient copies |
| Wall time | 30 minutes | One-client 14B took 10:26; this leaves bounded concurrency/archive headroom |
| Local workspace | `/raid/scratch/$USER/$SLURM_JOB_ID` | Fast ephemeral execution |
| Persistent result | `$PROJECT_ROOT/artifacts/$SLURM_JOB_ID` | Manifest and archived workspace |

The request consumes the node's eight GPUs but does not use `--exclusive`. Slurm releases it immediately when the
job exits. Pending time consumes no GPUs; running time is billed for all eight.

There is no separate server allocation. A separate SJ/CJ launcher, persistent parent, and PR #4930 are intentionally
deferred until this colocated capacity test is complete.

## Why this can proceed directly to training

Do not spend an additional exchange-only or one-GPU allocation if the staged container, venv, model, and cluster
image are unchanged:

- the one-GPU container/dependency preflight passed;
- the four-GPU NCCL/FSDP2 bridge passed;
- one-client 14B exchange-only passed;
- one-client 14B real training passed; and
- the new two-client behavior can be validated and exported without a GPU.

The only new GPU-scale variable is two-client concurrency. One deliberate 14B training job tests it directly.

## New fail-closed evidence

The two clients do not merely run identical opaque subprocesses:

- `site-1` and `site-2` receive disjoint GPU groups;
- the site name is included in every ready/round record;
- a stable site-specific text prefix gives the two clients different deterministic batches;
- the FedAvg quorum is two, so one client cannot complete the round alone;
- every client must report one `PASS` round with all four rank records;
- both clients must agree on payload bytes and tensor count;
- the server log must contain `Aggregated 2/2 results`; and
- the server log must confirm final model persistence.

After simulation, `job.py` scans the per-site and server logs. It prints one
`real_training_federation` JSON record only if all evidence passes; otherwise the Python process, `srun`, and Slurm
job fail.

## 1. Verify staged inputs without a GPU

Use a Data Copier or VS Code node and enter the same container used for qualification:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-14B-97e1e76335b7"
export MODEL_REVISION=97e1e76335b7017d8f67c08a19d103c0504298c9

test -s "$CONTAINER_IMAGE"
test -d "$MODEL_PATH"
test "$(cat "$MODEL_PATH/REVISION")" = "$MODEL_REVISION"
git -C "$REPO_ROOT" status --short --branch
git -C "$REPO_ROOT" rev-parse HEAD

enroot start --mount "$PROJECT_ROOT:$PROJECT_ROOT" "$CONTAINER_IMAGE"
```

Inside the container:

```bash
source "$PROJECT_ROOT/envs/nvflare-fsdp2/bin/activate"
cd "$PROJECT_ROOT/repos/NVFlare"

python -m pip check
python research/llm_fl_stress/real_training/dependency_check.py
```

Do not rerun the 30 GB model checksum automatically. The immutable model path, full revision, existing manifest,
and offline loader are sufficient unless the snapshot may have been modified.

## 2. Validate and export the two-client job without a GPU

Still inside the container:

```bash
python research/llm_fl_stress/real_training/job.py \
  --model-name-or-path "$MODEL_PATH" \
  --model-revision "$MODEL_REVISION" \
  --workspace-root "$PROJECT_ROOT/jobs/qwen25-14b-2client-validation-workspace" \
  --export-root "$PROJECT_ROOT/jobs/qwen25-14b-2client-validation-export" \
  --num-clients 2 \
  --nproc-per-node 4 \
  --run-mode train \
  --expected-gpu-name-substring A100-SXM4-80GB \
  --validate-only

python research/llm_fl_stress/real_training/job.py \
  --model-name-or-path "$MODEL_PATH" \
  --model-revision "$MODEL_REVISION" \
  --workspace-root "$PROJECT_ROOT/jobs/qwen25-14b-2client-offline-workspace" \
  --export-root "$PROJECT_ROOT/jobs/qwen25-14b-2client-export" \
  --num-clients 2 \
  --nproc-per-node 4 \
  --run-mode train \
  --expected-gpu-name-substring A100-SXM4-80GB \
  --export-only
```

Both commands must report:

```json
{
  "clients": ["site-1", "site-2"],
  "gpu_config": "[0,1,2,3],[4,5,6,7]",
  "num_clients": 2,
  "status": "PASS",
  "total_gpu_processes": 8
}
```

The actual JSON contains additional fields. NVFLARE may warn that the public 40-character model revision resembles
a secret; that warning is nonfatal and must not be generalized to real credentials.

Exit the container after validation:

```bash
exit
```

## 3. Submit exactly one two-client allocation

Run manually from a login node:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-14B-97e1e76335b7"
export MODEL_REVISION=97e1e76335b7017d8f67c08a19d103c0504298c9
export JOB_EXPORTS=ALL,MODEL_PATH="$MODEL_PATH",MODEL_REVISION="$MODEL_REVISION",RUN_MODE=train,LOCAL_STEPS=1
export JOB_EXPORTS="$JOB_EXPORTS",TRAINABLE_TARGET=last-layer
cd "$PROJECT_ROOT/repos/NVFlare"

JOB_ID=$(sbatch --parsable \
  --export="$JOB_EXPORTS" \
  research/llm_fl_stress/real_training/cs_oci_ord/two_client_14b.slurm)
echo "$JOB_ID"
```

Do not add `--exclusive`, change NCCL variables, background an interactive `srun`, use `sbatch -W`, or submit a
second copy while this one is pending/running.

## 4. Inspect once and decide

Allow approximately 20 minutes before the first check. This is an estimate, not a polling interval:

```bash
sacct -j "$JOB_ID" \
  --format=JobID,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

grep -F '"event": "real_training_federation"' \
  "$PROJECT_ROOT/logs/"*"$JOB_ID".out

grep -F '"event": "real_training_round"' \
  "$PROJECT_ROOT/logs/"*"$JOB_ID".out

cat "$PROJECT_ROOT/artifacts/$JOB_ID/manifest.txt"
ls -lh "$PROJECT_ROOT/artifacts/$JOB_ID"
```

Pass only if:

- Slurm reports `COMPLETED` and `0:0`;
- exactly one `real_training_federation` record reports `status=PASS`, `num_clients=2`,
  `aggregated_results=2`, and `persisted=true`;
- the federation record contains both `site-1` and `site-2`;
- each site has a finite positive loss and positive selected-parameter change;
- each site contains ranks 0–3, all on A100-SXM4-80GB devices;
- each site reports 579 tensors and the same 29,540,067,328-byte internal payload;
- the manifest records `num_clients=2`, `nproc_per_client=4`, `total_gpu_processes=8`, `run_mode=train`, status zero,
  the full model revision, and the intended Git commit; and
- `run.tar` exists rather than only `run.tar.partial`.

The two site losses should normally differ because their deterministic batches differ. Do not impose an exact loss
or runtime copied from the one-client result.

If the job fails, do not resubmit automatically. Preserve the job ID, inspect the saved client/server logs and
partial artifact once, then change one diagnosed cause.

## 5. Decision after the result

A pass closes the immediate real multi-client concurrency gap. Record its elapsed time, per-site rank-zero RSS,
per-rank GPU peaks, two transfer paths, aggregation time, persistence time, and archive size before considering
one-client 32B exchange-only.

A failure caused by system-memory pressure should be evaluated against the 2 TB physical node before increasing
`--mem`; a failure caused by transfer timeout, filesystem load, or client process startup needs a targeted change
rather than a larger allocation. Do not proceed to 32B or 72B until the two-client 14B cause is understood.
