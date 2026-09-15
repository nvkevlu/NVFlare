# Resource statistics schema v1

This directory contains the proposed Phase 1 wire contract.

The contract says what a site reports and how the server calculates totals. It
does not choose whether CP, a job process, a child process, or another NVFlare
component collects the data.

## Files

| File | Purpose |
| --- | --- |
| [resource_stats_v1.schema.json](resource_stats_v1.schema.json) | Closed Draft 2020-12 JSON Schema. |
| [contract_v1.py](contract_v1.py) | Cross-record checks and exact arithmetic. |
| [FIELD_CATALOG.md](FIELD_CATALOG.md) | Every field, type, unit, and limit. |
| [CODE_CATALOG.md](CODE_CATALOG.md) | Every status, issue, and end reason. |
| [golden/v1](golden/v1) | Valid example records and final CLI output. |
| [build_review_artifacts.py](build_review_artifacts.py) | Deterministic generator for the goldens. |

Unknown fields are rejected. New meanings require a new schema version.

## Plain terms and JSON names

| Plain term | JSON name |
| --- | --- |
| Site report | participant_summary |
| Measurement period | attempt |
| Expected participant list | participants |
| Saved-result byte total | retained_content |
| Measurement-scope key | environment_key |

An attempt is a measurement period. It does not imply a process launch,
scheduler attempt, resource lease, or any particular roadmap architecture.

## Record types

The schema accepts exactly eight record kinds:

| Kind suffix | Purpose |
| --- | --- |
| participant_start | Start of one site's job run and its storage observation. |
| attempt_start | Start time and resources for one measurement period. |
| attempt_final | Optional final resource observation for that period. |
| attempt_end | End time and reason for that period. |
| participant_final | End of the site run, one saved-result byte total, and F3 counters. |
| participant_summary | One final site report. |
| resource_summary | Final server result for the job. |
| manifest | Hashes of the stored server files. |

The small start, final, and end records are logical collection fragments. The
schema does not require them to be separate files. participant_summary is the
final site-level record. resource_summary is the result read by the CLI and
Phase 2.

The files under `golden/v1/finalized_job` form one complete example. Its
resource summary combines a stable client, a client with two measured periods
separated by an unmeasured gap, an expected client whose report is missing,
and an accepted server report. The stable client has a known empty result set;
the second client uses `unavailable/not_bound` because it has no complete known
set; and the server has the complete saved-result byte total. Other JSON files
directly under `golden/v1` include standalone boundary cases and are not all
part of that job.

## Architecture and deployment constraints

The schema contains no launcher name, process-coordination token, process ID,
storage path, or resource-manager field.

It requires no new:

- privilege;
- container capability;
- host service;
- mount;
- launcher argument;
- environment variable; or
- user or operator configuration.

The implementation uses normal NVFlare code and existing workspace and message
paths. The component that calls the collector is still an open design choice.

## Identity

**attempt_id** is a random 128-bit ID written as 32 lowercase hexadecimal
characters. It is an internal record ID. The schema does not define how it
crosses process boundaries.

**environment_key** is a job-scoped HMAC value. In prose, it is the
measurement-scope key. It prevents simultaneous reports for the same
measurement scope.

The key is generated from information and key material NVFlare already has. It
needs no new secret or user configuration. Its exact input is open and must be
changed if the selected process model cannot produce it without extra setup.

Periods with the same key may be sequential but may not overlap. Different
keys may overlap. Reports from different jobs may describe the same physical
hardware and are intentionally not deduplicated.

**participant_key** is a job-scoped HMAC used for server file names. The public
participant ID and role appear only in the server's expected participant list.

## Trust model

Resource observations are self-reported by the NVFlare site environment.

If the implementation writes site fragments, it may use the existing job
workspace. Job code may be able to change or remove them, and a crash may lose
them. A local write-once API prevents accidental conflicting writes through
that API, but it is not immutable evidence.

After the server receives a final site report, it validates the report and
stores the exact accepted bytes. The manifest hashes those server-side bytes.
A matching digest proves byte identity, not the truth of the original
observation.

No separate protected site directory is required by this contract.

## CPU

A reported CPU object contains:

- visible_units;
- at least one strong evidence value: affinity_count, cpuset_count, or
  quota_units; or
- online_count only when none of those strong values is available.

visible_units is the minimum of the applicable strong values. If none is
available, it equals online_count.

quota_units is exact quota divided by period, rounded down to at most nine
fractional decimal places. For example:

~~~text
150000 / 100000 = 1.5
1 / 3 = 0.333333333
~~~

Raw quota and period values are not stored.

Model and architecture are optional. A CPU model is present only when all
affinity-visible CPUs normalize to one model.

## Memory

A reported memory object contains visible_bytes and its evidence.

visible_bytes is the smaller finite value from:

- the process-visible memory limit; and
- process-visible physical memory.

An unlimited memory value is omitted. Swap is excluded.

## GPU

A reported numeric GPU inventory requires successful CUDA-runtime enumeration.

The presence of CUDA_VISIBLE_DEVICES may be stored only as the boolean
cuda_mask_present. The raw string is never stored and never provides a numeric
count.

A successful empty CUDA inventory is reported with an empty groups array. An
unavailable CUDA runtime produces an unavailable or error object, not a zero.

NVML may add metadata only to devices already found by CUDA. It cannot add a
device or change a count.

Full GPUs and MIG instances use separate groups. memory_bytes is memory per
visible entity in that group. Different memory values create different groups.

Model, memory, and MIG profile are optional. MIG fields are absent for ordinary
full-GPU data and when no MIG instance is present.

## Storage and saved results

Storage is observed for the filesystem that contains the existing job
workspace. capacity_bytes is the total visible filesystem capacity.

Storage time covers the site job-run interval only when workspace continuity is
known. If continuity is uncertain, storage is partial or unavailable.

The saved-result observation contains only status and a byte count. It does not
expose filenames or hash model content. The collector uses a complete, bounded
file list already known to NVFlare. If no such list exists, the value is
unavailable with `not_bound`. The feature adds no registry or job setting and
does not scan unrelated directories. A partial byte value is only the exact
subtotal for the successfully observed portion; it is not presented as the
complete retained size.

## Measurement periods

A participant_summary contains zero or more attempts. Each attempt has:

- attempt_id;
- environment_key;
- opened_at;
- optional start resource observation;
- optional final resource observation; and
- an end object with closed_at and reason.

opened_at and closed_at must use one NVFlare clock. The period is the half-open
interval from opened_at to closed_at.

A launch_failed period has no start or final observation. Other periods require
a start observation. A final observation is optional.

End reasons are:

- released;
- reconfigured;
- failed;
- terminated; and
- launch_failed.

These reasons describe why the measurement ended. They do not change the
formula. reconfigured does not require or imply another measurement period.

A completed accepted report with no attempts means zero observed compute time
only when NVFlare knows that the attempt list is complete. Otherwise the site
must be missing or invalid.

## Resource-time formulas

For each period:

~~~text
duration_seconds = closed_at - opened_at
cpu_unit_seconds = visible_cpu_units × duration_seconds
memory_byte_seconds = visible_memory_bytes × duration_seconds
gpu_instance_seconds = visible_gpu_count × duration_seconds
~~~

Each product is rounded to nine decimal places with round-half-even before
summing.

The start observation supplies capacity. The optional final observation checks
whether that value remained stable. A missing or numerically different final
makes the affected total partial.

A period with known times but no start observation contributes to measured time
but not a numeric resource total. The resource total is partial or unavailable.

Storage uses the participant start-to-final interval, not each attempt.
The saved-result byte total and F3 counters contribute once per site report.

## F3 counters

The final site record has three counters:

- remote_accepted;
- local_delivered; and
- remote_failed_before_acceptance.

Each counter contains payload_bytes and messages.

Remote accepted bytes are measured after payload encoding and optional
end-to-end encryption, immediately before the normal send. The remote counter
increments only after send acceptance.

Count task request, task response, task result, job application, and job stream
data. Exclude control traffic, workspace transfer, log export, unknown classes,
and resource-summary publication.

Fan-out counts once per destination. Forwarding counts once per sender hop.
Lower-level framing, TLS, compression, and retransmission are outside the
metric.

Before serializing participant_final, NVFlare closes all counters in one
operation. Later callbacks do not change canonical totals.

## Expected participant list

The `participants` array contains every client and server expected for the job,
not just the ones that reported. The server already knows this list and must not
infer it from received resource reports.

At the report cutoff, every expected participant is one of:

- accepted;
- missing;
- invalid; or
- disabled.

Only accepted reports contribute numeric values. Missing or invalid reports
make affected job totals partial.

An accepted report can still contain partial measurements. In the canonical
example, `site-2` has one period without a final resource observation, a gap,
and a later complete period. The gap contributes no compute time. This records
an interruption and later resumption of measurement; it does not identify a
network disconnect, process architecture, or resource-release event.

A retry with identical bytes is accepted as the same report. Different bytes
for an already accepted participant are rejected.

## Server files

The stored tree is:

~~~text
resource_stats/
  resource_summary.json
  manifest.json
  participants/
    <participant_key>.json
~~~

The job-store query component is exactly RESOURCE_STATS. A generic prefix is
not allowed.

The manifest contains the SHA-256 digest of resource_summary.json and every
accepted participant file. The query copy must be byte-for-byte identical to
the stored resource_summary.json.

These files use the job's existing storage, retention, deletion, and
authorization behavior.

## Large numbers

Canonical numeric quantities are strings.

Integer quantities are unsigned decimal strings. Fractional quantities are
plain decimal strings with at most nine fractional digits. Exponents, NaN, and
Infinity are rejected.

Strings preserve values such as byte-seconds that are larger than JavaScript's
safe integer range.

## Privacy

Never store:

- host names or network addresses;
- process IDs;
- GPU UUIDs or PCI addresses;
- raw CUDA masks;
- raw cpuinfo, CPU flags, or topology;
- hardware serial numbers;
- absolute workspace paths; or
- raw command output or exception text.

Normalized CPU and GPU models are optional and may be omitted. This feature
does not add a model-publication setting. Omission does not change a valid
numeric status.

## Validation

Run:

~~~bash
python3 -m unittest discover \
  -s research/runtime_resource_proxy_prototype/tests \
  -p 'test_*.py'
~~~

The Python validator checks relationships that JSON Schema cannot express
cleanly, including:

- CPU selector reconciliation;
- time ordering;
- non-overlapping periods for one measurement-scope key;
- final/start stability;
- exact totals;
- expected participant status;
- manifest hashes; and
- privacy restrictions.

Regenerate examples with:

~~~bash
python3 research/runtime_resource_proxy_prototype/schema/build_review_artifacts.py
~~~
