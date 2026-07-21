# Server Memory Analysis: 32B, Three Clients, Three Rounds

## Executive Summary

The completed three-client run does **not** support the earlier explanation that
the server needs one full in-memory model copy for every destination client.
F3's outbound `CacheableObject` generates each serialized item once, shares it
between receivers, and evicts that item after all receivers acknowledge it.

The server's highest sampled cgroup usage was **493.91 GiB** on a machine with
**503.49 GiB** of physical RAM. That number was not 493.91 GiB of live model
tensors. At the sampled peak it consisted of:

| Memory category | GiB | Share of sampled cgroup peak | Meaning |
| --- | ---: | ---: | --- |
| Cgroup anonymous memory | 224.70 | 45.5% | Anonymous pages charged to the cgroup: tensors, buffers, Python/native heaps, and allocator-retained pages |
| Cgroup file memory | 261.57 | 53.0% | Regular filesystem page cache, primarily from tensor-offload and persistence files |
| Cgroup kernel memory | 7.63 | 1.5% | 7.16 GiB slab, 0.45 GiB page tables, about 0.001 GiB sockets, and 0.02 GiB other kernel charge |
| **Cgroup current** | **493.91** | **100%** | Total memory charged to the service cgroup |

At that same sample, the server process tree RSS was **225.16 GiB** and Linux
still reported **268.20 GiB available**. `memory.current` and `MemAvailable`
must not be added or interpreted as two disjoint pools. Linux counts much of
the file cache in the cgroup total while also treating it as reclaimable and
therefore available to applications. The run completed without cgroup OOM,
`memory.high`, or `memory.max` events.

Process-tree RSS and cgroup anonymous memory are different measurements. RSS
is the sum of resident pages mapped by the monitored launcher and server
processes; it can include anonymous, file-backed, shared, and double-counted
shared pages. Cgroup `anon` is the cgroup's charge for anonymous mappings across
all tasks in the cgroup. They were within 0.47 GiB at this sample because the
server process RSS was overwhelmingly anonymous, not because the metrics are
definitionally equivalent.

## Run Under Analysis

- Run ID: `20260720T224359Z-qwen25-32b-3client-f3-4m-batch2m-3r-bce5fd11`
- Workload: synthetic Qwen2.5 32.5B tensor shape
- Model representation: BF16, 65,000,000,000 bytes, or 60.54 GiB
- Topology: one server and three clients
- Rounds: three, all three clients accepted in every round
- Server: 540,618,801,152 bytes, or 503.49 GiB physical RAM
- Server cgroup: natural host limit; no lowered `memory.high` or `memory.max`
- Clients: approximately 125 GiB each
- Tensor disk offload: enabled
- Swap: disabled
- Result: NVFlare job `FINISHED:COMPLETED`; 9/9 sentinels and no OOM

The generated report labels the run `FAIL` only because the cumulative
round-end RSS growth rule compares round zero with round two and exceeds its
10% threshold. The workload itself completed. Round-end post-persist RSS was
121.83 GiB, 182.37 GiB, and 182.42 GiB. The last transition was only 0.0224%,
which is consistent with a one-time model-sized warm-up or retained allocation
followed by a plateau, rather than continuing per-round linear growth.

## What The Server Does Not Hold

The server does not create three unique 60.54 GiB parameter sets merely to send
the same global model to three clients. The outbound F3 path uses one source
object and a shared serialized-item cache:

1. `CacheableObject` records the number of receivers for the transaction.
2. A tensor item is serialized when first requested.
3. Other receivers use the cached serialized bytes for that item.
4. The cached item is removed after every receiver has acknowledged it.
5. The transaction releases the source-object reference after completion.

The observed fan-out behavior supports that implementation. The maximum during
the first round's outbound fan-out was **131.17 GiB**. A 60.54 GiB source plus
three unique 60.54 GiB destination copies would already require about
**242.15 GiB**, before Python, F3, or kernel overhead. That did not occur.

Each receiver does add stream/window state, request bookkeeping, socket/kernel
buffers, and the possibility that the slowest receiver keeps shared serialized
items cached longer. With a 128 MiB F3 window, three clients represent about
384 MiB of nominal per-receiver window capacity, not three additional full
models.

## Where Client Count Does Matter

Returned client results are logically distinct payloads, but disk tensor
offload prevents all three returned models from becoming three complete
resident tensor dictionaries at once:

1. Each incoming safetensors item is written to an offload file.
2. The server keeps lightweight lazy references to the file and tensor key.
3. Aggregation materializes tensors as each shard is needed.
4. The first client initializes one weighted accumulator.
5. Later clients are added into that accumulator in place.

More clients therefore increase simultaneous incoming files, page-cache
activity, stream state, disk writes, and the time that intermediate state
overlaps. They do not require one permanently resident accumulator per client.
In this run, the third client's main visible effect was greater file-cache and
phase-overlap pressure during fan-in.

## Phase-By-Phase Peaks

| Round and phase | Duration | Cgroup peak GiB | Anonymous GiB | File cache GiB | Kernel GiB | Process-tree RSS GiB | Available GiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Round 0 fan-out | 14.37 min | 131.17 | 130.60 | 0.26 | 0.28 | 130.85 | 359.84 |
| Round 0 fan-in/materialize | 14.28 min | 352.08 | 184.85 | 162.37 | 4.81 | 185.09 | 308.33 |
| Round 0 aggregate/persist | 0.76 min | 247.03 | 122.90 | 120.70 | 3.41 | 123.14 | 370.45 |
| Round 1 fan-out | 12.90 min | 316.02 | 187.53 | 124.81 | 3.65 | 187.77 | 304.41 |
| Round 1 fan-in/materialize | 14.40 min | 470.87 | 244.88 | 219.44 | 6.52 | 245.12 | 248.07 |
| Round 1 aggregate/persist | 0.98 min | 370.32 | 183.08 | 181.85 | 5.38 | 183.32 | 307.62 |
| Round 2 fan-out | 13.71 min | 377.33 | 190.06 | 181.85 | 5.39 | 190.30 | 299.57 |
| Round 2 fan-in/materialize | 13.74 min | **493.91** | **224.70** | **261.57** | **7.63** | **225.16** | **268.20** |
| Round 2 aggregate/persist | 0.84 min | 377.05 | 228.67 | 143.90 | 4.44 | 228.95 | 262.24 |

The phase table shows two different effects:

- Live anonymous/process memory rises while model tensors, aggregation shards,
  and serialization work are active.
- File cache accumulates as incoming offloaded tensors and persisted models are
  written and read. It can carry over into the next round until Linux reclaims
  it or the backing files are removed.

## The Highest-Memory Moment

The highest sampled cgroup usage occurred at `2026-07-21T00:09:22Z`, late in
round two's client-result fan-in. One client had finished sending and the other
two were still active. The sequence around that peak was:

| UTC | Observation |
| --- | --- |
| 00:09:09 | File cache reached its maximum of 298.09 GiB while anonymous memory was about 184.99 GiB. |
| 00:09:15--00:09:16 | The first final-round contribution was accepted; the tensor observer reported 121.07 GiB of unique tensor storage. |
| 00:09:22 | Sampled cgroup peak: 493.91 GiB = 224.70 GiB anonymous + 261.57 GiB file + 7.63 GiB kernel. |
| 00:09:39 | Anonymous memory reached its separate maximum of 245.22 GiB while file cache had fallen to 240.84 GiB. |
| 00:09:55 | A second contribution was accepted; observer-visible unique tensor storage reached 181.61 GiB. |
| 00:10:00 onward | Final aggregation and persistence completed; total memory then dropped. |

The file-cache maximum, anonymous maximum, and total maximum did not occur at
exactly the same instant. This matters: adding individual category maxima would
overstate the amount actually used at any one time.

## Why The Final Round Was Highest

At the start of round two, file cache was already **181.85 GiB** from earlier
offload and persistence activity. Final-round result files then added more
file-cache pressure while live aggregation and serialization allocations were
also present. The resulting overlap produced the 493.91 GiB cgroup sample.

The same three-client workload provides an especially useful comparison:

| Run length | Cgroup peak | Process-tree RSS peak | Interpretation |
| --- | ---: | ---: | --- |
| Two rounds | 429.10 GiB | 245.39 GiB | Live process peak already reached approximately its steady maximum. |
| Three rounds | 494.10 GiB gauge / 493.91 GiB sampled | 245.46 GiB | About 65 GiB more cgroup peak, but essentially no increase in process RSS peak. |

The extra round increased the cgroup peak almost entirely through file-cache
carry-over and timing overlap. It did not add another round-sized collection of
live tensors to the server process.

## Interpreting The Measurements

### Cgroup current and peak

`memory.current` includes anonymous pages, file-backed page cache, and kernel
memory charged to the cgroup. `memory.peak` is the kernel's high-water gauge.
The gauge reached 494.10 GiB; the 500 ms/one-second sampler observed 493.91 GiB.
The small difference is expected because a sample can miss a brief maximum.

### Process RSS

Process-tree RSS is useful for identifying the active process working set but
is not a perfect count of unique tensor bytes. It can include allocator-retained
pages and shared or memory-mapped pages, and summing processes can double-count
shared pages. Here it tracks anonymous memory closely enough to show that the
hundreds of GiB of additional cgroup usage were mostly file cache, not a hidden
set of live destination tensors.

For presentation, call this **server process-tree RSS** or **process-resident
working set**. Do not label it “anonymous memory” or “required live tensors.”
Anonymous memory also contains allocator-retained and other application pages
that may no longer correspond to reachable tensors but cannot be discarded by
the kernel while the process still owns them.

### File memory

Cgroup `memory.stat:file` is the amount of file-backed memory charged to the
cgroup. At the peak, `shmem` was zero, so the measured 261.57 GiB was effectively
regular filesystem page cache rather than tmpfs or shared-memory usage. In this
workload it was generated primarily by the 243 safetensors offload shard files
per returned client update and by server checkpoint persistence. Logs,
executables, and other file-backed pages are also included but are small by
comparison.

The telemetry does not attribute page-cache bytes to individual files, so it
cannot defensibly split the 261.57 GiB into exact per-client, offload, and
checkpoint amounts. “Primarily offload and persistence page cache” is the
strongest evidence-supported description. These pages are normally reclaimable
under pressure, though reclaim can cause rereads, writeback, and stalls.

### Kernel memory

At the sampled cgroup peak, the 7.63 GiB kernel charge consisted of **7.16 GiB
slab**, **0.45 GiB page tables**, **about 0.001 GiB socket memory**, and **0.02
GiB other kernel categories**. Slab holds kernel objects such as dentries,
inodes, file descriptors, task/network metadata, and other caches. Some slab is
reclaimable and some is not. The harness captured total slab but not the
`slab_reclaimable` and `slab_unreclaimable` split, so it cannot assign all slab
to either category.

### Tensor-owner observer

The observer deduplicates PyTorch storage addresses visible from known owners.
It recorded model-sized steps from 60.54 GiB to 121.07 GiB and 181.61 GiB as
global/retained model storage and aggregation state overlapped. It cannot see
every byte in F3, safetensors, Python, the native allocator, or the kernel.
Consequently, the category-level explanation is measured, while exact
object-by-object attribution of every anonymous page remains an inference.

### System available memory

At the cgroup peak, `MemAvailable` remained 268.20 GiB because the kernel could
reclaim much of the 261.57 GiB file cache if anonymous allocations demanded
it. This is why a near-host-sized `memory.current` value did not imply that only
9.6 GiB was usable or that the machine was necessarily about to OOM.

## Capacity Implications

- For this exact 32B/three-client/three-round test, a 512 GiB-class server is
  appropriate and completed naturally without a cgroup cap.
- Sizing solely from the 494.10 GiB cgroup gauge is too conservative because
  more than half of the sampled peak was reclaimable file cache.
- Sizing solely from 245.46 GiB process RSS is too aggressive because Linux
  still needs reclaim headroom, kernel memory, and room for burst overlap.
- A 384 GiB server may be viable if page-cache reclaim behaves promptly, but it
  would be a boundary/pressure test rather than a low-risk qualification run.
- More clients should be expected to increase fan-in overlap and page-cache
  churn more than permanent live-tensor memory. Client-count scaling should be
  tested with the same rounds and model while separating anonymous and file
  memory, rather than comparing only total cgroup peaks.

## Follow-Up Instrumentation Status

1. Implemented: offload-file bytes, files, write time, lifecycle, and lazy
   materialization counters are emitted as structured transaction summaries.
2. Implemented: F3 cache bytes, peak bytes, item counts, hits, evictions, and
   duplicate serialization attempts are emitted once per transaction.
3. Record allocator statistics or a non-mutating trim diagnostic at round and
   transaction boundaries to separate reachable objects from free allocator
   arenas.
4. Add phase-scoped maxima to the generated report so anonymous, file, kernel,
   RSS, and available-memory peaks are not interpreted from one total alone.
5. Report the last round-to-round RSS transition separately from cumulative
   growth so one-time warm-up does not look like a continuing leak.

## Evidence And Code Paths

- Run report: `runs/20260720T224359Z-qwen25-32b-3client-f3-4m-batch2m-3r-bce5fd11/report/summary.json`
- Raw cgroup telemetry: `runs/20260720T224359Z-qwen25-32b-3client-f3-4m-batch2m-3r-bce5fd11/metrics/cgroup_samples.csv`
- Raw process telemetry: `runs/20260720T224359Z-qwen25-32b-3client-f3-4m-batch2m-3r-bce5fd11/metrics/process_samples.csv`
- Timeline and tensor-owner events: `runs/20260720T224359Z-qwen25-32b-3client-f3-4m-batch2m-3r-bce5fd11/events.jsonl`
- Shared outbound cache: `nvflare/fuel/f3/streaming/cacheable.py`
- Incoming offload writes: `nvflare/app_opt/pt/tensor_downloader.py`
- Lazy tensor materialization: `nvflare/app_opt/pt/lazy_tensor_dict.py`
- In-place weighted aggregation: `nvflare/app_common/aggregators/weighted_aggregation_helper.py`
