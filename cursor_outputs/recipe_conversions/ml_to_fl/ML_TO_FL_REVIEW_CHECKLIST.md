# ML-to-FL Conversion - Quick Review Checklist

**PR Branch:** `local_ytrecipePR_branch`
**Status:** Ready for merge after fixes
**Rating:** 8.5/10 → 9.5/10 (after fixes)

---

## 🔴 CRITICAL - Must Fix Before Merge

- [ ] **TensorFlow metrics bug** (`tf/client.py:71`)
  - Change `metrics={"accuracy": test_global_acc}`
  - To `metrics={"accuracy": test_acc}`
  - Impact: Wrong accuracy sent to server for model selection

---

## 🟡 HIGH PRIORITY - Should Fix Before Merge

- [ ] **Fix export method names** (2 files)
  - `pt/job.py:99`: Change `export_job()` → `export()`
  - `tf/job.py:72`: Change `export_job()` → `export()`

- [ ] **Make export paths configurable**
  - Add `--export_dir` argument to all three job.py files
  - Remove hardcoded `/tmp/nvflare/jobs/job_config`

- [ ] **Make DDP parameters configurable** (`pt/job.py`)
  - Add `--nproc_per_node` and `--master_port` arguments
  - Remove hardcoded port 7777 and nproc=2

---

## 🟢 MEDIUM PRIORITY - Nice to Have

- [ ] **Standardize print statements** across frameworks
  - Use shorter format: `"Result:"` not `"Result can be found in :"`

- [ ] **Add type hints** to all job.py files
  - `def define_parser() -> argparse.Namespace:`
  - `def main() -> None:`

- [ ] **Add input validation** to NumPy recipe
  - Add Pydantic validators for min_clients, num_rounds

---

## ✅ Testing Before Merge

### NumPy
- [ ] `python job.py` (basic)
- [ ] `python job.py --update_type diff`
- [ ] `python job.py --metrics_tracking`
- [ ] `python job.py --export_config`

### PyTorch
- [ ] `python job.py --mode pt`
- [ ] `python job.py --mode pt_ddp` (needs 2 GPUs)
- [ ] `python job.py --mode lightning`
- [ ] `python job.py --mode lightning_ddp` (needs 2 GPUs)

### TensorFlow
- [ ] `python job.py --mode tf`
- [ ] `python job.py --mode tf_multi` (needs 2 GPUs)

---

## 📊 Summary Stats

- **Lines changed:** +940 / -1670 (net -730, 43% reduction)
- **Files changed:** 36
- **Frameworks converted:** 3 (NumPy, PyTorch, TensorFlow)
- **Critical bugs:** 1 (easy fix)
- **High priority issues:** 3 (easy fixes)

---

## 🌟 Highlights

✅ Outstanding documentation improvements
✅ Excellent code consolidation
✅ Smart mode-based architecture (PyTorch)
✅ Proper Recipe pattern usage
✅ Good infrastructure enhancements

---

## 📝 Next Steps

1. Fix critical TensorFlow bug
2. Fix export method names
3. Run all tests
4. Update RECIPE_CONVERSION_INVENTORY.md
5. Merge to main

---

**See ML_TO_FL_CONVERSION_REVIEW.md for detailed analysis**
