# CS-OCI-ORD two-client Qwen2.5-14B full-model qualification

**Qualification status:** Prepared, not yet run. This procedure is bound to release
`2026-07-31-full-model-14b-v12` and the clean bundle head captured during transfer. Do not describe the lane as
qualified until the final eight-GPU Slurm job and every retained evidence check below pass.

## Claim and evidence boundary

This runbook prepares one narrow, auditable claim:

> Two provisioned NVFLARE clients concurrently performed real full-model training of the pinned
> Qwen2.5-14B checkpoint, with four-rank FSDP2 per client on one eight-A100-SXM4-80GB node. Every model parameter
> was trainable, each client performed eight local optimizer steps over its own fixed data, both clients returned
> complete full-model states, the CPU-only server completed equal-weight 2/2 FedAvg aggregation, and the persistence
> watcher observed a stable nonempty full checkpoint at least as large as the exact logical state before cleanup.

The server and both clients run on the same physical Slurm node. The server has an empty
`CUDA_VISIBLE_DEVICES`; site-1 owns GPUs 0–3 and site-2 owns GPUs 4–7. They are separate provisioned NVFLARE
participants using ephemeral startup kits and TLS, but they are not separate machines or failure domains. Model
traffic is therefore same-node traffic, not a wide-area-network measurement.

This lane is intentionally different from the earlier 14B work:

| Lane | Client optimization | Federated state |
| --- | --- | --- |
| July 28 14B evidence | Last decoder layer only | Complete 579-tensor full state |
| This runbook | **All model parameters** | **Complete 579-tensor full state** |

The earlier result proved that the complete 29.54 GB state can cross this FSDP2/NVFLARE boundary. It did **not**
prove that gradients and optimizer state for every parameter fit or execute. The one-client four-GPU capacity gate
in this runbook exists specifically to prove that new resource boundary before an eight-GPU submission.

The exact target contract is:

| Property | Required value |
| --- | --- |
| Model | `Qwen/Qwen2.5-14B` |
| Revision | `97e1e76335b7017d8f67c08a19d103c0504298c9` |
| Architecture / dtype | `Qwen2ForCausalLM` / BF16 |
| Hidden / intermediate size | 5,120 / 13,824 |
| Decoder layers | 48 |
| Attention / key-value heads | 40 / 8 |
| Safetensor shards | 8 |
| Full exchanged state | 579 tensors / 29,540,067,328 bytes |
| Client trainable target | `all` |
| Federated state scope | `full` |
| Transfer semantics | Absolute full states, not deltas |
| Clients / FSDP2 ranks | 2 / 4 ranks per client |
| GPU mapping | site-1: 0–3; site-2: 4–7 |
| Target work | 1 federated round, 8 local steps per rank |
| Sequence length | 512 tokens |
| Site data | Distinct fixed JSONL partitions with pinned SHA-256 values |
| Aggregation | Explicit equal site weights, 2/2 required |
| Required software release | `2026-07-31-full-model-14b-v12` |
| Required Git commit | Clean bundle head captured as `EXPECTED_HEAD` during transfer |

`trainable_target=all` means that every client parameter must have `requires_grad=True`; the evidence must report
zero frozen parameters. `state_scope=full` means rank zero receives and exports the complete CPU state through the
FSDP2 bridge. `TransferType.FULL` means the server averages the two absolute client models. It does not interpret
the payloads as parameter differences.

Eight local steps at four ranks consume 32 records per site. The packaged site-1 and site-2 JSONL partitions must
have distinct checksums, and each site must report 32 unique record IDs for the target round. A run using the
embedded fallback text, the same partition at both sites, or missing sample-ID evidence does not satisfy this
claim.

## Optimizer and memory caveat

The clients construct PyTorch `AdamW` directly over the BF16 FSDP2 parameters. In the reviewed stack, Adam moment
buffers are expected to follow the BF16 parameter dtype. The capacity and production evidence must record the
actual optimizer-state dtypes, byte counts, and parameter coverage. A pass supports the claim that this BF16
optimizer-state path executed; it does **not** establish FP32 Adam moments, FP32 master weights, or equivalence to a
mixed-precision training system that retains FP32 optimizer state.

The four-GPU gate fails unless its aggregated `AdamW` evidence has `foreach=false`, `fused=false`, and exactly two
BF16 moment values for every one of the 14,770,033,664 trainable parameters: 29,540,067,328 values occupying
59,080,134,656 bytes. FP32 scalar step counters may also appear in the dtype histogram; they are not counted as
moment coverage.

Before activations and FSDP communication buffers, the approximate four-way per-GPU persistent state is:

| State | Approximate amount per GPU |
| --- | ---: |
| BF16 parameter shard | 6.88 GiB |
| BF16 gradient shard | 6.88 GiB |
| Two BF16 Adam moment shards | 13.76 GiB |
| Approximate subtotal | 27.51 GiB |

This estimate is planning input, not acceptance evidence. Gradient checkpointing, activation memory at length
512, FSDP2 all-gather/reduce buffers, allocator fragmentation, and full-state export add to it. The exact four-GPU
gate must run the same eight-step, length-512 workload and retain at least 16 GiB of reserved-memory headroom on
every rank.

The qualification must not create an FP32 clone of every trainable shard merely to prove that parameters changed.
Change evidence is bounded to deterministic representative parameters and gradients from early, middle, and late
model regions. The gate must also report that all trainable parameters are covered by the optimizer.

## Topology and resource contract

| Stage | GPUs | CPUs | Host RAM | Slurm wall | Purpose |
| --- | ---: | ---: | ---: | ---: | --- |
| Control-plane gate | 0 | 4 | 16 GiB | 15 min | TLS services and two consecutive 2/2 jobs |
| CPU model/export preflight | 0 | 16 | 128 GiB | 1 hour | Full server model, identity, recipe, and exported job |
| Exact capacity gate | 4 x A100 80 GB | 32 | 256 GiB | 1 hour | One client's exact all-parameter workload |
| Production qualification | 8 x A100 80 GB | 64 | 512 GiB | 2 hours | Server plus two concurrent four-rank clients |

The three model-bearing wrappers fail before model loading unless the actual Slurm environment matches this table.
The CPU preflight requires `SLURM_MEM_PER_NODE >= 131072` MiB and at least 3,300 seconds remaining; the GPU gate
requires at least 262,144 MiB, exactly four `SLURM_GPUS_ON_NODE`, and 3,300 seconds remaining; production requires
at least 524,288 MiB, exactly eight GPUs, and 6,900 seconds remaining. Remaining time is computed from the documented
`SLURM_JOB_END_TIME` epoch. Each manifest retains the observed memory, GPU count when applicable, end/check epochs,
and remaining seconds; login readiness rejects undersized or internally inconsistent preflight records.

The production server is CPU-only. It holds the global state, performs in-time equal-weight aggregation, and
persists the result. It does not perform forward, backward, or optimizer work. The four-GPU capacity result must
project its measured one-client host RSS to two clients and then include a conservative server allowance of at
least three complete 29,540,067,328-byte states plus a fixed 128 GiB reserve. The projected total must remain below
512 GiB.

Production also samples process-tree RSS/PSS, system-available memory, and scratch space throughout the run. When
the node exposes the Slurm allocation's cgroup-v2 memory controller, it additionally records allocation-wide
current/peak memory and fails on new limit, OOM, or OOM-kill events. If that controller is not exposed inside the
container, the artifact explicitly reports the narrower `process-tree-plus-system` telemetry scope instead of
failing a correct training run for a host instrumentation difference.

The live workspace is under `/raid/scratch/$USER/$SLURM_JOB_ID`. Before services start, production must prove at
least 200 GiB of free local scratch and 100,000 free inodes. This covers disk-backed incoming tensors, the global
state, aggregation/persistence transients, logs, and evidence. Lustre stores the source, model, environment, and
retained evidence; node-local scratch is ephemeral and is removed by the guarded cleanup path.

## Timeout inventory and failure policy

There is no application-level total-runtime deadline. A healthy job must not be marked failed merely because a
model load, optimizer step, state transfer, or persistence operation took longer than an expected duration. The
two-hour Slurm allocation is the unavoidable whole-run ceiling.

Readiness and no-progress supervision are separate. Before both clients report ready, the readiness clock covers
model load and FSDP2 sharding. After both clients are ready, the stall clock resets on log-visible local-step,
accepted stream-transfer, result-submission, aggregation, or persistence progress. There is no intra-step compute
heartbeat: a single silent forward/backward/optimizer operation lasting 1,800 seconds could still reach the stall
boundary. The capacity gate therefore records model-ready and post-ready totals without imposing a live timing
cutoff, and login readiness permits the final submission only when each observed total is at most 1,500 seconds,
leaving a 300-second margin beneath the corresponding 1,800-second watchdog.

| Boundary | Required value |
| --- | ---: |
| Production Slurm wall | 2 hours |
| Slurm TERM notice | 300 seconds before the wall |
| Production service registration | 300 seconds |
| Gate and target client readiness | At least 1,800 seconds |
| Post-ready no-progress stall | At least 1,800 seconds, progress-aware |
| Capacity-gate feasibility margin below both watchdogs | 300 seconds |
| External init, heartbeat, task, runner, result, and download operations | 10,800 seconds |
| Tensor transfer per request and minimum download | 10,800 seconds |
| F3 ACK wait, ACK-progress, stream read, and send guards | 10,800 seconds |
| Streaming idle | 10,800 seconds |
| Compatibility maximum peer silence | 16,200 seconds |
| External launcher shutdown | 600 seconds |
| Persisted-model capture | 7,200 seconds |
| Result resends | 3 |
| FedAvg workflow | No total task timeout |

Slurm may deliver a requested pre-time-limit signal up to 60 seconds earlier than the nominal offset. Treat the
two-hour production request as approximately 114 minutes of usable time before the earliest TERM notice, not as a
promise of a full 115-minute compute window.

The exported-job preflight must reject late `flare.init()`, missing timeout keys, generic timeout keys that do not
control PyTorch tensor transfers, relaxed required-client startup, missing datasets, unbounded resends, or a short
launcher shutdown. The final wrapper must also reject inherited `NCCL_P2P_DISABLE`; CS-OCI-ORD NVLink/NCCL defaults
are part of the qualified topology.

Never automatically submit the next stage, requeue a failure, or rerun the final job. Each stage is submitted once
by a person after the previous evidence is inspected. A failure is evidence to diagnose, not permission for an
automatic retry. The control gate, CPU model preflight, four-GPU gate, and final wrapper all pin
`#SBATCH --no-requeue`, so this policy does not depend on the cluster's default `JobRequeue` setting.

## 1. Install the reviewed source bundle

Create and transfer the final bundle only after the implementation, tests, and this runbook have been reviewed.
On the Mac:

```bash
export LOCAL_REPO=/Users/kevlu/Documents/codex/worktrees/secondcopynvflare-14b
export EXPECTED_HEAD="$(git -C "$LOCAL_REPO" rev-parse HEAD)"
export BUNDLE=/Users/kevlu/Documents/codex/nvflare-14b-full-model-v12.bundle

test "$(git -C "$LOCAL_REPO" rev-parse HEAD)" = "$EXPECTED_HEAD"
test -z "$(git -C "$LOCAL_REPO" status --porcelain --untracked-files=all)"
test "$(cat "$LOCAL_REPO/research/llm_fl_stress/real_training/QUALIFICATION_RELEASE")" \
  = "2026-07-31-full-model-14b-v12"

git -C "$LOCAL_REPO" bundle create "$BUNDLE" codex/llm-fl-real-14b
git -C "$LOCAL_REPO" bundle verify "$BUNDLE"
(cd "$(dirname "$BUNDLE")" && shasum -a 256 "$(basename "$BUNDLE")" > "$(basename "$BUNDLE").sha256")

rsync -avP \
  "$BUNDLE" "$BUNDLE.sha256" \
  kevlu@cs-oci-ord-dc-02.nvidia.com:/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/incoming/
```

The macOS system `rsync` supports `-avP`; do not use `--append-verify` or `--info=progress2`.

On a Data Copier or login node:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export BUNDLE="$PROJECT_ROOT/incoming/nvflare-14b-full-model-v12.bundle"

cd "$PROJECT_ROOT/incoming"
sha256sum --check "$(basename "$BUNDLE").sha256"
git -C "$REPO_ROOT" bundle verify "$BUNDLE"
EXPECTED_HEAD=$(git bundle list-heads "$BUNDLE" refs/heads/codex/llm-fl-real-14b | awk '{print $1}')
test "$EXPECTED_HEAD" != ""
HEAD_FILE="$BUNDLE.head"
printf '%s\n' "$EXPECTED_HEAD" > "$HEAD_FILE"
chmod 600 "$HEAD_FILE"
test "$(cat "$HEAD_FILE")" = "$EXPECTED_HEAD"

git -C "$REPO_ROOT" status --short --branch
test -z "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)"
git -C "$REPO_ROOT" fetch "$BUNDLE" refs/heads/codex/llm-fl-real-14b
git -C "$REPO_ROOT" merge --ff-only FETCH_HEAD

test "$(git -C "$REPO_ROOT" rev-parse HEAD)" = "$EXPECTED_HEAD"
test "$(git -C "$REPO_ROOT" branch --show-current)" = "codex/llm-fl-real-14b"
test "$(cat "$REPO_ROOT/research/llm_fl_stress/real_training/QUALIFICATION_RELEASE")" \
  = "2026-07-31-full-model-14b-v12"
test -z "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)"
git -C "$REPO_ROOT" log -3 --oneline
```

`git bundle verify` needs an existing repository, which is why the command uses `git -C "$REPO_ROOT"`. An
`ahead N` report against the bundle clone's old file-based `origin` is harmless. Exact `HEAD`, the release marker,
the named branch, and a clean tree are mandatory. The adjacent `.head` file is the durable transfer-derived commit
identity; do not regenerate it from the live checkout during later stages.

## 2. Verify the pinned model and environment

The existing Qwen2.5-14B snapshot must remain at:

```text
/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/models/Qwen2.5-14B-97e1e76335b7
```

Do not download or hash the 30 GB model on a login or GPU node. Use a Data Copier for any restaging or full
checksum. From a Data Copier container session:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
export MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-14B-97e1e76335b7"
export MODEL_REVISION=97e1e76335b7017d8f67c08a19d103c0504298c9

sha256sum --check "$CONTAINER_IMAGE.sha256"
sha256sum "$CONTAINER_IMAGE.sha256" > "$CONTAINER_IMAGE.sha256.verified"

enroot start --mount "$PROJECT_ROOT:$PROJECT_ROOT" "$CONTAINER_IMAGE"

# Inside the container:
source "$PROJECT_ROOT/envs/nvflare-fsdp2/bin/activate"
test "$(cat "$MODEL_PATH/REVISION")" = "$MODEL_REVISION"
test "$(python -c \
  'import json,sys; c=json.load(open(sys.argv[1])); print(c["hidden_size"], c["intermediate_size"], c["num_hidden_layers"], c["num_attention_heads"], c["num_key_value_heads"], c["torch_dtype"])' \
  "$MODEL_PATH/config.json")" = "5120 13824 48 40 8 bfloat16"

test -s "$MODEL_PATH/model.safetensors.index.json"
test "$(find "$MODEL_PATH" -maxdepth 1 -name 'model-*.safetensors' -type f | wc -l | tr -d ' ')" = "8"
test -s "$MODEL_PATH/MANIFEST.sha256"
test -s "$MODEL_PATH/MANIFEST.sha256.verified"
test "$(python -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["metadata"]["total_size"])' \
  "$MODEL_PATH/model.safetensors.index.json")" = "29540067328"

(cd "$MODEL_PATH" && sha256sum --check MANIFEST.sha256)
sha256sum "$MODEL_PATH/MANIFEST.sha256" > "$MODEL_PATH/MANIFEST.sha256.verified"
du -sh "$MODEL_PATH"
exit
```

The full manifest check intentionally rereads the complete snapshot. Perform it on a Data Copier once for this
release. Later gates hash only the small manifest/marker and reject files changed after the marker.

The environment and container must already exist from the general
[CS-OCI-ORD real-training runbook](cs-oci-ord-real-training-runbook.md). Do not rebuild dependencies in a GPU
allocation.

## 3. Run the CPU production control-plane gate

This gate requests no GPU. It verifies provisioned TLS services, both required client identities, exact transport
settings, strict two-client startup, and two consecutive 2/2 control jobs at the reviewed commit.

```bash
ssh kevlu@cs-oci-ord-login-03.nvidia.com
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export HEAD_FILE="$PROJECT_ROOT/incoming/nvflare-14b-full-model-v12.bundle.head"
cd "$REPO_ROOT"

test -s "$HEAD_FILE"
export EXPECTED_HEAD="$(cat "$HEAD_FILE")"
test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test -z "$(git status --porcelain --untracked-files=all)"

CONTROL_JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/control_plane_preflight.slurm)
echo "CONTROL_JOB_ID=$CONTROL_JOB_ID"
```

Check once after several minutes; do not use `watch`:

```bash
sacct -j "$CONTROL_JOB_ID" \
  --format=JobID,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

CONTROL_ARTIFACT="$PROJECT_ROOT/artifacts/control-plane-$CONTROL_JOB_ID"
cat "$CONTROL_ARTIFACT/manifest.txt"
cat "$CONTROL_ARTIFACT/exported-job-preflight.json"
cat "$CONTROL_ARTIFACT/environment.json"
cat "$CONTROL_ARTIFACT/services/transport-config.json"
cat "$CONTROL_ARTIFACT/control-plane.json"
cat "$CONTROL_ARTIFACT/control-plane-job-1/summary.json"
cat "$CONTROL_ARTIFACT/control-plane-job-2/summary.json"
cat "$CONTROL_ARTIFACT/qualification.json"
```

Require Slurm `COMPLETED 0:0`, exact commit/release evidence, connected clients `site-1` and `site-2`, two
consecutive completed jobs with `aggregated_results: 2`, provisioned TLS, and all operation/transport timeout
values at 10,800 seconds. Stop on any mismatch.

## 4. Run the CPU full-model server and exported-job preflight

This CPU job validates the exact model/index/manifest, instantiates the complete CPU BF16 `HFTextModel` used by the
server, requires a 579-tensor 29,540,067,328-byte state, records server-model RSS, and exports the exact two-client
job. The exported-job validator must prove `trainable_target=all`, `state_scope=full`, eight local steps, maximum
length 512, four torchrun ranks, distinct packaged site data/checksums, equal aggregation weights, early
`flare.init()`, strict startup, and the full timeout inventory.

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
cd "$REPO_ROOT"

PREFLIGHT_JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/model_14b_full_model_preflight.slurm)
echo "PREFLIGHT_JOB_ID=$PREFLIGHT_JOB_ID"
```

After completion:

```bash
sacct -j "$PREFLIGHT_JOB_ID" \
  --format=JobID,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

PREFLIGHT_ARTIFACT="$PROJECT_ROOT/artifacts/14b-full-model-preflight-$PREFLIGHT_JOB_ID"
cat "$PREFLIGHT_ARTIFACT/manifest.txt"
cat "$PREFLIGHT_ARTIFACT/static-readiness.json"
cat "$PREFLIGHT_ARTIFACT/dependency-check.json"
cat "$PREFLIGHT_ARTIFACT/full-state-server-preflight.json"
cat "$PREFLIGHT_ARTIFACT/job-export.json"
cat "$PREFLIGHT_ARTIFACT/exported-job-preflight.json"
```

Do not advance unless Slurm is `COMPLETED 0:0` and every record is `PASS`. The server preflight must report the
exact revision, 579 state tensors, 29,540,067,328 payload bytes, successful model construction/state materialization,
and a peak RSS within the 128 GiB allocation. The exported job must contain exactly two client apps and one server app;
both client launchers must contain the reviewed `all`, `full`, `8`, `512`, dataset, checksum, and 10,800-second
arguments.

NVFLARE may emit `PotentialSecretWarning` for the public 40-character Hugging Face revision SHA. That heuristic
warning does not stop export and is not a failure for this pinned public revision; never apply that exception to an
actual credential or access token.

## 5. Run the exact one-client four-GPU capacity gate

This is the only accelerator preflight. It does not start NVFLARE services and does not use `SimEnv`. Four
torchrun ranks load the pinned 14B snapshot, select all parameters, apply FSDP2, exercise full-state load/export,
and perform the exact eight-step, length-512 site-1 workload.

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
cd "$REPO_ROOT"

GPU_PREFLIGHT_JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/model_14b_full_model_gpu_preflight.slurm)
echo "GPU_PREFLIGHT_JOB_ID=$GPU_PREFLIGHT_JOB_ID"

GPU_PREFLIGHT_LOG="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-14b-full-model-gpu-gate-$GPU_PREFLIGHT_JOB_ID.out"
echo "GPU_PREFLIGHT_LOG=$GPU_PREFLIGHT_LOG"
tail -F "$GPU_PREFLIGHT_LOG"
```

`tail -F` reads a file and does not poll Slurm. While the job is pending, one initial `cannot open ... No such file`
message is expected because Slurm creates the output file only after allocation; `-F` keeps retrying. `Ctrl-C` stops
only the local tail.

After completion:

```bash
sacct -j "$GPU_PREFLIGHT_JOB_ID" \
  --format=JobID,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

GPU_PREFLIGHT_ARTIFACT="$PROJECT_ROOT/artifacts/14b-full-model-gpu-preflight-$GPU_PREFLIGHT_JOB_ID"
cat "$GPU_PREFLIGHT_ARTIFACT/manifest.txt"
cat "$GPU_PREFLIGHT_ARTIFACT/static-readiness.json"
cat "$GPU_PREFLIGHT_ARTIFACT/capacity-gate.json"
```

Require all of the following before proceeding:

- Slurm `COMPLETED 0:0` and capacity status `PASS`;
- exact release, Git commit, model revision, and model identity;
- four ranks on four exact `NVIDIA A100-SXM4-80GB` devices;
- `trainable_target=all`, `state_scope=full`, eight local steps, and maximum length 512;
- total parameter count equals trainable parameter count and frozen parameter count is zero;
- finite positive loss and finite nonzero representative gradients/updates from early, middle, and late regions;
- aggregated `AdamW` evidence proves `foreach=false`, `fused=false`, and exactly 29,540,067,328 BF16 moment values
  occupying 59,080,134,656 bytes, while recording any additional optimizer-state dtypes separately;
- initial and final full exports each contain 579 tensors and 29,540,067,328 bytes;
- the bounded parameter probes prove that the optimizer changed the model without a full FP32 parameter snapshot;
- each rank retains at least 16,384 MiB of PyTorch reserved-memory headroom;
- the projected two-client plus full-state server host footprint, including the fixed 128 GiB reserve, is below
  512 GiB; and
- no CUDA, NCCL, FSDP2, optimizer, dataset, or state-bridge error occurred.

The gate itself has no live model-ready or work-time cutoff. Its observed totals are telemetry during the expensive
allocation, but they become a pre-submission feasibility requirement: login readiness requires model-ready time and
post-ready work each to be at most 1,500 seconds, retaining a 300-second margin below the final 1,800-second
readiness and stall watchdogs. A slower correct gate is preserved as evidence but blocks the final submission until
the timeout design is reviewed; do not weaken or bypass the readiness validator.

## 6. Run the login-node readiness validator

The read-only validator binds the three passing gate IDs to the exact current source, release, model/container
freshness markers, recipe, resources, and evidence. It does not invoke Slurm, import the training stack, read all
model weights, or start services.

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export HEAD_FILE="$PROJECT_ROOT/incoming/nvflare-14b-full-model-v12.bundle.head"
cd "$REPO_ROOT"
test -s "$HEAD_FILE"
export EXPECTED_HEAD="$(cat "$HEAD_FILE")"
test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"

: "${CONTROL_JOB_ID:?set CONTROL_JOB_ID to the passing control-plane job}"
: "${PREFLIGHT_JOB_ID:?set PREFLIGHT_JOB_ID to the passing CPU/export preflight}"
: "${GPU_PREFLIGHT_JOB_ID:?set GPU_PREFLIGHT_JOB_ID to the passing four-GPU capacity gate}"

unset NCCL_P2P_DISABLE MODEL_PATH TARGET_MODEL_PATH GATE_MODEL_PATH
unset TARGET_READY_TIMEOUT TARGET_STALL_TIMEOUT GATE_READY_TIMEOUT GATE_STALL_TIMEOUT
unset SERVICE_STARTUP_TIMEOUT QUALIFICATION_PROFILE

READINESS_ARTIFACT="$PROJECT_ROOT/artifacts/14b-full-model-login-readiness.json"
python3 \
  research/llm_fl_stress/real_training/cs_oci_ord/validate_14b_full_model_readiness.py \
  --project-root "$PROJECT_ROOT" \
  --control-job-id "$CONTROL_JOB_ID" \
  --cpu-job-id "$PREFLIGHT_JOB_ID" \
  --gpu-job-id "$GPU_PREFLIGHT_JOB_ID" \
  | tee "$READINESS_ARTIFACT"

grep -q '"safe_to_submit": true' "$READINESS_ARTIFACT"
grep -q '"status": "PASS"' "$READINESS_ARTIFACT"
grep -q '"release": "2026-07-31-full-model-14b-v12"' "$READINESS_ARTIFACT"
grep -q "\"git_commit\": \"$EXPECTED_HEAD\"" "$READINESS_ARTIFACT"
```

If this exits nonzero, stop. Never weaken the validator to make stale evidence pass. If source changes, create a
new reviewed bundle and rerun every gate whose exact-commit artifact is invalidated.

## 7. Submit one eight-GPU production qualification

Only submit after the preceding validator passes. Submission is manual and singular:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export HEAD_FILE="$PROJECT_ROOT/incoming/nvflare-14b-full-model-v12.bundle.head"
cd "$REPO_ROOT"
test -s "$HEAD_FILE"
export EXPECTED_HEAD="$(cat "$HEAD_FILE")"

test "$(git rev-parse HEAD)" = "$EXPECTED_HEAD"
test "$(cat research/llm_fl_stress/real_training/QUALIFICATION_RELEASE)" \
  = "2026-07-31-full-model-14b-v12"
test -z "$(git status --porcelain --untracked-files=all)"

unset NCCL_P2P_DISABLE MODEL_PATH TARGET_MODEL_PATH GATE_MODEL_PATH
unset TARGET_READY_TIMEOUT TARGET_STALL_TIMEOUT GATE_READY_TIMEOUT GATE_STALL_TIMEOUT
unset SERVICE_STARTUP_TIMEOUT QUALIFICATION_PROFILE

JOB_ID=$(sbatch --parsable \
  --export=ALL,CONTROL_JOB_ID="$CONTROL_JOB_ID",PREFLIGHT_JOB_ID="$PREFLIGHT_JOB_ID",GPU_PREFLIGHT_JOB_ID="$GPU_PREFLIGHT_JOB_ID" \
  research/llm_fl_stress/real_training/cs_oci_ord/two_client_14b_full_model.slurm)
echo "JOB_ID=$JOB_ID"

GPU_LOG="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-14b-full-model-$JOB_ID.out"
GPU_ERR="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-14b-full-model-$JOB_ID.err"
echo "GPU_LOG=$GPU_LOG"
echo "GPU_ERR=$GPU_ERR"
tail -F "$GPU_LOG"
```

While the job is pending, one initial `cannot open ... No such file` from `tail -F` is expected because Slurm has
not created the log yet. `-F` keeps retrying, and `Ctrl-C` stops only the local tail, not the Slurm job.

The final wrapper must rerun the same readiness validator inside the allocation before model loading. Expected
sequence:

1. allocation-start readiness repeats `PASS` for the same three gate IDs and commit;
2. exactly eight A100-SXM4-80GB GPUs and the dependency set pass;
3. at least 200 GiB of local scratch and 100,000 inodes pass;
4. the CPU-only server and both provisioned TLS clients connect;
5. the exact-topology small-model all-parameter/full-state gate passes;
6. both 14B clients report ready with four ranks and zero frozen parameters;
7. both clients perform eight local steps over distinct fixed data;
8. both complete full-state export and result submission;
9. the server reports `Aggregated 2/2 results` with equal weights;
10. full-state persistence completes, and the watcher observes a stable nonempty checkpoint before cleanup and
    retains size metadata at least as large as the exact logical state; and
11. the top-level qualification reports `PASS` and the wrapper exits zero.

Do not cancel a healthy job because startup or a full-state transfer is quiet. Use the progress records and the
separate readiness/stall clocks. Do not submit another copy while this job is pending or running.

## 8. Inspect and accept the retained evidence

After the job leaves `squeue`, use accounting once:

```bash
sacct -j "$JOB_ID" \
  --format=JobID,JobName%44,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

ARTIFACT="$PROJECT_ROOT/artifacts/$JOB_ID"
cat "$ARTIFACT/manifest.txt"
cat "$ARTIFACT/allocation-start-readiness.json"
cat "$ARTIFACT/dependency-check.json"
cat "$ARTIFACT/environment.json"
cat "$ARTIFACT/scratch-capacity.json"
cat "$ARTIFACT/services/transport-config.json"
cat "$ARTIFACT/control-plane.json"
cat "$ARTIFACT/gpu-monitor.json"
cat "$ARTIFACT/allocation-monitor.json"
test -s "$ARTIFACT/allocation-memory.jsonl"
tail -n 20 "$ARTIFACT/allocation-memory.jsonl"
cat "$ARTIFACT/target-identity.json"
cat "$ARTIFACT/gate-1.5b/summary.json"
cat "$ARTIFACT/target-14b-full-model/summary.json"
cat "$ARTIFACT/target-14b-full-model/persistence/persisted_model.json"
cat "$ARTIFACT/qualification.json"
```

Inspect fatal markers without repeatedly querying Slurm:

```bash
rg -n \
  'Traceback|CUDA out of memory|OutOfMemoryError|NCCL.*(WARN|ERROR)|distributed round failed|EXECUTION_EXCEPTION|SYSTEM_PANIC|UnsafeComponentError' \
  "$ARTIFACT" "$GPU_LOG" "$GPU_ERR" || true
```

Accept the claim only when every condition below holds:

- Slurm is `COMPLETED` with exit code `0:0`;
- the manifest records status zero, `full-model-14b`, release `2026-07-31-full-model-14b-v12`, and
  `$EXPECTED_HEAD`, plus at least 524,288 MiB, exactly eight GPUs, and at least 6,900 seconds remaining at its
  allocation check;
- allocation-start readiness is `PASS` and names the exact control, CPU, and GPU gate IDs;
- the environment reports eight exact A100-SXM4-80GB GPUs and all transport settings equal 10,800;
- scratch evidence reports at least 200 GiB free and 100,000 inodes before services start;
- the gate and target summaries both report `trainable_target=all` and `state_scope=full`;
- each target site reports one round, four ranks, eight local steps, length 512, finite losses, and a loss trajectory
  of length eight;
- the two dataset SHA-256 values differ, each site reports 32 unique record IDs, and no site used fallback text;
- total and trainable parameter counts match, frozen count is zero, representative early/middle/late gradients and
  updates are finite and nonzero, and optimizer-state coverage is complete;
- optimizer-state dtype and byte telemetry is present, with no claim that the moments were FP32;
- every received and returned state has exactly 579 tensors and 29,540,067,328 bytes;
- bounded input probes show both clients started from a common global-state schema and sampled values, and each
  client's denser optimizer-update probe proves a positive model change;
- the server accepted both contributions, applied explicit equal weights, and logged 2/2 aggregation;
- retained persistence metadata proves the watcher observed a stable nonempty checkpoint of at least
  29,540,067,328 bytes before private-scratch cleanup;
- every GPU index 0–7 has positive monitored memory and utilization and every rank reports valid memory telemetry;
- the four-GPU gate and production rank telemetry retain at least 16 GiB of reserved GPU headroom; and
- retained logs contain no fatal CUDA, NCCL, FSDP2, runner, transfer, aggregation, or persistence error.

Any missing condition is a failure of the formal claim, even if some training occurred. Preserve the job ID and
artifacts, diagnose the first failed invariant, and review a correction before deciding whether a manual rerun is
worth the resource cost.

## Explicit non-claims

A successful artifact does not establish:

- convergence, downstream quality, generalization, or a useful trained checkpoint;
- that eight local steps or one federated round are an appropriate training schedule;
- FP32 Adam moments, FP32 master weights, or numerical equivalence to conventional mixed-precision training;
- multi-node networking, cross-site latency, fault tolerance, or independent administrative domains;
- privacy, secure aggregation, differential privacy, or protection from a colocated server;
- production throughput, cost efficiency, optimal GPU utilization, or scaling beyond two clients;
- multi-round state continuity, because the target has one federated round;
- a post-run reload of the 29.54 GB persisted full checkpoint or an independent tensor-by-tensor numerical
  reconstruction of the FedAvg result; the evidence establishes the configured equal weights, both accepted
  contributions, server 2/2 aggregation, and completed persistence instead;
- full-model training capacity for 32B, 72B, another architecture, another sequence length, or another optimizer;
  or
- that full-state federation is efficient for repeated training. One round moves approximately 118.16 GB of
  logical model state across the four server/client directions before serialization overhead.

The defensible result is narrower: the pinned 14B model, reviewed software release, exact one-node topology,
all-parameter BF16 AdamW path, full-state FSDP2 bridge, two required clients, equal-weight aggregation, and
persistence completed once with the retained evidence above.
