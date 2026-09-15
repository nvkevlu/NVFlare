# NVFlare Phase 1 Runtime-Visible Resource Statistics — Implementation Plan

**Status:** The candidate-v1 data contract and review artifacts are concrete and approved for
prototype implementation. Production collectors, launcher wiring, durable handoff, server
materialization, and CLI integration do not yet exist.

For a meeting-oriented walkthrough, start with the
[linear review guide](../../research/runtime_resource_proxy_prototype/REVIEW_GUIDE.md). The
[accepted decision record](../../research/runtime_resource_proxy_prototype/SIMPLIFICATION_REVIEW.md)
explains the reductions that produced this plan. The normative candidate is the
[schema bundle](../../research/runtime_resource_proxy_prototype/schema/README.md).

## 1. Outcome and boundary

Phase 1 records facts that an NVFlare job execution can observe under ordinary user permissions:

- CPU, memory, storage, and GPU capacity visible at trusted startup;
- a second full capacity observation when the child can finalize normally;
- an observation interval used to derive resource time;
- exact bytes in platform-registered retained result files; and
- attempt-bound F3 application payload counters.

These are **runtime-visible proxies**, not utilization, allocation, reservation, ownership,
guaranteed capacity, price, cost, or billable usage. Process, Docker, Kubernetes, and Slurm use
one definition: observe from inside the execution environment of the job process. Phase 1 does
not read launcher specifications, scheduler allocation data, cloud metadata, or billing systems
to reinterpret the observation.

Participant-visible views can overlap on shared CPU, memory, filesystems, or GPUs. Cross-job
overlap is intentionally retained. A downstream estimator decides whether these qualified facts
are useful; NVFlare does not deduplicate them into physical capacity.

Explicitly excluded from Phase 1 are CPU/GPU utilization, memory peaks, storage occupancy
polling, generic OS I/O/network, generic network, privileged host agents, cost, carbon, and
cross-job aggregation. Phase 2 publication is discussed separately in the
[telemetry sketch](job_resource_statistics_phase2_telemetry_sketch.md).

Collection and persistence failures never change the federated job result. They produce an honest
status or roster gap while unaffected facts remain usable.

## 2. End-to-end flow

~~~text
platform parent mints attempt identity
  -> sanitized platform bootstrap runs before job custom imports
  -> child reports typed startup capacity
  -> parent authenticates and writes accepted bytes to durable, parent-owned storage
  -> child reports final capacity + retained content + F3 when finalization succeeds
  -> parent always records the observed process exit
  -> parent constructs one detailed participant summary
  -> server accepts the first valid immutable participant summary by a fixed cutoff
  -> server derives compact participant and job totals over a frozen roster
  -> server writes resource_summary.json + participant files + path/digest manifest
  -> exact resource_summary.json becomes the RESOURCE_STATS query copy
  -> finalized CLI/API reads the persisted result
~~~

The child start/final values remain self-reports. Authenticated parent handoff and write-once
storage prevent later job-side mutation of accepted bytes; they do not make those values
independently attested. Process exit is parent-observed, and aggregate totals are server-derived.

## 3. Candidate-v1 records

Every record has exact **schema_version: "1.0"**, one namespaced kind, and no unknown fields.
The six kinds are:

| Kind | Purpose |
| --- | --- |
| nvflare.resource_stats.attempt_start | Child startup capacity self-report. |
| nvflare.resource_stats.attempt_final | Child final capacity, retained-content, and F3 self-report. |
| nvflare.resource_stats.attempt_parent_exit | Parent-observed lifecycle closure. |
| nvflare.resource_stats.participant_summary | Detailed lifecycle facts for one accepted participant. |
| nvflare.resource_stats.resource_summary | Frozen roster with compact participant and job totals. |
| nvflare.resource_stats.manifest | Canonical path/digest inventory. |

Unknown versions are rejected. The exact shapes, bounds, and privacy rules are indexed in the
[field catalog](../../research/runtime_resource_proxy_prototype/schema/FIELD_CATALOG.md); status
and issue rules are in the
[status catalog](../../research/runtime_resource_proxy_prototype/schema/CODE_CATALOG.md).

### 3.1 Attempt identity

Standalone lifecycle records carry:

~~~text
schema_version, kind, job_id, participant_id,
attempt_id, environment_key, observed_at
~~~

The parent creates a random 32-lowercase-hex attempt ID before launch. Participant and
environment keys are job-scoped platform HMAC-SHA-256 values, not plain hashes of enumerable
labels. Payload identity is always checked against authenticated launcher/roster context.

The environment key identifies a reporter lease boundary. Within one job, attempts that use the
same environment key may be sequential but their half-open observation intervals may not
overlap, even across participant/rank files. This prevents duplicate rank reports without
mistaking a retry for duplication. It does not deduplicate different jobs.

Role is not repeated in lifecycle or participant records. It appears once on each frozen server
roster entry.

### 3.2 Typed capacity

An enabled start and every accepted final contain:

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
  "storage": {
    "status": "reported",
    "capacity_bytes": "1099511627776"
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

### 3.3 CPU, memory, and storage selection

CPU visible units are the minimum of the available strong selectors:

- process affinity count;
- effective cgroup cpuset count; and
- finite cgroup quota already normalized to CPU units.

If none is usable, online logical CPUs are an explicit host-visible fallback. Canonical evidence
stores only **affinity_count**, **cpuset_count**, **quota_units**, or the mutually exclusive
**online_count** fallback. Low-level quota inputs remain inside the probe and are not persisted.

Memory visible bytes are the smaller finite value among effective cgroup memory and physical RAM.
Swap is excluded; an unlimited cgroup value is omitted. Physical-only evidence is a host-visible
fallback.

Storage **capacity_bytes** is the total reported by statvfs for the filesystem containing the job
run directory. Free space, filesystem class, and absolute path are not persisted. This is
filesystem-capacity time, not retained content or storage occupancy.

### 3.4 GPU authority and optional metadata

A numeric GPU inventory requires successful CUDA-runtime enumeration. The visibility-mask value
and token count are forbidden; **cuda_mask_present** is diagnostic only. If CUDA enumeration is
unavailable or fails, Phase 1 emits no numeric GPU count even if a mask exists.

Reported GPU groups have positive counts and remain separated as **full_gpu** or
**mig_compute_instance**. An empty reported group array is a successful zero. Within a reported
inventory, absence of a kind means zero for that kind, so a normal non-MIG client has no MIG
field or row. Full GPUs and MIG instances are never combined into a generic GPU total.

CUDA device properties can supply normalized model and per-entity memory. NVML may refine
metadata only for devices already matched to the CUDA-visible inventory; it cannot add a device
or change the count. MIG profile is optional and legal only on a MIG group.

CPU/GPU model metadata is optional infrastructure fingerprinting. Site policy may suppress
model, architecture, per-entity memory, and MIG profile without changing numeric status. A CPU
model is reported only when every affinity-visible processor normalizes to one model. A
heterogeneous set omits it. Never persist raw cpuinfo, CPU flags/topology/serials, GPU UUID/PCI
identity, raw command output, or host/container/pod identity.

### 3.5 Final snapshot, retained content, and F3

A valid child final retains a second complete typed capacity object. It is useful for audit and
change detection; it does not replace startup as the resource-time basis. The final also contains
terminal retained-content and F3 facts at one **observed_at** cutoff.

Retained content uses **reported | partial | unavailable | error**. Reported/partial contains
sorted registered-file entries:

~~~json
{"relative_path": "result/model.pt", "size_bytes": "18874368", "sha256": "..."}
~~~

The total is derived from entry sizes. Only frozen regular files explicitly registered with the
platform are included. The workspace/archive is not swept.

F3 has one status, **cutoff_sequence**, and five counter pairs when reported or partial:

| Bucket | Meaning |
| --- | --- |
| remote_accepted | Remote application payload accepted by transport before cutoff; the primary F3 total. |
| local_delivered | Direct/local delivery, kept separately. |
| remote_failed_before_acceptance | Remote traffic that failed before sender acceptance. |
| late_after_cutoff | Post-cutoff traffic excluded from the frozen total. |
| summary_excluded | Summary-publication traffic excluded by a platform-owned, non-spoofable path. |

Every pair contains canonical integer-string **payload_bytes** and **messages**. Zero messages
requires zero bytes. The included traffic classes, sender-acceptance point, and exclusion
mechanism are fixed v1 implementation rules, not job-controlled or serialized labels. Failure
bytes are retained only when post-serialization size is known.

### 3.6 Parent exit and crash behavior

Parent exit is flat:

~~~json
{
  "observed_at": "2026-09-09T14:05:42.6Z",
  "outcome": "finished_ok",
  "return_code": 0
}
~~~

Outcomes are **finished_ok | finished_error | terminated | launch_failed**. Launch failure has no
return code; the other outcomes require one with the outcome-specific zero/nonzero invariant.

The parent always records exit. When a valid final is absent, it does not invent final capacity,
retained files, or F3 counters. Startup capacity can still be multiplied through the
parent-observed exit, but the affected derived resource time is partial.

### 3.7 Participant summary, time formula, and replay

The participant file is deliberately small in structure:

~~~json
{
  "schema_version": "1.0",
  "kind": "nvflare.resource_stats.participant_summary",
  "job_id": "job-20260909-001",
  "participant_key": "sha256-...",
  "attempts": [
    {
      "attempt_id": "...",
      "environment_key": "sha256-...",
      "start": {"observed_at": "...", "collection_state": "enabled", "capacity": {}},
      "final": {"observed_at": "...", "capacity": {}, "retained_content": {}, "f3": {}},
      "exit": {"observed_at": "...", "outcome": "finished_ok", "return_code": 0}
    }
  ]
}
~~~

Start/final are optional lifecycle facts; exit is required. A retained start is enabled, and a
final requires it. Launch failure has exit only. Disabled collection is represented by the
server roster rather than an accepted participant file. Attempts are sorted by unique attempt ID.

The participant file stores no child rollup, duration, role, trust declaration, summary ID, or
revision. The server/parent derives each resource interval:

~~~text
resource time = startup visible capacity
              × (final observed_at or parent-exit observed_at − start observed_at)
~~~

Products use decimal arithmetic, round half-even once to at most nine fractional digits, and
then sum. A missing final or changed numeric final makes the affected result partial. Startup is
not averaged with an endpoint sample. Optional metadata change alone is not a capacity change.

There is no participant revision protocol. The first valid authenticated participant summary
received by **report_cutoff_at** wins. An identical digest retry is an idempotent no-op; a
different digest is a conflicting replacement and is rejected. An invalid candidate does not
reserve the slot. Distinct executions remain separate attempts inside the one immutable summary.

All measured/derived values are canonical decimal strings. Resource time, retained bytes, F3
counters, and aggregate observation seconds are bounded by U128. This avoids loss beyond
JavaScript's safe-integer range; the golden large-value records make that case concrete.

### 3.8 Compact server summary

The server freezes one roster. Every entry has participant ID, job-scoped participant key, role,
and **accepted | missing | invalid | disabled**. Accepted entries also have **received_at**,
**summary_sha256**, **observation_seconds**, and flat **totals**. Invalid entries retain
**received_at** and a compact issue list. Missing/disabled entries add nothing.

**observation_seconds** is a checked convenience: the sum of that participant's derived enabled
attempt intervals, not a second clock measurement.

Accepted-participant totals and job totals use the same flat shape:

~~~json
{
  "cpu": {"status": "reported", "groups": [{"model": "...", "architecture": "x86_64", "unit_seconds": "513.75"}]},
  "memory": {"status": "reported", "byte_seconds": "2942052597760"},
  "storage": {"status": "reported", "byte_seconds": "376582732513280"},
  "gpu": {"status": "reported", "groups": [{"kind": "full_gpu", "model": "...", "instance_seconds": "342.5"}]},
  "retained_content": {"status": "reported", "bytes": "18874368"},
  "f3": {"status": "reported", "remote_accepted": {"payload_bytes": "5632", "messages": "2"}}
}
~~~

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

Required sequence:

1. The parent mints job/participant/attempt/environment identity.
2. The launcher passes **attempt_id** and the opaque parent-handoff locator through its explicit,
   fixed argument allowlist.
3. The child starts in a sanitized platform Python environment and constructs Workspace.
4. Platform code takes CPU, memory, and CUDA observations before enabling custom imports.
5. Once the run directory exists, it adds the storage observation.
6. It hands the bounded complete start record to the parent.
7. The parent authenticates identity and durably accepts the bytes.
8. Only then does the bootstrap enable the job custom path and enter normal worker/runner code.

This exact ordering applies to direct process, Docker, Kubernetes, and Slurm launchers. Each
launcher needs a negative test proving that an unallowlisted attempt argument or a custom
PYTHONPATH/sitecustomize cannot bypass the bootstrap.

On child finalization, platform code takes the final capacity snapshot, freezes retained-content
and F3 facts, and hands them to the parent before custom teardown can corrupt them. Parent exit is
written regardless of whether that final handoff succeeds.

## 5. Parent-owned storage and delivery

Accepted local lifecycle bytes live under a durable platform root outside the job-writable
workspace:

~~~text
<parent-owned-root>/<job_id>/<participant_key>/
  attempts/<attempt_id>/start.json
  attempts/<attempt_id>/final.json          # only when received
  attempts/<attempt_id>/parent_exit.json
  participant_summary.json
~~~

Child-writable resource files are diagnostic self-reports, not immutable evidence. Kubernetes
emptyDir alone is insufficient because pod loss can remove a final fragment before parent
acceptance. The implementation must use authenticated IPC, a parent-owned bind, or an equivalent
handoff whose durability matches the parent/job lifecycle.

Reuse the existing terminal job-outcome request/reply path to deliver the bounded participant
summary. Do not create another completion barrier. Failure to deliver becomes a missing roster
entry; it does not change the federated job outcome.

## 6. Server materialization, manifest, and query API

At the existing terminal barrier the server:

1. freezes **report_cutoff_at** and the expected participant roster;
2. accepts at most the first valid authenticated participant summary for each key;
3. derives accepted participant totals and **observation_seconds** from lifecycle facts;
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
view starts with the proxy disclaimer, then shows roster status, observed duration, full-GPU
hours, CPU hours, memory/storage GiB-hours, retained bytes, and F3 bytes. A MIG column and
MIG-specific text appear only when selected data has positive MIG instance-time. Optional CPU/GPU
models appear in JSON and a detail/single-site view, not the compact default table.

JSON returns the exact typed summary inside the normal CLI envelope. A selected participant is
not labeled a job total. Expected-but-missing is a successful partial result; unknown site,
not-ready job, absent legacy data, and failed manifest/query integrity use distinct errors.

Review the generated [human output](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-all.txt),
[JSON output](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-all.json),
and [hardware detail](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-site-1-details.txt).

## 8. Production code fit

| Existing area | Phase 1 work |
| --- | --- |
| JobProcessArgs and every launcher | Add and allowlist the parent-minted attempt ID and handoff locator; invoke the sanitized bootstrap consistently. |
| client_executor.py / server_engine.py | Mint identity, own the durable attempt store, record exit, construct/deliver participant summaries. |
| worker_process.py / runner_process.py | Enter job execution only after platform bootstrap has been accepted; emit normal final data. |
| workspace.py | Resolve the run-filesystem observation and explicit result registration roots without exporting paths. |
| new private resource_stats package | Typed models, probes, canonical decimals, fragment acceptance, participant derivation, and server materialization. |
| CoreCell sender path | Bind attempt-local F3 counters to trusted lifecycle identity and acceptance/cutoff semantics. |
| JobRunner / job store | Freeze roster/cutoff, validate summaries, derive totals, write archive/manifest, and save exact RESOURCE_STATS bytes. |
| session/job CLI | Add authorized finalized resource query and adaptive human/typed JSON renderers. |

The collector path must not consume resource-manager allocation results, launcher resource specs,
or arbitrary payload labels as measurement authority.

## 9. Implementation slices

| Slice | Deliverable | Exit criterion |
| --- | --- | --- |
| P1-01 | Land typed contract helpers and goldens in production test packaging. | Schema and executable validation agree for every golden and negative case. |
| P1-02 | Add sanitized bootstrap, launcher attempt allowlists, CPU/memory/storage/CUDA probes, and model policy. | All launchers prove pre-custom-code ordering and identical observation semantics. |
| P1-03 | Add authenticated parent handoff, write-once durable attempt storage, final/crash behavior, and participant reconstruction. | Child loss cannot mutate accepted bytes; final is preserved when present and never invented. |
| P1-04 | Add trusted F3 registry/counter and artifact registry. | Five buckets, cutoff, non-spoofable summary exclusion, and retained entries pass lifecycle tests. |
| P1-05 | Add server acceptance/derivation, compact archive/manifest, exact RESOURCE_STATS APIs, and CLI/API. | Finalized jobs expose verified typed results; retries and roster gaps cannot duplicate totals. |
| P1-06 | Complete compatibility, security, retention, launcher, and operator tests. | The feature remains non-fatal, bounded, redacted, and backward compatible. |

## 10. Required tests

- pre-Python custom-path/sitecustomize isolation and attempt-argument allowlists for process,
  Docker, Kubernetes, and Slurm;
- CPU affinity/cpuset/quota/fallback matrices and cgroup v1/v2/hybrid ancestor behavior;
- memory finite/unlimited/malformed/permission cases and physical fallback;
- CUDA success/zero/unavailable/error, MIG/full-GPU separation, metadata suppression, and no raw
  mask/UUID/BDF leakage;
- homogeneous and heterogeneous CPU models and optional GPU model normalization;
- normal final, changed final, missing final/crash, launch failure, sequential retry, and
  overlapping same-environment reporter rejection;
- retained registry freeze, regular-file descriptor sizing, symlink/change rejection, and exact
  sum;
- all five F3 buckets, zero-byte messages, counter gap, fixed cutoff, acceptance boundary,
  forwarding, and non-spoofable summary exclusion;
- first-valid participant acceptance, identical retry, conflicting replacement, late report,
  invalid-before-valid, frozen roster, and aggregate arithmetic;
- manifest membership/digest corruption, exact RESOURCE_STATS authorization/copy, deletion,
  clone behavior, and archive fallback;
- CLI all/site/detail, partial/missing/disabled/unavailable/corrupt states, adaptive MIG, and
  exact base-unit JSON; and
- size/depth/decimal bounds, duplicate JSON keys, unknown fields/version, and privacy rejection.

## 11. Remaining production decisions

The data shape is no longer open. Remaining choices are implementation bindings and product
policy:

| Gap | Required decision |
| --- | --- |
| CUDA packaging | Supported runtime binding/fallback and driver compatibility matrix. |
| cgroup readers | Exact v1/v2/hybrid ancestor precedence and supported fallback behavior. |
| model normalization | Platform-specific CPU/CUDA whitelists and deployment suppression policy. |
| environment lease | Trusted key minting and multi-node/rank ownership lifecycle. |
| parent handoff | IPC/durable-storage mechanism and crash recovery lifetime. |
| artifact registry | Registration API, approved roots, freeze, symlink/change, and retry behavior. |
| F3 hook | Exact CoreCell send-acceptance callback and lifecycle registry binding. |
| delivery | Bounded authenticated outbox/retry behavior before cutoff. |
| product defaults | Enablement, retention, deletion/clone, authorization, and non-Linux support. |

The maintained list is the prototype [gap register](../../research/runtime_resource_proxy_prototype/GAPS.md).
No gap should be filled with a launch-mode heuristic, inferred allocation, invented zero, or
unversioned field.
