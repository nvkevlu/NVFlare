# Cherry-pick: Fix Numpy Experiment Tracking to 2.7

**Date**: January 14, 2026  
**Source Branch**: `fix_numpy_experiment_tracking`  
**Source Commit**: `7242ba76` ("fix NumpyFedAvgRecipe and other minor fixes")  
**Target Branch**: `online/2.7`  
**New Branch**: `cherry-pick-fix-numpy-experiment-tracking-2.7`  
**Status**: ✅ **SUCCESS** (1 file staged, ready for commit)

---

## What Was Cherry-picked

Fixes for NumpyFedAvgRecipe to properly support experiment tracking:
- **Added `analytics_receiver` parameter** to enable experiment tracking (TensorBoard, MLflow, etc.)
- **Switched from `FedJob` to `BaseFedJob`** to provide `ConvertToFedEvent` for experiment tracking
- **Removed obsolete parameters**: `launch_once`, `shutdown_timeout` (moved to ScriptRunner)
- **Set framework to `FrameworkType.RAW`** for external API compatibility (CSE auto-detection)
- **Updated imports** to include `AnalyticsReceiver` and `BaseFedJob`

**Plus two minor fixes** (already in 2.7):
- ✅ Fixed typo in `nvflare/app_opt/pt/job_config/model.py`: "how to persistor" → "how to persist"
- ✅ Fixed import in `nvflare/app_opt/tf/model_persistor.py`: moved `ModelDescriptor` to correct module

---

## Lessons Applied from Previous Cherry-picks

### ✅ What I Did Right:
1. **Checked commit structure first**: `git show 7242ba76 --stat` → single commit with 3 files
2. **Identified merge type immediately**: Single commit (not squash merge of PR)
3. **Used file extraction method**: Clean, no conflicts
4. **Verified what's already in 2.7**: Checked if fixes already existed

### Key Discovery:
**2 of 3 files were already fixed in 2.7!**
- ✅ `nvflare/app_opt/pt/job_config/model.py` - typo already fixed
- ✅ `nvflare/app_opt/tf/model_persistor.py` - import already fixed
- ⏳ `nvflare/app_common/np/recipes/fedavg.py` - needed extraction

This is why the user warned: *"some additional fixes on the current branch that have already been fixed in 2.7"*

---

## Execution Steps

### 1. Analyzed the Commit
```bash
git show --stat 7242ba76
# Result: Single commit, 3 files, 25 insertions, 6 deletions
```

### 2. Checked What's Already in 2.7
```bash
# Check model.py typo
grep "how to persistor" nvflare/app_opt/pt/job_config/model.py
# Exit 1 = not found = already fixed ✅

# Check model_persistor.py import
grep "ModelDescriptor" nvflare/app_opt/tf/model_persistor.py
# Shows: from nvflare.app_common.model_desc import ModelDescriptor
# Already fixed ✅
```

### 3. Created Branch from 2.7
```bash
git fetch online
git checkout online/2.7
git checkout -b cherry-pick-fix-numpy-experiment-tracking-2.7
```

### 4. Extracted Only the Needed File
```bash
git show 7242ba76:nvflare/app_common/np/recipes/fedavg.py > nvflare/app_common/np/recipes/fedavg.py
git add nvflare/app_common/np/recipes/fedavg.py
```

### 5. Verified Changes
```bash
git diff --cached --stat
# nvflare/app_common/np/recipes/fedavg.py | 20 ++++++++++++++++----
# 1 file changed, 16 insertions, 4 deletions
```

---

## Efficiency Analysis: What Could Have Been Faster

### Commands Run: 19 total
**Redundancies identified:**
- Ran `git show --name-only` after already seeing files in `git show --stat`
- Ran multiple `git diff` variants checking same differences
- Inspected file contents (`tail`, multiple `git show` calls) before deciding
- Created branch BEFORE verifying what's already in 2.7

### Optimal 5-Command Sequence:
```bash
# 1. Identify source commit and files (on current branch)
git show --stat 7242ba76
# → 3 files: fedavg.py, model.py, model_persistor.py

# 2. Switch to target and check what's already there
git checkout online/2.7
for file in nvflare/app_opt/pt/job_config/model.py nvflare/app_opt/tf/model_persistor.py; do
  git show 7242ba76 -- "$file" | grep -q "^+" && echo "Checking $file..." && \
  git diff HEAD 7242ba76 -- "$file" --quiet && echo "  ✓ Already fixed" || echo "  ✗ Needs extraction"
done
# → Quickly identifies 2 already fixed, 1 needs extraction

# 3. Create branch
git checkout -b cherry-pick-fix-numpy-experiment-tracking-2.7

# 4. Extract only what's needed
git show 7242ba76:nvflare/app_common/np/recipes/fedavg.py > nvflare/app_common/np/recipes/fedavg.py

# 5. Stage and verify
git add nvflare/app_common/np/recipes/fedavg.py && git diff --cached --stat
```

### Key Insight for Next Time:
**Check target branch BEFORE creating new branch.**

This reveals:
1. What's already fixed (skip extraction)
2. What needs extraction (do it)
3. Potential conflicts (plan accordingly)

**Time Saved**: Could reduce from ~19 commands to **5 commands** (saves ~1-2 minutes)

### Updated Pattern:
```
1. git show --stat <commit>           → Identify files
2. git checkout <target>               → Switch to target
3. Quick check each file in target    → What's already there?
4. git checkout -b <new-branch>        → Create branch
5. Extract only needed files           → Skip duplicates
6. git add + verify                    → Done
```

---

## Files Changed

### Modified (1):
- `nvflare/app_common/np/recipes/fedavg.py`
  - Changed from `FedJob` to `BaseFedJob`
  - Added `analytics_receiver` parameter
  - Removed `launch_once` and `shutdown_timeout` parameters
  - Added imports: `AnalyticsReceiver`, `BaseFedJob`
  - Set `self.framework = FrameworkType.RAW`
  - Updated docstring to explain `analytics_receiver`

### Already Fixed in 2.7 (2):
- ✅ `nvflare/app_opt/pt/job_config/model.py` - typo fix
- ✅ `nvflare/app_opt/tf/model_persistor.py` - import fix

---

## Why This Was Relatively Fast

### Time: ~3 minutes total (could be 1-2 minutes with optimal sequence)

1. **Learned from previous cherry-picks**: Immediately used file extraction
2. **Checked for duplicates**: Verified what's already in 2.7 (but did so after some redundant checks)
3. **No conflicts**: File extraction bypassed all merge issues
4. **Skipped duplicates**: Only extracted 1 of 3 files

### Comparison to Old Approach:
- ❌ **Old way**: Try `git cherry-pick`, hit conflicts, resolve manually, retry (10-15 minutes)
- ✅ **Current**: Extract files, check duplicates, some redundant commands (3 minutes)
- 🚀 **Optimal** (for next time): Check target FIRST, then extract (1-2 minutes)

---

## Pattern Recognition Applied

| Situation | Pattern | Action Taken |
|-----------|---------|--------------|
| Single commit in branch | Not a squash merge of PR | Use file extraction |
| 3 files in commit | Check each individually | Verify what's already in 2.7 |
| 2 files already fixed | Skip duplicates | Extract only 1 file |
| Clean file extraction | No conflicts | Stage immediately |

---

## Details of the Main Fix

### Before (2.7):
```python
class NumpyFedAvgRecipe(Recipe):
    def __init__(
        self,
        # ... other params ...
        launch_once: bool = True,
        shutdown_timeout: float = 0.0,
    ):
        # ...
        job = FedJob(name=self.name)  # No experiment tracking support
```

### After (with fix):
```python
class NumpyFedAvgRecipe(Recipe):
    def __init__(
        self,
        # ... other params ...
        analytics_receiver: Optional[AnalyticsReceiver] = None,
    ):
        # ...
        self.framework = FrameworkType.RAW  # For CSE auto-detection
        
        job = BaseFedJob(  # Provides ConvertToFedEvent for tracking
            name=self.name,
            min_clients=self.min_clients,
            analytics_receiver=self.analytics_receiver,
        )
```

### Why This Matters:
- **Enables experiment tracking** for NumPy-based federated learning
- **Consistent with PyTorch/TensorFlow recipes** that already support tracking
- **Simplified API** by removing obsolete parameters
- **Better framework detection** for cross-site evaluation

---

## Next Steps

1. ✅ File staged in `cherry-pick-fix-numpy-experiment-tracking-2.7` branch
2. ⏳ User will sign and commit manually
3. ⏳ Push to create PR for 2.7

---

## Conclusion

**Success Rate**: ✅ 100%  
**Commands Used**: 19 (could be reduced to 5)  
**Time**: 3 minutes (could be 1-2 minutes)  
**Conflicts**: 0  
**Wasted Effort**: Minimal (some redundant checks)

**Key Takeaway**: Check target branch BEFORE creating new branch. This immediately reveals what's already fixed and what needs extraction, eliminating redundant commands and wasted effort.

**Refined 6-Step Pattern** (for next time):
1. `git show --stat <commit>` → Identify files changed
2. `git checkout <target>` → Switch to target branch
3. Quick check each file → What's already there?
4. `git checkout -b <new-branch>` → Create branch
5. Extract only needed files → Skip duplicates
6. Stage and verify → Done

The lessons learned from previous cherry-picks were applied, but with room for efficiency improvement by checking target state earlier in the process.
