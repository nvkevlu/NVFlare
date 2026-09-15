# NVFlare Phase 1 resource statistics — implementation plan

Status: draft for review.

This document describes the data Phase 1 should collect, how to calculate the
results, and how users should read them. It does not choose the future NVFlare
task-process or resource-management architecture.

For a shorter introduction, start with the
[review guide](../../research/runtime_resource_proxy_prototype/REVIEW_GUIDE.md).

## 1. Agreed scope

Phase 1 reports resources visible inside the environment where an NVFlare job
runs. It does not report utilization or authoritative allocation data.

Included:

- visible CPU capacity;
- visible memory capacity;
- CUDA-enumerated GPUs;
- point-in-time visible capacity of the filesystem that contains the existing
  job workspace;
- one exact byte total for a complete NVFlare result set already known to the
  platform; and
- F3 application-payload counters.

Excluded:

- CPU, memory, or GPU utilization;
- Kubernetes requests and limits read from the API;
- Docker configuration or socket data;
- Slurm allocation records;
- cloud instance metadata;
- billing rates or monetary calculations; and
- scans of unrelated files or operating-system network counters.

### Deployment constraint

The feature must work with the permissions and setup NVFlare already has.

It must not require:

- root access;
- a privileged container;
- a host agent or sidecar;
- Docker socket access;
- additional Kubernetes RBAC permissions;
- cloud permissions;
- Slurm administrator access;
- a new volume or mount;
- a new launcher argument or environment variable; or
- new operator or job configuration.

Any implementation that needs one of these is out of scope.

This feature does require NVFlare code changes. It must not require users or
operators to change installation, job configuration, launch commands, or
deployment setup.

## 2. Architecture boundary

The resource-statistics contract must not decide which component runs a task.

The resource-management work may choose any of these shapes:

- CP runs task code directly.
- An NVFlare process starts a child process.
- A process is replaced or restarted between parts of a job.
- Another platform-owned design is selected.

All of them should be able to write the same records.

In the JSON, an **attempt** means a measurement period. It does not necessarily
mean a process launch, a scheduler attempt, or a resource lease. A measurement
period has one start time, one end time, and one observed CPU, memory, and GPU
set.

The final implementation will decide what starts and ends a measurement period.
The schema does not require a new period after a resource change. If NVFlare
does observe another period, it may record one. If the start and final resource
observations differ, the affected totals are partial.

An earlier prototype selected one possible roadmap process model. That was not
a design decision, so the assumption has been removed.

## 3. Plain-language data flow

The intended flow is:

1. NVFlare begins a site's part of the job.
2. NVFlare records the visible capacity of the job-workspace filesystem.
3. When a measurement period begins, NVFlare records its start time and visible
   CPU, memory, and GPU values.
4. At a normal end, NVFlare may take one final resource observation.
5. NVFlare records the period end time.
6. At site completion, NVFlare records the final visible workspace-filesystem
   capacity, one saved-result byte total, and the closed F3 counters.
7. The site sends one final report through an existing authenticated NVFlare
   path.
8. The server validates the report, combines all received site reports, and
   stores the final job result.
9. The CLI reads the stored result. It does not contact sites.

The exact NVFlare component that performs steps 1–6 is open. The data contract
is the same whichever component is selected.

## 4. Records

Candidate v1 has eight closed record types:

| Record | Purpose |
| --- | --- |
| **participant_start** | Start of one site's part of the job and initial visible workspace-filesystem capacity observation. |
| **attempt_start** | Start of one measurement period and its CPU, memory, and GPU observation. |
| **attempt_final** | Optional final resource observation for that period. |
| **attempt_end** | End time and reason for that period. |
| **participant_final** | Final visible workspace-filesystem capacity observation, one saved-result byte total, and F3 counters. |
| **participant_summary** | One complete site report built from the preceding facts. |
| **resource_summary** | Job result with every expected participant classified. |
| **manifest** | Hashes of the exact stored server files. |

The exact required fields and types are in the
[field catalog](../../research/runtime_resource_proxy_prototype/schema/FIELD_CATALOG.md).
The machine-readable rules are in the
[JSON Schema](../../research/runtime_resource_proxy_prototype/schema/resource_stats_v1.schema.json).

### Identity

Each measurement period has a random 128-bit **attempt_id**. This is an internal
record ID. The schema does not require it to be passed as a launcher argument.

Each period also has an **environment_key**. In review material, call this the
measurement-scope key. NVFlare generates it from information already available
to the platform. It requires no user configuration.

Periods with the same measurement-scope key may not overlap. This prevents two
ranks in one environment from reporting the same visible capacity at the same
time. Periods from different jobs are not deduplicated. Therefore totals across
jobs may count the same physical hardware more than once.

The exact way NVFlare derives the key is still open. If the selected process
model cannot derive it without new setup, the key design must change.

## 5. Resource rules

### CPU

Report effective CPU capacity in CPU units. One unit is the scheduling capacity
of one logical CPU.

Read these values when available:

- process affinity count;
- effective CPU-set count; and
- finite CPU quota divided by period.

Use the smallest applicable value. If none is available, use the online logical
CPU count visible to the process.

**quota_units** is the exact quota/period ratio rounded down to at most nine
decimal places. Rounding down avoids overstating capacity. Raw **quota_us** and
**period_us** remain inside the probe and are not stored.

The normalized CPU model and architecture are optional. Report a CPU model only
when every affinity-visible CPU normalizes to the same model. Otherwise omit it.

### Memory

Report effective visible RAM in bytes.

Use the smaller finite value from:

- a memory maximum enforced on the process environment; and
- physical memory visible to the process.

Treat an unlimited cgroup value as no finite limit. Do not add swap.

### GPU

A numeric GPU count requires successful CUDA-runtime enumeration. A raw
**CUDA_VISIBLE_DEVICES** string never provides a count.

NVML may add model, per-device memory, and MIG profile only for devices already
found by CUDA. NVML cannot add a device or change the count.

Keep full GPUs and MIG instances in separate groups. **memory_bytes** is the
runtime-reported memory for each entity in the group. Devices with different
memory values use different groups.

MIG fields and CLI columns are omitted when no positive MIG value is present.

### Visible workspace-filesystem capacity

At participant start and final, read the total visible capacity of exactly the
filesystem containing the existing NVFlare job workspace. Do not enumerate or
sum other mounted filesystems, and do not export the workspace's absolute path.

Treat the two readings as independent point observations. They need not match
and do not prove availability between those instants. The capacity may describe
a shared filesystem; it is not usage, allocation, billable storage, or storage
owned by this job.

Do not calculate storage byte-seconds. Do not add visible workspace-filesystem
capacity to participant totals or combine it across participants.

This is a deliberate v1 boundary: a shared filesystem cannot be attributed to
the job without privileges or configuration that this feature is not allowed
to require.

### Saved-result byte total

Record one exact byte total only when existing NVFlare state identifies a
complete, bounded result set. Calculate it from that set without exporting
per-file data. If no such set exists, retained content is unavailable with
`not_bound`. Do not add an artifact registry, job setting, or scan of unrelated
directories.

Keep only status and a byte count. A reported value is the complete total; a
partial value is the exact observed subtotal. Do not export result filenames
or hash model content. Keep saved-result bytes separate from filesystem
capacity.

### F3 network counters

Count these job traffic classes:

- task request;
- task response;
- task result;
- job application; and
- job stream data.

Do not count:

- job stream control;
- bulk envelopes;
- workspace transfer;
- platform control;
- log export;
- unknown traffic classes; or
- the resource-summary publication itself.

For remote delivery, count payload bytes only after the payload is encoded and
any end-to-end encryption is applied, immediately before the normal F3 send.
Increment the remote counter only after the send is accepted.

Keep three counters:

- remote accepted;
- local delivered; and
- remote failed before acceptance.

For fan-out, count each destination. For forwarding, count each sender hop.
Exclude headers, driver framing, TLS framing, compression overhead, and
retransmissions below this boundary.

Before writing the final site report, NVFlare closes all three counters in one
operation. Later callbacks do not change the stored totals. Job code cannot
mark its own traffic as excluded.

## 6. Time and totals

Both timestamps for one measurement period must come from the same NVFlare
clock.

Use the half-open interval from **opened_at** up to, but not including,
**closed_at**:

~~~text
duration_seconds = closed_at - opened_at

cpu_unit_seconds =
    visible_cpu_units × duration_seconds

memory_byte_seconds =
    visible_memory_bytes × duration_seconds

gpu_instance_seconds =
    visible_gpu_instances × duration_seconds
~~~

Round each product to nine decimal places using round-half-even, then add the
period values.

A final resource observation does not define duration. It checks whether the
startup value appears to have remained valid. If it is missing or numerically
different, mark the affected total partial.

The saved-result byte total and F3 counters contribute once per site report.

A measurement period that started but could not capture resources may retain
its known start and end times. Its resource values are unavailable, and job
totals are partial.

A completed site report with no measurement periods means zero observed
compute time only when NVFlare knows that the list is complete. If it cannot
make that statement, the site report must be missing or invalid rather than
claiming zero.

## 7. Status and issue codes

Status depends on the fact being described:

| Fact | Allowed status |
| --- | --- |
| Point-in-time CPU, memory, GPU, or visible workspace-filesystem capacity | **reported**, **unavailable**, **error** |
| Saved results or F3 counters | **reported**, **partial**, **unavailable**, **error** |
| Derived resource-time total | **reported**, **partial**, **unavailable** |

Point-in-time CPU, memory, GPU, and visible workspace-filesystem capacity
cannot be partial. NVFlare either obtains a valid selected value at that
moment or it does not. Saved-result and F3 facts may be partial when they
retain useful numeric data but have incomplete coverage.

The server classifies each expected participant as:

| Status | Meaning |
| --- | --- |
| **accepted** | A valid final site report arrived before the cutoff. |
| **missing** | No report arrived. |
| **invalid** | A report arrived but failed validation. |
| **disabled** | Existing policy disabled collection for that site. |

Issue codes explain partial, unavailable, and error states. The fixed list is in
the [code catalog](../../research/runtime_resource_proxy_prototype/schema/CODE_CATALOG.md).
Missing data is never replaced with zero.

End reasons are **released**, **reconfigured**, **failed**, **terminated**, and
**launch_failed**. These are descriptive only; they do not change the time
formula. **reconfigured** means NVFlare ended a measurement period after
observing a capacity change. It does not require or imply a later period.

## 8. Trust, storage, and delivery

### Site-side files

The schema does not require site-side fragment files. The prototype shows one
best-effort option that writes them in the existing NVFlare job workspace. If
an implementation uses that option, job code may change or remove the files,
and a process or pod crash may lose them.

The prototype uses best-effort write-once file creation to avoid accidental
conflicting writes through the collector. This does not add a security boundary
or require a new directory, mount, or privilege.

### Final site report

One final report is produced for each client and for the server. The report
contains all measurement periods known to that site.

The delivery mechanism is not chosen here. It must reuse an authenticated
NVFlare path and must not require user configuration. Two possible internal
implementations are:

- add the report to an existing terminal job-outcome exchange; or
- add a bounded internal accounting message.

This is an implementation decision, not a schema decision.

### Server storage

The server already knows which participants the job expects. At a fixed cutoff,
it marks each one accepted, missing, invalid, or disabled. It does not build the
list from incoming reports, because that would hide missing participants.

The server stores:

~~~text
workspace/resource_stats/
  resource_summary.json
  manifest.json
  participants/
    <participant_key>.json
~~~

The query copy uses exactly one job-store component:

~~~text
RESOURCE_STATS
~~~

The implementation must expose narrow **save_resource_stats** and
**get_resource_stats** APIs. A generic prefix is not accepted.

The files follow the job's existing retention and deletion behavior. No new
storage configuration is introduced.

## 9. CLI and API

Proposed CLI:

~~~text
nvflare job resources JOB_ID
nvflare job resources JOB_ID --site SITE
nvflare job resources JOB_ID --format json
~~~

The command is a finalized-job view. It reads server storage and does not
contact clients.

Text output shows:

- expected-report coverage;
- one row per expected site;
- report status and measurement quality;
- measured time;
- GPU hours;
- CPU hours;
- memory GiB-hours;
- saved-result GiB; and
- accepted remote F3 GiB.

The default command does not show or aggregate visible workspace-filesystem
capacity. Those point observations remain in the accepted participant reports.

The command says clearly that job totals may contain overlapping physical
resources and are not physical capacity.

Examples:

- [all sites](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-all.txt)
- [one site with models](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-site-1-details.txt)
- [site with partial measurement evidence](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-site-2-details.txt)
- [JSON](../../research/runtime_resource_proxy_prototype/schema/golden/v1/finalized_job/cli/resources-all.json)

## 10. Initial observation and job code

The first observation must come from NVFlare platform code before job code can
change the result.

The previous prototype prescribed process-specific bootstrap and launch
changes. They were not accepted requirements and have been removed.

The selected process model must provide a suitable platform call site without
new operator setup. If a launch mode cannot do this, its affected values must be
unavailable. Phase 1 must not gain extra privileges or configuration to force a
measurement.

No job-provided event handler, component, or configuration can replace the
platform collector.

## 11. Phase 2 and JobStatsReporter

Phase 2 is separate. It may use **JobStatsReporter** to publish selected fields
from the finalized Phase 1 **RESOURCE_STATS** record.

Phase 2 must not:

- collect Phase 1 values;
- read in-progress site fragments;
- turn utilization samples into Phase 1 capacity;
- change Phase 1 totals; or
- make the job fail when publication fails.

The detailed mapping is in
[job_resource_statistics_phase2_telemetry_sketch.md](job_resource_statistics_phase2_telemetry_sketch.md).

## 12. Implementation slices

| Slice | Work | Done when |
| --- | --- | --- |
| P1-01 | Finalize the schema, fields, units, codes, formulas, and examples. | Schema, validator, and goldens agree. |
| P1-02 | Add normal-user CPU, memory, GPU, and visible workspace-filesystem capacity probes at the selected NVFlare call site. | No extra setup is required; probe failure cannot fail a job. |
| P1-03 | Add per-job F3 counters. | Included traffic, excluded traffic, acceptance, and cutoff behavior are tested. |
| P1-04 | Build one final site report and deliver it through an existing authenticated path. | Missing, duplicate, invalid, and retried reports behave predictably. |
| P1-05 | Store the server summary and expose the CLI/API. | The stored JSON, manifest, query copy, and CLI output match the goldens. |
| P1-06 | Validate supported process and launch modes after the resource-management architecture is selected. | Each mode produces the same schema without new privileges or configuration. |
| P2-01 | Add an optional JobStatsReporter publisher for finalized Phase 1 data. | Publication is bounded, redacted, retry-safe, and non-fatal. |

## 13. Required tests

Tests must cover:

- CPU affinity, CPU set, fractional quota, conflicting limits, and fallback;
- finite, unlimited, malformed, and unreadable memory limits;
- CUDA-enumerated full GPUs, zero visible GPUs, unavailable CUDA, and MIG;
- hardware-model suppression and heterogeneous CPUs;
- exact selection of the existing job-workspace filesystem, no enumeration or
  summation of other mounts, and unreadable workspace filesystems;
- exact saved-result byte totals;
- all included and excluded F3 traffic classes;
- fan-out, forwarding, local delivery, failed send, and cutoff;
- normal completion, missing final observation, crash, and launch failure;
- duplicate reports in one measurement scope;
- intentional overlap across jobs;
- missing, invalid, disabled, and accepted participants;
- large exact integer values;
- manifest hashes and exact **RESOURCE_STATS** bytes;
- text and JSON CLI output; and
- ordinary-user execution with no extra privileges or configuration.

## 14. Open-decision shortlist

[GAPS.md](../../research/runtime_resource_proxy_prototype/GAPS.md) is the
authoritative list. The main implementation questions are:

1. Which existing NVFlare component records site-run and measurement-period
   boundaries?
2. What starts and ends a measurement period?
3. How is the first observation protected from job code in that process model?
4. How is the measurement-scope key derived from information NVFlare already
   has?
5. How much crash recovery is possible using only existing workspace and
   message paths?
6. Which existing authenticated path carries the final site report?
7. Is **reconfigured** useful, or can the final-observation comparison explain
   capacity changes without it?
8. Is Linux the first fully supported platform?

Use the GAPS review table for the complete set, constraints, and Phase 2
questions. This shortlist should not be maintained as a second complete list.

## 15. Golden example

The main finalized-job example has four expected participants:

- `site-1` has a complete 37-minute, 3-second report;
- `site-2` has an accepted report with incomplete measurement evidence;
- `site-3` has no valid report before the cutoff; and
- the server has a complete 37-minute, 3-second report.

`site-1` reports 32 visible CPU units, 192 GiB of memory, four A100 80 GB
GPUs, a 1 TiB point-in-time visible workspace-filesystem capacity, a known
empty saved-result set, and 147,700,336,640 bytes of accepted remote F3
payload. Its derived values are:

~~~text
CPU:     32 × 2,223 = 71,136 CPU-unit-seconds
Memory:  192 GiB × 2,223 = 458,290,190,352,384 byte-seconds
GPU:     4 × 2,223 = 8,892 GPU-instance-seconds
~~~

The 1 TiB visible workspace-filesystem capacity observation is not multiplied
by time and is not included in participant or job totals.

The [`site-2` report](../../research/runtime_resource_proxy_prototype/schema/golden/v1/participant_summary_partial_periods.json)
contains a five-minute 16-CPU, 128-GiB, two-GPU period that ends without a
final observation, a five-minute unmeasured gap, and a later 27-minute,
3-second 32-CPU, 192-GiB, four-GPU period. Its report is accepted, but CPU,
memory, and GPU totals are partial. Its saved-result byte count is unavailable
with `not_bound` because no complete result set is known. No compute time is
claimed for the gap.

This example says only that one measurement ended and another later began. It
does not claim that a client disconnected, a process changed, or resources were
released. Those meanings depend on the resource-management architecture.

The [resource summary](../../research/runtime_resource_proxy_prototype/schema/golden/v1/resource_summary.json)
shows all four expected participants, each accepted participant's derived
totals, and the job totals. `site-3` is the missing participant; the server is
accepted rather than being described as interrupted. The server reports the
complete 29,540,266,113-byte saved-result total. Across accepted reports, the
example contains 145,656 CPU-unit-seconds, 986,880,405,405,696 memory
byte-seconds, 15,984 GPU-instance-seconds, and 590,801,346,560 accepted remote
F3 payload bytes.

The scale comes from a completed five-round, two-client Qwen2.5-14B Colossus
qualification. That run used four A100s per client, lasted 37:03, exchanged a
29,540,067,328-byte state in twenty directions, and observed a
29,540,266,113-byte saved result. The golden example is not a replay: its CPU,
memory, visible workspace-filesystem capacity, and measurement-period
partitions are illustrative. The historical run recorded logical tensor size
but did not measure post-encoding
F3 acceptance bytes. The example sets its F3 counters to the derived logical
volume only to use a realistic scale.

Large quantities are stored as decimal strings so JavaScript and other clients
do not lose integer precision.
