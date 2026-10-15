# Synthetic schema 3 examples

Every example here is synthetic contract and CLI material, not a captured
NVFlare run, benchmark, or launcher qualification. Hardware model labels are
illustrative; the large-value fixture is intentionally unrealistic to exercise
exact decimal-string arithmetic beyond floating-point precision.

`generate_v3_examples.py` builds raw-capacity participant records and job
summaries, validates exact archive inventories, serializes them with the
production writer, reads an in-memory workspace ZIP with the production
archive reader, and renders the production CLI views. The capacity-change
example covers 300 seconds at two GPUs followed by 300 seconds at one GPU.
Its query-derived GPU time is 900 device-seconds; those products are absent
from participant and job-summary storage. Partial, unavailable and missing
examples show independent coverage and counters.

The study combines two current-format jobs in one derived totals object. It
also contains one finished job without a report and one running job, which
appear in coverage rather than contributing invented zeros. Earlier prototype
formats and version cohorts are not supported.

From this worktree, using a Python environment with NVFlare's dependencies:

```bash
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 python -m research.runtime_resource_proxy_prototype.schema.generate_v3_examples --check
```

Omit `--check` only to regenerate this version 3 directory. The generator never
writes historical captures or review-deck materials.
