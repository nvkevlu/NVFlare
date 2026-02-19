# Astro Tutorial Catalog Audit — 2.7 Branch (Filesystem-Only)
**Date:** February 9, 2026  
**Branch:** 2.7 (verified with `git branch --show-current`)  
**Method:** Every GitHub `tree`/`blob` path was checked with `test -e` against the repo. No planning docs (e.g. Confluence summary) were used; only current layout on 2.7.

---

## Summary

| Action | Count | Details |
|--------|--------|--------|
| **Removed** | 5 | Paths do not exist on 2.7 |
| **Path fixed** | 5 | Paths moved/restructured on 2.7 |
| **Typos fixed** | 3 | Title/description only |
| **Unchanged** | All other entries | Paths verified present |

---

## 1. Removed (5 entries) — path missing on 2.7

| Title | Link path | Reason |
|--------|-----------|--------|
| Step-by-Step CIFAR10 Examples | `examples/hello-world/step-by-step/cifar10` | No `step-by-step` under `hello-world` on 2.7 |
| Step-by-Step HIGGS Examples | `examples/hello-world/step-by-step/higgs` | Same |
| Hello FedAvg | `examples/hello-world/hello-fedavg/README.md` | No `hello-fedavg` on 2.7 |
| Logistic Regression with Newton-Raphton | `examples/advanced/lr-newton-raphson` | Directory missing on 2.7 |
| Federated Learning for Random Forest based on XGBoost | `examples/advanced/random_forest/README.md` | No `random_forest` on 2.7 |

---

## 2. Path fixes (5 entries) — path exists at new location on 2.7

| Title | Old path | New path |
|--------|----------|----------|
| Simulated Federated Learning with CIFAR-10 | `examples/advanced/cifar10/cifar10-sim/README.md` | `examples/advanced/cifar10/pt/cifar10-sim/README.md` |
| Real-world Federated Learning with CIFAR-10 | `examples/advanced/cifar10/cifar10-real-world/README.md` | `examples/advanced/cifar10/pt/cifar10-real-world/README.md` |
| Histogram-based FL for XGBoost | `examples/advanced/xgboost/histogram-based/README.md` | `examples/advanced/xgboost/fedxgb/README.md` (description updated) |
| Tree-based Federated Learning for XGBoost | `examples/advanced/xgboost/tree-based/README.md` | `examples/advanced/xgboost/fedxgb/README.md` (description updated) |
| MONAI & NVIDIA FLARE Integration with Experiment Tracking | `integration/monai/examples/spleen_ct_segmentation_local/README.md` | `examples/advanced/monai/spleen_ct_segmentation/README.md` |

---

## 3. Typos fixed (3)

- **Parameter Efficient Fine Turning** → **Parameter Efficient Fine Tuning**
- **FedSM Alogithrm** → **FedSM Algorithm**
- **distributed optimization** → **Distributed Optimization**

---

## 4. Verification

- All remaining `tree/${gh_branch}/...` and `blob/${gh_branch}/...` links were checked; each path exists on 2.7.
- ReadTheDocs links (e.g. `nvflare.readthedocs.io`) were not checked (external).
- Lint: no errors on `web/src/components/tutorials.astro`.

---

## 5. Note on planning docs

This audit does **not** rely on:

- `ORIGINAL_confluence_summary.txt`
- `20260114_CORRECTED_inventory.txt`
- Any other planning or “official” list

Decisions are based only on whether the target path exists on the current 2.7 branch.
