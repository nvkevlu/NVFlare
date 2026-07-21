# LLM Federated Server Stress Harness

This project measures the FLARE server data path with LLM-sized PyTorch state
dictionaries. It creates exact parameter-count synthetic models, runs two-client
FedAvg for one or two rounds, captures process and phase telemetry, and produces
a machine-readable pass/fail report.

The synthetic model is intentional: it isolates model distribution, streamed
return, aggregation, disk offload, and checkpoint persistence from tokenizer,
dataset, optimizer, and GPU-training variability. It does **not** claim that a
server-only pass proves end-to-end training capacity.

Scenario names and parameter counts are based on public model cards, but these
tests do not call `from_pretrained`, contact the Hugging Face Hub, or download
published model weights. No Hugging Face token is needed for the synthetic
capacity curve. A later real-model experiment should pre-stage each selected
revision once per host; public models can be downloaded anonymously, while
private or gated models require approved access and a read-scoped token. Keep
that token in a site environment variable or mounted secret file, never in the
scenario, exported job, startup kit, logs, or repository.

The default lane is a same-host FLARE simulation. Server phase events isolate
the server process, while process-tree metrics show the extra client and
simulator memory that shares the host.

The current measured-results summary and next-machine recommendation are in
[results and next steps](docs/results-and-next-steps-2026-07-20.md). The short
shareable allocation table is in the [machine decision guide](docs/machine-plan.md).
The detailed 32B round-two RAM trace is in
[server memory attribution](docs/server-memory-attribution.md).
The measured one/two/three-client server-memory curve and shareable explanation
are in the [client-count memory brief](docs/client-count-memory-brief-2026-07-21.md).
The [real GPU training reuse audit](docs/real-training-reuse-audit-2026-07-21.md)
identifies the existing Hugging Face, torchrun, Qwen, Lightning, and Slurm
building blocks and isolates the remaining FSDP-specific work.
The prepared one-server/three-client follow-up is in the
[three-client 32B runbook](docs/three-client-32b-run.md).

## Start Here

Run commands from the repository root. The current `main` branch may contain
NVFlare features that are not published on PyPI yet, so install NVFlare from this
repository until the corresponding package is released:

```bash
python3 -m pip install -e '.[app_opt]'
```

On macOS, use `python3 -m pip install -e '.[app_opt_mac]'` instead.

Validate a scenario without allocating its tensors:

```bash
python3 research/llm_fl_stress/validate.py
```

This schema-and-sizing check uses only the Python standard library. After the
NVFlare and PyTorch environment is installed, validate the full recipe without
allocating its tensors:

```bash
python3 research/llm_fl_stress/job.py \
  --scenario research/llm_fl_stress/configs/qwen25-14b-1r.json \
  --validate-only
```

Run the local 16M-parameter smoke test:

```bash
python3 research/llm_fl_stress/job.py \
  --scenario research/llm_fl_stress/configs/smoke.json
```

Then collect the first laptop scaling point with the 135M tier:

```bash
python3 research/llm_fl_stress/job.py \
  --scenario research/llm_fl_stress/configs/smollm2-135m.json
```

Continue to the more demanding 0.49B tier only after 135M passes:

```bash
python3 research/llm_fl_stress/job.py \
  --scenario research/llm_fl_stress/configs/qwen25-0.5b.json
```

Export a production job without allocating the model:

```bash
python3 research/llm_fl_stress/job.py \
  --scenario research/llm_fl_stress/configs/qwen25-32b.json \
  --export-only
```

Every command prints its immutable artifact directory immediately. Production
runs then update `live_status.json` once per minute and immediately on status or
phase changes. Follow completion from a second terminal without contacting the
leased machines:

```bash
python3 research/llm_fl_stress/ops/watch_run.py <run-directory>
```

The watcher exits when `RUN_COMPLETE` or `RUN_FAILED` is written and reports a
stale launcher heartbeat after three minutes. For detailed live transfer phase,
RSS, available memory, and disk snapshots, run `ops/live_status.py` against the
active run every two or three minutes rather than continuously.

Production runs also recover remote telemetry and service logs incrementally
every five minutes, independent of FLARE's potentially blocking result/status
calls. When the lease deadline is known, add an explicit pre-expiry checkpoint:

```bash
python3 research/llm_fl_stress/job.py <production-options> \
  --lease-expiry-utc 2026-07-21T22:00:00Z
```

The default guard runs 15 minutes before expiry. Change the cadences with
`--artifact-checkpoint-interval-seconds` and
`--lease-final-checkpoint-lead-seconds`. Incremental recovery copies only logs
and telemetry; it does not stop monitors, download large model checkpoints, or
alter the running FLARE job.

Review
`report/summary.json` first, then inspect `report/evidence.json`, `events.jsonl`,
the metric CSVs, and native FLARE logs.

If the launcher is killed before it can write a report, the external sampler
keeps flushing telemetry until the launcher PID disappears. Recover the report
after the machine or allocation is stable:

```bash
PYTHONPATH=research/llm_fl_stress python3 -m harness.finalize <run-directory>
```

## FSDP2 GPU Qualification Gate

Before downloading a Hugging Face model or starting NVFLARE services, validate
the FSDP2 full-state boundary on every GPU in a prospective training host:

```bash
python -m torch.distributed.run \
  --standalone \
  --nproc_per_node=4 \
  research/llm_fl_stress/fsdp2_gpu_gate.py
```

The gate uses a small deterministic model and NCCL. It loads a CPU full state
held only by rank zero into FSDP2 shards, gathers and verifies a rank-zero-only
CPU full state, performs one real sharded optimizer step, verifies that a known
parameter changed, and repeats the full-state gather. Its single JSON result
includes PyTorch/CUDA/NCCL versions plus per-rank loss, CPU RSS, peak GPU memory,
and load/export durations. It does not contact the Hugging Face Hub, allocate an
NVFLARE job, or modify system packages.

## Model Tiers

One model family keeps architecture and dtype differences out of the first
scaling curve. The official Qwen2.5 model cards list
[14.7B](https://huggingface.co/Qwen/Qwen2.5-14B),
[32.5B](https://huggingface.co/Qwen/Qwen2.5-32B), and
[72.7B](https://huggingface.co/Qwen/Qwen2.5-72B) parameters. These are practical
family-consistent baselines near the requested 10B, 30B, and 70B tiers. The
separate exact 10B diagnostic below provides the requested lower-tier data point.

The same official family also provides
[0.49B](https://huggingface.co/Qwen/Qwen2.5-0.5B),
[1.54B](https://huggingface.co/Qwen/Qwen2.5-1.5B),
[3.09B](https://huggingface.co/Qwen/Qwen2.5-3B), and
[7.61B](https://huggingface.co/Qwen/Qwen2.5-7B) sizes for the scaling ramp.
For an even smaller bridge tier, the official
[SmolLM2-135M](https://huggingface.co/HuggingFaceTB/SmolLM2-135M) model card
identifies a 135M-parameter base model.
The exact 10B diagnostic uses the public
[Falcon3-10B-Base](https://huggingface.co/tiiuae/Falcon3-10B-Base) parameter
count. The synthetic harness does not download that repository or its weights.

### Single-Machine Ramp

| Scenario | Payload | Wire/round | Server plan | Each client | Same host | Local use |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `smoke.json` | 0.06 GiB | 0.25 GiB | 1.72 GiB | 0.82 GiB | 3.36 GiB | Passed |
| `smollm2-135m.json` | 0.25 GiB | 1.01 GiB | 3.14 GiB | 1.41 GiB | 5.96 GiB | Passed |
| `qwen25-0.5b.json` | 0.91 GiB | 3.65 GiB | 8.10 GiB | 3.48 GiB | 15.05 GiB | Diagnose `ENOBUFS` |
| `qwen25-1.5b.json` | 2.87 GiB | 11.47 GiB | 22.76 GiB | 9.59 GiB | 41.94 GiB | Distributed only |
| `qwen25-3b.json` | 5.76 GiB | 23.02 GiB | 44.42 GiB | 18.61 GiB | 81.64 GiB | Distributed only |
| `qwen25-7b.json` | 14.17 GiB | 56.70 GiB | 107.56 GiB | 44.92 GiB | 197.40 GiB | Distributed only |
| `falcon3-10b.json` | 18.63 GiB | 74.51 GiB | 140.95 GiB | 58.83 GiB | 258.61 GiB | One-round distributed risk diagnostic passed |
| `synthetic-12b.json` | 22.35 GiB | 89.41 GiB | 168.89 GiB | 70.47 GiB | 309.84 GiB | One-round distributed risk diagnostic passed |

The 32 GiB Mac is useful and already produced real data: smoke and 135M passed,
while the concurrent 0.49B run failed in the transport path with `ENOBUFS`.
That error means a socket or pipe could not proceed because buffer space was
unavailable or a queue was full. It is different from process-memory exhaustion
(`ENOMEM`) and disk exhaustion (`ENOSPC`). The run showed no swap or OOM signal,
so the leading hypothesis is same-host socket or queue pressure, not insufficient
model RAM. See the [machine decision guide](docs/machine-plan.md) for the exact
interpretation and evidence boundary.

Run the two one-variable diagnostics before leaving the Mac:

```bash
python3 research/llm_fl_stress/job.py \
  --scenario research/llm_fl_stress/configs/qwen25-0.5b-small-shards.json
python3 research/llm_fl_stress/job.py \
  --scenario research/llm_fl_stress/configs/qwen25-0.5b-serial.json
```

Do not run 1.5B same-host: its 41.94 GiB planning envelope exceeds the machine's
total RAM. The preflight blocks runs without enough currently available memory.

| Scenario | Payload | Wire/round | Server plan | Each client | Same host | Disk plan |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `qwen25-14b.json` | 27.38 GiB | 109.52 GiB | 206.61 GiB | 86.19 GiB | 378.99 GiB | 136.90 GiB |
| `qwen25-32b.json` | 60.54 GiB | 242.14 GiB | 455.27 GiB | 189.80 GiB | 834.87 GiB | 302.68 GiB |
| `qwen25-72b.json` | 135.41 GiB | 541.66 GiB | 1,016.86 GiB | 423.79 GiB | 1,864.45 GiB | 677.07 GiB |

Use `qwen25-14b-1r.json` for the first 14B capacity gate. It has the same
per-round payload and planning envelope as `qwen25-14b.json`, but stops after
one round; run the two-round file only after that artifact passes.

Use `qwen25-72b-1r.json` for the first 72B gate. It retains the 2 MiB transport
baseline and uses longer stream timeouts derived from the measured 32B path.
Run `qwen25-72b.json` for two rounds only after the one-round artifact passes.

Use `qwen25-32b-trim-probe.json` only for the explicit server-memory
attribution lane. It calls allocator-aware cleanup before the first client
contribution in each round and records unique tensor storage by owner. It is not
the unchanged baseline scenario.

After that probe passes, use `qwen25-32b-3client-trim-probe.json` to change the
fan-out from two clients to three while retaining the same memory diagnostic.
It requires a startup kit containing `site-3` and defaults that site's SSH alias
to `flare-site-3`.

Use `qwen25-32b-f3-tuned-1r.json` for the controlled high-throughput transport
comparison. It keeps the 32.5B BF16 model, two-client topology, disk offload,
and allocator trim while changing the lower F3 stream from its 1 MiB frame,
16 MiB window, and 4 MiB ACK defaults to 4 MiB, 128 MiB, and 32 MiB. These are
service-startup settings; redeploy all FLARE services with the matching options
documented in [the three-client runbook](docs/three-client-32b-run.md) before
submitting the job. The production harness refuses a mismatched environment.

These are planning envelopes, not observed requirements. The recalibrated model
includes fixed Python/PyTorch/FLARE overhead, a six-payload server allowance, a
2.5-payload client allowance, and 20% reserve. These are conservative modeling
coefficients, not a claim that exactly that many tensor objects always coexist.
The plan intentionally rounds above the two successful local measurements. See
the [metrics and sizing guide](docs/metrics-guide.md) for formulas and
plain-language definitions.

The next network-efficiency lease should use exactly three CPU machines: one
256-GiB server and two 128-GiB clients, preferably with 25-Gbps-class private
connectivity and local NVMe. A cheaper 128/64/64-GiB topology is enough for the
1.5B transport microbench, but the recommended allocation can also confirm 14B
and one-round 32B without reprovisioning. GPUs are not required. The 72B gate is
deferred until the application path improves materially above its measured
0.75--0.80 Gbps per flow. The exact staged configurations are in the
[machine decision guide](docs/machine-plan.md).

Normal simulation refuses to start when conservative available-RAM or free-disk
checks fail. Use `--allow-capacity-risk` only for a deliberate constrained-memory
or constrained-disk failure run.

## Controlled Failure Lane

Production runs can place any configured host label (`server`, `site-1`, and so
on) in a temporary per-run cgroup while keeping SSH, admin, and telemetry
processes outside it. The harness captures `memory.stat`, `memory.events`, and
`memory.pressure`, removes the cgroup afterward, and restarts a service killed by
the test. The same controls work with every model scenario.

This 10B command reproduced a server OOM after both clients returned valid
updates:

```bash
python3 research/llm_fl_stress/job.py \
  --scenario research/llm_fl_stress/configs/falcon3-10b.json \
  --production --startup-kit-location <admin-kit> \
  --ssh-config research/llm_fl_stress/.local/ssh_config \
  --skip-result-download --allow-capacity-risk \
  --cgroup-memory-max-gib server=42 \
  --cgroup-memory-high-ratio 1.0 \
  --expect-cgroup-oom server
```

`--expect-cgroup-oom` changes the successful harness verdict to
`EXPECTED_FAILURE` only when every named host records a new `oom_kill`; a
timeout, peer loss, or ordinary job failure cannot falsely satisfy it. The
default high ratio is `0.9`, which is useful for a reclaim/pressure lane. Use
`1.0` when the objective is a hard OOM rather than prolonged soft throttling.
Any managed cgroup OOM is polled whether or not it was expected. An unexpected
`oom_kill` now ends collection immediately with `FAILED:CGROUP_OOM` instead of
waiting for the normal job timeout. The same production loop polls FLARE status;
both checks default to five seconds and can be changed with
`--status-poll-interval-seconds`.

To measure reclaim pressure without imposing an artificial hard limit, set an
absolute soft threshold only:

```bash
python3 research/llm_fl_stress/job.py <production-options> \
  --skip-result-download --allow-capacity-risk \
  --cgroup-memory-high-gib server=320
```

This leaves `memory.max` at the cgroup's natural host/scheduler ceiling. Crossing
320 GiB asks Linux to reclaim and throttle and increments `memory.events:high`;
it does not make 320 GiB an OOM boundary. Use `--cgroup-memory-max-gib` only for
an intentional hard-cap test.

An operator can auditably lower an active run's hard limit without editing the
run directory by hand:

```bash
python3 research/llm_fl_stress/ops/adjust_cgroup_limit.py \
  --ssh-config research/llm_fl_stress/.local/ssh_config \
  --ssh-alias <host-alias> --run-id <run-id> --host-label server \
  --memory-max-gib <new-limit>
```

For a larger model, change only the scenario and model-appropriate limit. Start
from a known passing run, keep the limit role-specific, and preserve the failed
artifact before trying another threshold.

## Single-Machine Representativeness

A same-host run is representative for FLARE recipe correctness, tensor
serialization, streaming and disk offload, FedAvg aggregation, persistence,
sentinel integrity, failure classification, and the server process's phase RSS.
It is also useful for building the first payload-versus-memory scaling curve.

For one- and two-round scenarios, round-end RSS growth is recorded as an
advisory rather than a pass/fail gate because allocator warm-up cannot be
distinguished from sustained growth with only two points. Use at least three
rounds when memory-growth enforcement, rather than peak capacity, is the goal.

It is not representative of real NIC throughput, TLS and network latency,
independent client/server memory limits, remote disconnects, scheduler behavior,
or multi-host concurrency. Shared RAM and storage also make process-tree peaks
more conservative than a server with remote clients. Use the laptop results to
validate the harness and relative scaling, then use separate hosts for final
14B, 32B, and 72B capacity decisions.

## What Is Measured

- Process-tree and per-role RSS/VMS, CPU, threads, and read/write bytes.
- System available memory, swap, filesystem free space, cgroup limit/peak,
  anonymous/file/kernel memory, clean versus dirty/writeback file cache,
  active/inactive file cache, reclaimable/unreclaimable slab, page faults,
  pressure, and per-run OOM counter deltas.
- Server memory before/after aggregation and persistence for every round.
- Client memory and duration around receive and send operations.
- F3 cache hits, duplicate serializations, serialization bytes/time, and peak
  cached bytes, emitted once per completed transfer transaction.
- Tensor-offload bytes/files, header parsing and disk-write time, plus lazy
  materialization bytes/time and offload-directory lifetime.
- GPU memory/utilization when `nvidia-smi` is present.
- Workspace and checkpoint sizes, terminal status, aggregation evidence, and
  classified OOM, disk, transfer, peer, serialization, and checkpoint failures.
- A deterministic sentinel proving that each client received the expected global
  model and that FedAvg incorporated both client updates.

Process and cgroup telemetry defaults to a 0.5-second interval. This gives
multiple samples during the shortest measured aggregation phases while halving
the sampler work and CSV volume relative to the original 0.25-second
qualification runs. Each run preserves its effective interval in `scenario.json`.

The [metrics and sizing guide](docs/metrics-guide.md) explains what every major
planning, memory, transfer, correctness, and disk number answers and which values
should be used for same-host versus distributed machine sizing.

Client names are intentionally fixed to the sequential `site-1` through
`site-N` pattern because those indexes define the deterministic sentinel deltas.

## Real-Model Confirmation

Do not begin with full LLM training. After the synthetic 14B baseline passes,
run one confirmation with the actual Qwen2.5-14B tensor topology: load the real
base-model state, use one tiny fixed token batch, update only one selected layer
or adapter for one step, and still return the full state dictionary. This keeps
the server path comparable while checking transformer serialization, tensor
count, client GPU memory, and library compatibility. Repeat at 32B and 72B only
if the synthetic-to-real 14B memory ratio changes the machine decision.

A LoRA-only exchange is useful for client-training validation but is not a
replacement for this server stress test because its payload is much smaller.

## Safety Rules

- Always run `smoke.json` before a large scenario on a new machine image.
- Follow the [short-lived access runbook](docs/access-runbook.md) before using
  remote machines. Never store SSH private keys or NVFlare startup kits in this
  repository or its retained run directories.
- `--validate-only` and `--export-only` do not allocate model tensors; a normal
  invocation really allocates the configured payload on the FLARE server.
- Start with tensor disk offload enabled and at least 20% RAM and disk headroom.
- Preserve failed run directories. They are evidence, not disposable output.
- Do not start 72B until 32B passes with complete telemetry and no swap pressure.
- For scheduler or kernel kills, copy the allocation output and permitted kernel
  excerpt into the run's `logs/` directory before running `harness.finalize`.

See the [short-lived access runbook](docs/access-runbook.md) for SSH and NVFlare
credential handling, the [machine decision guide](docs/machine-plan.md) for exact node requests,
the [metrics and sizing guide](docs/metrics-guide.md) for number definitions,
the [expedited plan](docs/test-plan.md) for execution order, and the
[artifact contract](docs/artifacts.md) for file definitions. The
[2026-07-15 local baseline](docs/local-baseline-2026-07-15.md) records the first
32 GiB same-host measurements and the observed 0.49B transport failure. The
[2026-07-15 three-host qualification record](docs/qualification-session-2026-07-15.md)
records the sanitized readiness checks and measured results through the
one-round 10B diagnostic. The
[2026-07-17 result-download incident](docs/result-download-incident-2026-07-17.md)
traces the completed-job admin transfer timeout and explains why it appeared as
a misleading 600-second job timeout.
