# Recipe Conversion Inventory Documents

This directory contains documentation tracking the conversion of NVFlare examples from legacy config-based approaches to the modern Job Recipe API.

## Documents

### ⭐⭐⭐ Current Verified Status (LATEST - Use This!)
**File**: `20260126_verified_status_inventory.txt`
**Created**: January 26, 2026
**Scope**: Complete verified status with all recent updates

**MAJOR UPDATES**:
- ✅ CIFAR-10 PT: 100% complete (9 jobs) - ALL algorithms converted!
- ✅ CIFAR-10 TF: 100% complete (4 jobs) - TensorFlow variants
- ✅ GNN: 100% complete (2 examples)
- ✅ Amplify: 100% complete (2 examples)
- ✅ MONAI: 100% complete (3 examples)
- ✅ BioNeMo: 100% complete (6 examples)
- ✅ NEW RECIPES: FedOptRecipe, ScaffoldRecipe, FedAvgRecipeWithHE

**Why use this**:
- ✅ **Current status: ~55+/60+ examples (~92%+)**
- ✅ **CIFAR-10 COMPLETE** - Was #1 blocker, now 100% done!
- ✅ **17+ recipes available** (3 new since Jan 14)
- ✅ **Verified by actual code inspection** (58+ job.py files checked)
- ✅ **All major use cases covered** (CV, NLP, GNN, Medical, Biology)

**Key Features**:
- Verified against actual codebase (not assumptions)
- Major conversions since Jan 14 documented
- Almost all examples now using Recipe API
- Minimal remaining work (~5% or less)

---

### 📋 Comprehensive Audit (Jan 12, 2026)
**File**: `20260112_comprehensive_status_and_consistency_audit.md`
**Created**: January 12, 2026
**Scope**: Complete status audit + detailed consistency analysis

**Why use this**:
- ✅ **Complete example-by-example status** (all 48 examples)
- ✅ **Detailed consistency audit** across 8 dimensions
- ✅ **Specific issues identified** for each example
- ✅ **File-level analysis** (what to rename, move, delete)
- ✅ ~200 files to delete, ~50 to rename, ~150 to update identified

**Use for**: Deep consistency analysis and file-level cleanup planning

---

### 📊 Status Tracker (Previous Version)
**File**: `20251212_recipe_conversion_status_tracker.md`
**Created**: December 12, 2025
**Scope**: Actionable status tracker for all examples

**Why use this**:
- ✅ Clear progress visualization
- 🎯 Prioritized action plan
- 📊 At-a-glance completion status
- 📋 Concrete next steps with effort estimates
- 🚧 Blockers and dependencies identified

**Key Features**:
- Progress bars by category
- Completed (14) vs Remaining (29) clearly separated
- 4-phase conversion roadmap
- Recipe creation checklist with priorities
- Weekly progress tracking

---

### 📊 Original Inventory (Reference)
**File**: `20251203_recipe_conversion_inventory_all_examples.md`
**Created**: December 3, 2025
**Scope**: Original comprehensive inventory of ALL examples

**Contents**:
- Hello World examples (8 examples)
- Advanced ML examples (sklearn, XGBoost, etc.)
- Computer Vision examples (CIFAR-10, medical imaging)
- NLP examples (transformers, LLMs)
- Federated Statistics examples
- Specialized examples (GNN, distributed optimization, etc.)
- Infrastructure examples (not requiring conversion)

**Summary Statistics**:
- Total ML examples tracked: 43
- Recipe API converted: 13 (30%)
- FedJob API (needs conversion): 23 (53%)
- Legacy JSON (high priority): 7 (16%)

**Key Sections**:
- Status breakdown by category
- Priority roadmap (high/medium/low)
- Recipe gaps analysis (what recipes need to be created)
- Migration strategy
- Tracking metrics with quarterly targets

---

### 🎯 Hello World Focus
**File**: `20251212_hello_world_recipe_status.md`
**Created**: December 12, 2025
**Scope**: Detailed analysis of hello-world examples only

**Contents**:
- Detailed status of all 9 hello-world examples
- Recipe usage patterns
- Code examples for each recipe
- Corrections to outdated inventory data
- Specific next steps for remaining conversions

**Key Findings**:
- ✅ 8/9 hello-world examples converted (89%)
- ⚙️ 1/9 still needs conversion (hello-numpy-cross-val)
- Identified 3 examples incorrectly marked in main inventory:
  - hello-lr: Actually uses `FedAvgLrRecipe` ✅
  - hello-flower: Actually uses `FlowerRecipe` ✅
  - hello-tabular-stats: Uses `FedStatsRecipe` ✅

**Action Item**: Create `CrossSiteEvalRecipe` to reach 100%

---

## Document Organization

```
cursor_outputs/recipe_conversions/
├── inventory/
│   ├── README.md (this file)
│   ├── 20251212_recipe_conversion_status_tracker.md ⭐ CURRENT
│   ├── 20251212_hello_world_recipe_status.md
│   └── 20251203_recipe_conversion_inventory_all_examples.md (reference)
├── plans/
│   └── 20251218_experiment_tracking_conversion_plan.md ⭐ NEW
└── ml_to_fl/
    └── ML_TO_FL_CONVERSION_REVIEW.md
```

---

## Usage

### For Quick Reference
- **⭐ Want current status & action plan?** → Read `20260114_current_status_inventory.txt` (MAIN)
- **⭐ Want consistency analysis?** → Read `20260112_comprehensive_status_and_consistency_audit.md`
- **Want Confluence-ready summary?** → Read `20260112_confluence_ready.txt`
- **Want original inventory?** → Read `20251203_recipe_conversion_inventory_all_examples.md` (reference)

### Which Document to Use?
- **Planning work**: Use Current Status Inventory (shows priorities, effort, blockers)
- **Checking progress**: Use Current Status Inventory (clear progress tracking)
- **File-level cleanup**: Use Comprehensive Audit (consistency issues, file operations)
- **Stakeholder updates**: Use Confluence-Ready Summary (clean format)
- **Historical reference**: Use Original Inventory

### For Updates
When updating these documents:
1. Create a new dated version (format: `YYYYMMDD_description.md`)
2. Update this README to point to the latest version
3. Keep old versions for historical reference

---

## Key Insights

### What's Working Well ✅
- **Sklearn examples**: 100% converted (linear, kmeans, svm)
- **Hello-world**: 89% converted (8/9 examples)
- **Recipe patterns**: FedAvg, Cyclic, Stats all working great

### What Needs Work 🔄
- **Computer Vision**: 0% converted (CIFAR-10 high priority)
- **XGBoost**: 25% converted (need histogram & vertical recipes)
- **NLP**: 0% converted (need transformer recipe)

### Missing Recipes 🎯
High priority recipes to create:
1. `CrossSiteEvalRecipe` - For hello-numpy-cross-val
2. `FedOptRecipe` - For CIFAR-10 FedOpt
3. `FedProxRecipe` - For CIFAR-10 FedProx
4. `ScaffoldRecipe` - For CIFAR-10 SCAFFOLD
5. `XGBHistogramRecipe` - For horizontal XGBoost
6. `XGBVerticalRecipe` - For vertical XGBoost
7. `TransformerRecipe` - For NLP examples

---

## Related Documentation

- **ML-to-FL Conversion**: `../ml_to_fl/ML_TO_FL_CONVERSION_REVIEW.md`
- **Recipe API Docs**: (link to official docs)
- **Example README files**: Each example's README.md

---

---

## Latest Update Summary (Jan 14, 2026)

### What Changed
1. ✅ **CORRECTED inventory** - XGBoost work was incorrectly omitted
   - Previous: Listed XGBoost as 0% (0/3)
   - Correct: XGBoost is 100% (3/3) - completed Jan 13, 2026
2. ✅ Fixed **NumpyFedAvgRecipe** to support experiment tracking (Jan 14)
   - Changed from FedJob to BaseFedJob
   - Now provides ConvertToFedEvent widget automatically
3. ✅ **XGBoost conversion completed** (Jan 13, 2026)
   - XGBHistogramRecipe created (251 lines)
   - XGBVerticalRecipe created (280 lines)
   - 57% code reduction, 24 tests created
4. ✅ Updated progress tracking: 31/39 examples (79%)
   - Up from incorrectly reported 22/39 (56%)
   - Denominator excludes 7 deletion + 2 deferral examples

### Key Findings
- **31/39 examples converted** (79%) - NOT 22/39
- **14 recipes created** (including XGBHistogramRecipe, XGBVerticalRecipe)
- **5 new recipes needed** for high-priority examples
- **CIFAR-10 is the biggest remaining gap** (0% converted, most used)
- **Hello-world, Sklearn, Experiment Tracking, XGBoost, Multi-GPU**: All 100% complete

### Next Actions
1. 🔴 START CIFAR-10 recipe creation (FedOpt, FedProx, SCAFFOLD, Central)
2. 🟡 Review llm_hf (already uses FedAvgRecipe, needs verification)
3. 🟡 Complete hierarchical_stats (last statistics example)

---

**Maintained By**: NVFlare Team
**Last Updated**: January 14, 2026
**Review Cadence**: Weekly
