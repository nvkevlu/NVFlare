# Remaining implementation and product gaps

The candidate-v1 field design is ready for review: typed resources, exact statuses/issues, normalized
CPU evidence, optional privacy-controlled hardware models, full attempt-final capacity when
available, supervisor/server-derived resource time, three F3 facts, immutable participant
summaries, compact roster/totals, and a path-plus-digest manifest. See the
[candidate decision record](SIMPLIFICATION_REVIEW.md).

The lifecycle shape now assumes the GPU-release roadmap rather than treating one job process as
one attempt. A durable GPU-free supervisor owns the logical participant. Each attempt is one
stable `(resource lease, reporter environment, CPU/memory/GPU vector)` window; one allocation may
contain concurrent environments or several sequential vectors. Persistent storage, retained
content, and F3 belong to the participant lifetime. The remaining work is binding that contract
to the in-flight resource-release implementation without coupling it to a particular process
topology.

The F3 implementation must use the closed candidate-v1 classification. Included classes are
`task_request`, `task_response`, `task_result`, `job_application`, and `job_stream_data`;
`job_stream_control`, `bulk_envelope`, `workspace_transfer`, `platform_control`, `log_export`,
unknown classes, and summary publication are excluded. Bytes are measured after payload encoding
and optional end-to-end encryption, immediately before direct delivery or remote send. They are
counted once per destination and participant sender hop, with remote traffic recorded only after
send acceptance and direct delivery kept separate.

The realistic captures under `generated/` remain pre-v1 probe evidence. The files under
[`schema/golden/v1/`](schema/golden/v1/) are the canonical format examples.

## Integration work still required

| Gap | Required result | Why the prototype cannot settle it alone |
| --- | --- | --- |
| Roadmap supervisor hook | Bind logical participant start/final, acquire/resume, release confirmation, preemption, checkpoint recovery, and terminal delivery to the durable GPU-free supervisor. | The contract is topology-neutral; only the in-flight resource-release implementation can choose its concrete CP/CJ/worker hooks. |
| Sanitized bootstrap/acquire hook | Launch an absolute platform-owned bootstrap artifact with `python -I -S`, a platform-owned cwd, and a fixed minimal pre-Python environment allowlist. Record `opened_at` at confirmed acquire, pass the attempt ID and opaque supervisor-handoff locator through each launcher allowlist, and enable custom imports only after snapshot acceptance. | `-S -m` remains shadowable through cwd; a launch-plan fixture is not an installed launch path. |
| Supervisor-owned durable handoff | Authenticate untimed worker snapshots and store accepted bytes write-once outside disposable workers; use one owner clock for `opened_at`/`closed_at`; define recovery after supervisor or node failure. | Worker files and Kubernetes `emptyDir` are self-reported and may disappear with the allocation. |
| CUDA/NVML adapter | Package a supported CUDA-runtime enumeration adapter and optional matched-device NVML enrichment. Every GPU-vector transition must probe after visibility is applied in a fresh/CUDA-uninitialized worker or helper; zero requires successful empty enumeration. | NVFlare does not currently require CUDA Python, runtime availability varies, and initialized CUDA state cannot be assumed to reset. |
| CPU/cgroup implementation | Implement effective v1/v2/hybrid ancestor traversal and test affinity-only, cpuset-only, quota-only, unlimited, malformed, and unreadable cases. | A readable leaf may not be the effective CPU boundary. |
| Memory/cgroup implementation | Implement equivalent ancestor/unlimited/malformed handling and physical-memory fallback tests. | A malformed or host-visible value must not become zero or a reservation claim. |
| Participant storage lifecycle | Capture persistent run-filesystem capacity at logical participant start/final, and prove continuous workspace availability before multiplying across release/resume. Otherwise emit partial/unavailable. | The concrete persistent workspace and recovery guarantee comes from the roadmap implementation. |
| CPU model normalization | Define the exact platform-specific whitelist/normalizer and prove that model is emitted only for a homogeneous affinity-visible set. | The schema fixes the behavior but not every OS parsing adapter. |
| GPU model normalization | Define the CUDA property normalization and optional NVML merge behavior without retaining UUID/BDF identity. | Packaging and driver behavior must be tested on real supported GPUs. |
| Reporter lease | Mint one environment key per reporter boundary; allow concurrent distinct environments; reject same-environment overlap; and have the trusted lifecycle authority assert an exact-boundary same-environment successor for **reconfigured** (rejecting equal snapshots when both are comparable) without misclassifying an adjacent full release/reacquire. | The contract validates shapes but cannot create trusted environment identity or drive production transitions. |
| Attempt volume | Confirm that the 4,096-attempt participant bound is operationally sufficient or specify bounded batching/paging for very long per-round allocation jobs. | The likely number of release/resume cycles depends on production workflows and scheduling policy. |
| Artifact registry | Add narrow registration/freeze APIs, approved result roots, descriptor-based regular-file sizing, symlink/change handling, and retry behavior. | NVFlare has no central final-result registry today. |
| F3 lifecycle hook | Bind the three all-job counters to trusted participant/CellNet identity across worker transitions; enforce the exact traffic-class allowlist/exclusions, post-encode/encryption payload sizing, per-destination/per-hop counting, remote acceptance, separate direct delivery, atomic freeze before participant-final serialization, ignored callbacks after freeze, and platform-only summary exclusion without circular counters. | Message labels and payload fields are spoofable and disposable worker counters cannot establish complete job attribution. |
| Participant delivery | Choose a bounded authenticated client outbox/retry path, plus equivalent local durable ingestion for the server participant, and surface missing coverage by cutoff. | A valid local participant file can otherwise be absent from server materialization. |
| Server materializer | Snapshot expected identity/role from authenticated job-selection/deployment state independently of report arrivals; freeze/classify it at cutoff; apply first-valid immutable acceptance; derive totals; write the archive/manifest; and save the exact query copy. | An arrival-derived roster would hide missing participants; the schema describes the result but production code does not yet create it. |
| Bundle verification | Verify the summary, every accepted participant file, exact manifest membership/digests, and byte-identical `RESOURCE_STATS` copy together. | A standalone JSON Schema cannot open sibling files or authenticate storage. |
| CLI integration | Add all-site and complete selected-site human/JSON paths, separate STATUS/QUALITY, ENV WINDOW, F3 REMOTE, the qualified accepted-report aggregate, plus missing, unknown, disabled, not-ready, unavailable, corrupt, and adaptive-MIG cases. | Golden output exists, but the production command and error wiring do not. |
| Phase 2 telemetry | Have `JobStatsReporter` consume only validated finalized Phase 1 data; choose bounded metric/label names and optional model-label policy. | Telemetry backend cardinality and privacy require integration review. |
| Retention and cloning | Decide enablement default, archive retention, deletion behavior, and guarantee that cloned jobs start with no inherited statistics. | These are product lifecycle policies, not record-shape questions. |
| Non-Linux behavior | Decide which platforms are unsupported versus allowed to report an explicit host-visible fallback. | macOS probes can return real host values but cannot prove Linux affinity/cgroup containment. |

## Required trust checks outside JSON

Production readers must receive authenticated expected job, participant, attempt, execution-
environment, role, and roster context. They must compare the record with that context before
acceptance. Shape and digest validation cannot make a resource-worker claim authoritative by
themselves. Participant start/final and attempt end additionally require trusted supervisor
provenance rather than payload assertion.

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
- three contiguous main-record vectors: GPU 60 s, reported-zero GPU 300 s, GPU 120 s, with
  CPU/memory/storage spanning 480 s and GPU spanning 180 s;
- preemption followed by a true 300-second all-resource gap and resume, with partial totals and no
  invented attempt final;
- launch failure after acquisition with known open/close duration but missing transient capacity;
- concurrent distinct reporter environments whose summed window time exceeds participant wall
  time, alongside rejected same-environment overlap;
- identical-retry and conflicting-replacement participant acceptance tests;
- an expected roster sourced independently of reports, including a missing participant that
  cannot disappear from coverage;
- changed/missing attempt-final resource-time and changed participant-final storage cases;
- manifest corruption and extra/missing participant-file cases;
- each CLI error path plus complete selected-site/detail and partial preempt/resume output; and
- F3 exact included/excluded classes, zero-byte messages, post-encode/encryption payload sizing,
  fan-out/forwarding, remote acceptance versus direct delivery, counter gaps, unavailable counters,
  atomic-freeze races, ignored callbacks after freeze, and summary exclusion without stored
  circular counters.

The remaining gaps are implementation and product-policy work. They are not reasons to restore
the removed generic metric metadata, caveat catalogs, participant revisions, or duplicated
participant detail in the resource summary.
