# NVFlare Recipe Conversion Status Tracker

**Last Updated**: December 12, 2025
**Quick Status**: 14/43 Examples Converted (33%) | 7 Recipes Created | 9 Recipes Needed

---

## 📊 Progress Overview

```
Overall Progress: [████████░░░░░░░░░░░░░░░░░░░░] 33%

✅ Completed (Recipe API):     14 examples  (33%)
⚙️  Needs Recipe Creation:     22 examples  (51%)
❌ Legacy JSON (High Priority):  7 examples  (16%)

Total Tracked:                 43 examples  (100%)
```

---

## 🎯 Completion by Category

| Category | Total | ✅ Done | ⚙️ Needs Recipe | ❌ Legacy | Progress |
|----------|-------|---------|----------------|-----------|----------|
| **Hello World** | 9 | 8 | 1 | 0 | ████████████████████░░ 89% |
| **Sklearn** | 3 | 3 | 0 | 0 | ██████████████████████ 100% ⭐ |
| **XGBoost** | 4 | 1 | 3 | 0 | █████░░░░░░░░░░░░░░░░░ 25% |
| **Computer Vision** | 6 | 0 | 2 | 4 | ░░░░░░░░░░░░░░░░░░░░░░ 0% |
| **NLP** | 2 | 0 | 2 | 0 | ░░░░░░░░░░░░░░░░░░░░░░ 0% |
| **Statistics** | 6 | 2 | 4 | 0 | ███████░░░░░░░░░░░░░░░ 33% |
| **Specialized** | 13 | 0 | 10 | 3 | ░░░░░░░░░░░░░░░░░░░░░░ 0% |

---

## ✅ COMPLETED - Recipe API (14 examples)

### Hello World Examples (8/9) ⭐ 89%

| Example | Recipe | Location |
|---------|--------|----------|
| hello-pt | `FedAvgRecipe` | `examples/hello-world/hello-pt/job.py` |
| hello-tf | `FedAvgRecipe` | `examples/hello-world/hello-tf/job.py` |
| hello-numpy | `FedAvgRecipe` | `examples/hello-world/hello-numpy/job.py` |
| hello-lightning | `FedAvgRecipe` | `examples/hello-world/hello-lightning/job.py` |
| hello-cyclic | `CyclicRecipe` | `examples/hello-world/hello-cyclic/job.py` |
| hello-lr | `FedAvgLrRecipe` | `examples/hello-world/hello-lr/job.py` |
| hello-flower | `FlowerRecipe` | `examples/hello-world/hello-flower/job.py` |
| hello-tabular-stats | `FedStatsRecipe` | `examples/hello-world/hello-tabular-stats/job.py` |

### Sklearn Examples (3/3) ⭐ 100%

| Example | Recipe | Location |
|---------|--------|----------|
| sklearn-linear | `SklearnFedAvgRecipe` | `examples/advanced/sklearn-linear/job.py` |
| sklearn-kmeans | `KMeansFedAvgRecipe` | `examples/advanced/sklearn-kmeans/job.py` |
| sklearn-svm | `SVMFedAvgRecipe` | `examples/advanced/sklearn-svm/job.py` |

### XGBoost Examples (1/4) - 25%

| Example | Recipe | Location |
|---------|--------|----------|
| random_forest | `XGBBaggingRecipe` | `examples/advanced/random_forest/job.py` |

### Statistics Examples (2/6) - 33%

| Example | Recipe | Location |
|---------|--------|----------|
| federated-statistics/image_stats | `StatisticsRecipe` | `examples/advanced/federated-statistics/image_stats/job.py` |
| federated-statistics/df_stats | `StatisticsRecipe` | `examples/advanced/federated-statistics/df_stats/job.py` |

---

## 🔄 IN PROGRESS - Needs Recipe Creation (29 examples)

These use `FedJob` API and need dedicated recipes.

### 🔴 HIGH PRIORITY (12 examples)

#### Hello World - Nearly Complete! (1 example)
| Example | Current | Recipe Needed | Effort | Impact |
|---------|---------|---------------|--------|--------|
| hello-numpy-cross-val | FedJob + CrossSiteModelEval | `CrossSiteEvalRecipe` | Low | High - Completes hello-world 100% |

#### Computer Vision - Most Popular! (2 examples)
| Example | Current | Recipe Needed | Effort | Impact |
|---------|---------|---------------|--------|--------|
| cifar10/tf | FedJob + ScriptRunner | `TFFedAvgRecipe` (enhance existing) | Low | High - TF users |
| hello-pt-resnet | FedJob + ScriptRunner | `FedAvgRecipe` (already exists!) | Low | Medium - Just refactor |

#### XGBoost - Tabular ML (3 examples)
| Example | Current | Recipe Needed | Effort | Impact |
|---------|---------|---------------|--------|--------|
| xgboost/fedxgb (horizontal) | FedJob + FedXGBHistogramExecutor | `XGBHistogramRecipe` | High | High - Popular for tabular |
| xgboost/fedxgb (vertical) | FedJob + VerticalXGBExecutor | `XGBVerticalRecipe` | High | High - Unique capability |
| xgboost/fedxgb_secure | FedJob + HE | `XGBVerticalRecipe` + HE | High | Medium - Specialized |

#### NLP - Transformers (2 examples)
| Example | Current | Recipe Needed | Effort | Impact |
|---------|---------|---------------|--------|--------|
| nlp-ner | FedJob + PTModel + ScriptRunner | `TransformerRecipe` | Medium | High - BERT/GPT users |
| llm_hf | Custom LLMRecipe | Standardize `HFRecipe` | Low | High - LLM fine-tuning |

#### Finance (1 example)
| Example | Current | Recipe Needed | Effort | Impact |
|---------|---------|---------------|--------|--------|
| finance | FedJob + XGBoost | `XGBHistogramRecipe` (reuse) | Low | Medium - Fraud detection |

#### Statistics (3 examples)
| Example | Current | Recipe Needed | Effort | Impact |
|---------|---------|---------------|--------|--------|
| federated-statistics/hierarchical_stats | Manual components | Enhance `StatisticsRecipe` | Medium | Medium - Multi-tier |
| kaplan-meier-he | FedJob + custom KM workflow | `SurvivalAnalysisRecipe` | High | Low - Specialized |
| lr-newton-raphson | FedJob + custom workflow | `NewtonRaphsonRecipe` | Medium | Low - Research |

### 🟡 MEDIUM PRIORITY (7 examples)

#### Specialized Examples
| Example | Current | Recipe Needed | Effort | Impact |
|---------|---------|---------------|--------|--------|
| gnn | Custom controllers | `GNNRecipe` | High | Medium - Graph ML growing |
| amplify | Custom multi-task | `MultiTaskRecipe` | High | Medium - Research |
| bionemo | BioNeMo integration | Keep FedJob | N/A | Low - Highly specialized |
| rag/embedding | FedJob + custom | `EmbeddingRecipe` | Medium | Low - Niche |
| swarm_learning | Custom decentralized | `SwarmRecipe` | High | Low - Research |
| streaming | Custom streaming | Keep FedJob | N/A | Low - Infrastructure |
| vertical_federated_learning | VFL components | `VFLRecipe` | High | Medium - Unique paradigm |

### 🟢 LOW PRIORITY (10 examples)

#### Distributed Optimization
| Example | Current | Recipe Needed | Effort | Impact |
|---------|---------|---------------|--------|--------|
| distributed_optimization/1-consensus | Notebook-based | `ConsensusRecipe` | Medium | Low - Research |
| distributed_optimization/2-two_moons | Python scripts | `ConsensusRecipe` | Medium | Low - Research |
| distributed_optimization/3-mnist | Python scripts | `ConsensusRecipe` | Medium | Low - Research |

#### Other Specialized (Can Stay FedJob)
| Example | Type | Recommendation |
|---------|------|----------------|
| edge/jobs | Edge deployment | Keep FedJob - Infrastructure |
| experiment-tracking/mlflow | MLflow integration | N/A - Utility |
| experiment-tracking/tensorboard | TensorBoard | N/A - Utility |
| experiment-tracking/wandb | Wandb integration | N/A - Utility |
| hello-pt-resnet | ResNet demo | Refactor to use `FedAvgRecipe` |
| finance-end-to-end | End-to-end demo | Keep FedJob - Demo format |
| tensor-stream | Tensor streaming | Already has recipe? (verify) |

---

## ❌ LEGACY JSON - Needs Immediate Conversion (7 examples)

These still use old config files - highest priority for modernization!

### Computer Vision (4 examples) 🔥
| Example | Current Config | Recipe Needed | Algorithms | Priority |
|---------|---------------|---------------|------------|----------|
| **cifar10/cifar10-sim** | JSON configs | `FedAvgRecipe`, `FedOptRecipe`, `FedProxRecipe`, `ScaffoldRecipe` | FedAvg, FedOpt, FedProx, SCAFFOLD | 🔥 CRITICAL |
| **cifar10/cifar10-real-world** | JSON configs | `FedAvgRecipe` + HE | FedAvg + HE, TensorBoard | 🔥 HIGH |
| **brats18** | JSON configs | `FedAvgRecipe` + medical utils | Medical imaging (3D) | 🔥 HIGH |
| **prostate** | JSON configs | `FedAvgRecipe` + medical utils | Medical imaging (2D/3D) | 🔥 HIGH |

### Specialized (3 examples)
| Example | Current Config | Recipe Needed | Type | Priority |
|---------|---------------|---------------|------|----------|
| federated-policies | Policy JSON | N/A - Keep as infrastructure | Policy framework | Low |
| job-level-authorization | Auth JSON | N/A - Keep as infrastructure | Authorization | Low |
| monitoring | Config YAML | N/A - Keep as infrastructure | Monitoring | Low |

**Note**: 3 specialized examples are infrastructure and don't need recipe conversion.

---

## 📋 Action Plan - Prioritized

### Phase 1: Quick Wins (1-2 weeks) ⚡

| # | Task | Effort | Impact | Notes |
|---|------|--------|--------|-------|
| 1 | Create `CrossSiteEvalRecipe` | Low | High | Completes hello-world 100% |
| 2 | Refactor hello-pt-resnet to use `FedAvgRecipe` | Low | Medium | Recipe already exists |
| 3 | Convert cifar10-sim to `FedAvgRecipe` | Low | Critical | Start with basic FedAvg |
| 4 | Enhance TF `FedAvgRecipe` for cifar10/tf | Low | High | TensorFlow users |

**Expected**: 4 examples converted, hello-world at 100%

### Phase 2: Core Algorithms (3-4 weeks) 🎯

| # | Task | Effort | Impact | Notes |
|---|------|--------|--------|-------|
| 5 | Create `FedOptRecipe` | Medium | High | For cifar10-sim FedOpt variant |
| 6 | Create `FedProxRecipe` | Medium | High | For cifar10-sim FedProx variant |
| 7 | Create `ScaffoldRecipe` | High | High | For cifar10-sim SCAFFOLD variant |
| 8 | Create `XGBHistogramRecipe` | High | High | For XGBoost horizontal + finance |
| 9 | Convert cifar10-real-world to recipes | Medium | High | FedAvg + HE |

**Expected**: 8+ examples converted, popular algorithms covered

### Phase 3: Medical & NLP (4-6 weeks) 🏥

| # | Task | Effort | Impact | Notes |
|---|------|--------|--------|-------|
| 10 | Create `TransformerRecipe` | Medium | High | For NLP-NER |
| 11 | Standardize `HFRecipe` for llm_hf | Low | High | Already has recipe |
| 12 | Convert brats18 to `FedAvgRecipe` | Medium | High | Medical imaging |
| 13 | Convert prostate to `FedAvgRecipe` | Medium | High | Medical imaging |
| 14 | Create medical imaging utilities | Medium | High | Shared across medical |

**Expected**: Medical and NLP examples fully converted

### Phase 4: Specialized (6-8 weeks) 🔬

| # | Task | Effort | Impact | Notes |
|---|------|--------|--------|-------|
| 15 | Create `XGBVerticalRecipe` | High | Medium | Vertical XGBoost |
| 16 | Create `GNNRecipe` | High | Medium | Graph neural networks |
| 17 | Create `MultiTaskRecipe` | High | Medium | For amplify |
| 18 | Enhance `StatisticsRecipe` | Medium | Medium | Hierarchical stats |
| 19 | Convert remaining specialized examples | High | Low | As needed |

**Expected**: Most specialized examples converted

---

## 🎯 Recipe Creation Checklist

### Recipes to Create (Priority Order)

#### Immediate (Week 1-2)
- [ ] `CrossSiteEvalRecipe` - For hello-numpy-cross-val
  - Wraps training + CSE workflow
  - Reuses existing `CrossSiteModelEval` component
  - **Effort**: 2-3 days

#### High Priority (Week 3-6)
- [ ] `FedOptRecipe` - For cifar10 FedOpt algorithm
  - Federated Adam/Yogi/Adagrad optimizers
  - **Effort**: 1-2 weeks

- [ ] `FedProxRecipe` - For cifar10 FedProx algorithm
  - Adds proximal term to FedAvg
  - **Effort**: 1 week

- [ ] `ScaffoldRecipe` - For cifar10 SCAFFOLD algorithm
  - Control variates for variance reduction
  - **Effort**: 2 weeks (complex)

- [ ] `XGBHistogramRecipe` - For horizontal XGBoost
  - Histogram-based federated XGBoost
  - Reusable for finance example
  - **Effort**: 2-3 weeks

#### Medium Priority (Week 7-10)
- [ ] `TransformerRecipe` - For NLP examples
  - Generic BERT/GPT/transformer support
  - Model loading, tokenization
  - **Effort**: 2 weeks

- [ ] `XGBVerticalRecipe` - For vertical XGBoost
  - Vertical federated learning
  - Split learning integration
  - **Effort**: 3 weeks

- [ ] `HFRecipe` (standardize) - For LLM fine-tuning
  - Refactor existing llm_hf custom recipe
  - **Effort**: 1 week

#### Lower Priority (Week 11+)
- [ ] `GNNRecipe` - For graph neural networks
- [ ] `MultiTaskRecipe` - For multi-task learning
- [ ] `ConsensusRecipe` - For distributed optimization
- [ ] `SurvivalAnalysisRecipe` - For Kaplan-Meier
- [ ] `VFLRecipe` - For vertical federated learning

### Recipes to Enhance
- [ ] `FedAvgRecipe` (PyTorch) - Add medical imaging utilities
- [ ] `FedAvgRecipe` (TensorFlow) - Enhance for CIFAR-10
- [ ] `StatisticsRecipe` - Add hierarchical statistics support

---

## 🚧 Blockers & Dependencies

### Current Blockers
1. **CIFAR-10 Multi-Algorithm**: Need FedOpt, FedProx, SCAFFOLD recipes before full conversion
2. **Medical Imaging**: Need shared utilities (metrics, data loaders) before brats18/prostate
3. **XGBoost Horizontal**: Need histogram recipe design before fedxgb conversion
4. **Vertical XGBoost**: Need vertical recipe design and secure aggregation

### Dependencies
- `CrossSiteEvalRecipe` → No blockers (can start immediately)
- `FedOptRecipe` → Depends on PyTorch FedAvg recipe patterns
- `XGBHistogramRecipe` → Depends on XGBoost executor understanding
- `TransformerRecipe` → Depends on model loading patterns

---

## 📈 Metrics & Targets

### Current State (Dec 12, 2025)
- ✅ Examples converted: 14/43 (33%)
- 🎯 Recipes created: 7
- 📝 Examples tested: 4 (sklearn + random_forest)

### Q1 2025 Target (End of March)
- 🎯 Examples converted: 28/43 (65%)
- 🎯 Recipes created: 12
- 🎯 High priority complete: CIFAR-10, XGBoost, hello-world 100%

### Q2 2025 Target (End of June)
- 🎯 Examples converted: 37/43 (85%)
- 🎯 Recipes created: 15
- 🎯 Legacy JSON eliminated: All moved to Recipe or FedJob

### Progress Tracking

```
Week 1-2:   [✅] CrossSiteEvalRecipe, hello-world 100%, cifar10 basic
Week 3-4:   [  ] FedOpt, FedProx recipes
Week 5-6:   [  ] SCAFFOLD, XGBHistogram recipes
Week 7-8:   [  ] Medical imaging conversion
Week 9-10:  [  ] NLP conversion (Transformer recipe)
Week 11-12: [  ] Specialized examples
```

---

## 📊 Success Criteria

### Example is "Converted" When:
- ✅ Uses Recipe API (not FedJob manual config)
- ✅ Has `job.py` with recipe instantiation
- ✅ README updated with recipe usage
- ✅ Tests added for recipe configuration
- ✅ No legacy JSON config files

### Recipe is "Complete" When:
- ✅ Recipe class implemented in `nvflare/app_opt/`
- ✅ Unit tests pass
- ✅ Integration tests pass
- ✅ Documentation written
- ✅ At least one example uses it successfully

---

## 🔍 Quick Reference

### By Status
- **✅ Completed (14)**: See "COMPLETED" section above
- **⚙️ Needs Recipe (29)**: See "IN PROGRESS" section above
- **❌ Legacy JSON (7)**: 4 CV examples + 3 infrastructure (keep as-is)

### By Priority
- **🔴 High (12)**: Cross-val, CIFAR-10, XGBoost, NLP, Finance
- **🟡 Medium (7)**: GNN, Specialized examples
- **🟢 Low (10)**: Distributed optimization, Infrastructure

### By Category
- **Hello World**: 8/9 done (89%) - 1 remaining
- **Sklearn**: 3/3 done (100%) ⭐
- **XGBoost**: 1/4 done (25%) - 3 remaining
- **Computer Vision**: 0/6 done (0%) - 6 remaining 🔥
- **NLP**: 0/2 done (0%) - 2 remaining
- **Statistics**: 2/6 done (33%) - 4 remaining
- **Specialized**: 0/13 done (0%) - 13 remaining

---

## 📁 File Locations

### Inventory Documents
- This tracker: `cursor_outputs/recipe_conversions/inventory/20251212_recipe_conversion_status_tracker.md`
- Original inventory: `cursor_outputs/recipe_conversions/inventory/20251203_recipe_conversion_inventory_all_examples.md`
- Hello-world focus: `cursor_outputs/recipe_conversions/inventory/20251212_hello_world_recipe_status.md`
- Index: `cursor_outputs/recipe_conversions/inventory/README.md`

### Example Locations
- Hello-world: `examples/hello-world/*/job.py`
- Advanced: `examples/advanced/*/job.py`
- Tests: `tests/unit_test/app_opt/*/test_*.py`

---

**Maintained By**: NVFlare Team
**Next Review**: December 19, 2025 (weekly)
**Contact**: Recipe conversion working group
