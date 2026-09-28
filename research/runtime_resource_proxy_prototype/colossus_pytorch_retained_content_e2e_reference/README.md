# Colossus retained-content end-to-end reference

This directory preserves a real one-server, two-client PyTorch run of the
production resource-statistics path after the simple terminal run-directory
observation was added. The run used the same collector, handoff, CellNet
transport, server reconciliation, normal `workspace` ZIP, archive reader, and
CLI code that NVFlare uses outside the test.

The run also includes the follow-up polish made during review:

- a traversal or per-file observation error produces a numeric `partial`
  subtotal instead of a falsely complete report;
- symlinks and other non-regular entries contribute zero and are not followed;
- a symlink cannot be used as the run-directory root; and
- human output calls the value `RUN-DIR FILES`, shows its status, and no longer
  calls the mixed workspace tree "saved content."

This run was captured before the intermediate decision to add `job_name` to
the server-created summary and study rows. A later review removed it again
from the archived `resource_summary`. These records remain historical runtime
evidence for collection, F3, transport, rollup, archive, and CLI behavior, not
current-schema goldens. The participant wire record never carried a name.

## Run definition

| Item | Value |
|---|---|
| Date | 2026-09-22 |
| Job ID | `64b20e29-7f08-4eeb-bdd6-8303be37dae8` |
| Study | `retained-validation` |
| Job status | `FINISHED:COMPLETED` |
| Wall-clock job duration | 32.9 seconds |
| NVFlare distribution | `2.10.0.dev260922` |
| Python | 3.12.3 |
| PyTorch | `2.14.0+cu130` |
| Torchvision | `0.29.0+cu130` |
| CUDA bundled with PyTorch | 13.0 |
| Driver | 580.178.04 |
| GPU | one visible NVIDIA L40G with 23,028 MiB |
| CPU | 32 visible units, AMD EPYC 7313P 16-Core Processor |
| Participants | server, site-1, site-2 on one Process POC host |
| Training | 3 FedAvg rounds, 1 epoch per client per round, batch size 64 |
| Data | real CIFAR-10: 50,000 training and 10,000 test images |

The existing verified CIFAR-10 copy under `/tmp/nvflare/data` was reused; no
dataset download was needed for this run.

## Result

All three expected reports were accepted. Resource-time, run-directory files,
and F3 all have status `reported`.

| Participant | Measured seconds | Average CPU units | Average memory GiB | Average full GPUs | Run-dir file bytes | F3 messages | F3 payload bytes |
|---|---:|---:|---:|---:|---:|---:|---:|
| site-1 | 26.945311029 | 32 | 125.6553 | 1 | 72,912 | 3 | 760,203 |
| site-2 | 27.437844415 | 32 | 125.6553 | 1 | 72,912 | 3 | 760,203 |
| server | 25.394132093 | 32 | 125.6553 | 1 | 616,179 | 8 | 1,559,780 |
| Additive total | 79.777287537 | — | — | — | 762,003 | 14 | 3,080,186 |

The exact retained-content equation is:

```text
72,912 + 72,912 + 616,179 = 762,003 bytes
```

The job rollup, all three participant copies, the job CLI, the one-job study
rollup, and the archive reader agree exactly. The complete machine-checked
receipt is [`artifacts/validation.json`](artifacts/validation.json).

Both clients completed all three rounds. Their test accuracy progressed from
10% to 44% to 53%, and both error logs are empty.

## What the value includes

The terminal observation adds logical `st_size` for regular files below that
participant's job run directory. It excludes the top-level `resource_stats/`
subtree and ignores symlinks and non-regular entries. It is one best-effort,
non-atomic participant self-report; it is not a curated model inventory or the
compressed archive size.

The server value includes both persisted model files:

| File | Logical bytes |
|---|---:|
| `app_server/FL_global_model.pt` | 252,165 |
| `app_server/best_FL_global_model.pt` | 252,165 |

The hello-pt client code writes `cifar_net.pth` relative to the POC service
working directory. Those two 251,813-byte files landed at the site roots, one
level above each job run directory. They are therefore deliberately not in the
reported run-directory value or the central job workspace. This is useful
boundary evidence: the implementation measures the declared run directory,
not arbitrary files a custom application writes elsewhere. Separately
configured result, log, and audit roots remain an explicit coverage gap until
the design has a deduplication rule for them.

## Why the final directory is larger

The value is captured before the private terminal handoff is written, before
`stats_pool_summary.json` is created, before upload, and before later shutdown
log lines. Final files therefore cannot reproduce the earlier observation
byte-for-byte.

| Participant evidence | Reported bytes | Later bytes | Difference |
|---|---:|---:|---:|
| site-1 final run-directory scan | 72,912 | 111,551 | 38,639 |
| site-2 final run-directory scan | 72,912 | 112,213 | 39,301 |
| server final ZIP, excluding `resource_stats/` | 616,179 | 650,586 | 34,407 |

The client differences are dominated by the later stats-pool file. The server
ZIP contains 616,710 bytes when that file is also removed, only 531 bytes above
the terminal observation because logs continued to grow. These comparisons are
sanity checks, not schema equalities.

On the two final 19-file client trees, a repeat of the production scan took
0.339 ms and 0.316 ms. That is reassuring for this workload, but the traversal
still needs a fixed production bound for pathological trees; the live timing
does not remove that documented gap.

## F3 cross-check

The expected two-client, three-round topology remains exact:

- server: two job applications plus six task responses = 8 messages;
- site-1: three task results = 3 messages;
- site-2: three task results = 3 messages; and
- job total: 14 messages.

The payload total differs by only 24 bytes from the earlier F3 reference
because the exported job metadata changed slightly; the semantic message
counts and origin-only accounting behavior are unchanged.

## Artifact map

- [`artifacts/job-store/workspace`](artifacts/job-store/workspace) is the
  original 662,961-byte normal job-store ZIP. There is no duplicate
  `RESOURCE_STATS` component.
- [`extracted-workspace/resource_stats/resource_summary.json`](extracted-workspace/resource_stats/resource_summary.json)
  is the directly viewable job rollup; the participant records are beside it.
- [`artifacts/cli/resources-job.txt`](artifacts/cli/resources-job.txt) and
  [`resources-job.json`](artifacts/cli/resources-job.json) are the job views.
- [`artifacts/cli/resources-site-1.txt`](artifacts/cli/resources-site-1.txt)
  is one site detail; site-2 and server outputs are beside it.
- [`artifacts/cli/resources-study.txt`](artifacts/cli/resources-study.txt) and
  [`resources-study.json`](artifacts/cli/resources-study.json) show the
  one-job study view.
- [`artifacts/validation.json`](artifacts/validation.json) contains the strict
  schema, rollup, archive, CLI, F3, and post-job scan assertions that passed
  against the then-current pre-release v1 contract. Current v1 has an ID-only
  archived job summary and a renamed, destination-grouped message-traffic field.
- [`artifacts/inventory/`](artifacts/inventory/) records the final client file
  trees and the two client checkpoints outside those trees.
- [`artifacts/logs/`](artifacts/logs/) and
  [`artifacts/training-summary.txt`](artifacts/training-summary.txt) preserve
  the training and POC evidence.
- [`artifacts/package-versions.json`](artifacts/package-versions.json) and
  [`artifacts/nvidia-smi.csv`](artifacts/nvidia-smi.csv) record the framework
  and device environment without a GPU UUID.

## Commands used

After installing the locally built wheel into the preserved isolated virtual
environment, the fresh POC and job were run with:

```console
nvflare poc config \
  --pw /tmp/nvflare-resource-retained-e2e-20260922/poc_workspace
nvflare poc prepare -n 2
nvflare poc start -gpu 0

python job.py --export \
  --export-dir /tmp/nvflare-resource-retained-e2e-20260922/job_config \
  --n_clients 2 --num_rounds 3 --epochs 1 \
  --batch_size 64 --num_workers 2

nvflare study register retained-validation \
  --site-org nvidia:site-1,site-2
nvflare job submit \
  -j /tmp/nvflare-resource-retained-e2e-20260922/job_config/hello-pt \
  --study retained-validation --format json
nvflare job wait 64b20e29-7f08-4eeb-bdd6-8303be37dae8 \
  --study retained-validation --timeout 1800 --format json

nvflare job resources \
  --job 64b20e29-7f08-4eeb-bdd6-8303be37dae8 \
  --study retained-validation
nvflare job resources \
  --job 64b20e29-7f08-4eeb-bdd6-8303be37dae8 \
  --study retained-validation --site site-1 --format json
nvflare job resources --study retained-validation
```

The POC was stopped after recovery. The Colossus lease was not released.
