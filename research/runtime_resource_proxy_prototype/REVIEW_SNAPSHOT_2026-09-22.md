# Job resource statistics: worktree map and review snapshot (2026-09-22)

This is a point-in-time review of the whole feature: production code, lifecycle
integration, query surfaces, design and research docs, live captures, fixtures,
and tests. It is a working note for later follow-up, not an authoritative design
document. For current behavior, prefer
[PRODUCTION_IMPLEMENTATION.md](PRODUCTION_IMPLEMENTATION.md); for status,
[GAPS.md](GAPS.md); for F3 semantics, [F3_GAP.md](F3_GAP.md).
In particular, the in-flight `job_name` requirement discussed below was later
reversed: current archived `resource_summary` records contain only `job_id`.

- **Snapshot base:** branch `codex/job-resource-statistics-implementation-plan`
  at `bd847b741`, plus about 70 uncommitted in-flight changes from a concurrent
  session (mainly the `job_name` field, retained-content partial handling, and
  doc/fixture refreshes) and several untracked live-capture directories.
- **Method:** five parallel read-only review passes (core module, lifecycle and
  surfaces, authoritative docs, supporting research docs, artifacts and tests),
  followed by direct re-verification of the highest-severity findings.
- **Caveat:** files were being edited during the review. A few issues the passes
  reported were fixed while they ran and are omitted here. Line numbers drift;
  prefer the function names.

---

## Part 1 — Map

### What the feature does

For every finished job, each participant (the server and each client) reports:

- **Resource time:** CPU, memory, and GPU *capacity*-time — the capacity visible
  to the job process at start, multiplied by the measured duration. It is not a
  utilization or busy-time measurement.
- **Workspace filesystem capacity:** one `statvfs` snapshot at job finalization.
- **Retained content:** the regular-file size of the job's run directory at
  finalization, excluding the top-level `resource_stats/` bookkeeping directory.
- **F3 traffic:** bytes and messages the local transport accepted for three
  operations — job deployment (SP), real task responses (SJ), and task results
  (CJ).

The server combines these into one `resource_summary.json` stored in the job's
normal WORKSPACE archive. `nvflare job resources` and the FLARE API read it back
per job or roll it up per study.

Where exactly the job processes take their measurements is documented in
[JOB_PROCESS_MEASUREMENT_POINTS.md](JOB_PROCESS_MEASUREMENT_POINTS.md).

### Data flow

```text
SERVER PARENT (SP, long-lived)                     CLIENT PARENT (CP, long-lived)
job_runner.py                                       client_executor.py (JobExecutor)
 ├ F3 registry start ─ coordinator.start_job         ├ F3 registry start (after meta check)
 ├ deploy ──[job_application]──► F3                  └ launch ─► wait ─► freeze F3 (0s)
 │                                                                │
 │  SERVER JOB (SJ) runner_process.py               CLIENT JOB (CJ) worker_process.py
 │   ├ collector + F3 counter start (before custom code runs)   (same)
 │   ├ GET_TASK real reply ──[task_response]──► F3    ├ submit_update ──[task_result]──► F3
 │   └ teardown: drain ─► freeze ─► finish() ─► terminal_handoff.json   (same)
 │                                                                │
 ├ read SJ handoff + SP F3 ─► participant_summary   CP: read handoff + CP F3 ─► participant_summary
 ├ coordinator.accept ◄──────── REPORT_JOB_FAILURE(+RESOURCE_REPORT) ──────┘
 └ finalize ─► resource_stats/{participants/*.json, resource_summary.json} ─► WORKSPACE zip

QUERY  job_cli.py ─► flare_api ─► job_cmds.get_job/study_resources ─► archive_reader ─► contract ─► job_resources.py
```

### Code

| Layer | Module(s) | Runs in | Role |
|---|---|---|---|
| Contract | `nvflare/private/fed/resource_stats/contract.py` | everywhere | Schema, validation, aggregation. Trust boundary; stdlib-only leaf. |
| Observation | `probes/cgroup_linux.py`, `probes/gpu_nvidia.py`, `probes/_shared.py`, `accumulator.py` | job processes | Capacity probes and capacity-time math |
| Facade | `collector.py` | job processes (`JobResourceCollector`, `observe_*`); parents (`assemble_participant_summary`, `merge_f3_snapshots`) | Composition entry points |
| Handoff | `handoff.py` | child writes, parent reads | Private `terminal_handoff.json`, symlink-safe I/O |
| F3 | `f3_counter.py`, `f3_registry.py` (SP/CP), `f3_job_counter.py` (SJ/CJ), `f3_bindings.py` | all | Counters, ownership, trusted binding helper |
| F3 transport | `nvflare/fuel/f3/send_accounting.py` + hooks in `message.py`, `cellnet/core_cell.py`, `cellnet/cell.py`, `streaming/byte_streamer.py`, `streaming/blob_streamer.py`, `stream_cell.py`, `streaming/download_service.py`, `streaming/obj_downloader.py`, `streaming/stream_types.py`, `fuel/utils/fobs/decomposers/via_downloader.py` | every sender | Origin-only logical-send accounting; context is process-local and never serialized |
| Server | `coordinator.py` | SP | Accept, disable, finalize, forget; bounded in-memory ledger |
| Query | `archive_reader.py`, `nvflare/private/fed/server/job_cmds.py` | SP admin path | Fixed-member ZIP read; job and study views |
| Surfaces | `nvflare/tool/job/job_cli.py`, `nvflare/tool/job/job_resources.py`, `nvflare/fuel/flare_api/flare_api.py` | admin client | CLI and API |

Existing NVFlare files touched by the feature:

- Server: `job_runner.py`, `fed_server.py`, `server_command_agent.py`, `message_send.py`, `admin.py`, `job_cmds.py`
- Client: `client_executor.py`, `communicator.py`
- Job processes: `worker_process.py`, `runner_process.py`, new `job_process_bootstrap.py`, `job_process_cleanup.py`
- Launchers: process, Docker, Kubernetes, Slurm, plus `job_launcher_utils.py`
- Constants and registration: `security.py`, `fl_constant.py`, `job_def.py`, `private/defs.py`, `filesystem_storage.py`

### Docs — where to read what

| If you want… | Read | Status |
|---|---|---|
| Where to start reviewing | [README.md](README.md) | current index |
| What the code does today | [PRODUCTION_IMPLEMENTATION.md](PRODUCTION_IMPLEMENTATION.md) | authoritative; some stale code anchors |
| What's done, left, and decided | [GAPS.md](GAPS.md) | authoritative status |
| Exact F3 semantics | [F3_GAP.md](F3_GAP.md) | authoritative for F3 |
| Where CJ/SJ take measurements | [JOB_PROCESS_MEASUREMENT_POINTS.md](JOB_PROCESS_MEASUREMENT_POINTS.md) | new, current |
| Why, and the target design | [implementation plan](../../docs/design/job_resource_statistics_implementation_plan.md) | mix of current and target |
| Future telemetry publication | [Phase 2 sketch](../../docs/design/job_resource_statistics_phase2_telemetry_sketch.md) | draft |
| Integration spec, record flow, reviewer walkthrough | [CURRENT_CODE_INTEGRATION.md](CURRENT_CODE_INTEGRATION.md), [ROLLUP_FLOW.md](ROLLUP_FLOW.md), [REVIEW_GUIDE.md](REVIEW_GUIDE.md) | reference; line numbers drifting |
| Field, status, error catalogs | [schema/README.md](schema/README.md), [schema/FIELD_CATALOG.md](schema/FIELD_CATALOG.md), [schema/CODE_CATALOG.md](schema/CODE_CATALOG.md) | reference; name the wrong normative source (see M10) |
| What was cut and why | [SIMPLIFICATION_REVIEW.md](SIMPLIFICATION_REVIEW.md) | historical rationale |
| Operator docs | `docs/user_guide/nvflare_cli/job_cli.rst`, `docs/user_guide/data_scientist_guide/flare_api.rst` | current |

### Evidence

| Capture | What it shows | Valid against current contract? |
|---|---|---|
| `colossus_e2e_reference`, `colossus_pytorch_e2e_partial`, `colossus_pytorch_e2e_reference` (+ `fixed_run`, `cli/revised`) | 09-18 and 09-21 runs; GPU discovery; the bundled-CUDA gap and its fix | No — predate F3, retained content, and `job_name` |
| `colossus_pytorch_f3_e2e_reference` (committed; README untracked) | F3 of 14 messages / 3,080,162 B. Topology matches exactly: server = 2 deployments + 6 task responses; each client = 3 task results | No — no `job_name`; retained content `not_bound` |
| `colossus_pytorch_retained_content_e2e_reference` (untracked) | Retained content: server 616,179 B including checkpoints; each client 72,912 B (logs/config only — see M6) | No — no `job_name` |
| `colossus_pytorch_job_name_e2e_reference` (untracked, new) | Everything live: `job_name` `hello-pt`, F3 14 / 3,080,186 B, retained 761,986 B | **Yes** — job and study CLI JSON verified |
| `production_reference/`, `schema/golden/v1/` | Deterministic output generated through the production code | Yes |

### Tests and style (at review time)

- **Production:** 3,019 passed, 0 failed. 3 k8s tests deselected (the review venv lacks `kubernetes`).
- **Research:** 83 pytest passed plus 26 subtests; 79 unittest OK; `production_reference/generate_reference.py --check` current. **None run in CI** — `runtest.sh` only runs `tests/unit_test`.
- **Style:** flake8 clean. black would reformat 3 in-flight files, including `nvflare/private/fed/server/job_runner.py` (would fail CI). isort fails 4 research files (not CI-checked).

---

## Part 2 — Consistency review

### High — fix before this goes further

- **H1. `job_name` can break things (in-flight).** The contract accepts only
  `^[A-Za-z0-9][A-Za-z0-9._-]{0,254}$`. NVFlare job names can contain spaces and
  have no length limit, but the code falls back to another name only when the
  name is *empty*.
  - A job named e.g. `"CIFAR-10 FedAvg"` silently loses its whole resource report
    (`coordinator.start_job` raises; `job_runner` swallows it).
  - `derive_study_totals(rows)` runs *outside* the `try` in
    `JobCommandModule.get_study_resources` (`job_cmds.py` ~L748), so that one job
    crashes `nvflare job resources --study` for everyone. Verified.
  - The fallback chain is written three times (`job_runner.py` start and restore,
    `job_cmds._resource_job_name`), and differs from `CommandUtil.get_job_name`.
  - Fix: one shared helper that picks the first candidate matching the pattern
    (name → job folder → job ID); move `derive_study_totals` inside the `try`.
- **H2. `job_name` breaks every older archive (in-flight).** It became required
  while `SCHEMA_VERSION` stayed `"1.0"`.
  - Every job finalized before the change errors on `--job` and shows as
    `unavailable` in study rollups — including all Colossus captures except the
    new `job_name` one, and their WORKSPACE zips (reproduced with the production
    reader).
  - `job_resources.py` indexes `summary['job_name']` directly and would raise
    `KeyError` on older summaries.
  - Fix: accept a missing `job_name` on read (fall back to job ID), or bump the
    version and dual-read; use `.get()` in the renderer.
- **H3. An unrelated transport change is inside the F3 commit.**
  `Cell._fire_and_forget` (`cellnet/cell.py`) now always passes
  `num_receivers=len(targets)` and `receiver_ids=targets` when encoding, even
  with no accounting context attached. Every other hook is gated on accounting.
  This changes `DownloadService` transaction completion for ordinary
  fire-and-forget large-object traffic (count-based → identity-aware). It may be
  a latent fix for multi-target sends or a new way to wait on a receiver that
  never downloads; either way it is untested. Verified against `main`.
  - Fix: gate on `message.get_logical_send_context() is not None`, or split it
    into a separately reviewed change. Also add a test that accounted and
    unaccounted large-object sends complete identically (accounted sends also set
    `RECEIVER_IDS`).
- **H4. Repo hygiene before any push.**
  - Internal IP `10.176.254.250` (24 lines) in the untracked
    `colossus_pytorch_retained_content_e2e_reference/artifacts/logs/server/poc_console.log`.
  - `ipp2-*` hostnames in 4 committed READMEs
    (`collector_walkthrough/README.md`, `colossus_e2e_reference/README.md`,
    `colossus_pytorch_e2e_partial/README.md`, `colossus_pytorch_e2e_reference/README.md`).
  - Capture job-store WORKSPACE zips (committed F3 capture; untracked
    retained-content and `job_name` captures) contain model `.pt` files,
    submitter certificates and signature JSON, `meta.json`, and `__pycache__`,
    contradicting the captures' own stated policy
    (`colossus_pytorch_e2e_reference/README.md` ~L211-216).
  - Clutter: `nvidia-smi.pid`, empty `nvidia-smi.err`, raw console logs, a
    `__pycache__/` in the new capture directory, `/tmp` paths in READMEs.

### Medium

- **M5. Docs left stale by earlier fixes.**
  - Deploy-failed clients are now `disabled` (`job_runner.py` calls
    `disable_clients`), but the plan (§5.2, §8, §10.3), PRODUCTION §3, and
    CURRENT_CODE_INTEGRATION still say `missing`.
  - "No loadable CUDA Runtime anywhere = authoritative GPU zero" is contradicted
    by `schema/README.md` (~L204, "An unavailable CUDA runtime is not an observed
    zero") and missing from `FIELD_CATALOG.md`, `SIMPLIFICATION_REVIEW.md`,
    `REVIEW_GUIDE.md`, and `ROLLUP_FLOW.md`.
- **M6. Retained content.**
  - No size or time bound on the directory walk, which runs inside job teardown.
  - `JobResourceCollector.finish()` has no per-field isolation: one failing
    observer (a >16 EiB filesystem that exceeds the U64 capacity bound, or
    `RecursionError` from a very deep tree on Python 3.10/3.11) discards the whole
    handoff.
  - Outputs written outside the run directory are not counted. In the live run,
    hello-pt clients save checkpoints elsewhere, so their figure is only logs,
    config, and code. This is documented only in a capture README, not in the
    user docs, GAPS, or the plan.
- **M7. CLI/API contract.**
  - `RESOURCE_VIEW_TOO_LARGE` is documented (plan §11.2, CURRENT_CODE_INTEGRATION,
    REVIEW_GUIDE, CODE_CATALOG) but does not exist in code.
  - `nvflare job resources` error codes don't match the rest of `nvflare job`:
    `INVALID_ARGUMENT` vs `INVALID_ARGS`, `JOB_NOT_FINALIZED` vs `JOB_NOT_DONE`,
    unregistered `RESOURCE_DATA_UNAVAILABLE`, authorization failures reported as
    data errors, `AuthenticationError` re-raised.
  - `--site` for a missing/disabled/invalid participant fails the whole query;
    per-participant statuses are not documented in `job_cli.rst`.
- **M8. Study authorization is coarser than per-job.** `GET_STUDY_RESOURCES`
  uses command-level authorization and returns per-job totals, so a user can see
  totals for jobs they cannot view individually. Follows the `list_jobs`
  precedent; needs a decision (document it or filter rows by per-job authz).
- **M9. Evidence and docs drift apart.**
  - Docs disagree on which capture is the "primary live reference"; the new
    `job_name` capture should become it.
  - PRODUCTION §6 claims an older capture still validates (it now fails on
    `job_name`).
  - The F3 capture is committed without its README; nothing links to it.
  - The retained-content capture is untracked but linked from ~6 committed docs,
    and records no commit SHA or wheel hash.
  - Single-shot delivery and the in-memory ledger lost on restart are still
    listed as "remaining work, if required" (GAPS §4, plan §16 #4) rather than as
    accepted Phase 1 decisions.
- **M10. More than one source of truth.**
  - `schema/FIELD_CATALOG.md` and `schema/CODE_CATALOG.md` name the research
    `contract_v1.py` and JSON Schema as normative, not production `contract.py`.
  - The JSON Schema differs from production on the model-name privacy regex
    (substring vs whole word; case sensitivity), the U64 caps, and the F3
    `messages == 0 ⇒ payload_bytes == 0` rule.
  - `prototype_contract.py`'s F3 merge disagrees with production
    `merge_f3_snapshots` in 4 of 6 probed cases, and its own test pins that.
- **M11. Accounting guards swallow `BaseException`.** Guards in `f3_bindings.py`,
  `send_accounting._safe_call`, and the transport hooks catch `BaseException`
  without re-raising, so `KeyboardInterrupt`/`SystemExit` mid-accounting is
  swallowed. Catch `Exception` instead where nothing is re-raised.

### Low (grouped)

- **Duplication:** layout constants (`resource_stats`, `participants`,
  `resource_summary.json`, `staging`) are defined across `handoff.py`,
  `coordinator.py`, `archive_reader.py`, and `contract.py`; the retained-content
  exclusion depends on them matching. The symlink-safe dir-fd descent exists in
  both `handoff.py` and `coordinator.py`.
- **Dead code:** `contract.validate_bundle`,
  `JobResourceCollector.observe_capacity_change`,
  `job_launcher_utils.refresh_custom_dir_import_path`, the unreachable bare-word
  branch in `job_cmds._is_terminal_resource_job`, `U32_MAX`, and diagnostic-only
  F3 methods (`F3Counter.snapshot`/`pending_count` in production,
  `F3CounterRegistry.mark_prior_history_incomplete`).
- **Launchers:** the process launcher still differs from Docker/K8s/Slurm (no
  `-u`, script path vs `-m`; only it scrubs `PYTHONPATH`). Docker/K8s/Slurm need
  NVFlare in site-packages for `-I -m`; undocumented, not yet run live.
- **Output and naming:** human output hides the F3 and retained-content columns
  when unavailable everywhere instead of showing the status; 4-decimal GiB turns
  73 KB into `0.0001`; the same field is `retained_content` / "Run-directory
  files" / "RUN-DIR FILES".
- **Minor code:** bounded cleanup-path leaks in rare branches (SP `run()` when a
  job leaves `DISPATCHED` during deploy; `restore_running_job` outer `except`;
  CP `start_app` raising before registration). Setup failures before the
  teardown `try` skip the child handoff (see
  [JOB_PROCESS_MEASUREMENT_POINTS.md](JOB_PROCESS_MEASUREMENT_POINTS.md)).
  Parent processes import the GPU probe module and run its import-time
  distribution-root scan for no reason.
- **Housekeeping:** the isolated worktree
  `../job-resource-statistics-retained-content` and branch
  `codex/retained-content-workspace-size` are redundant.

---

## Part 3 — What's missing / to do

### P0 — before committing the in-flight `job_name` work

1. Shared `job_name` helper with pattern-based fallback; move
   `derive_study_totals` inside the `try`; renderer uses `.get("job_name")`. (H1)
2. Decide compatibility: optional-on-read with job-ID fallback (recommended,
   keeps older archives and captures readable) or declare v1 pre-release / bump
   the version. (H2)
3. black on `job_runner.py`.
4. Capture hygiene: redact the IP and hostnames; strip zips to `resource_stats/`
   members plus a member list; drop pid/err/`__pycache__`/console logs; commit or
   drop the untracked capture pieces so doc links don't break. (H4)

### P1 — before calling the branch review-ready

5. Gate or split out the `Cell._fire_and_forget` receiver-identity change; add
   accounted-vs-unaccounted large-object equivalence tests. (H3)
6. Harden retained content: traversal budget that returns `partial`,
   per-observer isolation in `finish()`, U64 clamp for filesystem capacity, and
   user-facing docs for the outside-run-directory limitation. (M6)
7. Align CLI error codes with `nvflare job`; implement or remove
   `RESOURCE_VIEW_TOO_LARGE`. (M7)
8. Decide study-rollup authorization semantics. (M8)
9. Doc sweep: `disabled` for deploy-failed clients; GPU no-runtime zero;
   durability as an accepted decision; the `job_name` capture as the primary live
   reference; stale code anchors; production `contract.py` as the normative
   source; per-participant statuses. (M5, M9, M10)
10. Replace non-re-raising `BaseException` catches with `Exception`. (M11)

### P2 — known open work (the design docs agree on these)

11. Put the research suites (or at least `generate_reference.py --check`) into
    CI, or trim `research/`; retire or sync `prototype_contract`'s F3 merge.
12. Live platform matrix: Docker, Kubernetes, Slurm; multi-GPU; MIG; constrained
    cgroups; other CUDA and packaging variants.
13. Scale-test study queries (~10,000 jobs, remote job stores).
14. Final decision on the completion transport: Option A (reuse
    `REPORT_JOB_FAILURE`) vs Option B.
15. Whether retained content should also cover separately configured result,
    log, and audit roots, and how to de-duplicate them.
16. Dead-code and duplication cleanup; remove the redundant isolated worktree.
17. Phase 2 open decisions: field names, publication scope, cadence.
