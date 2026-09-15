# Open resource-statistics decisions

These are decisions, not current requirements.

Any answer must preserve this deployment rule:

> Resource statistics must work with existing NVFlare permissions and setup.
> No new privilege, mount, service, launcher setting, environment variable, or
> user/operator configuration may be required.

## Process and timing

| Question | Why it matters | Allowed direction |
| --- | --- | --- |
| Which existing NVFlare component records a site's start and finish? | The schema needs start and end times but must not choose the task architecture. | CP, a job process, a child-process parent, or another existing platform component may do it. |
| What starts and ends a measurement period? | Capacity is multiplied by this duration. | Define it after the resource-management process model is chosen. |
| Can resource changes be observed during one site run? | Without an event, a startup value may become stale. | Record another period when the chosen design exposes a reliable event; otherwise use the final observation and mark the total partial. |
| Is the reconfigured end reason useful? | Arithmetic does not need it. | Keep it as a diagnostic only, or remove it before v1 is final. It must not imply a successor period. |
| Which clock supplies both period timestamps? | Mixing clocks can create wrong durations. | Use one clock already available to the selected NVFlare component. |

## Initial observation

| Question | Why it matters | Constraint |
| --- | --- | --- |
| Where can NVFlare observe resources before job code can change the result? | A job-provided sitecustomize or import path may run before a normal entry function. | Use an existing platform call site. Do not add operator setup or extra privilege. |
| What happens when a launch mode cannot provide that boundary? | The result would not be trustworthy. | Mark the affected value unavailable; do not weaken the requirement or invent a privileged collector. |

The earlier isolated-bootstrap and launcher-argument prototype has been removed.
It was one possible implementation, not an approved requirement.

## Identity and duplicate reports

| Question | Why it matters | Constraint |
| --- | --- | --- |
| How is environment_key derived? | It prevents two ranks in one measurement scope from reporting the same capacity at once. | Use only information NVFlare already has. No user value or new launcher argument. |
| What is one measurement scope for multi-node work? | A process-visible value may cover only one node. | Report the actual scope. Do not present a partial scope as whole-participant capacity. |
| Is the 4,096-period bound sufficient? | Very long jobs might create many periods. | Confirm with real workloads before v1 is fixed. |

## Site files and crashes

| Question | Why it matters | Constraint |
| --- | --- | --- |
| How much data survives a process or pod crash? | Site fragments in the normal workspace may be lost. | State actual coverage honestly. Do not require a new mount, service, or privileged storage path. |
| Can the selected component write a final report after a child fails? | Partial data is useful only when the platform still has it. | Use existing NVFlare state and message paths; otherwise mark the site missing or partial. |
| How is workspace continuity established for storage time? | Filesystem capacity cannot be multiplied across a period when the workspace was absent. | Report storage time only for an interval the platform can support. |

Site-side files are self-reported and not immutable. Server-side accepted
participant files are protected by existing server job storage after receipt;
only the reconciled summary is copied to the `RESOURCE_STATS` job-store
component.

## Delivery and server finalization

| Question | Why it matters | Options |
| --- | --- | --- |
| Which existing authenticated path carries the final site report? | The report must arrive without a second completion wait. | Extend the terminal job-outcome exchange or add a bounded internal accounting message. |
| What is the report cutoff? | The server needs a fixed time to classify missing reports. | Tie it to existing job finalization and document late-report behavior. |
| How are duplicate retries handled? | A lost acknowledgement must not create a second report. | Accept identical bytes; reject different bytes after first acceptance. |
| How is the server's own report ingested? | It should use the same schema without pretending to send remotely. | Validate and store it through the same internal acceptance API. |

## Resource adapters

| Question | Why it matters | Constraint |
| --- | --- | --- |
| Which CUDA API and versions are supported? | Numeric GPU counts depend on successful runtime enumeration. | The raw CUDA mask is never count authority. NVML can enrich only matched devices. |
| Which operating systems are in the first supported implementation? | CPU, memory, and model probes are platform-specific. | Choose the initial support matrix from ordinary-user evidence; unsupported platforms report unavailable. |
| Which CPU model normalizer is used on each OS? | Raw model strings may expose too much or split equivalent models. | Use a bounded normalized value; omit it for heterogeneous visible CPUs. |
| Which filesystems can prove continuity? | Shared and ephemeral filesystems have different behavior. | Keep the visible-capacity qualification and never claim ownership. |
| Which existing NVFlare state identifies the complete saved-result set? | Exact size requires a complete, bounded set. | Use existing platform state. If none exists, report unavailable; do not add a registry, job setting, or arbitrary path scan. Store only the total bytes, not filenames or content hashes. |

## F3 integration

The code still needs a concrete hook that:

- counts only approved job traffic;
- counts remote bytes after encoding and optional end-to-end encryption;
- increments remote totals only after send acceptance;
- keeps local delivery and pre-acceptance failure separate;
- counts fan-out per destination and forwarding per sender hop;
- closes counters before the final report; and
- excludes resource-summary publication through platform code.

The hook must use the existing F3 path. It may not add a permission or setting.

## Phase 2

The team must choose:

- final resource_proxy field names;
- job-only versus per-site publication;
- whether hardware models may be published;
- the JobStatsReporter event type and payload limit;
- retry duration and duplicate-delivery behavior;
- which already-active reporter or reporters publish the Phase 1 subset; and
- how it coexists with current JobStatsReporter utilization output.

Phase 2 reads only finalized RESOURCE_STATS data. It does not solve any Phase 1
collection or process-model question.

## Closed decisions (reference only)

These are no longer open:

- no extra privileges or configuration;
- no scheduler, container, cloud, or billing APIs;
- CUDA runtime is the only numeric GPU-count authority;
- full GPUs and MIG instances are separate;
- raw identity and topology fields are excluded;
- missing data is not zero;
- the server component name is exactly RESOURCE_STATS; and
- the resource-statistics schema does not choose the roadmap process model.

The rationale is kept in [SIMPLIFICATION_REVIEW.md](SIMPLIFICATION_REVIEW.md)
and does not need to be presented unless a closed point is reopened.
