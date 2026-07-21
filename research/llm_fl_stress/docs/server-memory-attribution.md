# Server Memory Attribution: 32B Two-Round Run

## Conclusion

The 32B round-two stall was not caused by one persistent global-model copy per
client. The server had a 60.54 GiB BF16 payload and entered the first round-two
aggregation callback with about 184 GiB resident. It then tried to create the
next model-sized weighted accumulator and reached 226 GiB before cgroup
`memory.high` reclaim prevented useful progress.

The unexplained third payload-sized plateau is associated with the completed
outbound transport/serialization phase. Existing telemetry cannot yet
distinguish whether all of it remained reachable through transport objects or
whether part was free inside the native allocator. It was not a third unique
set of model parameters. The new observer records unique PyTorch storage by
owner and provides an explicit trim probe to settle that distinction on the
next run.

## Existing Evidence

One BF16 payload contains 65,000,000,000 bytes, or 60.54 GiB.

| UTC phase | Server RSS | Cgroup anon | Cgroup file | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Round 0 start, 21:35:08 | 61.06 GiB | Not yet stable | Near zero | Initial model is resident. |
| Round 0 outbound established, 21:35:12 | 121.70 GiB | About 121 GiB | Near zero | One additional payload-sized transport/serialization working set appears. |
| Round 0 before final averaging, 22:02:26 | 178.52 GiB | About 174 GiB | About 33 GiB | The first accumulator has nearly completed while the transport-sized plateau remains. |
| Round 0 after averaging, 22:02:30 | 122.51 GiB | About 122 GiB | Growing checkpoint cache | About one payload is released before persistence; two tensor payloads remain. |
| Round 1 start, 22:03:17 | 121.44 GiB | About 122 GiB | Checkpoint cache | Original and current global tensors remain resident. |
| Round 1 outbound complete, 22:16:54 | 183.30 GiB | 183.19 GiB | 31.65 GiB | The transport-sized plateau remains after both 65 GB downlinks report completion. |
| First round-1 result, 22:29:32 | About 184 GiB | 183.82 GiB | 37.87 GiB | Aggregation begins with roughly three payload equivalents resident. |
| Stalled callback, 22:36:30 | 225.96 GiB | 225.85 GiB | Approximately zero | File cache has already been reclaimed; active anonymous memory dominates. |

The server did not log `Aggregated 1/2 results` in round one. That message is
written only after `WeightedAggregationHelper.add()` returns. The first
round-one callback therefore stalled while materializing shards and creating
the accumulator, not after aggregation had completed.

## Code Path

1. `SyntheticShardModel` creates the 60.54 GiB parameter storage.
2. `PTFileModelPersistor` retains the original module and its initial state.
3. `FedAvg.send_model()` turns the current `FLModel` into a task shareable.
4. `TensorDownloadable.produce_item()` serializes each tensor shard to
   safetensors bytes for the download service.
5. The two downlinks complete, but the process remains at the additional
   payload-sized RSS plateau.
6. The first client result reaches `WeightedAggregationHelper.add()`.
7. Its first contribution calls `v.mul(weight)` for every shard, creating a new
   model-sized in-memory accumulator.

Tensor disk offload prevents the server from holding both returned client
models fully in memory. It does not offload the global tensors, outbound
transport state, or the weighted accumulator.

## Why Normal Reclaim Did Not Fix It

At the stall, cgroup file memory had fallen to approximately zero while cgroup
anonymous memory was about 225.85 GiB. Linux could discard checkpoint page
cache, but it could not discard anonymous tensor, serialization, or allocator
pages. Swap was also disabled.

Round zero released approximately one payload while final averaging completed.
Round one could not reach that release point because it first needed enough
memory to finish constructing the accumulator. This is an allocation-ordering
problem: memory that may become releasable later does not provide headroom to
the earlier allocation that is currently blocked.

Without the operator lowering `memory.max`, the most supported outcomes are a
continued pressure stall until the harness timeout or a later natural cgroup
OOM if allocations reached the original 235 GiB hard limit. A delayed garbage
collection could theoretically have released transport state, but more than
seven minutes at roughly 80% full pressure produced no such recovery. It should
not be described as a run that would normally have completed given more time.

The operator change from 235 GiB to 225 GiB did not create the original stall.
It converted an already-stalled run into a prompt, observable OOM so the harness
could collect and restore the environment.

## Next Diagnostic

Run `configs/qwen25-32b-trim-probe.json` on the same 251/125/125 GiB class when
available. The observer now records at contribution boundaries:

- process RSS split into anonymous, file, and shared pages;
- cgroup current, high, max, anonymous, and file bytes;
- unique PyTorch storage bytes, deduplicated by storage address;
- storage bytes attributed to the persistor module, persisted weights, context
  global model, aggregation result, and aggregation accumulator;
- RSS and cgroup deltas from one explicit `gc.collect()` plus `malloc_trim(0)`
  before the first contribution in each round.

Interpret the round-one `server_allocator_trim_probe` event as follows:

| Observation | Conclusion |
| --- | --- |
| RSS falls by roughly 50--65 GiB while unique tensor storage stays constant | The third plateau is primarily unreachable or allocator-retained transport serialization memory; phase cleanup can close the 32B two-round gap. |
| RSS changes little and known tensor storage is about 121 GiB | Live transport infrastructure retains the extra memory; a lifecycle fix or larger server is required. |
| Known unique tensor storage is already about 181 GiB before aggregation | A third tensor owner exists and its owner breakdown identifies it directly. |
| Trimmed run completes around 180--190 GiB | Repeat once without diagnostic mutation after moving cleanup into the correct lifecycle boundary. |

Do not lower `memory.max` during this diagnostic. Keep the original 235 GiB
hard limit so the trim result, natural pressure behavior, and final outcome are
unambiguous.
