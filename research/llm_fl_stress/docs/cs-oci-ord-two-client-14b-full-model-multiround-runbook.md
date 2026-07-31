# CS-OCI-ORD five-round Qwen2.5-14B full-model federation

This is the next result-producing experiment after the passing one-round 14B full-model qualification. It runs one
provisioned-TLS NVFLARE server and two real clients on one eight-A100 node. Each client uses four FSDP2 ranks, trains
all 14,770,033,664 parameters for two optimizer steps per round, and exchanges the exact 579-tensor, 29,540,067,328-byte
full state for five rounds.

There is no 1.5B training gate and no separate control-plane, CPU-preflight, or GPU-preflight Slurm allocation. The
profile records the gate as `SKIPPED`. Five rounds focus this run on repeated receive, train, export, aggregate, and
persist behavior; two steps also reduce BF16 no-change risk while using 40 of the 48 unique records per site. Expected
runtime is approximately 35–55 minutes. The two-hour Slurm allocation is the only whole-run deadline; target ready/stall and
transport guards are at least as long as that wall.

## Update the reviewed checkout

After transferring `nvflare-14b-5round.bundle`, its checksum, and its `.head` file to `incoming`:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export BUNDLE="$PROJECT_ROOT/incoming/nvflare-14b-5round.bundle"

sha256sum --check "$BUNDLE.sha256"
git -C "$REPO_ROOT" bundle verify "$BUNDLE"
git -C "$REPO_ROOT" fetch "$BUNDLE" refs/heads/codex/llm-fl-real-14b
git -C "$REPO_ROOT" merge --ff-only FETCH_HEAD

export EXPECTED_HEAD="$(cat "$BUNDLE.head")"
test "$(git -C "$REPO_ROOT" rev-parse HEAD)" = "$EXPECTED_HEAD"
test -z "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all)"
```

## Submit exactly one GPU job

From the login node, in the same shell:

```bash
cd "$REPO_ROOT"
unset NCCL_P2P_DISABLE

JOB_ID=$(sbatch --parsable \
  --export=ALL,EXPECTED_HEAD="$EXPECTED_HEAD" \
  research/llm_fl_stress/real_training/cs_oci_ord/two_client_14b_full_model_multiround.slurm)
echo "JOB_ID=$JOB_ID"

GPU_LOG="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-14b-5round-$JOB_ID.out"
GPU_ERR="$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-14b-5round-$JOB_ID.err"
tail --retry -F "$GPU_LOG"
```

`Ctrl-C` stops only `tail`. Do not repeatedly poll `squeue`; a pending job is not consuming GPUs. The wrapper refuses a
different checkout, a dirty tree, fewer than eight GPUs, less than 512 GiB, insufficient remaining wall time, or an
inherited `NCCL_P2P_DISABLE` before model loading.

## Inspect the result

```bash
sacct -j "$JOB_ID" \
  --format=JobID,JobName%44,State,Elapsed,ExitCode,AllocTRES,MaxRSS -X

ARTIFACT="$PROJECT_ROOT/artifacts/$JOB_ID"
cat "$ARTIFACT/manifest.txt"
cat "$ARTIFACT/qualification.json"
cat "$ARTIFACT/target-14b-full-model-multiround/summary.json"
cat "$ARTIFACT/gpu-monitor.json"
cat "$ARTIFACT/allocation-monitor.json"
```

Accept only if Slurm is `COMPLETED 0:0`, the manifest is `status=0`, qualification and target summary are `PASS`, gate
status is `SKIPPED`, target evidence reports five rounds from both sites, the server aggregated both results five times,
five persisted checkpoints were observed, all eight GPUs were active, and the allocation monitor reports no OOM event.
Do not automatically retry a failure; inspect the retained phase failure and collected logs first.
