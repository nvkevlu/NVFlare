# CS-OCI-ORD two-client Qwen2.5-72B last-layer qualification

## Claim and success boundary

This runbook prepares one defensible claim:

> Two production NVFLARE clients concurrently performed real last-decoder-layer training of the pinned
> Qwen2.5-72B checkpoint with four-rank FSDP2 per client on one eight-A100-SXM4-80GB node, returned both updated
> trainable states, completed 2/2 FedAvg aggregation, and persisted the aggregated state.

This is not full-model fine-tuning. The immutable 72B base is present at both clients so that each forward,
backward, and optimizer step executes through the real complete model. Only the final decoder layer is trainable
and crosses the federated boundary.

The exact target contract is:

| Property | Required value |
| --- | --- |
| Model | `Qwen/Qwen2.5-72B` |
| Revision | `efba10c8e54e91e0d9570ab5f7b51a958474d4cb` |
| Architecture / dtype | `Qwen2ForCausalLM` / BF16 |
| Hidden / intermediate size | 8,192 / 29,568 |
| Decoder layers | 80 |
| Attention / key-value heads | 64 / 8 |
| Safetensor shards | 37 |
| Selected final-layer parameters | 877,684,736 |
| Trainable tensors / payload | 12 / 1,755,369,472 bytes |
| Clients / FSDP2 ranks | 2 / 4 ranks per client |
| GPU mapping | site-1: 0–3; site-2: 4–7 |
| Target work | 1 federated round, 2 optimizer steps per rank |
| State scope | final decoder layer only |
| Required software release | `2026-07-30-trainable-72b-v10` |

The target must pass four manual gates in order:

1. CPU production control-plane qualification;
2. CPU sparse-model, identity, recipe, and exported-job preflight;
3. one real four-GPU 72B FSDP2 capacity gate; and
4. one eight-GPU two-client production qualification.

Never automatically submit the next gate or rerun a failure. Preserve and inspect each artifact first.

## Why this version is safe to attempt

The successful 32B production qualification used the same two-client, four-rank-per-client topology and completed
as Slurm job `31091793`. Its peak monitored GPU memory was 28,017 MiB. The 72B target has a larger sharded immutable
base and a 1.64 GiB selected layer, but remains below an 80 GB A100's nominal memory on a four-way shard by design.
The estimate is not treated as proof: the four-GPU gate loads this exact 72B snapshot, performs two real optimizer
steps, exports the exact selected state, and requires at least 8 GiB of measured reserved-memory headroom on every
rank before the eight-GPU job is allowed.

The production server does not instantiate the complete 72B base. It constructs only the final Qwen2 decoder layer
on a meta device, allocates that layer on CPU, and reads only its 12 tensors from the indexed safetensor shards.
This keeps the server and CPU preflight bounded to the 1,755,369,472-byte trainable state rather than approximately
145 GB of model weights.

The full job requests 1,400 GB of host RAM because eight independent training ranks can be in checkpoint loading
and FSDP2 initialization concurrently. The capacity gate requests 768 GB for four ranks. These conservative host
limits avoid turning an accelerator allocation into a host-memory experiment.

## Timeout and failure policy

There is no application-level total-runtime deadline. Healthy model loading, training, or a progressing tensor
transfer is not stopped because an arbitrary elapsed duration was crossed.

| Boundary | Value |
| --- | ---: |
| Full Slurm allocation | 3 hours |
| Four-GPU capacity-gate allocation | 90 minutes |
| Slurm TERM notice | 300 seconds before the allocation limit |
| 72B client readiness | 3,600 seconds |
| Post-readiness no-progress stall | 1,800 seconds |
| External init, task, runner, result, download, and tensor operations | 2,400 seconds |
| Streaming maximum peer silence | 3,600 seconds |
| Persisted-model capture | 2,400 seconds |
| Result resends | 3 |
| FedAvg workflow | no total task timeout |

The client calls `flare.init()` before heavyweight model loading. Readiness and stall clocks are separate, and
progress resets the inactivity clock. The checked-in exported-job preflight rejects missing large-model timeout
settings, late FLARE initialization, unbounded resends, missing datasets, or relaxed two-client startup.

## 1. Install the reviewed source bundle

Transfer the bundle through a Data Copier. From the Mac:

```bash
export BUNDLE=/Users/kevlu/Documents/codex/nvflare-72b-ready-v10.bundle

rsync -avP \
  "$BUNDLE" "$BUNDLE.sha256" \
  kevlu@cs-oci-ord-dc-02.nvidia.com:/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/incoming/
```

The macOS system `rsync` supports `-avP`; do not use unsupported `--append-verify` or `--info=progress2`.

On a Data Copier or login node:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export BUNDLE="$PROJECT_ROOT/incoming/nvflare-72b-ready-v10.bundle"

cd "$PROJECT_ROOT/incoming"
sha256sum --check "$(basename "$BUNDLE").sha256"
git -C "$REPO_ROOT" bundle verify "$BUNDLE"
BUNDLE_HEAD=$(git bundle list-heads "$BUNDLE" refs/heads/codex/llm-fl-real-14b | awk '{print $1}')
test -n "$BUNDLE_HEAD"

git -C "$REPO_ROOT" status --short --branch
git -C "$REPO_ROOT" fetch "$BUNDLE" refs/heads/codex/llm-fl-real-14b
git -C "$REPO_ROOT" merge --ff-only FETCH_HEAD

test "$(git -C "$REPO_ROOT" rev-parse HEAD)" = "$BUNDLE_HEAD"
test "$(cat "$REPO_ROOT/research/llm_fl_stress/real_training/QUALIFICATION_RELEASE")" \
  = "2026-07-30-trainable-72b-v10"
test -z "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)"
git -C "$REPO_ROOT" log -3 --oneline
```

`git bundle verify` needs an existing repository, hence the explicit `git -C "$REPO_ROOT"`. An `ahead N` report
against the bundle clone's old `origin` is harmless; the required facts are exact `BUNDLE_HEAD` and a clean tree.

## 2. Stage Qwen2.5-72B on a Data Copier

Do not download or checksum the model on a login or GPU node. The public model does not require a Hugging Face
token.

```bash
ssh kevlu@cs-oci-ord-dc-02.nvidia.com
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"

enroot start --mount "$PROJECT_ROOT:$PROJECT_ROOT" "$CONTAINER_IMAGE"

# Inside the container:
source "$PROJECT_ROOT/envs/nvflare-fsdp2/bin/activate"
export HF_HOME="$PROJECT_ROOT/cache/huggingface"
export MODEL_ID=Qwen/Qwen2.5-72B
export MODEL_REVISION=efba10c8e54e91e0d9570ab5f7b51a958474d4cb
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-72B-efba10c8e54e"

hf download "$MODEL_ID" \
  --revision "$MODEL_REVISION" \
  --local-dir "$MODEL_PATH"

printf '%s\n' "$MODEL_REVISION" > "$MODEL_PATH/REVISION"

test "$(python -c \
  'import json,sys; c=json.load(open(sys.argv[1])); print(c[\"hidden_size\"], c[\"intermediate_size\"], c[\"num_hidden_layers\"], c[\"num_attention_heads\"], c[\"num_key_value_heads\"], c[\"torch_dtype\"])' \
  "$MODEL_PATH/config.json")" = "8192 29568 80 64 8 bfloat16"

SHARD_COUNT=$(find "$MODEL_PATH" -maxdepth 1 -name 'model*.safetensors' -type f | wc -l)
test "$SHARD_COUNT" -eq 37

(
  cd "$MODEL_PATH"
  find . -path './.cache' -prune -o \
    -type f ! -name MANIFEST.sha256 -print0 |
    LC_ALL=C sort -z |
    xargs -0 sha256sum > MANIFEST.sha256
)

test -s "$MODEL_PATH/model.safetensors.index.json"
test -s "$MODEL_PATH/MANIFEST.sha256"
du -sh "$MODEL_PATH"
echo "72B staging PASS: revision=$MODEL_REVISION shards=$SHARD_COUNT"
exit
```

Expect approximately 145 GB of model weights and 37 safetensor shards. Manifest creation reads the snapshot once
on the Data Copier. Do not repeat the full checksum before every compute job.

## 3. Run the CPU production control-plane gate

This gate requests no GPU. It provisions a TLS server and two production clients, validates the generated
large-model lifecycle settings, and completes two consecutive required-two-client jobs.

```bash
ssh kevlu@cs-oci-ord-login-03.nvidia.com
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
cd "$REPO_ROOT"

CONTROL_JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/control_plane_preflight.slurm)
echo "CONTROL_JOB_ID=$CONTROL_JOB_ID"
```

Check once after several minutes; do not use `watch`:

```bash
sacct -j "$CONTROL_JOB_ID" \
  --format=JobID,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

CONTROL_ARTIFACT="$PROJECT_ROOT/artifacts/control-plane-$CONTROL_JOB_ID"
cat "$CONTROL_ARTIFACT/exported-job-preflight.json"
cat "$CONTROL_ARTIFACT/control-plane.json"
cat "$CONTROL_ARTIFACT/control-plane-job-1/summary.json"
cat "$CONTROL_ARTIFACT/control-plane-job-2/summary.json"
cat "$CONTROL_ARTIFACT/qualification.json"
```

Require `COMPLETED 0:0`, two connected sites, two jobs with `aggregated_results: 2`, and `PASS` everywhere.

## 4. Run the CPU 72B sparse-state and exported-job preflight

This job requests 32 GB on the CPU partition. It does not load the complete 72B checkpoint. It verifies the exact
model identity and shard layout, materializes only the final layer, checks the exact payload and 2 GiB safety
ceiling, exports the exact two-client job, and validates all packaged configuration and source.

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
cd "$REPO_ROOT"

PREFLIGHT_JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/model_72b_preflight.slurm)
echo "PREFLIGHT_JOB_ID=$PREFLIGHT_JOB_ID"
```

After it finishes:

```bash
sacct -j "$PREFLIGHT_JOB_ID" \
  --format=JobID,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

PREFLIGHT_ARTIFACT="$PROJECT_ROOT/artifacts/72b-preflight-$PREFLIGHT_JOB_ID"
cat "$PREFLIGHT_ARTIFACT/dependency-check.json"
cat "$PREFLIGHT_ARTIFACT/trainable-server-preflight.json"
cat "$PREFLIGHT_ARTIFACT/job-export.json"
cat "$PREFLIGHT_ARTIFACT/exported-job-preflight.json"
cat "$PREFLIGHT_ARTIFACT/manifest.txt"
```

Require `COMPLETED 0:0`, `PASS` in every JSON record, 37 shards, 12 trainable tensors, payload
`1755369472`, ceiling `2147483648`, two clients, four ranks per client, one target round, two local steps, early
FLARE initialization, strict startup, and timeout `2400`.

## 5. Run the real four-GPU 72B capacity gate

This is the only accelerator preflight. It does not use the simulator or NVFLARE services. Four torchrun ranks
load the exact 72B snapshot, apply FSDP2, load/export the exact trainable state through the NVFLARE FSDP2 bridge,
perform two real optimizer steps on the fixed site-1 partition, and export the changed state.

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
cd "$REPO_ROOT"

GPU_PREFLIGHT_JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/model_72b_gpu_preflight.slurm)
echo "GPU_PREFLIGHT_JOB_ID=$GPU_PREFLIGHT_JOB_ID"
GPU_PREFLIGHT_LOG="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-72b-gpu-gate-$GPU_PREFLIGHT_JOB_ID.out"
echo "GPU_PREFLIGHT_LOG=$GPU_PREFLIGHT_LOG"
tail -F "$GPU_PREFLIGHT_LOG"
```

`tail -F` does not poll Slurm. `Ctrl-C` stops only the local tail.

After completion:

```bash
sacct -j "$GPU_PREFLIGHT_JOB_ID" \
  --format=JobID,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

GPU_PREFLIGHT_ARTIFACT="$PROJECT_ROOT/artifacts/72b-gpu-preflight-$GPU_PREFLIGHT_JOB_ID"
cat "$GPU_PREFLIGHT_ARTIFACT/capacity-gate.json"
cat "$GPU_PREFLIGHT_ARTIFACT/manifest.txt"
```

Do not proceed unless Slurm is `COMPLETED 0:0`, the capacity event is `PASS`, world size is four, every GPU is an
A100-SXM4-80GB, the initial and final payloads are exactly `1755369472`, their hashes differ, every rank has a
finite loss and positive selected-parameter change, and every rank reports at least 8,192 MiB
`reserved_headroom_bytes`.

## 6. Submit one eight-GPU two-client 72B qualification

Only run this after all three preceding artifacts pass.

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
cd "$REPO_ROOT"

test "$(cat research/llm_fl_stress/real_training/QUALIFICATION_RELEASE)" \
  = "2026-07-30-trainable-72b-v10"
test -z "$(git status --porcelain --untracked-files=all)"

JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/two_client_72b_trainable.slurm)
echo "JOB_ID=$JOB_ID"
GPU_LOG="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-72b-trainable-$JOB_ID.out"
GPU_ERR="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-72b-trainable-$JOB_ID.err"
echo "GPU_LOG=$GPU_LOG"
echo "GPU_ERR=$GPU_ERR"
tail -F "$GPU_LOG"
```

Expected sequence:

1. exactly eight A100s pass the environment check;
2. both production TLS clients connect;
3. the two-round 1.5B exact-topology gate completes with 2/2 aggregation and persistence;
4. both 72B clients report ready;
5. both sites report one passing 72B round with two optimizer steps;
6. the server reports `Aggregated 2/2 results`;
7. persistence completes and reloads; and
8. the qualification summary reports `PASS`.

Do not cancel a healthy job merely because 72B startup is quiet. The target readiness allowance is one hour and
the post-ready no-progress allowance is 30 minutes. Inspect emitted progress and the separate ready-site list.

## 7. Accept the claim

After completion:

```bash
sacct -j "$JOB_ID" \
  --format=JobID,JobName%40,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

ARTIFACT="$PROJECT_ROOT/artifacts/$JOB_ID"
cat "$ARTIFACT/manifest.txt"
cat "$ARTIFACT/qualification.json"
cat "$ARTIFACT/gpu-monitor.json"
cat "$ARTIFACT/target-identity.json"
cat "$ARTIFACT/target-72b/summary.json"
cat "$ARTIFACT/target-72b/trainable-state-evidence.json"
```

Accept only if all of the following hold:

- Slurm is `COMPLETED` with exit code `0:0`;
- the manifest records `status=0`, `qualification_profile=trainable-72b`, and the reviewed Git commit;
- both the 1.5B gate and 72B target are `PASS`;
- the target has exactly two client round records and 2/2 aggregation;
- both sites used distinct fixed data and reported finite losses and positive optimizer changes;
- every trainable transfer is 12 tensors and exactly `1,755,369,472` bytes;
- the persisted checkpoint reloads and matches the sampled equal-weight mean of the two client outputs;
- all GPU indices 0–7 have positive monitored memory and utilization; and
- retained server and participant logs contain no fatal error marker.

This is the point at which it is accurate to say that real two-client last-layer federated training succeeded on
Qwen2.5-72B. A failed gate is diagnostic evidence, not permission to submit an automatic rerun.
