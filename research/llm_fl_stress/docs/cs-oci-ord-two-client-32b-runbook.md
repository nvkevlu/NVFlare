# CS-OCI-ORD two-client Qwen2.5-32B real-training qualification

## Purpose and success boundary

This is the next formal large-model qualification. It runs two real provisioned NVFLARE clients on one
eight-A100-SXM4-80GB node:

- site-1 uses GPUs 0–3;
- site-2 uses GPUs 4–7;
- each client runs four-rank FSDP2;
- both clients load the complete immutable Qwen2.5-32B base locally;
- only the final decoder layer is trainable and federated;
- a Qwen2.5-1.5B exact-topology gate must pass before 32B starts; and
- the result is accepted only if Slurm, both training clients, 2/2 aggregation, persistence, state continuity, and
  all eight GPU activity checks pass.

Qwen2.5-32B revision `1818d35814b8319459f4bd55ed1ac8709630f003` has 64 decoder layers and hidden size 5120. Its final
decoder layer contains 487,605,248 BF16 parameters, or 975,210,496 payload bytes (930.03 MiB). The qualification
refuses a target with the wrong revision, architecture, 17-shard layout, staged weight size, or sparse payload.

The 32B target performs one federated round and two real optimizer steps per rank. This is intentionally a formal
scale qualification, not a long training campaign. A later experiment can increase rounds only after this exact
artifact is green.

## Timeout policy

There is no application-level total-runtime deadline. In particular, the obsolete 720-second watchdog is not
present.

The remaining controls have distinct purposes:

- production services must register normally;
- the 32B clients have up to 1,800 seconds to load and report ready;
- only after both clients are ready, 900 seconds with no meaningful transfer, training, result, aggregation, or
  persistence progress is considered a stall;
- explicit runner, CUDA, NCCL, FSDP2, or service errors abort immediately; and
- Slurm's two-hour request is only the allocation ceiling and signals the wrapper five minutes before expiry so it can
  retain failure evidence.

Progress events reset the inactivity clock. A healthy run is not aborted merely because total elapsed time crosses
an application-selected number. The job releases the allocation immediately after success; requesting two hours does
not force it to occupy the node for two hours.

## 1. Install the reviewed source bundle

Transfer the final bundle and checksum to the Data Copier with the macOS-compatible `rsync` form already documented
in the main runbook. On the cluster:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export BUNDLE="$PROJECT_ROOT/incoming/nvflare-32b-success.bundle"

sha256sum --check "$BUNDLE.sha256"
git -C "$REPO_ROOT" bundle verify "$BUNDLE"
git -C "$REPO_ROOT" fetch "$BUNDLE" refs/heads/codex/llm-fl-real-14b
git -C "$REPO_ROOT" merge --ff-only FETCH_HEAD

test "$(cat "$REPO_ROOT/research/llm_fl_stress/real_training/QUALIFICATION_RELEASE")" \
  = "2026-07-29-trainable-32b-v7"
test -z "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)"
git -C "$REPO_ROOT" log -3 --oneline
```

Do not submit from a dirty checkout and do not substitute the older `nvflare-trainable-14b-ready.bundle`.

## 2. Stage the pinned 32B model on a Data Copier

Use `cs-oci-ord-dc-02` or another available Data Copier. The public model does not require a Hugging Face token.

```bash
ssh kevlu@cs-oci-ord-dc-02.nvidia.com
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
enroot start --mount "$PROJECT_ROOT:$PROJECT_ROOT" "$CONTAINER_IMAGE"

# Inside the container:
source "$PROJECT_ROOT/envs/nvflare-fsdp2/bin/activate"
export HF_HOME="$PROJECT_ROOT/cache/huggingface"
export MODEL_ID=Qwen/Qwen2.5-32B
export MODEL_REVISION=1818d35814b8319459f4bd55ed1ac8709630f003
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-32B-1818d35814b8"

hf download "$MODEL_ID" \
  --revision "$MODEL_REVISION" \
  --local-dir "$MODEL_PATH"

printf '%s\n' "$MODEL_REVISION" > "$MODEL_PATH/REVISION"
test "$(python -c \
  'import json,sys; c=json.load(open(sys.argv[1])); print(c[\"hidden_size\"], c[\"num_hidden_layers\"], c[\"torch_dtype\"])' \
  "$MODEL_PATH/config.json")" = "5120 64 bfloat16"

(
  cd "$MODEL_PATH"
  find . -path './.cache' -prune -o \
    -type f ! -name MANIFEST.sha256 -print0 |
    LC_ALL=C sort -z |
    xargs -0 sha256sum > MANIFEST.sha256
)

du -sh "$MODEL_PATH"
find "$MODEL_PATH" -maxdepth 1 -name 'model*.safetensors' -type f | wc -l
exit
```

Expect approximately 65.5 GB and 17 safetensor shards. Manifest creation deliberately reads the model once on the
Data Copier; do not repeat a full checksum immediately before every GPU job.

## 3. Run the CPU-only 32B model and recipe preflight

Return to a login node and submit exactly one CPU job:

The job requests 150 GB, which fits the documented 176 GB CS-OCI-ORD CPU nodes. The model loader uses the
low-CPU-memory path and the server retains only the final decoder layer after construction.

```bash
ssh kevlu@cs-oci-ord-login-03.nvidia.com
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
cd "$REPO_ROOT"

PREFLIGHT_JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/model_32b_preflight.slurm)
echo "PREFLIGHT_JOB_ID=$PREFLIGHT_JOB_ID"
```

Check once after it has had time to run; do not use `watch`:

```bash
sacct -j "$PREFLIGHT_JOB_ID" \
  --format=JobID,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

PREFLIGHT_ARTIFACT="$PROJECT_ROOT/artifacts/32b-preflight-$PREFLIGHT_JOB_ID"
cat "$PREFLIGHT_ARTIFACT/dependency-check.json"
cat "$PREFLIGHT_ARTIFACT/trainable-server-preflight.json"
cat "$PREFLIGHT_ARTIFACT/job-export.json"
cat "$PREFLIGHT_ARTIFACT/manifest.txt"
```

Required result:

- Slurm `COMPLETED` and `0:0`;
- all JSON records report `PASS`;
- model identity is Qwen2 BF16 with hidden size 5120, 64 layers, and exactly 17 weight shards;
- sparse server payload is exactly `975210496`;
- job export reports two clients, one round, two local steps, four ranks per client, and trainable state scope; and
- each site package contains `custom/data/site-N.jsonl`, while its generated launcher passes
  `--dataset-file data/site-N.jsonl`; and
- the manifest records the reviewed Git commit.

Do not submit the GPU job if any preflight condition is missing.

## 4. Submit the single 32B GPU qualification

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
cd "$REPO_ROOT"

test "$(cat research/llm_fl_stress/real_training/QUALIFICATION_RELEASE)" \
  = "2026-07-29-trainable-32b-v7"
test -z "$(git status --porcelain --untracked-files=all)"

JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/two_client_32b_trainable.slurm)
echo "JOB_ID=$JOB_ID"
GPU_LOG="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-32b-trainable-$JOB_ID.out"
echo "GPU_LOG=$GPU_LOG"
tail -F "$GPU_LOG"
```

`tail -F` reads the file and does not poll Slurm. `Ctrl-C` stops only the local tail.

Expected sequence:

1. eight A100s pass the environment check;
2. both production clients connect;
3. the two-round 1.5B trainable-state gate passes;
4. both 32B clients report ready;
5. both clients report a passing 32B training round with two optimizer steps;
6. the server reports `Aggregated 2/2 results`;
7. persistence completes; and
8. the qualification summary reports `PASS`.

## 5. Accept or reject the result

After completion:

```bash
sacct -j "$JOB_ID" \
  --format=JobID,JobName%40,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

ARTIFACT="$PROJECT_ROOT/artifacts/$JOB_ID"
cat "$ARTIFACT/manifest.txt"
cat "$ARTIFACT/qualification.json"
cat "$ARTIFACT/gpu-monitor.json"
cat "$ARTIFACT/target-identity.json"
cat "$ARTIFACT/target-32b/summary.json"
cat "$ARTIFACT/target-32b/trainable-state-evidence.json"
```

Acceptance requires all of the following:

- Slurm `COMPLETED` with exit code `0:0`;
- manifest `status=0` and `qualification_profile=trainable-32b`;
- gate and target summaries both `PASS`;
- exactly two 32B client round records and 2/2 aggregation;
- payload `975210496` bytes, below the 1 GiB ceiling;
- finite losses and positive selected-parameter changes on both clients;
- distinct site dataset hashes and expected sample IDs;
- persisted state matching the equal-weight FedAvg sample;
- all GPU indices 0–7 observed with positive memory and utilization; and
- no fatal error marker in retained participant logs.

Do not automatically rerun a failure. Preserve the artifact and diagnose it before consuming another allocation.
