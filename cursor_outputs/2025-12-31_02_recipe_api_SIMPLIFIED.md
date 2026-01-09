# Recipe API Migration Status - SIMPLIFIED
Date: 2025-01-04

## Executive Summary

**You're RIGHT** - for most simulation cases, we CAN just use `python job.py`! I was overcomplicating it. However, there are still some issues to address.

## Current Changes Status

### ✅ What's Good (Keep As-Is):
1. **Path replacements** from `hello-numpy-sag` → `hello-numpy` - Correct!
2. **Test directory rename** - Correct!
3. **Most documentation updates** - Paths are now correct!

### ⚠️ What Needs Minor Fixes:

#### 1. Simulation/Simulator Commands - EASY FIX

**FOR SIMULATOR**: Just change to `python job.py` approach

Examples that need updates:
- `examples/tutorials/flare_simulator.ipynb`
- `examples/tutorials/logging.ipynb`
- `docs/user_guide/nvflare_cli/fl_simulator.rst`

**OLD (won't work)**:
```bash
nvflare simulator -w workspace -n 2 ../hello-world/hello-numpy
```

**NEW (simple!)**:
```bash
cd ../hello-world/hello-numpy
python job.py  # That's it!
```

**Why**: The job.py already has SimEnv inside it, so just run it directly.

---

#### 2. POC/Production Submission - NEEDS CONTEXT

**FOR POC/PROD**: Need to clarify the workflow

Examples that need updates:
- `examples/tutorials/flare_api.ipynb`
- `docs/user_guide/nvflare_cli/poc_command.rst`

**Can't do this** (my mistake):
```python
sess.submit_job("hello-world/hello-numpy")  # ❌ Won't work
```

**Two valid options**:

**Option A: Export first** (traditional workflow)
```python
# Export the recipe to a job folder
cd hello-world/hello-numpy
python -c "
from job import recipe
recipe.export('/tmp/exported_job')
"
# Then submit normally
sess.submit_job("/tmp/exported_job/hello-numpy")
```

**Option B: Use Recipe's execute** (new way)
```python
from hello_numpy.job import recipe  # Or recreate recipe
from nvflare.recipe import PocEnv

env = PocEnv(num_clients=2)
run = recipe.execute(env)  # Handles everything
```

**Recommendation**: Show BOTH options, note that Option A is "traditional feel", Option B is "Recipe API way"

---

## What to Change Where

### 🔴 Critical (Tutorials Users Follow):

**File: `examples/tutorials/flare_simulator.ipynb`**
- Cell 4: Change simulator command to `python job.py` approach
- Add note: "hello-numpy uses Recipe API, run job.py directly"

**File: `examples/tutorials/logging.ipynb`**
- Cells 2, 20: Same as above

**File: `examples/tutorials/flare_api.ipynb`**
- Cells 6-10: Show both export approach AND Recipe execute approach
- Add explanation of why direct submit doesn't work

---

### 🟡 Important (Reference Docs):

**File: `docs/user_guide/nvflare_cli/fl_simulator.rst`**
- Lines 56-60: Update example to use `python job.py`
- Lines 756, 771: Same updates
- Add note about Recipe API examples

**File: `docs/user_guide/nvflare_cli/poc_command.rst`**
- Lines 383, 400, 411: Show export approach or Recipe execute
- Add box explaining Recipe API submission

**File: `docs/examples/hello_scatter_and_gather.rst`**
- This one needs more rewrite (references non-existent config files)
- Can simplify to conceptual overview + point to hello-numpy code

---

### 🟢 Nice to Have:

**Add new doc: `docs/user_guide/recipe_api_quick_start.md`**
```markdown
# Recipe API Quick Start

## Running Examples Locally
cd examples/hello-world/hello-numpy
python job.py  # Runs in simulation

## Submitting to POC/Production

### Method 1: Export then submit (familiar)
python -c "from job import recipe; recipe.export('/tmp/job')"
sess.submit_job("/tmp/job/hello-numpy")

### Method 2: Use Recipe execute (recommended)
from nvflare.recipe import PocEnv, ProdEnv
env = PocEnv(num_clients=2)  # or ProdEnv(...)
run = recipe.execute(env)
```

---

## Testing Checklist

### Simulation (Should work now):
- [x] `cd hello-numpy && python job.py` ✅
- [ ] Update tutorials to show this
- [ ] Update simulator docs to show this

### POC/Production:
- [ ] Document export approach
- [ ] Document Recipe execute approach
- [ ] Test both work
- [ ] Update tutorials

---

## Simplified Action Plan

### This Week (High Priority):

1. **Update 3 tutorial notebooks** (30 mins each)
   - flare_simulator.ipynb → `python job.py`
   - logging.ipynb → `python job.py`
   - flare_api.ipynb → show export OR execute

2. **Update 2 CLI docs** (20 mins each)
   - fl_simulator.rst → `python job.py` examples
   - poc_command.rst → add Recipe submission methods

3. **Add warning boxes** (10 mins)
   - To all updated files explaining Recipe API

### Next Week (Polish):

4. **Simplify hello_scatter_and_gather.rst** (1 hour)
   - Make it conceptual, reference hello-numpy code
   - Remove config file references

5. **Create quick start guide** (30 mins)
   - Recipe API patterns
   - Common workflows

### Later (Nice to Have):

6. Label examples as "Recipe API" vs "Traditional"
7. Create troubleshooting FAQ
8. Test everything end-to-end

---

## Key Messages (Simplified)

### For Simulation:
✅ **Just run `python job.py`** - That's it!

### For POC/Production:
⚠️ **Can't submit Recipe directory directly**
✅ **Two options**: Export first OR use Recipe.execute()

### For Documentation:
📝 **Most path changes are correct**
🔧 **Need to update some workflow examples**
📚 **Add Recipe API explanation where needed**

---

## Your Question: "Can we just replace with python job.py?"

**YES for simulation contexts!**

- ✅ Simulator examples → `python job.py`
- ✅ Quick start tutorials → `python job.py`
- ✅ Local testing → `python job.py`

**But NOT for POC/Production submission:**

- ❌ Can't do `sess.submit_job("hello-numpy")`
- ✅ CAN do: Export first, then submit
- ✅ CAN do: Use Recipe.execute(PocEnv/ProdEnv)

---

## Bottom Line

Your intuition was RIGHT - I was overcomplicating! The fix is much simpler:

1. **Simulation**: Change to `python job.py` ← Simple!
2. **POC/Prod**: Show export or execute method ← Straightforward!
3. **Most path changes**: Already correct ← Keep them!

The documentation just needs:
- Update a few workflow examples
- Add Recipe API context boxes
- Create a quick reference guide

Not the massive rewrite I initially suggested!

---

## Files to Actually Update (Prioritized)

### Must Fix (Break User Workflows):
1. `examples/tutorials/flare_simulator.ipynb` - Change to python job.py
2. `examples/tutorials/logging.ipynb` - Change to python job.py
3. `examples/tutorials/flare_api.ipynb` - Add export/execute options

### Should Fix (Confusing):
4. `docs/user_guide/nvflare_cli/fl_simulator.rst` - Update examples
5. `docs/user_guide/nvflare_cli/poc_command.rst` - Add Recipe methods

### Nice to Fix (Polish):
6. `docs/examples/hello_scatter_and_gather.rst` - Simplify
7. Create new: Quick start guide

**That's it!** Not 40+ files, just ~7 that need attention.
