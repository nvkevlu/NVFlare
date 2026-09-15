# Phase 1 resource statistics: review guide

This is the best place to start a design review.

## The idea in one paragraph

Phase 1 records the CPU, memory, storage, and GPUs that an NVFlare job can see.
It also records saved-result sizes and NVFlare message payload bytes. The result
is useful for later cost estimation, but it is not utilization, reserved
capacity, or a bill.

This design defines the data and the calculations. It does **not** choose how
NVFlare will run tasks. CP may run tasks directly, NVFlare may use child
processes, or the resource-management work may choose another design. All of
those implementations can produce the same report.

## Hard requirements

These requirements come from the Phase 1 source document and the latest review:

- Run with the permissions NVFlare already has.
- Require no root access or privileged container.
- Require no host agent, Docker socket, additional Kubernetes RBAC permission,
  cloud permission, or Slurm administrator access.
- Require no new mount, sidecar, service, launcher flag, environment variable,
  operator setting, or deployment setup.
- Read values from the environment where the job runs. Do not read scheduler
  requests, container specifications, cloud metadata, or billing data.
- A failed or slow probe must not fail the job.
- Do not turn missing data into zero.

NVFlare itself will need code changes. Users and operators should not need to
change how they install, configure, launch, or run a job.

## What the user sees

The proposed command is:

```text
nvflare job resources JOB_ID
nvflare job resources JOB_ID --site site-1
nvflare job resources JOB_ID --format json
```

The full generated examples are:

- [all-site text output](schema/golden/v1/finalized_job/cli/resources-all.txt)
- [one-site text output](schema/golden/v1/finalized_job/cli/resources-site-1-details.txt)
- [JSON output](schema/golden/v1/finalized_job/cli/resources-all.json)
- [partial multi-period output](schema/golden/v1/finalized_job/cli/resources-partial-periods.txt)

The text output starts with this warning:

> Resources visible to the job while it ran. These are not utilization,
> reserved capacity, or billing data.

## Three plain terms

| Plain term | JSON term | Meaning |
| --- | --- | --- |
| Site report | `participant_summary` | Everything one client or server reports for one job. |
| Measurement period | `attempt` | A start and end time for which one resource observation applies. It is not necessarily a process launch or scheduler attempt. |
| Expected participant list | `roster` | The clients and server that the job already expects. It is used to show missing reports. |

The JSON names remain unchanged because they are already used by the prototype.
Human-facing prose should use the plain terms.

## What one site reports

A site report has three parts:

1. Job-run start and finish facts.
2. Zero or more measurement periods.
3. Facts collected once at the end: saved-result sizes and F3 counters.

Each measurement period contains:

- a random internal ID;
- an internal measurement-scope key used to avoid duplicate simultaneous
  reports;
- a start and end time from one NVFlare clock;
- CPU, memory, and GPU values observed at the start; and
- an optional final observation.

The scope key is generated inside NVFlare. It requires no user setting, process
argument, or launcher change in the data contract. The implementation may use a
different internal mechanism as long as duplicate reports are handled.

The contract does not require another period after a resource change. If the
chosen implementation observes a later period, it may record one. If the final
observation differs from the start, or is missing, the affected totals are
marked partial.

## How the values are collected

### CPU

NVFlare reads the CPU affinity, effective CPU set, and finite CPU quota that the
process can see. It uses the smallest applicable value. If none is available,
it falls back to the online CPU count.

`quota_units` is quota divided by period. It is rounded down to at most nine
decimal places so the report never overstates capacity.

The normalized CPU model and architecture are optional. If the visible CPUs
have different models, the model is omitted.

### Memory

NVFlare uses the smaller of:

- a finite memory limit visible to the process; and
- physical memory visible to the process.

Swap is not included.

### GPU

A numeric GPU count requires successful CUDA-runtime enumeration. A raw
`CUDA_VISIBLE_DEVICES` string is diagnostic only and never creates a count.

NVML may add model and memory details only for devices CUDA already found. It
cannot add devices or change the count.

Full GPUs and MIG instances remain separate. MIG fields and CLI columns appear
only when a positive MIG value exists.

### Storage

NVFlare reads the capacity of the filesystem that contains the existing job
workspace. No new volume or mount is required.

Storage time is reported only when NVFlare can establish that the workspace was
available for the stated interval. Otherwise the result is partial or
unavailable.

### Saved results

At completion, NVFlare records exact sizes only when existing platform state
provides a complete, bounded list of result files. If it has no such list, this
value is unavailable. The feature adds no artifact registry or job setting and
does not scan unrelated directories.

### Network

The primary network value is the F3 application payload accepted for remote
send. Local delivery and failure before remote acceptance are separate
counters.

These counts exclude transport headers, TLS, retransmissions, and general
operating-system traffic. They are not cloud-billed network bytes.

## How time-based totals are calculated

For one complete measurement period:

```text
duration = end time - start time
CPU time = visible CPU units × duration
memory time = visible memory bytes × duration
GPU time = visible GPU instances × duration
```

Storage uses the site job-run interval when workspace continuity is known.
Saved-result bytes and F3 counters are added once, not once per measurement
period.

Different sites may be using the same physical machine or shared storage.
Therefore a job total is a sum of received reports, not a claim about physical
capacity.

## Missing and partial data

The allowed states depend on the kind of fact:

| Fact | Allowed states |
| --- | --- |
| CPU, memory, or GPU at one point in time | `reported`, `unavailable`, `error` |
| Storage, saved results, or F3 counters | `reported`, `partial`, `unavailable`, `error` |
| Derived resource-time total | `reported`, `partial`, `unavailable` |

`partial` means usable numeric data exists but some coverage is missing.
Point-in-time CPU, memory, and GPU cannot be partial: NVFlare either obtains a
valid selected value at that moment or it does not.

The expected participant list uses:

| State | Meaning |
| --- | --- |
| `accepted` | A valid final site report was received. |
| `missing` | A report was expected but did not arrive. |
| `invalid` | A report arrived but failed validation. |
| `disabled` | Collection was already disabled by existing policy. No new setting is introduced here. |

The short issue codes are defined in
[CODE_CATALOG.md](schema/CODE_CATALOG.md). They are intentionally generic so
the resource name does not have to be repeated in every code.

## Storage and trust

The schema does not require site-side fragment files. The prototype shows one
best-effort option that writes them in the existing job workspace. If an
implementation uses that option, the files are self-reported rather than
immutable: job code may change or remove them, and a crash may lose them.

The server validates the final site report and stores the accepted bytes in the
existing job store under the exact component name `RESOURCE_STATS`. The
manifest hashes those server-side files.

This prototype does not require a separate protected site directory. If
stronger crash recovery is later needed, the team must choose a solution that
still satisfies the no-new-privileges and no-new-configuration requirements.

## Security boundary

The first observation must come from NVFlare platform code before job code can
change the result. The exact call site depends on the process model that the
resource-management work selects.

An earlier prototype prescribed process-specific bootstrap and launch changes.
They are no longer part of this design.

If the selected process model cannot provide a trustworthy initial observation
without extra privileges or operator setup, the value must be marked
unavailable. The implementation must not weaken the deployment constraints.

## What is agreed and what is still open

### Agreed

- Field types, units, bounds, privacy rules, and status codes.
- CPU and memory selection rules.
- CUDA-runtime authority for GPU counts.
- Resource-time formulas.
- F3 counter meanings.
- The exact `RESOURCE_STATS` server component.
- CLI behavior and golden examples.
- No extra privileges, configuration, or deployment setup.
- The data contract does not choose the task process model.

### Open

- Which existing NVFlare component records job-run and measurement-period
  boundaries.
- What starts and ends a measurement period in the selected process model.
- How a trustworthy pre-job-code observation is made in that model.
- How much site-side data can survive a crash using only existing storage.
- How the measurement-scope key is derived from information NVFlare already
  has.
- Whether `reconfigured` remains useful as an end reason. It no longer implies
  a successor period.

These are listed in [GAPS.md](GAPS.md) as decisions, not requirements.

## File map

| File | Purpose |
| --- | --- |
| [Implementation plan](../../docs/design/job_resource_statistics_implementation_plan.md) | Agreed behavior, open integration decisions, and implementation slices. |
| [Phase 2 sketch](../../docs/design/job_resource_statistics_phase2_telemetry_sketch.md) | How `JobStatsReporter` may publish a finalized Phase 1 result. |
| [Schema guide](schema/README.md) | Exact record shapes and calculations. |
| [Field catalog](schema/FIELD_CATALOG.md) | Every field, type, and unit. |
| [Code catalog](schema/CODE_CATALOG.md) | Every status, issue, and end reason. |
| [JSON Schema](schema/resource_stats_v1.schema.json) | Machine-readable structure. |
| [Validator](schema/contract_v1.py) | Cross-record and arithmetic checks. |
| [Artifact generator](schema/build_review_artifacts.py) | Rebuilds the golden JSON and CLI output. |
| [Open decisions](GAPS.md) | Questions that the resource-management design must answer. |

## Rebuild and test

```bash
python3 research/runtime_resource_proxy_prototype/schema/build_review_artifacts.py
python3 -m unittest discover \
  -s research/runtime_resource_proxy_prototype/tests \
  -p 'test_*.py'
```
