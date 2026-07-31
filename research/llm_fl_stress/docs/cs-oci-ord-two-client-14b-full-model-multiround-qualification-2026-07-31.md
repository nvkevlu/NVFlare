# CS-OCI-ORD five-round 14B full-model qualification — 2026-07-31

## Outcome

Slurm job `31225699` is a **formal qualification pass** for five-round, two-client, all-parameter federated
training of the pinned Qwen2.5-14B model on one eight-A100 node.

The allocation completed in 39:19 with Slurm state `COMPLETED` and exit code `0:0`. The fail-closed production
qualification and the independent CPU-only post-run analyzer both report `PASS`. The analyzer found exactly five
unique parsed round records per client, five 2/2 aggregations, five persistence start/end pairs, and four
round-to-round transitions that matched equal-weight BF16 FedAvg at every retained bounded coordinate.

The exact implementation under test was:

- source Git commit `8e20a555559449f5927d2263f1f05ede31bb5191`;
- qualification release `2026-07-31-full-model-14b-v12`;
- production NVFLARE services with provisioned gRPC/TLS, not `SimEnv`;
- one CPU-only server plus two real clients on host `batch-block7-01737`;
- site-1 on GPUs 0–3 and site-2 on GPUs 4–7;
- four FSDP2 ranks per client;
- pinned Qwen2.5-14B revision `97e1e76335b7017d8f67c08a19d103c0504298c9`;
- five federated rounds with two local optimizer steps per client and round at sequence length 512;
- all 14,770,033,664 model parameters trainable; and
- complete 579-tensor, 29,540,067,328-byte state exchange in every round.

The previously qualified 1.5B topology gate was intentionally recorded as `SKIPPED`; this was one result-producing
GPU allocation, not a repeated gate ladder.

## Topology and logical data path

All participants ran as separate processes on the same physical node. The provisioned server participant was named
`localhost` and had no GPU assignment. Site-1 owned four A100s and site-2 owned the other four. Each client launched
four `torch.distributed.run` workers and used FSDP2 to shard the complete model over its GPU group.

Every round performed two server-to-client full-state deliveries and two client-to-server full-state returns. Five
rounds therefore imply 20 logical state-direction payloads:

```text
29,540,067,328 bytes × 4 directions/round × 5 rounds
= 590,801,346,560 logical bytes
= 590.80 decimal GB (550.23 GiB)
```

This is logical tensor payload, not measured serialized or TLS wire traffic. Both clients loaded the staged base
checkpoint from shared Lustre; NVFLARE did not distribute the Hugging Face checkpoint itself. The colocated path
exercised real process isolation, TLS transport, task execution, serialization, aggregation, and persistence, but
it does not measure multi-node bandwidth, firewall behavior, independent failure domains, or WAN performance.

## Federated execution and timing

The internal NVFLARE job `06080ac0-13d8-45e1-acf5-89f95f85ba20` finished as `FINISHED:COMPLETED`. Its target
phase lasted 2,223.479 seconds (37:03). The complete Slurm allocation lasted 2,359 seconds (39:19), leaving about
135.5 seconds for wrapper validation, service setup outside the timed phase, and cleanup. The allocation consumed
approximately 5.24 allocated A100-hours; this is not a claim that every GPU was continuously active.

Each site used eight unique records per round—two steps on four ranks—and 40 unique records across the run. The
post-run analyzer found no cross-site sample-ID overlap.

| Site | Round | Final loss | Local train loop | Rank-zero max RSS | Sampled parameter tensors changed |
| --- | ---: | ---: | ---: | ---: | ---: |
| site-1 | 0 | 6.722119 | 18.707 s | 31.57 GiB | 481 / 579 |
| site-1 | 1 | 5.870090 | 12.576 s | 34.96 GiB | 482 / 579 |
| site-1 | 2 | 5.324338 | 12.027 s | 36.30 GiB | 482 / 579 |
| site-1 | 3 | 5.264512 | 14.253 s | 37.24 GiB | 482 / 579 |
| site-1 | 4 | 5.971639 | 15.334 s | 37.33 GiB | 482 / 579 |
| site-2 | 0 | 6.531734 | 18.746 s | 31.60 GiB | 481 / 579 |
| site-2 | 1 | 6.375522 | 14.516 s | 35.71 GiB | 482 / 579 |
| site-2 | 2 | 6.021887 | 13.604 s | 35.85 GiB | 482 / 579 |
| site-2 | 3 | 5.548635 | 15.486 s | 35.85 GiB | 482 / 579 |
| site-2 | 4 | 6.294414 | 15.866 s | 36.25 GiB | 479 / 579 |

The sampled maximum parameter change was `3.0517578125e-05` for both clients in every round. Early, middle, and
late-layer gradient probes were finite and nonzero in all ten client-round records. The changed-tensor counts are
lower-bound sampled evidence from at most 64 local-shard values per parameter tensor; they do not imply that the
remaining tensors received no update.

Each client recreated its AdamW optimizer every federated round; BF16 moment state was rematerialized during that
round. The experiment therefore proves bounded global-model/FedAvg continuity at the retained coordinates, not
continuity of Adam moments or other optimizer state.

The five reported local training loops summed to 72.90 seconds for site-1 and 78.22 seconds for site-2. They ran
concurrently and account for only a small part of the 37:03 target phase. The remainder includes model and
distributed initialization, repeated full-state load/export, NVFLARE serialization and transport, aggregation,
persistence, and service coordination. The telemetry confirms that work outside the short local loops dominated;
it does not isolate the listed components or establish which one was the largest contributor.

## Bounded full-state continuity proof

Every round reported the same 579 tensors, 29,540,067,328-byte payload, and schema SHA-256
`7b12f14a319d7e73bdbd6e579550f2c4b6a2739367cadef0ff9095a71fd5fa84`. The retained probe sampled four
coordinates per tensor, for 2,316 unique bounded coordinates per state.

Both clients received identical sampled global input values in every round. Their sampled output values diverged
in every round:

| Round | Divergent output coordinates | Checked coordinates |
| ---: | ---: | ---: |
| 0 | 284 | 2,316 |
| 1 | 278 | 2,316 |
| 2 | 292 | 2,316 |
| 3 | 291 | 2,316 |
| 4 | 289 | 2,316 |

Across transitions 0→1, 1→2, 2→3, and 3→4, all 9,264 comparisons matched:

```text
next input = BF16 round((site-1 output + site-2 output) / 2)
```

There were zero mismatches and the maximum observed absolute error was exactly `0.0`. The explicit analyzer
tolerance was zero absolute error allowance plus `1e-6` relative and `0.5` BF16 ULP. This closes the bounded
multi-round FedAvg-continuity gap left by the one-round qualification.

This is deliberately a sampled-state proof. It does not compare every value in each 29.54-GB state. It also covers
the four observable next-round transitions, not the final round-4 output against the persisted checkpoint contents.

## Persistence evidence

The server log contained exactly five `Aggregated 2/2 results` records, five persistence-start records, and five
persistence-end records. The watcher captured sequences 0–4. Every observation reported a 29,540,266,113-byte
(27.5115-GiB) file, 198,785 bytes above the logical tensor payload floor.

All five observations refer to the same server path, which NVFLARE overwrote each round. Only the five small
metadata records were retained on Lustre; the private `/raid/scratch` checkpoint was removed during cleanup.
Persistence is therefore classified as `SIZE_ONLY`: the evidence proves five completed persistence observations at
the expected scale, but it does not prove checkpoint tensor contents, a distinct retained file per round, hashing,
reloadability, or equality between the final checkpoint and the final aggregate.

## GPU evidence

The GPU monitor retained 448 samples for every GPU, 3,584 rows total. All indices 0–7 were observed and active, and
every GPU reached 100% utilization in at least one sample.

| GPUs | Peak monitored memory | Approximate remaining 80-GiB memory |
| --- | ---: | ---: |
| 0 and 4 | 49,021 MiB | 32,899 MiB |
| 1–3 and 5–7 | 48,637 MiB | 33,283 MiB |

Every client-round separately reported a PyTorch peak of 40,157,044,224 allocated bytes (37.40 GiB) and
49,564,090,368 reserved bytes (46.16 GiB), leaving 35,610,492,928 bytes (33.16 GiB) of reserved-memory headroom.
The monitor proves that no GPU was omitted and that all eight reached full sampled utilization. It does not provide
a time-weighted utilization average, so no sustained-utilization percentage is claimed.

## Host-memory evidence

The complete server-plus-two-client job requested 512 GiB. The allocation monitor collected 386 process-tree and
system samples and reported:

- peak process-tree RSS: 183,879,004,160 bytes (171.25 GiB);
- peak process-tree PSS: 181,348,541,440 bytes (168.89 GiB);
- minimum host `MemAvailable`: 1,915,988,893,696 bytes (1,784.40 GiB); and
- minimum local-scratch free space: 16,603,711,873,024 bytes (15.10 TiB).

Compared arithmetically with the 512-GiB request, sampled process-tree RSS left 340.75 GiB. That is nominal
process-tree headroom, not allocation-wide cgroup accounting. Cgroup metrics were unavailable on this node, so the
empty fatal-event counters do not independently prove that no cgroup event occurred. The clean `COMPLETED 0:0`
result and qualification pass show no OOM failure.

Rank-zero client RSS increased from 31.57/31.60 GiB in round 0 to 37.33/36.25 GiB in round 4; the six nonzero ranks
remained tightly grouped at approximately 6.75 GiB. This is consistent with rank zero's repeated full-state bridge
and allocator/cache duties, but the retained telemetry cannot distinguish reusable cache from a leak. The run
completed with large host headroom, so this trend does not invalidate the qualification. The process-tree monitor
also does not isolate the CPU-only server's peak from the clients; exact server-only RAM remains unmeasured.

## Retained evidence

The durable evidence root is:

```text
$PROJECT_ROOT/artifacts/31225699
```

Primary records include:

- `manifest.txt`;
- `qualification.json`;
- `gpu-monitor.json` and `gpu-samples.csv`;
- `allocation-monitor.json` and `allocation-memory.jsonl`;
- `target-14b-full-model-multiround/configuration.json`;
- `target-14b-full-model-multiround/summary.json`;
- retained server, site-1, and site-2 log trees;
- five `persistence/persisted_model-*.json` observations; and
- `multiround-post-run-analysis.json`.

The source Slurm logs are:

```text
$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-14b-5round-31225699.out
$PROJECT_ROOT/logs/coreai_edgeai_flresearch-kevlu:nvflare-14b-5round-31225699.err
```

## Qualification conclusion

This run proves, for the pinned software and model revision:

- five completed production NVFLARE rounds with a provisioned TLS server and two required clients;
- concurrent two-client FSDP2 training across all eight allocated A100s;
- all 14.77 billion parameters participating in ten optimizer steps per client;
- 40 unique records per site with no cross-site sample-ID overlap;
- complete full-state return from both clients in all five rounds;
- distinct sampled client outputs in every round;
- exact equal-weight BF16 FedAvg continuity at all 9,264 retained transition coordinates;
- five 2/2 aggregations and five full-scale persistence observations;
- measured GPU and process-tree memory with substantial headroom; and
- clean release of the allocation in 39:19.

It does not establish every unsampled state value, persisted checkpoint contents or reloadability, convergence,
useful model quality, multi-node networking, sustained GPU utilization, exact server-only RAM, FP32-moment
capacity, fault tolerance, privacy properties, or full-model scaling to 32B/72B. No rerun is required for this
qualification. The next GPU allocation should answer a distinct capacity question.
