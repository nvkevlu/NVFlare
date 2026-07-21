# Large-Model Transfer Bottleneck: Team Brief

## Copy/paste summary

The current large-model FL transfer bottleneck is not the physical network and
is not primarily the F3 streaming window. A short three-client `iperf3` test
reached 23.53 Gbps aggregate toward the server and 23.65 Gbps aggregate from
the server, effectively filling the 25 Gbps link. The same hosts transfer the
1.5B synthetic BF16 payload through NVFlare at approximately 0.75--0.80 Gbps
per flow. Increasing F3's chunk/window/ACK settings improved the measured
two-way transfer path by only 8%, and increasing the tensor request batch from
2 MiB to 768 MiB produced no improvement. The evidence therefore points to the
per-byte application/transport path: whole-tensor safetensors serialization,
synchronous pull/consume behavior, disk-offload writes, gRPC/protobuf copying,
and possible duplicate serialization when clients request the same uncached
tensor concurrently. F3 already fragments tensors into smaller streaming
chunks; the main issue is that tensor production, transport, and consumption
are not pipelined efficiently enough to approach the available link rate.

## Scope

This diagnosis applies to the synthetic Qwen-shaped BF16 stress workload. It
isolates model distribution, client return transfer, server memory, and
aggregation behavior; it does not measure GPU training throughput.

The later 32.5B, three-client, three-round natural-memory run completed in
1h54m02s. It reached 245.46 GiB process-tree RSS and a 494.10 GiB cgroup gauge,
with more than half of the sampled cgroup peak attributable to file cache. That
run confirms the operational cost of the slow path but does not change the
small controlled tests that separate link capacity from software throughput.

## Measurements

### Physical network baseline

Five-second, single-stream `iperf3` tests were run in both directions. Three
additional tests ran concurrently to reproduce server fan-in and fan-out.

| Direction | Sequential paths | Three-client aggregate |
| --- | ---: | ---: |
| Clients to server | 18.45--22.93 Gbps | 23.53 Gbps |
| Server to clients | 15.60--21.33 Gbps | 23.65 Gbps |

The concurrent result is the important comparison: the server and network can
move approximately 23.6 Gbps while all three client paths are active.

The measured RTT was approximately 0.4--0.5 ms. At 25 Gbps, the corresponding
bandwidth-delay product is only about 1.2--1.6 MiB. F3's default 16 MiB window
was already well above that value.

Raw artifact:
`../.local/session-2026-07-20-3client/iperf3-quick-20260720/summary.json`

### F3 transport sweep

Each candidate transferred the same 3.08 GB BF16 payload to two clients and
returned two contributions.

| F3 profile | Two-way critical path | Mean per-flow throughput |
| --- | ---: | ---: |
| 1 MiB chunk / 16 MiB window / 4 MiB ACK | 67.56 s | 0.749 Gbps |
| 4 MiB chunk / 128 MiB window / 32 MiB ACK | 62.56 s | 0.795 Gbps |
| 8 MiB chunk / 256 MiB window / 64 MiB ACK | 66.70 s | 0.745 Gbps |
| 16 MiB chunk / 512 MiB window / 128 MiB ACK | 74.04 s | 0.672 Gbps |

The 4 MiB profile won, but only by 8%. Larger values regressed. This rules out
an undersized F3 window as the primary cause and shows that simply increasing
buffers is not an effective fix.

Artifact: `../.local/session-2026-07-20-3client/f3-sweep-summary.md`

### Tensor request batch comparison

The existing `tensor_download_chunk_size` is 2 MiB. Because a tensor item is
always included even when it exceeds that threshold, this setting does not
split a large tensor into 2 MiB pieces. F3 performs the lower-level streaming
fragmentation.

| Tensor request batch | Two-way critical path | Mean per-flow throughput |
| --- | ---: | ---: |
| 2 MiB | 62.56 s | 0.795 Gbps |
| 768 MiB | 62.91 s | 0.788 Gbps |

Grouping more tensors into each pull reply did not improve throughput. Request
round-trip count is therefore not the dominant cost in the tested workload.

Artifact: `../.local/session-2026-07-20-3client/tensor-batch-summary.md`

## Working diagnosis

### 1. The download loop is synchronous across tensor batches

`download_object()` sends a request and waits for the complete reply. It then
passes the returned tensor bytes to the consumer. Only after consumption
finishes does it request the next batch.

This prevents overlap among:

- serialization of the next tensor;
- transport of the current tensor;
- disk writing or deserialization of the previous tensor.

The larger request-batch result shows that merely reducing request count does
not solve this. A bounded multi-item pipeline is needed to overlap the stages.

Relevant code: `../../../nvflare/fuel/f3/streaming/download_service.py`, in the
request loop beginning near `download_object()`.

### 2. Tensor items are serialized as whole safetensors byte buffers

`TensorDownloadable.produce_item()` converts one complete tensor into a
safetensors byte object before the item is returned to the download service.
F3 later streams that object in smaller chunks, but whole-tensor serialization
and buffer ownership have already occurred.

Relevant code: `../../../nvflare/app_opt/pt/tensor_downloader.py`,
`TensorDownloadable.produce_item()`.

### 3. Disk offload is item-buffered, not stream-to-file

The disk consumer receives a complete safetensors item and calls
`f.write(item)`. This reduces long-lived tensor memory, but it does not stream
incoming F3 chunks directly to the destination file. Network receive and disk
write are serialized at the item boundary.

Relevant code: `../../../nvflare/app_opt/pt/tensor_downloader.py`,
`DiskTensorConsumer.consume_items()`.

### 4. The gRPC driver introduces another full frame copy

The synchronous gRPC driver constructs a protobuf `Frame` using
`data=bytes(frame)`. Every F3 frame is therefore copied into a bytes object and
then encoded by protobuf/gRPC. The direct socket driver instead sends a
`memoryview` through the socket.

This is not yet proven to be the largest individual cost, but it is the
highest-value transport A/B because it can be tested by provisioning with
`scheme: tcp` while retaining TLS.

Relevant code:

- `../../../nvflare/fuel/f3/drivers/grpc_driver.py`, `send_frame()`;
- `../../../nvflare/fuel/f3/drivers/socket_conn.py`, `_send_with_timeout()`.

### 5. Concurrent fan-out can duplicate tensor serialization

`CacheableObject._get_item()` intentionally produces an uncached item outside
the cache lock. If two or three clients request the same tensor concurrently,
multiple threads may serialize it. Only after serialization does one result
win the cache race; the redundant results are discarded.

This behavior avoids lock serialization, but it can multiply CPU work and
temporary bytes during synchronized three-client fan-out. A per-item
single-flight future would let one producer serialize while all requesters
share the result.

Relevant code: `../../../nvflare/fuel/f3/streaming/cacheable.py`,
`CacheableObject._get_item()`.

## What is ruled out or unlikely

- **25 Gbps NIC capacity:** concurrent `iperf3` reaches approximately 23.6
  Gbps in both directions.
- **Linux TCP tuning:** single TCP streams reach 15.6--22.9 Gbps on these paths.
- **Insufficient F3 window:** the default window is already more than ten times
  the measured bandwidth-delay product.
- **Too-small tensor request batches:** increasing the batch by 384 times did
  not improve the transfer path.
- **Too few generic streaming workers:** the configured pools are far larger
  than the three active client flows.

The `iperf3` test is plaintext whereas the FLARE connection uses TLS, so it
does not independently quantify encryption overhead. It does establish that
the hosts, NICs, switch, kernel networking, and TCP path can carry line-rate
traffic. TLS and gRPC remain part of the software-path comparison.

## Recommended engineering work

### Priority 0: use the new transaction diagnostics

The harness now records transaction-level counters for:

1. whole-item serialization work and bytes;
2. F3 cache hits, fills, evictions, peak bytes, and duplicate production;
3. offload bytes, item/key counts, header parse time, and file-write time;
4. offload-file lifecycle and lazy materialization bytes/time.

These summaries are emitted once per transaction/lifecycle and imported into
`events.jsonl`. First/last F3 frame timestamps remain a useful follow-up if the
transaction counters do not isolate the dominant stage.

### Priority 1: run a direct TCP+TLS A/B

Provision an otherwise identical small federation with `scheme: tcp` and keep
`connection_security: tls`. Compare the same 1.5B one-round transfer against
the 4 MiB gRPC baseline. This is a configuration-level experiment, not a code
redesign.

### Priority 1: pipeline tensor production, transfer, and consumption

Allow a bounded number or byte budget of tensor items to be in flight. The
receiver should request upcoming items before the current item finishes disk
consumption. Backpressure should be byte-based so memory remains predictable.

### Priority 1: implement per-item single-flight serialization

Represent each in-progress cache item with a future or condition. The first
request serializes it; concurrent requesters wait for and reuse that result
instead of serializing duplicate copies.

### Priority 2: stream disk-offloaded tensors directly to files

Avoid reassembling a complete tensor bytes object before writing. Feed ordered
F3 chunks to a file-backed consumer, then validate the safetensors header and
length at completion.

### Priority 2: reduce gRPC copies or select the socket path for bulk payloads

If TCP+TLS materially outperforms gRPC+TLS, either document the socket driver
as the recommended bulk-model transport or optimize the gRPC frame path to
avoid avoidable bytes/protobuf copies.

## Suggested acceptance criteria

Use the existing one-round 1.5B test as the fast regression gate:

- preserve all sentinels and two-client aggregation;
- preserve disk-offload and memory safety;
- reduce the 62.56-second two-way critical path by at least 30%;
- demonstrate a material increase above 0.8 Gbps per flow;
- avoid increased OOM, retry, peer-loss, and transient-memory failures;
- confirm the improvement persists with three concurrent clients and the 32B
  shape.

An initial target of at least 3 Gbps per flow would be a meaningful improvement
while remaining conservative relative to the measured network capacity.

## Current conclusion

The bottleneck is best described as a **bulk tensor software-pipeline
efficiency problem**, not a network-capacity problem. F3 lower-level streaming
works and buffer tuning provides a small benefit, but the surrounding
whole-tensor serialization, synchronous pull/consume loop, disk-offload item
buffering, gRPC copying, and concurrent cache-production behavior prevent the
application from using the available 25 Gbps link efficiently.

Because this inefficiency dominates lease time, do not book 72B next. Use one
server and two clients for the gRPC+TLS versus TCP+TLS A/B and instrumentation
work, then add a third client only after a candidate improvement passes the
two-client gate. Resume 72B qualification after the critical path improves by
at least 30% without memory, retry, or correctness regression.
