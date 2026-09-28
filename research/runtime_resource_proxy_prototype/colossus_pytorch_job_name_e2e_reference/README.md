# Historical Colossus job-name validation

This directory preserves live end-to-end evidence of an intermediate design
that stored `resource_summary.job_name`. It was captured on September 22, 2026 from
a real two-client PyTorch CIFAR-10 POC run on Colossus.

This capture predates the later review decisions to remove stored job-summary
timestamps, totals, and job name and to replace the public `f3` name. Its JSON and CLI files
remain unchanged as evidence of that run. The current closed schema rejects
the older shape; use the regenerated production reference for the current
contract.

## Run

- Job ID: `a624b97e-2eba-4b1c-bb44-765d83dd945b`
- Job name: `hello-pt`
- Study: `job-name-validation`
- Final status: `FINISHED:COMPLETED`
- Reported job duration: 32.9 seconds
- Participants: `site-1`, `site-2`, and `server`; all three reports accepted
- Workload: three-round PyTorch CIFAR-10 federated training with one local
  epoch per client per round
- Host GPU: NVIDIA L40G, 23,028 MiB, driver 580.178.04
- PyTorch: 2.14.0+cu130; CUDA runtime 13.0

The tested wheel was built directly from this dirty local design worktree at
base commit `bd847b741`. This is validation evidence, not a signed release
artifact or a product integrity mechanism.

## What this proves

The trusted root server obtained `hello-pt` from persisted job metadata. No
client report contains or supplies the name.

- The archived [`resource_summary.json`](artifacts/job-store/workspace) has
  both `job_id` and `job_name`.
- The job JSON response preserves both fields.
- The job human view begins with `Recorded resources for job hello-pt (ID:
  a624b97e-2eba-4b1c-bb44-765d83dd945b).`
- The study JSON repeats the name in its included job row.
- The study table has separate `JOB ID` and `NAME` columns.
- The name in the archive, the durable job metadata, and both CLI responses is
  exactly the same.

The same run also reconfirms the previously implemented measurements:

- Resource time: `reported`; 80.373874143 additive participant-seconds
- Retained run-directory files: `reported`; 761,986 additive bytes
- F3 remote accepted traffic: `reported`; 3,080,186 bytes in 14 messages

These are participant-report sums. All POC participants ran on the same host,
so the sums are not a claim of distinct physical capacity.

## Files

- [`resources-job.json`](artifacts/cli/resources-job.json) and
  [`resources-job.txt`](artifacts/cli/resources-job.txt): all-participant job
  views
- [`resources-site-1.json`](artifacts/cli/resources-site-1.json) and
  [`resources-site-1.txt`](artifacts/cli/resources-site-1.txt): one-site detail
  views
- [`resources-study.json`](artifacts/cli/resources-study.json) and
  [`resources-study.txt`](artifacts/cli/resources-study.txt): study rollup
- [`workspace`](artifacts/job-store/workspace): exact durable NVFlare workspace
  ZIP containing `resource_stats/resource_summary.json` and three participant
  summaries
- [`extracted-workspace/resource_stats`](artifacts/extracted-workspace/resource_stats):
  directly viewable copies of those exact four JSON members
- [`meta`](artifacts/job-store/meta): persisted server-owned job metadata
- [`job-wait.json`](artifacts/job-wait.json): terminal status and duration
- [`package-versions.json`](artifacts/package-versions.json) and
  [`nvidia-smi.csv`](artifacts/nvidia-smi.csv): runtime context
- [`test_reference.py`](test_reference.py): archive/extracted-file comparison,
  numeric reconciliation, metadata, and historical CLI checks

Run the reference test from the repository root:

```bash
python -m pytest -q \
  research/runtime_resource_proxy_prototype/colossus_pytorch_job_name_e2e_reference/test_reference.py
```
