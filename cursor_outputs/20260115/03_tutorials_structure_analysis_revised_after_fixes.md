# REVISED Tutorial Analysis - Examples Found on Branches!
**Date:** January 15, 2026  
**REVISION:** Updated with official planning decisions from recipe conversion inventory  
**Source:** `cursor_outputs/recipe_conversions/inventory/ORIGINAL_confluence_summary.txt` and `20260114_CORRECTED_inventory.txt`

**IMPORTANT:** This analysis now reflects:
1. Official decisions on which examples to delete
2. XGBoost conversion completed Jan 13, 2026 on `add_xgb_recipe` branch
3. Team consultation items (Chester, Zhijin Li)
4. Examples that need README links only (not web page changes)

---

## 🎉 GREAT NEWS: Most Examples Exist!

After checking unmerged branches, **only 3 tutorials are truly missing**. The rest exist on branches waiting to be merged or need path updates.

---

## ✅ EXAMPLES FOUND ON BRANCHES (7 examples)

### 1. **Secure Federated XGBoost with Homomorphic Encryption** ✅
- **Web Page Says:** `examples/advanced/xgboost_secure`
- **Actually Exists On:** `add_xgb_recipe` branch
- **Actual Path:** `examples/advanced/xgboost/fedxgb_secure/`
- **Status:** Complete with README, job.py, and both horizontal & vertical FL
- **Action:** 
  - Option A: Wait for `add_xgb_recipe` to merge, then update web link to `examples/advanced/xgboost/fedxgb_secure/README.md`
  - Option B: Update web page now to point to future path

### 2. **Federated Vertical XGBoost** ✅
- **Web Page Says:** `examples/advanced/vertical_xgboost`
- **Actually Exists On:** `add_xgb_recipe` branch  
- **Actual Path:** `examples/advanced/xgboost/fedxgb/` (includes `job_vertical.py`)
- **Status:** Complete, integrated into consolidated xgboost example
- **Action:** 
  - Update web link to `examples/advanced/xgboost/fedxgb/README.md#vertical-federated-xgboost`
  - Or update description to clarify it's part of the main xgboost example

### 3. **ML/DL to FL** ✅
- **Web Page Says:** `examples/hello-world/ml-to-fl`
- **Actually Exists On:** `convert_to_recipe_tradml` branch
- **Actual Path:** `examples/hello-world/ml-to-fl/` with `np/`, `pt/`, `tf/` subdirs
- **Status:** Complete with README and examples for numpy, pytorch, lightning, tensorflow
- **Action:** Wait for merge, no path change needed!

### 4. **Federated Learning for Random Forest based on XGBoost** ✅
- **Web Page Says:** `examples/advanced/random_forest`
- **Actually Exists On:** `recipe-random-forest` branch
- **Actual Path:** `examples/advanced/random_forest/`
- **Status:** Complete with Recipe API, job.py, README, and notebook
- **Action:** Wait for merge, no path change needed!

### 5. **BraTS18 Segmentation with Differential Privacy** ✅
- **Web Page Says:** `examples/advanced/brats18`
- **Actually Exists On:** `recipe-random-forest` branch  
- **Actual Path:** `examples/advanced/brats18/`
- **Status:** Complete with dataset preparation, configs, and README
- **Action:** Wait for merge, no path change needed!

### 6. **Prostate Segmentation** ✅
- **Web Page Says:** `examples/advanced/prostate`
- **Actually Exists On:** `recipe-random-forest` branch
- **Actual Path:** `examples/advanced/prostate/`
- **Status:** Complete with 2D/3D versions, data preparation scripts
- **Note:** Also exists in `research/prostate` on main branch (older version?)
- **Action:** 
  - Wait for merge from `recipe-random-forest` branch
  - Keep web link as `examples/advanced/prostate` (NOT research/prostate)

### 7. **Kaplan-Meier Survival Analysis with HE** ✅
- **Web Page Says:** `examples/advanced/kaplan-meier-he`
- **Actually Exists On:** `add_survival` branch
- **Actual Path:** `examples/advanced/kaplan-meier-he/`
- **Status:** Complete with Recipe API, HE support, and comprehensive README
- **Action:** Wait for merge, no path change needed!

---

## ❌ OFFICIALLY MARKED FOR DELETION (7 examples)

**Source:** `cursor_outputs/recipe_conversions/inventory/ORIGINAL_confluence_summary.txt`

These examples were officially marked for deletion in the recipe conversion planning:

### 1. **BraTS18** - Line 276-279
- **Reason:** Too old
- **Action:** **REMOVE from web page**

### 2. **Finance End-to-End** - Line 378-381
- **Reason:** Already in tutorials
- **Action:** **REMOVE from web page**

### 3. **FL Hub** - Line 129-132
- **Reason:** No longer useful
- **Action:** **REMOVE from web page**

### 4. **Prostate** - Line 282-285
- **Reason:** Too old, already in tutorials, covered in MONAI example
- **Note:** Example exists on `recipe-random-forest` branch and in `research/prostate` BUT officially marked for deletion
- **Action:** **REMOVE from web page** (per official decision, not just path update)

### 5. **RAG/Embedding** - Line 439-443
- **Reason:** Overlapping with llm_hf example
- **Action:** **REMOVE from web page**

### 6. **Getting Started** - Line 135-138
- **Status:** Does not exist
- **Action:** **REMOVE from web page**

### 7. **Hello FedAvg** - Line 159-162
- **Note:** `examples/advanced/fedavg-with-early-stopping/` exists but needs team consultation
- **Action:** 
  - Option A: **REMOVE** (if redundant)
  - Option B: Update link to `examples/advanced/fedavg-with-early-stopping/`

---

## ⚠️ SPECIAL CASES - Team Consultation & Link-Only Updates

**Source:** `cursor_outputs/recipe_conversions/inventory/ORIGINAL_confluence_summary.txt`

### TEAM CONSULTATION NEEDED

### 1. **Logistic Regression with Newton-Raphson** - Line 207-211
- **Web Page Link:** `examples/advanced/lr-newton-raphson`
- **Status:** ❌ Does NOT exist
- **Team Note:** "Hello-LR, asking Zhijin Li to merge Hello-LR Recipe"
- **Action:** **WAIT for team decision** - may be merged with hello-lr or removed

### 2. **FedAvg with Early Stopping** - Line 159-162 (Hello FedAvg)
- **Current Path:** `examples/advanced/fedavg-with-early-stopping/`
- **Team Note:** "Ask Chester if this needs to be converted or after FOX, — Merge with FedAvg"
- **Action:** **WAIT for team decision** - update link to advanced/fedavg-with-early-stopping OR remove

### ADD LINK IN README ONLY (Don't Remove from Web Page)

### 3. **Swarm Learning** - Line 221-225
- **Current:** `examples/advanced/swarm_learning` - README only, no code
- **Official Decision:** "Already in tutorials - add link in README"
- **Action:** 
  - **KEEP on web page**
  - Add link to tutorials in the example's README
  - Update web description to note "See also: tutorials"

### 4. **Finance** - Not specifically in web issues but related
- **Official Decision:** "Already in tutorials - add links in README"
- **Action:** Add links to tutorials in README (not a web page issue)

### 5. **NLP-NER** - Line 312-315
- **Official Decision:** "Already in tutorials - add link in README"
- **Action:** 
  - **KEEP on web page**
  - Add link to tutorials in the example's README

---

## 📋 SUMMARY TABLE (Based on Official Planning Docs)

| Tutorial Name | Status | Branch | Official Decision | Action |
|---------------|--------|--------|-------------------|--------|
| **CONFIRMED FOR REMOVAL (7)** |
| BraTS18 | On branch but obsolete | `recipe-random-forest` | Delete - too old | **REMOVE** |
| Finance End-to-End | README only | main | Delete - in tutorials | **REMOVE** |
| FL Hub | - | - | Delete - not useful | **REMOVE** |
| Prostate | On branch but obsolete | `recipe-random-forest` | Delete - in tutorials | **REMOVE** |
| RAG/Embedding | ❌ Missing | N/A | Delete - overlaps llm_hf | **REMOVE** |
| Getting Started | ❌ Missing | N/A | Not mentioned but missing | **REMOVE** |
| Hello FedAvg | Needs consultation | N/A | Ask Chester | **WAIT or REMOVE** |
| **READY ON BRANCHES (3)** |
| Secure XGBoost HE | ✅ Completed Jan 13 | `add_xgb_recipe` | Converted - ready | Update link after merge |
| Vertical XGBoost | ✅ Completed Jan 13 | `add_xgb_recipe` | Converted - ready | Update link after merge |
| ML/DL to FL | ✅ On Branch | `convert_to_recipe_tradml` | Being converted | Wait for merge |
| Kaplan-Meier HE | ✅ On Branch | `add_survival` | Being converted | Wait for merge |
| **SPECIAL HANDLING (3)** |
| Random Forest | On branch, may stay | `recipe-random-forest` | Not in delete list | Wait for merge |
| Newton-Raphson LR | ❌ Missing | N/A | Ask Zhijin Li | **WAIT** |
| Swarm Learning | README only | main | Add link, keep | Add README link |

---

## 🎯 RECOMMENDED ACTIONS (Based on Official Decisions)

### Immediate (Can do now):

1. **REMOVE 6 officially deprecated tutorials:**
   - BraTS18 (too old)
   - Finance End-to-End (already in tutorials)
   - FL Hub (no longer useful)
   - Prostate (too old, in tutorials/MONAI)
   - RAG/Embedding (overlaps with llm_hf)
   - Getting Started (doesn't exist)

2. **Update 3 examples on branches** with "(Available in upcoming release)" notes:
   - Secure XGBoost HE (on add_xgb_recipe - completed Jan 13, 2026)
   - Vertical XGBoost (on add_xgb_recipe - completed Jan 13, 2026)
   - ML/DL to FL (on convert_to_recipe_tradml)
   - Kaplan-Meier HE (on add_survival)

3. **WAIT for team decisions on 2 tutorials:**
   - Hello FedAvg → Ask Chester (may merge with fedavg-with-early-stopping)
   - Newton-Raphson LR → Ask Zhijin Li (may merge with hello-lr)

4. **NO ACTION needed for link-only examples** (handled via README, not web):
   - Swarm Learning (add link in README)
   - NLP-NER (add link in README)
   - Finance (add link in README)

### After Branch Merges:

1. **Update XGBoost links** when `add_xgb_recipe` merges:
   - Secure XGBoost: → `examples/advanced/xgboost/fedxgb_secure/`
   - Vertical XGBoost: → `examples/advanced/xgboost/fedxgb/` (or add anchor link)

2. **Verify paths** after these branches merge:
   - `convert_to_recipe_tradml` (ml-to-fl)
   - `recipe-random-forest` (random_forest, brats18, prostate)
   - `add_survival` (kaplan-meier-he)

---

## 📊 REVISED STATISTICS

**Original Assessment:**
- 67 total tutorials
- 21 with issues (31%)

**After Branch Discovery & Official Planning Docs:**
- 67 total tutorials
- **6 officially marked for deletion** (team decision)
- **4 exist on branches** (waiting for merge)
- **2 need team consultation** (Chester, Zhijin Li)
- **3 are link-only updates** (not web page changes)

**Summary:** 6 to remove, 4 to note as "coming soon", 2 to wait on - much clearer now! 🎉

---

## 🔍 BRANCHES TO TRACK

Monitor these branches for merge status:

```bash
# Check branch status
git branch -a | grep -E "add_xgb_recipe|convert_to_recipe_tradml|recipe-random-forest|add_survival"

# Check if merged to main
git branch -a --merged main | grep <branch_name>
```

---

## 💡 LESSONS LEARNED

1. **Always check branches** before declaring examples "missing"
2. **Recipe conversions** are happening across many examples
3. **Examples are being consolidated** (e.g., multiple XGBoost examples → one directory)
4. **Active development** means web page may be ahead of main branch

---

## 📝 WEB PAGE UPDATE STRATEGY

### Strategy A: Conservative (Recommended)
- Remove only the 3-4 truly missing tutorials
- Add "(Coming soon)" notes for tutorials on branches
- Wait for branches to merge before updating paths

### Strategy B: Proactive
- Remove truly missing tutorials
- Update paths NOW to match future branch locations
- Add clear notes that examples are in development branches

### Strategy C: Minimal
- Do nothing now
- Wait for all branches to merge
- Then do one comprehensive update

**Recommendation:** Use Strategy A - remove broken links now, note coming-soon examples, update paths after merges.

---

## END OF REVISED ANALYSIS

**Key Insight:** The web page is actually fairly accurate - it's just ahead of the main branch!

Most "issues" will resolve automatically when the recipe-related branches merge. Only 3-4 tutorials are truly problematic.
