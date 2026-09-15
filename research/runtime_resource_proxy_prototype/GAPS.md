# Remaining implementation and product gaps

The candidate-v1 field design is now decided: typed resources, exact statuses/issues, normalized
CPU evidence, optional privacy-controlled hardware models, full final capacity when available,
parent/server-derived resource time, five F3 facts, immutable participant summaries, compact
roster/totals, and a path-plus-digest manifest. See the
[accepted decision record](SIMPLIFICATION_REVIEW.md).

The realistic captures under `generated/` remain pre-v1 probe evidence. The files under
[`schema/golden/v1/`](schema/golden/v1/) are the canonical format examples.

## Integration work still required

| Gap | Required result | Why the prototype cannot settle it alone |
| --- | --- | --- |
| Sanitized bootstrap | Every process, Docker, Kubernetes, and Slurm launcher enters a platform-owned bootstrap before custom imports and passes the platform-minted attempt ID through an exact argument allowlist. | A launch-plan fixture is not an installed launch path. |
| Parent-owned durable handoff | Authenticate start/final fragments and store accepted bytes write-once outside the child-writable job area; define recovery after parent or node failure. | Child files and Kubernetes `emptyDir` are self-reported and may disappear. |
| CUDA/NVML adapter | Package a supported CUDA-runtime enumeration adapter and optional matched-device NVML enrichment; test driver/runtime combinations and MIG. | NVFlare does not currently require CUDA Python, and runtime availability varies. |
| CPU/cgroup implementation | Implement effective v1/v2/hybrid ancestor traversal and test affinity-only, cpuset-only, quota-only, unlimited, malformed, and unreadable cases. | A readable leaf may not be the effective CPU boundary. |
| Memory/cgroup implementation | Implement equivalent ancestor/unlimited/malformed handling and physical-memory fallback tests. | A malformed or host-visible value must not become zero or a reservation claim. |
| CPU model normalization | Define the exact platform-specific whitelist/normalizer and prove that model is emitted only for a homogeneous affinity-visible set. | The schema fixes the behavior but not every OS parsing adapter. |
| GPU model normalization | Define the CUDA property normalization and optional NVML merge behavior without retaining UUID/BDF identity. | Packaging and driver behavior must be tested on real supported GPUs. |
| Reporter lease | Mint and authenticate one execution-environment key and at most one active trusted reporter lease per job/environment, including multi-node jobs. | The contract rejects overlapping claims and permits sequential retries, but cannot create platform identity. |
| Artifact registry | Add narrow registration/freeze APIs, approved result roots, descriptor-based regular-file sizing, symlink/change handling, and retry behavior. | NVFlare has no central final-result registry today. |
| F3 lifecycle hook | Bind attempt-local counters to trusted CellNet job identity and sender acceptance; test retries, forwarding hops, local delivery, failures, summary exclusion, and cutoff races. | Message labels and payload fields are spoofable and cannot establish attribution. |
| Participant delivery | Choose a bounded authenticated outbox/retry path and surface missing coverage when delivery fails by the cutoff. | A valid local participant file can otherwise be absent at the server. |
| Server materializer | Freeze the roster/cutoff, apply first-valid immutable acceptance, derive participant/job totals, write the archive/manifest, and save the exact query copy. | The schema describes this result; production code does not yet create it. |
| Bundle verification | Verify the summary, every accepted participant file, exact manifest membership/digests, and byte-identical `RESOURCE_STATS` copy together. | A standalone JSON Schema cannot open sibling files or authenticate storage. |
| CLI integration | Add all-site and selected-site human/JSON paths plus missing, unknown, disabled, not-ready, unavailable, corrupt, and adaptive-MIG cases. | Golden output exists, but the production command and error wiring do not. |
| Phase 2 telemetry | Have `JobStatsReporter` consume only validated finalized Phase 1 data; choose bounded metric/label names and optional model-label policy. | Telemetry backend cardinality and privacy require integration review. |
| Retention and cloning | Decide enablement default, archive retention, deletion behavior, and guarantee that cloned jobs start with no inherited statistics. | These are product lifecycle policies, not record-shape questions. |
| Non-Linux behavior | Decide which platforms are unsupported versus allowed to report an explicit host-visible fallback. | macOS probes can return real host values but cannot prove Linux affinity/cgroup containment. |

## Required trust checks outside JSON

Production readers must receive authenticated expected job, participant, attempt, execution-
environment, role, and roster context. They must compare the record with that context before
acceptance. Shape and digest validation cannot make a child claim authoritative by themselves.

Participant replay handling must be atomic:

1. reject a candidate that arrives after the fixed cutoff;
2. validate and authenticate it before reserving the participant slot;
3. accept the first valid digest;
4. treat an identical digest retry as success/no-op; and
5. reject a different digest rather than interpret it as a revision.

## Manageable next fixtures

These additions improve confidence without requiring all production hooks at once:

- CPU and memory selector matrices, including malformed and fallback cases;
- homogeneous, heterogeneous, and site-suppressed CPU/GPU model cases;
- numeric boundary/overflow and decimal-rounding examples;
- identical-retry and conflicting-replacement participant acceptance tests;
- changed-final and missing-final resource-time cases;
- manifest corruption and extra/missing participant-file cases;
- each CLI error path plus selected-site/detail output; and
- F3 zero-byte messages, counter gaps, unavailable counters, and cutoff boundary races.

The remaining gaps are implementation and product-policy work. They are not reasons to restore
the removed generic metric metadata, caveat catalogs, participant revisions, or duplicated
participant detail in the resource summary.
