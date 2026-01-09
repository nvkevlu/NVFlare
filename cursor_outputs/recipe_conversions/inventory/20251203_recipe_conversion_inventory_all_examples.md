# NVFlare Example Recipe Conversion Inventory

This document tracks the progress of converting examples from legacy config-based approaches to the modern **Job Recipe API**.

## Legend

- ✅ **Recipe API**: Fully converted to Job Recipe API (e.g., `FedAvgRecipe`, `XGBBaggingRecipe`)
- ⚙️ **FedJob API**: Uses `FedJob` with manual component configuration (intermediate API)
- ❌ **Legacy JSON**: Uses old config files (`config_fed_server.json`, `config_fed_client.json`)
- 🔄 **Hybrid**: Contains both recipe and legacy approaches
- 🚫 **N/A**: Infrastructure/utility example, not applicable for recipe conversion

---

## Hello World Examples

| Example | Framework | Status | File | Notes |
|---------|-----------|--------|------|-------|
| hello-pt | PyTorch | ✅ | `job.py` | Uses `FedAvgRecipe` |
| hello-tf | TensorFlow | ✅ | `job.py` | Uses `FedAvgRecipe` |
| hello-numpy | NumPy | ✅ | `job.py` | Uses `FedAvgRecipe` |
| hello-lightning | PyTorch Lightning | ✅ | `job.py` | Uses `FedAvgRecipe` |
| hello-cyclic | PyTorch | ✅ | `job.py` | Uses `CyclicRecipe` |
| hello-flower | Flower | ⚙️ | `job.py` | Uses `FedJob`, specialized for Flower integration |
| hello-numpy-cross-val | NumPy | ⚙️ | `job.py` | Uses `FedJob` with CrossSiteModelEval |
| hello-lr | NumPy | ⚙️ | `job.py` | Uses `FedJob` with FedAvg workflow |

**Summary**: 5/8 converted to Recipe API (62.5%)

---

## Advanced Examples - Machine Learning

### Sklearn Examples
| Example | Algorithm | Status | File | Notes |
|---------|-----------|--------|------|-------|
| sklearn-linear | Logistic Regression | ✅ | `job.py` | Uses `SklearnFedAvgRecipe` - **CONVERTED** |
| sklearn-kmeans | K-Means Clustering | ✅ | `job.py` | Uses `KMeansFedAvgRecipe` - **CONVERTED** |
| sklearn-svm | SVM | ✅ | `job.py` | Uses `SVMFedAvgRecipe` - **CONVERTED** |

**Summary**: 3/3 converted to Recipe API (100%) ✨

### XGBoost Examples
| Example | Algorithm | Status | File | Notes |
|---------|-----------|--------|------|-------|
| random_forest | Random Forest (Bagging) | ✅ | `job.py` | Uses `XGBBaggingRecipe` - **CONVERTED** |
| xgboost/fedxgb | Horizontal/Vertical XGB | ⚙️ | `xgb_fl_job_*.py` | Uses `FedJob` with XGB executors |
| xgboost/fedxgb_secure | Secure Vertical XGB | ⚙️ | `xgb_fl_job.py` | Uses `FedJob` with secure aggregation |
| finance | Credit Card Fraud | ⚙️ | `jobs/*_base` | Uses `FedJob` with XGBoost |

**Summary**: 1/4 converted to Recipe API (25%)
**Priority**: Create `XGBHistogramRecipe` and `XGBVerticalRecipe`

---

## Advanced Examples - Deep Learning

### Computer Vision
| Example | Framework | Status | File | Notes |
|---------|-----------|--------|------|-------|
| cifar10/cifar10-sim | PyTorch | ❌ | `jobs/*/config/*.json` | Multiple algorithms (FedAvg, FedOpt, FedProx, SCAFFOLD) |
| cifar10/cifar10-real-world | PyTorch | ❌ | `jobs/*/config/*.json` | FedAvg + HE, streaming TensorBoard |
| cifar10/tf | TensorFlow | ⚙️ | `tf_fl_script_runner_cifar10.py` | Uses `FedJob` API |
| brats18 | Medical Imaging | ❌ | `configs/*.json` | Brain tumor segmentation |
| prostate | Medical Imaging | ❌ | `prostate_2D/jobs/*/config/*.json` | Prostate segmentation |
| hello-pt-resnet | PyTorch ResNet | ⚙️ | `fedavg_script_runner_pt.py` | Uses `FedJob` API |

**Summary**: 0/6 converted to Recipe API (0%)
**Priority High**: CIFAR-10 with multiple algorithm recipes

### Natural Language Processing
| Example | Framework | Status | File | Notes |
|---------|-----------|--------|------|-------|
| nlp-ner | PyTorch (Transformers) | ⚙️ | `nlp_fl_job.py` | Named Entity Recognition with BERT/GPT |
| llm_hf | HuggingFace | 🔄 | `job.py` | Custom recipe (`LLMRecipe`), needs standardization |

**Summary**: 0/2 converted to Recipe API (0%)
**Priority**: Create `TransformerRecipe` or `HFRecipe`

---

## Advanced Examples - Federated Statistics & Analytics

| Example | Type | Status | File | Notes |
|---------|------|--------|------|-------|
| federated-statistics/image_stats | Image Statistics | ✅ | `job.py` | Uses `StatisticsRecipe` |
| federated-statistics/df_stats | DataFrame Statistics | ✅ | `job.py` | Uses `StatisticsRecipe` |
| federated-statistics/hierarchical_stats | Hierarchical Stats | ⚙️ | Manual | Multi-tier statistics |
| hello-tabular-stats | Tabular Statistics | ⚙️ | Custom | Federated analytics |
| kaplan-meier-he | Survival Analysis + HE | ⚙️ | `km_job.py` | Uses `FedJob` with custom KM workflow |
| lr-newton-raphson | Newton-Raphson | ⚙️ | `lr_fl_job.py` | Custom iterative algorithm |

**Summary**: 2/6 converted to Recipe API (33%)

---

## Advanced Examples - Specialized

### Graph Neural Networks
| Example | Type | Status | File | Notes |
|---------|------|--------|------|-------|
| gnn | GNN (PyTorch Geometric) | ⚙️ | `code/*.py` | Uses custom controllers |

### Distributed Optimization
| Example | Type | Status | File | Notes |
|---------|------|--------|------|-------|
| distributed_optimization/1-consensus | Consensus | ⚙️ | Notebook | Federated consensus |
| distributed_optimization/2-two_moons | Classification | ⚙️ | Python scripts | Two moons dataset |
| distributed_optimization/3-mnist | MNIST | ⚙️ | Python scripts | Distributed MNIST |

### Other Advanced
| Example | Type | Status | File | Notes |
|---------|------|--------|------|-------|
| amplify | Multi-task Learning | ⚙️ | `run_fl_*.py` | Custom multi-task workflow |
| bionemo | Bio ML | ⚙️ | Multiple | BioNeMo integration |
| fedavg-with-early-stopping | PyTorch | ✅ | `job.py` | Uses `FedAvgRecipe` with custom stopping |
| rag/embedding | RAG Embeddings | ⚙️ | `job.py` | Retrieval-augmented generation |
| tensor-stream | Tensor Streaming | ✅ | `job.py` | Uses `TensorStreamRecipe` |
| swarm_learning | Swarm Learning | ⚙️ | `swarm_learning_job.py` | Decentralized learning |
| streaming | Data Streaming | ⚙️ | Multiple | Streaming utilities |
| vertical_federated_learning | Vertical FL | ⚙️ | Multiple | Vertical partitioning |

**Summary**: 2/13 converted to Recipe API (15%)

---

## Infrastructure & Utilities Examples

These are not ML training examples and don't need recipe conversion:

| Example | Purpose | Status |
|---------|---------|--------|
| docker | Docker setup | 🚫 N/A |
| cc_provision | Confidential Computing | 🚫 N/A |
| custom_authentication | Auth setup | 🚫 N/A |
| keycloak-site-authentication | Keycloak integration | 🚫 N/A |
| federated-policies | Policy framework | 🚫 N/A |
| job-level-authorization | Authorization | 🚫 N/A |
| monitoring | System monitoring | 🚫 N/A |
| fl_hub | FL Hub | 🚫 N/A |
| edge | Edge deployment | ⚙️ Partial |
| experiment-tracking | MLflow/Wandb/TB | 🚫 N/A |
| psi | Private Set Intersection | 🚫 N/A |
| code-pre-install | Code installation | 🚫 N/A |
| hello-ccwf | Client-Controlled WF | 🚫 N/A |
| finance-end-to-end | End-to-end demo | ⚙️ Mixed |

---

## Overall Summary

### By Status
| Status | Count | Percentage |
|--------|-------|------------|
| ✅ Recipe API | **13** | 30% |
| ⚙️ FedJob API | **23** | 53% |
| ❌ Legacy JSON | **7** | 16% |
| **Total (ML Examples)** | **43** | 100% |

### By Framework/Category
| Category | Total | Recipe ✅ | FedJob ⚙️ | Legacy ❌ | % Converted |
|----------|-------|-----------|-----------|-----------|-------------|
| **Hello World** | 8 | 5 | 3 | 0 | 62.5% |
| **Sklearn** | 3 | 3 | 0 | 0 | **100%** ✨ |
| **XGBoost** | 4 | 1 | 3 | 0 | 25% |
| **Computer Vision** | 6 | 0 | 2 | 4 | 0% |
| **NLP** | 2 | 0 | 2 | 0 | 0% |
| **Statistics** | 6 | 2 | 4 | 0 | 33% |
| **Specialized** | 14 | 2 | 12 | 0 | 14% |

---

## Conversion Priority Roadmap

### 🔴 High Priority (High Impact, Frequently Used)

1. **CIFAR-10 Examples** (cifar10-sim, cifar10-real-world)
   - Create `FedAvgRecipe`, `FedOptRecipe`, `FedProxRecipe`, `ScaffoldRecipe` for PyTorch
   - Impact: Most popular CV example, demonstrates multiple algorithms
   - Complexity: Medium (need algorithm-specific recipes)

2. **XGBoost Horizontal/Vertical** (xgboost/fedxgb)
   - Create `XGBHistogramRecipe`, `XGBVerticalRecipe`
   - Impact: Popular for tabular data, demonstrates different XGB modes
   - Complexity: High (different training modes, custom aggregation)

3. **NLP-NER Example** (nlp-ner)
   - Create `TransformerRecipe` or adapt `FedAvgRecipe` for transformers
   - Impact: Popular NLP use case with BERT/GPT
   - Complexity: Medium (model loading, tokenization)

### 🟡 Medium Priority (Valuable, Moderate Usage)

4. **Medical Imaging** (brats18, prostate)
   - Create `FedAvgRecipe` variants with medical imaging utilities
   - Impact: Important healthcare use cases
   - Complexity: Medium (3D data, metrics)

5. **Distributed Optimization Examples**
   - Create specialized recipes for consensus, distributed optimization
   - Impact: Research-oriented, demonstrates advanced techniques
   - Complexity: High (custom algorithms)

6. **GNN Example**
   - Create `GNNRecipe` for graph neural networks
   - Impact: Emerging use case
   - Complexity: High (graph data structures)

### 🟢 Low Priority (Specialized, Lower Usage)

7. **LLM HuggingFace** (llm_hf)
   - Standardize existing custom recipe
   - Impact: Important but already has working recipe
   - Complexity: Low (refactor existing)

8. **Vertical FL, Swarm Learning, etc.**
   - Advanced/research examples
   - Impact: Niche use cases
   - Complexity: High (different paradigms)

---

## Recipe Gaps Analysis

### Recipes Needed (Don't Exist Yet)

1. **`FedOptRecipe`** - Federated optimizer (Adam, Yogi, Adagrad)
2. **`FedProxRecipe`** - FedProx with proximal term
3. **`ScaffoldRecipe`** - SCAFFOLD algorithm with control variates
4. **`XGBHistogramRecipe`** - XGBoost histogram-based horizontal FL
5. **`XGBVerticalRecipe`** - XGBoost vertical FL with split learning
6. **`TransformerRecipe`** - Generic transformer/BERT/GPT recipe
7. **`GNNRecipe`** - Graph neural network federated learning
8. **`ConsensusRecipe`** - Distributed consensus/optimization
9. **`MultiTaskRecipe`** - Multi-task federated learning

### Recipes Existing But Need Enhancement

1. **`FedAvgRecipe`** - Add PyTorch/TF-specific variants with better defaults
2. **`SklearnFedAvgRecipe`** - Completed ✅
3. **`StatisticsRecipe`** - Add more statistical operations
4. **`XGBBaggingRecipe`** - Completed ✅

---

## Migration Strategy

### For Each Example Conversion:

1. **Assessment**
   - Identify current approach (FedJob or Legacy JSON)
   - Determine if existing recipe fits or new recipe needed
   - Check dependencies (custom components, data loaders)

2. **Recipe Selection/Creation**
   - Use existing recipe if applicable
   - Create new recipe class if pattern is reusable
   - Keep FedJob for truly custom workflows

3. **Code Changes**
   - Create `job.py` with recipe instantiation
   - Update `README.md` with recipe usage
   - Keep old approach for backward compatibility (optional)
   - Add tests for the recipe

4. **Testing**
   - Unit tests for recipe configuration
   - Integration tests for end-to-end workflow
   - Verify results match previous approach

5. **Documentation**
   - Update example README
   - Add recipe to documentation
   - Create migration guide if breaking changes

---

## Next Steps

### Immediate Actions (Based on Your Recent Work)

1. ✅ Complete sklearn examples (linear, kmeans, svm) - **DONE**
2. ✅ Complete random_forest (XGBoost bagging) - **DONE**
3. ✅ Add comprehensive tests - **DONE**
4. 🔄 Update this inventory as examples are converted
5. 📝 Create recipe design docs for high-priority gaps

### Short-term (Next 2-4 Weeks)

1. **CIFAR-10 Recipe Conversion**
   - Start with `FedAvgRecipe` for cifar10-sim
   - Add `FedOptRecipe`, `FedProxRecipe`, `ScaffoldRecipe`
   - Convert TensorFlow version

2. **XGBoost Horizontal Recipe**
   - Create `XGBHistogramRecipe` for horizontal learning
   - Update finance example to use it

3. **NLP Recipe**
   - Create `TransformerRecipe` or enhance `FedAvgRecipe`
   - Convert nlp-ner example

### Long-term (Next Quarter)

1. Medical imaging examples (brats18, prostate)
2. Remaining specialized examples (GNN, distributed optimization)
3. Create comprehensive recipe tutorial/documentation
4. Deprecate legacy JSON-based examples

---

## Tracking Metrics

| Metric | Current | Target (Q1 2025) | Target (Q2 2025) |
|--------|---------|------------------|------------------|
| Recipe Conversion % | 30% | 60% | 85% |
| High-Priority Examples | 0/3 | 2/3 | 3/3 |
| New Recipes Created | 4 | 8 | 12 |
| Examples with Tests | 4 | 15 | 30 |

---

**Last Updated**: December 3, 2025
**Maintained By**: NVFlare Team
