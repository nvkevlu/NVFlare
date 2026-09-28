# Colossus PyTorch F3 end-to-end reference

This directory preserves a real end-to-end run of the production resource-statistics implementation at Git commit `c4372e10950ee77f6317e8e9bec0afcdd6b06290`.

Historical contract note: this capture predates the required pre-release v1
`job_name` field in server-created job and study summaries. Those summaries no
longer validate against or render with the current contract, while the
participant summaries and numeric/F3 reconciliation remain valid historical
evidence. For current-schema live output, see the
[job-name reference](../colossus_pytorch_job_name_e2e_reference/README.md).

The run proves that the implementation can:

1. discover the CUDA Runtime bundled privately with PyTorch before importing PyTorch;
2. initialize PyTorch and execute CUDA work after that probe;
3. run a real two-client CIFAR-10 federated job;
4. count origin-only F3 logical sends, including their DownloadService payloads;
5. finalize one participant report for the server and each client;
6. roll those reports up into the normal job `workspace` ZIP;
7. read that ZIP through `nvflare job resources` for job, site, and study views; and
8. validate under the contract in effect at capture time and reconcile every
   persisted numeric total.

## Run definition

| Item | Value |
|---|---|
| Date | 2026-09-22 |
| Job ID | `0137b861-101e-4ce4-9e62-ddef0e8c935a` |
| Job status | `FINISHED:COMPLETED` |
| Wall-clock job duration | 32.718297 seconds |
| NVFlare distribution | `2.10.0.dev260922` |
| Python | 3.12.3 |
| PyTorch | `2.14.0+cu130` |
| Torchvision | 0.29.0 |
| CUDA bundled with PyTorch | 13.0 |
| Driver | 580.178.04 |
| GPU | one visible NVIDIA L40G with 23,028 MiB |
| CPU | 32 visible units, AMD EPYC 7313P 16-Core Processor |
| Visible memory | 134,921,367,552 bytes |
| Participants | server, site-1, site-2 on one Process POC host |
| Training | 3 FedAvg rounds, 1 epoch per client per round, batch size 64 |
| Data | real CIFAR-10: 50,000 training and 10,000 test images |

The pre-staged dataset was the official CIFAR-10 Python archive. It was checked before extraction with SHA-256 `6d958be074577803d12ecdefd02955f39262c83c16fe9348329d7fe0b5c001ce` and official MD5 `c58f30108f718f92721af3b95e74349a`. These are test-input provenance only; they are not resource-schema fields or a job manifest.

## Result at a glance

All three expected participant reports were accepted and every resource-time and F3 observation had status `reported`.

| Participant | Measured seconds | Average CPU units | Average memory GiB | Average full GPUs | F3 messages | F3 payload bytes |
|---|---:|---:|---:|---:|---:|---:|
| site-1 | 27.975040097 | 32 | 125.6553 | 1 | 3 | 760,203 |
| site-2 | 27.968987578 | 32 | 125.6553 | 1 | 3 | 760,203 |
| server | 28.409528106 | 32 | 125.6553 | 1 | 8 | 1,559,756 |
| Additive total | 84.353555781 | — | — | — | 14 | 3,080,162 |

The CLI renders the additive resource-time total as:

- 0.7498 CPU unit-hours;
- 2.9443 memory GiB-hours; and
- 0.0234 full-GPU instance-hours.

This was a same-host POC run. The three participant intervals overlap and all three saw the same physical GPU, so the additive GPU total is intentionally three participant reports, not the physical capacity of the host. The CLI states that overlapping resources can be counted more than once.

Each site detail reports 1,759.6855 GiB of visible capacity for the filesystem containing its job workspace. This is a point-in-time filesystem observation. It is not usage, allocation, job-owned storage, storage-time, or an additive job total.

`retained_content` remains `unavailable` with issue `not_bound`, as expected because retained-result measurement is not wired yet.

## What the F3 numbers mean

The expected message topology for two clients and three rounds is:

- server: two job applications plus six task responses = 8 messages;
- site-1: three task results = 3 messages;
- site-2: three task results = 3 messages; and
- job total: 14 messages.

The persisted values match that topology exactly.

The run also exercised the DownloadService path. The model arrays were logged as `ArrayDownloadable` transfers of 250,604 bytes while the enclosing Cell/FOBS message body was logged separately. F3 counted one semantic message per operation and added both payload portions:

- each client: `3 × (250,604 array bytes + 2,797 message-body bytes) = 760,203` bytes;
- the six server task responses: `6 × 250,604 + 2 × 2,705 + 4 × 3,201 = 1,521,838` bytes; and
- the remaining 37,918 server bytes are the two job-application sends, or 18,959 bytes each by subtraction.

The production report intentionally exposes the participant total rather than per-traffic-class subtotals. The last job-application value above is therefore an inference from the exact total and the independently logged task-response transfers.

## CUDA bootstrap check

[`pre_torch_probe_and_matmul.txt`](artifacts/pre_torch_probe_and_matmul.txt) records one fresh interpreter that:

1. confirmed `torch` was not loaded;
2. ran the installed production capacity probe;
3. discovered one L40G through the framework-bundled CUDA Runtime;
4. confirmed the probe still had not imported `torch`;
5. imported PyTorch; and
6. completed a finite 2048-by-2048 CUDA matrix multiplication.

This directly validates the absolute-path CUDA Runtime discovery without requiring a system CUDA toolkit or importing custom framework code before the snapshot.

## Training and teardown checks

Both client logs show rounds 0, 1, and 2, evaluation against all 10,000 test images in every round, and successful training completion. Their error logs are empty. The server log ends with `Finished FedAvg`.

There was no F3 callback-drain timeout or incomplete-attribution warning. The public F3 status is `reported` for all participants, so the bounded five-second failure path was not consumed in this run. This does not by itself measure the nanosecond-level cost of individual counter operations; the focused unit and socket tests cover those paths.

During the recorded job window, the one-second GPU samples showed 7.88% average utilization, 26% maximum utilization, 1,112 MiB maximum memory use, and 95.9 W maximum power. This small CNN is real GPU work but is not a stress benchmark.

## Artifact map

- [`job-store/workspace`](job-store/workspace) is the original 662,175-byte job-store `workspace` ZIP with no separate `RESOURCE_STATS` component.
- [`extracted-workspace/resource_stats/resource_summary.json`](extracted-workspace/resource_stats/resource_summary.json) is the directly viewable job roll-up.
- [`extracted-workspace/resource_stats/participants/`](extracted-workspace/resource_stats/participants/) contains the three directly viewable participant reports.
- [`artifacts/cli/resources-job.txt`](artifacts/cli/resources-job.txt) and [`resources-job.json`](artifacts/cli/resources-job.json) are the job-level CLI views.
- [`artifacts/cli/resources-site-1.txt`](artifacts/cli/resources-site-1.txt) shows the human-readable hardware and workspace-filesystem detail. Matching JSON and site-2/server views are beside it.
- [`artifacts/cli/resources-study.txt`](artifacts/cli/resources-study.txt) and [`resources-study.json`](artifacts/cli/resources-study.json) are the one-job study roll-up.
- [`artifacts/archive-validation.json`](artifacts/archive-validation.json) records capture-time production-reader validation and exact numeric-total reconciliation.
- [`artifacts/logs/`](artifacts/logs/) contains the server and client run logs used for round and transfer verification.
- [`artifacts/nvidia-smi.csv`](artifacts/nvidia-smi.csv) and [`nvidia-smi-summary.json`](artifacts/nvidia-smi-summary.json) contain device-level telemetry without process IDs or GPU UUIDs.
- [`artifacts/package-versions.json`](artifacts/package-versions.json) records the installed distribution and framework versions.
- [`artifacts/input-checksums.txt`](artifacts/input-checksums.txt) records only the test wheel and dataset checksums.

The locally built wheel's `nvflare --version` command emitted `0+unknown`; its installed distribution metadata correctly reports `2.10.0.dev260922`. That packaging-version display quirk is unrelated to resource collection and is preserved in the artifacts rather than hidden.

## Exact commands used

After creating the isolated virtual environment and installing the test wheel plus the pinned PyTorch packages, the POC and job were run with:

```console
nvflare poc config --pw /tmp/nvflare-resource-f3-e2e-20260922/poc_workspace
nvflare poc prepare -n 2
nvflare poc start -gpu 0

python job.py --export \
  --export-dir /tmp/nvflare-resource-f3-e2e-20260922/job_config \
  --n_clients 2 --num_rounds 3 --epochs 1 \
  --batch_size 64 --num_workers 2

nvflare job submit \
  -j /tmp/nvflare-resource-f3-e2e-20260922/job_config/hello-pt \
  --study default --format json
nvflare job wait 0137b861-101e-4ce4-9e62-ddef0e8c935a \
  --timeout 1800 --format json

nvflare job resources --job 0137b861-101e-4ce4-9e62-ddef0e8c935a
nvflare job resources --job 0137b861-101e-4ce4-9e62-ddef0e8c935a --format json
nvflare job resources --job 0137b861-101e-4ce4-9e62-ddef0e8c935a --site site-1
nvflare job resources --study default
nvflare job resources --study default --format json
```

Bare `nvflare job resources` was also checked and displayed command help with exit code 0, as designed.
