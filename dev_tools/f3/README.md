# F3 Benchmark Tools

Three programs for measuring F3 streaming, tensor-transfer throughput, and
gRPC connection scaling between two machines, plus sample tuning configs.

| File | Purpose |
|------|---------|
| `tensor_download_bench.py` | End-to-end PyTorch tensor transfer through FOBS and the F3 Download Service |
| `cellnet_bench.py` | Raw F3 cellnet streaming and baseline raw-TCP ceiling |
| `grpc_lane_bench.py` | Isolated same-port gRPC RPC/channel scaling diagnostic |
| `comm_config.yml` | Sample F3 tuning config for high-bandwidth networks |
| `grpc_tls/comm_config.yml` | Synchronous gRPC profile for production-equivalent transport-TLS tests |

Start the receiver on the destination machine first; then start the sender.
Use the same Python environment (`nvflare` must be importable) on both hosts.
The cellnet benchmark's RSS sampler reads Linux ``/proc/self/statm``; run it on
Linux when memory reporting is required.

---

## `tensor_download_bench.py`

Measures the full tensor transfer pipeline: FOBS decomposition →
Download Service → receiver reconstruction → validation. Runs two modes
against the same receiver process:

- **memory** — reconstruct every received tensor as a `torch.Tensor` in RAM.
- **disk** — write safetensors chunks to local storage and reconstruct lazy
  references. Only one small validation tensor is materialised.

Throughput is reported over the unique tensor bytes that `TensorDecomposer`
actually transfers (aliased or tied tensors count once). The logical model size
is reported separately. Sender and receiver peak RSS deltas and receiver disk
consumption are included in the summary.

Each run also reports direct-path eligible, observed-direct, and fallback tensor
counts and bytes, plus the direct reply count and items-per-reply distribution.
Memory-mode validation hashes a tensor of at least 10 MiB and
requires that exact received tensor to have been produced by the direct decoder;
this avoids accidentally validating only a small legacy-path tensor. Disk mode
requires zero observed direct-path items and does not materialize the direct
sample. A memory run fails early if its tensor selection has no direct-eligible
item. Direct validation uses a zero-copy raw-byte hash on both endpoints after
the timed transfer, so it neither pre-warms mmap pages nor inflates transfer time.

The primary throughput uses the receiver-observed interval ending when the full
request reaches the transfer callback. The sender also reports validated
end-to-end time and receiver validation time separately, so correctness checking
does not make the transport appear slower.

### Quick start

```bash
# Receiver (destination host) — start first
python dev_tools/f3/tensor_download_bench.py recv \
    --url tcp://0.0.0.0:8002 \
    --offload-dir /fast/local/nvme

# Sender (host with the checkpoint)
python dev_tools/f3/tensor_download_bench.py send \
    --url tcp://<receiver-host>:8002 \
    --checkpoint /path/to/pytorch_model.bin
```

`--modes memory,disk` (default) runs both modes. Use `--modes memory` or
`--modes disk` to run only one. `--repeat N` repeats for stable median values.

For a fair legacy-path control using the same candidate binary and F3 settings,
add `--disable-direct` to the sender command. The sender coordinates this with
the receiver for each run; the receiver needs no extra flag. Eligible tensor
counts are still reported, while validation requires zero observed direct items.
Omitting the flag preserves the default requirement that every eligible
memory-mode tensor uses the negotiated direct path.

To isolate bounded multi-tensor replies without falling back to safetensors,
add `--disable-direct-batch`. This keeps the direct-memory V1 path enabled but
forces one tensor per Download Service reply. Compare it with the default on the
same candidate binary; `direct-replies`, `batched-replies`, and `items/reply` in
the result prove which policy was exercised. `--disable-direct` also disables
batch negotiation automatically.

The memory-mode receiver needs enough RAM for the full model plus transient
serialisation buffers. Put `--offload-dir` on fast local storage for a
meaningful disk result.

### Smoke test with a size limit

`--max-bytes` selects the smallest unique tensors up to a binary byte limit
(aliases of a selected tensor are included at no extra cost). Use this to
verify both transfer paths without sending the full checkpoint:

```bash
python dev_tools/f3/tensor_download_bench.py send \
    --url tcp://<receiver-host>:8002 \
    --checkpoint /path/to/pytorch_model.bin \
    --max-bytes 512M
```

Suffixes are binary: `1K = 1024`, `1M = 1024K`, `1G = 1024M`.

### With F3 tuning

Pass the same `comm_config.yml` to both endpoints:

```bash
python dev_tools/f3/tensor_download_bench.py recv \
    --url tcp://0.0.0.0:8002 \
    --offload-dir /fast/local/nvme \
    --f3-config dev_tools/f3/comm_config.yml

python dev_tools/f3/tensor_download_bench.py send \
    --url tcp://<receiver-host>:8002 \
    --checkpoint /path/to/pytorch_model.bin \
    --f3-config dev_tools/f3/comm_config.yml
```

### Production-equivalent synchronous gRPC with TLS

Use the supplied gRPC profile on both endpoints. Credential material remains
outside this repository: the receiver directory must contain `rootCA.pem`,
`server.crt`, and `server.key`; the sender directory must contain `rootCA.pem`.

```bash
# Receiver
python dev_tools/f3/tensor_download_bench.py recv \
    --url grpc://0.0.0.0:8002 \
    --offload-dir /fast/local/nvme \
    --f3-config dev_tools/f3/grpc_tls/comm_config.yml \
    --connection-security tls \
    --credentials-dir /path/to/server/startup

# Sender
python dev_tools/f3/tensor_download_bench.py send \
    --url grpc://<receiver-host>:8002 \
    --checkpoint /path/to/pytorch_model.bin \
    --modes memory \
    --repeat 5 \
    --f3-config dev_tools/f3/grpc_tls/comm_config.yml \
    --connection-security tls \
    --credentials-dir /path/to/client/startup
```

The sender URL hostname must match a SAN in the server certificate. This mode
measures production-equivalent gRPC transport TLS; Cell end-to-end message
encryption remains disabled so its cost is not conflated with the transport.
Clear mode remains available for controls, but is not the production-equivalent
result.

---

## `cellnet_bench.py`

Measures F3 cellnet streaming throughput and, optionally, the raw TCP ceiling
for the same host pair so you can see how much overhead F3 adds.

### F3 cellnet

```bash
# Receiver
python dev_tools/f3/cellnet_bench.py recv --url tcp://0.0.0.0:8002

# Sender — unreliable (faster, no retransmit)
python dev_tools/f3/cellnet_bench.py send \
    --url tcp://<receiver-host>:8002 --reliable false

# Sender — reliable
python dev_tools/f3/cellnet_bench.py send \
    --url tcp://<receiver-host>:8002 --reliable true
```

Default payload is 10 GiB (`--size-gb 10`). The receiver stays up between
runs, so you can A/B `reliable=true` vs `reliable=false` without restarting.

### With F3 tuning

```bash
python dev_tools/f3/cellnet_bench.py recv \
    --url tcp://0.0.0.0:8002 \
    --f3-config dev_tools/f3/comm_config.yml

python dev_tools/f3/cellnet_bench.py send \
    --url tcp://<receiver-host>:8002 \
    --f3-config dev_tools/f3/comm_config.yml
```

The same `--connection-security`, `--credentials-dir`, and
`grpc_tls/comm_config.yml` combination can be used with `cellnet_bench.py` to
measure raw F3 throughput over synchronous gRPC/TLS. Raw `--transport tcp`
does not accept TLS credential options because it intentionally bypasses F3.

### Raw TCP ceiling

Measures the Python/TCP throughput limit for the host pair, independent of F3.
Stop the cellnet receiver before reusing the port.

```bash
# Receiver
python dev_tools/f3/cellnet_bench.py recv \
    --transport tcp --url tcp://0.0.0.0:8002

# Sender
python dev_tools/f3/cellnet_bench.py send \
    --transport tcp --url tcp://<receiver-host>:8002
```

Raw TCP mode defaults to a 1 GiB untimed warm-up followed by a 100 GiB
measured payload (about 30 seconds at 25 Gbit/s). Override with
`--size-gb`. The default application buffer is 16 MiB; change it with
`--buffer-mb` on **both** endpoints. Override the nominal link rate used for
utilisation reporting with `--target-gbps`.

---

## `grpc_lane_bench.py`

Determines whether one synchronous gRPC stream or one physical gRPC/TCP
connection is the transport bottleneck. This is a diagnostic beneath F3: it
uses the same `streamer.Streamer/Stream` bidirectional RPC and `Frame` protobuf
as the gRPC driver, but it does not include Cell, SFM, Download Service, or
tensor work.

Every condition uses one receiver hostname, listening port, and TLS
certificate. Total measured bytes, warm-up bytes, and aggregate application
credit remain fixed as the lane count changes. Each lane keeps the configured
ACK threshold, so dividing the bytes among lanes keeps aggregate ACK work
approximately fixed. Each Python Channel is explicitly assigned a local gRPC
subchannel pool, and the receiver returns the `context.peer()` socket for every
RPC. A run fails if the requested number of physical connections was not
actually created.

This program owns the same `/streamer.Streamer/Stream` RPC name as F3, so run
it as a dedicated receiver process on a dedicated test port. It cannot attach
to or share a live F3 listener, and it must not be pointed at a production
endpoint. TLS authenticates the receiver only; it does not authenticate
benchmark senders, so bind it only on trusted leased hosts and stop it after
the test.

Use the production TLS profile and credentials exactly as for the other
benchmarks:

```bash
# Receiver — keep this process running for all four conditions
python dev_tools/f3/grpc_lane_bench.py recv \
    --url grpc://0.0.0.0:8002 \
    --f3-config dev_tools/f3/grpc_tls/comm_config.yml \
    --connection-security tls \
    --credentials-dir /path/to/server/startup

# Sender — current topology: one RPC on one physical connection
python dev_tools/f3/grpc_lane_bench.py send \
    --url grpc://<receiver-host>:8002 \
    --channels 1 --rpcs-per-channel 1 \
    --direction server-to-client \
    --size-gb 16 --warmup-gb 1 --chunk-mb 2 --repeat 3 \
    --f3-config dev_tools/f3/grpc_tls/comm_config.yml \
    --connection-security tls \
    --credentials-dir /path/to/client/startup
```

Repeat the sender command with these topologies, preserving all other options:

| Channels | RPCs/channel | Expected physical sockets | What it isolates |
|----------|--------------|---------------------------|------------------|
| 1 | 1 | 1 | Current synchronous driver topology |
| 1 | 2 | 1 | Per-RPC/handler serialization on one HTTP/2 connection |
| 2 | 1 | 2 | Two physical gRPC/TCP/TLS connections on the same port |
| 4 | 1 | 4 | Four physical connections on the same port |

`server-to-client` is the primary result because it matches model download;
`client-to-server` is a control for asymmetry in the two halves of the
bidirectional RPC. Run the full topology table in both directions. In
`server-to-client` mode, `[send]` is the active gRPC client but receives the
bulk bytes; `[recv]` is the listening server and sends them. Attribute CPU and
RSS using both the process label and the reported direction.

The default 64 MiB aggregate window is divided among logical RPCs. Every lane
retains the default 16 MiB ACK threshold, which keeps total ACK count roughly
constant because each lane transfers only its share of the bytes.
`peak_outstanding_bytes` must not exceed `window_bytes`, so a multi-lane result
cannot gain throughput merely by multiplying application buffering. If the
fixed-credit matrix is flat, run a separately labelled scaled-credit control
by scaling `--window-mb` to `64 × logical_rpcs` while retaining `--ack-mb 16`;
that measures the performance and memory cost of multiplying flight size.

Interpret the matrix before changing production F3. Scaling for `1 × 2`
points to per-RPC serialization. Scaling only for `2 × 1` or `4 × 1` points to
a per-physical-connection limit. If neither scales, adding connections to F3
will not address the shared protobuf, gRPC-core, copy, or CPU bottleneck.
Even a positive result is only a gate: this diagnostic bypasses Cell/SFM,
F3's shared ordered ACK/retry state, and Download Service. A production-shaped
F3 connection-pool experiment is still required before changing the driver.

---

## `comm_config.yml`

Benchmark-selected F3 streaming defaults for a nominal 25 Gbit/s network.
Pass the same file to both endpoints with `--f3-config`. The file is annotated
with all available options. Key defaults:

| Setting | Value |
|---------|-------|
| `streaming_chunk_size` | 1 MiB |
| `streaming_window_size` | 64 MiB (64 chunks) |
| `streaming_ack_interval` | 16 MiB |
| `streaming_retry_max_pending_bytes` | 128 MiB |

The receiver's out-of-sequence chunk limit is left unset so it is derived from
the effective window and chunk sizes. For these benchmark defaults, the derived
limit is 65 chunks.

Byte-size fields accept integer bytes or binary suffixes (`1K`, `1M`, `1G`).
