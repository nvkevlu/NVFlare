# Real PyTorch Colossus end-to-end reference

Status: complete evidence recovered from a real run on September 21, 2026.

This bundle shows what the current production prototype actually records for a
real CUDA workload. It is intentionally not a polished golden example. The run
completed successfully, all three resource reports reached the server, and the
job and study commands worked. It also exposed one GPU-discovery gap that a
synthetic fixture would have hidden. The follow-up prototype and production
collector check later in this bundle demonstrate the implemented fix.

## Start here

1. Read the exact [job CLI output](cli/resources-job.txt).
2. Compare it with the clearer [revised rendering](cli/revised/README.md),
   which uses the same archived JSON and preserves the old output unchanged.
3. Inspect the archived [job summary](workspace/resource_stats/resource_summary.json)
   and one [participant report](workspace/resource_stats/participants/site-1.json).
4. Read the [reconciliation and telemetry summary](telemetry/summary.json).
5. Review the GPU-discovery finding and its follow-up below before treating
   this original run's `FULL GPU h: N/A` as evidence that it did not use a GPU.

## What ran

The stock `examples/hello-world/hello-pt` job ran in one Process-launch POC on
Colossus host `ipp2-2318`:

- one server and two clients (`site-1` and `site-2`);
- real PyTorch 2.14.0 with CUDA 13.0 on one NVIDIA L40;
- CIFAR-10 with 50,000 training and 10,000 test images;
- three FedAvg rounds;
- four local epochs per client and round;
- batch size 64 and two data-loader workers; and
- cross-site evaluation after training.

Both clients used the same complete CIFAR-10 data set. This is a real compute
and transport test, but it is not an experiment in federated data
heterogeneity and its accuracy should not be treated as a benchmark.

Job `bb65f3e7-28bc-48d9-9ed4-656e596811fd` reached
`FINISHED:COMPLETED` in 82.6 seconds. See [job-wait.txt](run/job-wait.txt).
The exact NVFlare, PyTorch, torchvision, CUDA, and CUDA-matrix-operation
preflight is in [environment.txt](setup/environment.txt). The exported client
and server settings are under [job-config](setup/job-config).

Training completed all three rounds at client-reported accuracies of 9%, 59%,
and 65%. The final cross-site evaluation reported 65% for the global results
and 63% for each site result. The exact per-round records are in
[round_metrics.jsonl](training/round_metrics.jsonl) and
[metrics_summary.json](training/metrics_summary.json); the concise client-log
evidence is in [training-evidence.txt](training/training-evidence.txt).

## What the GPU telemetry proves

One-second `nvidia-smi` telemetry ran outside the resource-statistics
implementation. It is diagnostic evidence only; it was not used to populate
the resource records.

During the 76.073-second interval in which both client worker processes were
visible:

- both PyTorch processes were resident on the NVIDIA L40;
- each process reached 542 MiB of GPU memory;
- device memory reached 1,112 MiB in total;
- 55 of 76 device samples had nonzero GPU utilization;
- utilization averaged 13.84% and peaked at 35%; and
- power averaged 85.98 W and peaked at 92.30 W.

The derived figures and safe device-level source rows are in
[summary.json](telemetry/summary.json) and [gpu.csv](telemetry/gpu.csv). The
durable summary retains process counts and memory maxima but deliberately
omits process identifiers and executable paths.

## What the resource-statistics path produced

The server accepted exactly three reports: `server`, `site-1`, and `site-2`.
Job coverage is therefore complete. The production bundle validator passed,
the job totals equal a fresh derivation from the three participant records,
each site JSON view equals its archived record, the job JSON view equals the
archived summary, and the one-job study total equals the job total. See
[production-validation.json](workspace/production-validation.json) and the
`reconciliation` section of [summary.json](telemetry/summary.json).

The participant measurements are:

| Participant | Measured seconds | CPU unit-seconds | Memory byte-seconds |
| --- | ---: | ---: | ---: |
| `site-1` | 77.068958262 | 2466.206664384 | 10397983446627.58846464 |
| `site-2` | 76.594372593 | 2451.019922976 | 10333953335911.76964096 |
| `server` | 76.384144872 | 2444.292635904 | 10305589849337.20080384 |
| **Additive job total** | **230.047475727** | **7361.519223264** | **31037526631876.55890944** |

Each record resolves to 32 visible CPU units and 134,917,918,720 visible
memory bytes over its measured interval. The CPU model is
`AMD EPYC 7313P 16-Core Processor`. The human CLI renders the additive totals
as 2.0449 CPU hours and 8.0294 GiB-hours.

Because this POC ran every participant on the same machine, these additive
participant totals overlap. That is the design's intentional cross-participant
accounting policy; they are not a claim that the host had three independent
sets of CPU or memory.

Every participant also observed 1,889,447,919,616 bytes (1759.6855 GiB) as the
capacity of the filesystem containing its job workspace. This is a final
point-in-time filesystem observation, not usage, allocation, job-owned space,
or a billable value. It is shown only in site detail and is not multiplied by
time or aggregated.

`retained_content` and `f3` are `unavailable/not_bound` because this artifact
was captured before the current F3 bindings and before a retained-result owner
existed. The artifact is intentionally not rewritten.

## Original finding: real GPU work, but no GPU resource total

All three resource-time objects are `partial` with
`observation_incomplete`, and the CLI shows `FULL GPU h: N/A`. This is not
because the workload ran on the CPU. The independent telemetry above proves
that both client jobs used the L40.

The collector build used for this original run deliberately accepted a numeric
GPU count only after `cudaGetDeviceCount` succeeded. On this newly provisioned
machine, the NVIDIA driver supplied `libcuda` and NVML, but no CUDA Runtime
library was available through the system dynamic-linker search path. PyTorch
brought its own runtime at:

```text
<venv>/lib/python3.12/site-packages/nvidia/cu13/lib/libcudart.so.13
```

PyTorch can find that private dependency when it starts, so CUDA training
works. The trusted collector in that build ran before Torch or job code was
imported and could not resolve that library, so it correctly refused to infer
a count from `CUDA_VISIBLE_DEVICES`, NVML, or `nvidia-smi`. The observed library
locations are summarized without host-specific paths in
[gpu-probe-diagnosis.txt](setup/gpu-probe-diagnosis.txt), and
the exact collector result is in
[production-capacity-probe.json](setup/production-capacity-probe.json).

We intentionally did not add `LD_LIBRARY_PATH`, install a system CUDA toolkit,
or otherwise tune the machine to make the example pass. The design requires
no extra privilege or configuration. This original result therefore became a
direct test case for private-runtime discovery. Its archived JSON remains
unchanged so reviewers can see the failure honestly.

## Follow-up: absolute-path discovery works before PyTorch

On the same lease and in the same virtual environment, a focused program read
the installed `nvidia-cuda-runtime` distribution metadata, found its one owned
CUDA Runtime library, and loaded that file by absolute path with local symbol
scope. It did this before importing PyTorch and without changing
`LD_LIBRARY_PATH`.

The exact [prototype program](setup/pre_torch_absolute_cudart.py) and
[captured output](setup/pre_torch_absolute_cudart.txt) prove that:

- PyTorch was absent from `sys.modules` before and after CUDA enumeration;
- `cudaGetDeviceCount` returned one device from the absolute-path runtime;
- PyTorch 2.14.0 then initialized CUDA 13.0 normally; and
- a 2048-by-2048 CUDA matrix multiply on the L40 completed with finite output.

The collector now uses that behavior only as a fallback after ordinary dynamic
loader lookup or enumeration fails. It searches installed distribution
metadata under Python roots frozen before job paths are enabled, accepts only
an NVIDIA CUDA Runtime distribution and an exact CUDA Runtime filename,
requires one unique regular target contained in that installation root, and
loads it by absolute path. It still obtains the numeric count only from a
successful CUDA Runtime call and still requires Driver UUID and NVML matching
before publishing a positive GPU group. It does not import PyTorch or `nvidia`,
run a command, modify an environment variable, add configuration, or persist a
library path.

A wheel containing the production change was then installed into the test
virtual environment. The exact
[installed-collector check](setup/installed_collector_then_torch.py) and
[captured output](setup/installed_collector_then_torch.txt) show that the real
`probe_capacity()` returned 32 CPU units, 134,917,918,720 memory bytes, and one
NVIDIA L40 with 48,305,799,168 device-memory bytes before PyTorch was imported.
PyTorch again initialized and completed the CUDA matrix multiply.

Finally, the same real federated PyTorch job was run again. The
[fixed end-to-end run](fixed_run/README.md) contains its exact job, site, and
two-job study output. All three participants now report one visible NVIDIA L40
and complete resource time; the original run remains unchanged for comparison.

This closes the specific CUDA-13 wheel layout exposed by the run. Broader CUDA
versions, multiple GPUs, MIG, Windows, and packaging layouts without supported
Python distribution metadata still require validation. Unsupported or
ambiguous layouts continue to omit GPU data rather than infer a count.

## Artifact map

| Directory | Contents |
| --- | --- |
| [cli](cli) | Exact human and JSON output for the job, each participant, and the study. |
| [workspace](workspace) | The four archived `resource_stats` JSON files, their fixed-member inventory, and the production validation result. |
| [telemetry](telemetry) | Safe device-level GPU samples and a sanitized derived reconciliation summary. |
| [training](training) | Saved round metrics and concise evidence derived from the client logs. |
| [setup](setup) | Exact software preflight, production probes, CUDA diagnosis, pre-PyTorch absolute-load proof, installed-collector proof, and exported job settings. |
| [run](run) | Job submit and terminal wait output. |
| [fixed_run](fixed_run) | New end-to-end job after the private-runtime fix, including exact revised CLI and two-job study output. |

The checked-in bundle omits the CIFAR-10 archive, `.pt` model files, job
signatures/certificates, the installed wheel, complete job archive, submitter
metadata, broad logs, and raw process identifiers. The two focused follow-up
transcripts retain only the executable and CUDA Runtime paths needed to prove
the absolute-path test. No extra resource manifest or participant-name
encoding was added.
