# CS-OCI-ORD two-client 14B production qualification

This runbook replaces the failed two-client SimEnv attempt (`30918938`). That job put both logical clients into
one simulator worker thread. Site-1 occupied the thread while loading and training Qwen2.5-14B; site-2's job runner
could not synchronize with the server runner within its fixed 60-second window. NVFLARE then waited for a two-client
quorum until Slurm stopped the allocation. The failure was a control-plane topology error, not evidence that the
model, FSDP2 bridge, A100s, NCCL, or second four-GPU group was defective.

Neither `SimEnv` nor `PocEnv` is used by the replacement. `PocEnv` has not been recently qualified as a supported
deployment dependency for this work. The replacement reuses the production mechanism already exercised by the LLM
stress harness:

- centralized TLS startup-kit provisioning;
- a real server service started with `startup/sub_start.sh --once`;
- two independent real client services started the same way;
- admin-API registration checks; and
- recipe submission through `ProdEnv`.

## Prepared state on July 27

The production path has been checked without consuming another cluster GPU allocation:

- the complete stress-harness suite passes locally;
- shell syntax, Python compilation, formatting, and lint checks pass;
- a live local TLS/`ProdEnv` smoke provisioned a server and two independent clients;
- both clients registered and completed two consecutive submitted NumPy jobs through the same services;
- the server aggregated 2/2 results twice and both jobs reached `FINISHED:COMPLETED`;
- ephemeral startup kits and keys were deleted; and
- retained logs passed the transient-token redaction check.

This is control-plane qualification, not a substitute for tomorrow's exact 8-GPU gate. The remaining no-GPU action
after installing the final bundle is the cluster CPU preflight described below. No new 14B GPU claim should be made
until the exact gate and target phases pass on CS-OCI-ORD.

## Fixed topology

All services remain inside one Slurm allocation and one Pyxis/Enroot container:

```text
localhost TLS NVFLARE server: CUDA_VISIBLE_DEVICES=""
├── site-1 service: CUDA_VISIBLE_DEVICES=0,1,2,3
│   └── torchrun: four FSDP2 ranks
└── site-2 service: CUDA_VISIBLE_DEVICES=4,5,6,7
    └── torchrun: four FSDP2 ranks
```

The server and both clients are separate operating-system processes with separate workspaces. Both client services
must register through the admin API before any federated job is submitted. This preserves real production runner
and service boundaries without asking Slurm for two nodes.

## Resource and failure controls

The GPU wrapper requests one node, eight A100 80 GB GPUs, 64 CPUs, 512 GB RAM, and 25 minutes. It runs two phases
sequentially inside that one allocation:

1. an exact-topology Qwen2.5-1.5B training gate; and
2. Qwen2.5-14B training only if the gate passes completely.

The gate is not a synthetic test. It runs two real four-rank FSDP2 clients, transfers two full model states,
aggregates 2/2 results, and persists the global model. Its smaller model makes a topology or synchronization failure
cheap to detect before loading 14B.

The launcher fails closed:

- the checkout must be the clean `codex/llm-fl-real-14b` branch and contain the qualified production base;
- both exact client names must register within 90 seconds;
- both gate clients must report ready within 120 seconds and the gate must finish within 300 seconds;
- the 14B clients must report ready within 300 seconds and normally finish within 720 seconds;
- a bounded 120-second completion grace is available only after verified 2/2 aggregation or persistence progress;
- known runner-synchronization and distributed-training errors cause an immediate abort;
- every phase must end as `FINISHED:COMPLETED`;
- both client round records, four ranks per client, 2/2 aggregation, and server persistence are required;
- the 14B phase is never submitted after a gate failure; and
- a Slurm signal two minutes before the 25-minute limit triggers cleanup.

No full 3 GB or 30 GB result is copied back to Lustre while GPUs sit idle. The persisted model is validated in the
node-local server workspace; its path, size, small metadata sidecar, client/server logs, phase summary, and
five-second per-GPU utilization samples are retained. The monitor requires every GPU index 0 through 7 to have at
least one sample with positive utilization and positive memory use, and retains per-GPU peaks. Ephemeral startup
kits, TLS private keys, and full model files stay under node-local private scratch and are deleted during cleanup.

The observed July 28 full-state run lasted 16:07 and completed persistence just after its old 720-second target
deadline. Details are in the
[July 28 qualification record](cs-oci-ord-two-client-14b-qualification-2026-07-28.md). The 25-minute Slurm limit is
a hard ceiling, not a target.

## Trainable-state multiround follow-up

The next qualification deliberately keeps the same Qwen2.5-14B model and proven eight-GPU production topology. It
changes the experiment, not the model size:

- the immutable full BF16 model is loaded locally by both clients;
- only the final decoder layer is trainable and crosses the federated boundary;
- the 1.5B gate runs two FL rounds with four optimizer steps per rank per round;
- the 14B target runs three FL rounds with four optimizer steps per rank per round;
- site-1 and site-2 receive separate fixed 48-record JSONL partitions;
- four ranks consume 16 unique records per client per round, so the 14B phase consumes all 48 records at each site
  exactly once; and
- the server aggregates the two selected-layer states with explicit equal client weights.

The selected Qwen2.5-14B decoder layer is expected to be approximately 551 MB in BF16, compared with the measured
29.54 GB full-state payload. The implementation enforces a 1 GiB payload ceiling: a regression to full-model
exchange fails qualification. Moving the selected layer is part of the experiment and should be fast on this node;
the retained evidence records load time, export time, payload bytes, and derived logical wire bytes so this
assumption is measured rather than hidden.

This profile answers correctness questions that a one-round completion cannot:

1. each client log records its pinned dataset checksum and the exact unique record IDs used per round;
2. a per-step global loss trajectory proves four real forward/backward/optimizer steps were executed;
3. exact SHA-256 summaries prove both clients started each round from the same global selected-layer state;
4. distinct output hashes prove the different client partitions produced different local updates;
5. deterministic tensor samples prove each persisted global value is the equal-weight mean of the two client
   outputs;
6. persisted round `r` must exactly match both clients' input hash in round `r+1`; and
7. every persisted checkpoint, including the final checkpoint, is reloaded and schema-checked before the ephemeral
   workspace is removed.

The run is still a systems qualification, not a convergence or model-quality benchmark. Three short rounds over
fixed qualification text are sufficient to establish FL state flow and real gradient work without spending an
allocation on an unbounded training experiment. A larger model would add memory and transfer risk but would not
answer these state-correctness questions more directly.

## Install the final transfer bundle

Create the final bundle locally from the reviewed worktree and transfer it through a Data Copier node. The
trainable multiround artifact is named `nvflare-trainable-14b-ready.bundle`; its adjacent checksum uses only the
basename so it can be verified after transfer:

```bash
export BUNDLE=/Users/kevlu/Documents/codex/nvflare-trainable-14b-ready.bundle
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b

rsync -ah --partial --progress \
  "$BUNDLE" "$BUNDLE.sha256" \
  kevlu@cs-oci-ord-dc-02.nvidia.com:"$PROJECT_ROOT/incoming/"
```

On the cluster, verify the checksum and derive the intended branch head from the bundle itself:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
cd "$PROJECT_ROOT/incoming"

sha256sum -c nvflare-trainable-14b-ready.bundle.sha256
git -C "$REPO_ROOT" bundle verify "$PROJECT_ROOT/incoming/nvflare-trainable-14b-ready.bundle"
BUNDLE_HEAD=$(git bundle list-heads nvflare-trainable-14b-ready.bundle |
  awk '$2 == "refs/heads/codex/llm-fl-real-14b" {print $1}')
test -n "$BUNDLE_HEAD"

git -C "$REPO_ROOT" fetch \
  "$PROJECT_ROOT/incoming/nvflare-trainable-14b-ready.bundle" \
  refs/heads/codex/llm-fl-real-14b
git -C "$REPO_ROOT" switch codex/llm-fl-real-14b
git -C "$REPO_ROOT" merge --ff-only FETCH_HEAD
test "$(git -C "$REPO_ROOT" rev-parse HEAD)" = "$BUNDLE_HEAD"
test -z "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)"
```

The last test is intentional. Both Slurm wrappers also refuse a dirty tree, the wrong branch, a checkout missing the
production qualification base, or a checkout missing the current qualification release marker. If the old
accidental `?? awk` entry is still present, inspect it and move it outside the repository; do not use `git clean`:

```bash
git -C "$REPO_ROOT" status --short
if [[ -f "$REPO_ROOT/awk" ]]; then
  sed -n '1,20p' "$REPO_ROOT/awk"
  mv "$REPO_ROOT/awk" "$PROJECT_ROOT/incoming/awk.accidental-preflight"
fi
test -z "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)"
```

## Prerequisites

The existing cluster setup remains authoritative:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export GATE_MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-1.5B-8faed761d45a"
export TARGET_MODEL_PATH="$PROJECT_ROOT/models/Qwen2.5-14B-97e1e76335b7"
export TARGET_MODEL_REVISION=97e1e76335b7017d8f67c08a19d103c0504298c9

test -s "$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
test -s "$PROJECT_ROOT/envs/nvflare-fsdp2/requirements.lock"
test -s "$GATE_MODEL_PATH/REVISION"
test "$(cat "$TARGET_MODEL_PATH/REVISION")" = "$TARGET_MODEL_REVISION"
git -C "$REPO_ROOT" status --short --branch
git -C "$REPO_ROOT" rev-parse HEAD
```

Do not proceed from a dirty cluster checkout or a head other than `BUNDLE_HEAD`. Do not rerun the 30 GB checksum
unless the immutable snapshot may have changed.

## CPU-only control-plane qualification

Run this once after updating the branch. It requests no GPU and exercises the exact TLS provision/start/register
path inside the qualified container. It submits two consecutive tiny two-client NumPy jobs through `ProdEnv`,
requires both client runners to synchronize for each job, aggregates 2/2 results twice, and reaches
`FINISHED:COMPLETED` twice. Before starting those services, it runs the trainable-only state bridge on two real
PyTorch 2.12 CPU ranks, instantiates the sparse 1.5B server state container on CPU, enforces its 1 GiB payload
ceiling, exports the trainable-state recipe, and requires exactly one site-1 partition in the site-1 app, exactly
one site-2 partition in the site-2 app, and the matching dataset arguments in the generated configurations.
Reusing the same long-lived services for the second job mirrors the GPU gate-to-target transition:

```bash
cd "$REPO_ROOT"
CONTROL_JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/control_plane_preflight.slurm)
echo "$CONTROL_JOB_ID"
```

After it finishes, inspect once:

```bash
sacct -j "$CONTROL_JOB_ID" --format=JobID,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X
cat "$PROJECT_ROOT/artifacts/control-plane-$CONTROL_JOB_ID/control-plane.json"
cat "$PROJECT_ROOT/artifacts/control-plane-$CONTROL_JOB_ID/control-plane-job-1/summary.json"
cat "$PROJECT_ROOT/artifacts/control-plane-$CONTROL_JOB_ID/control-plane-job-2/summary.json"
cat "$PROJECT_ROOT/artifacts/control-plane-$CONTROL_JOB_ID/qualification.json"
cat "$PROJECT_ROOT/artifacts/control-plane-$CONTROL_JOB_ID/fsdp2-trainable-cpu-gate.json"
cat "$PROJECT_ROOT/artifacts/control-plane-$CONTROL_JOB_ID/trainable-server-preflight.json"
cat "$PROJECT_ROOT/artifacts/control-plane-$CONTROL_JOB_ID/trainable-export-validation.json"
```

All seven JSON files must report `status: PASS`; `connected_clients` and both completed jobs' `sites` must be exactly
`site-1` and `site-2`, and each job summary must report `aggregated_results: 2`. Do not submit the GPU job if this
check fails. The CPU FSDP2 gate must report two ranks on the pinned torch version. The sparse-server preflight must
report a positive payload below 1 GiB. The export validation must additionally report `state_scope: trainable`,
`job_exported: true`, two clients, two rounds, and four local steps. The July 28 services-only preflight took 4:51;
the hard limit is ten minutes with the added CPU checks.

## Submit one qualified GPU allocation

No custom exports are normally needed because the wrapper pins both model paths and the 14B revision:

```bash
cd "$REPO_ROOT"
JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/two_client_14b_trainable.slurm)
echo "$JOB_ID"
```

`two_client_14b_trainable.slurm` selects the `trainable-multiround` profile and then delegates to the same reviewed
production wrapper used by the completed full-state qualification. The older `two_client_14b.slurm` remains the
full-state regression entry point and is not the command for this follow-up.

Do not submit a second copy, add `--exclusive`, set `NCCL_P2P_DISABLE`, use `sbatch -W`, or run `watch squeue`.
Pending time consumes no GPUs. Once it starts, the wrapper uses all eight GPUs for each training phase.

## Observe without scheduler polling

The Slurm output emits `real_training_production_progress` every five seconds. Follow the existing log directly;
this does not send repeated RPCs to the Slurm controller:

```bash
tail -F "$PROJECT_ROOT/logs/"*"$JOB_ID".out
```

Expected milestones are:

1. `real_training_production_environment` with eight A100s;
2. `real_training_production_control_plane` with both clients;
3. a submitted gate job;
4. gate progress with both `ready_sites`;
5. two gate round records, two reloaded gate checkpoints, and a gate summary with `status: PASS`;
6. a submitted 14B job;
7. target progress with both `ready_sites`; and
8. three target round records, three reloaded target checkpoints, a
   `real_training_trainable_state_evidence` record, and a qualification `status: PASS`.

An emitted `real_training_production_abort` or `real_training_production_phase_failure` is a terminal diagnostic,
not a prompt to resubmit.

`PotentialSecretWarning` may identify the pinned 40-character Hugging Face revision or the two public dataset
SHA-256 values as high-entropy text. That warning is non-blocking for these public integrity identifiers, but it
does not make actual credentials acceptable in recipe arguments. No token, password, or private key should appear
in the generated job configuration.

The first phase is intentionally small, so persistent underutilization or a missing client is detected before 14B.
During model load and full-state serialization, utilization can temporarily be low or uneven; judge the run from the
five-second samples and phase milestones, not one instantaneous `nvidia-smi`.

## Final acceptance

After the job ends, issue one accounting query:

```bash
sacct -j "$JOB_ID" \
  --format=JobID,JobName%36,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

cat "$PROJECT_ROOT/artifacts/$JOB_ID/manifest.txt"
cat "$PROJECT_ROOT/artifacts/$JOB_ID/configuration.json"
cat "$PROJECT_ROOT/artifacts/$JOB_ID/qualification.json"
cat "$PROJECT_ROOT/artifacts/$JOB_ID/gpu-monitor.json"
cat "$PROJECT_ROOT/artifacts/$JOB_ID/gate-1.5b/summary.json"
cat "$PROJECT_ROOT/artifacts/$JOB_ID/target-14b/summary.json"
cat "$PROJECT_ROOT/artifacts/$JOB_ID/target-14b/persistence/"persisted_model-*.json
ls -lh "$PROJECT_ROOT/artifacts/$JOB_ID"
```

Accept only if Slurm reports `COMPLETED` with `0:0`, the manifest reports `execution_environment=ProdEnv`, the GPU
monitor reports `PASS` with observed indices 0–7, and all three summaries report `PASS`. Each phase summary must
contain:

- both `site-1` and `site-2`;
- exactly four rank records per site on A100-SXM4-80GB;
- finite positive loss and positive selected-parameter change for each site;
- identical positive payload bytes and tensor counts across clients;
- `aggregated_results: 2`;
- `persisted: true`; and
- a non-empty persisted-model size.

For the trainable multiround profile, also require:

- `qualification_profile=trainable-multiround` in `manifest.txt`;
- `state_scope: trainable`;
- `num_rounds: 2` for the gate and `num_rounds: 3` for the target;
- `local_steps: 4`;
- distinct pinned dataset checksums and 32/48 unique records per site in gate/target;
- a selected-state payload no greater than 1 GiB;
- two/three successfully reloaded persisted checkpoints in gate/target;
- client-output divergence on every round;
- exact persisted-to-next-round hash continuity; and
- sampled equal-weight FedAvg checks on every persisted round.

If any gate fails, do not resubmit automatically. Preserve the job ID and inspect
`qualification-error.log`, `services/`, and the phase log directories. A submitted phase also retains
`submitted.json`; a failed phase retains `failure.json` and best-effort `failure-logs/`. Change only a diagnosed
cause before another allocation.

## Tomorrow's go/no-go checklist

Proceed to one GPU submission only when every item is true:

1. the transferred bundle checksum and `git bundle verify` pass;
2. the cluster checkout equals `BUNDLE_HEAD`, is on `codex/llm-fl-real-14b`, and is clean;
3. the staged 1.5B and 14B revision files match the intended immutable snapshots;
4. the CPU preflight is `COMPLETED 0:0` and the registration plus both sequential job records pass;
5. no second copy of the GPU job is queued or running; and
6. the output log path is ready to tail without `squeue` polling.

If the GPU job needs to be stopped, issue one `scancel "$JOB_ID"` and let the signal/cleanup path run. Do not launch a
replacement until the retained failure evidence identifies a concrete cause.

## Deliberate safety interlock

`real_training.slurm` and `job.py` still support the previously qualified one-client SimEnv workflow. Both now reject
multi-client execution through that surface. The only checked-in two-client 14B entry point is
`two_client_14b.slurm`, which uses provisioned production services and `ProdEnv`.
