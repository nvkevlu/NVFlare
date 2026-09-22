# F3 implementation and validation status

This document defines the Phase 1 `f3` value and maps it to the implementation
in this branch. The filename is retained because earlier reviews linked to it,
but F3 is no longer only a proposed gap.

The implementation uses existing NVFlare processes and messages. It adds no
privilege, service, mount, launcher argument, environment variable, job
setting, or operator configuration.

## The public value

A participant reports one counter pair:

```json
{
  "status": "reported",
  "remote_accepted": {
    "payload_bytes": "12582912",
    "messages": "3"
  }
}
```

`remote_accepted` means that the local transport accepted an included logical
send to a remote destination. It does not mean that the receiver processed or
durably stored the message.

Both counters are canonical unsigned decimal strings bounded to U128.
`messages` counts logical operations, not Cell frames or stream chunks. A
reported zero message count therefore requires zero payload bytes.

A final in-process delivery to the logical destination and a send that fails
before local transport acceptance do not enter the public value. They are also
not published as separate diagnostic buckets.

## Exactly what is counted

The allowlist has three classes:

| Class | Trusted origin | Included operation |
| --- | --- | --- |
| `job_application` | Server parent (SP) | One deployment send to each selected remote client. |
| `task_response` | Server job process (SJ) | A response that contains a real task. `TRY_AGAIN`, `END_RUN`, errors, and empty responses are excluded. |
| `task_result` | Client job process (CJ) | A submitted task result. Its acknowledgement is excluded. |

There is no `task_request` class. Poll requests are frequent and add little
meaning once real task responses are counted. There is also no separate
stream-data class. Large-object bytes created by an included operation belong
to that operation's existing class.

Classification happens only at the NVFlare call site that owns the operation.
A Cell channel, topic, wire header, relaying process, or value supplied by job
code is not classification authority.

## Message and byte rules

For each included operation:

- count once per remote destination;
- count one message for the top-level logical send;
- measure the main payload after FOBS encoding and before optional end-to-end
  encryption;
- if FOBS replaces large data with a `DownloadService` reference, add the
  successfully accepted source data bytes to the same logical operation;
- do not add another message for those out-of-band bytes; and
- do not count retries or repeated delivery of the same logical chunk again.

This boundary includes the serialized application payload. It excludes Cell
headers, encryption expansion, driver and TLS framing, transport compression,
and lower-layer retransmissions.

Only the process that originates the trusted semantic operation may count it.
An intermediate process that forwards the already classified payload does not
count another send. The accounting context is a local Python object and is
never serialized as a header, so it cannot grant authority to a remote or
forwarding process. If the remote logical destination is reached through a
local first-hop relay, the origin still counts its logical send once; only the
relay's duplicate contribution is excluded.

## Explicit exclusions

Phase 1 excludes:

- task-poll requests;
- `TRY_AGAIN`, `END_RUN`, empty, timeout, and error task responses;
- task-result acknowledgements;
- final in-process delivery to the logical destination;
- sends that fail before local transport acceptance;
- an additional relay or forwarding contribution;
- `DownloadService` control requests and retry duplication;
- workspace and result-workspace transfer;
- the terminal resource report itself;
- authentication, registration, heartbeat, shutdown, job-heartbeat, log, HCI,
  and federated-event traffic;
- bulk or protocol envelopes that are not one of the three trusted semantic
  operations; and
- every unknown or unbound route.

Generic CellNet `StatsPool` values cannot replace this counter. Those values
mix application and protocol traffic, lack trusted job/class ownership, use a
different numeric representation, and do not share this job cutoff.

## Where the implementation binds the operation

The branch now binds the three operations at their semantic owners:

| Operation | Binding |
| --- | --- |
| Deployment | `JobRunner` supplies its job-scoped server-parent counter when it sends the existing deploy requests. |
| Real task response | After producing a real task response, the job-process command path attaches accounting and pre-admits the known SJ-origin/requester-destination pair before its callback returns. |
| Task result | `Communicator.submit_update()` attaches the client job-process counter before sending the result. |

The low-level F3/Cell path then performs the common work:

1. preserve the process-local accounting context across deliberate message
   clones;
2. admit at most one logical send for an origin and destination, either at the
   trusted task-response callback barrier or lazily in transport;
3. FOBS-encode the payload and retain that encoded size without counting it yet;
4. optionally encrypt only after the size has been retained;
5. complete the counter only when the remote send is locally accepted; and
6. abandon the admission when acceptance fails.

The exact boundary depends on which existing send path carries the encoded
payload:

- For a normal CoreCell send, `_send_to_endpoint()` FOBS-encodes first, reuses
  an owner pre-admission or lazily admits the operation, records the encoded
  size, optionally encrypts, and calls the communicator. A remote send that
  returns without an error completes the
  admission. It abandons only an error or a final local delivery where the
  chosen endpoint is the logical destination. A local first-hop endpoint for a
  different remote destination still completes the origin's one logical send.
- For a Cell blob stream, `ByteStreamer.send()` receives the already
  FOBS-encoded `BlobStream`. It admits once for the origin and destination
  immediately before constructing and starting `TxTask`. A final process-local
  target is not admitted; a remote logical target remains admitted even when
  routing starts through a local relay. A setup/start exception abandons the
  admission. Otherwise the admission remains pending for the whole
  `StreamFuture`: terminal success commits `stream.get_size()` once, while an
  asynchronous error or cancellation abandons it. Per-frame sends and reliable
  retries carry no accounting context, so they cannot add messages or bytes.

FOBS `DownloadService` transactions register with the logical-send context
during main-payload encoding, before the main transport attempt. The
task-response owner admission may already exist at this point. Each
source data reply gets a stable source-owned chunk identity. Its raw produced
data length is added only after that reply is locally accepted, and the same
logical chunk cannot add bytes again on a retry. The main operation completes
only when its main send was accepted and every registered transaction reports
success for that destination. A failed transaction, unknown receiver, unstable
chunk identity, or ambiguous settlement discards the affected operation and
marks the snapshot `partial/counter_gap`; it never publishes a known
undercount.

Accounting is observational. Callback or bookkeeping failures must not alter
the real application send.

The steady-state cost is confined to in-process bookkeeping for the three
included operations: a small number of lock/condition and per-destination map
operations around the payload that FOBS already produced. It adds no network
message, polling thread, subprocess, per-send filesystem write, or second FOBS
serialization. The only resource-statistics file write remains the terminal
handoff.

`DownloadService` retry identity is also bounded. Accounting canonicalizes
ordinary request state with limits of 16 levels, 4,096 nodes, and 64 KiB of
scalar data, then uses that immutable key directly in the logical operation's
existing hash sets. This replaces repeated linear scans, unbounded deep copies,
and a duplicate per-transfer ledger with one bounded traversal and average
constant-time lookup. Unsupported, cyclic, or over-limit state leaves the real
transfer unchanged and marks the affected F3 operation
`partial/counter_gap`.

## Counter owners and cutoff

One participant can span a parent process and a job process, so each process
has its own counter:

- SP owns deployment accounting;
- SJ owns real task-response accounting;
- CJ owns task-result accounting; and
- CP owns a job-scoped counter even when the selected Phase 1 operations give
  it no positive contribution.

CJ and SJ start their counters before custom imports are enabled. CP and SP
start counters from existing trusted job lifecycle state. No identity or class
is passed through a new launcher argument or environment variable.

At terminal finalization, each counter follows the same one-way lifecycle:

```text
collecting -> closing -> frozen
```

Child cleanup first closes application-command admission and waits up to five
seconds for already admitted command callbacks while Cell and streaming remain
alive. This prevents a callback from originating new F3 traffic after
publication. A timeout or error marks `counter_gap`. The child then closes F3
admission, gives its admitted logical sends their fixed five-second drain, and
freezes once before transport shutdown. If the callback pre-drain failed,
cleanup still performs one bounded post-stop callback wait before closing
security state.

Parent cleanup has no child command-callback gate and does not wait. It closes
F3 admission and freezes immediately after the job handle finishes. This is
safe for the current allowlist: CP originates no included class, and SP's
blocking deployment sends finish during deployment. A parent operation still
pending at cleanup is therefore an instrumentation gap, not useful work to
delay terminal publication for; it produces `partial/counter_gap`.

Neither child wait is an unconditional five-second sleep. Both use condition
variables and return immediately when the active or pending count is zero.
They run only during job-process terminal cleanup and do not poll during normal
execution. Parent finalization has no F3 wait, so an anomalous parent admission
cannot hold the server's serial completion loop or another job's terminal
publication.

The two child waits are sequential, so a pathological active callback followed
by a pending F3 operation can add at most ten seconds before handoff
publication. If the callback pre-drain failed, the existing post-stop callback
wait can add at most five more seconds to that child process's exit; it occurs
after publication. Normal cleanup has zero wait at both conditions. The current
resource-time final reading includes the actual pre-drain and F3-drain tails,
but not the post-stop wait.

A real task-response callback returns its `Message` before CellNet starts the
send. The trusted binding therefore pre-admits its known origin/destination
pair before the callback returns. The later transport path reuses that same
admission and supplies the post-FOBS byte count and terminal outcome. This
small barrier closes the callback-return/send-start race without counting
early or blocking the callback.

The child freezes first and writes `child_f3` into the existing private
`terminal_handoff.json`. After the job handle completes, the parent closes and
freezes its counter, validates the child handoff, and performs a checked
parent/child merge:

- two complete snapshots produce `reported`;
- a useful subtotal plus a missing contribution produces
  `partial/attribution_incomplete`;
- a counter gap preserves bounded numeric values as `partial/counter_gap`;
- malformed arithmetic fails closed; and
- no usable numeric contribution produces `unavailable`, never a guessed
  zero.

The merge combines non-overlapping semantic origins. It does not add another
contribution for a relay.

The parent freezes before it constructs and sends the terminal resource
report. The report therefore cannot count itself. If a server job is restored,
the new counter keeps its post-restore subtotal but marks prior history
`partial/attribution_incomplete`.

## Events are not the metric

NVFlare uses *event* for several concepts. None is a substitute for this
sender counter:

- `FLComponent.fire_event()` is local component dispatch and does not itself
  send a network message.
- `FLComponent.fire_fed_event()` sends auxiliary `fed.event` traffic, which is
  explicitly excluded.
- Prototype `JobTrafficEvent` objects are test inputs, not NVFlare events or
  CellNet messages.

CellNet is the communication layer used by the selected operations. The F3
field counts only the three semantic operations above, not all CellNet or
event traffic.

## Validation status

The production implementation is present in this worktree. The current focused
and socket-backed suites pass. They cover counter state and merge, semantic
bindings, fan-out, cloning,
pre-encryption sizing, streamed terminal success/failure, `DownloadService`
folding and retry suppression, exact final-local versus local-relay behavior,
child callback pre-drain, cutoff, restore, and terminal-report self-exclusion.

The remaining evidence is a new process-mode end-to-end run. That run should
replace the earlier historical `unavailable/not_bound` F3 artifact with a live
reported result; it does not require another schema redesign.

The checked-in Colossus runs predate this implementation. Their exact
`unavailable/not_bound` F3 values remain useful historical evidence and are
intentionally unchanged. No new process-mode or Colossus live F3 reference has
yet replaced them.

An uncovered runtime path must produce `partial` or `unavailable` data. It
must not fall back to generic network statistics or claim a complete zero.

## Code anchors

- Counter and cutoff: `nvflare/private/fed/resource_stats/f3_counter.py`
- Per-job counter ownership:
  `nvflare/private/fed/resource_stats/f3_job_counter.py` and
  `f3_registry.py`
- Trusted binding helper: `nvflare/private/fed/resource_stats/f3_bindings.py`
- Local logical-operation context and clone preservation:
  `nvflare/fuel/f3/send_accounting.py` and `nvflare/fuel/f3/message.py`
- FOBS/pre-encryption send boundaries:
  `nvflare/fuel/f3/cellnet/core_cell.py`,
  `nvflare/fuel/f3/streaming/blob_streamer.py`, and
  `nvflare/fuel/f3/streaming/byte_streamer.py`
- Large-object folding:
  `nvflare/fuel/f3/streaming/download_service.py` and
  `nvflare/fuel/utils/fobs/decomposers/via_downloader.py`
- Task bindings: `nvflare/private/fed/client/communicator.py` and
  `nvflare/private/fed/server/server_command_agent.py`
- Deployment binding: `nvflare/private/fed/server/job_runner.py` and
  `nvflare/private/fed/server/message_send.py`
- Child handoff and checked merge:
  `nvflare/private/fed/resource_stats/collector.py`
- Child and parent lifecycle hooks:
  `nvflare/private/fed/app/client/worker_process.py`,
  `nvflare/private/fed/app/server/runner_process.py`,
  `nvflare/private/fed/client/client_executor.py`, and
  `nvflare/private/fed/server/job_runner.py`
