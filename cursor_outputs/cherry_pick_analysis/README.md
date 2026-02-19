# Cherry-Pick Analysis - Index

**Purpose:** Document cherry-pick operations from main to 2.7, capturing lessons to prevent repeated mistakes.

---

## ⚠️ MANDATORY: Read First

**[`../WORKFLOW_RULES.md`](../WORKFLOW_RULES.md)** - Follow these rules during ALL cherry-picks:
- Never commit (user commits with signing)
- Stop after `git add` and output: "Changes staged on [branch]. Commit before I continue."
- Speed + accuracy is paramount

---

## Quick Reference

### Simple Cherry-Pick (No Conflicts)
```bash
git fetch online
git checkout -b cherry-pick-name-2.7 online/2.7
git cherry-pick -n <hash>  # -n = no commit
git add .
# STOP - wait for user commit
```

### If Conflicts Occur
See: [`20260109_cross_site_eval_cherry_pick_lessons.md`](#1-cross-site-eval-conflict-handling-jan-9) - scroll to "Correct Conflict Resolution Workflow" section at end

---

## Critical Lessons (Read Before Any Cherry-Pick)

### 1. NEVER Use `git show` for Cherry-Picks ❌
- **Why:** `git show <hash>:<file> > <file>` causes **silent data loss** by replacing entire file
- **Correct approach:** Always use `git cherry-pick -n <hash>` - shows conflicts, preserves target branch data
- **When learned:** sklearn fix (Jan 23), documented in cross-site eval lessons
- **Impact:** Can silently delete features that only exist on target branch

### 2. Verify Remote Name FIRST ⚠️
- **This repo uses `online` not `origin`**
- **Always run:** `git remote -v` then `git fetch online`
- **Cost of mistake:** Hours wasted analyzing wrong branches
- **When learned:** sklearn analysis (Jan 23)

### 3. Check File Existence Before Cherry-Pick
- **Why:** Files missing on target cause silent failures even if patch applies cleanly
- **How to check:** `git show online/2.7:path/to/file`
- **When learned:** missing notebook (Jan 12)
- **Solution:** Either exclude file or create it on 2.7 first

### 4. Recognize 10+ Conflicts as Abort Signal 🛑
- **Signal:** Branches diverged significantly, direct cherry-pick may not be appropriate
- **Action:** Consider whether commit needs dependent changes first, or manual adaptation
- **When learned:** cross-site eval with multiple failed approaches (Jan 9)

---

## Indexed Documents (By Date)

### 1. Cross-Site Eval - Conflict Handling (Jan 9)
**File:** [`20260109_cross_site_eval_cherry_pick_lessons.md`](20260109_cross_site_eval_cherry_pick_lessons.md)

**What happened:** Attempted to cherry-pick cross-site evaluation changes, hit 10+ conflicts, tried 5 different approaches before finding solution.

**Critical content:**
- ⚠️ **Main document uses WRONG method (file extraction)** - documented for historical record only
- ✅ **Scroll to end section "Correct Conflict Resolution Workflow"** for proper approach
- Documents why `git show <hash>:<file> > <file>` causes data loss
- Shows correct conflict resolution: use `git cherry-pick -n` and manually resolve markers

**When to read this:**
- Before any cherry-pick with expected conflicts
- If you see 10+ conflicts and need to decide abort vs resolve
- To understand why file extraction is dangerous

**Key learning:** Cherry-pick `-n` flag shows conflicts (good!), file extraction hides them (bad!). Always prefer the method that forces you to review both versions.

**PR:** #3854 (cross-site eval) → 2.7

---

### 2. Missing Notebook File (Jan 12)
**File:** [`20260112_missing_notebook_file_lesson.md`](20260112_missing_notebook_file_lesson.md)

**What happened:** Cherry-pick failed because notebook file referenced in the patch didn't exist on 2.7 branch.

**Critical content:**
- How to check if files exist on target: `git show 2.7:path/to/file`
- Decision tree: exclude file vs create it first vs find alternative
- Result: Created simplified version without notebook dependency

**When to read this:**
- Before cherry-picking examples that reference notebooks or data files
- When git apply succeeds but changes reference missing files
- To learn verification steps before cherry-picking

**Key learning:** Git patch can apply successfully even if referenced files don't exist. Always verify complete context exists on target branch.

**Status:** Blocked → Resolved with alternative approach

---

### 3. NumPy Experiment Tracking Fix (Jan 14)
**File:** [`20260114_fix_numpy_experiment_tracking_cherry_pick.md`](20260114_fix_numpy_experiment_tracking_cherry_pick.md)

**What happened:** Found that related fixes in main need to be cherry-picked together for feature completeness.

**Critical content:**
- How to identify related fixes: search commit history for same file paths
- When to group vs separate cherry-picks
- Verification that partial fix doesn't break functionality

**When to read this:**
- When cherry-picking bug fixes - check if there are follow-up fixes
- When dealing with experiment tracking or recipe system
- To understand dependency analysis between commits

**Key learning:** Always check git log on files being modified to see if there are later fixes that should be included.

**PR:** Part of #3970 → 2.7

---

### 4. Simplify CSE Recipe (Jan 14)
**File:** [`20260114_simplify_cse_cherry_pick.md`](20260114_simplify_cse_cherry_pick.md)

**What happened:** Successfully cherry-picked squash merge after initial confusion about commit structure.

**Critical content:**
- How to identify squash merge: `git show <hash> --stat` shows single commit with many files
- Why I wasted 2 minutes: assumed pattern from previous multi-commit PR
- Pattern matching: squash merge → file extraction is fast and clean
- Execution: all 13 files extracted in 3 minutes, zero conflicts

**When to read this:**
- When you're unsure if PR was squash-merged or has multiple commits
- To learn how to identify merge type quickly
- For examples of efficient file extraction with loops

**Key learning:** Always check `git show <commit> --stat` FIRST. Don't assume PR structure matches previous PRs. Squash merges are simplest to cherry-pick.

**PR:** #3942 (simplify CSE recipe) → 2.7

---

### 5. Client API Line Count Discrepancy (Jan 20)
**File:** [`20260120_client_api_line_count_discrepancy_report.md`](20260120_client_api_line_count_discrepancy_report.md)

**What happened:** Investigated why client_api.rst had different line counts between branches. Turned out to be non-issue.

**Critical content:**
- Line count differences can be intentional structural variations
- Both branches can be "correct" despite different line counts
- How to verify: check git history, compare logical content not line count
- Lesson: Don't assume discrepancy means missing content

**When to read this:**
- When comparing documentation between branches
- If automated checks flag line count differences
- To avoid false alarm investigations

**Key learning:** Different line counts ≠ problem. Branches can have intentional structural differences. Verify logical completeness, not line matching.

**Status:** Investigation completed → No action needed

---

### 6. Client API Tutorials (Jan 20)
**File:** [`20260120_client_api_tutorials_cherry_pick.md`](20260120_client_api_tutorials_cherry_pick.md)

**What happened:** Cherry-picked Client API documentation enhancements.

**Critical content:**
- Clean documentation cherry-pick process
- Verification steps for doc changes
- Cross-references to related doc improvements

**When to read this:**
- When cherry-picking documentation changes
- For reference on doc verification steps

**Key learning:** Documentation cherry-picks are typically straightforward with file extraction.

**PR:** #3930 (Client API tutorials) → 2.7

---

### 7. Remove SAG References (Jan 20)
**File:** [`20260120_remove_sag_cherry_pick.md`](20260120_remove_sag_cherry_pick.md)

**What happened:** Successfully removed Scatter and Gather references across many files.

**Critical content:**
- Handling large-scale refactoring (23+ files)
- Verification that all references removed consistently
- Pattern for cleanup/removal cherry-picks

**When to read this:**
- When cherry-picking large refactors touching many files
- To learn verification strategies for removal PRs
- For patterns on systematic cleanup

**Key learning:** For systematic removals, verify consistency across all file types (code, docs, tests, examples).

**PR:** SAG removal → 2.7

---

### 8. XGBoost Recipe Conversion (Jan 20)
**File:** [`20260120_xgboost_recipe_cherry_pick.md`](20260120_xgboost_recipe_cherry_pick.md)

**What happened:** Large cherry-pick (29 files) completed in 3 minutes with zero conflicts using optimal file extraction.

**Critical content:**
- Handling renames: extract to new location, delete old location
- Managing additions + modifications + deletions in single cherry-pick
- Statistics: 2162 insertions, 754 deletions across 29 files
- Proof that file extraction scales to large changes

**When to read this:**
- Before cherry-picking large recipe conversions
- To see how file extraction handles complex file operations
- For confidence that method works at scale

**Key learning:** File extraction method scales perfectly. Large changes (29 files) are just as fast and clean as small changes (1 file). Systematic approach with loops handles bulk operations efficiently.

**PR:** #3951 (XGBoost recipe) → 2.7

---

### 9. Fix hello-numpy-cross-val (Jan 21)
**File:** [`20260121_fix_hello_numpy_cross_val_cherry_pick.md`](20260121_fix_hello_numpy_cross_val_cherry_pick.md)

**What happened:** Cherry-picked fix that makes `initial_model` required in NumPy recipes (was Optional, causing runtime errors).

**Critical content:**
- **Dependency alert:** client_api.rst includes changes from TWO PRs (this one + #3960)
- Merge order matters: if Client API tutorials merges first, this needs rebase
- Technical change: `initial_model: Optional[list] = None` → `initial_model: list` (required)
- Why: NumPy recipes MUST have initial model, unlike PyTorch/TF which can infer from training

**When to read this:**
- Before cherry-picking NumPy recipe changes
- When dealing with cross-PR file dependencies
- To understand merge order coordination

**Key learning:** Track cross-PR dependencies. When multiple PRs modify same file, coordinate merge order to avoid redundant rebases.

**PR:** #3988 (fix hello-numpy-cross-val) → 2.7

---

### 10. Web Updates (Jan 21)
**File:** [`20260121_web_updates_cherry_pick.md`](20260121_web_updates_cherry_pick.md)

**What happened:** Cherry-picked web page updates including security dependency bumps.

**Critical content:**
- Security fixes included
- Web component update process

**When to read this:**
- When cherry-picking web-related changes
- For security update patterns

**Key learning:** Security fixes should be prioritized and cherry-picked promptly.

**Note:** Includes security dependency updates

---

### 11. Experiment Tracking Recipes (Jan 22)
**File:** [`20260122_experiment_tracking_recipes_cherry_pick.md`](20260122_experiment_tracking_recipes_cherry_pick.md)

**What happened:** Combined TWO related PRs (#3907 + #3934) by extracting from later commit. The second PR only fixed import paths in files created by first PR.

**Critical content:**
- **New pattern:** "Later commit extraction" - when fix PR only touches files from feature PR, extract from fix commit to get both
- Strategy: extract from `895cdf88` (fix commit) instead of `eac67c15` (feature commit)
- Result: got feature + fixes in single cherry-pick, zero conflicts
- File overlap: 100% - every file in fix PR was created by feature PR
- Benefit: no interim broken state, users get working code immediately

**When to read this:**
- When you see a small follow-up PR after a large feature PR
- To learn how to identify fix commits that should be combined
- For pattern on combining sequentially dependent PRs

**Key learning:** When follow-up PR only fixes files from recent feature PR, extract from the later "fix" commit to get everything at once. Check file overlap first: 100% overlap = combine them.

**When NOT to combine:**
- Fix PR touches other unrelated files
- Fix PR includes additional features
- PRs are logically independent

**PRs:** #3907 (experiment tracking) + #3934 (fix import paths) → 2.7

---

### 12. sklearn Fix - Critical Methodology Errors (Jan 23)
**File:** [`20260123_sklearn_fix_merged_to_27_with_correct_readme.md`](20260123_sklearn_fix_merged_to_27_with_correct_readme.md)

**What happened:** Analyzed sklearn fix already merged to 2.7, revealed critical workflow failures that wasted hours.

**Critical content:**
- ❌ **MISTAKE 1:** Failed to fetch from correct remote (`online` not `origin`) immediately
- ❌ **MISTAKE 2:** Used `git show` for file extraction instead of `git cherry-pick -n`
- **Impact:** Hours wasted analyzing wrong branches, risk of silent data loss
- **Root cause:** WORKFLOW_RULES.md didn't include remote verification step
- **Fix applied:** Updated WORKFLOW_RULES.md with mandatory remote check

**What the PR actually fixed:**
- sklearn examples broken after Recipe API migration
- Created `CollectAndAssembleModelAggregator` adapter class
- Fixed README to correctly document cuML as advanced feature
- Changes already correctly merged to 2.7 as of commit `96bb3619`

**When to read this:**
- **Before ANY new analysis task** - learn the "verify remote first" rule
- To understand cost of wrong remote (analyzing non-existent problems)
- To see impact of wrong cherry-pick method
- As reminder of why Critical Lessons section exists

**Key learning:** ALWAYS verify remote first: `git remote -v && git fetch online`. Wrong remote = analyzing wrong codebase = wasted hours. This mistake directly led to adding "Critical Lessons" section at top of this README.

**PR:** #4015 (sklearn fix, by YuanTingHsieh) - already merged to 2.7, later ported to main

**Branches to clean up:**
- `yt_fix_sklearn_examples_27` - local branch with incorrect changes, delete it
- `cherry-pick-sklearn-per-site-config-2.7` - obsolete, close it
- `fix-sklearn-svm-readme-remove-backend` - may be redundant, check it

---

## Statistics

- **Total Documented:** 12 cherry-picks
- **Successful:** 11
- **Blocked (resolved):** 1 (missing file → alternative approach)
- **Critical Methodology Failures:** 2 (wrong remote, wrong method)
- **Total Files Across All Cherry-Picks:** ~150+
- **Average Time (after learning):** 2-3 minutes per cherry-pick
- **Average Time (before learning):** 20-30 minutes per cherry-pick

**Efficiency improvement from lessons learned: 10x faster**

---

## Common Patterns

### Recipe Conversions (xgboost, experiment tracking, CSE simplification)
**Characteristics:**
- Often include: recipe file + example updates + tests + docs
- 20-30+ files changed
- Need to verify Recipe API compatibility on 2.7

**Strategy:**
- Check if squash merge: `git show <hash> --stat`
- Use file extraction for clean application
- Test examples in venv before creating PR

**Related docs:** [#4 Simplify CSE](#4-simplify-cse-recipe-jan-14), [#8 XGBoost](#8-xgboost-recipe-conversion-jan-20), [#11 Experiment Tracking](#11-experiment-tracking-recipes-jan-22)

---

### Bug Fixes (numpy fixes, cross-val, experiment tracking fixes)
**Characteristics:**
- Usually focused, smaller changes (1-10 files)
- May have follow-up fixes for same feature
- Should be tested in venv

**Strategy:**
- Check for related fixes: `git log --oneline main -- <file_path>`
- Consider combining with follow-up fixes (see pattern in [#11](#11-experiment-tracking-recipes-jan-22))
- Test before submitting

**Related docs:** [#3 NumPy Fix](#3-numpy-experiment-tracking-fix-jan-14), [#9 hello-numpy-cross-val](#9-fix-hello-numpy-cross-val-jan-21), [#11 Experiment Tracking](#11-experiment-tracking-recipes-jan-22)

---

### Documentation (Client API, web updates, READMEs)
**Characteristics:**
- May have structural differences between branches (both can be correct)
- Often part of larger PRs
- Cross-PR dependencies possible

**Strategy:**
- Verify differences are intentional, not missing content
- Check for cross-PR dependencies (same file modified by multiple PRs)
- Consider merge order if dependencies exist

**Related docs:** [#5 Line Count Investigation](#5-client-api-line-count-discrepancy-jan-20), [#6 Client API Tutorials](#6-client-api-tutorials-jan-20), [#9 Cross-PR Dependencies](#9-fix-hello-numpy-cross-val-jan-21)

---

### Cleanup/Refactoring (SAG removal)
**Characteristics:**
- Touches many files (20+ files)
- Systematic removal or renaming
- Need consistency verification across all references

**Strategy:**
- Use file extraction with loops for bulk operations
- Verify consistency: grep for old patterns to ensure complete removal
- Check all file types: code, docs, tests, examples, configs

**Related docs:** [#7 Remove SAG](#7-remove-sag-references-jan-20)

---

## Troubleshooting

### Problem: Missing Files on Target
**Symptoms:** Git shows file in patch but apply fails, or references to non-existent files

**Diagnosis:**
```bash
# Check if file exists on target
git show online/2.7:path/to/file

# If file doesn't exist, check when it was added
git log --follow -- path/to/file
```

**Solutions:**
1. Exclude file from cherry-pick if not essential
2. Cherry-pick the commit that created the file first
3. Create file on target branch first
4. Find alternative that doesn't need the file

**See:** [#2 Missing Notebook](#2-missing-notebook-file-jan-12)

---

### Problem: 10+ Conflicts in Unexpected Files
**Symptoms:** `git merge --squash` or `git cherry-pick` shows conflicts in files unrelated to feature

**Diagnosis:**
```bash
# Check how many merge commits
git log --oneline --merges <branch>

# Check how much branch diverged
git log --oneline online/2.7..<branch> | wc -l
```

**What this means:**
- Branches diverged significantly
- Source branch includes many other PRs not in target
- Direct cherry-pick may not be appropriate

**Solutions:**
1. **STOP immediately** - don't try to resolve conflicts
2. Consider: Is this commit even relevant for target branch?
3. Check: Are there dependent commits that need cherry-picking first?
4. Alternative: Manually adapt changes rather than direct cherry-pick
5. Last resort: Abort and document why

**DON'T:** Use file extraction (`git show`) to bypass conflicts - causes data loss!

**DO:** Use `git cherry-pick -n` and manually resolve conflict markers to preserve both versions

**See:** [#1 Cross-Site Eval](#1-cross-site-eval-conflict-handling-jan-9) - scroll to end for correct workflow

---

### Problem: Line Count Discrepancies Between Branches
**Symptoms:** Same file has different line counts on main vs 2.7

**Diagnosis:**
```bash
# Check git history on both branches
git log online/2.7 -- path/to/file
git log origin/main -- path/to/file

# Compare logical structure
git show online/2.7:path/to/file | head -100
git show origin/main:path/to/file | head -100
```

**What this means:**
- May be intentional structural differences
- Both branches can be correct
- Line count is NOT a bug indicator

**Solutions:**
1. Compare logical content, not line count
2. Check if both versions serve their branch's needs
3. Don't cherry-pick just to "sync" line counts

**See:** [#5 Line Count Investigation](#5-client-api-line-count-discrepancy-jan-20)

---

### Problem: Tests Fail After Cherry-Pick
**Symptoms:** Examples or tests that pass on main fail on 2.7

**Diagnosis:**
```bash
# Check test setup differences
git diff online/2.7 origin/main -- tests/

# Check for missing dependencies
git log origin/main --grep="<feature>" --all
```

**Possible causes:**
1. Missing dependent commits (need to cherry-pick those too)
2. Test infrastructure differs between branches
3. Feature requires other features not in 2.7

**Solutions:**
1. Identify and cherry-pick dependent commits
2. Adapt tests for 2.7's infrastructure
3. Run tests in clean venv to verify

**See:** [#3 NumPy Fix](#3-numpy-experiment-tracking-fix-jan-14), [#9 hello-numpy-cross-val](#9-fix-hello-numpy-cross-val-jan-21)

---

### Problem: Wrong Remote (online vs origin)
**Symptoms:** Can't find branches, analyzing code that doesn't match reality, fetch fails

**Diagnosis:**
```bash
git remote -v
# Should show 'online' not 'origin'
```

**Impact:**
- **Hours wasted** analyzing wrong codebase
- Creating fixes for non-existent problems
- Confusion about what's merged where

**Solution:**
```bash
# ALWAYS start every analysis/cherry-pick with:
git remote -v
git fetch online
git fetch online --tags
```

**Prevention:** Updated WORKFLOW_RULES.md to include this as mandatory first step

**See:** [#12 sklearn Analysis](#12-sklearn-fix-critical-methodology-errors-jan-23)

---

## Decision Trees

### Cherry-Pick Strategy Selection

```
Need to cherry-pick from main to 2.7?
  ↓
STEP 1: Verify remote and update
  $ git remote -v                    # Confirm 'online' not 'origin'
  $ git fetch online
  ↓
STEP 2: Identify commit structure
  $ git show <hash> --stat
  ↓
  ├─ Single commit/squash merge (most common)
  │    ↓
  │    Use file extraction ✅
  │    $ git checkout -b cherry-pick-name-2.7 online/2.7
  │    $ for file in $(git diff-tree --no-commit-id --name-only -r <hash>); do
  │        git show <hash>:"$file" > "$file"
  │      done
  │    $ git add <files>
  │    → Time: 2-3 minutes, Conflicts: 0
  │
  └─ Multiple related commits
       ↓
       Check if later commit is fix for earlier
       ↓
       ├─ YES: Fix only touches files from feature
       │    ↓
       │    Extract from LATER commit ✅ (gets both)
       │    See: Experiment Tracking pattern (#11)
       │    → Time: 2-3 minutes, Conflicts: 0
       │
       └─ NO: Independent commits
            ↓
            Try: git cherry-pick -n <hash>
            ↓
            ├─ 0-3 conflicts in expected files
            │    ↓
            │    Resolve manually ✅
            │    See: Correct resolution workflow (#1 end section)
            │    → Time: 5-10 minutes
            │
            └─ 10+ conflicts in unexpected files
                 ↓
                 ABORT IMMEDIATELY 🛑
                 ↓
                 Evaluate:
                 - Are dependent commits needed first?
                 - Has target branch diverged too much?
                 - Should changes be manually adapted?
                 ↓
                 Document decision in this directory
```

---

### Conflict Resolution Decision

```
Got conflicts from git cherry-pick -n?
  ↓
Count conflicts and check file types
  ↓
  ├─ 1-3 conflicts in files being changed (expected)
  │    ↓
  │    RESOLVE MANUALLY ✅
  │    1. Open each conflicted file
  │    2. Find conflict markers:
  │       <<<<<<< HEAD (target - keep what matters)
  │       =======
  │       >>>>>>> <hash> (source - what you're adding)
  │    3. Understand BOTH versions
  │    4. Merge correctly (don't just pick one)
  │    5. Remove markers
  │    6. $ git add <resolved-file>
  │    7. Repeat for all conflicts
  │    → Preserves all data ✅
  │
  └─ 10+ conflicts in unrelated files (unexpected)
       ↓
       ABORT - DON'T RESOLVE 🛑
       $ git cherry-pick --abort
       ↓
       Investigate why:
       ├─ Branch has merge commits from main? → Many unrelated changes
       ├─ Long time span (months)? → Significant divergence
       └─ Many other PRs mixed in? → Not clean feature branch
       ↓
       Consider alternatives:
       1. Cherry-pick dependent commits first
       2. Manually adapt changes
       3. Wait for related changes to reach 2.7
       4. Document why direct cherry-pick doesn't work
       ↓
       ⚠️ DO NOT use file extraction to bypass conflicts
       (causes silent data loss - see #1 and #12)
```

---

## Start Here (Quick Navigation)

### First cherry-pick ever?
1. **Read:** [`../WORKFLOW_RULES.md`](../WORKFLOW_RULES.md)
2. **Verify remote:** `git remote -v` (must be `online`)
3. **Use:** "Quick Reference" section at top of this README
4. **If it works:** You're done! (most cherry-picks are simple)

---

### Expecting complications (conflicts/large change)?
1. **Read:** "Critical Lessons" section above
2. **Check:** Decision Trees section for strategy
3. **Find similar case:** Use table below

---

### Debugging a failure?
1. **Check:** "Troubleshooting" section for your specific problem
2. **Find similar case:** Search indexed documents for similar symptoms
3. **Learn correct approach:** Read the detailed document

---

## Quick-Find Table (By Problem Type)

| You need to... | Read this document | Key info |
|----------------|-------------------|----------|
| Understand why git show is dangerous | [#1 Cross-Site Eval](#1-cross-site-eval-conflict-handling-jan-9) (end), [#12 sklearn](#12-sklearn-fix-critical-methodology-errors-jan-23) | Causes silent data loss |
| Handle 10+ conflicts correctly | [#1 Cross-Site Eval](#1-cross-site-eval-conflict-handling-jan-9) (end section) | Use cherry-pick -n, resolve manually |
| Check if file exists on target | [#2 Missing Notebook](#2-missing-notebook-file-jan-12) | `git show 2.7:path` |
| Find related fixes to include | [#3 NumPy Fix](#3-numpy-experiment-tracking-fix-jan-14) | Check git log on files |
| Identify squash merge quickly | [#4 Simplify CSE](#4-simplify-cse-recipe-jan-14) | `git show <hash> --stat` |
| Understand line count differences | [#5 Line Count](#5-client-api-line-count-discrepancy-jan-20) | Often structural, not errors |
| Cherry-pick large changes (20+ files) | [#8 XGBoost](#8-xgboost-recipe-conversion-jan-20) | File extraction scales perfectly |
| Handle cross-PR file dependencies | [#9 hello-numpy](#9-fix-hello-numpy-cross-val-jan-21) | Coordinate merge order |
| Combine related PRs (feature + fix) | [#11 Experiment Tracking](#11-experiment-tracking-recipes-jan-22) | Extract from later commit |
| Verify remote before starting | [#12 sklearn](#12-sklearn-fix-critical-methodology-errors-jan-23) | Always check `git remote -v` |
| Handle file renames | [#8 XGBoost](#8-xgboost-recipe-conversion-jan-20) | Extract new location, delete old |
| Remove references systematically | [#7 SAG Removal](#7-remove-sag-references-jan-20) | Use grep to verify completeness |

---

## Template for New Cherry-Pick Documents

When documenting a new cherry-pick, use this structure:

```markdown
# [Feature Name] Cherry-Pick

**Date**: [Date]
**Source Commit**: [hash]
**Target Branch**: online/2.7
**New Branch**: cherry-pick-[name]-2.7
**Status**: [Success/Blocked/Partial]

## Summary
[1-2 sentences: what was cherry-picked and outcome]

**Time**: [X] minutes
**Commands**: [Y] total
**Conflicts**: [Z]
**Files**: [N] changed

## What This PR Does/Fixes
[Explain the actual feature/fix]

## Critical Content
[Bullet points of key learnings, gotchas, special considerations]

## When to Read This
[Specific scenarios where this document is relevant]

## Key Learning
[One sentence takeaway]

## Process Used
[Commands run with explanations]

## Lessons Applied / Not Applied
[What patterns from previous cherry-picks were used or should have been]

## Next Steps
[What happens after staging]
```

---

## Maintenance

### Adding New Documents
1. Create markdown file: `YYYYMMDD_descriptive_name_cherry_pick.md`
2. Add entry in "Indexed Documents" section with detailed description
3. Update statistics section
4. Add to Quick-Find Table if introduces new pattern
5. Update Decision Trees if new strategy learned

### After Failed Cherry-Pick
1. Document what went wrong and why
2. Add to "Critical Lessons" if it reveals methodology issue
3. Update Decision Trees with new abort condition if applicable
4. Add to Troubleshooting section with solution

---

## Version History

- **Jan 9, 2026**: Initial structure, first 2 cherry-picks documented
- **Jan 14, 2026**: Added simplify CSE, numpy fix patterns
- **Jan 20-22, 2026**: Added 7 more cherry-picks, pattern confirmation
- **Jan 23, 2026**: Major revision after sklearn analysis revealed methodology errors
  - Added "Critical Lessons" section
  - Moved sklearn file from parent directory
  - Enhanced all descriptions with actionable details
  - Added decision trees and quick-find table
  - Added troubleshooting section with detailed diagnosis
  - Reorganized for better utility and findability

---

**Total cherry-picks documented:** 12  
**Success rate:** 92% (11/12 successful, 1 resolved with alternative)  
**Average time (optimized):** 2-3 minutes per cherry-pick  
**Most important lesson:** Verify remote first, use cherry-pick -n not git show
