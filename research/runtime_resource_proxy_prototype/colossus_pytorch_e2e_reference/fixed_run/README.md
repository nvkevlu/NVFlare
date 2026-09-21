# Fixed private-CUDA-runtime end-to-end run

This is the follow-up to the original PyTorch run in the parent directory. It
used the same Colossus lease, virtual environment, prepared one-server/two-client
Process POC, exported `hello-pt` job, CIFAR-10 data, and NVIDIA L40. The only
relevant implementation change was the collector's trusted absolute-path CUDA
Runtime fallback; the revised human renderer was also present.

Job `534b4073-9f7b-41ef-99fd-c4a0abd4229b` reached
`FINISHED:COMPLETED` in 81.0 seconds. See the exact [submit](run/job-submit.txt)
and [wait](run/job-wait.txt) transcripts. The POC was stopped after the output
was recovered; the lease was not released.

## Result

All three expected reports were accepted and all three resource-time values
are now `reported`, rather than `partial/observation_incomplete`:

| Participant | Measured seconds | Average visible CPU units | Average visible memory GiB | Average visible full GPUs |
| --- | ---: | ---: | ---: | ---: |
| `site-1` | 76.059206174 | 32.0000 | 125.6521 | 1.0000 |
| `site-2` | 76.062303083 | 32.0000 | 125.6521 | 1.0000 |
| `server` | 76.410302355 | 32.0000 | 125.6521 | 1.0000 |

The additive totals are 2.0314 CPU-unit hours, 7.9765 memory GiB-hours, and
0.0635 full-GPU instance-hours. These are participant totals. Because this POC
ran all three participants on one host and exposed the same L40 to each, their
intervals overlap; the GPU total is not a claim that the machine had three
physical GPUs.

The [site-1 detail](cli/resources-site-1.txt) names the AMD EPYC 7313P and
NVIDIA L40 and shows the L40's 44.9883 GiB device memory. It also shows the
1,759.6855 GiB visible capacity of the filesystem containing the job workspace.
That last value is a point-in-time observation only. It is not multiplied by
time, added across participants, called usage, or treated as job-owned storage.

`retained_content` and `f3` remain `unavailable/not_bound` in the exact JSON.
The human CLI omits those columns because no participant has a value. Nothing
was guessed or displayed as zero.

## What to review

- [One-job human output](cli/resources-job.txt): understandable per-participant
  averages first, additive resource-time second.
- [One-job JSON](cli/resources-job.json): exact accepted participant entries and
  additive job totals.
- [Site-1 human output](cli/resources-site-1.txt): hardware models and the
  non-additive workspace-filesystem observation.
- [Site-1 JSON](cli/resources-site-1.json): the complete participant record,
  including unavailable retained-content/F3 objects.
- [Study human output](cli/resources-study.txt): the corrected job beside the
  original partial-GPU job.
- [Study JSON](cli/resources-study.json): exact two-job rollup.

The original parent [`cli`](../cli) files remain unchanged. They are the
before-fix, before-renderer output. The parent [`cli/revised`](../cli/revised)
files isolate the presentation change by rendering the original JSON again.
This directory shows the final combination: fixed collection plus revised
presentation on a new real run.
