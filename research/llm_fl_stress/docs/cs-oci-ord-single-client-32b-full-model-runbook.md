# CS-OCI-ORD single-client Qwen2.5-32B full-model capacity experiment

## Purpose and claim boundary

This experiment answers the next distinct resource question without repeating the already-passing control-plane,
1.5B, 14B, or sparse-32B gates:

> Can one eight-rank FSDP2 client train every parameter of the pinned Qwen2.5-32B BF16 checkpoint for multiple
> steady-state optimizer steps on one eight-A100-SXM4-80GB CS-OCI-ORD node, and can the NVFLARE FSDP2 state bridge
> load and export the exact complete state with measurable GPU and host headroom?

It is a result-producing capacity experiment, not a precursor to another GPU job. It does **not** start an NVFLARE
server, perform client/server transport, aggregate multiple clients, or persist a server checkpoint. The successful
two-client provisioned-TLS and FedAvg results already cover those framework behaviors at smaller payloads. A pass
here supports one 32B client's compute, optimizer, and bridge capacity; it is not a two-client 32B federation claim.

The exact contract is:

| Property | Required value |
| --- | ---: |
| Model / revision | `Qwen/Qwen2.5-32B` / `1818d35814b8319459f4bd55ed1ac8709630f003` |
| Architecture / dtype | Qwen2 causal LM / entirely BF16 parameters |
| Layers / hidden / intermediate | 64 / 5,120 / 27,648 |
| Parameter tensors / parameters | 771 / 32,763,876,352 |
| Logical full state | 65,527,752,704 bytes (61.027 GiB) |
| Physical 17-shard checkpoint | 65,527,841,752 bytes; kept distinct from logical state |
| FSDP2 ranks | exactly 8, one rank per A100 |
| Trainable target / bridge scope | `all` / `full` |
| Work | 6 optimizer steps per rank at sequence length 512 |
| Data | all 48 fixed site-1 records, one unique record per rank-step |
| Optimizer | AdamW, `foreach=false`, `fused=false`, exact BF16 moment coverage |
| GPU acceptance | training succeeds on all ranks; headroom is measured, not thresholded |
| Host acceptance | allocation monitor reports no limit, OOM, or OOM-kill event when cgroup metrics are available |

Six steps are long enough to measure activity after AdamW state has been materialized while still keeping the run a
capacity experiment rather than pretending that 48 qualification examples are a model-quality training corpus.

## Resource and timeout policy

The job requests one node, eight A100 80 GB GPUs, 64 CPUs, 900 GiB of host RAM, and two hours. CS-OCI-ORD GPU nodes
have eight A100s, 2 TB of host RAM, and local NVMe. The job releases the allocation immediately when it finishes.

The persistent BF16 planning subtotal per rank, before activations and communication buffers, is approximately:

| State | Per GPU |
| --- | ---: |
| Parameter shard | 7.63 GiB |
| Gradient shard | 7.63 GiB |
| Two Adam moment shards | 15.26 GiB |
| Subtotal | 30.51 GiB |

The experiment records actual allocator peaks and free memory at every important phase. It deliberately sets no
minimum-headroom pass threshold on this first 32B measurement: a successful workload is not relabeled as failed by
an arbitrary reserve. The host projection is also report-only because summing independent per-rank RSS maxima and a
full-state reserve is conservative and not a simultaneous measurement. The allocation monitor is the authoritative
source for actual cgroup memory pressure and OOM events.

There is no application total-runtime cutoff and no model-ready or post-ready elapsed cutoff. The 10,800-second
PyTorch distributed timeout protects collective operations; it is longer than the Slurm allocation and is not a
healthy-run deadline. Slurm requests a graceful `TERM` five minutes before the two-hour wall; accounting and signal
delivery granularity make the effective workload ceiling approximately 114–115 minutes. The wrapper requires at least
6,600 seconds remaining before model loading, leaving at least 110 minutes for the experiment and roughly four minutes
of additional margin. It never requeues or automatically retries.

## 1. Install and bind the reviewed checkout

Transfer the bundle, checksum, and head file with the Data Copier procedure in the main cluster runbook. On the
cluster:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export BUNDLE="$PROJECT_ROOT/incoming/nvflare-32b-single-client.bundle"
export HEAD_FILE="$BUNDLE.head"

cd "$(dirname "$BUNDLE")"
sha256sum --check "$(basename "$BUNDLE").sha256"
git -C "$REPO_ROOT" bundle verify "$BUNDLE"
git -C "$REPO_ROOT" fetch "$BUNDLE" refs/heads/codex/llm-fl-real-14b
git -C "$REPO_ROOT" merge --ff-only FETCH_HEAD

export EXPECTED_HEAD="$(cat "$HEAD_FILE")"
test "$(git -C "$REPO_ROOT" rev-parse HEAD)" = "$EXPECTED_HEAD"
test -z "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)"
git -C "$REPO_ROOT" status --short --branch
```

Do not submit from a dirty checkout or replace `EXPECTED_HEAD` with whatever happens to be checked out.

## 2. Run the zero-GPU readiness check

This is not a Slurm job and does not load tensor payloads. Run it in the existing container on a Data Copier. It
checks the revision, exact Qwen config, safetensor index and headers, all 17 shard layouts, logical and physical byte
counts, and the 48 unique training records.

```bash
ssh kevlu@cs-oci-ord-dc-02.nvidia.com

export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-32B-1818d35814b8"
export MODEL_REVISION=1818d35814b8319459f4bd55ed1ac8709630f003
export STATIC_RESULT="$PROJECT_ROOT/artifacts/32b-single-client-static.json"
export EXPECTED_HEAD="$(cat "$PROJECT_ROOT/incoming/nvflare-32b-single-client.bundle.head")"

mkdir -p "$(dirname "$STATIC_RESULT")"

# One-time container integrity reread on the Data Copier. The GPU wrapper
# later checks only this small freshness marker.
sha256sum --check "$CONTAINER_IMAGE.sha256"
sha256sum "$CONTAINER_IMAGE.sha256" > "$CONTAINER_IMAGE.sha256.verified"
sha256sum --check "$CONTAINER_IMAGE.sha256.verified"

enroot start --mount "$PROJECT_ROOT:$PROJECT_ROOT" "$CONTAINER_IMAGE"
```

Inside the container:

```bash
set -Eeuo pipefail
source "$PROJECT_ROOT/envs/nvflare-fsdp2/bin/activate"
cd "$REPO_ROOT"

test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test -z "$(git status --porcelain --untracked-files=all)"

# The already-staged 32B snapshot needs one full integrity reread before any
# GPU submission. Do this here on the Data Copier, never inside the allocation.
test -s "$MODEL_PATH/MANIFEST.sha256"
(
  cd "$MODEL_PATH"
  sha256sum --check MANIFEST.sha256
  sha256sum MANIFEST.sha256 > MANIFEST.sha256.verified
  sha256sum --check MANIFEST.sha256.verified
)

python research/llm_fl_stress/real_training/dependency_check.py
python research/llm_fl_stress/real_training/model_structure_preflight.py \
  --model-name-or-path "$MODEL_PATH" \
  --model-revision "$MODEL_REVISION" \
  --expected-hidden-size 5120 \
  --expected-intermediate-size 27648 \
  --expected-num-hidden-layers 64 \
  --expected-num-attention-heads 40 \
  --expected-num-key-value-heads 8 \
  --expected-safetensor-files 17 \
  --expected-tensor-count 771 \
  --expected-parameters 32763876352 \
  --expected-tensor-bytes 65527752704 \
  --expected-checkpoint-file-bytes 65527841752 \
  --dataset-file research/llm_fl_stress/real_training/data/site-1.jsonl \
  --minimum-dataset-records 48 \
  | tee "$STATIC_RESULT"

grep -q '"status": "PASS"' "$STATIC_RESULT"
test -s "$CONTAINER_IMAGE.sha256.verified"
test -s "$MODEL_PATH/MANIFEST.sha256.verified"
echo "32B zero-GPU readiness PASS"
```

Exit the container after the check. Do not submit the GPU experiment if this command fails. The structural check reads
metadata and safetensor headers without materializing tensors, but the one-time manifest verification deliberately
rereads all approximately 62 GB of checkpoint files from storage. Perform that I/O on the Data Copier; it still does
not justify a separate CPU or GPU gate allocation.

## 3. Submit the one result-producing GPU job

From a login node:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
cd "$REPO_ROOT"

export EXPECTED_HEAD="$(cat "$PROJECT_ROOT/incoming/nvflare-32b-single-client.bundle.head")"
test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test -z "$(git status --porcelain --untracked-files=all)"
CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-32B-1818d35814b8"
test -s "$CONTAINER_IMAGE.sha256.verified"
test -s "$MODEL_PATH/MANIFEST.sha256.verified"
sha256sum --check "$CONTAINER_IMAGE.sha256.verified"
(cd "$MODEL_PATH" && sha256sum --check MANIFEST.sha256.verified)
test ! "$CONTAINER_IMAGE" -nt "$CONTAINER_IMAGE.sha256.verified"
test ! "$CONTAINER_IMAGE.sha256" -nt "$CONTAINER_IMAGE.sha256.verified"
test ! "$MODEL_PATH/MANIFEST.sha256" -nt "$MODEL_PATH/MANIFEST.sha256.verified"
test -z "$(find "$MODEL_PATH" -path "$MODEL_PATH/.cache" -prune -o \
  \( -type f -o -type l \) \
  ! -path "$MODEL_PATH/MANIFEST.sha256" \
  ! -path "$MODEL_PATH/MANIFEST.sha256.verified" \
  -newer "$MODEL_PATH/MANIFEST.sha256.verified" -print -quit)"
unset NCCL_P2P_DISABLE

JOB_ID=$(sbatch --parsable \
  --export=ALL,EXPECTED_HEAD="$EXPECTED_HEAD" \
  research/llm_fl_stress/real_training/cs_oci_ord/single_client_32b_full_model.slurm)
echo "JOB_ID=$JOB_ID"

GPU_LOG="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-32b-single-client-$JOB_ID.out"
GPU_ERR="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-32b-single-client-$JOB_ID.err"
echo "GPU_LOG=$GPU_LOG"
echo "GPU_ERR=$GPU_ERR"
tail --retry -F "$GPU_LOG"
```

`tail` does not poll Slurm. `Ctrl-C` stops only the local tail. Do not use `watch squeue`; the cluster rate-limits
repeated scheduler RPCs. If `squeue` later says the job ID is invalid, the job has left the live queue—use `sacct`.

## 4. Accept or reject the result once

```bash
sacct -j "$JOB_ID" \
  --format=JobID,JobName%44,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

ARTIFACT="$PROJECT_ROOT/artifacts/32b-full-model-single-client-$JOB_ID"
cat "$ARTIFACT/manifest.txt"
cat "$ARTIFACT/static-model-preflight.json"
cat "$ARTIFACT/capacity-experiment.json"
cat "$ARTIFACT/qualification.json"
cat "$ARTIFACT/gpu-monitor.json"
cat "$ARTIFACT/allocation-monitor.json"
```

Run the analyzer with the pinned container and virtual environment, not the older login-node Python. On a Data
Copier:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
export JOB_ID=<completed-job-id>
export ARTIFACT="$PROJECT_ROOT/artifacts/32b-full-model-single-client-$JOB_ID"

enroot start --mount "$PROJECT_ROOT:$PROJECT_ROOT" "$CONTAINER_IMAGE"
```

Inside the container:

```bash
source "$PROJECT_ROOT/envs/nvflare-fsdp2/bin/activate"
cd "$REPO_ROOT"

python research/llm_fl_stress/real_training/telemetry_analysis.py \
  --artifact-root "$ARTIFACT" \
  --output "$ARTIFACT/telemetry-analysis.json"
cat "$ARTIFACT/telemetry-analysis.json"
```

Accept the experiment only when:

- Slurm reports `COMPLETED` and `0:0`, and the manifest says `status=PASS`;
- static model evidence is `PASS` and distinguishes 65,527,752,704 logical bytes from 65,527,841,752 physical bytes;
- capacity evidence reports exactly ranks and local ranks 0–7 on A100-SXM4-80GB GPUs;
- all 32,763,876,352 parameters and all 771 parameter tensors are BF16 and trainable;
- six finite-loss steps completed, gradients are finite and nonzero in early, middle, and late layers, and the
  bounded update probe changed;
- AdamW evidence reports exactly 65,527,752,704 BF16 moment values occupying 131,055,505,408 bytes;
- initial load and final export each report 771 tensors and 65,527,752,704 bytes with an unchanged schema;
- all eight GPUs show activity, while measured per-rank peaks and headroom are retained without an arbitrary
  headroom threshold;
- the allocation monitor is `PASS` and, when cgroup metrics are exposed, reports zero new `max`, `oom`, and
  `oom_kill` events; and
- offline telemetry analysis is `PASS` or explicitly `PARTIAL` only for a documented unsupported metric—not
  `FAIL`.

If the job fails, inspect the retained JSON and stderr once. Do not automatically retry. A successful result closes
the single-client 32B capacity gap; the remaining untested 32B question would be actual 65.5 GB NVFLARE transport
and multi-client aggregation, which requires a deliberately different experiment and likely more than one node.
