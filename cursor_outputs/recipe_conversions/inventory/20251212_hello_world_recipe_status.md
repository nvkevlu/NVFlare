# Hello World Examples - Recipe Conversion Status

**Last Updated**: December 12, 2025
**Location**: `/examples/hello-world/`

---

## ✅ Current Status: 8/9 Converted (89%) 🎉

All primary hello-world examples have been converted to use Recipe API!

---

## Detailed Breakdown

### ✅ Fully Converted to Recipe API (8 examples)

| # | Example | Framework | Recipe Used | File | Status |
|---|---------|-----------|-------------|------|--------|
| 1 | **hello-pt** | PyTorch | `FedAvgRecipe` | `job.py` | ✅ Complete |
| 2 | **hello-tf** | TensorFlow | `FedAvgRecipe` | `job.py` | ✅ Complete |
| 3 | **hello-numpy** | NumPy | `FedAvgRecipe` | `job.py` | ✅ Complete |
| 4 | **hello-lightning** | PyTorch Lightning | `FedAvgRecipe` | `job.py` | ✅ Complete |
| 5 | **hello-cyclic** | PyTorch | `CyclicRecipe` | `job.py` | ✅ Complete |
| 6 | **hello-lr** | NumPy | `FedAvgLrRecipe` | `job.py` | ✅ Complete |
| 7 | **hello-flower** | Flower | `FlowerRecipe` | `job.py` | ✅ Complete |
| 8 | **hello-tabular-stats** | Tabular Stats | `FedStatsRecipe` | `job.py` | ✅ Complete |

### ⚙️ Using FedJob API (1 example)

| # | Example | Framework | Current Approach | File | Notes |
|---|---------|-----------|------------------|------|-------|
| 9 | **hello-numpy-cross-val** | NumPy | FedJob + `CrossSiteModelEval` | `job_train_and_cse.py` | Needs `CrossSiteEvalRecipe` |

---

## Example Details

### 1. hello-pt ✅
- **Recipe**: `FedAvgRecipe` from `nvflare.app_opt.pt.recipes.fedavg`
- **Model**: SimpleNetwork (custom PyTorch model)
- **Features**: TensorBoard tracking
- **Status**: Fully converted, works perfectly

```python
recipe = FedAvgRecipe(
    name="hello-pt",
    min_clients=n_clients,
    num_rounds=num_rounds,
    initial_model=SimpleNetwork(),
    train_script="client.py",
)
```

### 2. hello-tf ✅
- **Recipe**: `FedAvgRecipe` from `nvflare.app_opt.tf.recipes.fedavg`
- **Model**: TensorFlow Keras model
- **Status**: Fully converted

### 3. hello-numpy ✅
- **Recipe**: `FedAvgRecipe` from `nvflare.app_opt.np.recipes.fedavg`
- **Model**: NumPy-based linear regression
- **Status**: Fully converted

### 4. hello-lightning ✅
- **Recipe**: `FedAvgRecipe` from `nvflare.app_opt.lightning.recipes.fedavg`
- **Model**: PyTorch Lightning LitNet
- **Features**: CIFAR-10 dataset, Lightning training
- **Status**: Fully converted

### 5. hello-cyclic ✅
- **Recipe**: `CyclicRecipe` from `nvflare.app_opt.pt.recipes.cyclic`
- **Model**: PyTorch SimpleNetwork
- **Workflow**: Cyclic weight transfer (non-aggregating)
- **Status**: Fully converted

### 6. hello-lr ✅
- **Recipe**: `FedAvgLrRecipe` from `nvflare.app_common.np.recipes.lr.fedavg`
- **Model**: Logistic regression using Newton-Raphson
- **Dataset**: Heart disease data
- **Features**: Custom damping factor
- **Status**: Fully converted

```python
recipe = FedAvgLrRecipe(
    num_rounds=num_rounds,
    damping_factor=0.8,
    num_features=13,
    train_script="client.py",
    train_args=f"--data_root {data_root}",
)
```

### 7. hello-flower ✅
- **Recipe**: `FlowerRecipe` from `nvflare.app_opt.flower.recipe`
- **Purpose**: Integrate Flower framework with NVFlare
- **Features**: TensorBoard tracking support
- **Status**: Fully converted (specialized recipe for Flower integration)

```python
recipe = FlowerRecipe(
    name=args.job_name,
    flower_content=args.content_dir,
    min_clients=num_of_clients,
)
```

### 8. hello-tabular-stats ✅
- **Recipe**: `FedStatsRecipe` from `nvflare.recipe.fedstats`
- **Purpose**: Federated statistics on tabular data (Adult dataset)
- **Statistics**: count, mean, sum, stddev, histogram, quantile
- **Status**: Fully converted

```python
recipe = FedStatsRecipe(
    sites=sites,
    stats_generator=df_stats_generator,
    statistic_configs=statistic_configs,
    output_path=output_path,
)
```

### 9. hello-numpy-cross-val ⚙️
- **Current**: Uses `FedJob` with manual component setup
- **Workflow**: `ScatterAndGather` + `CrossSiteModelEval`
- **Status**: **Needs conversion** - waiting for `CrossSiteEvalRecipe`
- **Files**: `job_train_and_cse.py`, `job_cse.py`

**Current approach:**
```python
job = FedJob(name="hello-numpy-cse", min_clients=n_clients)
persistor_id = job.to_server(NPModelPersistor())
aggregator_id = job.to_server(InTimeAccumulateWeightedAggregator(...))
controller = ScatterAndGather(...)
job.to_server(controller, id="scatter_and_gather")

# Separate CSE workflow
controller_cse = CrossSiteModelEval(...)
job.to_server(controller_cse, id="cross_site_eval")
```

**What's needed:**
- Create `CrossSiteEvalRecipe` that wraps both training and cross-site evaluation
- Or add CSE as a feature to `FedAvgRecipe`

---

## Recipes Used Summary

### Existing Recipes Utilized

1. **`FedAvgRecipe`** - Used in 4 examples (pt, tf, numpy, lightning)
   - Location: Framework-specific (e.g., `nvflare.app_opt.pt.recipes.fedavg`)
   - Purpose: Standard FedAvg algorithm
   - ✅ Works great!

2. **`CyclicRecipe`** - Used in 1 example (hello-cyclic)
   - Location: `nvflare.app_opt.pt.recipes.cyclic`
   - Purpose: Cyclic weight transfer
   - ✅ Works great!

3. **`FedAvgLrRecipe`** - Used in 1 example (hello-lr)
   - Location: `nvflare.app_common.np.recipes.lr.fedavg`
   - Purpose: Logistic regression with Newton-Raphson
   - ✅ Works great!

4. **`FlowerRecipe`** - Used in 1 example (hello-flower)
   - Location: `nvflare.app_opt.flower.recipe`
   - Purpose: Flower framework integration
   - ✅ Works great!

5. **`FedStatsRecipe`** - Used in 1 example (hello-tabular-stats)
   - Location: `nvflare.recipe.fedstats`
   - Purpose: Federated statistics computation
   - ✅ Works great!

### Missing Recipe

- **`CrossSiteEvalRecipe`** - Needed for hello-numpy-cross-val
  - Should wrap training + cross-site evaluation workflow
  - Or extend `FedAvgRecipe` with optional CSE phase

---

## What Needs to Be Done?

### 🎯 Priority: Create CrossSiteEvalRecipe

**Option 1: Standalone CrossSiteEvalRecipe**
```python
# Proposed API
recipe = CrossSiteEvalRecipe(
    name="hello-numpy-cse",
    min_clients=2,
    num_rounds=1,
    train_script="client.py",
    eval_script="client.py",  # or same script with eval mode
    model_class=NPModel,
    enable_cross_site_eval=True,
)
```

**Option 2: Enhance FedAvgRecipe**
```python
# Add CSE as optional feature
recipe = FedAvgRecipe(
    name="hello-numpy-cse",
    min_clients=2,
    num_rounds=1,
    train_script="client.py",
    enable_cross_site_eval=True,  # New parameter
    cse_eval_script="client.py",   # Optional separate eval
)
```

**Complexity**: Low-Medium
- Reuse existing `CrossSiteModelEval` workflow
- Wrap in recipe interface
- Handle model persistence and validation

**Impact**: Completes hello-world recipe conversion to 100%!

---

## Comparison with Original Inventory

The original inventory (created earlier) had **outdated information**:

| Example | Old Status | Actual Status | Correction |
|---------|------------|---------------|------------|
| hello-lr | ⚙️ FedJob | ✅ Recipe | Uses `FedAvgLrRecipe` |
| hello-flower | ⚙️ FedJob | ✅ Recipe | Uses `FlowerRecipe` |
| hello-tabular-stats | ⚙️ FedJob | ✅ Recipe | Uses `FedStatsRecipe` |
| hello-numpy-cross-val | ⚙️ FedJob | ⚙️ FedJob | ✅ Correct |

**Updated Conversion Rate**: 8/9 = **89%** (was reported as 5/8 = 62.5%)

---

## Next Steps

### Immediate Action
1. ✅ Update main inventory document with corrected hello-world status
2. 🔄 Create `CrossSiteEvalRecipe` for hello-numpy-cross-val
3. ✅ Update hello-world README with recipe examples

### Short-term
1. Add tests for all hello-world recipes
2. Create unified "hello-world recipe tutorial"
3. Document recipe patterns used across examples

### Long-term
1. Consider deprecating FedJob approach in hello examples
2. Ensure all hello-world examples have consistent structure
3. Add more recipe features (early stopping, custom metrics, etc.)

---

## File Locations

```
examples/hello-world/
├── hello-pt/job.py                    ✅ FedAvgRecipe
├── hello-tf/job.py                    ✅ FedAvgRecipe
├── hello-numpy/job.py                 ✅ FedAvgRecipe
├── hello-lightning/job.py             ✅ FedAvgRecipe
├── hello-cyclic/job.py                ✅ CyclicRecipe
├── hello-lr/job.py                    ✅ FedAvgLrRecipe
├── hello-flower/job.py                ✅ FlowerRecipe
├── hello-tabular-stats/job.py         ✅ FedStatsRecipe
└── hello-numpy-cross-val/
    ├── job_train_and_cse.py           ⚙️ Needs CrossSiteEvalRecipe
    └── job_cse.py                     ⚙️ Needs CrossSiteEvalRecipe
```

---

## Success Metrics

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Hello-world conversion % | 100% | 89% | 🟡 Nearly there! |
| Examples using Recipe API | 9 | 8 | 🟡 1 remaining |
| New recipes created | N/A | 0 | Need CrossSiteEvalRecipe |
| Examples with tests | TBD | TBD | Future work |

---

## Conclusion

The hello-world examples are in **excellent shape** with 89% recipe conversion! Only one example (hello-numpy-cross-val) needs a new `CrossSiteEvalRecipe` to reach 100%.

All the common patterns are covered:
- ✅ PyTorch, TensorFlow, NumPy, Lightning
- ✅ FedAvg, Cyclic workflows
- ✅ Logistic regression, Federated statistics
- ✅ External framework integration (Flower)
- 🔄 Cross-site evaluation (in progress)

**Recommendation**: Create `CrossSiteEvalRecipe` as the final piece to complete hello-world recipe migration!
