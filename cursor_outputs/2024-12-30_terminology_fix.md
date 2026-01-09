# Cross-Site Terminology Fix

**Date:** December 30, 2024
**Issue:** Changed "Cross-Site Validation" to "Cross-Site Evaluation" without considering NVFlare conventions

---

## The Problem

In Branch C, I changed the NumPy README title from:
```markdown
# Hello Numpy Cross-Site Validation
```

To:
```markdown
# Hello NumPy Cross-Site Evaluation
```

**This was incorrect** and broke consistency with existing NVFlare conventions.

---

## NVFlare's Mixed Terminology (Root Cause)

The NVFlare codebase itself uses BOTH terms interchangeably, which caused the confusion:

### Where "Evaluation" is Used
- **Class name**: `CrossSiteModelEval`
- **File name**: `cross_site_model_eval.py`
- **Official docs title**: "Cross Site Model Evaluation / Federated Evaluation"

### Where "Validation" is Used
- **Directory constant**: `CROSS_VAL_DIR = "cross_site_val"`
- **Task name**: `TASK_VALIDATION = "validate"`
- **Directory name**: `examples/hello-world/hello-numpy-cross-val/`
- **Original example title**: "Hello Numpy Cross-Site Validation"
- **Official docs reference**: Links to "Hello Numpy Cross-Site Validation"

### Even the Official Docs Mix Terms
From `cross_site_model_evaluation.rst`:
```
Title: "Cross Site Model Evaluation / Federated Evaluation"
Text: "run local validation" and "results of local validation"
```

---

## The Technical Distinction

After analyzing the codebase, the **proper semantic usage** is:

| Term | Usage | Example |
|------|-------|---------|
| **Validation** | The **task/action** clients perform | "Each client performs validation on its local data" |
| **Evaluation** | The **workflow/orchestration** | "The CrossSiteModelEval workflow coordinates validation" |

**In practice:** Both terms are acceptable for user-facing documentation, but consistency matters more.

---

## What I Fixed

### 1. Reverted Title to Match Convention ✅

**Changed back to:**
```markdown
# Hello NumPy Cross-Site Validation
```

**Reason:**
- Matches directory name (`hello-numpy-cross-val/`)
- Matches official docs reference
- Maintains historical consistency

### 2. Fixed User-Facing Text ✅

Changed user-facing descriptions to use "validation":
- "Cross-site validation creates..." (not "evaluation")
- "Run cross-site validation" (not "evaluation")
- "validation results" (not "evaluation results")
- "validated across all sites" (not "evaluated")

### 3. Kept API Names Unchanged ✅

**Did NOT change** (these are correct as-is):
- Function name: `add_cross_site_evaluation()` ← This is the API
- Class reference: `CrossSiteModelEval` ← This is the class name
- Code comments referring to the API

---

## Files Modified

### `examples/hello-world/hello-numpy-cross-val/README.md`

**Changes:**
- Title: "Cross-Site Evaluation" → "Cross-Site Validation" ✅
- Headings: "What is Cross-Site Evaluation?" → "What is Cross-Site Validation?" ✅
- Descriptions: Changed ~10 instances of "evaluation" to "validation" in user-facing text ✅
- API references: Left `add_cross_site_evaluation()` unchanged ✅

### `examples/hello-world/hello-pt/README.md`

**No changes needed** - This file uses "evaluation" which is acceptable since:
- It's new content from Branch A
- There was no existing convention to break
- The PyTorch example doesn't have "validation" in its directory name

---

## The Correct Pattern Going Forward

### For User-Facing Titles and Descriptions:
```markdown
# Cross-Site Validation
This workflow validates models across multiple sites...
```

### For Code and API References:
```python
# Use the actual API names (which use "evaluation")
add_cross_site_evaluation(recipe, model_locator_type="numpy")
```

### For Technical Documentation:
Either term is fine, but be consistent within a single document.

---

## Why This Matters

1. **Consistency**: The directory is called `hello-numpy-cross-val/`, so the README should match
2. **Discoverability**: Users searching for "cross-site validation" expect to find it
3. **Documentation links**: Official docs reference "Hello Numpy Cross-Site Validation"
4. **User expectations**: Existing users know it by the original name

---

## Summary of Terminology Usage

| Context | Use This | Don't Use |
|---------|----------|-----------|
| NumPy example title | "Cross-Site Validation" ✅ | "Cross-Site Evaluation" ❌ |
| User-facing descriptions | Either (but be consistent) | Mixed terms in same doc ❌ |
| API function names | `add_cross_site_evaluation()` ✅ | Don't change API ❌ |
| Class references | `CrossSiteModelEval` ✅ | Don't change class names ❌ |
| Technical explanation | "The workflow coordinates validation" ✅ | - |

---

## Lessons Learned

1. **Check existing conventions** before renaming
2. **NVFlare's mixed terminology** makes it confusing, but consistency trumps correctness
3. **Match directory names** in README titles
4. **Don't change API names** just to match user-facing text
5. **When in doubt, preserve the status quo** for public-facing content

---

## Status: FIXED ✅

All user-facing text in the NumPy README now uses "validation" consistently, while preserving API references that use "evaluation".

The PR should now be consistent with NVFlare conventions and user expectations.
