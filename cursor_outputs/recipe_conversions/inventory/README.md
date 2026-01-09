# Recipe Conversion Inventory Documents

This directory contains documentation tracking the conversion of NVFlare examples from legacy config-based approaches to the modern Job Recipe API.

## Documents

### ⭐ Status Tracker (CURRENT - Use This!)
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
- **⭐ Want current status & action plan?** → Read `20251212_recipe_conversion_status_tracker.md` (MAIN)
- **Want hello-world deep dive?** → Read `20251212_hello_world_recipe_status.md`
- **Want original inventory?** → Read `20251203_recipe_conversion_inventory_all_examples.md` (reference)

### Which Document to Use?
- **Planning work**: Use the Status Tracker (shows priorities, effort, blockers)
- **Checking progress**: Use the Status Tracker (progress bars, completion %)
- **Deep dive on hello-world**: Use the Hello World Status doc
- **Historical reference**: Use the Original Inventory

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

## Latest Update Summary (Dec 12, 2025)

### What Changed
1. ✅ Created **Status Tracker** - more actionable than original inventory
2. ✅ Updated hello-world count: 8/9 done (89%) - was incorrectly 5/8
3. ✅ Identified 3 examples miscategorized (hello-lr, hello-flower, hello-tabular-stats)
4. ✅ Added 4-phase conversion roadmap with effort estimates
5. ✅ Separated by completion status for easier tracking

### Key Findings
- **14/43 examples converted** (33%) - was reported as 13
- **7 recipes created** so far
- **9 new recipes needed** for high-priority examples
- **CIFAR-10 is the biggest gap** (0% converted, most used)

### Next Actions
1. Create `CrossSiteEvalRecipe` (completes hello-world)
2. Convert cifar10-sim to `FedAvgRecipe`
3. Create `FedOptRecipe`, `FedProxRecipe`, `ScaffoldRecipe`

---

**Maintained By**: NVFlare Team
**Last Updated**: December 12, 2025
**Review Cadence**: Weekly
