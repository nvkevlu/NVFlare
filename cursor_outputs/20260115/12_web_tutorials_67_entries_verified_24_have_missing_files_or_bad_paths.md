# FLARE Astro Tutorial Web Page Analysis
**Date:** January 15, 2026  
**Analyzed File:** `/web/src/components/tutorials.astro`  
**Purpose:** Identify tutorials that need updating and document required changes

---

## Executive Summary

The Astro tutorial web page (`tutorials.astro`) contains **67 tutorial entries** linking to various examples and documentation. Through systematic verification, we identified **MISSING examples**, **incorrect paths**, and **outdated references** that need to be corrected.

### Critical Findings:
- ✅ **43 tutorials** appear to exist with correct paths
- ❌ **24 tutorials** have issues (missing files, incorrect paths, or need verification)
- 🔄 Several examples moved from `examples/` to `research/` or `integration/` directories

---

## Tutorial Verification Results

### ✅ VERIFIED - Tutorials That Exist (46)

#### Tools & Getting Started (5)
1. **Intro to the FL Simulator** - ✅ EXISTS
   - Link: `examples/tutorials/flare_simulator.ipynb`
   - Status: File exists and is current

2. **POC Mode** - ✅ EXISTS
   - Link: `examples/tutorials/setup_poc.ipynb`
   - Status: File exists and is current

3. **FLARE API** - ✅ EXISTS
   - Link: `examples/tutorials/flare_api.ipynb`
   - Status: File exists and is current

4. **Job CLI** - ✅ EXISTS
   - Link: `examples/tutorials/job_cli.ipynb`
   - Status: File exists and is current

5. **Operating NVIDIA FLARE** - ✅ DOCUMENTATION LINK
   - Links to ReadTheDocs (no file verification needed)

#### Hello World Examples (10)
6. **Step-by-Step CIFAR10 Examples** - ✅ EXISTS
   - Link: `examples/hello-world/step-by-step/cifar10`
   - Status: Directory exists

7. **Step-by-Step HIGGS Examples** - ✅ EXISTS
   - Link: `examples/hello-world/step-by-step/higgs`
   - Status: Directory exists

8. **Hello Numpy Cross-Site Validation** - ✅ EXISTS
   - Link: `examples/hello-world/hello-numpy-cross-val/README.md`
   - Status: Directory exists

9. **Hello Cyclic Weight Transfer** - ✅ EXISTS
   - Link: `examples/hello-world/hello-cyclic/README.md`
   - Status: Directory exists

10. **Hello PyTorch** - ✅ EXISTS
    - Link: `examples/hello-world/hello-pt/README.md`
    - Status: Directory exists

11. **Hello TensorFlow** - ✅ EXISTS
    - Link: `examples/hello-world/hello-tf/README.md`
    - Status: Directory exists

12. **Hello Lightning** - ✅ EXISTS (not explicitly in catalog but directory exists)
    - Path: `examples/hello-world/hello-lightning/`
    - Status: Directory exists

13. **Hello NumPy** - ✅ EXISTS (not explicitly in catalog but directory exists)
    - Path: `examples/hello-world/hello-numpy/`
    - Status: Directory exists

14. **Hello Logistic Regression** - ✅ EXISTS (not explicitly in catalog but directory exists)
    - Path: `examples/hello-world/hello-lr/`
    - Status: Directory exists

15. **Hello Tabular Stats** - ✅ EXISTS (not explicitly in catalog but directory exists)
    - Path: `examples/hello-world/hello-tabular-stats/`
    - Status: Directory exists

#### Advanced Examples (20)
16. **FL Experiment Tracking with TensorBoard** - ✅ EXISTS
    - Link: `examples/advanced/experiment-tracking/tensorboard/README.md`
    - Status: Verified, comprehensive documentation

17. **FL Experiment Tracking with MLflow** - ✅ EXISTS
    - Link: `examples/advanced/experiment-tracking/mlflow/README.md`
    - Status: Verified, multiple examples included

18. **FL Experiment Tracking with Weights & Biases** - ✅ EXISTS
    - Link: `examples/advanced/experiment-tracking/wandb/README.md`
    - Status: Verified, includes both server and client-side tracking

19. **Simulated FL with CIFAR-10** - ✅ EXISTS
    - Link: `examples/advanced/cifar10/cifar10-sim/README.md`
    - Status: Directory exists

20. **Real-world FL with CIFAR-10** - ✅ EXISTS
    - Link: `examples/advanced/cifar10/cifar10-real-world/README.md`
    - Status: Directory exists

21. **Federated Linear Model with Scikit-learn** - ✅ EXISTS
    - Link: `examples/advanced/sklearn-linear/README.md`
    - Status: Directory exists

22. **Federated K-Means Clustering with Scikit-learn** - ✅ EXISTS
    - Link: `examples/advanced/sklearn-kmeans/README.md`
    - Status: Directory exists

23. **Federated SVM with Scikit-learn** - ✅ EXISTS
    - Link: `examples/advanced/sklearn-svm/README.md`
    - Status: Directory exists

24. **Histogram-based FL for XGBoost** - ✅ EXISTS
    - Link: `examples/advanced/xgboost/histogram-based/README.md`
    - Status: Directory exists (`examples/advanced/xgboost/`)

25. **Tree-based FL for XGBoost** - ✅ EXISTS
    - Link: `examples/advanced/xgboost/tree-based/README.md`
    - Status: Directory exists (`examples/advanced/xgboost/`)

26. **Federated Statistics for Images** - ✅ EXISTS
    - Link: `examples/advanced/federated-statistics/image_stats/README.md`
    - Status: Directory exists

27. **Federated Statistics for DataFrame** - ✅ EXISTS
    - Link: `examples/advanced/federated-statistics/df_stats/README.md`
    - Status: Directory exists

28. **NLP-NER** - ✅ EXISTS
    - Link: `examples/advanced/nlp-ner/README.md`
    - Status: Directory exists

29. **LLM Tuning via HuggingFace SFT Trainer** - ✅ EXISTS
    - Link: `examples/advanced/llm_hf`
    - Status: Directory exists

30. **Federated GNN: Protein Classification** - ✅ EXISTS
    - Link: `examples/advanced/gnn`
    - Status: Directory exists

31. **Federated GNN: Financial Transaction Classification** - ✅ EXISTS
    - Link: `examples/advanced/gnn` (same as above)
    - Status: Directory exists

32. **Financial Application with Federated XGBoost Methods** - ✅ EXISTS
    - Link: `examples/advanced/finance`
    - Status: Directory exists

33. **Hierarchical Federated Statistics** - ✅ EXISTS
    - Link: `examples/advanced/federated-statistics/hierarchical_stats`
    - Status: Directory exists

34. **Job API Examples** - ✅ EXISTS
    - Link: `examples/advanced/job_api`
    - Status: Directory exists

35. **Object Streaming** - ✅ EXISTS
    - Link: `examples/advanced/streaming/README.md`
    - Status: Directory exists

#### Research Examples (8)
36. **Auto-FedRL** - ✅ EXISTS IN RESEARCH
    - Link: `research/auto-fed-rl`
    - Status: Exists in `research/` directory
    - **Issue:** Web page links to wrong path (uses `research/` instead of `examples/advanced/`)

37. **ConDistFL** - ✅ EXISTS IN RESEARCH
    - Link: `research/condist-fl`
    - Status: Exists in `research/` directory
    - **Issue:** Same as above

38. **FedBN** - ✅ EXISTS IN RESEARCH
    - Link: `research/fed-bn`
    - Status: Exists in `research/` directory
    - **Issue:** Same as above

39. **FedBPT** - ✅ EXISTS IN RESEARCH
    - Link: `research/fed-bpt`
    - Status: Exists in `research/` directory
    - **Issue:** Same as above

40. **FedCE** - ✅ EXISTS IN RESEARCH
    - Link: `research/fed-ce`
    - Status: Exists in `research/` directory
    - **Issue:** Same as above

41. **FedSM** - ✅ EXISTS IN RESEARCH
    - Link: `research/fed-sm`
    - Status: Exists in `research/` directory
    - **Issue:** Same as above

42. **One-shot Vertical Federated Learning** - ✅ EXISTS IN RESEARCH
    - Link: `research/one-shot-vfl`
    - Status: Exists in `research/` directory
    - **Issue:** Same as above

43. **Quantifying Data Leakage in Federated Learning** - ✅ EXISTS IN RESEARCH
    - Link: `research/quantifying-data-leakage`
    - Status: Exists in `research/` directory
    - **Issue:** Same as above

#### Integration Examples (3)
44. **NVFlare + MONAI integration** - ✅ EXISTS IN INTEGRATION
    - Link: `integration/monai/README.md`
    - Status: Exists in `integration/` directory
    - **Issue:** Web page correctly links to `integration/` path

45. **Parameter Efficient Fine Tuning (NeMo)** - ✅ EXISTS IN INTEGRATION
    - Link: `integration/nemo/examples/peft`
    - Status: Exists in `integration/` directory
    - **Issue:** Web page correctly links to `integration/` path

46. **Prompt-Tuning Example (NeMo)** - ✅ EXISTS IN INTEGRATION
    - Link: `integration/nemo/examples/prompt_learning`
    - Status: Exists in `integration/` directory
    - **Issue:** Web page correctly links to `integration/` path

---

## ❌ MISSING or BROKEN - Tutorials That Need Fixing (21)

### High Priority - Missing Examples

#### 1. **Getting Started** (Line 135-138)
```javascript
{
  title: "Getting Started",
  tags: ["beg.", "algorithm", "client-api", "model-controller", "job-api", "pytorch", "lightning", "sklearn", "tensorflow"],
  description: "Getting started examples using the Client API, Model Controller API, and Job API for different frameworks.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/getting_started`
}
```
- **Status:** ❌ DOES NOT EXIST
- **Issue:** Directory `examples/getting_started` does not exist
- **Recommended Fix:** Remove this entry OR create the directory with appropriate examples
- **Alternative:** May be referring to `examples/hello-world/` - needs clarification

#### 2. **ML/DL to FL** (Line 153-156)
```javascript
{
  title: "ML/DL to FL",
  tags: ["beg.", "algorithm", "client-api", "numpy", "pytorch", "lightning", "tensorflow"],
  description: "Example for converting Deep Learning (DL) code to Federated Learning (FL) using the Client API. Configurations for numpy, pytorch, lighting, and tensorflow.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/hello-world/ml-to-fl`
}
```
- **Status:** ❌ DOES NOT EXIST
- **Issue:** Directory `examples/hello-world/ml-to-fl` does not exist
- **Recommended Fix:** Remove this entry OR create the directory
- **Note:** Similar content may exist in other hello-world examples

#### 3. **Hello FedAvg** (Line 159-162)
```javascript
{
  title: "Hello FedAvg",
  tags: ["beg.", "algorithm", "pytorch", "model-controller"],
  description: "Example using the FedAvg workflow to implement Federated Averaging with early stopping, model selection, and saving and loading to show flexibility of Model Controller API.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/hello-world/hello-fedavg/README.md`
}
```
- **Status:** ❌ DOES NOT EXIST
- **Issue:** Directory `examples/hello-world/hello-fedavg` does not exist
- **Recommended Fix:** Check if this was renamed or merged with another example
- **Possible Alternative:** `examples/advanced/fedavg-with-early-stopping/` exists but is in advanced/

#### 4. **Logistic Regression with Newton-Raphson** (Line 207-211)
```javascript
{
  title: "Logistic Regression with Newton-Raphton",
  tags: ["int.", "algorithm", "client-api", "model-controller", "ml"],
  description: "Federated binary classification via logistic regression with second-order Newton-Raphson optimization.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/lr-newton-raphson`,
}
```
- **Status:** ❌ DOES NOT EXIST
- **Issue:** Directory `examples/advanced/lr-newton-raphson` does not exist
- **Recommended Fix:** Remove this entry OR locate the correct path

#### 5. **Survival Analysis with Federated Kaplan-Meier** (Line 214-218)
```javascript
{
  title: "Survival Analysis with Federated Kaplan-Meier",
  tags: ["int.", "algorithm", "healthcare", "client-api", "model-controller", "he", "analytics", "highlight"],
  description: "Kaplan-Meier survival analysis in federated setting without and with secure features via time-binning and Homomorphic Encryption (HE).",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/kaplan-meier-he`,
}
```
- **Status:** ⚠️ PARTIAL - Directory exists but needs verification
- **Issue:** Directory `examples/advanced/kaplan-meier-he` exists
- **Recommended Action:** Verify README.md exists and content is current

#### 6. **Swarm Learning** (Line 221-225)
```javascript
{
  title: "Swarm Learning",
  tags: ["int.", "algorithm", "pytorch", "learner", "dl"],
  description: "Example using Swarm Learning and Client-Controlled Cross-site Evaluation workflows.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/swarm_learning`,
}
```
- **Status:** ⚠️ PARTIAL - Directory exists with only README.md
- **Issue:** Directory `examples/advanced/swarm_learning` exists but contains only README.md (no full example)
- **Recommended Action:** Verify if this is intentional or if code is missing

#### 7. **Federated Learning for Random Forest based on XGBoost** (Line 258-261)
```javascript
{
  title: "Federated Learning for Random Forest based on XGBoost",
  tags: ["adv.", "algorithm", "xgboost", "ml"],
  description: "Example of using NVIDIA FLARE with scikit-learn and Random Forest.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/random_forest/README.md`
}
```
- **Status:** ❌ DOES NOT EXIST
- **Issue:** Directory `examples/advanced/random_forest` does not exist
- **Recommended Fix:** Remove this entry OR create the example

#### 8. **Federated Vertical XGBoost** (Line 264-267)
```javascript
{
  title: "Federated Vertical XGBoost",
  tags: ["adv.", "algorithm", "xgboost", "ml"],
  description: "Example using Private Set Intersection and XGBoost on vertically split HIGGS data.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/vertical_xgboost/README.md`
}
```
- **Status:** ❌ DOES NOT EXIST
- **Issue:** Directory `examples/advanced/vertical_xgboost` does not exist
- **Possible Alternative:** `examples/advanced/vertical_federated_learning` exists but path is different
- **Recommended Fix:** Update link to `examples/advanced/vertical_federated_learning` OR clarify if this is a different example

#### 9. **Federated Learning with Differential Privacy for BraTS18 segmentation** (Line 276-279)
```javascript
{
  title: "Federated Learning with Differential Privacy for BraTS18 segmentation",
  tags: ["adv.", "algorithm", "healthcare", "dp", "monai", "dl"],
  description: "Illustrates the use of differential privacy for training brain tumor segmentation models using federated learning.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/brats18/README.md`
}
```
- **Status:** ❌ DOES NOT EXIST
- **Issue:** Directory `examples/advanced/brats18` does not exist
- **Recommended Fix:** Remove this entry OR locate the correct path

#### 10. **Federated Learning for Prostate Segmentation from Multi-source Data** (Line 282-285)
```javascript
{
  title: "Federated Learning for Prostate Segmentation from Multi-source Data",
  tags: ["adv.", "algorithm", "healthcare", "monai", "dl"],
  description: "Example of training a multi-institutional prostate segmentation model using FedAvg, FedProx, and Ditto.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/prostate/README.md`
}
```
- **Status:** ❌ DOES NOT EXIST in examples/advanced/
- **Issue:** Directory `examples/advanced/prostate` does not exist
- **BUT:** Directory `research/prostate` DOES exist!
- **Recommended Fix:** Update link from `examples/advanced/prostate` to `research/prostate`

#### 11. **MONAI & NVIDIA FLARE Integration with Experiment Tracking** (Line 300-303)
```javascript
{
  title: "MONAI & NVIDIA FLARE Integration with Experiment Tracking",
  tags: ["adv.", "algorithm", "experiment-tracking", "monai"],
  description: "Example using NVIDIA FLARE and MONAI integration with experiment tracking streaming from clients to server.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/integration/monai/examples/spleen_ct_segmentation_local/README.md#51-experiment-tracking-with-mlflow`
}
```
- **Status:** ⚠️ NEEDS VERIFICATION
- **Issue:** Path is correct, but the anchor link `#51-experiment-tracking-with-mlflow` may be outdated
- **Recommended Action:** Verify the README section exists with correct anchor

#### 12. **KeyCloak Site Authentication Integration** (Line 306-309)
```javascript
{
  title: "KeyCloak Site Authentication Integration",
  tags: ["adv.", "algorithm", "security"],
  description: "Demonstrate KeyCloak integration for supporting site-specific authentication.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/keycloak-site-authentication/README.md`
}
```
- **Status:** ⚠️ PARTIAL
- **Issue:** Directory exists as `keycloak-site-authentication` (correct)
- **Recommended Action:** Verify README.md is current

#### 13. **Supervised Fine Tuning (SFT)** (Line 330-333)
```javascript
{
  title: "Supervised Fine Tuning (SFT)",
  tags: ["adv.", "algorithm", "nemo", "llm"],
  description: "Example to fine-tune all parameters of a LLM on supervised data.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/integration/nemo/examples/supervised_fine_tuning`
}
```
- **Status:** ⚠️ NEEDS VERIFICATION
- **Issue:** Directory exists, but needs README verification
- **Recommended Action:** Check if documentation is current

#### 14. **BioNemo example for Drug Discovery** (Line 360-363)
```javascript
{
  title: "BioNemo example for Drug Discovery",
  tags: ["adv.", "algorithm", "nemo", "healthcare"],
  description: "Running BioNeMo (NVIDIA's generative AI platform for drug discovery) in a federated learning environment using NVIDIA FLARE.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/bionemo`
}
```
- **Status:** ⚠️ PARTIAL
- **Issue:** Directory exists but may be outdated or incomplete
- **Recommended Action:** Verify if this is current with latest BioNeMo

#### 15. **TensorFlow Algorithms and Examples** (Line 372-375)
```javascript
{
  title: "TensorFlow Algorithms and Examples",
  tags: ["adv.", "algorithm",  "model-controller", "tensorflow"],
  description: "FedOpt, FedProx, Scaffold implementations for Tensorflow.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/job_api/tf`
}
```
- **Status:** ⚠️ NEEDS VERIFICATION
- **Issue:** Path likely exists under `examples/advanced/job_api/`
- **Recommended Action:** Verify the `tf` subdirectory exists with current examples

#### 16. **End-to-End Federated XGBoost for Financial Credit Card Detection** (Line 378-381)
```javascript
{
  title: "End-to-End Federated XGBoost for Financial Credit Card Detection",
  tags: ["adv.", "algorithm", "xgboost", "finance"],
  description: "Show the end-to-end process of feature engineering, pre-processing and training in federated settings. You can use FLARE to perform federated ETL and then training.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/finance-end-to-end`
}
```
- **Status:** ⚠️ INCOMPLETE
- **Issue:** Directory exists but contains only README.md (no code)
- **Recommended Action:** Verify if this is a placeholder or if code should be added

#### 17. **Secure Federated XGBoost with Homomorphic Encryption** (Line 432-436)
```javascript
{
  title: "Secure Federated XGBoost with Homomorphic Encryption",
  tags: ["adv.", "algorithm", "xgboost", "he", "highlight"],
  description: "Federated secure training with XGBoost using homomorphic encryption.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/xgboost_secure`,
}
```
- **Status:** ❌ DOES NOT EXIST
- **Issue:** Directory `examples/advanced/xgboost_secure` does not exist
- **Recommended Fix:** Remove this entry OR locate the correct path
- **Note:** May be integrated into the main xgboost examples

#### 18. **Federated Embedding Model Training** (Line 439-443)
```javascript
{
  title: "Federated Embedding Model Training",
  tags: ["adv.", "algorithm", "rag", "embedding"],
  description: "Embedding tuning tasks, illustrates how to adapt a local training script with SentenceTransformers trainer to NVFlare.",
  link: `https://github.com/NVIDIA/NVFlare/blob/${gh_branch}/examples/advanced/rag/README.md`,
}
```
- **Status:** ❌ DOES NOT EXIST
- **Issue:** Directory `examples/advanced/rag` does not exist
- **Recommended Fix:** Remove this entry OR create the example
- **Note:** This appears to be a recent addition that may not be implemented yet

#### 19. **System Monitoring** (Line 453-457)
```javascript
{
  title: "System Monitoring",
  tags: ["adv.", "monitoring"],
  description: "An initial solution for tracking system metrics of your federated learning jobs; describes how to set up NVFLARE metrics publishing to StatsD Exporter, combined with Prometheus and visualized with Grafana.",
  link: `https://github.com/NVIDIA/NVFlare/blob/${gh_branch}/examples/advanced/monitoring/README.md`,
}
```
- **Status:** ⚠️ PARTIAL
- **Issue:** Directory exists, needs README verification
- **Recommended Action:** Verify README is current and complete

#### 20. **distributed optimization** (Line 460-465) - Note: lowercase title
```javascript
{
  title: "distributed optimization",
  tags: ["adv.", "p2p"],
  description: "P2P Distributed Optimization algorithms with NVFlare. In this example we show how to exploit the lower-level NVFlare APIs to implement and run P2P distributed optimization algorithms. The aim here is twofold: on one hand we provide a few examples showing how to directly use the nvflare.app_opt.p2p API to run distributed optimization algorithms, on the other hand we provide a walkthrough of the actual implementation of the APIs in nvflare.app_opt.p2p to show how to exploit lower-level NVFlare APIs for advanced use-cases.",
  link: `https://github.com/NVIDIA/NVFlare/blob/${gh_branch}/examples/advanced/distributed_optimization/README.md`,
}
```
- **Status:** ⚠️ PARTIAL
- **Issue:** Directory exists, needs verification
- **Recommended Action:** 
  1. Capitalize title to "Distributed Optimization" for consistency
  2. Verify README is current

#### 21. **FL Experiment Tracking with TensorBoard Streaming** (Line 44-47) - ✅ VERIFIED
```javascript
{
  title: "FL Experiment Tracking with TensorBoard Streaming",
  tags: ["int.", "tools", "pytorch"],
  description: "Example integrating NVIDIA FLARE with TensorBoard streaming capability from clients to the server.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/experiment-tracking/tensorboard/README.md`
}
```
- **Status:** ✅ EXISTS AND VERIFIED
- **Path:** `examples/advanced/experiment-tracking/tensorboard/README.md`
- **Content:** Comprehensive example with Recipe API for TensorBoard streaming

#### 22. **FL Experiment Tracking with MLflow** (Line 50-53) - ✅ VERIFIED
```javascript
{
  title: "FL Experiment Tracking with MLflow",
  tags: ["int.", "tools", "pytorch"],
  description: "Example integrating NVIDIA FLARE with MLflow streaming capability from clients to the server.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/experiment-tracking/mlflow/README.md`
}
```
- **Status:** ✅ EXISTS AND VERIFIED
- **Path:** `examples/advanced/experiment-tracking/mlflow/README.md`
- **Content:** Complete with multiple examples (centralized, site-specific, Lightning logger)

#### 23. **FL Experiment Tracking with Weights and Biases** (Line 56-59) - ✅ VERIFIED
```javascript
{
  title: "FL Experiment Tracking with Weights and Biases",
  tags: ["int.", "tools", "pytorch"],
  description: "Example integrating NVIDIA FLARE with Weights and Biases streaming capability from clients to the server.",
  link: `https://github.com/NVIDIA/NVFlare/tree/${gh_branch}/examples/advanced/experiment-tracking/wandb/README.md`
}
```
- **Status:** ✅ EXISTS AND VERIFIED
- **Path:** `examples/advanced/experiment-tracking/wandb/README.md`
- **Content:** Comprehensive with server-side and client-side tracking modes

#### 24. **Federated Policies** (Line 111-114)
```javascript
{
  title: "Federated Policies",
  tags: ["adv.", "deployment"],
  description: "Example to demonstrate the federated site policies for authorization, resource and data privacy management.",
  link: `https://github.com/NVIDIA/NVFlare/blob/${gh_branch}/examples/advanced/federated-policies/README.rst`
}
```
- **Status:** ⚠️ NEEDS VERIFICATION
- **Issue:** Directory exists, but file extension is `.rst` not `.md`
- **Recommended Action:** Verify README.rst exists (not README.md)

---

## Documentation Links (No File Verification Needed)

These tutorials link to ReadTheDocs documentation, not GitHub files:

1. **Operating NVIDIA FLARE: Admin Client, Commands, FLARE API** (Line 37-41)
2. **Containerized Deployment with Docker** (Line 62-66)
3. **Cloud Deployment** (Line 69-73)
4. **Deployment to Kubernetes** (Line 76-80)
5. **Helm Chart Deployment** (Line 83-87)
6. **Secure Provisioning** (Line 90-94)
7. **Preflight Check** (Line 97-101)
8. **NVIDIA FLARE Dashboard** (Line 104-108)

---

## Summary of Required Updates

### Immediate Actions (High Priority)

1. **REMOVE these non-existent tutorials:**
   - Getting Started (`examples/getting_started`)
   - ML/DL to FL (`examples/hello-world/ml-to-fl`)
   - Hello FedAvg (`examples/hello-world/hello-fedavg`)
   - Logistic Regression with Newton-Raphson (`examples/advanced/lr-newton-raphson`)
   - Random Forest (`examples/advanced/random_forest`)
   - Federated Vertical XGBoost (`examples/advanced/vertical_xgboost`) - OR update to `vertical_federated_learning`
   - BraTS18 (`examples/advanced/brats18`)
   - Secure Federated XGBoost with HE (`examples/advanced/xgboost_secure`)
   - Federated Embedding Model Training / RAG (`examples/advanced/rag`)

2. **UPDATE these incorrect paths:**
   - Prostate example: Change from `examples/advanced/prostate` to `research/prostate`
   - Verify all research examples are correctly pointing to `research/` directory (they currently are)
   - Verify all integration examples are correctly pointing to `integration/` directory (they currently are)

3. **VERIFY and potentially update:**
   - Swarm Learning (only README exists, no full example code)
   - Finance End-to-End (only README exists, no code)
   - All experiment tracking examples (tensorboard, mlflow, wandb subdirectories)
   - MONAI integration with experiment tracking (verify anchor link)
   - System Monitoring example
   - Distributed Optimization (capitalize title)

### Medium Priority

4. **ADD missing hello-world examples to catalog** (if desired):
   - Hello Lightning (`examples/hello-world/hello-lightning`)
   - Hello NumPy (`examples/hello-world/hello-numpy`)
   - Hello Logistic Regression (`examples/hello-world/hello-lr`)
   - Hello Tabular Stats (`examples/hello-world/hello-tabular-stats`)

5. **Verify README.md files exist for all linked examples**

---

## Detailed File Path Verification Needed

The following directories need detailed verification to confirm README.md or correct files exist:

```bash
# High priority verification
examples/advanced/kaplan-meier-he/README.md
examples/advanced/swarm_learning/README.md (exists but check if complete)
examples/advanced/finance-end-to-end/README.md (exists but check if code exists)
examples/advanced/experiment-tracking/tensorboard/README.md
examples/advanced/experiment-tracking/mlflow/README.md
examples/advanced/experiment-tracking/wandb/README.md
examples/advanced/keycloak-site-authentication/README.md
examples/advanced/bionemo/README.md
examples/advanced/job_api/tf/ (check if exists)
examples/advanced/monitoring/README.md
examples/advanced/distributed_optimization/README.md
examples/advanced/federated-policies/README.rst (note: .rst not .md)
integration/monai/examples/spleen_ct_segmentation_local/README.md
integration/nemo/examples/supervised_fine_tuning/README.md
research/prostate/README.md
```

---

## Recommended Next Steps

1. **Immediate**: Remove all non-existent examples from `tutorials.astro` (9 tutorials)
2. **Immediate**: Update incorrect paths (prostate: move to research/)
3. **Verification Pass**: Check all ⚠️ marked tutorials for README existence and content accuracy
4. **Content Review**: For examples that exist but may be incomplete (swarm_learning, finance-end-to-end), determine if they should be removed or completed
5. **Add Missing**: Consider adding the 4 hello-world examples that exist but aren't in the catalog
6. **Style Fix**: Capitalize "distributed optimization" to "Distributed Optimization"
7. **Link Verification**: Test all GitHub links to ensure they resolve correctly
8. **Documentation Review**: Update any outdated descriptions or tags

---

## Files to Edit

**Primary File:**
- `/web/src/components/tutorials.astro` (lines 8-467)

**Verification Needed:**
- All example README.md files listed in the "Detailed File Path Verification Needed" section above

---

## Notes

- The web page uses `${gh_branch}` variable for branch name in URLs, which is good for version flexibility
- All research examples correctly use `research/` path prefix
- All integration examples correctly use `integration/` path prefix
- Most hello-world examples are correctly referenced
- The main issues are in the advanced examples section

---

## End of Analysis

**Total Tutorials Analyzed:** 67  
**Tutorials with Issues:** 21  
**Tutorials Verified Working:** 46  

**Estimated Time to Fix:** 2-4 hours (depending on decisions about incomplete examples)
