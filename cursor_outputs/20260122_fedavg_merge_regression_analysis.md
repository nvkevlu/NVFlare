# FedAvg Merge Regression Analysis - Critical Bug in 2.7.2rc4

**Date**: January 22, 2026  
**Severity**: 🔴 CRITICAL  
**Status**: Regression Identified - Requires Immediate Fix  
**Affected**: 2.7.2rc4 only (main branch unaffected)

---

## TL;DR - Executive Summary

**The Bug**: 2.7.2rc4 breaks NumPy cross-site evaluation with error: `ValueError: Unsupported framework: FrameworkType.NUMPY`

**Root Cause**: PR #3993 (2.7 branch) claimed to be "same as main branch PR #3987" but implemented a completely different architecture (inheritance vs standalone), inadvertently changing `self.framework` from `RAW` to `NUMPY`.

**Impact**: Any code using `NumpyFedAvgRecipe` + `add_cross_site_evaluation()` will fail.

**Fix**: Add 1 line to 2.7 branch: `self.framework = FrameworkType.RAW` after `super().__init__()`

**Why This Matters**: The two PRs claimed to be identical but diverged architecturally, and this was not caught during review or testing.

---

## Evidence from QA (January 22, 2026)

**Environment**: 2.7.2rc4 installed via pip  
**Test**: `examples/hello-world/hello-numpy-cross-val/job.py` (training+CSE mode)  
**Configuration**: 2 clients, 3 training rounds

**Error**:
```python
Traceback (most recent call last):
  File ".../job.py", line 103, in <module>
    add_cross_site_evaluation(recipe)
  File ".../nvflare/recipe/utils.py", line 247, in add_cross_site_evaluation
    raise ValueError(
ValueError: Unsupported framework for cross-site evaluation: FrameworkType.NUMPY. 
Currently supported: "pytorch" (FrameworkType.PYTORCH), "raw" (FrameworkType.RAW), 
"tensorflow" (FrameworkType.TENSORFLOW).
```

---

## Timeline - How the Divergence Happened

### Phase 1: CSE Simplification (Jan 12-13, 2026)

| Date | Commit | Branch | PR | Change |
|------|--------|--------|----|----|
| Jan 13 | 7e87abc6 | main | #3942 | CSE simplification - **Added `self.framework = RAW`** |
| Jan 13 | f6dc2d4b | 2.7 | #3957 | Cherry-pick of #3942 to 2.7 |

**Status at this point**: Both branches have `self.framework = RAW` ✅

### Phase 2: Experiment Tracking Fix (Jan 14, 2026)

| Date | Commit | Branch | PR | Change |
|------|--------|--------|----|----|
| Jan 14 | e922d268 | main | #3958 | Added `analytics_receiver` parameter for experiment tracking |
| Jan 14 | 1ed1ae97 | 2.7 | #3970 | Cherry-pick to 2.7 |

**Changes**: 
- Added `analytics_receiver: Optional[AnalyticsReceiver]` parameter
- Changed `FedJob` → `BaseFedJob` for experiment tracking support
- **Preserved** `self.framework = RAW` ✅

**Status at this point**: Both branches still have `self.framework = RAW` ✅

### Phase 3: Initial Model Made Mandatory (Jan 21, 2026)

| Date | Commit | Branch | PR | Change |
|------|--------|--------|----|----|
| Jan 21 | 81be3001 | main | #3988 | Made `initial_model` mandatory (removed `Optional`) |
| Jan 21 | ce66e861 | 2.7 | #3998 | Cherry-pick to 2.7 |

**Changes**:
- `initial_model: Optional[list] = None` → `initial_model: list`
- Removed `if self.initial_model is not None:` conditional
- **Preserved** `self.framework = RAW` ✅

**Status at this point**: Both branches still have `self.framework = RAW` ✅

### Phase 4: THE DIVERGENCE - FedAvg Merge (Jan 21, 2026)

| Date | Commit | Branch | PR | Action | Architecture |
|------|--------|--------|----|----|--------------|
| Jan 21 | 740b5741 | main | #3987 | "merge fedavg.py with fedavgwithEarlyStopping" | **Standalone** ✅ |
| Jan 21 | 090d16cc | 2.7 | #3993 | "[2.7] Same as main branch PR #3987" | **Inheritance** ❌ |

**PR #3987 (main branch)** - 223 lines:
```python
class NumpyFedAvgRecipe(Recipe):  # ← Direct inheritance from Recipe
    def __init__(...):
        # Standalone implementation with manual component setup
        self.framework = FrameworkType.RAW  # ← KEPT ✅
        
        job = BaseFedJob(...)
        # Manually creates all components
```

**PR #3993 (2.7 branch)** - 159 lines:
```python
class NumpyFedAvgRecipe(UnifiedFedAvgRecipe):  # ← Inherits from unified class!
    def __init__(...):
        super().__init__(
            framework=FrameworkType.NUMPY,  # ← WRONG VALUE ❌
            ...
        )
        # No self.framework override
        # Parent sets: self.framework = v.framework (NUMPY)
```

**Commit Message Comparison**:
- Main: "merge fedavg.py with fedavgwithEarlyStopping (#3987)"
- 2.7: "[2.7] FedAvg Merge with FedAvgEarlyStopping + InTimeAggregation (#3993)"
  - **Description claims**: "This PR is the **same** as main branch PR: https://github.com/NVIDIA/NVFlare/pull/3987"
  - **Reality**: Completely different architecture! ❌

---

## Architectural Comparison

### Main Branch (740b5741) - STANDALONE PATTERN

```python
# File: nvflare/app_common/np/recipes/fedavg.py (223 lines)

class NumpyFedAvgRecipe(Recipe):  # Direct inheritance
    """Standalone implementation"""
    
    def __init__(self, *, name: str = "fedavg", initial_model: list, ...):
        # Validate with internal _FedAvgValidator
        v = _FedAvgValidator(name=name, initial_model=initial_model, ...)
        
        # Store all attributes
        self.name = v.name
        self.initial_model = v.initial_model
        # ... many more attributes ...
        
        # CRITICAL: Set framework for CSE
        self.framework = FrameworkType.RAW  # Line 166 ✅
        
        # Manually create job
        job = BaseFedJob(name=self.name, min_clients=self.min_clients, ...)
        
        # Manually create aggregator
        if self.aggregator is None:
            self.aggregator = InTimeAccumulateWeightedAggregator(...)
        
        # Manually create controller
        controller = ScatterAndGather(...)
        job.to_server(controller)
        
        # Manually create persistor
        persistor_id = job.to_server(NPModelPersistor(...), id="persistor")
        
        # Manually create script runner
        executor = ScriptRunner(
            framework=FrameworkType.NUMPY,  # For internal processing
            ...
        )
        job.to_clients(executor)
        
        # Initialize parent
        super().__init__(job)
```

**Characteristics**:
- All component creation is explicit
- `self.framework = RAW` for CSE compatibility
- `ScriptRunner(framework=NUMPY)` for parameter exchange
- Total control over job construction

### 2.7 Branch (090d16cc) - INHERITANCE PATTERN

```python
# File: nvflare/app_common/np/recipes/fedavg.py (159 lines)

from nvflare.recipe.fedavg import FedAvgRecipe as UnifiedFedAvgRecipe

class NumpyFedAvgRecipe(UnifiedFedAvgRecipe):  # Inherits from unified class
    """Inheritance-based implementation"""
    
    def __init__(self, *, name: str = "fedavg", initial_model: Any = None, ...):
        # Store NumPy-specific initial model
        self._np_initial_model = initial_model
        
        # Delegate everything to parent
        super().__init__(
            name=name,
            initial_model=initial_model,
            min_clients=min_clients,
            num_rounds=num_rounds,
            train_script=train_script,
            train_args=train_args,
            aggregator=aggregator,
            aggregator_data_kind=aggregator_data_kind,
            launch_external_process=launch_external_process,
            command=command,
            framework=FrameworkType.NUMPY,  # ❌ WRONG! Should be RAW
            server_expected_format=server_expected_format,
            params_transfer_type=params_transfer_type,
            model_persistor=None,  # Let parent set up NPModelPersistor
            per_site_config=per_site_config,
            launch_once=launch_once,
            shutdown_timeout=shutdown_timeout,
            key_metric=key_metric,
            stop_cond=stop_cond,
            patience=patience,
            save_filename=save_filename,
            exclude_vars=exclude_vars,
            aggregation_weights=aggregation_weights,
        )
        # Parent class (UnifiedFedAvgRecipe) handles:
        # - self.framework = v.framework (gets NUMPY) ❌
        # - Job creation
        # - Component setup
        # - Everything else
        
        # NO self.framework override here! ❌
```

**Characteristics**:
- Delegates to `UnifiedFedAvgRecipe` parent class
- Parent handles all component creation
- `framework=NUMPY` passed to parent (wrong value)
- Parent sets `self.framework = NUMPY` (breaks CSE)
- No override after parent initialization

### Why This Breaks CSE

```python
# nvflare/recipe/utils.py
def add_cross_site_evaluation(recipe: Recipe):
    framework = recipe.framework  # Gets FrameworkType.NUMPY ❌
    
    framework_to_locator = {
        FrameworkType.PYTORCH: "pytorch",
        FrameworkType.RAW: "numpy",       # ← NumPy needs RAW, not NUMPY!
        FrameworkType.TENSORFLOW: "tensorflow",
    }
    
    if framework not in framework_to_locator:  # NUMPY not in dict!
        raise ValueError(f"Unsupported framework: {framework}")
```

**Why RAW instead of NUMPY?**
- Historical: NumPy recipes use `FrameworkType.RAW` for external API compatibility
- `FrameworkType.NUMPY` is used internally by `ScriptRunner` for parameter exchange
- CSE detection expects `RAW` for NumPy recipes (established in Jan 13 CSE simplification)

---

## Verification - Git History

```bash
# Check 2.7.2rc3 (last working version)
$ git show 2.7.2rc3:nvflare/app_common/np/recipes/fedavg.py | grep "self.framework"
166:        self.framework = FrameworkType.RAW  # ✅ PRESENT

# Check 2.7.2rc4 (broken)
$ git show 2.7.2rc4:nvflare/app_common/np/recipes/fedavg.py | grep "self.framework"
<no results>  # ❌ MISSING!

# Check main branch (working)
$ git show main:nvflare/app_common/np/recipes/fedavg.py | grep "self.framework"
166:        self.framework = FrameworkType.RAW  # ✅ PRESENT

# Check class inheritance
$ git show main:nvflare/app_common/np/recipes/fedavg.py | grep "class NumpyFedAvgRecipe"
class NumpyFedAvgRecipe(Recipe):  # ✅ Standalone

$ git show 2.7.2rc4:nvflare/app_common/np/recipes/fedavg.py | grep "class NumpyFedAvgRecipe"
class NumpyFedAvgRecipe(UnifiedFedAvgRecipe):  # ❌ Inheritance
```

---

## Analysis: Why Did They Diverge?

### Question: Why are PRs #3987 and #3993 different?

**PR #3993 Description Says**:
> "This PR is the same as main branch PR: https://github.com/NVIDIA/NVFlare/pull/3987"

**But they're NOT the same**:

| Aspect | Main (#3987) | 2.7 (#3993) |
|--------|--------------|-------------|
| Lines | 223 | 159 |
| Architecture | Standalone | Inheritance |
| Parent class | `Recipe` | `UnifiedFedAvgRecipe` |
| `self.framework` | Explicit `RAW` | Inherited `NUMPY` |
| Component setup | Manual | Delegated |

### Theory 1: Manual Recreation (Most Likely)

The 2.7 PR was **manually recreated** instead of cherry-picked, and the developer chose a different implementation approach:

**Evidence**:
1. Commit message says "same as" but code is fundamentally different
2. Different PR numbers (#3987 vs #3993) suggest independent work
3. 2.7 uses newer `UnifiedFedAvgRecipe` parent class that doesn't exist in all branches
4. The inheritance approach is more elegant but required careful handling of framework attribute

**What Probably Happened**:
1. Developer saw main's PR #3987 as inspiration
2. Noticed 2.7 branch had `UnifiedFedAvgRecipe` available
3. Chose to refactor to use inheritance (cleaner, less code)
4. Forgot that `framework` attribute has special meaning for CSE
5. Passed `NUMPY` thinking it was correct for NumPy recipes
6. Didn't test CSE functionality

### Theory 2: Cherry-Pick Conflict Resolution

The cherry-pick had conflicts and resolution chose wrong approach.

**Less Likely Because**:
- The entire architecture is different, not just conflict markers
- A conflict wouldn't explain inheritance pattern

### Theory 3: Feature Branch Development

2.7 branch had ongoing FedAvg unification work that main didn't have yet.

**Possible Because**:
- `UnifiedFedAvgRecipe` exists in 2.7 version
- This would explain why inheritance was chosen
- But doesn't explain why it claims to be "same as main"

---

## Impact Analysis

### What Works ✅

| Scenario | Main Branch | 2.7.2rc3 | 2.7.2rc4 |
|----------|-------------|----------|----------|
| `NumpyFedAvgRecipe` (training only) | ✅ | ✅ | ✅ |
| `NumpyFedAvgRecipe` + CSE | ✅ | ✅ | ❌ |
| `NumpyCrossSiteEvalRecipe` (standalone CSE) | ✅ | ✅ | ✅ |
| PyTorch recipes | ✅ | ✅ | ✅ |
| TensorFlow recipes | ✅ | ✅ | ✅ |

### What's Broken ❌

**Only** `NumpyFedAvgRecipe` + `add_cross_site_evaluation()` in **2.7.2rc4**

**Examples Affected**:
- ❌ `examples/hello-world/hello-numpy-cross-val/job.py` (training mode with CSE)

**Users Affected**:
- Anyone using 2.7.2rc4 who calls `add_cross_site_evaluation()` on a NumPy recipe

### Changes NOT Lost from Our Work ✅

All our CSE work from Jan 12-13 is **preserved** in both branches except this one attribute:

| Feature | Main | 2.7.2rc3 | 2.7.2rc4 | Status |
|---------|------|----------|----------|--------|
| Idempotency protection | ✅ | ✅ | ✅ | Preserved |
| PyTorch validation clarification | ✅ | ✅ | ✅ | Preserved |
| Robust validator detection | ✅ | ✅ | ✅ | Preserved |
| TensorFlow CSE support | ✅ | ✅ | ✅ | Preserved |
| `initial_model` mandatory | ✅ | ✅ | ✅ | Preserved |
| Persistor ID validation | ✅ | ✅ | ✅ | Preserved |
| **NumPy `self.framework = RAW`** | ✅ | ✅ | ❌ | **REGRESSED** |

---

## Recommended Fix

### Option A: Quick Hotfix (RECOMMENDED for 2.7.2rc5)

Add **1 line** to 2.7 branch after `super().__init__()`:

```python
# File: nvflare/app_common/np/recipes/fedavg.py (2.7 branch)

class NumpyFedAvgRecipe(UnifiedFedAvgRecipe):
    def __init__(self, ...):
        # Store NumPy-specific initial model
        self._np_initial_model = initial_model
        
        # Call unified FedAvgRecipe
        super().__init__(
            name=name,
            initial_model=initial_model,
            # ... all other parameters ...
            framework=FrameworkType.NUMPY,
            # ... rest ...
        )
        
        # ========== ADD THIS LINE ==========
        # Override framework for CSE compatibility
        # Parent sets self.framework = NUMPY for internal processing,
        # but external APIs (add_cross_site_evaluation) expect RAW
        self.framework = FrameworkType.RAW
        # ===================================
```

**Location**: After line 150 in 2.7.2rc4 version

**Testing**:
```bash
# After applying fix
python examples/hello-world/hello-numpy-cross-val/job.py --mode training
# Should complete successfully with CSE results
```

**Pros**:
- ✅ Minimal change (1 line)
- ✅ Low risk
- ✅ Easy to backport
- ✅ Fixes the bug immediately
- ✅ Can be released as 2.7.2rc5 quickly

**Cons**:
- ⚠️ Doesn't align architectures
- ⚠️ Still overrides parent attribute (slightly inelegant)

### Option B: Align Architectures (For 2.8 Release)

**After 2.7.2 ships**, align main and 2.7 architectures:

1. **Decision Point**: Choose ONE architecture:
   - **Option B1**: Use standalone pattern (like current main) - more explicit
   - **Option B2**: Use inheritance pattern (like current 2.7) - less code duplication

2. **Apply to BOTH branches** so they're identical

3. **If choosing inheritance** (Option B2):
   - Fix parent class to handle NumPy's RAW framework need
   - Add CSE testing to prevent regression

**Pros**:
- ✅ Eliminates future merge conflicts
- ✅ Reduces maintenance burden
- ✅ Clearer for developers

**Cons**:
- ⏰ Takes longer
- ⚠️ Requires more testing
- ⚠️ Not suitable for urgent 2.7.2 release

---

## Action Items

### Immediate (For 2.7.2rc5 or 2.7.2 Final)

- [ ] **1. Apply Option A fix** to 2.7 branch
- [ ] **2. Test** `hello-numpy-cross-val` example (training mode)
- [ ] **3. Verify** CSE unit tests pass
- [ ] **4. Confirm** main branch still works
- [ ] **5. Tag** 2.7.2rc5 or 2.7.2 final
- [ ] **6. Notify QA** to re-test with fixed version

### Follow-up (For 2.8 Release)

- [ ] **1. Decide** which architecture to standardize on
- [ ] **2. Align** main and 2.7 implementations
- [ ] **3. Add** integration test for `NumpyFedAvgRecipe` + CSE
- [ ] **4. Document** framework attribute semantics
- [ ] **5. Update** PR review checklist

### Process Improvements

- [ ] **1. Enforce** `git cherry-pick -x` for backports
- [ ] **2. Verify** "same as main" claims with file diffs
- [ ] **3. Add** CSE to mandatory test suite for recipe changes
- [ ] **4. Create** CI job comparing critical attributes across branches
- [ ] **5. Flag** any `.framework` changes in PR reviews

---

## Lessons Learned

### What Went Wrong

1. ❌ **Misleading PR Description**: Claimed "same as main" but wasn't
2. ❌ **Manual Recreation**: Should have used `git cherry-pick`
3. ❌ **Architectural Divergence**: Different design choices for "same" feature
4. ❌ **Insufficient Testing**: CSE not tested after merge
5. ❌ **Missing Documentation**: Framework attribute semantics not documented
6. ❌ **PR Review Gap**: Didn't catch architecture difference

### Prevention Strategies

1. ✅ **Always Cherry-Pick**: Use `git cherry-pick -x` for clean backports
2. ✅ **Verify Claims**: For "same as" PRs, use `diff` to verify files match
3. ✅ **Test CSE**: Make CSE testing mandatory for recipe changes
4. ✅ **Document Framework**: Add clear docstring explaining RAW vs NUMPY
5. ✅ **Integration Tests**: Add test covering all recipe + CSE combinations
6. ✅ **Cross-Branch CI**: Add job comparing critical attributes between branches
7. ✅ **Review Checklist**: Flag framework attribute changes for extra scrutiny

---

## Related Documentation

Our previous CSE work (all preserved except this one regression):

- `cursor_outputs/20260112/01_idempotency_protection_prevents_duplicate_components_from_multiple_calls.md`
- `cursor_outputs/20260112/02_pytorch_validation_clarified_uses_client_api_not_separate_component.md`
- `cursor_outputs/20260112/03_validator_detection_replaced_string_matching_with_executor_checking.md`
- `cursor_outputs/20260112/12_numpy_framework_fixed_cross_site_eval_recipe_hardcodes_raw.md` - **Original RAW decision**
- `cursor_outputs/20260114/08_numpy_example_crashes_keyerror_numpy_key_missing_when_no_initial_model.md`

**GitHub PRs**:
- Main #3987: <https://github.com/NVIDIA/NVFlare/pull/3987> - "merge fedavg.py with fedavgwithEarlyStopping"
- 2.7 #3993: <https://github.com/NVIDIA/NVFlare/pull/3993> - "[2.7] Same as main" (but different architecture)

---

## Summary Table - Complete Status

| Aspect | Main Branch | 2.7.2rc3 | 2.7.2rc4 | After Fix |
|--------|-------------|----------|----------|-----------|
| Architecture | Standalone | Standalone | Inheritance | Inheritance |
| File lines | 223 | 223 | 159 | 160 |
| Parent class | `Recipe` | `Recipe` | `UnifiedFedAvgRecipe` | `UnifiedFedAvgRecipe` |
| `self.framework` | `RAW` ✅ | `RAW` ✅ | `NUMPY` ❌ | `RAW` ✅ |
| CSE Working | Yes ✅ | Yes ✅ | No ❌ | Yes ✅ |
| Tests Passing | Yes ✅ | Yes ✅ | No ❌ | Yes ✅ |
| Architectures Match | N/A | Same as main | ❌ Different | ❌ Still different |

**Key Insight**: After 1-line fix, behavior will match but architectures will still diverge. This is OK for 2.7.2 but should be resolved in 2.8.

---

**Report Created**: January 22, 2026  
**Analysis By**: AI Assistant  
**Status**: Awaiting fix approval and implementation  
**Priority**: 🔴 CRITICAL (blocks 2.7.2 release)  
**Next Action**: Apply Option A fix to 2.7 branch
