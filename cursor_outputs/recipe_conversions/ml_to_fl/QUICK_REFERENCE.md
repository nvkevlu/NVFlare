# ML-to-FL Quick Reference Card

**Last Updated:** January 15, 2026

---

## 🎯 One-Sentence Summary

**The ml-to-fl Recipe conversion is 100% complete, but the examples were refactored and merged into hello-* and multi-gpu directories, leaving broken documentation links that need fixing.**

---

## ✅ What Works

| Framework | Location | Recipe | Status |
|-----------|----------|--------|--------|
| NumPy | `hello-numpy/` | NumpyFedAvgRecipe | ✅ |
| PyTorch | `hello-pt/` | FedAvgRecipe | ✅ |
| TensorFlow | `hello-tf/` | FedAvgRecipe | ✅ |
| PyTorch DDP | `multi-gpu/pt/` | FedAvgRecipe | ✅ |
| Lightning | `multi-gpu/lightning/` | FedAvgRecipe | ✅ |
| TF Multi-GPU | `multi-gpu/tf/` | FedAvgRecipe | ✅ |

---

## ❌ What Doesn't Exist

- ❌ `examples/hello-world/ml-to-fl/` directory (deleted Dec 17, 2025)
- ❌ Side-by-side ML vs FL comparison examples
- ❌ Unified multi-mode examples (split into separate examples)

---

## 🔴 What's Broken

1. **Web links** in `tutorials.astro` and `series.astro` (point to deleted directory)
2. **Review documents** reference work that was never merged
3. **Inventory documents** don't reflect refactoring
4. **No migration guide** for users looking for ml-to-fl

---

## 🔧 How to Fix (1-2 hours)

### Immediate (30 min)
```bash
# 1. Update web/src/components/tutorials.astro (lines 141-145)
# 2. Update web/src/components/series.astro (lines 182-186)
# Change links from: examples/hello-world/ml-to-fl
# Change links to:   examples/hello-world#examples-by-framework
```

### Short-term (1 hour)
```bash
# 3. Update cursor_outputs/recipe_conversions/inventory/*.txt
# 4. Add headers to ML_TO_FL_CONVERSION_REVIEW.md
# 5. Create MIGRATION_GUIDE.md
```

---

## 📍 Where Things Moved

```
ml-to-fl/np/         →  hello-numpy/
ml-to-fl/pt/         →  hello-pt/
ml-to-fl/tf/         →  hello-tf/
ml-to-fl/pt/ (DDP)   →  multi-gpu/pt/
ml-to-fl/pt/ (Light) →  multi-gpu/lightning/
ml-to-fl/tf/ (Multi) →  multi-gpu/tf/
```

---

## 📚 Document Guide

| Document | Purpose | Time |
|----------|---------|------|
| **EXECUTIVE_SUMMARY.md** | Start here | 5 min |
| **ACTION_PLAN.md** | Fix instructions | 10 min |
| **ML_TO_FL_STATUS_ANALYSIS.md** | Full details | 30 min |
| **VISUAL_SUMMARY.md** | Diagrams | 10 min |
| **QUICK_REFERENCE.md** | This card | 2 min |

---

## 🎓 Key Dates

- **Dec 8, 2025** - Conversion completed (branch)
- **Dec 11, 2025** - Code review done
- **Dec 17, 2025** - Refactored & deleted (main)
- **Jan 15, 2026** - Status clarified

---

## ❓ FAQ

**Q: Is the conversion done?**  
A: Yes, 100% complete.

**Q: Where are the examples?**  
A: hello-numpy, hello-pt, hello-tf, multi-gpu

**Q: Why are links broken?**  
A: They point to deleted ml-to-fl directory.

**Q: What needs fixing?**  
A: Documentation links and status clarity.

**Q: How long to fix?**  
A: 1-2 hours for high-priority items.

**Q: Should we restore ml-to-fl?**  
A: No (recommended). Fix docs instead.

---

## 🚨 Priority Actions

1. 🔴 Fix web links (30 min)
2. 🟡 Update inventory (15 min)
3. 🟡 Add doc headers (15 min)
4. 🟢 Create migration guide (30 min)

---

## 📊 Status at a Glance

```
Technical:       ✅✅✅✅✅ 100%
Documentation:   ⚠️⚠️⚠️░░  60%
Educational:     ⚠️⚠️░░░░  40%
Overall:         ✅⚠️⚠️░░  70%
```

---

## 🔗 Quick Links

- **Main Analysis:** [ML_TO_FL_STATUS_ANALYSIS.md](./ML_TO_FL_STATUS_ANALYSIS.md)
- **Action Plan:** [ACTION_PLAN.md](./ACTION_PLAN.md)
- **Executive Summary:** [EXECUTIVE_SUMMARY.md](./EXECUTIVE_SUMMARY.md)
- **Visual Summary:** [VISUAL_SUMMARY.md](./VISUAL_SUMMARY.md)

---

## 💡 Bottom Line

**Technically complete. Documentation needs updating. 1-2 hours to fix.**

**Start:** [EXECUTIVE_SUMMARY.md](./EXECUTIVE_SUMMARY.md) → [ACTION_PLAN.md](./ACTION_PLAN.md) → Implement fixes
