# Result Download Incident: 2026-07-17

## Summary

The failed operation was not a Hugging Face model download, a client model
transfer, or training. It was the final FLARE admin download of the completed
job result package from `flare-server` to the local Mac.

The federated job itself completed successfully. The result transfer later lost
its server-side download reference after an inactivity timeout, and the harness
misreported that transfer failure as a 600-second job timeout.

## Evidence

Run: `20260717T154445Z-synthetic-smoke-ac0975e1`

| UTC | Evidence | Meaning |
| --- | --- | --- |
| 15:45:34 | `Server runner finished` and `server_run_end` | Both FL rounds, aggregation, and persistence completed. |
| 15:45:39 | Download service callback registered | The post-job admin result-transfer path started. |
| 15:47:09 | `status=timeout elapsed=90.00s size=90.0MB (94,398,418 bytes)` | The server-side source transaction expired after serving 94,398,418 bytes. This is bytes served, not proof of the package's total size. |
| 15:47:11 | `no ref found for R32bc... from _admin_...` | The local admin retried after the source transaction had removed the reference. |
| 15:47:15 | Harness status `FINISHED:COMPLETED` | FLARE still classified the actual job as successful. |

The normal 64 MiB round model transfers in the same run completed in about
1--10 seconds. They use a different path and did not fail.

## What Was Being Downloaded

`Session.download_job_result()` sends the `DOWNLOAD_JOB` admin command. The
server stages three job-store components:

1. `job.zip`: submitted job definition and application files.
2. `meta.json`: job metadata and final status.
3. `workspace.zip`: server workspace, logs, statistics, and persisted model
   checkpoints.

The checkpoint-heavy `workspace.zip` dominates this transfer. A comparable
successful synthetic smoke result contained two uncompressed persisted model
files of approximately 64 MiB each: `FL_global_model.pt` and
`best_FL_global_model.pt`. The failed transaction's 94,398,418-byte counter is
the amount the source served before expiration; it must not be described as the
exact total archive size.

## Exact Call Path

1. `research/llm_fl_stress/job.py` calls `run.get_result()` after submission.
2. `nvflare/recipe/run.py` delegates to the production execution environment.
3. `nvflare/recipe/session_mgr.py` first waits for `JOB_FINISHED`, then calls
   `Session.download_job_result()`.
4. `nvflare/fuel/flare_api/flare_api.py` sends the `DOWNLOAD_JOB` admin command.
5. `nvflare/private/fed/server/job_cmds.py` stages `job.zip`, `meta.json`, and
   `workspace.zip`, then calls `BinaryTransfer.download_folder()`.
6. `nvflare/fuel/hci/server/binary_transfer.py` creates one source-side
   `ObjectDownloader` transaction and one reference per staged file.
7. `nvflare/fuel/hci/client/file_transfer.py` pulls those references serially.
8. `nvflare/fuel/hci/client/api.py` calls
   `nvflare/fuel/f3/streaming/file_downloader.py::download_file()`.
9. `nvflare/fuel/f3/streaming/download_service.py::download_object()` repeatedly
   requests 5 MiB chunks and writes them to a temporary local file.

## Why It Failed

The source transaction timeout is an inactivity timeout, not a total-transfer
deadline. Each valid chunk request refreshes `last_active_time`. The monitor
checks every five seconds and removes a transaction when no request has arrived
for longer than the transaction timeout. Removing the transaction also removes
its file references.

For this provisioned server, no explicit `admin_timeout` is present, so the
server default is 10 seconds. The admin receiver's default per-request progress
timeout is 5 seconds. On a timed-out chunk request, the receiver retries with
2-, 4-, then 8-second backoffs. Repeated slow or lost chunk responses can
therefore leave the producer without a request for more than 10 seconds. The
producer expires and removes the reference while the receiver is still waiting
or backing off. Its next request then receives `INVALID_REQUEST` and produces
the observed `no ref found` error.

The logs prove the inactivity expiration and stale-reference request. They do
not contain the local admin's per-chunk retry messages, so the exact transport
event that created the request gap is an inference. The 2.34-second gap between
source expiration and the stale-reference request is consistent with the
receiver's first 2-second retry backoff.

## Why The Harness Message Was Misleading

The harness passes 600 seconds to `monitor_job()`. That value controls how long
to wait for the FL job to finish; it is not passed to the binary result-transfer
transaction.

`Run.get_result()` catches result-download exceptions and returns `None`. The
harness treats every `None` result as if job monitoring reached the 600-second
deadline and raises `production job did not finish within 600.0 seconds`, even
though its next status query returns `FINISHED:COMPLETED`.

## Current Mitigation And Required Fixes

- Large capacity tests use `--skip-result-download`; telemetry and service logs
  are still collected while the checkpoint-heavy admin transfer is omitted.
- Capture local admin transfer logs so chunk timeouts and retry counts are part
  of every full-result artifact.
- Report job-monitor timeout separately from result-transfer failure.
- Give the admin binary source an inactivity budget larger than the receiver's
  worst-case request timeout plus retry backoff, or make it independently
  configurable for result downloads.
- Keep a small full-result smoke gate because thin runs intentionally do not
  test this path.
