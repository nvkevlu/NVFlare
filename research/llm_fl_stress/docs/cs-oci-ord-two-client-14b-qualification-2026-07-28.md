# CS-OCI-ORD two-client 14B qualification — 2026-07-28

## Outcome

Slurm job `30986037` is a **formal qualification failure caused by an orchestration deadline race**, not a training
or federated execution failure.

The substantive 14B work completed:

- both real production clients registered;
- both four-rank FSDP2 groups loaded Qwen2.5-14B and trained;
- all eight ranks reported valid A100 memory and loss telemetry;
- both clients exported the complete 579-tensor, 29,540,067,328-byte state;
- both results reached the server with return code `OK`;
- the server aggregated 2/2 results; and
- the server logged `End persist model on server`.

The 720-second watchdog requested an abort at `07:20:07.730`. Persistence, which had already started, completed at
`07:20:09.449`—1.719 seconds later. The process therefore returned status 1 and Slurm correctly recorded `FAILED`,
even though persistence finished during abort handling. Because the persisted file was under ephemeral node-local
scratch and cleanup removed it before its size was captured, this run must not be relabeled as a formal pass.

## Exact timeline

| Time | Event |
|---|---|
| 07:05:44 | Production server service starts |
| 07:05:53 | Client services are available |
| 07:06–07:07 | Exact 1.5B gate runs |
| 07:07:45 | Gate aggregates 2/2 |
| 07:07:48 | Gate persistence completes |
| 07:08:06 | 14B server runner starts |
| 07:08:19 | 14B FedAvg round begins |
| 07:11:31 | Both 14B client tasks are assigned |
| 07:15:30 | Both 29.54 GB server-to-client state downloads finish |
| 07:19:21 | Site-1 result reaches the server |
| 07:19:29 | Server aggregates 1/2 |
| 07:19:30 | Site-2 result reaches the server |
| 07:19:38 | Server aggregates 2/2 |
| 07:19:40 | Server begins persistence |
| 07:20:07 | 720-second watchdog requests abort |
| 07:20:09 | Server logs successful end of persistence |

## Training evidence

Site-1:

- loss: `5.23686408996582`;
- selected-parameter maximum change: `1.52587890625e-05`;
- local load/train/export round: `17.75275007635355` seconds;
- full-state export: `11.62373803788796` seconds; and
- rank-0 maximum RSS: `61,187,833,856` bytes.

Site-2:

- loss: `5.263121604919434`;
- selected-parameter maximum change: `1.52587890625e-05`;
- local load/train/export round: `21.295618184376508` seconds;
- full-state export: `13.763840539380908` seconds; and
- rank-0 maximum RSS: `61,193,453,568` bytes.

Every rank reported an A100-SXM4-80GB, approximately 15.0 GB peak allocated GPU memory, and approximately 16.3 GB
peak reserved GPU memory. There was no NCCL, FSDP2, CUDA, model-loading, client-runner, transfer, aggregation, or
persistence error. The stderr messages were only the already-documented false-positive secret warnings for the
public 40-character Hugging Face revision.

## Transfer evidence and efficiency

This full-state qualification moves approximately 118.16 GB in one federated round:

- server to site-1: 29,540,115,112 bytes in 238.75 seconds;
- server to site-2: 29,540,115,112 bytes in 238.73 seconds;
- site-1 to server: 29,540,115,112 bytes in 213.97 seconds; and
- site-2 to server: 29,540,115,112 bytes in 218.39 seconds.

The Slurm allocation lasted 16:07, or approximately 2.15 allocated A100-hours. GPU monitoring captured 177 samples
for each index 0–7 and passed. The useful local training/export portion was only about 18–21 seconds per client; most
elapsed time was model startup and full-state movement. Full-state exchange is therefore useful as a 14B stress and
correctness qualification, but it is not an efficient structure for repeated real federated rounds.

For repeat or multi-round training, the recommended design is to keep the identical immutable 14B base at each site
and federate only the trainable last-layer parameters or deltas. The currently selected last layer has roughly
275 million trainable parameters, so a BF16 trainable-only payload would be hundreds of megabytes rather than
29.54 GB per client.

## Corrective action

The application-level total-runtime watchdog has been removed. It was not a valid safety control because it could
abort a healthy run at an arbitrary elapsed time. Supervision now separates:

- a readiness timeout, used only until both expected clients report ready;
- immediate aborts for explicit fatal service, runner, NCCL, FSDP2, or CUDA errors; and
- a no-progress timeout that begins only after both clients are ready and resets on meaningful transfer, training,
  result-submission, aggregation, or persistence activity.

Slurm's declared wall limit remains the ultimate allocation ceiling. The CPU preflight wall limit is also raised
from five to eight minutes because the successful cluster preflight `30985793` took 4:51.

## Rerun decision

Do not automatically rerun the full-state 14B qualification. This run already proves the production topology,
FSDP2 training, two-client transfers, 2/2 aggregation, and persistence at 14B. A rerun is justified only if a formal
`COMPLETED 0:0` artifact with captured persisted-model size is required.

Before any multi-round training experiment, implement and qualify trainable-only exchange instead of repeating
full-state movement.
