# REVISED Quick Actions - After Branch Discovery
**Date:** January 15, 2026  
**REVISION:** Updated with official planning decisions from recipe conversion inventory  
**Source:** `cursor_outputs/recipe_conversions/inventory/ORIGINAL_confluence_summary.txt` and `20260114_CORRECTED_inventory.txt`

## 🎉 Good News!

After checking official planning documents and unmerged branches:
- **6 tutorials officially marked for deletion** (clear team decision)
- **4 tutorials on branches waiting to merge** (XGBoost completed Jan 13!)
- **2 tutorials need team consultation** (Chester, Zhijin Li)
- **3 tutorials just need README links** (not web page changes)

---

## ✅ Examples Found on Branches (7)

Your recipe conversion branches have these examples ready to go:

1. **Secure XGBoost with HE** - on `add_xgb_recipe`
2. **Vertical XGBoost** - on `add_xgb_recipe`  
3. **ML/DL to FL** - on `convert_to_recipe_tradml`
4. **Random Forest** - on `recipe-random-forest`
5. **BraTS18** - on `recipe-random-forest`
6. **Prostate** - on `recipe-random-forest`
7. **Kaplan-Meier HE** - on `add_survival`

---

## ❌ Actions Needed Now

### 1. Remove These 6 Officially Deprecated Tutorials:

**Source:** Official planning doc `cursor_outputs/recipe_conversions/inventory/ORIGINAL_confluence_summary.txt`

**Delete from `web/src/components/tutorials.astro`:**

```javascript
// Lines 276-279 - REMOVE (officially marked: too old)
{
  title: "Federated Learning with Differential Privacy for BraTS18 segmentation",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/brats18/README.md`
},

// Lines 378-381 - REMOVE (officially marked: already in tutorials)
{
  title: "End-to-End Federated XGBoost for Financial Credit Card Detection",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/finance-end-to-end`
},

// Lines 129-132 - REMOVE (officially marked: no longer useful)
{
  title: "Federated Learning Hub",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/fl_hub/README.md`
},

// Lines 282-285 - REMOVE (officially marked: too old, covered in tutorials)
{
  title: "Federated Learning for Prostate Segmentation from Multi-source Data",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/prostate/README.md`
},

// Lines 439-443 - REMOVE (officially marked: overlapping with llm_hf)
{
  title: "Federated Embedding Model Training",
  link: `https://github.com/NVIDIA/NVFlare/blob/${gh_branch}/examples/advanced/rag/README.md`,
},

// Lines 135-138 - REMOVE (doesn't exist)
{
  title: "Getting Started",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/getting_started`
},
```

### 2. WAIT for Team Decision on These 2:

```javascript
// Lines 159-162 - ASK CHESTER (may merge with fedavg-with-early-stopping)
{
  title: "Hello FedAvg",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/hello-world/hello-fedavg/README.md`
},

// Lines 207-211 - ASK ZHIJIN LI (may merge with hello-lr)
{
  title: "Logistic Regression with Newton-Raphton",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/lr-newton-raphson`,
},
```

---

### 3. Add "Coming Soon" Notes for 4 Tutorials on Branches

**Update descriptions** for these 4 tutorials to indicate they're coming in next release:

```javascript
// Line 432-436 - COMPLETED JAN 13, 2026 on add_xgb_recipe branch
{
  title: "Secure Federated XGBoost with Homomorphic Encryption",
  tags: ["adv.", "algorithm", "xgboost", "he", "highlight"],
  description: "Federated secure training with XGBoost using homomorphic encryption. (Available in upcoming release - completed Jan 13, 2026)",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/xgboost/fedxgb_secure/README.md`,
}

// Line 264-267 - COMPLETED JAN 13, 2026 on add_xgb_recipe branch
{
  title: "Federated Vertical XGBoost",
  tags: ["adv.", "algorithm", "xgboost", "ml"],
  description: "Vertical federated XGBoost using Private Set Intersection on HIGGS data. Part of consolidated XGBoost examples. (Available in upcoming release - completed Jan 13, 2026)",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/xgboost/fedxgb/README.md`
}

// Line 153-156 - On convert_to_recipe_tradml branch
{
  title: "ML/DL to FL",
  description: "Example for converting Deep Learning (DL) code to Federated Learning (FL) using the Client API. Configurations for numpy, pytorch, lightning, and tensorflow. (Available in upcoming release)",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/hello-world/ml-to-fl`
}

// Line 214-218 - On add_survival branch
{
  title: "Survival Analysis with Federated Kaplan-Meier",
  description: "Kaplan-Meier survival analysis in federated setting without and with secure features via time-binning and Homomorphic Encryption (HE). (Available in upcoming release)",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/kaplan-meier-he`,
}
```

**Note:** Random Forest status TBD - on recipe-random-forest branch but not in official conversion list

---

### 4. Update XGBoost Paths Now (Paths are known)

Since XGBoost conversion was **completed Jan 13, 2026** on `add_xgb_recipe` branch, update paths now:

**Line 432-436 - Update path:**
```javascript
// CHANGE:
link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/xgboost_secure`,

// TO:
link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/xgboost/fedxgb_secure/README.md`,
```

**Line 264-267 - Update path:**
```javascript
// CHANGE:
link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/vertical_xgboost/README.md`

// TO:
link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/xgboost/fedxgb/README.md`

// AND UPDATE description:
description: "Vertical federated XGBoost using Private Set Intersection on HIGGS data. Part of consolidated XGBoost examples. (Available in upcoming release - completed Jan 13, 2026)",
```

---

## 📋 Decision Points

### Swarm Learning & Finance End-to-End

**Official Decision from Planning Doc:**

**Swarm Learning (Line 221-225):**
- Status: Already in tutorials
- Action: Add link in README (NOT a web page change)
- Web page: **KEEP AS-IS**

**Finance End-to-End (Line 378-381):**
- Official Decision: **DELETE** - already in tutorials
- Action: **REMOVE from web page** (see section 1 above)

---

## 🎯 Minimal Changes Option (Safest)

If you want to make the absolute minimum changes now:

1. **Remove only 6 officially deprecated tutorials** (per planning doc):
   - BraTS18, Finance End-to-End, FL Hub, Prostate, RAG, Getting Started
2. **Wait for team decisions on 2** (Hello FedAvg, Newton-Raphson)
3. **Wait for branches to merge** before updating paths
4. **Add "coming soon" notes** to 4 on-branch examples

This follows official decisions and removes deprecated content.

---

## 📅 After Branch Merges

Once these branches merge to main, update the web page:

### When `add_xgb_recipe` merges:
- Update Secure XGBoost link → `examples/advanced/xgboost/fedxgb_secure/`
- Update Vertical XGBoost link → `examples/advanced/xgboost/fedxgb/`
- Remove "(Available in upcoming release)" notes

### When `convert_to_recipe_tradml` merges:
- Verify ML/DL to FL link works
- Remove "(Available in upcoming release)" note

### When `recipe-random-forest` merges:
- Verify Random Forest, BraTS18, Prostate links work
- Remove "(Available in upcoming release)" notes

### When `add_survival` merges:
- Verify Kaplan-Meier HE link works
- Remove "(Available in upcoming release)" note

---

## 📊 Summary

**Before branch discovery:**
- 21 tutorials with issues
- Seemed like lots of work

**After branch discovery:**
- 7 tutorials on branches (will auto-resolve)
- 4 tutorials truly missing (easy to remove)
- **Much simpler fix!**

---

## 🚀 Recommended Workflow (Based on Official Planning)

1. **Today:** Remove 6 officially deprecated tutorials (15 minutes)
2. **Today:** Add "(Coming soon)" notes to 4 tutorials on branches (10 minutes)
3. **Today:** Update XGBoost paths to match completed work (5 minutes)
4. **Soon:** Consult with Chester (Hello FedAvg) and Zhijin Li (Newton-Raphson)
5. **After merges:** Remove "coming soon" notes and verify links (5 minutes per branch)

**Total immediate work: ~30 minutes!**
**Plus: 2 team consultations needed**

---

## Want Me to Make the Changes?

Based on the official planning documents, I can now:

1. **Conservative:** Remove 6 officially deprecated tutorials only
2. **Recommended:** Remove 6 + add "coming soon" notes to 4 + update XGBoost paths
3. **Full:** Remove 6 + notes to 4 + update paths + add team consultation notes for 2

**Recommendation:** Option 2 (Recommended) - follows official decisions and prepares for upcoming merges

Just let me know which approach you prefer!
