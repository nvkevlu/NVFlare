# Client Count And Server Memory: Team Brief

## Copy/Paste Summary

Increasing the number of clients increases total cluster memory, network bytes,
offload-file traffic, and elapsed time. It does **not** make the FLARE server
hold one permanent full model copy per client. In the measured 32.5B BF16
workload, one model payload was 60.54 GiB. The comparable first-round server
process peaks were 180.33 GiB with one client, 184.51 GiB with two clients, and
185.09 GiB with three clients. Going from one to three clients therefore added
only 4.76 GiB, or 2.64%, to live server RSS in that round.

Here, “server RSS” means the summed resident set of the monitored server
process tree. It is not a synonym for cgroup anonymous memory, although the two
were close in this workload because almost all process-resident pages were
anonymous.

Client count can still increase the server cgroup total substantially because
each returned model is written to disk and contributes Linux page cache. Page
cache is charged to the cgroup but is normally reclaimable; it is not another
set of live model tensors. In the final three-client/three-round peak, 493.91
GiB of cgroup usage consisted of 224.70 GiB anonymous memory, 261.57 GiB file
cache, and 7.63 GiB kernel memory. The server process tree was 225.16 GiB at that
sample and peaked at 245.46 GiB over the whole run. The job completed all three
rounds without `memory.high`, `memory.max`, or OOM events.

## What One More Client Adds

Do not combine these quantities into one memory formula. Present them as four
different scaling effects:

| Resource | What one additional 32B client added | Scaling behavior |
| --- | ---: | --- |
| Server process-tree RSS | Between 0.58 and 4.18 GiB in the measured first round | Small and not established as linear |
| That client's own machine | About 66--67 GiB RSS | Approximately one full client working set per machine |
| Logical network traffic | Exactly 121.08 GiB per round | Linear with client count |
| Server cgroup/file cache | Variable; can be tens of GiB or more | Depends on overlap, disk offload, reclaim, and rounds |

The outbound global model and serialized-item cache are shared, while returned
updates are disk-offloaded and aggregated into one accumulator rather than kept
as one permanent in-memory accumulator per client.

## Measured 32B Client-Count Curve

`P = 60.54 GiB` for the 32.5B BF16 model.

| Clients | Comparable server process-tree RSS | Increase from one client | Client RSS per host | Total client RSS across fleet | Logical wire/round |
| ---: | ---: | ---: | --- | ---: | ---: |
| 1 | 180.33 GiB | -- | 61.33 GiB observed | 61.33 GiB | 121.08 GiB |
| 2 | 184.51 GiB | +4.18 GiB / +2.32% | 65.98 and 66.44 GiB | 132.42 GiB | 242.16 GiB |
| 3 | 185.09 GiB in round zero | +4.76 GiB / +2.64% | about 67 GiB each | about 201 GiB | 363.24 GiB |

The one- and two-client runs used different soft cgroup thresholds, while the
three-client run used the natural host cgroup. Their total cgroup peaks are
therefore not an apples-to-apples client-count curve. Process RSS is the useful
comparison above. The three-client value is the round-zero fan-in/materialize
peak from the completed three-round run so later-round file-cache carry-over is
not mistaken for client-count growth.

The configuration and round count differed slightly, so the three points should
not be turned into a general per-client slope. Their useful conclusion is that
the server process-resident working set was approximately flat from one to
three clients.

## Why Client Count Still Matters

### Server fan-out

The server owns one global model object. F3 serializes a tensor item, shares the
cached bytes with the receivers, and evicts that item after every receiver
acknowledges it. More clients add per-flow request state, socket buffers, and
streaming windows. With the tested 128 MiB window, three nominal windows are
about 384 MiB, not three additional 60.54 GiB models.

Concurrent requests can redundantly serialize the same uncached tensor before
one result wins the cache race. The harness now records duplicate production,
serialization bytes/time, cache hits, and peak cache bytes so the next run can
measure this transient overhead directly.

### Server fan-in

Each client returns a logically distinct full update. Disk tensor offload writes
each safetensors item to a file and keeps lazy references. Aggregation
materializes shards as needed; the first contribution initializes the weighted
accumulator and later contributions update it in place. More clients therefore
increase offload files, page-cache churn, transfer overlap, and time, but not one
permanent full in-memory accumulator per client.

### Client machines

Each client really does need its own full-model working set. At 32B this was
about 66--67 GiB per client. Adding a third client adds another client machine's
approximately 67 GiB, but that RAM is not added to the server requirement.

## Yesterday's Three-Client Peak

Run: `20260720T224359Z-qwen25-32b-3client-f3-4m-batch2m-3r-bce5fd11`

| Quantity | Measured | Interpretation |
| --- | ---: | --- |
| Physical server RAM | 503.49 GiB | Installed host capacity |
| Cgroup peak gauge | 494.10 GiB | Highest instantaneous charge, including cache |
| Highest sampled cgroup current | 493.91 GiB | Sampled total charge |
| Anonymous at that sample | 224.70 GiB | Tensors, heaps, serialized buffers, allocator pages |
| File cache at that sample | 261.57 GiB | Primarily reclaimable offload/persistence page cache |
| Kernel at that sample | 7.63 GiB | Filesystem, networking, slab, page tables, and related charge |
| Process-tree RSS at that sample | 225.16 GiB | Resident server processes at the same instant |
| Whole-run process-tree RSS peak | 245.46 GiB | Highest sampled live-process working set |
| Linux `MemAvailable` at cgroup peak | 268.20 GiB | Included reclaimable cache; not a separate pool to add |
| OOM/high/max events | 0 / 0 / 0 | No cgroup pressure threshold or hard-limit failure |

`memory.current` and `MemAvailable` are not disjoint quantities. Linux charges
file cache to the service cgroup while also counting much of that cache as
available because it can be reclaimed. This is why 493.91 GiB cgroup usage and
268.20 GiB available memory can appear at the same time without contradiction.

The 7.63 GiB kernel charge was measured as 7.16 GiB slab, 0.45 GiB page tables,
about 0.001 GiB socket memory, and 0.02 GiB of other kernel categories. Slab is
kernel object-cache memory such as filesystem and process/network bookkeeping;
some slab can be reclaimed and some cannot. The run did not capture the finer
slab-reclaimable split.

The two-round and three-round three-client runs make the distinction especially
clear: the cgroup peak increased by about 65 GiB in the extra round, while the
process-tree peak changed only from approximately 245.39 to 245.46 GiB. The
extra cgroup charge was overwhelmingly page-cache timing/carry-over, not another
round-sized set of live tensors.

## What The Prior OOM Did And Did Not Prove

The earlier 32B OOM was produced after a 235 GiB hard cgroup limit was later
lowered below live usage. That experiment correctly tested failure capture, but
it did not prove that a natural 512 GiB host requires 494 GiB of non-reclaimable
RAM. Yesterday's uncapped run completed and showed that roughly half of the
near-494 GiB cgroup peak was file cache.

The unanswered sizing question is how aggressively Linux can reclaim that cache
on a smaller host without excessive stalls. The prepared follow-up sets only an
absolute `memory.high` at 384, 320, and optionally 288 GiB while leaving
`memory.max` at the natural host ceiling. That measures reclaim behavior without
manufacturing another hard OOM.

## Practical Allocation Conclusion

- Two clients are sufficient for the first 72B capacity and transport gate.
- A third client is useful as a separate fan-out/fan-in regression, not because
  the server needs three destination copies.
- Size every client independently for one full working set: start at 256 GiB per
  client for 72B.
- Size the server from live anonymous/process memory plus reclaim headroom, not
  from `client_count * model_payload` and not from the cgroup gauge alone.
- Keep disk offload enabled and provide fast storage because client count scales
  offload bytes and page-cache pressure even when live server RSS is nearly flat.
