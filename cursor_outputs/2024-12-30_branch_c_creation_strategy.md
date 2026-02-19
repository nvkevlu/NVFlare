# Branch C Creation Strategy: Combining Best of Both Worlds

**Date:** December 30, 2024
**Objective:** Create a new branch C that uses Branch A's architecture with useful parts from Branch B

---

## Branch Analysis

### Branch A: `localholgerroth_fedavg_crosssiteeval`
- **Base commit:** `b213f2b6` (Sept 19, 2025) - **3 MONTHS OLD**
- **Architecture:** Utility function pattern (`add_cross_site_evaluation()`)
- **Status:** Outdated base, needs rebasing on main

### Branch B: `hello_cross_site_eval_recipe`
- **Base commit:** `d1b18cda` (Dec 19, 2025) - **More recent**
- **Architecture:** Dedicated recipe classes
- **Status:** More up-to-date base

### Current main branch: `d1b18cda`
- Branch A is **behind by ~10+ commits**
- Branch B is **at the current main HEAD**

---

## Strategy: File-Based Copy Approach (Zero Memory Risk)

Instead of trying to memorize or manually recreate code, we'll use a **systematic file extraction and merge strategy**.

### Phase 1: Extract Files to Safe Location

Create a staging area where we extract exact files from each branch:

```
/tmp/branch_merge_workspace/
├── branch_a/           # Extract from localholgerroth_fedavg_crosssiteeval
│   ├── nvflare/
│   ├── examples/
│   └── manifest.txt    # List of all changed files
├── branch_b/           # Extract from hello_cross_site_eval_recipe
│   ├── nvflare/
│   ├── examples/
│   └── manifest.txt
├── main_current/       # Extract from current main
│   ├── nvflare/
│   └── examples/
└── merged/             # Where we'll build Branch C
    ├── nvflare/
    └── examples/
```

### Phase 2: Identify Changed Files

**From Branch A (architecture we want):**
1. `nvflare/recipe/utils.py` - Contains `add_cross_site_evaluation()` and `MODEL_LOCATOR_REGISTRY`
2. `nvflare/app_opt/pt/recipes/fedavg.py` - Has `cross_site_eval` parameter (optional)
3. `examples/hello-world/hello-pt/job.py` - CSE example with PyTorch
4. `examples/hello-world/hello-pt/README.md` - Documentation updates

**From Branch B (examples and docs we want):**
1. `examples/hello-world/hello-numpy-cross-val/client.py` - NumPy training script
2. `examples/hello-world/hello-numpy-cross-val/generate_pretrain_models.py` - Pre-trained model generator
3. Documentation structure (not exact files, but concepts)

**To delete:**
1. `examples/hello-world/hello-numpy-cross-val/job_cse.py` - Legacy
2. `examples/hello-world/hello-numpy-cross-val/job_train_and_cse.py` - Legacy

**To create fresh:**
1. `examples/hello-world/hello-numpy-cross-val/job.py` - New unified script using Branch A's utility
2. `examples/hello-world/hello-numpy-cross-val/README.md` - Updated documentation

---

## Detailed Step-by-Step Plan

### Step 1: Create Staging Directory and Extract Files

```bash
# Create staging area
mkdir -p /tmp/branch_merge_workspace/{branch_a,branch_b,main_current,merged}

# Extract Branch A files
cd /tmp/branch_merge_workspace/branch_a
git --git-dir=/Users/kevlu/workspace/repos/secondcopynvflare/.git \
    --work-tree=/tmp/branch_merge_workspace/branch_a \
    checkout localholgerroth_fedavg_crosssiteeval -- .

# Extract Branch B files
cd /tmp/branch_merge_workspace/branch_b
git --git-dir=/Users/kevlu/workspace/repos/secondcopynvflare/.git \
    --work-tree=/tmp/branch_merge_workspace/branch_b \
    checkout hello_cross_site_eval_recipe -- .

# Extract current main
cd /tmp/branch_merge_workspace/main_current
git --git-dir=/Users/kevlu/workspace/repos/secondcopynvflare/.git \
    --work-tree=/tmp/branch_merge_workspace/main_current \
    checkout main -- .
```

### Step 2: Create File Manifests

Generate lists of changed files in each branch:

```bash
# Branch A changes
cd /Users/kevlu/workspace/repos/secondcopynvflare
git diff --name-only main...localholgerroth_fedavg_crosssiteeval > /tmp/branch_merge_workspace/branch_a/manifest.txt

# Branch B changes
git diff --name-only main...hello_cross_site_eval_recipe > /tmp/branch_merge_workspace/branch_b/manifest.txt
```

### Step 3: Create Branch C from Current Main

```bash
cd /Users/kevlu/workspace/repos/secondcopynvflare
git checkout main
git pull origin main  # Ensure we're up to date
git checkout -b combined_cross_site_eval_recipe
```

### Step 4: Copy Core Architecture Files from Branch A

Priority order (most important first):

1. **Core utility function:**
   ```bash
   cp /tmp/branch_merge_workspace/branch_a/nvflare/recipe/utils.py \
      /Users/kevlu/workspace/repos/secondcopynvflare/nvflare/recipe/utils.py
   ```

2. **PyTorch FedAvg recipe (if modified):**
   ```bash
   cp /tmp/branch_merge_workspace/branch_a/nvflare/app_opt/pt/recipes/fedavg.py \
      /Users/kevlu/workspace/repos/secondcopynvflare/nvflare/app_opt/pt/recipes/fedavg.py
   ```

3. **PyTorch example:**
   ```bash
   cp /tmp/branch_merge_workspace/branch_a/examples/hello-world/hello-pt/job.py \
      /Users/kevlu/workspace/repos/secondcopynvflare/examples/hello-world/hello-pt/job.py

   cp /tmp/branch_merge_workspace/branch_a/examples/hello-world/hello-pt/README.md \
      /Users/kevlu/workspace/repos/secondcopynvflare/examples/hello-world/hello-pt/README.md
   ```

### Step 5: Add Missing ValidationJsonGenerator

Apply the fix identified in the comparison report:

```python
# Edit nvflare/recipe/utils.py
# Add ValidationJsonGenerator to add_cross_site_evaluation()
```

### Step 6: Copy Useful Files from Branch B

1. **NumPy training script:**
   ```bash
   cp /tmp/branch_merge_workspace/branch_b/examples/hello-world/hello-numpy-cross-val/client.py \
      /Users/kevlu/workspace/repos/secondcopynvflare/examples/hello-world/hello-numpy-cross-val/client.py
   ```

2. **Pre-trained model generator:**
   ```bash
   cp /tmp/branch_merge_workspace/branch_b/examples/hello-world/hello-numpy-cross-val/generate_pretrain_models.py \
      /Users/kevlu/workspace/repos/secondcopynvflare/examples/hello-world/hello-numpy-cross-val/generate_pretrain_models.py
   ```

### Step 7: Create New Unified job.py for NumPy

Instead of copying, we'll create this fresh using the recommended pattern from the comparison report.

### Step 8: Delete Legacy Files

```bash
cd /Users/kevlu/workspace/repos/secondcopynvflare
git rm examples/hello-world/hello-numpy-cross-val/job_cse.py
git rm examples/hello-world/hello-numpy-cross-val/job_train_and_cse.py
```

### Step 9: Verification Steps

Before committing:

1. **Syntax check all Python files:**
   ```bash
   python -m py_compile nvflare/recipe/utils.py
   python -m py_compile nvflare/app_opt/pt/recipes/fedavg.py
   python -m py_compile examples/hello-world/hello-pt/job.py
   python -m py_compile examples/hello-world/hello-numpy-cross-val/job.py
   python -m py_compile examples/hello-world/hello-numpy-cross-val/client.py
   ```

2. **Import test:**
   ```bash
   python -c "from nvflare.recipe.utils import add_cross_site_evaluation; print('✓ Import successful')"
   ```

3. **Run linters:**
   ```bash
   flake8 nvflare/recipe/utils.py
   ```

4. **Run existing tests:**
   ```bash
   pytest tests/unit_test/recipe/ -v
   pytest tests/integration_test/ -k cross_site -v
   ```

---

## Files to Copy/Create/Modify

### Copy Exactly As-Is from Branch A ✅

| File | Source | Verification |
|------|--------|--------------|
| `nvflare/recipe/utils.py` | Branch A | Check `add_cross_site_evaluation()` exists |
| `nvflare/app_opt/pt/recipes/fedavg.py` | Branch A | Check `cross_site_eval` parameter exists |
| `examples/hello-world/hello-pt/job.py` | Branch A | Check `--cross_site_eval` flag exists |

### Copy Exactly As-Is from Branch B ✅

| File | Source | Verification |
|------|--------|--------------|
| `examples/hello-world/hello-numpy-cross-val/client.py` | Branch B | Check training logic present |
| `examples/hello-world/hello-numpy-cross-val/generate_pretrain_models.py` | Branch B | Check model generation logic |

### Modify from Branch A 🔧

| File | Modification Needed |
|------|---------------------|
| `nvflare/recipe/utils.py` | Add `ValidationJsonGenerator` and `model_locator_config` param |

### Create Fresh ✨

| File | Approach |
|------|----------|
| `examples/hello-world/hello-numpy-cross-val/job.py` | Use template from comparison report Section 7 |
| `examples/hello-world/hello-numpy-cross-val/README.md` | Adapt Branch B structure with Branch A approach |

### Delete 🗑️

| File | Reason |
|------|--------|
| `examples/hello-world/hello-numpy-cross-val/job_cse.py` | Legacy FedJob API |
| `examples/hello-world/hello-numpy-cross-val/job_train_and_cse.py` | Legacy FedJob API |

---

## Conflict Resolution Strategy

### If Branch A's utils.py conflicts with main:

1. Extract the `add_cross_site_evaluation()` function only
2. Manually merge into main's `utils.py`
3. Preserve any updates made to main since Sept 19

### If examples conflict:

1. Start from main's version
2. Add CSE functionality incrementally
3. Test at each step

---

## Testing Strategy

### Unit Tests
```bash
# Test utility function
pytest tests/unit_test/recipe/test_utils.py -v -k cross_site

# Test recipes
pytest tests/unit_test/app_opt/pt/recipes/test_fedavg.py -v
```

### Integration Tests
```bash
# Test PyTorch CSE
cd examples/hello-world/hello-pt
python job.py --n_clients 2 --num_rounds 1 --cross_site_eval

# Test NumPy standalone CSE
cd examples/hello-world/hello-numpy-cross-val
python generate_pretrain_models.py
python job.py --mode pretrained

# Test NumPy training+CSE
python job.py --mode training --num_rounds 1
```

### Validation Checklist
- [ ] All Python files compile without syntax errors
- [ ] All imports resolve correctly
- [ ] PyTorch CSE example runs successfully
- [ ] NumPy standalone CSE runs successfully
- [ ] NumPy training+CSE runs successfully
- [ ] No hardcoded paths (use tempfile)
- [ ] Documentation is accurate
- [ ] Legacy files are deleted
- [ ] No merge conflicts remain

---

## Rollback Plan

If anything goes wrong:

```bash
# Rollback Branch C
cd /Users/kevlu/workspace/repos/secondcopynvflare
git checkout main
git branch -D combined_cross_site_eval_recipe

# Clean staging area
rm -rf /tmp/branch_merge_workspace
```

Then restart from Step 1 with lessons learned.

---

## Timeline Estimate

| Phase | Time | Status |
|-------|------|--------|
| 1. Extract files to staging | 10 min | Pending |
| 2. Create Branch C | 2 min | Pending |
| 3. Copy Branch A architecture | 15 min | Pending |
| 4. Apply fixes to utils.py | 10 min | Pending |
| 5. Copy Branch B examples | 10 min | Pending |
| 6. Create new job.py | 20 min | Pending |
| 7. Update README | 15 min | Pending |
| 8. Delete legacy files | 2 min | Pending |
| 9. Testing & verification | 30 min | Pending |
| 10. Documentation review | 10 min | Pending |
| **Total** | **~2 hours** | |

---

## Success Criteria

Branch C is complete when:

1. ✅ All files copied accurately from staging (zero memorization errors)
2. ✅ `add_cross_site_evaluation()` utility works with both PyTorch and NumPy
3. ✅ PyTorch example demonstrates CSE with single flag
4. ✅ NumPy example demonstrates both standalone and training+CSE modes
5. ✅ All legacy files removed
6. ✅ All tests pass
7. ✅ Documentation is clear and accurate
8. ✅ No conflicts with current main
9. ✅ Code follows NVFlare conventions
10. ✅ Ready for PR submission

---

## Next Steps

Would you like me to:
1. **Execute this plan** step-by-step with verification at each stage?
2. **Modify the strategy** if you see any issues?
3. **Add additional safety checks** before we start?

The key advantage of this approach:
- ✅ **Zero memory/hallucination risk** - copying exact files
- ✅ **Verifiable at every step** - can check diffs before committing
- ✅ **Reversible** - can rollback cleanly
- ✅ **Systematic** - follows checklist, can't miss steps
