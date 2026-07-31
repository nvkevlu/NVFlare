# CS-OCI-ORD two-client 72B final readiness audit

Date: 2026-07-30

## Subsequent execution

The reviewed procedure subsequently passed as Slurm job `31158690` (`COMPLETED 0:0` in 28:13). The
[dated qualification report](cs-oci-ord-two-client-72b-qualification-2026-07-30.md) records the final topology,
training, aggregation, persistence, resource telemetry, and evidence boundaries. This audit remains the historical
pre-run readiness decision.

## Decision

No known software, configuration, model-identity, transport-size, GPU-memory, host-memory, scratch-capacity, or
stale-evidence blocker remains for the reviewed one-node, eight-A100 Qwen2.5-72B last-layer qualification.

This is a readiness decision, not a claim that an unexecuted hardware run has succeeded. The final run is authorized
only after the exact committed source passes the CPU control-plane gate, CPU sparse/export gate, four-GPU exact-model
capacity gate, and exact-commit login-node validator in the checked-in runbook. The partition's four-hour wall time
is an unavoidable outer limit. The wrapper requests `SIGTERM` for the job steps five minutes before that limit,
and Slurm may deliver it up to 60 seconds early; useful work should be assumed to stop when the step receives it.

## Missed-boundary audit and corrections

The final review traced configured values to the code that actually consumes them. It found and closed these gaps:

| Finding | Prior risk | Correction and proof |
| --- | --- | --- |
| Launcher final-result transfer | Exported config said 10,800 seconds, but the live launcher retained its 300-second constructor default | `last_result_transfer_timeout` is now applied to the launcher runtime and covered by unit tests |
| Subprocess tensor pull | Parent/client config said 10,800 seconds, but subprocess `ViaDownloader` could fall back to 600 seconds | Parent resolves the active `tensor_` setting, writes `TASK_EXCHANGE.download_req_timeout`, `ClientConfig` validates it, and the subprocess installs it as `FOBSContextKey.DOWNLOAD_REQ_TIMEOUT` before decoding its first task |
| Low-level F3 flow-control/read/send guards | ACK progress defaulted to 60 seconds; ACK wait and receiver read defaulted to 300 seconds; the optional socket driver defaulted to 30 seconds | The wrapper exports all four settings as 10,800 seconds, provisioning writes and rereads them in the server and both client `comm_config.json` files, qualification validates the environment before service startup, and the CPU artifact records both layers for final-readiness attestation |
| `streaming_max_peer_silence` | It could be mistaken for an active Phase-1 liveness guard | Documentation now labels it compatibility-only; active streaming-idle and low-level F3 settings provide the reviewed guards |
| CoreCell 3,600 seconds | It was described as a ceiling | Source audit confirmed it is a default only when no caller timeout is provided; explicit 10,800-second calls are not clamped |
| Slurm timing | Internal watchdogs could be mistaken for permission to run beyond the allocation | The runbook identifies four hours as the hard partition limit and the requested five-minute TERM notice, which may arrive up to 60 seconds early |

Invalid explicit subprocess tensor timeouts (`0`, negative, infinity, or NaN) now fail before launch instead of
surviving until an allocated training subprocess.

## Active timeout inventory

| Boundary | Reviewed value and semantics |
| --- | --- |
| CPU control-plane Slurm allocation | 15 minutes |
| Synthetic control-plane job | 180-second total timeout; CPU-only and exercised twice |
| CPU model/export preflight | 1 hour |
| Four-GPU exact-model gate | 2-hour allocation; TERM notice at five minutes; 7,200-second distributed process-group timeout |
| Final qualification | 4-hour partition maximum; job-step TERM requested five minutes before the limit and possibly delivered up to 60 seconds early |
| Service registration | 300 seconds |
| Admin login | 60 seconds; occurs before model loading and is exercised by the control-plane gate |
| 1.5B topology gate | 900-second absolute readiness plus 900-second post-ready inactivity |
| 72B target readiness | 7,200-second absolute clock from target submission |
| 72B post-ready stall | 1,800 seconds without recorded training, transfer, aggregation, or persistence progress |
| Client/tensor operation envelope | 10,800 seconds for external init, task exchange, runner sync, result submit/download, final result, and decomposer requests |
| F3 low-level guards | ACK wait, ACK-progress, receiver read, and optional socket send all pinned to 10,800 seconds in each provisioned config and the service environment; ACK progress and read are inactivity guards, ACK wait is an absolute blocked-window limit, and socket send is an absolute per-frame limit |
| Persistence | 7,200 seconds |
| External-process shutdown | 600 seconds; cleanup-only |
| START_JOB | 20-second RPC for an already-deployed client job; exercised twice with both required clients |
| Result retry | Three resends maximum; never unbounded |
| FedAvg task | No total application task timeout |

The target readiness clock is intentionally absolute. Before both clients are ready, incidental log activity does
not extend it. After both are ready, only recorded meaningful progress resets the inactivity clock. The four-GPU
gate's 2,400-second model-ready and 1,200-second post-ready thresholds are measured acceptance gates, not hidden
mid-operation kill timers; they provide evidence that a healthy final run has margin beneath Slurm's outer limit.

## Capacity and identity inventory

The wrappers, preflights, and readiness validator collectively fail closed on all of these values:

- exactly two clients with four ranks each on one node;
- GPUs 0–3 for site-1 and 4–7 for site-2;
- exactly eight `A100-SXM4-80GB` devices for the final run;
- Qwen2.5-72B revision `efba10c8e54e91e0d9570ab5f7b51a958474d4cb`;
- BF16 Qwen2 architecture: hidden 8,192, intermediate 29,568, 80 layers, 64 attention heads, and 8 KV heads;
- 37 indexed safetensor shards and exactly 145,412,407,296 tensor bytes;
- 12 selected final-layer tensors, 877,684,736 trainable parameters, and a 1,755,369,472-byte payload;
- individual largest tensor 484,442,112 bytes and aggregate trainable payload below the 2 GiB ceiling;
- at least 16 GiB of reserved GPU-memory headroom on every capacity-gate rank;
- 900 GiB for the four-rank capacity gate and 1,600 GiB for the final job;
- projected two-client rank RSS plus checkpoint bytes plus a fixed 128 GiB host reserve fitting 1,600 GiB;
- at least 50 GiB and 100,000 inodes on node-local scratch;
- exact model/container verification markers, exact Git commit in every gate artifact, the expected branch and release,
  and a clean working tree.

The server materializes only the selected final layer, not the immutable 72B base. The four client ranks at each site
load and shard the complete model with FSDP2 and perform real forward/backward/optimizer work.

## Operational acceptance

Do not submit from memory or manually reconstruct the command. Follow
`cs-oci-ord-two-client-72b-runbook.md` in order. A failed gate is diagnostic evidence and does not trigger an
automatic rerun. The success claim is allowed only after the final artifact proves two ready clients, two changed
site results, 2/2 aggregation, persistence completion, persisted-state mean verification, positive activity on all
eight GPUs, and no fatal marker in retained service or participant logs.
