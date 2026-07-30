# CS-OCI-ORD two-client 32B qualification — 2026-07-29

## Outcome

Slurm job `31091793` is a **formal qualification pass** for two-client, trainable-state federated training of
Qwen2.5-32B on one eight-A100 node.

The run completed in 11:19 with Slurm state `COMPLETED` and exit code `0:0`. The retained qualification artifact,
GPU monitor, 1.5B gate, and 32B target all report `PASS`. There was no traceback, execution exception, failed status,
or fatal runtime marker in the reviewed output.

The exact implementation under test was:

- Git commit `d7e4618fe9ad2cc6314493b852f5a641b107611a`;
- qualification release `2026-07-29-trainable-32b-v9`;
- production NVFLARE services with provisioned TLS, not the simulator;
- one server plus two real clients on the allocated host;
- site-1 on GPUs 0–3 and site-2 on GPUs 4–7;
- four FSDP2 ranks per client;
- the pinned Qwen2.5-32B revision `1818d35814b8319459f4bd55ed1ac8709630f003`; and
- trainable-state exchange for the final decoder layer.

## Pre-allocation gates

Two CPU-only jobs qualified the code and generated job before the accelerator submission:

| Slurm job | Purpose | Result | Elapsed |
|---|---|---|---|
| `31086176` | Production control plane and two consecutive two-client jobs | `COMPLETED 0:0`, `PASS` | 4:45 |
| `31088259` | 32B identity, sparse server state, dependency, export, and packaged-job preflight | `COMPLETED 0:0`, `PASS` | 2:36 |

The exported-job preflight confirmed both clients, early `flare.init()`, strict two-client startup, three finite
resends, both packaged datasets, and the coordinated 2,400-second large-model timeout envelope.

The 32B model preflight confirmed:

- architecture `Qwen2ForCausalLM`;
- BF16 weights;
- hidden size 5,120 and 64 decoder layers;
- 17 safetensor shards totaling 65,527,841,752 bytes; and
- a 12-tensor trainable server state of exactly 975,210,496 bytes.

## Federated execution evidence

The GPU qualification first ran a two-round Qwen2.5-1.5B gate. It completed in 89.637 seconds with two optimizer
steps per client per round, 2/2 aggregation, persistence after both rounds, successful checkpoint reloads, and
distinct fixed datasets. Its trainable payload was 93,595,648 bytes per transfer.

The Qwen2.5-32B target then completed one federated round:

- both clients became ready after the expected model-load and FSDP initialization period;
- each client ran two real optimizer steps;
- both clients returned one 975,210,496-byte, 12-tensor trainable state;
- the server aggregated 2/2 results with equal weights;
- the server persisted the aggregated trainable state; and
- the persisted checkpoint reloaded with the expected tensor schema.

The 32B target phase completed in 492.098 seconds with status `FINISHED:COMPLETED`.

The evidence validator checked sampled persisted values against the equal-weight mean of the two client outputs.
It also rejected stale-state reuse, schema changes, missing clients, repeated local examples, and inconsistent
payload sizes. The resulting evidence record reports:

- `state_scope=trainable`;
- one completed round and two local steps;
- 8 unique samples at each site;
- distinct site dataset SHA-256 values;
- 3,900,841,984 logical wire bytes;
- one successfully reloaded persisted checkpoint; and
- final persisted trainable-state SHA-256
  `920bda5ff5229f7d778c6e5cf6eddd881134e35e39c34294cad64b540e33fde1`.

## Training evidence

Site-1:

- final loss: `6.426687240600586`;
- loss trajectory: `5.719701766967773`, `6.426687240600586`;
- selected-parameter maximum change: `3.0517578125e-05`;
- eight unique records, `site-1-001` through `site-1-008`; and
- local round time: `3.7193620591424406` seconds.

Site-2:

- final loss: `6.7094573974609375`;
- loss trajectory: `6.115311622619629`, `6.7094573974609375`;
- selected-parameter maximum change: `3.0517578125e-05`;
- eight unique records, `site-2-001` through `site-2-008`; and
- local round time: `3.6928612529300153` seconds.

Every rank identified an `NVIDIA A100-SXM4-80GB`. Each rank reported finite losses and a positive selected-parameter
change.

## Resource and transfer efficiency

All GPU indices 0–7 were observed and active. Peak monitored memory was:

- 28,017 MiB on GPUs 0 and 4; and
- 27,633 MiB on GPUs 1–3 and 5–7.

Peak utilization was 75% on GPU 0, 35% on GPU 4, and 100% on GPUs 1–3 and 5–7. The monitor collected 122 samples
per GPU and reported `PASS`.

The 11:19 allocation consumed approximately 1.51 allocated A100-hours. The scheduler released the node immediately
after evidence collection and cleanup, despite the conservative two-hour wall limit.

The 32B target exchanged 3.90 GB of logical trainable-state traffic: one server-to-client and one client-to-server
transfer for each of two sites. This is approximately 30 times less traffic than the 118.16 GB full-state exchange
observed in the earlier 14B stress qualification, even though the base model is larger. The immutable 32B base
checkpoint remained local to each site; only the approximately 487.6 million BF16 values in the selected decoder
layer crossed the federated boundary.

## Timeout behavior

The target produced four initial streaming-progress events and then spent approximately 434 seconds in heavyweight
model loading and distributed initialization before both clients reported ready. This was healthy startup, not a
hang.

The corrected client calls `flare.init()` before heavyweight model, tokenizer, dataset, and checkpoint loading.
The qualification uses separate readiness and no-progress budgets rather than an application-level total-runtime
deadline. The readiness budget covered the expected 32B startup, and the inactivity counter reset when both clients
became ready, when their results arrived, when aggregation completed, and when persistence completed.

This run therefore directly validates the lifecycle ordering and progress-aware timeout changes that replaced the
earlier arbitrary deadline.

## Qualification conclusion

The run proves, at 32B scale:

- production NVFLARE service orchestration with two required clients;
- concurrent two-site FSDP2 training across all eight allocated A100s;
- distinct site-local data consumption;
- finite real losses and nonzero optimizer updates;
- bounded trainable-state exchange below the 1 GiB payload ceiling;
- 2/2 FedAvg aggregation;
- persisted-state equality with the sampled equal-weight client mean;
- successful checkpoint reload; and
- clean resource release with a durable `COMPLETED 0:0` record.

No rerun is required for this qualification. Any subsequent accelerator allocation should answer a new scaling,
model-quality, multi-round, or multi-node question rather than repeat this completed proof.
