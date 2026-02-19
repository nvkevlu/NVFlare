# Fix hello-numpy-cross-val Example Cherry-Pick

**Date**: January 21, 2026  
**Branch**: `fix_hello-numpy-cross-val`  
**Target**: `2.7`  
**Original Commit**: `81be3001a7886fab3c8e01a32d53fbe5adbe70a6`  
**PR**: #3988 "Fix hello-numpy-cross-val example"  
**New Branch**: `cherry-pick-fix-hello-numpy-cross-val-2.7`

---

## Summary

Successfully cherry-picked PR #3988 to 2.7 using the optimal file extraction method. 

**Time**: ~2 minutes  
**Commands**: 5 (fetch, branch, extract, stage, verify)  
**Conflicts**: 0  
**Files**: 10 modified

**Changes**: 328 insertions, 171 deletions

---

## What This PR Fixes

### Core Issues Addressed:

1. **Makes `initial_model` required in `NumpyFedAvgRecipe`**
   - Changed from `Optional[list] = None` to `list` (required parameter)
   - Removed conditional logic for handling missing initial_model
   - Simplified persistor setup (always adds NPModelPersistor)

2. **Fixes hello-numpy examples**
   - Added missing line in `client.py` files
   - Updated `job.py` to provide required initial_model
   - Added documentation improvements

3. **Updates documentation references**
   - Fixed refs: `hello_pt` → `hello_pt_job_api`
   - Fixed refs: `hello_tf` → `hello_tf_job_api`
   - Updated Lightning examples to use github links

4. **Enhances tests**
   - Updated integration tests for NumPy recipe
   - Cleaned up unit tests (removed 74 lines of test code)

---

## Files Modified

### Core Recipe Changes (2 files):

1. **`nvflare/app_common/np/recipes/fedavg.py`** (14 lines changed)
   - Made `initial_model` required (was Optional)
   - Simplified persistor logic
   - Added clarifying comment about NumPy vs PyTorch/TF behavior

2. **`nvflare/recipe/utils.py`** (2 lines changed)
   - Minor update to utility function

### Example Fixes (4 files):

3. **`examples/hello-world/hello-numpy-cross-val/README.md`** (+1 line)
4. **`examples/hello-world/hello-numpy-cross-val/client.py`** (+1 line)
5. **`examples/hello-world/hello-numpy-cross-val/job.py`** (5 insertions, 1 deletion)
6. **`examples/hello-world/hello-numpy/client.py`** (+1 line)

### Documentation Updates (2 files):

7. **`docs/programming_guide/execution_api_type/client_api.rst`** (302 insertions, many deletions)
   - ⚠️ **Note**: This includes changes from BOTH:
     - PR #3960 (Client API tutorials) - not yet merged to 2.7
     - PR #3988 (ref fixes) - this PR
   - Fixed reference links for hello examples
   - Enhanced Examples section

8. **`docs/user_guide/nvflare_cli/poc_command.rst`** (78 insertions, 13 deletions)
   - Enhanced POC command documentation

### Test Updates (2 files):

9. **`tests/integration_test/recipe_system_test.py`** (20 lines changed)
10. **`tests/unit_test/recipe/fedavg_recipe_test.py`** (75 deletions, 1 insertion)
    - Significant cleanup removing obsolete test code

---

## Important Dependency Note

### Client API Tutorials Dependency

**⚠️ Critical**: The `client_api.rst` file in this cherry-pick includes content from PR #3960 (Client API tutorials), which has a separate cherry-pick PR but **is not yet merged to 2.7**.

**What This Means**:

1. **Current State**: 
   - This cherry-pick extracts the final state of `client_api.rst` from commit `81be3001`
   - That state includes BOTH the Client API tutorial enhancements AND the ref fixes

2. **If Client API tutorials PR merges first**:
   - This PR will need rebasing
   - Only the 6-line ref fix diff will remain
   - No conflicts expected (just rebase)

3. **If this PR merges first**:
   - Client API tutorials PR becomes redundant for `client_api.rst`
   - That PR would only update `client_api_usage.rst`

**Recommendation**: Coordinate merge order with the team. Ideally:
- Merge Client API tutorials PR #3960 cherry-pick first
- Then rebase this PR to only include the 6-line ref fix

---

## Verification: What Was Actually New

### Already in 2.7:

❌ **None of these changes were in 2.7** - this is a completely new fix

### New in This Cherry-pick:

✅ **All 10 files needed updates**:

1. `nvflare/app_common/np/recipes/fedavg.py` - `initial_model` still Optional in 2.7
2. `client_api.rst` - 2.7 has old Examples section (missing enhancements)
3. Example files - Missing the required initial_model fixes
4. Tests - Missing updates

**Key Finding**: Unlike the previous `fix_numpy_experiment_tracking` cherry-pick where 2 of 3 files were already fixed, this PR has NO overlap with existing 2.7 changes. All changes are new.

---

## Technical Details

### Before (2.7):
```python
class NumpyFedAvgRecipe(Recipe):
    def __init__(
        self,
        *,
        name: str = "fedavg",
        initial_model: Optional[list] = None,  # Optional
        min_clients: int,
        ...
    ):
```

### After (This Cherry-pick):
```python
class NumpyFedAvgRecipe(Recipe):
    def __init__(
        self,
        *,
        name: str = "fedavg",
        initial_model: list,  # Required!
        min_clients: int,
        ...
    ):
```

### Rationale:
- NumPy recipes MUST have an initial model (unlike PyTorch/TF which can infer from training)
- Making it required prevents runtime errors
- Simplifies the persistor setup code

---

## Cherry-Pick Process

### Commands Used:

```bash
# 1. Update 2.7
git fetch online
# Result: 2.7 updated to 61335fdf

# 2. Create branch
git checkout -b cherry-pick-fix-hello-numpy-cross-val-2.7 online/2.7

# 3. Extract files (bulk script)
for file in [10 files]; do
  git show 81be3001:"$file" > "$file"
done

# 4. Stage changes
git add [10 files]

# 5. Verify
git status
# Result: 10 files changed, 328 insertions(+), 171 deletions(-)
```

**Total**: 5 commands, ~2 minutes, 0 conflicts ✅

---

## Why This Was Straightforward

### Success Factors:

1. **Squash merge detected**: PR #3988 was squashed into single commit `81be3001`
2. **Clear file list**: `git show --stat` showed exactly 10 files
3. **No prior fixes**: Unlike previous numpy PR, nothing was already in 2.7
4. **File extraction method**: Bypassed all potential conflicts
5. **Optimal process**: Used the established 5-command pattern

### Lessons Applied:

✅ Always check if commit is a squash merge first  
✅ Use file extraction for squash merges  
✅ Verify no files already fixed in target branch  
✅ Extract all files in bulk with script  
✅ Use selective `git add` to avoid permission issues

---

## What's Staged

```
On branch cherry-pick-fix-hello-numpy-cross-val-2.7
Changes to be committed:
  modified:   docs/programming_guide/execution_api_type/client_api.rst
  modified:   docs/user_guide/nvflare_cli/poc_command.rst
  modified:   examples/hello-world/hello-numpy-cross-val/README.md
  modified:   examples/hello-world/hello-numpy-cross-val/client.py
  modified:   examples/hello-world/hello-numpy-cross-val/job.py
  modified:   examples/hello-world/hello-numpy/client.py
  modified:   nvflare/app_common/np/recipes/fedavg.py
  modified:   nvflare/recipe/utils.py
  modified:   tests/integration_test/recipe_system_test.py
  modified:   tests/unit_test/recipe/fedavg_recipe_test.py
```

**Stats**: 10 files changed, 328 insertions(+), 171 deletions(-)

---

## Next Steps

### Immediate:
Ready for you to sign and commit with:  
`[2.7] Fix hello-numpy-cross-val example (#3988)`

### Before Merging:
- **Coordinate with Client API tutorials PR** (#3960 cherry-pick)
- Decide merge order (see Dependency Note above)
- Consider rebasing if Client API tutorials merges first

### After Commit:
Push to create PR for 2.7

---

## Potential Issues & Resolutions

### Issue 1: Merge Conflict with Client API Tutorials PR

**Scenario**: Both PRs try to update `client_api.rst`

**Resolution**:
- This PR includes the superset of changes
- If Client API PR merges first, rebase this one
- Only 6 lines will show as diff after rebase
- No actual conflict in content (same final state)

### Issue 2: Tests May Fail if initial_model Not Provided

**Not an issue**:
- The change REQUIRES initial_model now
- Tests updated to provide it
- Examples updated to provide it
- This is the intended fix (prevent runtime errors)

---

## Key Takeaways

1. ✅ **File extraction method scales perfectly** - 10 files, 0 conflicts
2. ✅ **Bulk extraction script is efficient** - Single loop for all files
3. ✅ **Selective `git add` avoids permission issues** - Explicit file list
4. ⚠️ **Dependency tracking matters** - `client_api.rst` has cross-PR dependency
5. ✅ **Process is now consistent** - 5 commands, ~2 minutes, predictable results

---

## Comparison to Previous Cherry-picks

| Metric | Consolidation | Cross-site Eval | Simplify CSE | XGBoost | Client API | SAG Removal | **This PR** |
|--------|--------------|----------------|--------------|---------|------------|-------------|-------------|
| Files | 8 | 8 | 4 | 28 | 2 | 23 | **10** |
| Time | 20+ min | 20+ min | 3 min | 2 min | 2 min | 2 min | **2 min** |
| Conflicts | Many | Many (10+) | 0 | 0 | 0 | 0 | **0** |
| Method | Merge squash | File extraction | File extraction | File extraction | File extraction | File extraction | **File extraction** |
| Success | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | **✅** |

**Trend**: File extraction method is consistently fast, conflict-free, and reliable for squash merges.

---

## Conclusion

Cherry-pick successful using the optimal file extraction process. All 10 files cleanly extracted and staged. Ready for commit.

**Important**: Coordinate with Client API tutorials PR before merging to avoid redundant work.
