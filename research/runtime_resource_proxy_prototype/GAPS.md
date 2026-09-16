# Remaining resource-statistics decisions

This file separates decisions that are now concrete from work that still needs
design review. The detailed current-code path is in
[CURRENT_CODE_INTEGRATION.md](CURRENT_CODE_INTEGRATION.md).

Every answer must preserve this deployment rule:

> Resource statistics must work with existing NVFlare permissions and setup.
> No new privilege, mount, service, launcher argument, environment variable,
> or user/operator configuration may be required.

## Now concrete

The following questions are no longer open in the prototype design.

| Area | Current design |
| --- | --- |
| Current measurement period | One period covers the lifetime of today's client or server job process. Future code may open more periods through the same API without changing the schema. |
| Start hooks | In client `worker_process.py` and server `runner_process.py`, after workspace construction and before the explicit custom-directory import path is added. |
| Final hooks | After runner `END_RUN` processing and before F3/streaming shutdown. |
| Parent handling | Client parent reads, bounds, and hashes the frozen report after `job_handle.wait()`; root server parent validates accepted reports and performs the job reduction after the server job process exits. |
| Client delivery | Add the exact bounded `participant_summary` bytes and digest to the existing authenticated CP terminal-outcome request on `task/report_job_failure`. |
| Cutoff | Reuse the current client-outcome cutoff: normally the configured wait whose current default is 900 seconds; abort and server-failure paths skip that client wait after one server-local acceptance attempt. Acceptance close, ledger snapshot, and candidate commit use one lock. Add no second report window. |
| Duplicate reports | First valid digest wins; identical retries are idempotent; a different later digest is rejected and never overwrites accepted bytes. |
| Expected participants | Root server freezes the server plus every selected client before start-job delivery; incoming reports do not create this set. |
| Opaque keys | Root server derives participant and current-process environment keys with a per-job HMAC key, then places only the derived map in reserved existing job metadata. Client delivery uses its current metadata-file rewrite; Phase 1 adds the corresponding narrow deployed-file update in `ServerEngine` for the SJ. No secret or new launcher input leaves the root parent. |
| Server participant | Read from the returned/shared server workspace and pass through the same internal validator without a loopback network request. |
| Durable storage | Write participants, `resource_summary.json`, and `manifest.json` under the existing server run directory, then let normal job completion archive them in `WORKSPACE`. |
| CLI source | Read and verify fixed members directly from archived `WORKSPACE`. There is no `RESOURCE_STATS` component or other duplicate. |
| Trust statement | Site observations are authenticated self-reports, not tamper-resistant attestation. Workspace fragments can be changed or lost before receipt. |
| Future execution work | It may change who opens/closes periods and who delivers the site report. The schema, reconciliation, archive, and CLI stay stable; the CP terminal path is the adapter for current code, not a roadmap constraint. |

## Remaining Phase 1 design decisions

These are the decisions the team still needs to make before a production
implementation is complete.

### 1. GPU adapter support and matching

The authority rule is fixed: only successful CUDA Runtime enumeration may emit
a numeric GPU count, and NVML can only enrich those CUDA-validated entities.
The implementation still needs to choose:

- the minimum supported CUDA Runtime and NVML versions;
- how it loads the process-visible runtime without adding a package or setup
  requirement;
- the precise CUDA-to-NVML match for full GPUs and MIG compute instances; and
- which failures make all GPU capacity unavailable versus only suppressing
  model, memory, or MIG enrichment.

Raw `CUDA_VISIBLE_DEVICES` and `nvidia-smi` remain diagnostic only.

### 2. F3 correlation and provenance

The current route table and explicit exclusions are now audited in
[CURRENT_CODE_INTEGRATION.md](CURRENT_CODE_INTEGRATION.md#current-route-and-binding-table).
The low-level route alone cannot distinguish real work from polling or model
data from workspace ZIP data. Production still needs to implement and test:

- pending-byte correlation between an accepted `get_task` request and its real
  task reply;
- trusted provenance from an included large object into its shared
  DownloadService/stream transaction, with workspace transfer marked excluded;
- trusted class re-establishment at intermediate forwarding hops; and
- logical stream ID/sequence/destination deduplication for reliable retries.

The implementation also needs job-scoped counters in each sending process and
an exact parent merge. The existing process-global `StatsPool` is not
sufficient. A path without the required provenance reports `not_bound` or
`counter_gap`; it never falls back to generic sent/received totals.

### 3. Saved-result binding

Current `Workspace` result and run roots can overlap, and applications choose
their own persisted files. No generic authoritative result-file registry was
found. The first implementation should therefore emit
`retained_content.status=unavailable` with `not_bound` unless an existing
owning component supplies a complete bounded set.

The remaining decision is whether one current owner can make that guarantee.
Do not scan the workspace, infer model filenames, or add a registry or job
setting just to populate this field.

### 4. Initial supported platforms

The prototype implements Linux affinity, cgroup v1/v2 CPU and memory limits,
`/proc/cpuinfo`, and `statvfs`. It models an injectable CUDA Runtime adapter but
does not embed the production adapter yet. The team must decide whether v1 is
Linux-only or which ordinary-user evidence provides equivalent semantics on
another operating system. Unsupported adapters report unavailable; they do not
silently use a different meaning.

### 5. Attempt-bound and reason cleanup

The schema currently allows at most 4,096 measurement periods in one
participant report. Confirm this against expected future long-running jobs.

`reconfigured` is also currently an allowed end reason. Today's process model
does not expose a mid-process resource-change event. Keep the reason only if
the upcoming execution API can use it without inferring a resource change;
otherwise remove it before v1 is fixed.

### 6. Root-parent restart recovery

The normal and failure finalization paths are specified. Production tests must
still decide whether resource-report acceptance survives a root-server process
restart during a running job. If that current recovery mode is supported, the
derived expected-participant map, accepted digests, and cutoff state must be
restored from server-owned files in the existing run workspace. The HMAC key
does not need to be restored once all derived keys exist.

Until that recovery is implemented and tested, a root-parent loss can make the
resource summary unavailable. It must not reconstruct accepted measurements
from log text or unauthenticated site files.

## Known limitations, not open requirements

- A `PYTHONPATH`-injected `sitecustomize` can run before the proposed in-process
  start hook. Solving hostile-code attestation would require a stronger
  isolation boundary and is not a Phase 1 claim.
- Hard process or pod loss can remove local fragments. Existing workspace
  return paths improve normal-completion recovery but do not make fragments
  durable.
- A Slurm launcher whose rank-zero workspace contains only one node's evidence
  must report that actual scope or mark multi-node coverage partial. It must
  not present one rank as whole-participant capacity.
- The current workspace archival path can publish a terminal job status after
  repeated archival failure. The CLI then reports the resource summary
  unavailable; there is intentionally no fallback copy.
- V1 validates and installs a client report before resolving that client's
  terminal outcome. Client request timeouts bound network waiting, not local
  preparation or server filesystem calls. Slow workspace I/O can delay
  resolution and can hold the shared commit lock past the nominal outcome
  deadline. It does not change the job outcome or add a later reporting window.
- Totals across participants or jobs can refer to overlapping physical
  resources. They are measured visible capacity-time, not inventory or
  capacity ownership.

## Remaining Phase 2 decisions

The current in-job JobStatsReporter finishes before the root parent can build
the final Phase 1 summary. Phase 2 therefore needs a parent-side adapter, or a
post-archive reader using the same fixed-member helper as the CLI.

The team still needs to choose:

- final `resource_proxy.*` field names;
- job-only versus selected per-site publication;
- whether hardware models may ever be published;
- the telemetry event type and payload limit;
- retry duration and duplicate-delivery behavior; and
- the reusable JobStatsReporter publication interface exposed to the root
  server parent.

Phase 2 never collects Phase 1 data, never reads a duplicate job-store
component, and never changes the job outcome.

## Closed decisions (reference only)

- no extra privileges or configuration;
- no scheduler, container, cloud, or billing APIs;
- site data is self-reported rather than described as immutable evidence;
- CUDA Runtime is the only numeric GPU-count authority;
- full GPUs and MIG instances are separate, and MIG fields are omitted when
  inapplicable;
- CPU and GPU model strings are optional, bounded, and omitted when unsafe or
  heterogeneous;
- raw identity and topology fields are excluded;
- missing data is not zero;
- the visible capacity of only the job-workspace filesystem is observed at
  participant start and final, never multiplied by time or aggregated;
- the client report rides the existing authenticated terminal-outcome request;
- participant and current-process environment keys are HMAC-derived and only
  derived values travel through reserved existing job metadata;
- the server reconciles against a frozen expected-participant set;
- the existing `WORKSPACE` archive is the sole durable source for the CLI;
- no `RESOURCE_STATS` component exists; and
- the schema does not choose the future task/resource process model.

The rationale for earlier simplification is kept in
[SIMPLIFICATION_REVIEW.md](SIMPLIFICATION_REVIEW.md).
