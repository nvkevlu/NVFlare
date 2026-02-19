# January 12-13, 2026 - Cross-Site Evaluation (CSE) Enhancements

## Overview

Work spanning January 12-13, 2026 focused on fixing bugs, improving robustness, and adding TensorFlow support to the `add_cross_site_evaluation()` utility function in `nvflare/recipe/utils.py`.

---

## Files (Chronological Order)

### Core API Fixes (Jan 12)
1. `01_idempotency_protection_prevents_duplicate_components_from_multiple_calls.md` - Added flag to prevent duplicate calls
2. `02_pytorch_validation_clarified_uses_client_api_not_separate_component.md` - Fixed misleading docstring
3. `03_validator_detection_replaced_string_matching_with_executor_checking.md` - Robust `_has_task_executor()` helper

### TensorFlow Support (Jan 12-13)
4. `04_tensorflow_cse_support_added_file_model_locator_and_validator.md` - Added TF to CSE support matrix
5. `05_tf_model_persistor_fixed_missing_get_model_and_inventory_methods.md` - Implemented missing abstract methods
6. `06_tf_file_locator_fixed_bypassed_filter_processing_now_calls_get.md` - Fixed to use `get()` not `get_model()`
7. `07_persistor_id_validation_added_three_tier_checks_for_pytorch_tensorflow.md` - Defense-in-depth validation
8. `08_error_messages_improved_for_unsupported_frameworks.md` - Better framework error formatting
9. `09_tf_validator_usage_clarified_client_api_vs_component_pattern.md` - Decision guide for TFValidator

### NumPy Framework Fixes (Jan 12)
10. `10_numpy_framework_inconsistency_identified_raw_vs_numpy_mismatch.md` - Identified framework mismatch
11. `11_numpy_framework_mismatch_analyzed_two_fix_options.md` - Analyzed solution options
12. `12_numpy_framework_fixed_cross_site_eval_recipe_hardcodes_raw.md` - Hardcoded RAW in CSE recipe

### Additional Enhancements (Jan 12)
13. `13_duplicate_validator_prevented_robust_executor_detection_for_cse_recipes.md` - Skip validator for CSE-only recipes
14. `14_team_decision_feasibility_analyzed_proposed_api_simplifications.md` - API simplification feasibility
15. `15_cse_api_simplification_analyzed_reducing_framework_parameter.md` - Analysis of parameter reduction
16. `16_cse_api_examples_before_after_code_for_proposed_changes.md` - Code examples for UX improvements
17. `17_implementation_complete_all_fixes_applied_and_tested.md` - Summary of all changes

---

## Key Issues Resolved

### 1. Idempotency Protection (File 01)
**Problem:** Multiple calls added duplicate model locators, validators, controllers  
**Solution:** Flag-based check with `RuntimeError`  
**Status:** ✅ Fixed

### 2. PyTorch Validation Documentation (File 02)
**Problem:** Misleading docs implied validators were configured automatically  
**Solution:** Clarified PyTorch uses Client API pattern (`flare.is_evaluate()`)  
**Status:** ✅ Documented

### 3. Fragile Validator Detection (File 03)
**Problem:** String matching on "CSE" was error-prone  
**Solution:** New `_has_task_executor()` with 6 defensive checks  
**Status:** ✅ Fixed

### 4. TensorFlow Support Missing (Files 04-09)
**Problem:** TensorFlow listed as unsupported despite recipes existing  
**Solution:** Created `TFFileModelLocator`, `TFValidator`, fixed `TFModelPersistor`  
**Status:** ✅ Fully implemented

### 5. NumPy Framework Mismatch (Files 10-12)
**Problem:** RAW vs NUMPY framework type causing parameter exchange issues  
**Solution:** Hardcoded RAW in `NumpyCrossSiteEvalRecipe`  
**Status:** ✅ Fixed

---

## Technical Highlights

### Defense in Depth
- **3-tier validation** for persistor_id (empty check, component existence, type check)
- **6 defensive layers** in `_has_task_executor()` (hasattr, try-except, None checks)
- **Idempotency flag** prevents duplicate component additions

### Framework Support Matrix
| Framework   | Model Locator          | Validator Pattern                  | Status |
|-------------|------------------------|------------------------------------|--------|
| PyTorch     | PTFileModelLocator     | Client API (`flare.is_evaluate()`) | ✅ Yes |
| TensorFlow  | TFFileModelLocator     | Client API or TFValidator          | ✅ Yes |
| NumPy/RAW   | NPModelLocator         | NPValidator (auto-added)           | ✅ Yes |

---

## Start Here

**For bug context:** Read files 01-03  
**For TensorFlow implementation:** Read files 04-09  
**For NumPy framework fix:** Read files 10-12  
**For API simplification discussion:** Read files 14-16
