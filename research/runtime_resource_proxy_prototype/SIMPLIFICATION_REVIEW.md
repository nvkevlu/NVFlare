# Phase 1 simplification decisions

This file records why the current prototype is smaller than earlier drafts. It
is a decision history, not the main review document.

For the current design, read [REVIEW_GUIDE.md](REVIEW_GUIDE.md).

## Latest correction: current adapter is concrete; future architecture is open

An earlier draft treated one item from the NVFlare roadmap's “Possible
Features” list as a settled design. It assumed a particular process model and
special coordination between processes.

That assumption was wrong.

The current design now states:

- The v1 adapter for today's code uses one process-lifetime period in each
  client or server job process and the existing terminal-outcome transport.
- CP may run tasks directly, NVFlare may use child processes, or another design
  may be chosen in future roadmap work.
- A measurement period does not imply a process, allocation, or lease.
- A resource change does not require a successor measurement period.
- Process-specific bootstrap and coordination requirements are removed.
- No new privilege, mount, service, launcher flag, environment variable, or
  user/operator setting is allowed.
- Site files are self-reported until the server receives the final report.

The exact present-day hooks are in
[Current-code integration](CURRENT_CODE_INTEGRATION.md). Choosing those hooks
does not prescribe the future task-runner architecture; a future adapter can
open different periods without changing the records or formulas.

The previous intermediate commit remains in Git history so reviewers can
see exactly what changed.

## Vocabulary reduction

Human-facing documents now use:

| Technical JSON name | Plain term |
| --- | --- |
| participant_summary | site report |
| attempt | measurement period |
| participants | expected participant list |
| retained_content | saved-result byte total |
| environment_key | measurement-scope key |

The exact JSON names remain in schema tables and examples.

## Fields removed or consolidated

Earlier drafts repeated role, source, reason, coverage, trust, and warning fields
inside many nested values.

The current contract keeps:

- role once in the expected participant list;
- one typed object per resource;
- one status on each resource observation or total;
- short issue codes only when a value is not fully reported;
- one final site report;
- one server summary; and
- one manifest.

Saved-result accounting keeps only status and total bytes. Per-file names and
content hashes were removed because Phase 1 does not need them and NVFlare does
not have one universal result-file inventory.

Server warnings are derived from participant status and resource status rather
than copied into another warning array.

## Status decisions

Point-in-time CPU, memory, GPU, and visible workspace-filesystem capacity observations use
reported, unavailable, or error. Saved-result and F3 observations may also use
partial when usable numeric data has incomplete coverage.

Expected participants use:

- accepted;
- missing;
- invalid; and
- disabled.

Totals use:

- reported;
- partial; and
- unavailable.

The smaller issue-code list is:

- not_bound;
- counter_gap;
- observation_incomplete;
- attribution_incomplete;
- unsupported;
- permission_denied;
- dependency_missing; and
- malformed_source.

The resource name supplies context. For example, GPU plus dependency_missing is
enough; a second code such as gpu_library_missing is unnecessary.

## CPU decisions

Keep only evidence that explains the selected CPU value:

- affinity_count;
- cpuset_count;
- quota_units; or
- online_count as the fallback.

Do not store raw quota_us or period_us.

quota_units is exact quota divided by period, rounded down to at most nine
decimal places. For example:

~~~text
150000 / 100000 = 1.5
1 / 3 = 0.333333333
~~~

CPU model and architecture are optional. A heterogeneous visible CPU set omits
the model instead of inventing a representative model.

## GPU decisions

A numeric count comes only from successful CUDA-runtime enumeration.

A raw CUDA_VISIBLE_DEVICES value is not a count. NVML may add metadata for
CUDA-found devices, but it cannot add a device.

Full GPUs and MIG instances stay in separate groups. Model and per-device memory
are optional. MIG profile is present only for a MIG group. CLI MIG output
appears only when the selected data contains a positive MIG value.

A successful empty CUDA inventory remains useful as the generic no-visible-GPU
case. It no longer appears as a required consequence of resource release.

## Time decisions

The JSON name attempt remains for compatibility, but it means a measurement
period.

For each complete period:

~~~text
CPU, memory, or GPU time = observed capacity × (closed_at - opened_at)
~~~

Both times use one NVFlare clock. The schema does not choose which component
provides the clock.

The optional final observation checks whether the startup value remained
stable. Missing or changed final data makes the affected total partial.

The reconfigured reason is diagnostic only. It does not require another period
and does not affect arithmetic.

## Storage decisions

Visible workspace-filesystem capacity and saved-result bytes are different values.

- Visible workspace-filesystem capacity is observed at participant start and final for
  only the filesystem containing the existing NVFlare job workspace. Other
  mounted filesystems are not enumerated or summed.
- The saved-result byte total is the exact sum for a complete result set
  NVFlare already knows about.

The two capacity observations are independent. V1 does not calculate or
aggregate storage capacity-time because a shared filesystem cannot be
attributed to the job without extra privileges or configuration. The value is
not usage, allocation, billable storage, or storage owned by the job. No extra
volume or mount is introduced.

Site fragments are normal self-reported workspace files. They can be lost or
changed before the server receives the final report. Server-side accepted files
use existing server job storage and the manifest. The reconciled summary also
remains in that archived workspace; there is no separate query copy.

## F3 decisions

Keep only three final counters:

- remote accepted;
- local delivered; and
- remote failed before acceptance.

Count application payload bytes at the approved F3 boundary. Do not store
headers, TLS overhead, lower-layer retransmissions, or individual messages.

The final report closes the counters once. Resource-summary publication is
excluded through platform code so job code cannot spoof the exclusion.

## Server and CLI decisions

The server uses the expected participants already known to the job. It marks
each one accepted, missing, invalid, or disabled at the cutoff.

The server stores the bundle in the job's existing `workspace` archive. The
query handler reads fixed `resource_stats/...` ZIP members and does not accept
caller-selected archive paths.

The CLI uses:

- STATUS for report acceptance;
- QUALITY for measurement completeness;
- MEASURED TIME for the sum of reported periods; and
- Totals from received reports for the aggregate.

The default table and totals omit visible workspace-filesystem capacity and any
storage-time measure. The point observations remain in the participant report;
the CLI does not invent a cross-participant capacity total.

The CLI starts with the short label `Resources visible to the job while it ran.`

## Decisions still open

This history does not maintain another decision list. See
[GAPS.md](GAPS.md) for the current authoritative questions.
