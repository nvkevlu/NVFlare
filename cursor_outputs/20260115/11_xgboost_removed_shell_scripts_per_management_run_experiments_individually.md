# Shell Scripts Cleanup - XGBoost Examples

## Date: 2026-01-15
## Status: ✅ COMPLETE

---

## Management Feedback

**PR Comments:**
1. > "not sure we need this sh script, just let me run one after another, no need to have a shell script. they really do not like this"

2. > "these are different experiments, why do we need all these?" (on run_experiment_horizontal_histogram.sh)

**Philosophy:**
- Users should run Python commands directly
- READMEs should show ONE canonical example per section
- No wrapper scripts that hide what's happening
- No need to show multiple variations - users can modify parameters
- Users copy-paste and modify the command they need

---

## Shell Scripts Removed

### fedxgb/ (4 scripts deleted)

1. ❌ **`run_experiment_vertical.sh`**
   - Just ran: `python3 job_vertical.py --run_psi --run_training`
   - Trivial wrapper, users can run command directly

2. ❌ **`run_experiment_centralized.sh`**
   - Ran 6 baseline experiments with different parameters
   - Users should choose which experiments to run

3. ❌ **`run_experiment_horizontal_histogram.sh`**
   - Ran 4 histogram experiments with different configs
   - Also referenced deprecated `--training_algo` parameter
   - Users should run specific experiments they need

4. ❌ **`run_experiment_horizontal_tree.sh`**
   - Ran 10 tree-based experiments (5 and 20 clients)
   - Users should select experiments based on their needs

### fedxgb_secure/ (2 scripts deleted)

5. ❌ **`run_experiment.sh`**
   - Ran 4 experiments (horizontal/vertical × secure/non-secure)
   - Added echo messages and comments
   - Users should run experiments individually

6. ❌ **`run_training_standalone.sh`**
   - Ran 8 standalone training combinations
   - Created directories and echoed status
   - Users should run specific configurations they need

---

## Shell Scripts Kept

✅ **`prepare_data.sh`** (both examples)
- More complex data preparation logic
- Legitimately useful utility script
- Not just a command wrapper

---

## README Updates

### fedxgb/README.md

**Before:**
```bash
bash run_experiment_centralized.sh ${DATASET_ROOT}
bash run_experiment_horizontal_histogram.sh
bash run_experiment_horizontal_tree.sh
bash run_experiment_vertical.sh
```

**After (Simplified to ONE example per section):**
```bash
# Centralized baseline
python3 utils/baseline_centralized.py --num_parallel_tree 1 --data_path "${DATASET_ROOT}/HIGGS.csv"
# Modify parameters as needed

# Horizontal histogram
python3 job.py --site_num 2 --round_num 100 --split_method uniform
# Modify --site_num, --split_method as needed

# Tree-based bagging
python3 job_tree.py --site_num 5 --training_algo bagging --split_method uniform --lr_mode uniform
# Modify parameters as needed

# Tree-based cyclic
python3 job_tree.py --site_num 5 --training_algo cyclic --split_method uniform --lr_mode uniform
# Modify parameters as needed

# Vertical
python3 job_vertical.py --run_psi --run_training
```

### fedxgb_secure/README.md

**Before:**
```bash
bash run_training_standalone.sh
```

**After (Simplified to ONE federated example):**
```bash
# Baseline training
python3 ./train_standalone/train_base.py \
    --out_path /tmp/.../base_cpu \
    --gpu 0

# Federated training example (horizontal, encrypted)
python3 ./train_standalone/train_federated.py \
    --data_train_root /tmp/nvflare/dataset/xgb_dataset/horizontal_xgb_data \
    --out_path /tmp/.../hori_cpu_enc \
    --vert 0 --gpu 0 --enc 1

# Modify --vert (0=horizontal, 1=vertical), --enc (0/1), --gpu as needed
```

---

## Benefits of This Change

### 1. **Transparency**
- Users see exactly what commands are being run
- No hidden logic or assumptions
- Clear what each command does

### 2. **Flexibility**
- Users can easily modify parameters
- Run only the experiments they need
- Don't have to run entire script suites

### 3. **Better Documentation**
- README shows actual commands
- Copy-paste friendly
- Self-documenting examples

### 4. **Easier Debugging**
- See exact command that failed
- No need to look inside shell scripts
- Direct feedback from Python

### 5. **Cross-Platform**
- Python commands work everywhere
- No bash/shell script dependencies
- Better for Windows users

---

## Files Modified

### Deleted (6 files):
- ❌ `examples/advanced/xgboost/fedxgb/run_experiment_vertical.sh`
- ❌ `examples/advanced/xgboost/fedxgb/run_experiment_centralized.sh`
- ❌ `examples/advanced/xgboost/fedxgb/run_experiment_horizontal_histogram.sh`
- ❌ `examples/advanced/xgboost/fedxgb/run_experiment_horizontal_tree.sh`
- ❌ `examples/advanced/xgboost/fedxgb_secure/run_experiment.sh`
- ❌ `examples/advanced/xgboost/fedxgb_secure/run_training_standalone.sh`

### Updated (2 files):
- ✅ `examples/advanced/xgboost/fedxgb/README.md` - Updated 4 sections
- ✅ `examples/advanced/xgboost/fedxgb_secure/README.md` - Updated 1 section

---

## User Experience

### Before:
```bash
# What does this do? 🤔
bash run_experiment_horizontal_histogram.sh

# Have to look inside script to see:
# - Which experiments run?
# - What parameters used?
# - Can I run just one?
```

### After:
```bash
# Clear what's happening ✅
python3 job.py --site_num 2 --round_num 100 --split_method uniform

# Want different config? Easy:
python3 job.py --site_num 5 --round_num 50 --split_method exponential

# Copy-paste from README, modify as needed
```

---

## Addressing Both Management Concerns

### Issue 1: "not sure we need this sh script"
✅ **Fixed:** Deleted all 6 wrapper shell scripts
✅ **Result:** Users run Python commands directly

### Issue 2: "these are different experiments, why do we need all these?"
This comment was on `run_experiment_horizontal_histogram.sh` which ran 4 experiments:
- 2 sites + histogram (V1)
- 5 sites + histogram (V1)  
- 2 sites + histogram_v2 (V2)
- 5 sites + histogram_v2 (V2)

✅ **Fixed:**
1. Script deleted
2. V1/V2 distinction removed (algorithm parameter removed from recipe)
3. README simplified to show ONE canonical example per section
4. Users can modify parameters themselves

**Before README:**
- Showed multiple variations (2 sites, 5 sites, etc.)
- Multiple experiments per section

**After README:**
- ONE example per section
- Note: "Modify parameters as needed"
- Parameters documented separately

---

## Summary

✅ **6 wrapper shell scripts deleted**  
✅ **2 READMEs updated with direct Python commands**  
✅ **Simplified to ONE example per section** (addressed "why do we need all these")  
✅ **Users run commands directly** (management preference)  
✅ **Better transparency and flexibility**  
✅ **Easier to understand and modify**  

The examples now follow the philosophy of:
1. Show exactly what command to run (no scripts)
2. Show ONE canonical example (not multiple variations)
3. Let users modify parameters themselves
