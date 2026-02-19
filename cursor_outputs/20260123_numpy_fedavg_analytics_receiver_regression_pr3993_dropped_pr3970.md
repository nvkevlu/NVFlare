# Regression Report: NumpyFedAvgRecipe `analytics_receiver` Removed on 2.7

**Date:** 2026-01-23  
**Severity:** Regression — experiment tracking for NumPy FedAvg was added then removed on 2.7.  
**Remote used:** `online` (NVIDIA/NVFlare). 2.7 = `online/2.7`, main = `online/main`.

---

## What Happened (exact sequence)

1. **2026-01-15 — PR #3970 merged on 2.7**  
   - **Commit:** `1ed1ae979` — "[2.7] cherry pick fix for NumpyFedAvgRecipe experiment tracking (#3970)"  
   - **Change:** Added `analytics_receiver` to `nvflare/app_common/np/recipes/fedavg.py`: import, parameter, docstring, and pass-through so NumPy FedAvg could use experiment tracking (e.g. TensorBoard, MLflow).  
   - **File:** Single file change; 2.7 had the feature.

2. **2026-01-16 — PR #3973**  
   - **Commit:** `2089b3206` — "[2.7] expose key metric in recipe (#3973)"  
   - **Verification:** `analytics_receiver` still present in `nvflare/app_common/np/recipes/fedavg.py` after this commit.

3. **2026-01-21/22 — Regression**  
   - **Commit:** `090d16ccc` — "[2.7] FedAvg Merge with FedAvgEarlyStopping + InTimeAggregation (#3993)"  
   - **Author:** Chester Chen  
   - **PR:** #3993; described as "the same as main branch PR" https://github.com/NVIDIA/NVFlare/pull/3987  
   - **What the commit did:** Large refactor that made `NumpyFedAvgRecipe` subclass `UnifiedFedAvgRecipe` (from `nvflare/recipe/fedavg`) and rewrote the NumPy recipe to the new unified structure.  
   - **Regression:** In that rewrite, **`analytics_receiver` was not carried over.** The diff explicitly removes:
     - `from nvflare.app_common.widgets.streaming import AnalyticsReceiver`
     - `analytics_receiver` from the internal validator / API
     - The parameter and docstring from `NumpyFedAvgRecipe.__init__`
     - The pass-through of `analytics_receiver` into the job/validator
   - **Result:** From `090d16ccc` onward on 2.7, `NumpyFedAvgRecipe` no longer accepts or uses `analytics_receiver`. Experiment tracking for NumPy FedAvg on 2.7 was removed.

4. **All later commits on 2.7**  
   - Commits after `090d16ccc` that touch `nvflare/app_common/np/recipes/fedavg.py` do not restore `analytics_receiver`.  
   - **Current `online/2.7`:** File has no `analytics_receiver` (verified via `git show online/2.7:nvflare/app_common/np/recipes/fedavg.py` and grep).

---

## Why It Matters

- **User impact:** On 2.7, callers can no longer pass `analytics_receiver` to `NumpyFedAvgRecipe` for experiment tracking. Code that relied on PR #3970 would break or lose functionality after the merge.
- **No test caught it:** No test on 2.7 that instantiates `NumpyFedAvgRecipe(..., analytics_receiver=...)` or asserts experiment-tracking behavior for this recipe; otherwise the merge would have broken CI.
- **Main:** Commit `1ed1ae979` (PR #3970) is **not** an ancestor of `online/main`. Main never had this feature; the cherry-pick to main (your branch) is the first time it’s being brought to main.

---

## Root Cause

PR #3993 merged the unified FedAvg implementation (from main’s PR #3987) into 2.7. When the NumPy recipe was rewritten to subclass `UnifiedFedAvgRecipe`, the `analytics_receiver` addition from PR #3970 was not re-applied or preserved. So this is a **merge/refactor regression**: the new implementation was based on a version of the recipe that didn’t include the experiment-tracking parameter.

---

## Evidence (commands used)

```bash
git remote -v   # online = NVIDIA/NVFlare
git fetch online

# 1ed1ae979 is on 2.7 and added analytics_receiver
git show 1ed1ae979:nvflare/app_common/np/recipes/fedavg.py | grep -n analytics_receiver
# → multiple lines (import, param, doc, pass-through)

# Still present after next commit
git show 2089b3206:nvflare/app_common/np/recipes/fedavg.py | grep -n analytics_receiver
# → still present

# Gone after 090d16ccc
git show 090d16ccc:nvflare/app_common/np/recipes/fedavg.py | grep -n analytics_receiver
# → "GONE after 090d16ccc"

# Current 2.7 tip
git show online/2.7:nvflare/app_common/np/recipes/fedavg.py | grep -n analytics_receiver
# → No matches

# PR #3970 never on main
git merge-base --is-ancestor 1ed1ae979 online/main
# → exit non-zero (1ed1ae979 is NOT on main)
```

---

## Summary

| Item | Detail |
|------|--------|
| **Regression commit** | `090d16ccc` — [2.7] FedAvg Merge with FedAvgEarlyStopping + InTimeAggregation (#3993) |
| **Feature removed** | `analytics_receiver` on `NumpyFedAvgRecipe` (experiment tracking), added in PR #3970 |
| **Branch** | 2.7 (`online/2.7`) |
| **Cause** | Refactor to unified FedAvg in #3993 did not preserve PR #3970’s `analytics_receiver` in the NumPy recipe |
| **Fix** | Re-add `analytics_receiver` to `NumpyFedAvgRecipe` on 2.7 (and ensure unified parent supports it if needed), e.g. by cherry-picking or re-applying the PR #3970 behavior on top of current 2.7. |

This report reflects the exact history on `online` as of the investigation date.
