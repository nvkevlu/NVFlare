# Five-round 14B post-run continuity analysis

Run this only after the `full-model-14b-multiround` Slurm job completes successfully. It is a CPU-only analysis of
retained JSON evidence and logs; it does not request a GPU, contact Slurm, load Qwen2.5-14B, or load the persisted
29.54 GB checkpoints.

Run it on a Data Copier inside the pinned Enroot image. Do not activate the Lustre virtual environment directly on
the host: its Python/glibc requirements are guaranteed only inside this container.

On the Data Copier host:

```bash
export PROJECT_ROOT=/lustre/fs11/portfolios/coreai/projects/coreai_edgeai_flresearch/users/kevlu/nvflare-14b
export REPO_ROOT="$PROJECT_ROOT/repos/NVFlare"
export CONTAINER_IMAGE="$PROJECT_ROOT/containers/pytorch-25.01-py3.sqsh"
export JOB_ID=<completed-job-id>

enroot start --mount "$PROJECT_ROOT:$PROJECT_ROOT" "$CONTAINER_IMAGE"
```

Inside the container:

```bash
set -Eeuo pipefail
source "$PROJECT_ROOT/envs/nvflare-fsdp2/bin/activate"
ARTIFACT="$PROJECT_ROOT/artifacts/$JOB_ID"

cd "$REPO_ROOT"
python research/llm_fl_stress/real_training/multiround_post_run_analysis.py \
  --artifact-root "$ARTIFACT" \
  --output "$ARTIFACT/multiround-post-run-analysis.json"

cat "$ARTIFACT/multiround-post-run-analysis.json"
```

Accept the result only when `status` is `PASS`. The analyzer requires exactly five unique round records from each site,
40 unique sample IDs per site, stable unique bounded state coordinates, identical client inputs each round, all four
round-to-round transitions matching equal-weight BF16 FedAvg, and exactly five aggregation plus five persistence
start/end markers. The default continuity tolerance is stated in the result: `0` absolute, `1e-6` relative, plus
`0.5` BF16 ULP.

The persistence result is intentionally labeled `SIZE_ONLY`. The running qualification retains five checkpoint metadata
records but not the full checkpoint tensors, so this post-run pass can prove only that five files met the 29,540,067,328
byte floor at persistence time. It does not claim checkpoint-content equality or reloadability. Likewise, client-output
divergence is reported only when it is visible at retained bounded coordinates; a non-observation is not treated as proof
that the complete client outputs were identical.
