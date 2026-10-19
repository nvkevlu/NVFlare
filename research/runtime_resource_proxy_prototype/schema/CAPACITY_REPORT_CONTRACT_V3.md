# Participant capacity reports

Updated October 19, 2026. Schema 3.0 stores the resource capacities observed by
the participant's job process, rather than storing capacity multiplied by
elapsed seconds. A normal report therefore exposes CPU units, memory bytes,
and CUDA-device counts directly. Job and study queries calculate capacity-time
from these values when needed.

## What is measured

The measurement boundary is unchanged: the job process probes capacity after
normal workspace preparation and before application construction. It sends one
final report during the existing completion flow. This change adds no probe,
startup wrapper, privilege, dependency, configuration, or resource-release step.

CPU units start with the allowed logical-CPU count, falling back to the machine's
online count when necessary, and apply smaller readable CPU-set and quota
limits. A quota is CPU time divided by its period, not a set of pinned CPU IDs.
Memory bytes are physical memory capped by readable memory limits. GPU count
is the CUDA Driver's execution-visible count; optional NVML classification
cannot remove a counted device. These are observations of visible capacity,
not reservations or proof of actual resource use.

## Normal stored record

```json
{
  "resource_capacity": {
    "measured_seconds": "10",
    "cpu": {"groups": [{"units": "32", "model": "AMD EPYC", "architecture": "x86_64"}]},
    "memory": {"bytes": "68719476736"},
    "gpu": {"groups": [{"kind": "full_gpu", "count": "2", "model": "NVIDIA A100"}]}
  }
}
```

The duration covers the interval assigned to that observed capacity, including
waiting. It is not GPU busy time or the entire submission-to-archive lifecycle.
The collector uses its existing monotonic clock. CPU consumption still has its
own CPU-seconds value and matching elapsed duration.

Numbers remain decimal strings, with at most nine fractional digits. CPU units
may be fractional. Memory bytes and GPU counts must be integer-valued. CPU
capacity is positive and at most 1,048,576 units; a memory value is positive and
at most an unsigned 64-bit integer. GPU groups have positive counts whose sum
is at most 4,096. An observed GPU count of zero is an empty groups array.
Hardware descriptions are optional; raw device IDs and environment values are
not saved. Numeric values and descriptions cannot be null. Unknown resource
members are omitted under a partial block, or the whole block is unavailable.
The elapsed duration is nonnegative and bounded by the unsigned 128-bit limit.
Products and sums obey that same bound, with at most nine fractional digits
and round-half-even for finer product fractions.

## Missing values and capacity changes

Successful measurements omit status and issues. A partial measurement keeps
known values with the existing issue codes; unavailable contains only status
and issues. GPU unavailability does not erase known CPU or memory capacity.

An unreadable or malformed CPU/RAM limit does not discard another usable
value. Keep the smallest usable capacity and mark the block `partial` with
`observation_incomplete` when a restriction cannot be checked. Using the
online CPU count because affinity is unavailable has the same indication.
An absent controller or explicitly unlimited limit is not a failed read.
A missing file required by an assigned v1 controller is. These best-effort
values may exceed the actual process limit; unavailable is reserved for a
dimension with no usable positive value. No additional status, source field,
or issue code is required.

The block can be partial even when CPU, RAM, GPU, and duration are all present.
This records uncertainty in a limit or earlier observation, not necessarily a
missing field. Preserve its covered seconds and available values through the
handoff, job summary, and query calculations. The same block-level indication
marks derived capacity-time; CPU consumption retains its independent status.
The record does not identify a particular failed bound.

A malformed measurement in the child handoff makes only that measurement
unavailable with `malformed_source`; valid sibling measurements remain usable.
Malformed JSON, identity, or the handoff envelope is still rejected as a whole.
Server reception validates the complete public report as before.

Today's launch paths probe once. The existing capacity-change hook can close
an interval and record another observation. If it is used, the final report
stores an `intervals` list instead of a single flat CPU/memory/GPU snapshot.
Each interval has its raw capacity and its own measured seconds. The outer
duration equals the sum of those covered intervals. Identical consecutive
observations are combined. Unknown gaps are not included and mark coverage
partial. The list is bounded to 4,096 intervals and by the existing report-size
limit.

This exceptional form prevents multiplying an initial two-GPU observation by
time after a known GPU release. It does not introduce a supervisor or choose a
future launcher architecture. It also does not discover unreported changes.
The CLI shows a stable observed value when all intervals agree, or `varies`
when they differ; JSON retains the individual observations.

## Query calculations

For each covered interval, multiply CPU units, memory bytes, or GPU count by
that interval's seconds. Add the products for participant, job, and study
capacity-time views. Products are calculated with bounded decimal arithmetic
and are not copied into stored participant or job-summary records.

For the example above, a query can derive 320 CPU-unit seconds, 687,194,767,360
memory byte-seconds, and 20 CUDA-device seconds. It never sums filesystem
capacity or calculates filesystem capacity-time. Retained-file bytes,
communication counters, and actual CPU seconds retain their existing meanings.

## One supported format

This feature has not been released. Live reports, private handoffs and archive
queries support only the current raw-capacity format, labeled schema 3.0.
Keeping that label avoids an unnecessary renumbering; it does not imply
compatibility with earlier experiments. Earlier prototype reports are not
accepted, converted or read through a compatibility path.

Study queries have one derived `totals` object for included jobs. They do not
carry a version field on each job or separate version groups. Study coverage
separately identifies jobs without a usable report and jobs that are still
running. Stored participant and job reports still contain no derived totals.

Older captured runs remain historical evidence in the preserved prototype
worktree. They are not rewritten as newly collected capacity reports.

## Best-effort collection

Keep the existing measurement methods and ordinary Python startup behavior.
The implementation adds no mandatory dependency, privilege or deployment
configuration. GPU collection uses the system CUDA Driver; optional NVML
classification cannot erase its count. CPU consumption uses process and
waited-child counters, not an isolated-group counter. Missing values stay
missing rather than becoming zero or preventing the job from finishing.

The final client report is attached to the existing job-completion notification.
A separate statistics message is only a fallback if that integration is
rejected in review, not a second implementation requirement.

Start with the [simple design](../../../docs/design/resource_statistics_simple_design.md)
for the end-to-end explanation. The
[implementation guide](../../../docs/design/resource_statistics_implementation_blueprint.md)
links the collection, completion, server and query code.
