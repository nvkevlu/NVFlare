# Earlier NumPy Colossus process-mode smoke reference

Status: captured evidence from one successful run on September 18, 2026. These
are real outputs, not deterministic golden fixtures.

For the primary live evidence, including a real PyTorch/CIFAR-10 workload and
the framework-bundled CUDA Runtime gap it exposed, see the complete
[PyTorch Colossus E2E reference](../colossus_pytorch_e2e_reference/README.md).

This run installed a wheel built from this worktree into a fresh Python 3.14
virtual environment on Colossus host `ipp2-2159`, then ran NVFlare's normal
Process-launch POC with one server and two clients. The submitted job was the
small built-in `hello-numpy-sag` integration job.

## What the run proved

The successful path crossed all of these production boundaries:

```text
installed Python -I worker bootstrap
  -> real CPU, memory, CUDA Runtime/Driver, and NVML probe
  -> private child-to-parent terminal handoff
  -> client-parent participant report assembly
  -> authenticated CellNet completion request
  -> root-parent validation and three-participant reduction
  -> normal WORKSPACE job-store archive
  -> authenticated admin API
  -> job, site-detail, and study CLI views
```

Job `84722338-787a-41b0-8132-6de19bb89c92` completed successfully. The server,
`site-1`, and `site-2` reports were all accepted. The production bundle
validator accepts the four archived JSON records and confirms that the job
totals exactly reconcile with the participant records.

The normal `WORKSPACE` contains exactly these resource-statistics records:

```text
resource_stats/resource_summary.json
resource_stats/participants/server.json
resource_stats/participants/site-1.json
resource_stats/participants/site-2.json
```

There is no staging member or separate resource-statistics storage component.

## Artifacts

| File | Meaning |
| --- | --- |
| [resources-job.txt](resources-job.txt) | Exact human job view returned through the live admin connection. |
| [resources-site-1.txt](resources-site-1.txt) | Exact site detail, including the CPU model, L40G model, and final workspace-filesystem observation. |
| [resources-study.txt](resources-study.txt) | Exact on-demand rollup for the retained jobs in study `default`. |
| [resources-job.json](resources-job.json) | Machine-readable job response. |
| [resources-site-1.json](resources-site-1.json) | Machine-readable job plus selected participant response. |
| [resources-study.json](resources-study.json) | Machine-readable study response. |
| [resource_summary.json](archive/resource_stats/resource_summary.json) | The actual job summary read from the archived `WORKSPACE`. |
| [server.json](archive/resource_stats/participants/server.json) | Archived server participant report. |
| [site-1.json](archive/resource_stats/participants/site-1.json) | Archived first-client participant report. |
| [site-2.json](archive/resource_stats/participants/site-2.json) | Archived second-client participant report. |
| [workspace-members.txt](workspace-members.txt) | Complete member inventory of the archived `WORKSPACE`. |

## How to read the numbers

The three participants shared one physical NVIDIA L40G on the same host. Each
participant correctly reports the GPU capacity visible during its own measured
interval. The job total adds those participant reports, so their overlapping
GPU time is deliberately counted more than once. The total is participant
resource-time, not physical cluster capacity.

`retained_content` and F3 are `unavailable/not_bound`, matching the documented
production gaps. The run proves the current Linux Process-launch path with an
unconstrained cgroup and one full GPU. It does not prove Docker, Kubernetes,
Slurm, constrained-cgroup, multi-GPU, or MIG behavior.

This earlier run is retained as the comparison case where a
system-resolvable CUDA Runtime allowed GPU collection to succeed. Its lease is
no longer expected to exist; the reviewable outputs are the files preserved
in this directory.
