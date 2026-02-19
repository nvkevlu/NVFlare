# sklearn Examples Fix - Merged to 2.7 (Jan 22, 2026)

**Date:** January 23, 2026  
**Status:** ✅ COMPLETE - Merged to online/2.7  
**PR:** #4015 by YuanTingHsieh  
**Merge Commit:** 96bb3619

---

## What Happened

The sklearn-svm and sklearn-kmeans examples were broken in 2.7 after the Recipe API migration. The `FedAvg` controller expects `ModelAggregator` (FLModel-based) but these examples used `CollectAndAssembleAggregator` (Shareable-based), causing silent fallback to incorrect weighted averaging.

---

## The Fix (Merged Jan 22, 21:07 PST)

### Code Changes

1. **New Adapter Class:** `CollectAndAssembleModelAggregator`
   - Location: `nvflare/app_common/aggregators/collect_and_assemble_model_aggregator.py`
   - Bridges FLModel-based `FedAvg` with Shareable-based `Assembler` components
   - Enables custom aggregation (SVM, K-Means) to work with modern workflow

2. **Recipe Updates:**
   - `nvflare/app_opt/sklearn/recipes/svm.py`: Uses `CollectAndAssembleModelAggregator`
   - `nvflare/app_opt/sklearn/recipes/kmeans.py`: Uses `CollectAndAssembleModelAggregator`
   - Both now add `key_metric` parameter

3. **Example Updates:**
   - `examples/advanced/sklearn-svm/job.py`: Added `key_metric="AUC"`

### Documentation Changes

The README was correctly updated to reflect the Recipe API design:

**What Changed:**
- ✅ Title: "Federated SVM with Scikit-learn" (removed "and cuML")
- ✅ Removed cuML intro section (was prominently at the top)
- ✅ Removed `--backend` parameter from basic usage examples
- ✅ Removed `--backend` from Options list
- ✅ Added "Advanced: Using cuML Backend" section explaining:
  - cuML is available via `per_site_config` for advanced users
  - Not exposed through `job.py` by default
  - Requires manual configuration in train_args

**Why This is Correct:**
- Recipe API simplifies the interface - most users don't need cuML
- Advanced users can still use it via `per_site_config`
- Consistent with design philosophy: simple by default, powerful when needed

---

## Current State (online/2.7 as of 96bb3619)

✅ **Aggregator:** Uses `CollectAndAssembleModelAggregator` (correct)  
✅ **job.py:** NO `--backend` parameter (correct)  
✅ **README:** Clean, cuML moved to advanced section (correct)  
✅ **Examples:** Work correctly with FedAvg controller

---

## Related Branches

- `yt_fix_sklearn_examples_27`: Local branch, should be deleted (contains incorrect README changes)
- `cherry-pick-sklearn-per-site-config-2.7`: Obsolete, should be closed
- `fix-sklearn-svm-readme-remove-backend`: Contains similar README fix, check if redundant

---

## Lesson Learned

**CRITICAL ERROR:** Failed to fetch from correct remote (`online`, not `origin`) immediately, causing massive time waste analyzing wrong branches and creating incorrect documentation.

**Root Cause:** WORKFLOW_RULES.md did not include git fetch verification step.

**Fix:** Updated WORKFLOW_RULES.md to include mandatory remote verification at start of analysis tasks.
