# Resource statistics simple design

Resource statistics gives users a best-effort record of the resources a job
could see, its recorded CPU work, files remaining in its run directory, and
selected application data sent between participants. It uses NVFlare's existing
access and dependencies. It requires no extra privileges, mounts, services,
operator settings, or changes to Python startup and imports.

## How a report reaches the user

```text
Prepare the normal job workspace
  -> observe CPU, RAM and CUDA capacity once
  -> record elapsed time, CPU work and included application sends
  -> finish measurements and observe remaining files
  -> pass the report to the client parent
  -> release compute resources, then attach the report to the existing completion notification
  -> server saves participant measurements in the normal job workspace archive
  -> CLI reads the archive and calculates requested totals
```

The observation happens before application construction, after the existing
workspace preparation and custom-path refresh. Python startup imports may
already have run. These are site self-reports, not tamper-proof evidence.

## What each measurement means

| Measurement | Meaning and method |
| --- | --- |
| CPU capacity | Logical CPU units allowed by process affinity and readable cgroup limits; a quota may allow a fraction of a CPU. |
| RAM capacity | Physical RAM bounded by readable cgroup memory limits, not currently free RAM. |
| CUDA capacity | Devices available for CUDA execution to the job process, counted through the system CUDA Driver. Seeing a GPU does not prove the job used it. |
| Hardware descriptions | Optional CPU/GPU models and architecture; GPU type is verified with optional NVML or left unclassified. |
| Covered seconds | Monotonic elapsed time assigned to the capacity observation, including waiting. |
| CPU work | User and system CPU time for the process and descendants accounted for after waiting, with its own elapsed duration. Arbitrary un-waited descendants are not guaranteed covered. |
| Workspace filesystem | Visible total capacity of the filesystem containing the existing run directory, not storage owned by the job. |
| Remaining files | Bounded sum of regular-file logical lengths under the run directory, excluding symlinks and the top-level report directory. |
| Application data | Accepted payload bytes and logical messages for job deployment, actual task responses, and task results, grouped by destination. Not network-interface traffic or proof of receipt. |

The report keeps capacities and seconds separately. This illustrative excerpt
means two CPU units, 2 GiB of RAM, and one CUDA device over ten covered seconds:

```json
{
  "resource_capacity": {
    "measured_seconds": "10",
    "cpu": {"groups": [{"units": "2"}]},
    "memory": {"bytes": "2147483648"},
    "gpu": {"groups": [{"kind": "cuda_device_unclassified", "count": "1"}]}
  },
  "cpu_consumed": {"seconds": "2", "measured_seconds": "10"}
}
```

Average CPU used is 2 CPU seconds / 10 seconds = 0.2 CPUs. A query can separately
derive 20 CPU-unit seconds, 20 GiB-seconds, and 10 CUDA-device seconds. Shared
hardware may appear in several participants' observations; adding their
capacity-time does not establish exclusive ownership. Filesystem capacity is
never multiplied by time or summed across participants.

## Missing information

Successful measurements have no status label. A partial measurement retains
known values; unavailable means no usable value. A missing Driver is unavailable,
not zero. A successful Driver observation of no devices is zero. Missing GPU
information does not hide a valid CPU average.

The server checks report identity and contents. It keeps accepted reports in
memory until job finalization writes the archive files. A server crash before
that write can lose data. Missing reports remain gaps; statistics must not
turn a successful training job into a failed one. No durable recovery service
or isolated-group CPU accounting is added.

## Commands

```bash
nvflare job resources --job JOB_ID
nvflare job resources --job JOB_ID --site site-1
nvflare job resources --job JOB_ID --format json
nvflare job resources --study STUDY_NAME
```

Without `--study`, a job is looked up in the default study. Bare
`nvflare job resources` displays help. Study queries use each job's existing
access policy before reading its archive or including it in results.

See the [implementation guide](resource_statistics_implementation_blueprint.md)
for exact calls and code paths, the [current contract](../../research/runtime_resource_proxy_prototype/schema/CAPACITY_REPORT_CONTRACT_V3.md)
for fields, and the [generated examples](../../research/runtime_resource_proxy_prototype/schema/golden/v3/README.md)
for complete reports and CLI output. The final implementation supports only
the current report format, not earlier unreleased prototype formats.
