# CS-OCI-ORD two-client Qwen2.5-72B last-layer qualification

**Qualification status:** Passed on 2026-07-30 as Slurm job `31158690` (`COMPLETED 0:0` in 28:13).
See [the retained qualification report](cs-oci-ord-two-client-72b-qualification-2026-07-30.md) for the exact
topology, training, aggregation, persistence, memory, GPU, transfer, and evidence boundaries. Do not repeat the
qualification unless a new experiment requires a materially different proof.

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
| Indexed BF16 tensor bytes | 145,412,407,296 |
| Selected final-layer parameters | 877,684,736 |
| Trainable tensors / payload | 12 / 1,755,369,472 bytes |
| Clients / FSDP2 ranks | 2 / 4 ranks per client |
| GPU mapping | site-1: 0–3; site-2: 4–7 |
| Target work | 1 federated round, 2 optimizer steps per rank |
| State scope | final decoder layer only |
| Required software release | `2026-07-30-trainable-72b-v11` |

The target must pass four pre-submission gates and then the final qualification in order:

1. CPU production control-plane qualification;
2. CPU sparse-model, identity, recipe, and exported-job preflight;
3. one real four-GPU 72B FSDP2 capacity gate; and
4. the login-node exact-commit/readiness validator; then
5. one eight-GPU two-client production qualification.

Never automatically submit the next gate or rerun a failure. Preserve and inspect each artifact first.

## Why this version is safe to attempt

The successful 32B production qualification used the same two-client, four-rank-per-client topology and completed
as Slurm job `31091793`. Its peak monitored GPU memory was 28,017 MiB. The 72B target has a larger sharded immutable
base and a 1.64 GiB selected layer, but remains below an 80 GB A100's nominal memory on a four-way shard by design.
The estimate is not treated as proof: the four-GPU gate loads this exact 72B snapshot, performs two real optimizer
steps, exports the exact selected state, and requires at least 16 GiB of PyTorch reserved-memory headroom on every
rank before the eight-GPU job is allowed. It also rejects a model that takes more than 40 minutes to become ready,
post-readiness work longer than 20 minutes, or a measured two-client host-memory projection that does not fit the
production allocation with a fixed 128 GiB reserve.

The production server does not instantiate the complete 72B base. It constructs only the final Qwen2 decoder layer
on a meta device, allocates that layer on CPU, and reads only its 12 tensors from the indexed safetensor shards.
This keeps the server and CPU preflight bounded to the 1,755,369,472-byte trainable state rather than approximately
145 GB of model weights.

The full job requests 1,600 GiB of host RAM because eight independent training ranks can be in checkpoint loading
and FSDP2 initialization concurrently. The capacity gate requests 900 GiB for four ranks. The gate sums the measured
four-rank peak RSS, projects it to two clients, adds the physical checkpoint bytes and a fixed 128 GiB reserve, and
requires that result to fit 1,600 GiB. These conservative limits avoid turning an accelerator allocation into a
host-memory experiment.

## Timeout and failure policy

There is no application-level total-runtime deadline. Healthy model loading, training, or a progressing tensor
transfer is not stopped by a separate qualification watchdog. The Slurm allocation still has a hard four-hour
partition limit; no in-process timeout can extend it. The four-GPU gate therefore requires this exact model to
become ready within 40 minutes and finish its post-readiness work within 20 minutes before the final job is allowed.

| Boundary | Value |
| --- | ---: |
| CPU control-plane allocation | 15 minutes |
| Each synthetic control-plane job | 180 seconds total |
| CPU sparse-model/export preflight allocation | 1 hour |
| Full Slurm allocation | 4 hours (partition maximum) |
| Four-GPU capacity-gate allocation | 2 hours |
| Slurm TERM notice | 300 seconds before the allocation limit |
| Production service registration | 300 seconds |
| 1.5B gate readiness / stall | 900 / 900 seconds |
| 72B client readiness | 7,200 seconds |
| Post-readiness no-progress stall | 1,800 seconds |
| External init, task, runner, result, download, last-result, and tensor operations | 10,800 seconds |
| Subprocess tensor-download request | 10,800 seconds, propagated into its live FOBS context |
| F3 flow-control ACK wait, ACK-progress, receiver-read, and socket-send guards | 10,800 seconds in every provisioned `comm_config.json` and inherited environment |
| Streaming idle/no-progress | 10,800 seconds |
| Compatibility-only `streaming_max_peer_silence` value | 16,200 seconds; not a Phase-1 liveness guard |
| External-process shutdown | 600 seconds |
| Persisted-model capture | 7,200 seconds |
| Result resends | 3 |
| FedAvg workflow | no total task timeout |

The client calls `flare.init()` before heavyweight model loading. Readiness and stall clocks are separate. The
7,200-second readiness clock is absolute from target submission; log activity before both ready events does not
extend it. Once both clients are ready, the 1,800-second inactivity clock resets only on recorded training,
transfer, aggregation, or persistence progress—there is no event for every optimizer step. The 10,800-second client
envelope deliberately exceeds the readiness allowance; the parent client-job pipe can already be waiting while the
initialized subprocess continues model loading. The checked-in exported-job preflight rejects missing large-model
timeout settings, late FLARE initialization, a short launcher shutdown, unbounded resends, missing datasets, or
relaxed two-client startup.

Lower-level framework boundaries remain active. The small already-deployed client job has a 20-second START_JOB
RPC. F3 defaults to a 60-second no-ACK-progress guard, a 300-second flow-control ACK wait, and a 300-second receiver
read timeout; its socket driver also has a 30-second frame-send timeout, although this provisioned TLS topology uses
gRPC. The reviewed wrapper explicitly exports all four settings as 10,800 seconds. Provisioning also writes those
values into the server and both client `comm_config.json` files, where they take precedence over environment
fallbacks, then records and rereads that evidence. Qualification fails before service startup if any environment
value is missing, non-finite, or different; final readiness also rejects missing or mismatched provisioned-config
evidence. ACK-progress and receiver read are inactivity guards. ACK wait is an absolute limit while the
flow-control window remains blocked, even if partial ACK progress occurs; the optional socket send guard is an
absolute per-frame deadline. Pinning both absolute guards to 10,800 seconds keeps those lower boundaries outside the
expected same-node transfer. Normal 1 MiB chunks continuously advance ACK progress. CoreCell uses 3,600 seconds only
as its default when a caller supplies no request timeout; explicit
10,800-second operation waits are not clamped to 3,600 seconds. The CPU control-plane gate exercises START_JOB twice
with both required clients under this exact transport configuration. The largest selected tensor is 484,442,112
bytes, below the approximately 2 GiB message ceiling, and F3 fragments its serialized bytes into lower-level
frames.

The four-hour Slurm wall time is the one unavoidable whole-run cutoff. The internal readiness, inactivity, and
persistence envelopes are intentionally not summed into a larger promise: they diagnose different phases and may
overlap. The wrapper asks Slurm to send `SIGTERM` to its job steps five minutes before the limit; under
[Slurm's documented `--signal` semantics](https://slurm.schedmd.com/sbatch.html), delivery may be up to 60 seconds
early and the batch shell itself is not signaled without `B:`. The `srun` step ends at that point and the batch
wrapper then fails closed, while the allocation itself has its hard end at four hours. The exact-model capacity
gate plus same-node topology are the evidence that the expected healthy path fits this outer limit. Do not weaken
or skip that gate, and do not describe the run as cutoff-free.

## 1. Install the reviewed source bundle

Transfer the bundle through a Data Copier. From the Mac:

```bash
export BUNDLE=/Users/kevlu/Documents/codex/nvflare-72b-ready-v11.bundle

rsync -avP \
  "$BUNDLE" "$BUNDLE.sha256" \
  kevlu@cs-oci-ord-dc-02.nvidia.com:/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b/incoming/
```

The macOS system `rsync` supports `-avP`; do not use unsupported `--append-verify` or `--info=progress2`.

On a Data Copier or login node:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export BUNDLE="$PROJECT_ROOT/incoming/nvflare-72b-ready-v11.bundle"

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
  = "2026-07-30-trainable-72b-v11"
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

# Verify the existing 25 GiB image once, then create a cheap freshness
# attestation used by every later gate.
sha256sum --check "$CONTAINER_IMAGE.sha256"
sha256sum "$CONTAINER_IMAGE.sha256" \
  > "$CONTAINER_IMAGE.sha256.verified"

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
    -type f ! -name MANIFEST.sha256 \
    ! -name MANIFEST.sha256.verified -print0 |
    LC_ALL=C sort -z |
    xargs -0 sha256sum > MANIFEST.sha256
)

# This is intentionally done on the Data Copier, never a login/GPU node.
# For the already-staged snapshot it is the one full integrity reread.
(
  cd "$MODEL_PATH"
  sha256sum --check MANIFEST.sha256
  sha256sum MANIFEST.sha256 > MANIFEST.sha256.verified
  sha256sum --check MANIFEST.sha256.verified
)

test -s "$MODEL_PATH/model.safetensors.index.json"
test -s "$MODEL_PATH/MANIFEST.sha256"
test -s "$MODEL_PATH/MANIFEST.sha256.verified"
du -sh "$MODEL_PATH"
echo "72B staging PASS: revision=$MODEL_REVISION shards=$SHARD_COUNT"
exit
```

Expect approximately 145 GB of model weights and 37 safetensor shards. Manifest creation reads the snapshot once
and verification reads it once more on the Data Copier. Do not repeat the full checksum before every compute job.
The preflights verify the small marker hash and reject any manifest-listed file whose modification time is newer
than that marker.

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
cat "$CONTROL_ARTIFACT/environment.json"
cat "$CONTROL_ARTIFACT/services/transport-config.json"
cat "$CONTROL_ARTIFACT/control-plane.json"
cat "$CONTROL_ARTIFACT/control-plane-job-1/summary.json"
cat "$CONTROL_ARTIFACT/control-plane-job-2/summary.json"
cat "$CONTROL_ARTIFACT/qualification.json"
```

Require `COMPLETED 0:0`, two connected sites, two jobs with `aggregated_results: 2`, and `PASS` everywhere. In
`environment.json`, require all four `NVFLARE_STREAMING_*` values to equal `10800`. In
`services/transport-config.json`, require exactly `localhost`, `site-1`, and `site-2`, each with all four
`streaming_*` settings equal to `10800`.

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

Require `COMPLETED 0:0`, `PASS` in every JSON record, all 37 shard headers/key maps structurally validated,
indexed tensor bytes `145412407296`, 12 trainable tensors, payload `1755369472`, ceiling `2147483648`, two clients,
four ranks per client, one target round, two local steps, early FLARE initialization, strict startup, launcher
shutdown `600`, parent and subprocess tensor-download request timeout `10800`, and operation timeout `10800`.

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
finite loss and positive selected-parameter change, and every rank reports at least 16,384 MiB of PyTorch
`reserved_headroom_bytes`. Also require maximum model readiness no greater than 2,400 seconds, post-readiness work
no greater than 1,200 seconds, and nonnegative `projected_full_job_host_headroom_bytes` after the two-client
projection has already included the fixed 128 GiB reserve.

## 6. Run the login-node readiness validator

Do not submit the final allocation from manual visual inspection alone. The read-only validator requires the
control, CPU, and four-GPU artifacts to be `PASS`, requires all three manifests to record the exact current Git
commit, recomputes the capacity arithmetic, rejects `NCCL_P2P_DISABLE`, and rejects modified model/container files,
a dirty tree, or any wrong release/configuration value. Other manual overrides listed below are removed, and the
final wrapper supplies fixed reviewed values rather than accepting replacements.

The validator intentionally supports the cluster login node's Python 3.8 interpreter and remains
standard-library-only. Do not add Python 3.9-or-newer syntax or runtime APIs without changing and validating the
documented execution environment.

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
cd "$REPO_ROOT"

: "${CONTROL_JOB_ID:?set CONTROL_JOB_ID to the passing control-plane Slurm job}"
: "${PREFLIGHT_JOB_ID:?set PREFLIGHT_JOB_ID to the passing CPU 72B preflight}"
: "${GPU_PREFLIGHT_JOB_ID:?set GPU_PREFLIGHT_JOB_ID to the passing four-GPU gate}"

unset NCCL_P2P_DISABLE MODEL_PATH TARGET_MODEL_PATH GATE_MODEL_PATH
unset TARGET_READY_TIMEOUT TARGET_STALL_TIMEOUT GATE_READY_TIMEOUT GATE_STALL_TIMEOUT
unset SERVICE_STARTUP_TIMEOUT QUALIFICATION_PROFILE

READINESS_ARTIFACT="$PROJECT_ROOT/artifacts/72b-login-readiness.json"
python3 \
  research/llm_fl_stress/real_training/cs_oci_ord/validate_72b_readiness.py \
  --project-root "$PROJECT_ROOT" \
  --control-job-id "$CONTROL_JOB_ID" \
  --cpu-job-id "$PREFLIGHT_JOB_ID" \
  --gpu-job-id "$GPU_PREFLIGHT_JOB_ID" \
  | tee "$READINESS_ARTIFACT"

grep -q '"safe_to_submit": true' "$READINESS_ARTIFACT"
grep -q '"status": "PASS"' "$READINESS_ARTIFACT"
```

If this returns nonzero, stop. Do not weaken the validator to make an old artifact pass; rerun only the specific
cheap gate whose exact-commit evidence is missing.

## 7. Submit one eight-GPU two-client 72B qualification

Only run this immediately after the readiness validator passes:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
cd "$REPO_ROOT"
unset NCCL_P2P_DISABLE MODEL_PATH TARGET_MODEL_PATH GATE_MODEL_PATH
unset TARGET_READY_TIMEOUT TARGET_STALL_TIMEOUT GATE_READY_TIMEOUT GATE_STALL_TIMEOUT
unset SERVICE_STARTUP_TIMEOUT QUALIFICATION_PROFILE

# Repeat the cheap read-only validation and make submission conditional on that
# exact invocation, leaving no unchecked edit or environment change in between.
READINESS_ARTIFACT="$PROJECT_ROOT/artifacts/72b-login-readiness.json"
unset JOB_ID
python3 \
  research/llm_fl_stress/real_training/cs_oci_ord/validate_72b_readiness.py \
  --project-root "$PROJECT_ROOT" \
  --control-job-id "$CONTROL_JOB_ID" \
  --cpu-job-id "$PREFLIGHT_JOB_ID" \
  --gpu-job-id "$GPU_PREFLIGHT_JOB_ID" \
  > "$READINESS_ARTIFACT" &&
grep -q '"safe_to_submit": true' "$READINESS_ARTIFACT" &&
JOB_ID=$(sbatch --parsable \
  --export=ALL,CONTROL_JOB_ID="$CONTROL_JOB_ID",PREFLIGHT_JOB_ID="$PREFLIGHT_JOB_ID",GPU_PREFLIGHT_JOB_ID="$GPU_PREFLIGHT_JOB_ID" \
  research/llm_fl_stress/real_training/cs_oci_ord/two_client_72b_trainable.slurm)

cat "$READINESS_ARTIFACT"
if [[ -z "${JOB_ID:-}" ]]; then
  echo "Readiness failed; no 72B job was submitted." >&2
else
  echo "JOB_ID=$JOB_ID"
  GPU_LOG="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-72b-trainable-$JOB_ID.out"
  GPU_ERR="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-72b-trainable-$JOB_ID.err"
  echo "GPU_LOG=$GPU_LOG"
  echo "GPU_ERR=$GPU_ERR"
  tail -F "$GPU_LOG"
fi
```

Expected sequence:

1. the same exact-commit readiness check passes again inside the allocation before training starts;
2. exactly eight A100s pass the environment check;
3. the exact dependency set and at least 50 GiB/100,000 inodes of local scratch pass;
4. both production TLS clients connect;
5. the two-round 1.5B exact-topology gate completes with 2/2 aggregation and persistence;
6. both 72B clients report ready;
7. both sites report one passing 72B round with two optimizer steps;
8. the server reports `Aggregated 2/2 results`;
9. persistence completes and reloads; and
10. the qualification summary reports `PASS`.

Do not cancel a healthy job merely because 72B startup is quiet. The target readiness allowance is two hours and
the post-ready no-progress allowance is 30 minutes. Inspect emitted progress and the separate ready-site list.

## 8. Accept the claim

After completion:

```bash
sacct -j "$JOB_ID" \
  --format=JobID,JobName%40,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

ARTIFACT="$PROJECT_ROOT/artifacts/$JOB_ID"
cat "$ARTIFACT/manifest.txt"
cat "$ARTIFACT/qualification.json"
cat "$ARTIFACT/environment.json"
cat "$ARTIFACT/services/transport-config.json"
cat "$ARTIFACT/gpu-monitor.json"
cat "$ARTIFACT/scratch-capacity.json"
cat "$ARTIFACT/allocation-start-readiness.json"
cat "$ARTIFACT/dependency-check.json"
cat "$ARTIFACT/target-identity.json"
cat "$ARTIFACT/target-72b/summary.json"
cat "$ARTIFACT/target-72b/trainable-state-evidence.json"
```

Accept only if all of the following hold:

- Slurm is `COMPLETED` with exit code `0:0`;
- the manifest records `status=0`, `qualification_profile=trainable-72b`, and the reviewed Git commit;
- the allocation-start readiness artifact records `safe_to_submit: true` for that same commit and gate IDs;
- the final environment and provisioned-config artifacts repeat the four exact `10800` transport settings for the
  server and both clients;
- both the 1.5B gate and 72B target are `PASS`;
- the target has exactly two client round records and 2/2 aggregation;
- both sites used distinct fixed data and reported finite losses and positive optimizer changes;
- every trainable transfer is 12 tensors and exactly `1,755,369,472` bytes;
- the persisted checkpoint reloads and matches the sampled equal-weight mean of the two client outputs;
- all GPU indices 0–7 have positive monitored memory and utilization; and
- retained server and participant logs contain no fatal error marker.

This is the point at which it is accurate to say that real two-client last-layer federated training succeeded on
Qwen2.5-72B. A failed gate is diagnostic evidence, not permission to submit an automatic rerun.
