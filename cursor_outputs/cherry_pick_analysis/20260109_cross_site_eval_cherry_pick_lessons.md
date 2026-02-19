# Cross-Site Eval Cherry-Pick: What Worked and Why I Struggled

**Date:** January 9, 2026
**Task:** Cherry-pick cross-site evaluation changes from `combined_cross_site_eval_recipe` branch to `2.7` branch
**Status:** ⚠️ Successful but used WRONG method - causes data loss
**Updated:** January 23, 2026

---

## ⚠️ CRITICAL WARNING (Added Jan 23, 2026)

**The file extraction method documented below is DANGEROUS and causes data loss.**

Using `git show <hash>:<file> > <file>` replaces the entire file and silently deletes any changes the target branch has.

**Correct method:** Always use `git cherry-pick -n` and manually resolve conflicts.

**See "Correct Conflict Resolution Workflow" at the end of this document.**

---

## Executive Summary (Original - Documents WRONG approach)

Successfully cherry-picked cross-site evaluation changes to 2.7 by extracting specific files directly from commits after recognizing that squash merge produced 10+ conflicts.

**Key Revelation from Analysis:**
My initial understanding was wrong. I thought the consolidation cherry-pick worked because the branch was "clean" (no merges/other PRs), while cross-site eval failed because it was "messy."

**Actually:** Both branches were messy (both had 3-11 merge commits and multiple other PRs). The real difference was the **number of conflicts**:
- Consolidation: Few tolerable conflicts → squash merge worked
- Cross-site eval: 10+ intolerable conflicts → needed file extraction

**The core mistake:** Not recognizing the "10+ conflicts" signal as an immediate abort condition. I spent 20 minutes trying cherry-pick variations instead of pivoting to file extraction after seeing the conflict count.

---

## Summary

Successfully cherry-picked cross-site evaluation changes to 2.7 by extracting specific files directly from the final polished commits, rather than continuing to try squash merge or cherry-pick variations after encountering massive conflicts.

---

## Complete Cherry-Pick History

### Cherry-Pick #1: Consolidation (December 23, 2025) ✅

**Branch:** `consolidate_base_fed_job_fedavg` → `2.7`
**Approach:** `git merge --squash --no-commit`
**Result:** ✅ **Success**

**What happened:**
1. Initially tried individual `git cherry-pick` commands
2. Hit GPG signing errors: `gpg failed to sign the data`
3. Tried `git cherry-pick --continue` but conflicts arose
4. **Pivoted to squash merge:** `git merge --squash --no-commit consolidate_base_fed_job_fedavg`
5. Resolved a few conflicts (tolerable, in expected files)
6. User manually committed with GPG signing

**Files changed:** 8 files (nvflare core files + web assets)
- `nvflare/app_opt/pt/job_config/base_fed_job.py`
- `nvflare/app_opt/pt/recipes/fedavg.py`
- `nvflare/app_opt/sklearn/recipes/fedavg.py`
- `nvflare/app_opt/tf/job_config/base_fed_job.py`
- `nvflare/app_opt/tf/recipes/fedavg.py`
- `nvflare/job_config/base_fed_job.py` (new)
- `nvflare/recipe/__init__.py`
- `nvflare/recipe/fedavg.py` (new)
- Plus web component files

**Branch characteristics:**
- Had 3+ merge commits from main
- Had other PRs mixed in (#3661, #3880, #3707)
- BUT: Conflicts were tolerable (few, in expected files)

**Lessons from this attempt:**
- ✅ Squash merge avoids GPG signing issues during cherry-pick
- ✅ Allows grouping multiple commits into one logical change
- ✅ User can manually commit and sign after staging

---

### Cherry-Pick #2: Import Fix (December 23, 2025) ✅

**Branch:** `fix_import_TBAnalyticsReceiver` → `2.7` (on top of consolidation)
**Approach:** Applied on top of existing cherry-pick branch
**Result:** ✅ **Success**

**What happened:**
1. User wanted to combine import fix with consolidation in same PR
2. Applied import fix commits on top of already-staged consolidation changes
3. Staged together as single coherent change

**Files changed:** 2 files
- `nvflare/app_opt/pt/job_config/base_fed_job.py` - Removed unused TBAnalyticsReceiver import
- `nvflare/app_opt/tf/job_config/base_fed_job.py` - Fixed typo in docstring

**Lessons from this attempt:**
- ✅ Can stack multiple cherry-picks in same branch
- ✅ Makes sense when related changes should be in same PR

---

### Cherry-Pick #3: Cross-Site Eval (January 9, 2026) ✅ (after struggles)

**Branch:** `combined_cross_site_eval_recipe` → `2.7`
**Approach:** File extraction after failed squash merge
**Result:** ✅ **Success** (but took 25+ minutes with multiple failed attempts)

**What happened - in order:**

#### Attempt 3a: Squash Merge (FAILED ❌)
```bash
git merge --squash --no-commit combined_cross_site_eval_recipe
```
- Hit **10+ conflicts** in unexpected files:
  - `docs/user_guide/data_scientist_guide/federated_xgboost/secure_xgboost_user_guide.rst`
  - `examples/advanced/cifar10/pt/cifar10-sim/requirements.txt`
  - `examples/advanced/experiment-tracking/mlflow/hello-lightning-mlflow/client.py`
  - And 7+ more...
- **This was the signal to pivot immediately, but I didn't recognize it**

#### Attempt 3b: Sequential Cherry-Pick with `-n` (FAILED ❌)
```bash
git cherry-pick -n 511a00f7 535b2b60 3b519533 ...
```
- Hit conflict in `nvflare/recipe/utils.py` (docstring polish)
- After resolving, got: `error: your local changes would be overwritten by cherry-pick`
- Git's sequencer got confused with `-n` flag

#### Attempt 3c: Cherry-Pick to Temp Branch WITH Commits (FAILED ❌)
```bash
git cherry-pick 511a00f7 && git cherry-pick 535b2b60 ...
```
- Hit GPG signing error again: `gpg failed to sign the data`
- Same issue as consolidation attempt #1

#### Attempt 3d: Apply Patch (PARTIALLY WORKED ⚠️)
```bash
git diff '9d8d5cbc^1' 9d8d5cbc > /tmp/cross-site-eval.patch
git apply --3way /tmp/cross-site-eval.patch
```
- Applied most files successfully
- Still had 3-4 conflicts remaining
- Required manual resolution

#### Attempt 3e: File Extraction (SUCCESS ✅)
```bash
# Found the feature commits
git log --oneline combined_cross_site_eval_recipe | grep -i cross

# Extracted specific files from final polished commit
git show c43ab9d7:examples/hello-world/hello-numpy-cross-val/README.md > ...
# ... for each file

# Removed deleted files
rm examples/hello-world/hello-numpy-cross-val/job_cse.py
rm examples/hello-world/hello-numpy-cross-val/job_train_and_cse.py

# Staged cleanly
git add examples/hello-world/hello-numpy-cross-val/ ...
```
- **Zero conflicts**
- **Zero GPG issues**
- **Clean and fast**

**Branch characteristics:**
- Had **11 merge commits** from main (vs 3 for consolidation)
- Had **many more PRs** mixed in:
  - #3894 Kaplan-Meier conversion
  - #3931, #3928 Doc restructuring
  - #3924 Remove SAG
  - #3907 Experiment tracking refactor
  - #3906 Remove old examples
  - And 5+ more
- Conflicts were **intolerable** (10+, in unexpected files)

**Lessons from this attempt:**
- ❌ **Major mistake:** Kept trying cherry-pick variations for 20 minutes after seeing 10+ conflicts
- ✅ **What I should have done:** Pivot to file extraction immediately after squash merge showed 10+ conflicts
- ✅ **File extraction advantages:**
  - No conflicts (extract final clean state)
  - No GPG issues (stage without committing)
  - No sequencer problems (no git state machine)
  - Fast and clean

---

## Historical Pattern Analysis

### Did I Use File Extraction Before?

**NO.** Looking at the history:

1. **Branch C creation (Dec 30, 2024):** File-based copy approach for creating a NEW branch from scratch combining Branch A + Branch B. This was NOT a cherry-pick to an existing branch—it was branch creation.

2. **Consolidation cherry-pick (Dec 23, 2025):** Used **squash merge**, not file extraction. It worked despite branch messiness because conflicts were tolerable.

3. **Cross-site eval cherry-pick (Jan 9, 2026):** Used **file extraction** after squash merge failed with 10+ conflicts.

**Conclusion:** File extraction for cherry-picking is NEW. I've only used it once (now), and it worked brilliantly after other approaches failed.

### Why Didn't I Use File Extraction from the Start?

**Because I didn't know I needed it yet.** The decision tree should be:

```
Try squash merge first
  ↓
Conflicts?
  ├─ 0-3 → Continue with squash merge ✅ (Consolidation case)
  └─ 10+ → STOP. Use file extraction ✅ (Cross-site eval case)
```

I correctly tried squash merge first (it worked for consolidation). The mistake was not recognizing the 10+ conflict signal as an immediate abort condition.

---

## What Worked (Final Approach)

### The Solution
```bash
# 1. Identified the exact commits with cross-site eval changes
git log --oneline combined_cross_site_eval_recipe | grep -i cross

# 2. Found: 511a00f7 (initial) through c43ab9d7 (final fixes)

# 3. Extracted ONLY the specific files using git show
git show c43ab9d7:examples/hello-world/hello-numpy-cross-val/README.md > examples/hello-world/hello-numpy-cross-val/README.md
git show c43ab9d7:examples/hello-world/hello-numpy-cross-val/client.py > examples/hello-world/hello-numpy-cross-val/client.py
# ... etc for each file

# 4. Deleted removed files
rm examples/hello-world/hello-numpy-cross-val/job_cse.py
rm examples/hello-world/hello-numpy-cross-val/job_train_and_cse.py

# 5. Staged everything cleanly
git add examples/hello-world/hello-numpy-cross-val/ examples/hello-world/hello-pt/ nvflare/app_common/np/recipes/ nvflare/recipe/utils.py
```

### Files Changed (Cross-Site Eval Only)
- `examples/hello-world/hello-numpy-cross-val/README.md` - Updated docs
- `examples/hello-world/hello-numpy-cross-val/client.py` - New client implementation
- `examples/hello-world/hello-numpy-cross-val/generate_pretrain_models.py` - Updated
- `examples/hello-world/hello-numpy-cross-val/job.py` - New unified job file
- `examples/hello-world/hello-numpy-cross-val/job_cse.py` - DELETED
- `examples/hello-world/hello-numpy-cross-val/job_train_and_cse.py` - DELETED
- `examples/hello-world/hello-pt/README.md` - Added cross-site eval docs
- `examples/hello-world/hello-pt/job.py` - Updated
- `nvflare/app_common/np/recipes/__init__.py` - Added cross_site_eval export
- `nvflare/app_common/np/recipes/cross_site_eval.py` - NEW recipe
- `nvflare/recipe/utils.py` - Added add_cross_site_eval function

**Result:** Clean, focused changes ready to commit without GPG signing issues or conflicts.

---

## Failed Approaches and Why They Failed

### Attempt 1: Sequential Cherry-Pick with `-n` Flag
```bash
git cherry-pick -n 511a00f7 535b2b60 3b519533 ...
```

**Why it failed:**
1. Hit merge conflict in `nvflare/recipe/utils.py` (docstring polish commit)
2. After resolving, git complained about "your local changes would be overwritten"
3. Cherry-pick sequencing got confused with the `-n` (no-commit) flag

**Error:**
```
CONFLICT (content): Merge conflict in nvflare/recipe/utils.py
error: your local changes would be overwritten by cherry-pick.
```

### Attempt 2: Cherry-Pick to Temp Branch (WITH commits)
```bash
git checkout -b temp-cross-site-eval
git cherry-pick 511a00f7 && git cherry-pick 535b2b60 ...
```

**Why it failed:**
```
error: gpg failed to sign the data
error: failed to write commit object
fatal: cherry-pick failed
```
GPG signing kept failing (same issue we had before).

### Attempt 3: Squash Merge from Branch
```bash
git merge --squash --no-commit combined_cross_site_eval_recipe
```

**Why it failed:**
This was the approach that WORKED for the consolidation cherry-pick, but here it failed with massive conflicts:

```
CONFLICT (content): Merge conflict in docs/user_guide/data_scientist_guide/federated_xgboost/secure_xgboost_user_guide.rst
CONFLICT (rename/delete): examples/advanced/swarm_learning/requirements.txt renamed to examples/advanced/cifar10/pt/cifar10-sim/requirements.txt
CONFLICT (modify/delete): examples/advanced/experiment-tracking/mlflow/hello-lightning-mlflow/client.py
... (10+ conflicts)
```

**Root Cause:** The `combined_cross_site_eval_recipe` branch contained:
- ✅ Cross-site eval changes (what we wanted)
- ❌ Merge commits from main (4+ merges: 32d8d050, 7ab44268, f565a162, b03c6d3c)
- ❌ Other unrelated PRs:
  - #3894 - Kaplan-Meier example conversion
  - #3931 - Doc update part 2
  - #3928 - Doc update part 1
  - #3924 - Remove SAG mentions
  - #3917 - Fix preflight check
  - #3907 - Experiment tracking recipe
  - #3906 - Remove old examples
  - And many more...

### Attempt 4: Apply Patch from Merge Commit
```bash
git diff '9d8d5cbc^1' 9d8d5cbc > /tmp/cross-site-eval.patch
git apply --3way /tmp/cross-site-eval.patch
```

**Why it partially failed:**
The patch applied MOST files but failed on:
- Files that didn't exist in 2.7 yet
- Files with different contexts between main and 2.7

This was close but still left conflicts to manually resolve.

---

## Why This Time Was Different from the Consolidation Success

### Previous Success: Consolidation Branch (December 2024)

Looking at the history, for the consolidation cherry-pick, I successfully used:
```bash
git merge --squash --no-commit consolidate_base_fed_job_fedavg
```

**Why it worked then - CORRECTED ANALYSIS:**

Actually, the consolidate branch was NOT clean either:
- Had 3+ merge commits from main
- Had other PRs mixed in (#3661 device selection, #3880 dashboard, #3707 xgboost)

**But squash merge still worked. Why?**

The key difference was **WHEN the other PRs were added to main vs 2.7**:
- The other PRs in consolidate branch were likely already backported to 2.7
- OR they touched completely different files that didn't conflict with 2.7's state
- The "web/*" files that showed up were actually from the consolidation PR itself

### This Time: Combined Cross-Site Eval Branch

**Why squash merge failed this time:**
- The `combined_cross_site_eval_recipe` branch had **11 merge commits** (vs 3 for consolidate)
- It had **many more PRs** mixed in:
  - #3894 - Kaplan-Meier (major refactor)
  - #3931, #3928 - Doc restructuring
  - #3924 - Remove SAG (major removal)
  - #3907 - Experiment tracking refactor
  - #3906 - Remove old examples
  - And 5+ more
- These PRs modified files that **2.7 didn't have yet** or had in different states
- The branch spanned from August 2024 to January 2026 (much longer timeline)

**Visual comparison:**

```
Consolidation branch (worked with squash merge):
2.7 ─────────┬─────────────────> [stable base]
main ────────┼──> PR1 ──> PR2 ──> [some PRs]
             │      ↓       ↓
             └───> consolidate ──> [3 merges, tolerable conflicts]

Cross-site eval branch (failed with squash merge):
2.7 ─────────┬──────────────────────────────────> [stable base]
main ────────┼──> KM ──> Exp ──> SAG ──> Docs ──> [MANY PRs]
             │     ↓      ↓       ↓        ↓
             └──> CSE ────────────────────────> [11 merges, conflicts everywhere]
```

**The real issue:** Too much divergence between main and 2.7, with too many intermediate PRs that weren't in 2.7.

---

## Did I Forget the Successful Approach?

### Analysis: Yes and No

**What actually happened with consolidation:**
- Consolidation branch ALSO had merge commits (3+) and other PRs
- Squash merge still worked because conflicts were manageable
- I manually verified the changes were correct

**What I tried this time:**
1. ✅ Started with the same approach (squash merge) - correct!
2. ❌ When it failed with 10+ conflicts, I pivoted to cherry-pick instead of file extraction
3. ❌ Spent time trying to make cherry-pick work with different flags
4. ✅ Eventually realized and switched to file extraction

**What I should have recognized immediately:**

The **number and type of conflicts** was the key signal:

| Scenario | Signal | Action |
|----------|--------|--------|
| Consolidation | Few conflicts, expected files | Continue with squash merge |
| Cross-site eval | 10+ conflicts, unexpected files | Switch to file extraction immediately |

**What I should have done when squash merge failed:**
```bash
# When I saw 10+ conflicts, I should have immediately done:

# Step 1: Identify the exact feature commits
git log --oneline --first-parent combined_cross_site_eval_recipe | grep -i "cross-site"
# Result: 511a00f7 through c43ab9d7

# Step 2: See what files those commits touched
git show 511a00f7 --name-only
git show c43ab9d7 --name-only

# Step 3: Extract ONLY those files
git show c43ab9d7:path/to/file > path/to/file
```

**Why I didn't pivot immediately:**
1. **Success bias:** Squash merge worked before, so I tried to make it work again
2. **Tool fixation:** I thought "maybe cherry-pick with different flags will work"
3. **Missing the pattern:** I didn't recognize "10+ conflicts = wrong strategy" pattern
4. **Conflict resolution trap:** I started resolving conflicts instead of questioning the approach

**The key insight I missed:**
> When squash merge gives you 10+ conflicts in unexpected files, the branch has too much divergence. Don't try to resolve conflicts—extract files instead.

**CORRECTED: I didn't forget the approach, I forgot to recognize when to switch approaches.**

---

## Lessons Learned

### 1. **Always Inspect Branch Structure First**
Before choosing a cherry-pick strategy:
```bash
# Check how many merge commits
git log --oneline --merges <branch>

# Check total commit range
git log --oneline <base>..<branch> | wc -l

# Check for clean feature commits
git log --oneline --first-parent <branch>
```

### 2. **Conflict Count Determines Strategy (Not Branch Cleanliness)**

**CORRECTED UNDERSTANDING:** Both consolidation and cross-site eval branches were "messy" (had merges and other PRs), but squash merge worked for one and not the other.

| Conflict Level | Strategy | Example |
|----------------|----------|---------|
| **0-3 conflicts** in expected files | Continue with `git merge --squash --no-commit`, resolve conflicts | Consolidation branch |
| **10+ conflicts** in unexpected files | STOP. Extract files with `git show` instead | Cross-site eval branch |
| **Single commit** needed | `git cherry-pick -n <commit>` | Simple fixes |

**The key metric is not "branch cleanliness" but "conflict compatibility with target branch."**

### 3. **Recognize Failure Patterns Early**
- ✅ 1-2 conflicts in expected files → Normal, resolve and continue
- ❌ 10+ conflicts across unrelated files → Wrong approach, pivot immediately
- ❌ Same conflict type repeating → Strategy issue, not execution issue

### 4. **File Extraction is Powerful for Messy Branches**
When a branch has been through multiple merges and mixed PRs:
```bash
# Find the exact files changed by the feature
git log <branch> --name-only | grep <pattern>

# Extract the final version of each file
for file in <list>; do
  git show <final_commit>:$file > $file
done
```

### 5. **GPG Signing Workaround**
The `-n` flag in cherry-pick is supposed to help avoid GPG issues, but it creates its own problems with git's sequencer. File extraction completely sidesteps this.

---

## The Core Mistake

**I didn't recognize the early warning signal and pivot fast enough.**

The squash merge pattern was correct to try first (it worked for consolidation despite that branch also being messy). The mistake was continuing with variations of cherry-pick after seeing 10+ conflicts, instead of immediately pivoting to file extraction.

**CORRECTED: The issue wasn't trying squash merge—it was not recognizing when to abandon it.**

**Better decision tree:**
```
Need to cherry-pick?
  ↓
Try: git merge --squash --no-commit
  ↓
How many conflicts?
  ├─ 0-3 conflicts in expected files → Resolve and continue
  └─ 10+ conflicts in unexpected files → STOP
       ↓
       Extract files: git show <commit>:file > file
```

**Key insight:** Start with the simple approach (squash merge), but have a clear abort condition (10+ conflicts = switch strategies).

---

## Success Metrics

### Before (Failed Attempts)
- **Time spent:** ~25 minutes
- **Tool calls:** ~40
- **Conflicts encountered:** 10+
- **User frustration:** High ("why is this so hard?", "not like before")

### After (File Extraction)
- **Time to solution:** ~5 minutes
- **Tool calls:** ~10
- **Conflicts encountered:** 0
- **User satisfaction:** ✅ Success

---

## Conclusion

### What I Thought Was the Problem
Initially, I believed the consolidation branch was "clean" (no merges, no other PRs) and that's why squash merge worked. I thought the cross-site eval branch was "messy" and that's why it failed.

### What Was Actually the Problem
**CORRECTED after deep analysis:** Both branches were messy (3-11 merge commits, multiple other PRs). The real difference was:
- **Consolidation:** Tolerable conflicts (few, in expected files) → Squash merge succeeded
- **Cross-site eval:** Intolerable conflicts (10+, in unexpected files) → Squash merge failed

### The Real Lesson
It wasn't about choosing the "right" initial approach—squash merge was correct to try for both. **The mistake was not recognizing when to abandon that approach.**

**Success pattern from all 3 cherry-picks:**
1. ✅ Start with simplest approach (squash merge)
2. ✅ Evaluate the conflict pattern
3. ✅ If conflicts are intolerable (10+, unexpected), pivot immediately to file extraction
4. ✅ Don't try to "fix" a fundamentally incompatible merge

### Did I Forget or Learn?

**I didn't forget—I learned progressively:**

| Attempt | Learning |
|---------|----------|
| **Cherry-pick #1** (Consolidation) | Learned squash merge works for cherry-picking (avoids GPG issues) |
| **Cherry-pick #2** (Import fix) | Learned can stack related changes in same branch |
| **Cherry-pick #3** (Cross-site eval) | Learned when squash merge DOESN'T work (10+ conflicts = use file extraction) |

**File extraction was a NEW technique, not a forgotten one.** I had never used it for cherry-picking before. I discovered it today after exhausting other options.

### Evolution of Knowledge

```
Dec 23, 2025: Learned squash merge for cherry-picks
              ↓
Jan 9, 2026:  Learned file extraction for intolerable conflicts
              ↓
Future:       Will recognize 10+ conflicts signal immediately
```

**Key takeaway:**
> Pattern recognition is valuable, but **signal recognition** is essential. The number and type of conflicts is your signal—not the branch structure. Learn to recognize "this isn't working" early (10+ conflicts) and pivot immediately (within 5 minutes), rather than persisting with variations of a failing approach (20+ minutes).

### Why This Matters for Future Cherry-Picks

The next time we need to cherry-pick:
1. **Do try squash merge first** (it's the simplest when it works)
2. **Watch for the conflict signal** (10+ conflicts = abort signal)
3. **Have file extraction ready as Plan B** (not Plan Z after exhausting all cherry-pick variations)
4. **Time to pivot: 5 minutes, not 25 minutes** (one failed approach = switch, not iterate)

### Summary of All Successful Cherry-Picks

| # | Date | Feature | Source Branch | Approach Used | Time | Result |
|---|------|---------|---------------|---------------|------|--------|
| 1 | Dec 23, 2025 | Consolidation | `consolidate_base_fed_job_fedavg` | Squash merge | ~10 min | ✅ Success |
| 2 | Dec 23, 2025 | Import fix | `fix_import_TBAnalyticsReceiver` | Stacked on #1 | ~5 min | ✅ Success |
| 3 | Jan 9, 2026 | Cross-site eval | `combined_cross_site_eval_recipe` | File extraction (after 20 min of failed attempts) | ~30 min total | ✅ Success |

**Key insight from all three:**
- Cherry-picks #1 and #2 both used squash merge successfully
- Cherry-pick #3 needed file extraction because of 10+ conflicts
- **The determining factor is conflict count, not branch structure**
- Both "messy" branches worked with squash merge when conflicts were tolerable

---

## Quick Reference: Cherry-Pick Decision Tree

```
┌─────────────────────────────────────┐
│ Need to cherry-pick branch to 2.7? │
└────────────────┬────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────┐
│ Step 1: Try squash merge                            │
│ $ git merge --squash --no-commit <branch>           │
└────────────────┬────────────────────────────────────┘
                 │
                 ▼
         ┌───────────────┐
         │ Conflicts?    │
         └───┬───────┬───┘
             │       │
        0-3  │       │  10+
             │       │
             ▼       ▼
    ┌────────────┐  ┌──────────────────────────┐
    │ Resolve &  │  │ ABORT IMMEDIATELY        │
    │ Continue   │  │ Don't try to fix!        │
    └────────────┘  └────────┬─────────────────┘
                             │
                             ▼
                    ┌─────────────────────────────┐
                    │ Step 2: Extract files       │
                    │ 1. Find feature commits     │
                    │ 2. List changed files       │
                    │ 3. Extract with git show    │
                    │ 4. Stage and commit         │
                    └─────────────────────────────┘
```

### Command Cheat Sheet

```bash
# Approach 1: Squash Merge (try first)
git checkout -b cherry-pick-feature-2.7 2.7
git merge --squash --no-commit <branch>
# If 10+ conflicts → abort and use Approach 2
git merge --abort

# Approach 2: File Extraction (use when squash fails)
# Find the feature commits
git log --oneline --first-parent <branch> | grep <feature>

# See what files changed
git show <first_commit> --name-only
git show <last_commit> --name-only

# Extract each file
git show <last_commit>:path/to/file > path/to/file

# Remove deleted files
git rm <deleted_file>

# Stage everything
git add <files>

# Commit
git commit -S -m "Cherry-pick <feature> to 2.7"
```

---

## Time Comparison

| Approach | Time Spent | Tool Calls | Conflicts | Result |
|----------|------------|------------|-----------|--------|
| **Failed attempts** (cherry-pick variations) | 25 min | ~40 | 10+ | ❌ Frustration |
| **Successful approach** (file extraction) | 5 min | ~10 | 0 | ✅ Clean PR |

**Efficiency gain from learning this lesson: 5x faster**

---

## Final Summary: Answering Your Questions

### Q1: Did you successfully use file extraction before?

**NO.** This is the **first time** I used file extraction (`git show <commit>:file > file`) for cherry-picking.

**History:**
- **Dec 30, 2024:** Used file-based copy for creating a NEW branch (Branch C), not for cherry-picking to existing branch
- **Dec 23, 2025:** Used squash merge for consolidation cherry-pick (worked!)
- **Jan 9, 2026:** Used file extraction for cross-site eval cherry-pick (after failures)

**File extraction is a NEW technique I learned today through trial and error.**

### Q2: How many different times did you successfully cherry-pick?

**Three successful cherry-picks:**

1. **Consolidation** (Dec 23, 2025) - Squash merge worked, ~10 minutes
2. **Import fix** (Dec 23, 2025) - Stacked on top, ~5 minutes
3. **Cross-site eval** (Jan 9, 2026) - File extraction worked after 20 min of failures, total ~30 minutes

### Q3: Were there failures with lessons learned?

**YES. Cherry-pick #3 had FIVE failed attempts before success:**

| Attempt | Approach | Failure Reason | Time Wasted |
|---------|----------|----------------|-------------|
| 3a | Squash merge | 10+ conflicts | 5 min |
| 3b | Sequential cherry-pick `-n` | Git sequencer confusion | 5 min |
| 3c | Cherry-pick to temp branch | GPG signing failure | 5 min |
| 3d | Apply patch | Partial success, still had conflicts | 5 min |
| 3e | **File extraction** | ✅ **SUCCESS** | 5 min |

**Total: 25 minutes, where 20 minutes were wasted on approaches that couldn't work.**

### Q4: Why didn't you just use file extraction from the beginning?

**Because I didn't know I needed it yet!**

**The correct learning progression:**
1. Try squash merge first (it's simplest and works most of the time)
2. If 10+ conflicts → recognize this signal immediately
3. Pivot to file extraction (don't try variations)

**The mistake:** Not recognizing the 10+ conflict signal fast enough. I spent 20 minutes trying to "fix" squash merge instead of pivoting immediately.

### Q5: Did you forget and continue on the track of failure?

**Not exactly forgotten—I had never learned file extraction for cherry-picks before.**

**What I did know:** Squash merge (from cherry-pick #1)
**What I didn't know yet:** When to abandon squash merge and use file extraction
**What I learned today:** 10+ conflicts = immediate signal to switch strategies

**The progression:**
- ✅ Correctly tried squash merge first (right approach)
- ❌ Didn't recognize 10+ conflicts as abort signal (learning moment)
- ❌ Tried multiple variations of failing approach (persistence bias)
- ✅ Eventually discovered file extraction (new technique learned)

### Key Insight

**This wasn't forgetting—it was learning.** Each cherry-pick taught me something new:

- Cherry-pick #1: Squash merge > individual cherry-picks
- Cherry-pick #2: Can stack related changes
- Cherry-pick #3: 10+ conflicts = use file extraction

**For next time:** I now have the complete playbook, including the abort condition (10+ conflicts) and the alternative strategy (file extraction).


---

## Correct Conflict Resolution Workflow (Added Jan 23, 2026)

### ⚠️ Why File Extraction is Wrong

The "success" documented above used:
```bash
git show <hash>:path/to/file > path/to/file  # WRONG - causes data loss!
```

**Problem:** This replaces the ENTIRE file, deleting any changes the target branch has that the source doesn't have.

### ✅ Correct Approach: Cherry-Pick + Manual Conflict Resolution

```bash
# 1. Always use cherry-pick with -n (no commit)
git cherry-pick -n <hash>

# 2. If conflicts occur, git will show:
# CONFLICT (content): Merge conflict in path/to/file

# 3. Check which files have conflicts
git status

# 4. Open conflicted files and look for markers:
#    <<<<<<< HEAD (target branch - keep what matters here)
#    ... target's code ...
#    =======
#    ... source commit's code ...
#    >>>>>>> <hash>

# 5. Resolve by understanding BOTH versions and merging correctly
# Remove conflict markers after resolving

# 6. Stage resolved files
git add <resolved-file>

# 7. After all conflicts resolved, STOP
# Output: "Changes staged on [branch]. Commit before I continue."
```

### When to Abort Instead

If you see **10+ conflicts in unexpected files** (like this cherry-pick had):
- This signals the branches have diverged significantly
- Consider if the commit is even relevant for the target branch
- May need to cherry-pick dependent commits first
- Or adapt the changes rather than direct cherry-pick

**Abort command:**
```bash
git cherry-pick --abort
# Document why in this folder
```

### Key Difference

- **File extraction (`git show`)**: Zero conflicts, but SILENT DATA LOSS
- **Cherry-pick (`git cherry-pick -n`)**: Shows conflicts, preserves all data, forces you to resolve correctly

**Always choose the method that shows conflicts over the one that hides them.**
