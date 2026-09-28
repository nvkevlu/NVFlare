# CPU-consumed coverage for child workers

This is a follow-up note for the [resource-statistics implementation](PRODUCTION_IMPLEMENTATION.md), not a claim that every worker path is already covered. It records why some CPU-consumed reports are partial and what to check before using the number as a billing input. The metric is user plus system CPU time spent by the job's execution processes during the measured window. It is separate from visible CPU capacity multiplied by time.

## What the prototype measures today

On Linux and macOS, the [CPU accountant](../../nvflare/private/fed/resource_stats/cpu_consumed.py) reads `RUSAGE_SELF` and `RUSAGE_CHILDREN` once near job-process startup and once at finalization. It adds the two deltas. `SELF` covers the job process and its threads; `CHILDREN` covers exited children that were waited for. On Linux, a grandchild's CPU propagates only if each intervening parent waits for its child ([Linux `getrusage` manual](https://man7.org/linux/man-pages/man2/getrusage.2.html)). A short-lived child is therefore counted without sampling *if it was waited for*. The long-lived site parent is excluded because it can run several jobs at once.

The result goes into the existing single final participant report. A complete
CPU-consumed value omits `status` and `issues`; partial or unavailable results
carry an explicit status and issue. A partial CPU-consumed result does not
invalidate the separate capacity-time, memory, GPU, or retained-content fields.
An abrupt job-process death can prevent the final handoff entirely. A restarted
process cannot recover its predecessor's CPU time. Windows has no
`resource.getrusage` in this implementation and reports CPU consumed as
unavailable.

The [current accountant](../../nvflare/private/fed/resource_stats/cpu_consumed.py) marks a known worker path `partial/attribution_incomplete` when it cannot establish that all of that path's CPU reached `RUSAGE_CHILDREN`. That is a useful subtotal, **not** a complete chargeable total. Conversely, arbitrary custom code can launch an unregistered, un-waited child that this end-only method cannot discover; even a complete value with no status cannot certify the absence of such a child. This is a practical billing proxy, not an independently verified invoice ledger.

## Why the built-in paths differ

| Path | What NVFlare knows now | Why complete CPU is not yet established |
| --- | --- | --- |
| Ordinary work inside the job process | The process's own user and system CPU counters are available. | Its threads are included, but any un-waited child it starts is not. |
| [External trainer](../../nvflare/app_common/executors/client_api/external_process_backend.py) | NVFlare holds a `Popen` handle. Its existing shutdown asks the trainer to stop, makes bounded waits for the launcher, checks process-group liveness, and may send TERM/KILL. | A reaped launcher contributes its CPU, but a vanished process group does not prove the launcher waited for every descendant. The current registration conservatively marks **every** external trainer partial, including a command that might in fact be single-process. |
| [PyTorch `MultiProcessExecutor`](../../nvflare/app_common/executors/multi_process_executor.py) | NVFlare launches `torch.distributed.run`/`torchrun`, which launches ranks. At `finalize`, it sends `CLOSE` without waiting for replies, then kills the process group and terminates the launcher without a matching wait. | Training happens in the ranks. Neither `RUSAGE_SELF` of the NVFlare job process nor a process-group-exit check proves their CPU was passed through waited-for processes. |
| [XGBoost v2 partial-HE pools](../../nvflare/app_opt/xgboost/histogram_based_v2/sec/partial_he/) | The encryptor, adder, and decrypter create `ProcessPoolExecutor` workers and consume `map()` results. | Completed tasks do not imply that pool processes exited and were reaped before the final CPU reading. The inspected components have no explicit pool shutdown at that boundary. |
| Other managed processes | The [legacy XGBoost server](../../nvflare/app_opt/xgboost/histogram_based/controller.py) and [v2 adaptor](../../nvflare/app_opt/xgboost/histogram_based_v2/adaptors/adaptor.py) also create separate processes. | Their stop paths terminate or kill without an explicit successful join in the inspected code. Check each path before claiming complete coverage. |

The PyTorch gap is not limited to the named `PTMultiProcessExecutor`. Repository examples also use `torchrun` through the external-trainer path: [multi-GPU PyTorch](../../examples/advanced/multi-gpu/pt/job.py), [LLM fine-tuning](../../examples/advanced/llm_hf/job.py), [Qwen3-VL](../../examples/advanced/qwen3-vl/job.py), and [Docker DDP](../../examples/docker/jobs/pt-ddp-docker/app_site-1/config/config_fed_client.json). These show that the pattern matters to supported workloads, but repository examples do not tell us what fraction of customer jobs use it. For a distributed job, missing rank CPU could be a large share of consumed CPU; do not assume it is negligible.

## Existing shutdown is not CPU evidence

The external backend's [`_stop_trainer`](../../nvflare/app_common/executors/client_api/external_process_backend.py) already has a completion protocol and bounded process/group waits. Those answer **whether the trainer or group is still running**. They do not themselves measure CPU. The CPU accountant separately takes the two OS-counter readings described above.

Using the existing shutdown outcome would be a *future status refinement*, not a new measurement source or a new server message. For example, if a platform-owned, known single-process trainer was reaped before the final reading, its CPU can be covered without an extra wait. Do not infer "single-process" by parsing an arbitrary command string. Do not clear the partial status merely because its launcher exited and the process group disappeared: neither fact proves all ranks or other descendants were waited for. The prototype does **not** currently clear its permanent partial marker after a clean external-trainer shutdown.

## Recommended next steps, in order

1. **Make completion evidence precise.** Track each managed launch's normal exit versus forced termination, whether its direct process was reaped before the CPU boundary, and whether the path can prove descendant coverage. Avoid one permanent `descendants_may_be_unwaited` flag for all external commands, but do not treat an unknown command as single-process. Keep one CPU subtotal and one final participant transmission.
2. **Verify `torchrun` on normal exit.** With CPU-burning ranks, test whether it waits for all ranks and whether their CPU reaches the job process's `RUSAGE_CHILDREN` after NVFlare waits for `torchrun`. Test short-lived ranks, multiple ranks, a failed rank, and a killed group. If that does not establish coverage, NVFlare's own `sub_worker_process` ranks could emit a small job-local exit-time CPU receipt. An arbitrary external `torchrun` script has no equivalent platform-owned rank hook today; it stays partial unless a separate launch/wrapper design covers it. Count each rank once: do not add a receipt to a child counter that already includes it. A rank killed before its receipt remains partial.
3. **Repair the named built-in lifecycles.** For `MultiProcessExecutor`, do not immediately kill normally closing ranks; allow `CLOSE` and a bounded clean exit, then reap the launcher. Keep forced termination for abort/failure and report incomplete CPU when it prevents accounting. For XGBoost pools, close and join idle workers at their normal owner lifecycle. Python's [`Executor.shutdown(wait=True)`](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.Executor.shutdown) waits for pending work and resource cleanup; do **not** put an unbounded call on critical final teardown. Apply the same explicit-exit check to the other managed process paths above.
4. **Test the claim before omitting status.** Compare CPU work with sleep; cover a short-lived child between hypothetical sample times, multiple children, and parent/child non-duplication. Include two concurrent jobs, server and client participants, clean and forced PyTorch/XGBoost exits, restarts, failure paths, and job/study CLI reconciliation. A complete result with no status must have demonstrated coverage for the supported path. Keep an incomplete subtotal visibly `partial` and a failed reading `unavailable`.

No per-step or periodic CPU sampling is needed for these changes. The cost is chiefly at **shutdown**: orderly rank or pool exit may delay job completion and resource release, whereas the current PyTorch path kills immediately. The [sub-worker close loop](../../nvflare/private/fed/app/client/sub_worker_process.py) checks once per second, so clean exit can add roughly that responsiveness delay plus framework cleanup; measure it rather than promise a fixed duration. The external backend already performs bounded waits, so merely reusing their outcome adds negligible wait. Never add an unbounded pool join or a new shared-parent cleanup delay to make a number appear complete.

## Decision needed for billing use

Decide which managed launch paths must produce a complete number on **normal** completion, and what maximum added shutdown time is acceptable. On abort, crash, forced kill, or an arbitrary uninstrumented custom subprocess, preserving `partial` or `unavailable` is the honest policy under the current no-sampling, no-new-privilege, no-new-configuration design. Full accounting of arbitrary workers would require stronger isolation or instrumentation beyond this prototype; do not assume an existing Linux cgroup is exclusive to one job.
