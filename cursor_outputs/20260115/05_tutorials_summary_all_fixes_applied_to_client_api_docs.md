# Tutorial Fixes Summary - Quick Action List
**Date:** January 15, 2026

This is a **quick reference** for the web page tutorial updates needed. See `astro_tutorial_webpage_analysis.md` for detailed analysis.

---

## 🔴 CRITICAL - Remove These Non-Existent Tutorials (9)

These tutorials need to be **REMOVED** from `web/src/components/tutorials.astro`:

1. **Getting Started** (lines 135-138)
   - Path: `examples/getting_started` ❌ DOES NOT EXIST

2. **ML/DL to FL** (lines 153-156)
   - Path: `examples/hello-world/ml-to-fl` ❌ DOES NOT EXIST

3. **Hello FedAvg** (lines 159-162)
   - Path: `examples/hello-world/hello-fedavg` ❌ DOES NOT EXIST

4. **Logistic Regression with Newton-Raphson** (lines 207-211)
   - Path: `examples/advanced/lr-newton-raphson` ❌ DOES NOT EXIST

5. **Random Forest** (lines 258-261)
   - Path: `examples/advanced/random_forest` ❌ DOES NOT EXIST

6. **Federated Vertical XGBoost** (lines 264-267)
   - Path: `examples/advanced/vertical_xgboost` ❌ DOES NOT EXIST
   - **NOTE:** `examples/advanced/vertical_federated_learning` DOES exist - could update path instead

7. **BraTS18 segmentation** (lines 276-279)
   - Path: `examples/advanced/brats18` ❌ DOES NOT EXIST

8. **Secure Federated XGBoost with HE** (lines 432-436)
   - Path: `examples/advanced/xgboost_secure` ❌ DOES NOT EXIST

9. **Federated Embedding Model Training / RAG** (lines 439-443)
   - Path: `examples/advanced/rag` ❌ DOES NOT EXIST

---

## 🟡 UPDATE - Fix These Incorrect Paths (1)

1. **Prostate Segmentation** (lines 282-285)
   - Current: `examples/advanced/prostate` ❌
   - Correct: `research/prostate` ✅
   - **Action:** Change path from `examples/advanced/prostate` to `research/prostate`

---

## 🟢 VERIFY - Check These Partial/Incomplete Examples (11)

These examples exist but need content verification:

1. **Kaplan-Meier HE** (lines 214-218)
   - Path: `examples/advanced/kaplan-meier-he`
   - **Action:** Verify README.md exists and is complete

2. **Swarm Learning** (lines 221-225)
   - Path: `examples/advanced/swarm_learning`
   - **Issue:** Only README.md exists, no example code
   - **Action:** Decide if this should be removed or if code should be added

3. **MONAI Experiment Tracking** (lines 300-303)
   - Path: `integration/monai/examples/spleen_ct_segmentation_local/README.md#51-experiment-tracking-with-mlflow`
   - **Action:** Verify the anchor link `#51-experiment-tracking-with-mlflow` is correct

4. **KeyCloak Site Authentication** (lines 306-309)
   - Path: `examples/advanced/keycloak-site-authentication/README.md`
   - **Action:** Verify README.md is current

5. **Supervised Fine Tuning (SFT) NeMo** (lines 330-333)
   - Path: `integration/nemo/examples/supervised_fine_tuning`
   - **Action:** Verify README exists and is current

6. **BioNemo Drug Discovery** (lines 360-363)
   - Path: `examples/advanced/bionemo`
   - **Action:** Verify content is current with latest BioNeMo

7. **TensorFlow Algorithms** (lines 372-375)
   - Path: `examples/advanced/job_api/tf`
   - **Action:** Verify the `tf` subdirectory exists

8. **Finance End-to-End** (lines 378-381)
   - Path: `examples/advanced/finance-end-to-end`
   - **Issue:** Only README.md exists, no code
   - **Action:** Decide if this is placeholder or should be removed

9. **System Monitoring** (lines 453-457)
   - Path: `examples/advanced/monitoring/README.md`
   - **Action:** Verify README is complete

10. **Distributed Optimization** (lines 460-465)
    - Path: `examples/advanced/distributed_optimization/README.md`
    - **Action:** Capitalize title to "Distributed Optimization" (currently lowercase)

11. **Federated Policies** (lines 111-114)
    - Path: `examples/advanced/federated-policies/README.rst`
    - **Action:** Verify README.rst (not .md) exists

---

## 📝 EDITING INSTRUCTIONS

### File to Edit:
`/web/src/components/tutorials.astro`

### How to Remove a Tutorial:
Find the tutorial object in the `tutorials` array (lines 8-467) and delete the entire object including braces and comma.

### Example - Remove "Getting Started":
```javascript
// REMOVE THIS:
{
  title: "Getting Started",
  tags: ["beg.", "algorithm", "client-api", "model-controller", "job-api", "pytorch", "lightning", "sklearn", "tensorflow"],
  description: "Getting started examples using the Client API, Model Controller API, and Job API for different frameworks.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/getting_started`
},
```

### Example - Update a Path:
```javascript
// CHANGE THIS:
link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/prostate/README.md`

// TO THIS:
link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/research/prostate/README.md`
```

### Example - Capitalize Title:
```javascript
// CHANGE THIS:
title: "distributed optimization",

// TO THIS:
title: "Distributed Optimization",
```

---

## ✅ PRIORITY ORDER

### Phase 1 - Immediate (High Priority)
1. Remove 9 non-existent tutorials
2. Update 1 incorrect path (Prostate → research/)
3. Capitalize "distributed optimization" title

**Estimated Time:** 30 minutes

### Phase 2 - Verification (Medium Priority)
1. Verify all 11 partial/incomplete examples
2. Update any anchor links if needed
3. Remove or complete incomplete examples (Swarm Learning, Finance End-to-End)

**Estimated Time:** 1-2 hours

### Phase 3 - Enhancement (Optional)
1. Add missing hello-world examples to catalog if desired:
   - hello-lightning
   - hello-numpy
   - hello-lr
   - hello-tabular-stats

**Estimated Time:** 30 minutes

---

## 📊 Statistics

- **Total Tutorials:** 67
- **Working Correctly:** 46 (69%)
- **Need Removal:** 9 (13%)
- **Need Path Fix:** 1 (1%)
- **Need Verification:** 11 (16%)

---

## 🔗 Quick Commands for Verification

```bash
# Verify experiment tracking examples
ls examples/advanced/experiment-tracking/tensorboard/README.md
ls examples/advanced/experiment-tracking/mlflow/README.md
ls examples/advanced/experiment-tracking/wandb/README.md

# Check partial examples
ls examples/advanced/kaplan-meier-he/README.md
ls examples/advanced/swarm_learning/
ls examples/advanced/finance-end-to-end/
ls examples/advanced/monitoring/README.md
ls examples/advanced/distributed_optimization/README.md
ls examples/advanced/federated-policies/README.rst

# Verify integration examples
ls integration/monai/examples/spleen_ct_segmentation_local/README.md
ls integration/nemo/examples/supervised_fine_tuning/README.md

# Check research
ls research/prostate/README.md
```

---

## 📄 Related Files

- **Full Analysis:** `cursor_outputs/20260115/astro_tutorial_webpage_analysis.md`
- **Tutorial Catalog:** `web/src/components/tutorials.astro`

---

**Ready to start making updates? Begin with Phase 1 (30 minutes of work).**
