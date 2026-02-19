# ML-to-FL Documentation Cleanup - Action Plan

**Date:** January 15, 2026  
**Priority:** HIGH (Broken links in production)  
**Estimated Effort:** 4-6 hours  

---

## TL;DR

The ml-to-fl examples were **converted and then deleted**. The functionality now exists in hello-* and multi-gpu examples. We need to fix broken documentation links and clarify the current state.

---

## Immediate Actions (HIGH PRIORITY)

### 1. Fix Broken Web Documentation Links ⚠️

**Issue:** Web documentation points to non-existent `examples/hello-world/ml-to-fl/` directory

**Files to update:**

#### File 1: `web/src/components/tutorials.astro`
**Lines 141-145**

**Current (BROKEN):**
```javascript
{
  title: "ML/DL to FL",
  tags: ["beg.", "algorithm", "client-api", "numpy", "pytorch", "lightning", "tensorflow"],
  description: "Example for converting Deep Learning (DL) code to Federated Learning (FL) using the Client API. Configurations for numpy, pytorch, lightning, and tensorflow.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/hello-world/ml-to-fl`
}
```

**Proposed Fix (Option A - Split into separate entries):**
```javascript
{
  title: "Hello NumPy",
  tags: ["beg.", "algorithm", "client-api", "numpy"],
  description: "Simple federated learning example using NumPy and the Recipe API. Shows how to convert NumPy ML code to FL.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/hello-world/hello-numpy`
},
{
  title: "Hello PyTorch",
  tags: ["beg.", "algorithm", "client-api", "pytorch"],
  description: "Image classifier using PyTorch and FedAvg Recipe. Shows how to convert PyTorch ML code to FL.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/hello-world/hello-pt`
},
{
  title: "Hello TensorFlow",
  tags: ["beg.", "algorithm", "client-api", "tensorflow"],
  description: "MNIST classifier using TensorFlow and FedAvg Recipe. Shows how to convert TensorFlow ML code to FL.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/hello-world/hello-tf`
},
{
  title: "Multi-GPU Examples",
  tags: ["int.", "pytorch", "lightning", "tensorflow"],
  description: "Multi-GPU federated learning examples for PyTorch, Lightning, and TensorFlow using the Recipe API.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/multi-gpu`
}
```

**Proposed Fix (Option B - Update existing entry):**
```javascript
{
  title: "ML/DL to FL Examples",
  tags: ["beg.", "algorithm", "client-api", "numpy", "pytorch", "lightning", "tensorflow"],
  description: "Examples for converting Machine Learning code to Federated Learning using the Recipe API. See hello-numpy, hello-pt, hello-tf, and multi-gpu examples.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/hello-world#examples-by-framework`
}
```

**Recommended:** Option A (more discoverable)

---

#### File 2: `web/src/components/series.astro`
**Lines 182-186**

**Current (BROKEN):**
```javascript
{
  title: "ML/DL to FL",
  tags: ["beg.", "numpy", "pytorch", "lightning", "tensorflow"],
  description: "Example for converting Deep Learning (DL) code to Federated Learning (FL) using the Client API. Configurations for numpy, pytorch, lighting, and tensorflow.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/hello-world/ml-to-fl`
}
```

**Proposed Fix:**
```javascript
{
  title: "ML/DL to FL Examples",
  tags: ["beg.", "numpy", "pytorch", "lightning", "tensorflow"],
  description: "Examples for converting Machine Learning code to Federated Learning using the Recipe API. Includes NumPy, PyTorch, TensorFlow, and Lightning examples.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/hello-world#examples-by-framework`
}
```

**Effort:** 30 minutes  
**Testing:** Verify links work, check rendering on web

---

### 2. Update Inventory Documents

**Issue:** Inventory documents don't reflect that ml-to-fl was refactored into hello-* examples

#### File: `cursor_outputs/recipe_conversions/inventory/20260114_CORRECTED_inventory.txt`

**Add clarification section:**

```
================================================================================
ML-TO-FL STATUS CLARIFICATION
================================================================================

The ml-to-fl examples were converted to Recipe API and then refactored:

Original Plan (Dec 8, 2025):
  - Separate ml-to-fl directory with np/, pt/, tf/ subdirectories
  - Unified examples showing multiple training modes
  - Dedicated ML→FL conversion guides

Actual Implementation (Dec 17, 2025):
  - ml-to-fl directory deleted
  - Content merged into existing examples:
    • ml-to-fl/np → hello-numpy (Recipe API)
    • ml-to-fl/pt → hello-pt (Recipe API)
    • ml-to-fl/tf → hello-tf (Recipe API)
    • Multi-GPU variants → advanced/multi-gpu (Recipe API)

Current Status: ✅ 100% COMPLETE
  - All functionality exists in main branch
  - All examples use Recipe API
  - No technical gaps
  - Documentation links need updating

See: cursor_outputs/recipe_conversions/ml_to_fl/ML_TO_FL_STATUS_ANALYSIS.md
```

**Effort:** 15 minutes

---

### 3. Update Review Documents Status

**Issue:** Review documents reference work that was superseded

#### File: `cursor_outputs/recipe_conversions/ml_to_fl/ML_TO_FL_CONVERSION_REVIEW.md`

**Add header notice:**

```markdown
# ML-to-FL Recipe Conversion Review

**⚠️ HISTORICAL DOCUMENT - WORK WAS SUPERSEDED**

**Status:** This review was completed on December 11, 2025 for work in branch 
`local_ytrecipePR_branch`. However, this work was never merged. Instead, on 
December 17, 2025, a refactoring approach was taken (commit 7eb2f8d1) that 
deleted the ml-to-fl directory and merged content into existing hello-* and 
multi-gpu examples.

**Current State:** All functionality described in this review exists in main 
branch, but in a different structure. See ML_TO_FL_STATUS_ANALYSIS.md for 
current status.

**Original Review Date:** December 11, 2025  
**Superseded By:** Commit 7eb2f8d1 (December 17, 2025)  
**Current Status:** All Recipe conversions complete, content reorganized

---

## Original Review (Historical)

**PR Branch:** `local_ytrecipePR_branch`
**Commits Reviewed:** Last 3 commits (c7710512, a07f3477, bc0cde20)
**Review Date:** December 11, 2025
**Reviewer:** AI Code Review

[... rest of original review ...]
```

**Effort:** 10 minutes

---

#### File: `cursor_outputs/recipe_conversions/ml_to_fl/ML_TO_FL_REVIEW_CHECKLIST.md`

**Add header notice:**

```markdown
# ML-to-FL Conversion - Quick Review Checklist

**⚠️ HISTORICAL DOCUMENT - WORK WAS SUPERSEDED**

**Status:** This checklist was created for work in branch `local_ytrecipePR_branch` 
that was never merged. The ml-to-fl directory was deleted and content was merged 
into hello-* examples instead.

**Current State:** All functionality exists in main branch. See 
ML_TO_FL_STATUS_ANALYSIS.md for details.

---

## Original Checklist (Historical)

**PR Branch:** `local_ytrecipePR_branch`
**Status:** Superseded by refactoring approach
**Rating:** N/A (work not merged)

[... rest of original checklist ...]
```

**Effort:** 5 minutes

---

## Medium Priority Actions

### 4. Update README Files

#### File: `cursor_outputs/recipe_conversions/README.md`

**Update the ML-to-FL section:**

**Current:**
```markdown
└── ml_to_fl/
    └── ML_TO_FL_CONVERSION_REVIEW.md
```

**Updated:**
```markdown
└── ml_to_fl/
    ├── ML_TO_FL_STATUS_ANALYSIS.md       [NEW - Jan 15, 2026]
    ├── ACTION_PLAN.md                     [NEW - Jan 15, 2026]
    ├── ML_TO_FL_CONVERSION_REVIEW.md      [HISTORICAL]
    └── ML_TO_FL_REVIEW_CHECKLIST.md       [HISTORICAL]
```

**Add to Change Log:**
```markdown
### January 15, 2026
- ✅ **Clarified ML-to-FL status** - Work was completed then refactored
- ✅ Created comprehensive status analysis
- ✅ ml-to-fl examples merged into hello-* and multi-gpu (Dec 17, 2025)
- ✅ All Recipe conversions complete, content reorganized
- ⚠️ Web documentation links need updating (broken links to ml-to-fl)
- 📊 **Correct status: 100% complete** - functionality exists in different structure
```

**Effort:** 20 minutes

---

### 5. Create Migration Guide (Optional)

**File:** `cursor_outputs/recipe_conversions/ml_to_fl/MIGRATION_GUIDE.md`

**Content:**
```markdown
# ML-to-FL Examples - Where Did They Go?

If you're looking for the ml-to-fl examples, they were refactored and merged 
into existing examples in December 2025.

## Quick Reference

| Old Location | New Location | Status |
|--------------|--------------|--------|
| `ml-to-fl/np/` | `hello-numpy/` | ✅ Recipe API |
| `ml-to-fl/pt/` | `hello-pt/` | ✅ Recipe API |
| `ml-to-fl/tf/` | `hello-tf/` | ✅ Recipe API |
| `ml-to-fl/pt/` (DDP) | `multi-gpu/pt/` | ✅ Recipe API |
| `ml-to-fl/pt/` (Lightning) | `multi-gpu/lightning/` | ✅ Recipe API |
| `ml-to-fl/tf/` (Multi-GPU) | `multi-gpu/tf/` | ✅ Recipe API |

## What Changed?

### Before (Branch: local_ytrecipePR_branch)
```
examples/hello-world/ml-to-fl/
├── np/          # NumPy with multiple modes
├── pt/          # PyTorch with 4 variants
└── tf/          # TensorFlow with 2 variants
```

### After (Main Branch, since Dec 17, 2025)
```
examples/hello-world/
├── hello-numpy/     # Basic NumPy FL
├── hello-pt/        # Basic PyTorch FL
└── hello-tf/        # Basic TensorFlow FL

examples/advanced/multi-gpu/
├── pt/              # PyTorch multi-GPU
├── tf/              # TensorFlow multi-GPU
└── lightning/       # Lightning multi-GPU
```

## Why the Change?

The refactoring aimed to:
1. Reduce code duplication
2. Integrate with existing hello-* examples
3. Simplify directory structure
4. Make examples easier to find

## Finding What You Need

### For NumPy Examples
→ See `examples/hello-world/hello-numpy/`
- Uses NumpyFedAvgRecipe
- Supports full/diff update modes
- Has experiment tracking

### For PyTorch Examples
→ See `examples/hello-world/hello-pt/`
- Uses FedAvgRecipe (PyTorch variant)
- Basic single-GPU training
- Has experiment tracking

→ See `examples/advanced/multi-gpu/pt/`
- Multi-GPU PyTorch training
- DDP support

### For PyTorch Lightning Examples
→ See `examples/hello-world/hello-lightning/`
- Basic Lightning FL
- Uses FedAvgRecipe (Lightning variant)

→ See `examples/advanced/multi-gpu/lightning/`
- Multi-GPU Lightning training

### For TensorFlow Examples
→ See `examples/hello-world/hello-tf/`
- Uses FedAvgRecipe (TensorFlow variant)
- Basic single-GPU training

→ See `examples/advanced/multi-gpu/tf/`
- Multi-GPU TensorFlow training

## All Examples Use Recipe API

All the examples now use the modern Recipe API:

```python
from nvflare.app_opt.pt.recipes.fedavg import FedAvgRecipe
from nvflare.recipe import SimEnv, add_experiment_tracking

recipe = FedAvgRecipe(
    name="example",
    min_clients=2,
    num_rounds=3,
    initial_model=MyModel(),
    train_script="client.py",
)
add_experiment_tracking(recipe, tracking_type="tensorboard")

env = SimEnv(num_clients=2)
run = recipe.execute(env)
```

## Questions?

See the comprehensive analysis:
`cursor_outputs/recipe_conversions/ml_to_fl/ML_TO_FL_STATUS_ANALYSIS.md`
```

**Effort:** 30 minutes

---

## Low Priority Actions

### 6. Enhance hello-* READMEs with Conversion Guidance

Add sections to hello-numpy, hello-pt, hello-tf READMEs explaining how they 
demonstrate ML→FL conversion.

**Effort:** 1-2 hours

---

### 7. Create Comprehensive ML→FL Tutorial

Create a new tutorial document that explains ML→FL conversion process, 
referencing the existing examples.

**Effort:** 4-6 hours

---

## Summary of Actions

| Action | Priority | Effort | Status |
|--------|----------|--------|--------|
| Fix web documentation links | HIGH | 30 min | ⬜ TODO |
| Update inventory documents | HIGH | 15 min | ⬜ TODO |
| Update review document headers | HIGH | 15 min | ⬜ TODO |
| Update recipe_conversions README | MEDIUM | 20 min | ⬜ TODO |
| Create migration guide | MEDIUM | 30 min | ⬜ TODO |
| Enhance hello-* READMEs | LOW | 1-2 hrs | ⬜ TODO |
| Create ML→FL tutorial | LOW | 4-6 hrs | ⬜ TODO |

**Total High Priority Effort:** 1 hour  
**Total Medium Priority Effort:** 50 minutes  
**Total Low Priority Effort:** 5-8 hours  

---

## Testing Checklist

After making changes:

- [ ] Verify web documentation links work
- [ ] Check that tutorials.astro renders correctly
- [ ] Check that series.astro renders correctly
- [ ] Verify hello-* examples still work
- [ ] Verify multi-gpu examples still work
- [ ] Check that inventory documents are accurate
- [ ] Verify no other broken links to ml-to-fl

---

## Decision Needed

**Question:** Should we restore ml-to-fl as educational content?

**Option A: No (Recommended)**
- Accept current refactored state
- Fix documentation only
- Effort: 1-2 hours

**Option B: Yes**
- Cherry-pick work from local_ytrecipePR_branch
- Fix bugs identified in review
- Test thoroughly
- Effort: 20-30 hours

**Recommendation:** Option A - The functionality exists and works. Focus on 
documentation clarity rather than code restructuring.

---

**Next Steps:**
1. Get decision on restoration vs documentation-only approach
2. Execute high-priority actions (fix broken links)
3. Execute medium-priority actions (clarify status)
4. Consider low-priority actions (tutorials)

**Owner:** TBD  
**Target Completion:** Within 1 week for high-priority items
