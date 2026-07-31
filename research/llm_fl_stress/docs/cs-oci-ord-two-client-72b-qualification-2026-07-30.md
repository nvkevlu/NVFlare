# CS-OCI-ORD two-client 72B qualification — 2026-07-30

## Outcome

Slurm job `31158690` is a **formal qualification pass** for two-client, last-decoder-layer federated training of
Qwen2.5-72B on one eight-A100 node.

The allocation completed in 28:13 with Slurm state `COMPLETED` and exit code `0:0`. The retained 1.5B topology
gate, 72B target, trainable-state evidence, persisted-model reload, GPU monitor, and top-level qualification all
report `PASS`. The reviewed stderr contains only non-fatal potential-secret warnings triggered by pinned revisions
and dataset checksums; it contains no traceback or execution failure.

The exact implementation under test was:

- Git commit `163f13c24feef62ab1e5088c298821d5c6c05297`;
- qualification release `2026-07-30-trainable-72b-v11`;
- production NVFLARE services with provisioned gRPC/TLS, not the simulator;
- one CPU-side server plus two real clients on host `batch-block7-01058`;
- site-1 on GPUs 0–3 and site-2 on GPUs 4–7;
- four FSDP2 ranks per client;
- the pinned Qwen2.5-72B revision `efba10c8e54e91e0d9570ab5f7b51a958474d4cb`;
- one federated round with two optimizer steps per client; and
- trainable-state exchange for the 12 tensors in the final decoder layer.

## Exact topology and data path

All services ran as separate processes on the same allocated physical node. The provisioned server participant was
named `localhost` and started with an empty `CUDA_VISIBLE_DEVICES`; it did not use a GPU. Site-1 started with
`CUDA_VISIBLE_DEVICES=0,1,2,3`, and site-2 started with `CUDA_VISIBLE_DEVICES=4,5,6,7`. Each client then launched
four local `torch.distributed.run` workers.

The colocated layout still exercised real NVFLARE production service boundaries, serialization, gRPC/TLS
transport, client task execution, aggregation, and persistence. Traffic used localhost rather than a remote
network, so this result does not qualify inter-node bandwidth, routing, firewall behavior, or resilience.

The server did not load or transmit the complete 145.4-GB base model. Both clients read the staged checkpoint from
the shared Lustre model path and sharded the full model over their respective four GPUs. The server materialized
only the selected final decoder layer:

1. the server sent one 1,755,369,472-byte trainable state to each client;
2. each client used full-model forward passes for two real optimizer steps that updated the final decoder layer;
3. each client returned one changed 1,755,369,472-byte state;
4. the server aggregated both updates with FedAvg; and
5. the server persisted and reloaded the aggregated 12-tensor state.

The evidence therefore records exactly four logical payload transfers and `7,021,477,888` logical bytes. This
figure excludes TLS framing, transport metadata, control traffic, and checkpoint reads from Lustre.

## Pre-submission qualification ladder

The final login-node validator accepted these exact-commit gate artifacts before submission:

| Slurm job | Purpose | Accepted result |
|---|---|---|
| `31150243` | CPU production control plane and repeated two-client jobs | `PASS` |
| `31153668` | CPU 72B identity, sparse server state, dependency, export, and packaged-job preflight | `PASS` |
| `31154570` | Four-GPU exact-model FSDP2 capacity gate | `COMPLETED 0:0`, `PASS` in 15:27 |

The login-node readiness artifact reported `safe_to_submit: true` for the exact branch, release, commit, model
revision, model manifest, container verification marker, dependency lock, and all three gate IDs. The final
allocation repeated that readiness validation before starting services.

The four-GPU gate loaded this exact 72B checkpoint, performed two optimizer steps, exported the selected state, and
measured:

- maximum model-ready time: `793.136` seconds;
- maximum post-ready work time: `8.050` seconds;
- 12 tensors and a 1,755,369,472-byte payload;
- 30,371,807,232 bytes of PyTorch reserved-memory headroom per rank; and
- a conservative full-job host-memory projection of 332,415,472,616 bytes against the 1,600-GiB request.

That 309.59-GiB host projection was a preflight capacity bound, not a measurement of the final job. It combined
twice the measured four-rank RSS, the complete checkpoint size, and a fixed 128-GiB reserve.

## Federated execution evidence

The final job first ran the two-round Qwen2.5-1.5B exact-topology gate. It completed in 89.601 seconds with two
optimizer steps per client per round, 2/2 aggregation, persistence after both rounds, two successful checkpoint
reloads, and distinct fixed datasets. Its payload was 93,595,648 bytes per transfer.

The Qwen2.5-72B target then completed one federated round:

- both production clients became ready after model loading and distributed initialization;
- each client ran two optimizer steps on eight distinct local records;
- both clients returned one changed 12-tensor trainable state;
- the server aggregated 2/2 results;
- the server persisted the aggregated state; and
- the persisted checkpoint reloaded with the expected schema and sampled values.

The 72B target phase completed in `1,459.020` seconds, or approximately 24:19, with status
`FINISHED:COMPLETED`.

The state-evidence validator checked sampled persisted values against the equal-weight mean of the two client
outputs. It also rejected stale-state reuse, schema changes, missing clients, repeated local examples, and
inconsistent payload sizes. The resulting record reports:

- `state_scope=trainable`;
- one completed round and two local steps;
- 8 unique samples at each site;
- distinct site dataset SHA-256 values;
- 7,021,477,888 logical wire bytes;
- one successfully reloaded persisted checkpoint; and
- final persisted trainable-state SHA-256
  `d6170b5a5f173b5b1e5a3ddff4f8018e94f2c4b55701e7f0d4abf1a597fc791e`.

The persisted checkpoint was 1,755,375,119 bytes and contained the expected `meta_props`, `model`, and
`train_conf` keys.

## Training evidence

Site-1:

- final loss: `6.497442245483398`;
- loss trajectory: `5.510444641113281`, `6.497442245483398`;
- selected-parameter maximum change: `3.0517578125e-05`;
- eight unique records, `site-1-001` through `site-1-008`; and
- local round time: `6.600311005953699` seconds.

Site-2:

- final loss: `6.550402641296387`;
- loss trajectory: `6.101966381072998`, `6.550402641296387`;
- selected-parameter maximum change: `3.0517578125e-05`;
- eight unique records, `site-2-001` through `site-2-008`; and
- local round time: `6.746028731111437` seconds.

Every one of the eight ranks identified an `NVIDIA A100-SXM4-80GB`, reported finite losses, and reported the same
positive selected-parameter change.

## GPU and allocation efficiency

All GPU indices 0–7 were observed and active. Every GPU reached 100% utilization. The five-second monitor collected
314 samples per GPU and reported these peak device-memory values:

| GPUs | Peak monitored memory | Approximate 80-GiB headroom |
|---|---:|---:|
| 0 and 4 | 54,017 MiB (52.75 GiB) | 27,903 MiB (27.25 GiB) |
| 1–3 and 5–7 | 53,633 MiB (52.38 GiB) | 28,287 MiB (27.62 GiB) |

Each rank separately reported a PyTorch peak of 51,643,090,432 allocated bytes and 54,802,776,064 reserved bytes.
The full allocation consumed approximately 3.76 allocated A100-hours and released the node after 28:13, well below
the four-hour outer limit.

## Host-memory evidence and boundary

The GPU-node specification lists 2 TB of physical system memory. This job requested `--mem=1600G`, so the Slurm
allocation reserved 1,600 GiB for the complete server-plus-two-client process tree. That was a whole-job
allocation, not a private memory pool for the server.

The retained evidence does **not** isolate the server process's peak RSS or record point-in-time system
`MemAvailable`. The exact server RAM peak therefore cannot be claimed from this run. What is known is:

- the server loaded only the 1,755,369,472-byte selected state, not the 145.4-GB base checkpoint;
- individual training-rank CPU RSS high-water marks ranged from 5.77 to 7.48 GiB;
- summing all eight independently reported rank high-water marks gives 49.57 GiB, but those peaks were not
  necessarily simultaneous and exclude parent services, the server, page cache, and other process memory;
- Slurm reported `MaxRSS=20,621,724K` (approximately 19.67 GiB) for step `31158690.0`; and
- the capacity gate projected 309.59 GiB for its deliberately conservative full-job budget, leaving a projected
  1,290.41 GiB beneath the 1,600-GiB allocation.

[Slurm's `sacct` documentation](https://slurm.schedmd.com/sacct.html) defines `MaxRSS` as the maximum memory
consumption observed for one task of a step, not a sum of every process and not attribution to a named NVFLARE
role. The 19.67-GiB value must therefore not be labeled “server memory.” Likewise, checkpoint size is not server
RSS because aggregation, serialization, and persistence can hold additional copies.

A future experiment that needs exact server-memory attribution should sample the server process tree, allocation
cgroup, and system `MemAvailable` over time. That instrumentation is not required to accept this already successful
training qualification and is not a reason to repeat the 72B GPU run.

## Timeout behavior

Most of the 24:19 target phase was model loading and FSDP2 initialization; the measured local training rounds took
about 6.6–6.7 seconds after readiness. This was the expected healthy startup path.

The corrected lifecycle initialized FLARE before heavyweight model loading. Separate readiness and meaningful
no-progress guards allowed healthy initialization to continue, while the 10,800-second client and transport
envelope stayed outside that expected interval. No application-level arbitrary total-runtime deadline stopped the
run, and the 28:13 allocation remained far below Slurm's four-hour maximum.

## Retained evidence

The durable evidence root is:

```text
$PROJECT_ROOT/artifacts/31158690
```

The primary records are:

- `manifest.txt`;
- `qualification.json`;
- `environment.json`;
- `services/transport-config.json`;
- `gpu-monitor.json` and `gpu-samples.csv`;
- `allocation-start-readiness.json`;
- `target-identity.json`;
- `target-72b/summary.json`; and
- `target-72b/trainable-state-evidence.json`.

The source output is
`$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-72b-trainable-31158690.{out,err}`. The original raw
checkpoint path under `/raid/scratch/kevlu/31158690` was ephemeral; its inspected metadata, size, sampled values,
reload result, and SHA-256 are retained in the artifact records.

## Qualification conclusion

This run proves:

- production NVFLARE orchestration with a TLS server and two required clients;
- concurrent two-client FSDP2 training across all eight allocated A100s;
- distinct site-local data consumption;
- finite real losses and nonzero optimizer updates on every rank;
- bounded last-layer trainable-state exchange;
- 2/2 FedAvg aggregation;
- persisted-state equality with the sampled equal-weight client mean;
- successful checkpoint reload; and
- clean resource release with a durable `COMPLETED 0:0` record.

It does not prove full-model optimization, model convergence, multi-node networking, or failure recovery. No rerun
is required for this qualification. Any later accelerator allocation should answer a new model-quality,
multi-round, multi-node, or resilience question rather than repeat this completed proof.
