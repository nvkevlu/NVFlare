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

- both exact client names must register within 90 seconds;
- both gate clients must report ready within 120 seconds and the gate must finish within 300 seconds;
- the 14B clients must report ready within 300 seconds and the phase must finish within 720 seconds;
- known runner-synchronization and distributed-training errors cause an immediate abort;
- every phase must end as `FINISHED:COMPLETED`;
- both client round records, four ranks per client, 2/2 aggregation, and server persistence are required;
- the 14B phase is never submitted after a gate failure; and
- a Slurm signal two minutes before the 25-minute limit triggers cleanup.

No full 3 GB or 30 GB result is copied back to Lustre while GPUs sit idle. The persisted model is validated in the
node-local server workspace; its path, size, small metadata sidecar, client/server logs, phase summary, and five-second
per-GPU utilization samples are retained. Ephemeral startup kits, TLS private keys, and full model files stay under
node-local private scratch and are deleted during cleanup.

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

Do not proceed from a dirty cluster checkout or an unexpected commit. Do not rerun the 30 GB checksum unless the
immutable snapshot may have changed.

## CPU-only control-plane qualification

Run this once after updating the branch. It requests no GPU and exercises the exact TLS provision/start/register
path inside the qualified container. It also submits a tiny two-client NumPy job through `ProdEnv`, requires both
client runners to synchronize, aggregates 2/2 results, and reaches `FINISHED:COMPLETED`:

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
cat "$PROJECT_ROOT/artifacts/control-plane-$CONTROL_JOB_ID/control-plane-job/summary.json"
cat "$PROJECT_ROOT/artifacts/control-plane-$CONTROL_JOB_ID/qualification.json"
```

All three JSON files must report `status: PASS`; `connected_clients` and the completed job's `sites` must be exactly
`site-1` and `site-2`, and the job summary must report `aggregated_results: 2`. Do not submit the GPU job if this
check fails.

## Submit one qualified GPU allocation

No custom exports are normally needed because the wrapper pins both model paths and the 14B revision:

```bash
cd "$REPO_ROOT"
JOB_ID=$(sbatch --parsable \
  research/llm_fl_stress/real_training/cs_oci_ord/two_client_14b.slurm)
echo "$JOB_ID"
```

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
5. a `real_training_federation` gate summary with `status: PASS`;
6. a submitted 14B job;
7. target progress with both `ready_sites`; and
8. a target summary followed by a qualification `status: PASS`.

The first phase is intentionally small, so persistent underutilization or a missing client is detected before 14B.
During model load and full-state serialization, utilization can temporarily be low or uneven; judge the run from the
five-second samples and phase milestones, not one instantaneous `nvidia-smi`.

## Final acceptance

After the job ends, issue one accounting query:

```bash
sacct -j "$JOB_ID" \
  --format=JobID,JobName%36,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

cat "$PROJECT_ROOT/artifacts/$JOB_ID/manifest.txt"
cat "$PROJECT_ROOT/artifacts/$JOB_ID/qualification.json"
cat "$PROJECT_ROOT/artifacts/$JOB_ID/gate-1.5b/summary.json"
cat "$PROJECT_ROOT/artifacts/$JOB_ID/target-14b/summary.json"
ls -lh "$PROJECT_ROOT/artifacts/$JOB_ID"
```

Accept only if Slurm reports `COMPLETED` with `0:0`, the manifest reports `execution_environment=ProdEnv`, and all
three summaries report `PASS`. Each phase summary must contain:

- both `site-1` and `site-2`;
- exactly four rank records per site on A100-SXM4-80GB;
- finite positive loss and positive selected-parameter change for each site;
- identical positive payload bytes and tensor counts across clients;
- `aggregated_results: 2`;
- `persisted: true`; and
- a non-empty persisted-model size.

If any gate fails, do not resubmit automatically. Preserve the job ID and inspect
`qualification-error.log`, `services/`, and the phase log directories. Change only a diagnosed cause before another
allocation.

## Deliberate safety interlock

`real_training.slurm` and `job.py` still support the previously qualified one-client SimEnv workflow. Both now reject
multi-client execution through that surface. The only checked-in two-client 14B entry point is
`two_client_14b.slurm`, which uses provisioned production services and `ProdEnv`.
