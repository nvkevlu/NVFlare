# XGBoost Examples Fixed: env.run() to recipe.execute() API Update

**Date:** February 1, 2026  
**Severity:** CRITICAL - Breaking API change  
**Status:** ✅ FIXED  

---

## The Issue

XGBoost examples on the 2.7 branch were broken due to using an outdated Recipe API pattern.

### Symptoms Reported by User
1. **"No env.run() function"** - AttributeError when trying to run examples
2. **"Data loader being None"** - Secondary issue (actually caused by execution never reaching that point)

### Root Cause
The XGBoost examples were using the old API pattern:
```python
env = SimEnv()
env.run(recipe, work_dir="...")
```

But the correct Recipe API pattern is:
```python
env = SimEnv(num_clients=N)
run = recipe.execute(env)
```

The `SimEnv` class has a `deploy()` method (not `run()`), and recipes should call `execute()` on the environment, not the other way around.

---

## Files Fixed

### Python Job Files (3 files)
1. ✅ `examples/advanced/xgboost/fedxgb/job.py`
2. ✅ `examples/advanced/xgboost/fedxgb/job_tree.py`
3. ✅ `examples/advanced/xgboost/fedxgb/job_vertical.py` (2 places: PSI and training)

### Recipe Docstrings (3 files)
4. ✅ `nvflare/app_opt/xgboost/recipes/histogram.py`
5. ✅ `nvflare/app_opt/xgboost/recipes/vertical.py`
6. ✅ `nvflare/app_opt/xgboost/recipes/bagging.py`

### Documentation (1 file)
7. ✅ `examples/advanced/xgboost/fedxgb/README.md` (3 examples updated)

**Total: 7 files fixed**

---

## Changes Made

### Pattern 1: Basic Job Execution
**Before:**
```python
# Run simulation
env = SimEnv()
env.run(recipe, work_dir=f"/tmp/nvflare/workspace/works/{job_name}")
```

**After:**
```python
# Run simulation
env = SimEnv(num_clients=args.site_num)
run = recipe.execute(env)
print()
print("Job Status:", run.get_status())
print("Result can be found in:", run.get_result())
print()
```

### Pattern 2: Vertical Training with PSI
**Before:**
```python
# Run training
env = SimEnv()
env.run(recipe, work_dir="/tmp/nvflare/workspace/works/xgboost_vertical")

print("\n" + "=" * 80)
print("Training Complete!")
print("=" * 80 + "\n")
```

**After:**
```python
# Run training
env = SimEnv(num_clients=args.site_num)
run = recipe.execute(env)

print("\n" + "=" * 80)
print("Training Complete!")
print(f"Job Status: {run.get_status()}")
print(f"Result can be found in: {run.get_result()}")
print("=" * 80 + "\n")
```

---

## Key API Differences

| Aspect | Old (Broken) | New (Correct) |
|--------|-------------|---------------|
| Method call | `env.run(recipe)` | `recipe.execute(env)` |
| SimEnv init | `SimEnv()` | `SimEnv(num_clients=N)` |
| Return value | None | `run` object with status/result |
| Work dir | `work_dir` parameter | Handled by `SimEnv.workspace_root` |

---

## Why This Happened

Looking at the cherry-pick history from `cursor_outputs/cherry_pick_analysis/20260120_xgboost_recipe_cherry_pick.md`, the XGBoost recipes were cherry-picked from main to 2.7 on January 20, 2026.

However, the examples were using an **intermediate/experimental API** that existed during development but was changed before the final Recipe API was stabilized.

### Timeline
1. **Jan 13, 2026**: XGBoost recipes created on main (per conversion plan)
2. **Jan 14, 2026**: Refactored to use `per_site_config` pattern
3. **Jan 20, 2026**: Cherry-picked to 2.7
4. **Between Jan 13-20**: Recipe API changed from `env.run()` to `recipe.execute()`
5. **Feb 1, 2026**: Issue discovered and fixed

---

## Comparison with Working Examples

### Working Example (hello-numpy/job.py)
```python
env = SimEnv(num_clients=n_clients)
run = recipe.execute(env)
print()
print("Result can be found in :", run.get_result())
print("Job Status is:", run.get_status())
print()
```

### Working Example (hello-pt/job.py)
```python
env = SimEnv(num_clients=n_clients)
run = recipe.execute(env)
print()
print("Job Status is:", run.get_status())
print("Result can be found in :", run.get_result())
print()
```

### Working Example (fedxgb_secure/job.py) - Already Correct!
```python
env = SimEnv(num_clients=args.site_num)
run = recipe.execute(env)
```

This confirms that `fedxgb_secure` examples were already using the correct pattern, but the `fedxgb` examples were not updated.

---

## Verification

### Before Fix
```bash
$ rg "env\.run\(" examples/advanced/xgboost/ nvflare/app_opt/xgboost/
# Found 7 instances
```

### After Fix
```bash
$ rg "env\.run\(" examples/advanced/xgboost/ nvflare/app_opt/xgboost/
# No matches found ✅
```

### Git Diff Summary
```
 examples/advanced/xgboost/fedxgb/README.md       | 12 ++++++------
 examples/advanced/xgboost/fedxgb/job.py          |  8 ++++++--
 examples/advanced/xgboost/fedxgb/job_tree.py     |  8 ++++++--
 examples/advanced/xgboost/fedxgb/job_vertical.py |  8 +++++---
 nvflare/app_opt/xgboost/recipes/bagging.py       |  4 ++--
 nvflare/app_opt/xgboost/recipes/histogram.py     |  4 ++--
 nvflare/app_opt/xgboost/recipes/vertical.py      |  4 ++--
 7 files changed, 29 insertions(+), 19 deletions(-)
```

---

## Testing Recommendations

Before committing, test the following:

### 1. Horizontal Histogram XGBoost
```bash
cd examples/advanced/xgboost/fedxgb
python job.py --site_num 2 --round_num 5
```

### 2. Tree-Based (Bagging)
```bash
cd examples/advanced/xgboost/fedxgb
python job_tree.py --site_num 3 --training_algo bagging --round_num 1
```

### 3. Vertical XGBoost (PSI + Training)
```bash
cd examples/advanced/xgboost/fedxgb
python job_vertical.py --run_psi --run_training --site_num 2 --round_num 5
```

### 4. Secure Horizontal (Already working, but verify)
```bash
cd examples/advanced/xgboost/fedxgb_secure
python job.py --site_num 2 --round_num 3
```

---

## Lessons Learned

### 1. API Consistency is Critical
When cherry-picking or porting examples, **always verify the API pattern** matches the target branch's implementation.

### 2. Check Working Examples First
Before debugging complex issues, **compare with known-working examples** in the same codebase. This would have revealed the pattern difference immediately.

### 3. Update Documentation with Code
When changing APIs, **update docstrings and README examples** at the same time. We found outdated patterns in:
- Recipe class docstrings
- README code examples

### 4. Cherry-Pick Validation
When cherry-picking recipes, validate that:
- ✅ Recipe classes work
- ✅ Example job files work
- ✅ Documentation is updated
- ❌ **API patterns are consistent** ← This was missed

---

## Impact

### User Impact
- **HIGH**: Examples were completely broken and wouldn't run
- Users would get AttributeError: 'SimEnv' object has no attribute 'run'
- This blocks all XGBoost federated learning workflows

### Fix Impact
- **LOW**: Simple API update, no logic changes
- All functionality remains the same
- Better user experience with status/result printing

---

## Related Documents

- `cursor_outputs/cherry_pick_analysis/20260120_xgboost_recipe_cherry_pick.md` - Original cherry-pick
- `cursor_outputs/20260113/02_xgboost_conversion_plan_three_phases_recipes_architecture.md` - Conversion plan
- `cursor_outputs/20260114/01_xgboost_fixed_per_site_config_inconsistency_with_fedavg_pattern.md` - Earlier fix
- `cursor_outputs/WORKFLOW_RULES.md` - Workflow guidelines followed

---

**Fixed by:** AI Assistant  
**Reported by:** User  
**Date Completed:** February 1, 2026  
**Additional Enhancement:** February 2, 2026 - data_loader flexibility improvement

**Status:** ✅ Ready for commit  
**Test Status:** ✅ FULLY VALIDATED  
- API validation: See `02_xgboost_test_validation_results.md`  
- End-to-end test: See `03_xgboost_end_to_end_test_results.md` ✅ **JOB COMPLETED SUCCESSFULLY**
- Data loader flexibility: See `04_xgboost_data_loader_flexibility_improvement.md` ✅ **ENHANCEMENT COMPLETE**
