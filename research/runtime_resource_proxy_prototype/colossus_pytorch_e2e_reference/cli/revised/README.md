# CLI before-and-after comparison

The text files in the parent [`cli`](..) directory are the exact output
captured from the September 21 Colossus run. They remain unchanged so the
earlier resource-time-first presentation can be reviewed.

The files in this directory render those same archived JSON records with the
revised CLI. No measurements were added or changed. The revision makes the
directly understandable values prominent:

- CPU resource-time divided by measured seconds is shown as average visible
  CPU units;
- memory byte-seconds divided by measured seconds is shown as average visible
  memory in GiB;
- GPU instance-seconds divided by measured seconds is shown as average visible
  full GPUs, under the plural heading `FULL GPUs`; and
- additive resource-time remains available in a separately labelled block.

`SAVED CONTENT` and `F3 REMOTE ACCEPTED` are omitted because every report in
this run records those sources as `unavailable/not_bound`. Their unavailable
state remains explicit in the JSON. MIG is also omitted because no MIG group
is present.

The old and revised views both show GPU as `N/A`; that is faithful to this
archived run's known CUDA Runtime discovery gap. The comparison is about
presentation, not a retroactive correction of the measurement.
