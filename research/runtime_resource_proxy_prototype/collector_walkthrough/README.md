# Colossus resource collector walkthrough

This is a teaching version of the resource collector for the current Colossus
L40G machine. It is intentionally split into small steps so each output can be
traced to the call that produced it.

It is not the production implementation. In particular, the first two scripts
omit cgroup handling because cgroups do not narrow CPU or memory in the exact
execution context verified on `ipp2-2159`.

## First: there are no diagnostic shell commands in production

Production does not run `lscpu`, `taskset`, `nvidia-smi`, `df`, or similar
programs. It uses Python and native library calls directly:

| Value | Actual source used by production |
| --- | --- |
| CPU count | `os.sched_getaffinity(0)` plus applicable cgroup limits |
| CPU model | `/proc/cpuinfo` entries for the affinity-visible CPUs |
| CPU architecture | `platform.machine()` |
| Memory capacity | `os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")`, narrowed by an applicable cgroup limit |
| GPU count | CUDA Runtime `cudaGetDeviceCount` |
| GPU identity used for matching | CUDA Driver `cuDeviceGetUuid_v2` |
| GPU kind, model, and memory | NVML calls matched by CUDA UUID |
| Workspace-filesystem capacity | `os.statvfs(run_dir)` |
| Elapsed time | two `time.monotonic_ns()` readings |

The UUID is only a temporary join key between CUDA and NVML. It is not stored
in a participant report or job summary.

## Why the simple CPU and memory steps omit cgroups

The production collector inspected cgroup v2 on this host. For the tested SSH
process it found:

- CPU affinity: 32 CPUs.
- Root `cpuset.cpus.effective`: `0-31`, also 32 CPUs.
- Every applicable `cpu.max`: `max 100000`, meaning no finite CPU quota.
- Every applicable `memory.max`: `max`, meaning no finite memory limit.

Therefore cgroups did not change either selected value. This is specific to
this process context. A container, Slurm task, or later allocation can differ;
the real collector remains authoritative there.

## Run one source at a time

On the prepared Colossus host:

```bash
cd /tmp/nvflare-resource-probe.3QX8Ug
```

### 1. CPU

```bash
python3 -B collector_walkthrough/step_01_cpu.py
```

This maps the affinity-visible logical CPUs, homogeneous CPU model, and
architecture into the CPU capacity group.

### 2. Memory

```bash
python3 -B collector_walkthrough/step_02_memory.py
```

This prints the page size and page count separately, then their product. The
product becomes the selected memory capacity because there is no finite cgroup
memory limit here.

### 3. CUDA-authoritative GPU count

```bash
python3 -B collector_walkthrough/step_03_cuda_count.py
```

Only a successful `cudaGetDeviceCount` call can produce a number. The script
does not parse `CUDA_VISIBLE_DEVICES` and does not ask NVML for an inventory.

### 4. CUDA Driver UUID lookup

Pass the count from step 3:

```bash
python3 -B collector_walkthrough/step_04_cuda_uuids.py 1
```

The script requires the Driver API count to equal the Runtime API count before
mapping each visible ordinal to a UUID. The printed UUID is internal evidence
for the walkthrough only; production does not persist it.

### 5. NVML enrichment

Copy the bare UUID printed by step 4:

```bash
python3 -B collector_walkthrough/step_05_nvml_details.py UUID_FROM_STEP_4
```

This tries the `GPU-` and `MIG-` forms accepted by NVML and prints the kind,
model, and total memory for the CUDA-validated device.

### 6. Workspace filesystem

Pass the actual job workspace when one exists. Here `.` is the staged example
workspace:

```bash
python3 -B collector_walkthrough/step_06_filesystem.py .
```

The result is the capacity of the one filesystem containing that path. It is
not job usage, allocation, ownership, or billable storage.

### 7. Resource-time arithmetic

Pass the outputs from steps 1 through 3 and a requested wait in seconds:

```bash
python3 -B collector_walkthrough/step_07_resource_time.py 32 132501139456 1 2
```

The script measures the actual interval with `time.monotonic_ns()` and shows:

```text
CPU unit-seconds      = 32 × measured seconds
memory byte-seconds  = 132501139456 × measured seconds
GPU instance-seconds = 1 × measured seconds
```

### 8. Compare with the real collector

This final step imports the unchanged production collector rather than the
teaching scripts:

```bash
```

It prints the real participant summary so the earlier values can be matched to
their final fields.

## Observed on `ipp2-2159`

These values came from running the commands above on the prepared host. Timing
values change slightly on every run.

| Step | Raw observation | Value used by the report |
| --- | --- | --- |
| 1 | affinity IDs `0` through `31` | 32 CPU units; AMD EPYC 7313P; `x86_64` |
| 2 | page size `4096`; page count `32348911` | `132501139456` memory bytes |
| 3 | CUDA return code `0`; count `1` | one visible GPU |
| 4 | Driver count `1`; UUID lookup succeeded | CUDA-to-NVML match only; UUID not stored |
| 5 | NVML matched the CUDA UUID | one `full_gpu`; NVIDIA L40G; `24146608128` memory bytes |
| 6 | `16174456` blocks × `4096` bytes | `66250571776` workspace-filesystem capacity bytes |
| 7 | `2.000120241` measured seconds | `64.003847712` CPU unit-seconds; `265018210981.509328896` memory byte-seconds; `2.000120241` GPU instance-seconds |
| 8 | actual production duration `2.00019823` seconds | the same capacity sources produced `64.00634336`, `265028544612.87436288`, and `2.00019823` resource-time values |

## Final field map

| Final field | Walkthrough source |
| --- | --- |
| `resource_time.measured_seconds` | Step 7 monotonic end minus start |
| `resource_time.cpu.groups[].unit_seconds` | Step 1 units multiplied by elapsed seconds |
| CPU `model` and `architecture` | Step 1 `/proc/cpuinfo` and `platform.machine()` |
| `resource_time.memory.byte_seconds` | Step 2 bytes multiplied by elapsed seconds |
| `resource_time.gpu.groups[].instance_seconds` | Step 3 CUDA count multiplied by elapsed seconds |
| GPU `kind`, `model`, and `memory_bytes` | Step 5 NVML data for the CUDA/Driver-matched UUID |
| `workspace_filesystem.capacity_bytes` | Step 6 `f_blocks * f_frsize` |
| `retained_content` | Not measured by these probes; currently `unavailable/not_bound` |
| `f3` | Not measured by these probes; currently `unavailable/not_bound` |
| `job_id`, `participant_name`, `reported_at` | Trusted parent inputs and parent UTC clock, not machine probes |
