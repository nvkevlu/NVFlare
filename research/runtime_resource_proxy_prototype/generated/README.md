# Generated artifact sets

`actual_local/` is produced by `../generate_artifacts.py` and is intentionally a mixed real/explicitly-unavailable capture:

- **real local values:** ordinary-user CPU/memory host fallback, filesystem capacity, exact size of a generated registry-owned result file, timestamps, hashes, and observed duration;
- **explicitly unavailable:** CUDA-derived GPU inventory unless a real CUDA adapter is integrated, F3 traffic (no CellNet counter is installed), and the separate server role (the generator is one local process);
- **not product data:** the job ID, participant ID, result payload, and `disabled`/error CLI fixtures are safe prototype constructs.

Regenerate the set from the prototype root:

```bash
python3 generate_artifacts.py --output generated/actual_local --observation-seconds 1
```

The existing `actual_local` capture predates the hardened exact-component layout, but its server-side query copy is byte-for-byte identical to its server aggregate. `manifest.json` hashes the canonical server aggregate and accepted participant records. The CLI directory contains actual-local all-site and selected-site output, plus deliberately constructed error/disabled behavior fixtures.

Current generator output uses an exact parent-owned component path instead:

```text
<capture>/job_store/jobs/<job-id>/RESOURCE_STATS
```

It additionally creates `<capture>/review_contracts/`, a deterministic synthetic contract-fixture set for the trusted-bootstrap, GPU authority, reporter lease, parent-owned fragments, F3 finalization, and exact-component rules. The review fixtures are not local resource observations.

## Current viewable review set

Use `feedback_hardened_local_20260904/` for the current pre-v1 realistic capture. The most useful entry points are:

- [generation receipt](feedback_hardened_local_20260904/generation_receipt.json) for provenance and integrity;
- [assembled job record](feedback_hardened_local_20260904/server_run/resource_stats/resource_summary.json);
- [byte-identical `RESOURCE_STATS` query copy](feedback_hardened_local_20260904/job_store/jobs/prototype-local-resource-proxy-v03/RESOURCE_STATS);
- [human CLI projection](feedback_hardened_local_20260904/cli/resources-all.txt) and [machine CLI projection](feedback_hardened_local_20260904/cli/resources-all.json); and
- [hardened fixture manifest](feedback_hardened_local_20260904/review_contracts/manifest.json).

`actual_local/` is retained only as historical prototype output and must not be treated as the
canonical schema example. The schema-validated records live in the
[canonical v1 golden set](../schema/golden/v1/), with the
[large-number final record](../schema/golden/v1/attempt_final_large_value.json) as a useful edge
case. Generated local captures remain observational evidence rather than golden test vectors.

The most realistic canonical output is the reproducible
[finalized-job tree](../schema/golden/v1/finalized_job/). Start with its
[receipt](../schema/golden/v1/finalized_job/generation_receipt.json),
[human CLI output](../schema/golden/v1/finalized_job/cli/resources-all.txt), or
[server resource summary](../schema/golden/v1/finalized_job/server_run/resource_stats/resource_summary.json).
