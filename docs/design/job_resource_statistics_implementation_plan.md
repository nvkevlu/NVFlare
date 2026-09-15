# NVFlare Phase 1 Runtime-Visible Resource Statistics — Implementation Plan

**Status:** The candidate-v1 data contract and review artifacts are concrete and ready for design
review. Production collectors, launcher wiring, durable handoff, server materialization, and CLI
integration do not yet exist.

For a meeting-oriented walkthrough, start with the
[linear review guide](../../research/runtime_resource_proxy_prototype/REVIEW_GUIDE.md). The
[candidate decision record](../../research/runtime_resource_proxy_prototype/SIMPLIFICATION_REVIEW.md)
explains the reductions that produced this plan. The normative candidate is the
[schema bundle](../../research/runtime_resource_proxy_prototype/schema/README.md).

## 1. Outcome and boundary

Phase 1 records facts that an NVFlare participant can observe under ordinary user permissions.
The contract deliberately separates two lifecycles:

- a **logical participant lifecycle**, owned by a durable, GPU-free site supervisor and spanning
  checkpoint/resume, aggregation, barriers, downloads, and zero or more compute allocations; and
- a **resource-window lifecycle**, spanning one stable vector of transient CPU, memory, and GPU
  capacity.

For the logical participant, Phase 1 records persistent run-filesystem capacity at participant
start and finalization, exact bytes in platform-registered retained result files, and all-job F3
application payload counters. For each resource window, it records CPU, memory, and GPU capacity
after acquisition, an optional final capacity observation before closure, and the trusted time at
which the supervisor observes that the stable-capacity window has closed.

These are **runtime-visible proxies**, not utilization, ownership, guaranteed capacity, price,
cost, or billable usage. Process, Docker, Kubernetes, and Slurm use one definition: observe CPU,
memory, and GPU from inside the transient resource-bearing environment after its allocation is
active. Phase 1 uses a trusted supervisor closure event to delimit that stable-vector window; it
does not reinterpret launcher specifications, scheduler allocation quantities, cloud metadata,
or billing data as capacity measurements.

This boundary is compatible with the
[roadmap's time-bounded allocation model](../roadmap.rst). An attempt is not necessarily a whole
allocation: any change to the counted CPU/memory/GPU vector closes it and immediately opens a
successor if some counted compute resources remain held. For example, releasing only a GPU closes
the GPU-bearing attempt with reason **reconfigured** and opens a CPU/memory-plus-zero-GPU attempt.
Only an interval in which all counted compute resources are released has no attempt and adds zero
CPU, memory, and GPU resource-time. Persistent storage and job traffic can continue through either
kind of interval because they follow the logical participant lifecycle.

Participant-visible views can overlap on shared CPU, memory, filesystems, or GPUs. Cross-job
overlap is intentionally retained. A downstream estimator decides whether these qualified facts
are useful; NVFlare does not deduplicate them into physical capacity.

The shared supervisor's own CPU and memory overhead is excluded from this per-job compute proxy.
Explicitly excluded from Phase 1 are CPU/GPU utilization, memory peaks, storage occupancy
polling, generic OS I/O/network, generic network, privileged host agents, cost, carbon, and
cross-job aggregation. Phase 2 publication is discussed separately in the
[telemetry sketch](job_resource_statistics_phase2_telemetry_sketch.md).

Collection and persistence failures never change the federated job result. They produce an honest
status or roster gap while unaffected facts remain usable.

## 2. End-to-end flow

~~~text
durable GPU-free site supervisor begins logical participant lifecycle
  -> participant start records persistent run-filesystem capacity
  -> supervisor confirms resource acquisition, records opened_at, and mints attempt identity
  -> sanitized resource-worker bootstrap runs before job custom imports
  -> resource worker reports CPU + memory + GPU capacity after acquisition
  -> supervisor authenticates and immediately stores accepted bytes durably
  -> resource worker optionally reports a final capacity snapshot before the window changes
  -> supervisor records attempt_end.closed_at after release/reconfiguration is confirmed
  -> successor opens immediately when a counted vector remains; otherwise a no-attempt gap begins
  -> zero or more open / run / reconfigure-or-release cycles repeat
  -> participant final records storage + retained content + all-job F3 exactly once
  -> supervisor constructs one detailed participant summary
  -> server accepts the first valid immutable participant summary by a fixed cutoff
  -> server derives compact participant and job totals over a fixed expected-participant roster
  -> server writes resource_summary.json + participant files + path/digest manifest
  -> exact resource_summary.json becomes the RESOURCE_STATS query copy
  -> finalized CLI/API reads the persisted result
~~~

The resource worker's attempt start/final capacity snapshots remain self-reports and carry no
duration timestamps. Authenticated immediate
handoff and write-once supervisor storage prevent later job-side mutation of accepted bytes; they
do not make worker observations independently attested. Participant storage, registered-artifact
freeze, atomic F3 counter freeze, **opened_at**, and **end.closed_at** use the durable
supervisor/lifecycle-owner clock. Aggregate totals are server-derived.

For a client participant, only the terminal participant summary crosses the site-to-server
boundary for resource statistics. "Sent once at the end" refers to that central submission, not
to local durability: each attempt fragment is handed to the site supervisor immediately, and
normal task/heartbeat traffic continues independently throughout the job. The server participant
uses the same lifecycle contract under the server parent/job supervisor, but its terminal summary
is accepted through local durable ingestion rather than a fictitious remote send. Role remains
**client | server** only in the fixed roster.

## 3. Candidate-v1 records

Every record has exact **schema_version: "1.0"**, one namespaced kind, and no unknown fields.
The eight kinds are:

| Kind | Purpose |
| --- | --- |
| nvflare.resource_stats.participant_start | Supervisor-observed logical-participant startup storage. |
| nvflare.resource_stats.participant_final | Supervisor-owned final storage, retained-content, and F3 observation. |
| nvflare.resource_stats.attempt_start | Resource-worker CPU, memory, and GPU snapshot after the supervisor opens a window. |
| nvflare.resource_stats.attempt_final | Optional resource-worker capacity self-report before closure. |
| nvflare.resource_stats.attempt_end | Supervisor-observed stable-window closure after release, failure, or reconfiguration. |
| nvflare.resource_stats.participant_summary | Detailed lifecycle facts for one accepted participant. |
| nvflare.resource_stats.resource_summary | Fixed expected-participant roster with compact participant and job totals. |
| nvflare.resource_stats.manifest | Canonical path/digest inventory. |

Unknown versions are rejected. The exact shapes, bounds, and privacy rules are indexed in the
[field catalog](../../research/runtime_resource_proxy_prototype/schema/FIELD_CATALOG.md); status
and issue rules are in the
[status catalog](../../research/runtime_resource_proxy_prototype/schema/CODE_CATALOG.md).

### 3.1 Participant and attempt identity

Participant lifecycle records carry:

~~~text
schema_version, kind, job_id, participant_id, observed_at
~~~

Resource-window lifecycle records additionally carry **attempt_id** and **environment_key**.
The supervisor creates a random 32-lowercase-hex attempt ID whenever a stable resource vector
opens. Participant and environment keys are job-scoped platform HMAC-SHA-256 values, not plain
hashes of enumerable labels. Payload identity is always checked against authenticated
supervisor/roster context.

An attempt is exactly one half-open interval of one stable `(resource lease, reporter environment,
CPU/memory/GPU vector)`. Its duration is
set exclusively by the lifecycle owner's **opened_at** and **end.closed_at** clock. Opening occurs
as soon as acquisition is confirmed, before sanitized bootstrap and capacity probing, so bootstrap
time is included. Worker start/final snapshots do not own timestamps and cannot shorten the
window.

Normal checkpoint/resume, per-round release, or partial resource reconfiguration can therefore
produce multiple attempts; attempts are not limited to errors, retries, or process crashes. If
only GPU is released while CPU/memory remain held, the old vector ends as **reconfigured** and a
CPU/memory-plus-zero-GPU successor opens at the exact same lifecycle-owner timestamp.

The environment key identifies the trusted reporter lease boundary. Within one job, attempts
that use the same environment key may be sequential but their half-open resource windows may not
overlap, even across participant/rank files. This prevents duplicate rank reports without
mistaking a later allocation for duplication. It does not deduplicate different jobs.

One scheduler allocation may expose several concurrent reporter environments, each with its own
attempt and environment key. Their intervals are deliberately summed rather than collapsed; the
result is participant-visible environment time and may exceed wall time.

Role is not repeated in lifecycle or participant records. It appears once on each fixed server
roster entry.

### 3.2 Resource-window capacity

An accepted attempt start and every accepted attempt final contain:

~~~json
{
  "cpu": {
    "status": "reported",
    "visible_units": "1.5",
    "model": "AMD EPYC 9654",
    "architecture": "x86_64",
    "evidence": {
      "affinity_count": "4",
      "cpuset_count": "4",
      "quota_units": "1.5"
    }
  },
  "memory": {
    "status": "reported",
    "visible_bytes": "8589934592",
    "evidence": {
      "physical_bytes": "68719476736",
      "cgroup_limit_bytes": "8589934592"
    }
  },
  "gpu": {
    "status": "reported",
    "cuda_mask_present": true,
    "groups": [
      {
        "kind": "full_gpu",
        "count": "1",
        "model": "NVIDIA H100 80GB HBM3",
        "memory_bytes": "85899345920"
      }
    ]
  }
}
~~~

Typed location fixes meaning and unit. Records do not repeat metric names, unit, basis, scope,
sharing, source, coverage, caveats, warnings, qualifications, or a timestamp per value.

Point capacity uses **reported | unavailable | error**. Reported requires the typed value and
its required evidence. Unavailable/error has no numeric field and carries one to four applicable
issues. A numeric zero is never substituted for missing collection.

The eight issue values are:

~~~text
not_bound, counter_gap, observation_incomplete, attribution_incomplete,
unsupported, permission_denied, dependency_missing, malformed_source
~~~

Only source observations retain issues. Compact totals have status but no issue list; their
explanation derives from lifecycle and roster facts.

### 3.3 CPU and memory selection

CPU visible units are the minimum of the available strong selectors:

- process affinity count;
- effective cgroup cpuset count; and
- finite cgroup quota already normalized to CPU units.

If none is usable, online logical CPUs are an explicit host-visible fallback. Canonical evidence
stores only **affinity_count**, **cpuset_count**, **quota_units**, or the mutually exclusive
**online_count** fallback. `quota_units` is the exact quota/period ratio rounded down to at most
nine fractional decimal digits; flooring avoids overstating visible capacity. Low-level quota
inputs remain inside the probe and are not persisted.

Memory visible bytes are the smaller finite value among effective cgroup memory and physical RAM.
Swap is excluded; an unlimited cgroup value is omitted. Physical-only evidence is a host-visible
fallback.

CPU and memory here belong only to the transient resource-bearing worker. The durable
supervisor's shared control-plane overhead is not attributed to every logical job.

### 3.4 GPU authority and optional metadata

A numeric GPU inventory requires successful CUDA-runtime enumeration. The visibility-mask value
and token count are forbidden; **cuda_mask_present** is diagnostic only. If CUDA enumeration is
unavailable or fails, Phase 1 emits no numeric GPU count even if a mask exists.

Reported GPU groups have positive counts and remain separated as **full_gpu** or
**mig_compute_instance**. An empty reported group array is a successful zero. Within a reported
inventory, absence of a kind means zero for that kind, so a normal non-MIG client has no MIG
field or row. Full GPUs and MIG instances are never combined into a generic GPU total.

CUDA device properties can supply normalized model and per-entity memory. `memory_bytes` means
the runtime-reported memory of each visible entity in that group; entities with different values
form separate groups. NVML may refine metadata only for devices already matched to the
CUDA-visible inventory; it cannot add a device or change the count. MIG profile is optional and
legal only on a MIG group.

CPU/GPU model metadata is optional infrastructure fingerprinting. Site policy may suppress
model, architecture, per-entity memory, and MIG profile without changing numeric status. A CPU
model is reported only when every affinity-visible processor normalizes to one model. A
heterogeneous set omits it. Never persist raw cpuinfo, CPU flags/topology/serials, GPU UUID/PCI
identity, raw command output, or host/container/pod identity.

### 3.5 Participant storage lifecycle

Participant start and participant final each contain one typed storage observation.
**capacity_bytes** is the total returned by statvfs for the filesystem containing the persistent
job run directory. Free space, filesystem class, and absolute path are not persisted.

Storage-capacity time spans participant start through participant final, including GPU-free
aggregation, download, barrier, and resume gaps, because the run filesystem persists across
those gaps. It is calculated once for the participant rather than once per resource window. The
final storage observation is change evidence; the startup value remains the multiplication
basis. This formula requires the supervisor to guarantee that the workspace remained continuously
available across release/resume; otherwise the result is partial or unavailable. This is
filesystem-capacity time, not retained content or storage occupancy.

### 3.6 Attempt final, participant final, retained content, and F3

A valid resource-worker attempt final retains a second CPU, memory, and GPU capacity object just
before the resource window closes. It is optional audit/change-detection evidence; it neither
defines the interval endpoint nor carries a timestamp or participant-lifetime output facts. The
trusted supervisor's **opened_at** and **end.closed_at** define the interval.

The participant final contains the second storage observation plus retained-content and F3 facts
in one **observed_at** participant-final observation. These facts occur exactly once per logical participant, not once
per resumed compute allocation. This avoids duplicate retained files and fragmented traffic
counters when a normal job releases and reacquires GPUs many times.

Retained content uses **reported | partial | unavailable | error**. Reported/partial contains
sorted registered-file entries:

~~~json
{"relative_path": "result/model.pt", "size_bytes": "18874368", "sha256": "..."}
~~~

The total is derived from entry sizes. Only frozen regular files explicitly registered with the
platform are included. The workspace/archive is not swept. Files created by several resource
windows are frozen once at participant finalization.

F3 has one status and three counter pairs when reported or partial:

| Bucket | Meaning |
| --- | --- |
| remote_accepted | Remote application payload accepted by transport before the participant-final counter freeze; the primary F3 total. |
| local_delivered | Direct/local delivery, kept separately. |
| remote_failed_before_acceptance | Remote traffic that failed before sender acceptance. |

Every pair contains canonical integer-string **payload_bytes** and **messages**. Zero messages
requires zero bytes. Included v1 traffic classes are exactly **task_request, task_response,
task_result, job_application, and job_stream_data**. **job_stream_control, bulk_envelope,
workspace_transfer, platform_control, log_export, unknown classes, and resource-summary
publication** are excluded.

For each destination send or direct delivery, count one message and `len(message.payload)` after
`encode_payload` and optional end-to-end `encrypt_payload`, immediately before
`_send_direct_message` or `Communicator.send`. Headers, SFM/driver framing, TLS/network headers,
compression effects, and retransmissions are excluded. Fan-out therefore counts once per
destination. A forwarded message counts again at each participant sender hop: these are hop
traffic totals, not unique logical-data totals. **remote_accepted** increments only when the send
returns accepted; direct delivery increments **local_delivered** instead.

Before serializing participant final, the durable participant owner atomically freezes all three
canonical counters. Counter callbacks that complete after that freeze are ignored for canonical
totals. The class filter, sender-acceptance point, atomic-freeze behavior, and non-spoofable
summary-publication exclusion are fixed v1 platform behavior, not job-controlled or serialized
counters. Excluded summary traffic cannot be counted inside the summary that causes it without
circularity. Failure bytes are retained only when post-serialization size is known. F3 binds to
logical job identity, so traffic while no GPU is held still belongs to the participant total.

### 3.7 Attempt end and crash behavior

Attempt end is a compact supervisor observation:

~~~json
{
  "opened_at": "2026-09-09T14:00:00Z",
  "closed_at": "2026-09-09T14:05:42.6Z",
  "reason": "released"
}
~~~

Reasons are **released | reconfigured | failed | terminated | launch_failed**. This fact describes
closure of one stable capacity vector, not necessarily an entire allocation or exit of a
particular operating-system process. The
contract therefore does not depend on whether the roadmap implementation restarts a Client Job,
cycles a worker beneath a durable Client Job, or resumes through a time-bounded Slurm allocation.

The supervisor records attempt end only after it observes that release or reconfiguration has
taken effect. For **reconfigured**, the trusted lifecycle authority asserts an immediate
same-environment successor at the exact boundary, so a GPU-only release does not erase still-held
CPU/memory time. When both capacity snapshots are comparable, they must differ; an unavailable
successor snapshot is still representable and makes affected totals partial or unavailable. When
a valid attempt final is absent, the system does not invent one. Start capacity can still be
multiplied across the trusted window, but the affected derived resource time is partial.

That implication is one-way: every **reconfigured** end requires the lifecycle-authority successor
at `closed_at`, and equal comparable snapshots are invalid, but a fully **released** lease may be
reacquired at the same timestamp and may expose a different vector. Timestamp adjacency alone
does not turn a full release/reacquire into reconfiguration.

If launch fails after resource acquisition, the attempt still has supervisor-owned **opened_at**
and **end.closed_at**, but no worker start/final snapshot. Its duration contributes to
**resource_window_seconds**, while CPU/memory/GPU totals become incomplete: partial when another
window contributes numeric capacity, otherwise unavailable.

### 3.8 Participant summary, time formulas, and replay

The participant file is deliberately small in structure:

~~~json
{
  "schema_version": "1.0",
  "kind": "nvflare.resource_stats.participant_summary",
  "job_id": "job-20260909-001",
  "participant_key": "sha256-...",
  "start": {"observed_at": "...", "storage": {}},
  "attempts": [
    {
      "attempt_id": "...",
      "environment_key": "sha256-...",
      "opened_at": "...",
      "start": {"capacity": {}},
      "final": {"capacity": {}},
      "end": {"closed_at": "...", "reason": "released"}
    }
  ],
  "final": {"observed_at": "...", "storage": {}, "retained_content": {}, "f3": {}}
}
~~~

Participant start/final occur once. An attempt start/final snapshot applies only to that stable
compute vector; attempt final is optional and end is required. An attempt final requires an
accepted start. Launch failure has **opened_at** and end but no snapshots. Disabled collection is represented by
the server roster rather than an accepted participant file. Attempts are sorted by unique attempt
ID and may be empty for a participant that performed no resource-bearing work.

The participant file stores no worker rollup, duration, role, trust declaration, summary ID, or
revision. The supervisor/server derives resource time on the appropriate lifecycle:

~~~text
compute resource time = attempt-start CPU/memory/GPU capacity
                      × (end.closed_at − opened_at)

storage-capacity time = participant-start storage capacity
                      × (participant-final observed_at − participant-start observed_at)
~~~

Products use decimal arithmetic, round half-even once to at most nine fractional digits, and
then sum. A missing attempt final or changed numeric attempt final makes the affected compute
result partial. A changed final storage value makes storage time partial. Startup is not averaged
with an endpoint sample. Optional metadata change alone is not a capacity change.

Only intervals after all counted compute resources are released have no attempt and contribute
zero compute resource-time. A GPU-only release instead creates an immediate zero-GPU successor,
so GPU time stops while still-held CPU/memory time continues. Full-release gaps remain inside
participant storage time and may contain F3 traffic. The sum of attempt intervals may be shorter
than wall-clock participant duration across a true gap or exceed it when reporter environments
overlap. For one non-overlapping environment it equals wall time while at least one counted
compute resource remains continuously held.

There is no participant revision protocol. The first valid authenticated participant summary
received by **report_cutoff_at** wins. An identical digest retry is an idempotent no-op; a
different digest is a conflicting replacement and is rejected. An invalid candidate does not
reserve the slot. Distinct stable-capacity windows remain separate attempts inside the one
immutable summary. Multiple attempts are expected during normal GPU reconfiguration or
release/resume operation and do not
imply a retry.

All measured/derived values are canonical decimal strings. Resource time, retained bytes, F3
counters, and aggregate resource-window seconds are bounded by U128. This avoids loss beyond
JavaScript's safe-integer range; the golden large-value records make that case concrete.

### 3.9 Compact server summary

The server obtains expected participant identity and **client | server** role from authenticated
job-selection/deployment state, independently of resource-report arrivals. At the report cutoff it
snapshots that membership as the immutable expected-participant roster and classifies every slot;
received summaries can never define the roster and thereby hide a missing participant. Every
entry has participant ID, job-scoped participant key, role, and **accepted | missing | invalid |
disabled**. Accepted entries also have **received_at**,
**summary_sha256**, **resource_window_seconds**, and flat **totals**. Invalid entries retain
**received_at** and a compact issue list. Missing/disabled entries add nothing.

**resource_window_seconds** is a checked convenience: the sum of that participant's accepted
resource-window intervals, not a second clock measurement or the logical job duration. It can
exceed wall time when distinct reporter environments run concurrently.

Accepted-participant totals and job totals use the same flat shape:

~~~json
{
  "cpu": {"status": "reported", "groups": [{"model": "...", "architecture": "x86_64", "unit_seconds": "720"}]},
  "memory": {"status": "reported", "byte_seconds": "4123168604160"},
  "storage": {"status": "reported", "byte_seconds": "527765581332480"},
  "gpu": {"status": "reported", "groups": [{"kind": "full_gpu", "model": "...", "instance_seconds": "180"}]},
  "retained_content": {"status": "reported", "bytes": "18874368"},
  "f3": {"status": "reported", "remote_accepted": {"payload_bytes": "5632", "messages": "2"}}
}
~~~

This example has three contiguous stable-vector windows over 480 seconds: GPU-bearing for 60
seconds, CPU/memory with a reported zero-GPU inventory for 300 seconds, and GPU-bearing again for
120 seconds. One GPU therefore contributes 180 instance-seconds, while 1.5 CPU units contribute
720 unit-seconds and 8 GiB of memory contributes across all 480 seconds. Storage also spans the
480-second participant lifecycle. The middle interval is GPU-free, but it is not an all-resource
gap because CPU and memory remain held.

Total status is **reported | partial | unavailable**. Missing/invalid/disabled roster members or
degraded attempt facts make an otherwise numeric total partial. No numeric contributors means
unavailable. CPU groups retain optional model/architecture; GPU groups retain kind and optional
model/memory/profile. Suppressed or unknown metadata forms an unlabeled group.

The roster is the single coverage source. Expected/reported counts, coverage, contributor lists,
warnings, units, and explanatory qualifications are derived, not stored beside every total.

## 4. Trusted bootstrap and launcher integration

Capturing before worker_process.main() is insufficient: a launcher-provided PYTHONPATH can load
job sitecustomize or other custom code before Python reaches that function. Every launcher must
enter a platform-owned sanitized bootstrap in which job custom import paths are unavailable.
The target is an **absolute platform-owned bootstrap artifact** invoked with **`python -I -S`**
from a platform-owned working directory and a fixed minimal pre-Python environment allowlist.
`-S -m module` is insufficient because the module can still be shadowed from the current working
directory.

Logical-participant sequence:

1. The durable site supervisor begins the logical participant and records persistent storage
   capacity after the run directory exists.
2. It authenticates and durably stores that participant start outside the job-writable area.
3. It keeps the logical participant identity alive across checkpoints, allocation expiry, GPU-free
   waiting, and resumed resource windows.

For every resource window:

1. The supervisor confirms acquisition, mints attempt/environment identity, and durably records
   **opened_at** on its own clock before bootstrap begins.
2. The launcher passes **attempt_id** and the opaque supervisor-handoff locator through its
   explicit, fixed argument allowlist, while stripping unallowlisted environment and import-path
   inputs before Python starts.
3. A fresh resource worker starts in a sanitized platform Python environment. Platform code takes
   CPU, memory, and CUDA observations only after the allocation is applied and before enabling
   job custom imports.
4. It immediately hands the bounded capacity snapshot to the supervisor; the attempt-start record
   carries the supervisor-owned **opened_at**, not a worker measurement timestamp.
5. The supervisor authenticates identity and durably accepts the bytes.
6. Only then does the bootstrap enable the job custom path and enter or resume normal work.

This exact ordering applies to direct process, Docker, Kubernetes, and Slurm launchers. Each
launcher needs negative tests proving that unallowlisted attempt/handoff arguments, a hostile
working-directory module, custom PYTHONPATH/sitecustomize, or an extra pre-Python environment
value cannot bypass the bootstrap.

The contract is process-topology-neutral. If the roadmap implementation reuses an operating-
system process to preserve CPU-side job state, a platform-owned reconfigure/resume hook must still
close the old vector and open the successor at the same supervisor timestamp. Every GPU-vector
transition must apply the new visibility and probe it in a fresh, CUDA-uninitialized worker or
platform helper before custom GPU work resumes. An already CUDA-initialized process cannot be
assumed to re-enumerate a changed visibility mask unless a future runtime-reset path is explicitly
supported. The durable supervisor itself remains GPU-free. OS process exit is not the accounting
boundary, although worker replacement may be required to make the GPU transition real.

Before normal window closure, platform code takes and immediately hands off the optional attempt
final, which has no duration timestamp. After trusted release/reconfiguration confirmation, the
supervisor writes **attempt_end.closed_at**. For a partial release that changes the vector while
the same reporter environment and other counted resources remain, it uses reason
**reconfigured** and immediately opens the successor vector. If all counted resources are
released, no attempt is open until a later acquisition, even if that acquisition happens at the
same timestamp. On failure or preemption, the supervisor still closes the resources and records
end without inventing a final. On launch failure after acquisition, it preserves the open/close
duration even though no worker capacity snapshot exists.

A CPU/memory successor after GPU release reports a numeric zero GPU inventory only when the fresh
CUDA-runtime enumeration succeeds with an empty group array. If CUDA enumeration is unavailable
or fails, GPU remains unavailable and the derived GPU total is partial/unavailable; the design
never infers zero from the requested reconfiguration or a raw visibility mask.

At logical participant finalization, the supervisor takes the final storage observation, freezes
the registered retained files, atomically freezes the three all-job F3 counters, and only then
serializes and durably stores one participant final. Counter callbacks completing after the freeze
are ignored for canonical totals. Summary-publication traffic is excluded through a platform-only
path; neither behavior produces a circular counter in participant final. None of these participant-
lifetime facts belongs in an attempt final.

## 5. Supervisor-owned storage and delivery

Accepted local lifecycle bytes live under a durable platform root outside the job-writable
workspace:

~~~text
<supervisor-owned-root>/<job_id>/<participant_key>/
  participant_start.json
  attempts/<attempt_id>/start.json
  attempts/<attempt_id>/final.json          # only when received
  attempts/<attempt_id>/end.json
  participant_final.json
  participant_summary.json
~~~

Worker-writable resource files are diagnostic self-reports, not immutable evidence. Kubernetes
emptyDir alone is insufficient because pod loss can remove a fragment before supervisor
acceptance. The implementation must use authenticated IPC, a supervisor-owned bind, or an
equivalent handoff whose durability survives disposal of each compute allocation and supports
checkpoint/resume reconstruction.

Start/final fragments are handed off locally as soon as they exist; they are not held inside a
disposable worker until job completion. Reuse the existing terminal job-outcome request/reply
path only for the one bounded client-site-to-server participant summary. The server
parent/job supervisor performs the equivalent lifecycle ownership and locally ingests the server
participant summary. Do not create another completion barrier. Failure to deliver or ingest
becomes a missing roster entry; it does not change the federated job outcome.

## 6. Server materialization, manifest, and query API

At the existing terminal barrier the server:

1. snapshots expected identity and role from authenticated job-selection/deployment state, never
   from resource-report arrivals, and fixes **report_cutoff_at** so later arrivals cannot change
   roster classification or coverage;
2. accepts at most the first valid authenticated participant summary for each key;
3. derives accepted participant totals and **resource_window_seconds** from lifecycle facts;
4. materializes missing, invalid, and disabled roster entries;
5. derives exact flat job totals and **finalized_at**;
6. writes the participant files, resource summary, and manifest; and
7. saves the exact resource-summary bytes as the finalized query copy before job completion.

Canonical server archive:

~~~text
resource_stats/
  participants/<participant_key>.json
  resource_summary.json
  manifest.json
~~~

The manifest has only sorted **relative_path** and **sha256** entries: exactly
resource_summary.json plus one participant file per accepted roster member. It has no byte count
or repeated record-kind field. Bundle validation checks exact membership, digests, job identity,
accepted participant totals, job totals, ordering, and one-reporter interval rules.

Persist the exact resource-summary bytes behind one exact **RESOURCE_STATS** component. Do not
add it to generic DataTypes prefix authorization. Add narrow internal methods:

~~~text
save_resource_stats(job_id, exact_summary_bytes)
get_resource_stats(job_id)
~~~

The methods select the component internally. Reject RESOURCE_STATS_* or path-like variants.
No per-participant job-store components or separate database are needed. Job deletion removes the
resource archive/query copy; a cloned job starts empty.

## 7. CLI/API

Candidate read-only command:

~~~text
nvflare job resources JOB_ID --site all
nvflare job resources JOB_ID --site SITE
nvflare --format json job resources JOB_ID --site all
~~~

It is finalized-job only and reads persisted server data without contacting clients. The human
view starts with the proxy disclaimer, then separates roster **STATUS** from measurement
**QUALITY** and shows **ENV WINDOW**, full-GPU hours, CPU hours, memory/storage GiB-hours, retained
bytes, and **F3 REMOTE** payload KiB (with exact base bytes in JSON). Resource-window
duration is the sum of stable-vector windows. It can equal participant wall time when CPU/memory
remain held through GPU-free intervals, become shorter across true all-resource gaps, or exceed
wall time when reporter environments overlap. Storage time follows the participant lifecycle. A MIG column and
MIG-specific text appear only when selected data has positive MIG instance-time. Optional CPU/GPU
models appear in JSON and a detail/single-site view, not the compact default table.

JSON returns the exact typed summary inside the normal CLI envelope. The all-site aggregate is
explicitly labeled accepted-report totals; its resource-time columns are not physical capacity.
A selected participant is shown as a complete selected-site result with optional hardware details
and is not labeled a job total. Expected-but-missing is a successful partial result; unknown site,
not-ready job, absent legacy data, and failed manifest/query integrity use distinct errors.

Review the generated [human output](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-all.txt),
[JSON output](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-all.json),
[complete selected-site output with hardware detail](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-site-1-details.txt),
and [partial preempt/resume output](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-preempted-resume.txt).

## 8. Production code fit

| Existing area | Phase 1 work |
| --- | --- |
| Durable site supervisor and resource manager | Keep logical participant identity; acquire, reconfigure, and release counted compute resources; own attempt IDs, opened/closed clock, and durable reconstruction. |
| JobProcessArgs and every launcher | Add and allowlist the supervisor-minted attempt ID and handoff locator; invoke sanitized bootstrap or acquire/resume capture consistently. |
| client_executor.py / server_engine.py | Bind the roadmap supervisor implementation to participant lifecycle, own the durable fragment store, and construct/deliver one participant summary. |
| worker_process.py / runner_process.py | Enter or resume custom work only after the current vector's snapshot has been accepted; emit optional untimed capacity final before release/reconfiguration. |
| workspace.py | Resolve participant-lifetime run-filesystem observation and explicit result-registration roots without exporting paths. |
| new private resource_stats package | Typed models, probes, canonical decimals, fragment acceptance, attempt/participant derivation, and server materialization. |
| CoreCell sender path | Bind all-job F3 counters to trusted participant identity, send acceptance, and atomic participant-final freeze semantics across resource-window gaps. |
| JobRunner / job store | Freeze roster/cutoff, validate summaries, derive totals, write archive/manifest, and save exact RESOURCE_STATS bytes. |
| session/job CLI | Add authorized finalized resource query and adaptive human/typed JSON renderers. |

The collector path must not consume resource-manager allocation results, launcher resource specs,
or arbitrary payload labels as capacity measurement authority. It may consume the trusted
resource manager's acquire/release lifecycle solely to decide when a resource window begins and
ends.

## 9. Implementation slices

| Slice | Deliverable | Exit criterion |
| --- | --- | --- |
| P1-01 | Land typed contract helpers and goldens in production test packaging. | Schema and executable validation agree for every golden and negative case. |
| P1-02 | Add participant storage capture plus resource-window sanitized bootstrap, launcher attempt/handoff allowlists, CPU/memory/CUDA probes, and model policy. | Each stable vector is observed after open and before custom work; partial release produces a zeroed successor rather than dropping still-held dimensions. |
| P1-03 | Add authenticated supervisor handoff, write-once durable lifecycle storage, supervisor open/close clock, crash/preemption/launch-failure behavior, and participant reconstruction. | Bootstrap time is included; disposable-worker loss cannot mutate accepted bytes; vector change closes time without requiring process exit; finals are never invented. |
| P1-04 | Add participant-lifetime trusted F3 registry/counter and artifact registry. | Three factual buckets and retained entries finalize exactly once; counter callbacks after atomic freeze are ignored and summary publication is excluded without circular counters. |
| P1-05 | Add server acceptance/derivation, compact archive/manifest, exact RESOURCE_STATS APIs, and CLI/API. | Finalized jobs expose verified typed results; retries and roster gaps cannot duplicate totals. |
| P1-06 | Complete compatibility, security, retention, launcher, and operator tests. | The feature remains non-fatal, bounded, redacted, and backward compatible. |

## 10. Required tests

- pre-Python custom-path/sitecustomize isolation and attempt/handoff argument allowlists for process,
  Docker, Kubernetes, and Slurm;
- CPU affinity/cpuset/quota/fallback matrices and cgroup v1/v2/hybrid ancestor behavior;
- memory finite/unlimited/malformed/permission cases and physical fallback;
- CUDA success/zero/unavailable/error, MIG/full-GPU separation, metadata suppression, and no raw
  mask/UUID/BDF leakage;
- homogeneous and heterogeneous CPU models and optional GPU model normalization;
- three contiguous stable-vector windows over 480 seconds, with GPU time only in the first/last
  180 seconds but CPU/memory time across all 480 seconds;
- preemption/resume with a true all-resource 300-second gap, partial totals, persistent storage/F3
  coverage, and exactly-once retained-content finalization;
- GPU removal and return while CPU/memory remain held expressed as exact-boundary
  **reconfigured** successors, while an adjacent full release/reacquire remains a normal
  release/reacquire and only a positive full-release interval creates a no-attempt gap;
- normal attempt final, changed final, missing final/crash/preemption, launch failure, sequential
  allocation reuse, accepted concurrent distinct environments whose summed windows exceed wall
  time, and overlapping same-environment reporter rejection;
- fresh/CUDA-uninitialized GPU-transition probes, CPU-side state preservation without stale CUDA
  enumeration, and proof that attempt end occurs only after trusted release/reconfiguration
  confirmation;
- retained registry freeze, regular-file descriptor sizing, symlink/change rejection, and exact
  sum;
- all three stored F3 buckets, the exact included/excluded class allowlists, zero-byte messages,
  post-encode/encryption payload sizing, per-destination fan-out, per-hop forwarding, counter gap,
  atomic-freeze races, remote acceptance versus local delivery, ignored callbacks after freeze, and
  non-spoofable summary exclusion without a stored circular counter;
- first-valid participant acceptance, identical retry, conflicting replacement, late report,
  invalid-before-valid, independently sourced expected-participant roster (including a missing
  reporter), arrival-derived-roster rejection, and aggregate arithmetic;
- manifest membership/digest corruption, exact RESOURCE_STATS authorization/copy, deletion,
  clone behavior, and archive fallback;
- CLI all/site/detail, partial/missing/disabled/unavailable/corrupt states, adaptive MIG, and
  exact base-unit JSON; and
- size/depth/decimal bounds, duplicate JSON keys, unknown fields/version, and privacy rejection.

## 11. Remaining production decisions

The candidate shape is ready for review. If accepted, the remaining choices are implementation
bindings and product policy:

| Gap | Required decision |
| --- | --- |
| CUDA packaging | Supported runtime binding/fallback and driver compatibility matrix. |
| cgroup readers | Exact v1/v2/hybrid ancestor precedence and supported fallback behavior. |
| model normalization | Platform-specific CPU/CUDA whitelists and deployment suppression policy. |
| roadmap lifecycle hook | Exact durable supervisor, acquire/resume, release-confirmation, and checkpoint/reconstruction APIs without coupling the contract to one process topology. |
| environment lease | Trusted key minting, stable-vector transitions, exact-boundary reconfiguration, and multi-node/rank ownership lifecycle. |
| supervisor handoff | IPC/durable-storage mechanism, allocation-independent lifetime, and recovery after supervisor or node failure. |
| artifact registry | Registration API, approved roots, freeze, symlink/change, and retry behavior. |
| F3 hook | Exact CoreCell send-acceptance callback and participant-lifecycle registry binding across worker restarts. |
| attempt bound | Operational limit or paging/batching strategy for jobs with many per-round allocations. |
| delivery | Bounded authenticated outbox/retry behavior before cutoff. |
| product defaults | Enablement, retention, deletion/clone, authorization, and non-Linux support. |

The maintained list is the prototype [gap register](../../research/runtime_resource_proxy_prototype/GAPS.md).
No gap should be filled with a launch-mode heuristic, inferred allocation, invented zero, or
unversioned field.
