# F3 reporting gap

This document describes the remaining production work for the `f3` field in
job resource statistics. It does not propose a new public record, transport,
or operator setting. The schema, one-final-report flow, normal `WORKSPACE`
archive, and job/study commands stay unchanged.

## Current production behavior

Production reports the following value for every participant:

```json
{"issues":["not_bound"],"status":"unavailable"}
```

This is deliberate, not a failed network measurement. There is no production
counter with trusted job and traffic-class ownership yet.

Two current hardcoded boundaries enforce that result:

1. `JobResourceCollector.finish()` writes `child_f3` as
   `unavailable/not_bound` in the private terminal handoff.
2. `assemble_participant_summary()` does not merge a child and parent F3
   snapshot. It creates the public `f3` value as `unavailable/not_bound` even
   if the rest of the child handoff is valid.

The standalone `f3_finalization.py` model and the complete schema examples are
design and test material. They are not connected to the production collector,
parent processes, or F3 send path. A reported F3 value in a golden fixture is
therefore not evidence that a live run measured it.

## What the field means

F3 reporting is selected logical payload accounting at the sender. It is not a
NIC byte counter, a receiver-delivery acknowledgement, or a complete measure of
wire utilization.

A reported participant value has three counter pairs:

- `remote_accepted`: an included remote send accepted by the local transport;
- `local_delivered`: an included direct in-process delivery; and
- `remote_failed_before_acceptance`: an included remote send that failed
  before local transport acceptance.

Each pair contains exact `payload_bytes` and `messages` values. The public JSON
uses canonical unsigned decimal strings. A zero message count requires zero
payload bytes.

Only `remote_accepted` contributes to job and study F3 totals. The other two
pairs explain participant behavior without being added to the primary traffic
total.

The payload length is observed after FOBS encoding and optional end-to-end
payload encryption. It excludes Cell headers, driver and TLS framing,
transport compression, and reliable-transport retransmissions. A successful
local send does not prove that the receiver processed or durably retained the
message.

Fan-out counts once per destination. Forwarding counts once per real sender
hop. For example, a job child sending to its parent and the parent relaying to
another endpoint are two distinct included hops. Deduplication must suppress
duplicate instrumentation and retransmission of one hop; it must not collapse
a genuine relay into the child send.

## Included and excluded traffic

The included classes are a closed allowlist owned by NVFlare:

| Class | Required binding |
| --- | --- |
| `task_request` | Hold the accepted request by trusted request correlation and commit it only when the paired response contains a real task. Empty polls and terminal or retry responses do not count. |
| `task_response` | Count only a platform-produced response containing a real task. |
| `task_result` | Bind the job in `Communicator.submit_update()` and count the result send; do not count its acknowledgement. |
| `job_application` | Bind the inner `train.deploy` operation in `JobRunner._make_deploy_message()`. The shared outer admin route is not sufficient authority. |
| `job_stream_data` | Register trusted job/class provenance when an included logical payload creates a stream, then count its logical data once per destination. |

The field excludes:

- empty task polling, `TRY_AGAIN`, and `END_RUN` responses;
- acknowledgements and protocol or stream-control traffic;
- reliable retransmissions and same-hop retries;
- bulk envelopes;
- workspace and result-workspace transfer;
- the terminal resource report itself;
- authentication, registration, heartbeat, shutdown, and job-heartbeat traffic;
- logs, HCI, and federated events; and
- every unknown or unbound route.

The low-level channel, topic, or a job-supplied header cannot assign an included
class. Classification must originate at an NVFlare call site that already owns
the trusted job operation.

## Events are not the F3 metric

NVFlare uses the word *event* for more than one concept:

- `FLComponent.fire_event()` invokes the local component event system. A local
  event does not by itself send a network message.
- `FLComponent.fire_fed_event()` asks `FedEventRunner` to send an auxiliary
  `fed.event` message to another site. That message travels through CellNet,
  but this F3 field explicitly excludes federated-event traffic.
- `JobTrafficEvent` in `f3_finalization.py` is only a prototype accounting
  value describing one candidate sender hop. It is not dispatched through the
  NVFlare event system and is not sent over CellNet.

CellNet/F3 is the communication infrastructure underneath many NVFlare
operations. The resource-statistics F3 field selects a small semantic subset
of that traffic; it must not total all CellNet messages or all framework
events.

## Missing production bindings

F3 pools and callbacks are process-local, while one participant can have a
parent process and a job process. Production therefore needs one scoped
counter in each contributing process.

| Owner or boundary | Required production work |
| --- | --- |
| Server parent (SP) | Create the trusted job counter after scheduling selects the job and before `_deploy_job()`, so deployment and later included forwarding are covered. |
| Client parent (CP) | Create the counter in `ClientExecutor.start_app()` after authoritative start metadata matches deployed metadata and before launcher selection or launch. Earlier deployment is an incoming SP send and is not counted again by CP. |
| Server and client job processes (SJ/CJ) | Create their process-local counters before included job traffic and freeze the result into `child_f3` during `_archive_results()`. |
| Task pull | Preserve the locally accepted request size until the reply proves that it was a real task; discard empty, retry, terminal, timeout, and error outcomes. |
| Task response and result | Assign job/class at the trusted command and communicator call sites, and exclude acknowledgements. |
| Deployment | Assign job/class from `_make_deploy_message()` rather than infer it from the shared admin route. |
| Included streams | Carry trusted provenance from the logical parent payload into a stream registry and count logical data once, not every `sm__DATA` retry frame. |
| CoreCell send outcome | After encoding and optional encryption, record remote acceptance, direct delivery, or failure for messages that already have trusted accounting context. |
| Parent assembly | Freeze the parent snapshot, merge it with the validated child snapshot using checked arithmetic, and pass the merged value into the existing participant report. |

This state is internal and keyed by existing trusted job lifecycle data. It
requires no launcher argument, environment variable, message field supplied by
job code, job setting, or operator configuration.

## Counter cutoff and merge

The F3 counter cutoff is separate from the later root-server cutoff for
accepting participant reports.

For a job process, teardown first stops admission of new application commands.
The child then freezes its counter once in `_archive_results()`, before F3
streaming shutdown and workspace upload. If a previously admitted callback is
still active at that boundary, the numeric contribution is useful but not
complete, so its status is `partial` with `counter_gap`. A callback that
linearizes after the freeze cannot change the canonical snapshot.

For CP and SP, the parent closes admission after the job handle finishes. It
allows already-classified sends to drain for at most five seconds, freezes once,
and then builds its participant report. Five seconds is an internal bound, not
configuration. A drain timeout keeps bounded numeric values as
`partial/counter_gap`; later completions remain diagnostic only. CP freezes
before sending the terminal resource report, so the report cannot count itself.

Parent assembly adds compatible child and parent buckets with checked unsigned
arithmetic:

- two complete snapshots produce `reported`;
- one useful snapshot plus a missing contribution produces `partial` with
  `attribution_incomplete`;
- a useful snapshot with an incomplete drain preserves its numbers as
  `partial/counter_gap`; and
- no useful snapshot produces `unavailable` rather than zero.

Child and parent contributions are added because they describe distinct
process-local sender hops. The merge does not deduplicate a parent relay against
the child send.

## Integration traps

### Generic StatsPool values are not a substitute

Current CellNet statistics mix protocol and application traffic, lack trusted
job/class ownership, use floating-point MiB observations, and have no atomic
job cutoff. Converting those pools back to bytes would not satisfy this field's
contract.

### Private message properties can disappear during cloning

`Message.set_prop()` creates a process-local attribute, but current Cell and
CoreCell fan-out paths construct new `Message` objects from only headers and
payload. An accounting property placed on the original object can therefore be
lost before `_send_to_endpoint()`.

Production should pass trusted accounting context explicitly through the send
and clone path, or copy a dedicated internal context deliberately. It must not
solve this by accepting a user-controlled wire header as authority. A forwarded
hop must be rebound or validated from trusted incoming route/stream provenance
before it is counted.

### The low-level route cannot classify task polls

`server_command/get_task` is both a real-task route and an empty polling route.
The request cannot be committed merely because CoreCell accepted it. Its size
must remain pending until the paired reply is classified. An unresolved entry
at cutoff is a coverage gap, not a real-task count.

### Stream retries must not become traffic inflation

Reliable streaming can send the same logical sequence more than once. Counting
every transport frame at `_send_to_endpoint()` would inflate the result. The
included stream must have trusted provenance and a stable logical hop identity,
with counting performed once per destination independently of retry dispatch.

## Recommended implementation order

1. Move the counter state machine into production, including explicit
   collecting, closing, and frozen states, checked arithmetic, atomic cutoff,
   and the three existing public buckets. Keep live output `not_bound` while
   production route coverage remains incomplete.
2. Add automatic SP, CP, SJ, and CJ counter ownership at the lifecycle hooks
   above. Prove zero-traffic processes produce reported zero counters rather
   than missing contributions.
3. Bind non-stream operations: deployment, task result, real task response, and
   deferred task-request pairing.
4. Add trusted included-stream provenance, fan-out accounting, forwarding
   ownership, and reliable-retry suppression.
5. Connect the encoded CoreCell send outcome to the appropriate scoped counter,
   preserving trusted context across message clones and direct delivery.
6. Wire child freeze, fixed parent drain/freeze, and checked parent/child merge
   into `assemble_participant_summary()`.
7. Add integration coverage for empty polling, timeouts, real tasks, ACK
   exclusion, deployment fan-out, direct delivery, forwarding, stream retry,
   duplicate instrumentation, active callbacks at cutoff, missing child
   handoff, parent drain timeout, and resource-report self-exclusion.
8. Remove the production `not_bound` hardcoding only after those proofs pass.
   Runtime gaps must remain typed partial or unavailable values rather than
   inferred traffic.

## Current code anchors

- Child hardcoding: `nvflare/private/fed/resource_stats/collector.py`,
  `JobResourceCollector.finish()`.
- Parent hardcoding: the same file,
  `assemble_participant_summary()`.
- Public fields and rollup: `nvflare/private/fed/resource_stats/contract.py`.
- Low-level encoded send boundary:
  `nvflare/fuel/f3/cellnet/core_cell.py`, `_send_to_endpoint()`.
- Forwarding boundary: the same file, `_forward()`.
- Task request/result call sites:
  `nvflare/private/fed/client/communicator.py`.
- Real-task reply decision:
  `nvflare/private/fed/server/server_commands.py`.
- Deployment binding:
  `nvflare/private/fed/server/job_runner.py`, `_make_deploy_message()`.
- Reliable stream creation/retry:
  `nvflare/fuel/f3/streaming/byte_streamer.py`.
- Child cutoff ordering:
  `nvflare/private/fed/app/job_process_cleanup.py` and the client/server
  `_archive_results()` callbacks.
- Design-only counter behavior:
  `research/runtime_resource_proxy_prototype/f3_finalization.py`.
- Detailed audited route table:
  `research/runtime_resource_proxy_prototype/CURRENT_CODE_INTEGRATION.md`.
