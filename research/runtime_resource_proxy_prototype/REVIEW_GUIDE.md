# Phase 1 resource statistics: review guide

This is the best place to start a design review.

## Suggested meeting path

1. Read the idea and hard requirements below.
2. Inspect the generated all-site CLI output.
3. Walk through the four-participant example and its partial-data behavior.
4. Review the collection rules and formulas only where questions arise.
5. End with [GAPS.md](GAPS.md), the authoritative list of remaining decisions.

The field and code catalogs are lookup material. The decision-history document
is optional background and does not belong in the main meeting path.

## The idea in one paragraph

Phase 1 records the CPU, memory, storage, and GPUs that an NVFlare job can see.
It also records one saved-result byte total and NVFlare message payload bytes.
The result is useful for later cost estimation, but it is not utilization,
reserved capacity, or a bill.

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
- [partial-measurement site output](schema/golden/v1/finalized_job/cli/resources-site-2-details.txt)
- [JSON output](schema/golden/v1/finalized_job/cli/resources-all.json)

The text output starts with this label:

> Resources visible to the job while it ran.

## Three plain terms

| Plain term | JSON term | Meaning |
| --- | --- | --- |
| Site report | `participant_summary` | Everything one client or server reports for one job. |
| Measurement period | `attempt` | A start and end time for which one resource observation applies. It is not necessarily a process launch or scheduler attempt. |
| Expected participant list | `participants` | Every client and server the job expects, including entries whose report is missing or invalid. |

These are the names used by candidate schema v1. Human-facing prose should use
the plain terms when that is clearer.

## How the main example fits together

The files under `schema/golden/v1/finalized_job` describe one coherent job:

- `site-1` sent a complete report for one 37-minute, 3-second measurement
  period;
- `site-2` sent an accepted report, but part of its measurement evidence is
  incomplete;
- `site-3` was expected, but no valid report arrived before the cutoff; and
- the server produced and locally contributed a complete report.

For `site-2`, a five-minute period with 16 visible CPU units, 128 GiB of memory,
and two A100 GPUs ended at 14:05 without a final resource observation. Another
period began at 14:10 with 32 CPU units, 192 GiB, and four A100s, then ended at
14:37:03. The five-minute gap is not counted as CPU, memory, or GPU time. The
report itself is accepted, but those three totals are partial because the first
period lacks its final check.

`site-2` has no complete platform-known result set, so its saved-result total is
unavailable. `site-1` reports a known empty result set as zero. The server
reports a complete 29,540,266,113-byte saved-result total. This keeps a real
zero distinct from unavailable data and puts the result where the example says
it was saved.

This example does not claim that a network disconnect ended the first period or
that resources were released during the gap. It shows only facts the data model
can support: one measured period ended and measurement later resumed. The
future resource-management design will determine what events create those
boundaries.

The other JSON files directly under `schema/golden/v1` include focused boundary
examples. They are individually valid, but they are not all events from the
same job. The `finalized_job` directory is the end-to-end reconciled example.

### Why these example values are this size

The scale is based on a completed Colossus Qwen2.5-14B qualification: two
clients used four A100 80 GB GPUs each for five rounds. The NVFlare phase lasted
37:03. Each full model state contained 29,540,067,328 bytes, the twenty state
directions totaled 590,801,346,560 logical bytes (550.23 GiB), and the observed
saved result was 29,540,266,113 bytes (27.51 GiB).

The retained evidence is a **five-round 14B full-model qualification from
2026-07-31**. The generated
[receipt](schema/golden/v1/finalized_job/generation_receipt.json) records the
reference values and the distinction between evidence-based and illustrative
fields.

The golden example is not a replay of that run. Its CPU, memory, storage, and
measurement-period partitions are illustrative. Its F3 values use the derived
logical state volume as a realistic scale, but the historical run did not
record bytes at the proposed post-encoding F3 acceptance boundary. The F3
values are therefore example counters, not recovered benchmark measurements.

There is no proposed `resource.json` record:

| Name | What it is |
| --- | --- |
| `participant_summary.json` | One client or server's detailed input report. |
| `resource_summary.json` | The server's reconciled participant list and job totals. |
| `RESOURCE_STATS` | A byte-identical job-store copy of `resource_summary.json`. |
| `resources-all.json` | Example JSON printed by the CLI; it wraps the resource summary. |

Existing NVFlare files named `resources.json` are unrelated site or component
configuration.

## What one site reports

A site report has three parts:

1. Job-run start and finish facts.
2. Zero or more measurement periods.
3. Facts collected once at the end: one saved-result byte total and F3
   counters.

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

At completion, NVFlare records one exact byte total only when existing platform
state identifies a complete, bounded result set. It calculates the total from
that known set, but exports no per-file data. If it has no such set, the value
is unavailable. The feature adds no artifact registry or job setting and does
not scan unrelated directories. It does not expose filenames or hash model
content.

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

The server validates each final site report and archives the exact accepted
report bytes with the reconciled summary and manifest in the existing server
job workspace. The manifest hashes those archive files. Separately, the server
saves a byte-identical copy of the reconciled `resource_summary.json` in the
job store under the exact component name `RESOURCE_STATS` for queries and
Phase 2.

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

## Remaining decisions

[GAPS.md](GAPS.md) is the authoritative decision list. The main themes are:

- Which existing NVFlare component records job-run and measurement-period
  boundaries.
- What starts and ends a measurement period in the selected process model.
- How a trustworthy pre-job-code observation is made in that model.
- How much site-side data can survive a crash using only existing storage.
- How the measurement-scope key is derived from information NVFlare already
  has.
- Whether `reconfigured` remains useful as an end reason. It no longer implies
  a successor period.

The closed field, formula, privacy, deployment, and storage decisions are
already reflected in the examples and catalogs. Review their rationale only if
needed in [SIMPLIFICATION_REVIEW.md](SIMPLIFICATION_REVIEW.md).

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
