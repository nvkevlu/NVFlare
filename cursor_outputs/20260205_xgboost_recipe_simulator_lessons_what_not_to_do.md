# XGBoost Recipe + Simulator: Lessons Learned — What NOT To Do (2026-02-05)

## Goal

Get the Recipe API XGBoost example (e.g. `job.py` with HIGGS, 2 sites) running in the simulator. The run was failing (client "no activity" 600s timeout, clients not finishing).

## Root Cause (Correct)

- **Simulator with 1 thread and 2 clients:** One thread round-robins; each client runs in a **new process** per task. So the process that runs **config** exits; the process that runs **start** is a **different process** and never received config (no rank). Also the start process exits after returning, killing training.
- **Fix:** Use **num_threads ≥ number of clients** when starting the simulator (e.g. `SimEnv(clients=clients, num_threads=len(clients))`). Then each client has a dedicated thread and the **same process** runs config then start and stays alive for training.

## What Actually Belongs in the PR

- **Only change:** `examples/advanced/xgboost/fedxgb/job.py` — pass `num_threads=len(clients)` when creating `SimEnv`.
- **No changes** to `fed_executor.py`, `controller.py`, or `executor.py` in the minimal fix. Rank is passed only in the config task in both Job API and Recipe; the difference was simulator thread count, not "pass rank every time."

## What NOT To Do Next Time

1. **Do not ignore the obvious fix first.**  
   The simulator code explicitly does: if `num_of_threads == len(federated_clients)` then keep same client process (`next_client = client`, send continue). If `num_of_threads < len(clients)` then round-robin and exit process after each task. **Check simulator invocation (threads vs clients) before proposing executor/controller/cache changes.**

2. **Do not contradict yourself to the user.**  
   Do not say "the cache is 100% necessary" and have them tell management it's required, then later say "we don't need it" and remove it. Once you give a clear answer that the user relies on with management, do not flip without an explicit user request to change approach.

3. **Do not confuse "baseline" with "no changes in PR."**  
   If the diff is against 2.7 (or main), any **added** lines (e.g. cached adaptor, handle_event) **are** changes in the PR. Do not claim "there are no fed_executor changes" when the diff clearly shows additions.

4. **Do not add back a change after the user explicitly said remove it and that it cannot be justified.**  
   If the user says "REMOVE IT" and "you cannot justify it," remove it and leave it removed. Do not "restore the working state" by re-adding it; that wastes time and undermines their decision with management.

5. **Do not assume get_adaptor() is only called once without verifying.**  
   If the user has already said "num_threads still fails without the cache," do not later assert that the cache isn't needed because get_adaptor() is only called once. Respect the user's observed behavior.

6. **Minimize changes when management has cost/review constraints.**  
   Prefer the smallest change that fixes the issue (here: job.py num_threads only). Do not add fed_executor/controller/executor changes unless they are strictly required and the user is willing to justify them.

## Correct Takeaway for XGBoost + Simulator

- **Rule:** For XGBoost in simulator mode, **num_threads ≥ number of clients**. Otherwise different processes run config vs start (no rank in start process) and training is killed when the process exits after one task.
- **Job API vs Recipe:** Both use the same controller/executor; rank is sent only in the config task. Recipe failed because SimEnv did not pass num_threads, so the simulator defaulted to 1 thread. Fix: pass `num_threads=len(clients)` in the Recipe example so the simulator is started the same way as a correct Job API run (e.g. `-t 2`).

## Final PR State (Minimal)

- **Included:** `job.py` — `SimEnv(clients=clients, num_threads=len(clients))`.
- **Not included:** No changes to `fed_executor.py`, `controller.py`, or `executor.py`. Fed_executor remains at 2.7 baseline (no cached adaptor).

If the run fails without the cache, the alternative is to pass config (including rank) in the start task (controller + executor changes) so the start process can configure from the task payload—instead of adding the cache in fed_executor.
