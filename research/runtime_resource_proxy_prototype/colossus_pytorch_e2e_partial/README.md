# Partial Colossus PyTorch E2E evidence

Status: partial evidence recovered from command output before SSH access to the
leased host was lost on September 18, 2026. This is not a replacement for the
missing archived resource-statistics records and must not be treated as a
fully reconciled golden or live reference.

This historical bundle is superseded by the complete
[September 21 PyTorch rerun](../colossus_pytorch_e2e_reference/README.md), which
preserves the archived records, exact CLI views, metrics, and GPU telemetry.
It remains here only to document what was lost with the earlier lease.

## What completed

The stock NVFlare `examples/hello-world/hello-pt` job ran in a fresh
Process-launch POC with one server and two clients on Colossus host
`ipp2-2159`:

- real CIFAR-10 data, pre-downloaded once to `/tmp/nvflare/data`;
- two clients using the same complete data set;
- three FedAvg rounds;
- four local epochs per client and round;
- batch size 64 and two data-loader workers;
- cross-site evaluation enabled; and
- one NVIDIA L40G shared by the two clients and server environment.

Job `da63407a-8f1b-48c2-9742-f10dfc4cb727` reached
`FINISHED:COMPLETED` in 87 seconds. See [job-wait.txt](job-wait.txt).

The exact installed environment and successful CUDA matrix-operation
preflight are preserved in [environment.txt](environment.txt). During the job,
NVIDIA process telemetry showed both NVFlare client Python processes resident
on the L40G with 542 MiB each. The surviving samples are in
[gpu-process-samples.txt](gpu-process-samples.txt).

## What was not recovered

The CLI text and JSON views, complete GPU telemetry CSV files, downloaded job
result, normal job-store `WORKSPACE`, and its four `resource_stats` JSON files
were written under this remote path:

```text
/tmp/nvflare-resource-pytorch-e2e-20260918/artifacts
```

SSH routing disappeared before those files were copied locally. The host used
a tmpfs-backed `/tmp`, so an expired lease with clean reprovisioning should be
assumed to have destroyed them unless the same still-running host becomes
reachable again.

Consequently, this partial bundle cannot verify the exact participant
durations, participant-to-job arithmetic, archived member inventory, study
rollup, cross-site evaluation result file, or whether the stricter pre-import
CUDA resource probe reported the same GPU that PyTorch used.

## What can still be concluded

This run is stronger than the earlier NumPy smoke test in several ways: a real
PyTorch CNN completed federated training over CIFAR-10, two client CUDA
processes were visible to NVIDIA telemetry, and the job lasted about ten times
longer than the NumPy job.

It does not establish realistic federated data heterogeneity because both
clients read the same complete CIFAR-10 data set. It also does not recover the
Phase 1 resource records needed to determine whether the longer run produced
the expected terminal capacity-time totals.

The local capture script that would have reconciled the archived records still
exists at `/private/tmp/capture_nvflare_pytorch_e2e.sh` for this Codex host,
but it contains the expired run's fixed job and path values and is not a
general test harness.
