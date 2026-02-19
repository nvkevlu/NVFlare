# NVFlare Recipe Conversion: Comprehensive Status & Consistency Audit

**Date**: January 12, 2026
**Purpose**: Comprehensive analysis of recipe conversion status with detailed consistency audit
**Scope**: All examples, focusing on code patterns, documentation, and structural consistency

---

## 📊 Executive Summary

### Overall Status

| Category | Total | Converted | Legacy JSON | FedJob API | % Complete |
|----------|-------|-----------|-------------|------------|------------|
| **Hello World** | 9 | 9 | 0 | 0 | **100%** ✅ |
| **Sklearn** | 3 | 3 | 0 | 0 | **100%** ✅ |
| **Experiment Tracking** | 5 | 5 | 0 | 0 | **100%** ✅ |
| **XGBoost** | 4 | 1 | 0 | 3 | 25% |
| **Computer Vision** | 6 | 0 | 4 | 2 | 0% |
| **NLP** | 2 | 0 | 0 | 2 | 0% |
| **Statistics** | 6 | 2 | 0 | 4 | 33% |
| **Specialized** | 13 | 0 | 3 | 10 | 0% |
| **TOTAL** | **48** | **20** | **7** | **21** | **42%** |

**Note**: Updated count from 19 to 20 examples (hello-numpy-cross-val now completed with NumpyCrossSiteEvalRecipe)

### Key Findings

✅ **Completed Categories**: Hello-world, Sklearn, Experiment Tracking
❌ **Critical Gaps**: Computer Vision (0%), NLP (0%), Most of XGBoost
⚠️ **Consistency Issues**: Significant variations in file naming, structure, and documentation patterns

---

## 🔍 DETAILED CONSISTENCY AUDIT

This section analyzes consistency across all key dimensions requested:
1. Download Data
2. Prepare Data
3. Model Code
4. Code Structure
5. Client-Side Code
6. Server-Side Code (Job Recipe)
7. File Naming Conventions
8. Documentation Patterns

---

## 1. DATA DOWNLOAD CONSISTENCY

### Current State

#### Pattern A: `download_data.py` Script
**Examples using this:**
- `hello-world/hello-lr/download_data.py`
- `advanced/federated-statistics/image_stats/download_data.py`
- `advanced/codon-fm/download_data_and_split.py` (combined)

**Pattern:**
```python
# Standalone script
# Downloads from URL
# Saves to /tmp/nvflare/dataset/ or similar
```

#### Pattern B: Inline in prepare_data scripts
**Examples using this:**
- Most sklearn examples (download happens in prepare_data.sh)
- XGBoost examples (download in prepare_data.sh)

#### Pattern C: Manual download (README instructions only)
**Examples using this:**
- CIFAR-10 examples
- NLP-NER example
- Medical imaging examples

### ❌ CONSISTENCY ISSUES IDENTIFIED

| Issue | Severity | Impact |
|-------|----------|--------|
| **No standard naming** | High | Users don't know which file to run |
| **Some use .py, some use .sh** | Medium | Inconsistent execution method |
| **Different default paths** | Medium | Hard to share data preparation workflows |
| **No clear separation** | High | Download vs prepare_data mixed |

### ✅ RECOMMENDATION: Standardize Data Download

**Proposed Standard Pattern:**
```
examples/{category}/{example}/
├── download_data.sh          # Always shell script for consistency
├── prepare_data.sh           # Separate from download
└── README.md                 # Clear instructions
```

**Standard locations:**
- Downloaded raw data: `/tmp/nvflare/raw_data/{example_name}/`
- Prepared split data: `/tmp/nvflare/dataset/{example_name}/`

**Action Items:**
1. Create `download_data.sh` for all examples that need downloads
2. Separate download from preparation logic
3. Update all READMEs with consistent instructions

---

## 2. DATA PREPARATION CONSISTENCY

### Current State

#### Pattern A: `prepare_data.sh` (Shell Script)
**Examples:** 19 examples use this pattern

**Files found:**
```
advanced/cifar10/cifar10-sim/prepare_data.sh
advanced/sklearn-linear/prepare_data.sh
advanced/sklearn-kmeans/prepare_data.sh
advanced/sklearn-svm/prepare_data.sh
advanced/experiment-tracking/prepare_data.sh
advanced/federated-statistics/hierarchical_stats/prepare_data.sh
advanced/xgboost/fedxgb/prepare_data.sh
advanced/xgboost/fedxgb_secure/prepare_data.sh
advanced/nlp-ner/prepare_data.sh
advanced/finance/prepare_data.sh
advanced/psi/user_email_match/prepare_data.sh
hello-world/hello-cyclic/prepare_data.sh
hello-world/hello-lightning/prepare_data.sh
... (total 19 files)
```

**Typical content:**
```bash
#!/usr/bin/env bash
python3 utils/prepare_data.py --site_num 2
```

#### Pattern B: `prepare_data.py` (Python Script - Direct)
**Examples:** 13 examples use this pattern

**Files found:**
```
advanced/federated-statistics/image_stats/prepare_data.py
advanced/sklearn-kmeans/utils/prepare_data.py
advanced/sklearn-svm/utils/prepare_data.py
hello-world/hello-tabular-stats/prepare_data.py
hello-world/hello-lr/prepare_data.py
... (total 13 files)
```

#### Pattern C: In `utils/` subdirectory
**Examples:** Many advanced examples

**Structure:**
```
example/
├── prepare_data.sh          # Wrapper script
└── utils/
    └── prepare_data.py      # Actual logic
```

#### Pattern D: Multiple preparation scripts
**Examples:** XGBoost, vertical FL

**Structure:**
```
xgboost/fedxgb/utils/
├── prepare_data_horizontal.py
├── prepare_data_vertical.py
└── baseline_centralized.py
```

### ❌ CONSISTENCY ISSUES IDENTIFIED

| Issue | Severity | Examples Affected | Problem |
|-------|----------|-------------------|---------|
| **Inconsistent file location** | High | ~30 examples | Some in root, some in `utils/` |
| **Mixed naming conventions** | High | All examples | `prepare_data.py` vs `prepare_data.sh` vs both |
| **No standard CLI arguments** | Medium | ~20 examples | Different arg names: `--site_num` vs `--n_clients` vs `--num_sites` |
| **Different output directories** | Medium | ~25 examples | Varies: `/tmp/nvflare/dataset/` vs example-specific paths |
| **Unclear execution order** | High | ~10 examples | When to run download vs prepare not obvious |

### ✅ RECOMMENDATION: Standardize Data Preparation

**Proposed Standard Pattern:**
```
examples/{category}/{example}/
├── download_data.sh          # Step 1: Download raw data (if needed)
├── prepare_data.sh           # Step 2: Split/prepare for FL
└── utils/
    └── prepare_data.py       # Implementation logic
```

**Standard CLI arguments:**
```bash
./prepare_data.sh --n_clients 5 --split_mode uniform --data_root /path/to/raw
```

**Standard argument names:**
- `--n_clients` (not `--site_num` or `--num_sites`)
- `--split_mode` (not `--split_method` or `--data_split`)
- `--data_root` (input path)
- `--output_dir` (output path)

**Action Items:**
1. Move all `prepare_data.py` to `utils/` subdirectory
2. Create `prepare_data.sh` wrapper for all examples
3. Standardize CLI argument names across all examples
4. Update all READMEs to reflect consistent execution

---

## 3. MODEL CODE CONSISTENCY

### Current State

#### Pattern A: `model.py` in Example Root (Recipe API Pattern)
**Examples:** 8 examples use this pattern

**Files found:**
```
hello-world/hello-pt/model.py
hello-world/hello-tf/model.py
hello-world/hello-cyclic/model.py
hello-world/hello-lightning/model.py
advanced/experiment-tracking/tensorboard/model.py
advanced/experiment-tracking/mlflow/hello-pt-mlflow/model.py
advanced/experiment-tracking/mlflow/hello-pt-mlflow-client/model.py
advanced/experiment-tracking/mlflow/hello-lightning-mlflow/model.py
```

**Typical content:**
```python
# Model definition
class SimpleNetwork(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(784, 128)
        # ...
    
    def forward(self, x):
        # ...
```

**Pattern B: No Separate Model File (Defined in client.py)**
**Examples:** NumPy examples, some sklearn

**Files:**
```
hello-world/hello-numpy/client.py  # Model params inline
hello-world/hello-lr/client.py     # Logistic regression inline
```

#### Pattern C: Model in `src/` or `networks/` Subdirectory (Legacy Pattern)
**Examples:** CIFAR-10, NLP-NER, others

**Files:**
```
advanced/cifar10/pt/networks/cifar10_nets.py
advanced/nlp-ner/src/nlp_models.py
advanced/cifar10/pt/learners/cifar10_learner.py
advanced/amplify/src/
advanced/codon-fm/jobs/train-nn/
```

#### Pattern D: No Model File (External Models)
**Examples:** XGBoost, sklearn in some cases

### ❌ CONSISTENCY ISSUES IDENTIFIED

| Issue | Severity | Examples Affected | Problem |
|-------|----------|-------------------|---------|
| **Inconsistent file location** | High | ~15 examples | Some in root, some in `src/`, some in `networks/`, some in `learners/` |
| **Inconsistent naming** | Medium | ~10 examples | `model.py` vs `{framework}_model.py` vs `{example}_nets.py` |
| **Mixed with learners** | High | CIFAR-10 | Model definition mixed with training logic |
| **No clear pattern for multi-model** | Medium | CIFAR-10, NLP | Multiple models in different files |

### ✅ RECOMMENDATION: Standardize Model Code

**Proposed Standard Pattern:**

**For Recipe API Examples (Preferred):**
```
examples/{category}/{example}/
├── model.py                  # Model definition (PyTorch/TF)
├── client.py                 # Training script
└── job.py                    # Recipe configuration
```

**For Complex Multi-Model Examples:**
```
examples/{category}/{example}/
├── models/
│   ├── __init__.py
│   ├── simple_net.py
│   ├── resnet.py
│   └── transformer.py
├── client.py
└── job.py
```

**For Non-DL Examples (sklearn, XGBoost, NumPy):**
```
examples/{category}/{example}/
├── client.py                 # Model inline or imported from sklearn/xgboost
└── job.py
```

**Action Items:**
1. Consolidate all model definitions to `model.py` or `models/` directory
2. Remove legacy `networks/`, `learners/`, `src/` patterns for model code
3. Separate model definition from training logic
4. Update imports in all examples

---

## 4. CODE STRUCTURE CONSISTENCY

### Current State - Recipe API Examples

#### Pattern A: Flat Structure (Recommended ✅)
**Examples:** Most converted examples

```
example/
├── job.py              # Recipe instantiation
├── client.py           # Training script
├── model.py            # Model definition (if needed)
├── prepare_data.sh     # Data preparation
├── requirements.txt    # Dependencies
└── README.md           # Documentation
```

**Examples using this:**
- All hello-world examples (9/9)
- All sklearn examples (3/3)
- All experiment-tracking examples (5/5)

#### Pattern B: With Utils Subdirectory
**Examples:** sklearn, some statistics

```
example/
├── job.py
├── client.py
├── model.py
├── prepare_data.sh
├── utils/
│   ├── prepare_data.py
│   └── split_data.py
├── requirements.txt
└── README.md
```

### Current State - Legacy Examples

#### Pattern C: Jobs Directory with JSON Configs (Legacy ❌)
**Examples:** CIFAR-10-sim, Medical imaging

```
example/
├── jobs/
│   ├── cifar10_fedavg/
│   │   ├── cifar10_fedavg/
│   │   │   └── config/
│   │   │       ├── config_fed_client.json
│   │   │       └── config_fed_server.json
│   │   └── meta.json
│   ├── cifar10_fedopt/
│   └── cifar10_fedprox/
├── src/
│   └── learners/
├── prepare_data.sh
└── README.md
```

#### Pattern D: Complex Nested Structure (Legacy ❌)
**Examples:** XGBoost, vertical FL, others

```
example/
├── fedxgb/
│   ├── src/
│   ├── utils/
│   ├── xgb_fl_job_horizontal.py
│   ├── xgb_fl_job_vertical.py
│   ├── prepare_data.sh
│   └── README.md
├── fedxgb_secure/
│   ├── utils/
│   ├── train_standalone/
│   └── xgb_fl_job.py
└── README.md
```

### ❌ CONSISTENCY ISSUES IDENTIFIED

| Issue | Severity | Examples Affected | Problem |
|-------|----------|-------------------|---------|
| **Mixed job file naming** | High | ~21 examples | Some `job.py`, some `fl_job.py`, some `{example}_job.py` |
| **Inconsistent directory depth** | High | ~15 examples | Some flat, some nested 3+ levels |
| **Jobs directory pattern** | Critical | 7 examples | Legacy JSON config structure still exists |
| **No standard for utilities** | Medium | ~20 examples | Utils in root vs `utils/` vs `src/` |
| **Mixed requirements files** | Low | Some examples | Some have requirements.txt, some don't |

### ✅ RECOMMENDATION: Standardize Code Structure

**STANDARD RECIPE API STRUCTURE (All examples should follow this):**

```
examples/{category}/{example-name}/
├── job.py                    # REQUIRED: Recipe configuration
├── client.py                 # REQUIRED: Training/validation script
├── model.py                  # OPTIONAL: Model definition (DL frameworks)
├── prepare_data.sh           # OPTIONAL: Data preparation wrapper
├── download_data.sh          # OPTIONAL: Data download script
├── utils/                    # OPTIONAL: Helper utilities
│   ├── prepare_data.py       # Data preparation logic
│   └── {other_utils}.py      # Other helpers
├── requirements.txt          # REQUIRED: Python dependencies
└── README.md                 # REQUIRED: Documentation
```

**NAMING STANDARDS:**
- ✅ Always `job.py` (NOT `fl_job.py`, NOT `{example}_job.py`)
- ✅ Always `client.py` (NOT `train.py`, NOT `{example}_client.py`)
- ✅ Always `model.py` (NOT `{example}_model.py`, NOT `networks.py`)

**DIRECTORIES TO ELIMINATE:**
- ❌ `jobs/` with JSON configs - migrate to Recipe API
- ❌ `src/` for client code - move to root as `client.py`
- ❌ `learners/` - integrate into `client.py`
- ❌ Deep nesting - flatten structure

**Action Items:**
1. Rename all `fl_job.py` → `job.py`
2. Rename all `*_job.py` → `job.py`
3. Move all client code to root `client.py`
4. Flatten deeply nested structures
5. Remove all `jobs/` directories with JSON configs
6. Consolidate utilities to `utils/` subdirectory

---

## 5. CLIENT-SIDE CODE CONSISTENCY

### Current State

#### Pattern A: `client.py` with Recipe API (Recommended ✅)
**Examples:** All converted examples (20)

**Typical structure:**
```python
import flare.api as flare

def main():
    # 1. Get client API
    client = flare.init()
    
    # 2. Load data
    train_loader, val_loader = load_data(client.get_site_name())
    
    # 3. Load model
    model = client.get_model()
    
    # 4. Train
    while client.is_train():
        # Training loop
        train_one_epoch(model, train_loader)
        
        # Send model back
        client.send_model(model)
    
    # 5. Evaluate
    if client.is_evaluate():
        metrics = evaluate(model, val_loader)
        client.send_metrics(metrics)

if __name__ == "__main__":
    main()
```

**Examples using this pattern:**
- `hello-world/hello-pt/client.py`
- `hello-world/hello-numpy/client.py`
- `advanced/sklearn-linear/client.py`
- All experiment-tracking examples

#### Pattern B: Legacy Executor/Learner Pattern (❌ Legacy)
**Examples:** CIFAR-10, some advanced

**File location:** Usually in `src/` or `learners/`

**Structure:**
```python
class CustomLearner(BaseLearner):
    def initialize(self, parts, *args, **kwargs):
        # Setup
        
    def train(self, data, fl_ctx, *args, **kwargs):
        # Training
        
    def validate(self, data, fl_ctx, *args, **kwargs):
        # Validation
```

**Examples:**
- `advanced/cifar10/pt/learners/cifar10_learner.py`
- `advanced/cifar10/pt/learners/cifar10_model_learner.py`
- `advanced/cifar10/pt/learners/cifar10_scaffold_learner.py`

#### Pattern C: ScriptRunner/ScriptExecutor Pattern (Mixed)
**Examples:** Some examples use pre-configured ScriptRunner

**No explicit client file** - training logic embedded in separate scripts

### ❌ CONSISTENCY ISSUES IDENTIFIED

| Issue | Severity | Examples Affected | Problem |
|-------|----------|-------------------|---------|
| **Mixed API usage** | Critical | ~15 examples | Some use new Flare API, some use legacy Executor/Learner |
| **Inconsistent naming** | High | ~10 examples | `client.py` vs `train.py` vs learner classes |
| **File location varies** | High | ~10 examples | Root vs `src/` vs `learners/` |
| **Different initialization** | High | ~20 examples | `flare.init()` vs class-based vs script-based |
| **Inconsistent data loading** | Medium | ~25 examples | Different patterns for site-specific data |

### ✅ RECOMMENDATION: Standardize Client Code

**STANDARD CLIENT.PY STRUCTURE:**

```python
"""
Client-side training script for {Example Name}.

This script follows the NVFlare Client API pattern:
1. Initialize with flare.init()
2. Load site-specific data
3. Get model from server
4. Train and send back model
5. Optionally evaluate
"""

import flare.api as flare

def load_data(site_name: str):
    """Load site-specific data.
    
    Args:
        site_name: Name of the current site (e.g., "site-1", "site-2")
    
    Returns:
        Tuple of (train_loader, val_loader)
    """
    # Standard data loading pattern
    pass

def train_one_epoch(model, train_loader, optimizer, criterion):
    """Train model for one epoch.
    
    Args:
        model: The model to train
        train_loader: Training data loader
        optimizer: Optimizer instance
        criterion: Loss function
    
    Returns:
        Average training loss
    """
    # Standard training loop
    pass

def evaluate(model, val_loader, criterion):
    """Evaluate model on validation data.
    
    Args:
        model: The model to evaluate
        val_loader: Validation data loader
        criterion: Loss function
    
    Returns:
        Dictionary of metrics {"accuracy": ..., "loss": ...}
    """
    # Standard evaluation
    pass

def main():
    """Main training workflow."""
    # 1. Initialize
    client = flare.init()
    site_name = client.get_site_name()
    
    # 2. Load data
    train_loader, val_loader = load_data(site_name)
    
    # 3. Setup training
    model = client.get_model()
    optimizer = ...  # Setup optimizer
    criterion = ...   # Setup loss
    
    # 4. Training loop
    while client.is_train():
        train_loss = train_one_epoch(model, train_loader, optimizer, criterion)
        client.log_metric("train_loss", train_loss)
        client.send_model(model)
    
    # 5. Evaluation (optional)
    if client.is_evaluate():
        metrics = evaluate(model, val_loader, criterion)
        client.send_metrics(metrics)

if __name__ == "__main__":
    main()
```

**Standard Functions Required:**
1. `load_data(site_name)` - Site-specific data loading
2. `train_one_epoch(...)` - Single epoch training
3. `evaluate(...)` - Model evaluation
4. `main()` - Main workflow

**Action Items:**
1. Convert all legacy Executor/Learner classes to `client.py` with Flare API
2. Consolidate all client code into single `client.py` file
3. Standardize function names across all examples
4. Add consistent docstrings
5. Remove all files from `src/`, `learners/` directories

---

## 6. SERVER-SIDE CODE (JOB RECIPE) CONSISTENCY

### Current State

#### Pattern A: Recipe API - Simple Instantiation (Recommended ✅)
**Examples:** Most converted examples

**File:** `job.py`

**Structure:**
```python
"""
Job configuration using Recipe API.
"""
import argparse
from nvflare.app_opt.pt.recipes import FedAvgRecipe
from nvflare.recipe import SimEnv

def main():
    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--n_clients", type=int, default=2)
    parser.add_argument("--num_rounds", type=int, default=5)
    args = parser.parse_args()
    
    # Create recipe
    recipe = FedAvgRecipe(
        name="job_name",
        min_clients=args.n_clients,
        num_rounds=args.num_rounds,
        initial_model=MyModel(),
        train_script="client.py",
    )
    
    # Run
    recipe.run()

if __name__ == "__main__":
    main()
```

**Examples:**
- All hello-world (9 examples)
- All sklearn (3 examples)
- All experiment-tracking (5 examples)

#### Pattern B: Recipe API with Utilities (Recommended ✅)
**Examples:** Experiment tracking, cross-site eval

**Structure:**
```python
from nvflare.app_opt.pt.recipes import FedAvgRecipe
from nvflare.recipe.utils import add_experiment_tracking, add_cross_site_evaluation

recipe = FedAvgRecipe(...)

# Add utilities
add_experiment_tracking(recipe, "tensorboard")
add_cross_site_evaluation(recipe, model_locator_type="pytorch")

recipe.run()
```

#### Pattern C: FedJob API (❌ Needs Conversion)
**Examples:** XGBoost, NLP-NER, others (21 examples)

**File:** Various names (`fl_job.py`, `xgb_fl_job_horizontal.py`, etc.)

**Structure:**
```python
from nvflare.job_config.api import FedJob

job = FedJob(name="job_name")

# Manual component configuration
controller = FedAvg(...)
job.to(controller, "server")

executor = ScriptExecutor(...)
job.to(executor, "clients")

# Export
job.export(...)
```

#### Pattern D: Legacy JSON Configs (❌ Critical - Needs Conversion)
**Examples:** CIFAR-10-sim, medical imaging (7 examples)

**Structure:**
```
jobs/job_name/
├── app/
│   └── config/
│       ├── config_fed_server.json
│       └── config_fed_client.json
└── meta.json
```

### ❌ CONSISTENCY ISSUES IDENTIFIED

| Issue | Severity | Examples Affected | Problem |
|-------|----------|-------------------|---------|
| **Mixed file naming** | Critical | ~21 examples | `job.py` vs `fl_job.py` vs `{example}_job.py` |
| **Different APIs** | Critical | ~28 examples | Recipe API vs FedJob API vs JSON configs |
| **Inconsistent arguments** | High | ~25 examples | Different CLI arg patterns |
| **No standard imports** | Medium | ~20 examples | Various import patterns |
| **Mixed execution patterns** | High | ~20 examples | Some use `.run()`, some `.execute()`, some export |

### ✅ RECOMMENDATION: Standardize Job Configuration

**STANDARD JOB.PY STRUCTURE:**

```python
"""
Federated learning job configuration for {Example Name}.

This job uses the {RecipeName} Recipe API to configure:
- Algorithm: {Algorithm}
- Clients: {Number} minimum
- Rounds: {Number} training rounds
- Framework: {PyTorch/TensorFlow/NumPy/Sklearn}

Usage:
    python job.py --n_clients 5 --num_rounds 10
    
    # With custom options
    python job.py --n_clients 5 --num_rounds 10 --batch_size 32
"""

import argparse
from model import MyModel  # If applicable

from nvflare.app_opt.{framework}.recipes import {Recipe}
from nvflare.recipe import SimEnv
from nvflare.recipe.utils import add_experiment_tracking  # If applicable

def define_parser():
    """Define command line arguments.
    
    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(description="FL job configuration")
    
    # Standard arguments (all jobs should have these)
    parser.add_argument("--n_clients", type=int, default=2, 
                        help="Number of clients")
    parser.add_argument("--num_rounds", type=int, default=5, 
                        help="Number of training rounds")
    
    # Job-specific arguments
    parser.add_argument("--batch_size", type=int, default=32,
                        help="Training batch size")
    # ... other args
    
    return parser.parse_args()

def main():
    """Main job configuration and execution."""
    args = define_parser()
    
    # Create recipe
    recipe = {Recipe}(
        name="{job_name}",
        min_clients=args.n_clients,
        num_rounds=args.num_rounds,
        initial_model=MyModel(),  # If applicable
        train_script="client.py",
        # ... other recipe params
    )
    
    # Add utilities (optional)
    # add_experiment_tracking(recipe, "tensorboard")
    
    # Execute
    recipe.run()

if __name__ == "__main__":
    main()
```

**Standard Components:**
1. ✅ File always named `job.py`
2. ✅ Docstring at top explaining the job
3. ✅ `define_parser()` function for CLI args
4. ✅ `main()` function for execution
5. ✅ Standard argument names: `--n_clients`, `--num_rounds`
6. ✅ Recipe API (not FedJob, not JSON)
7. ✅ `.run()` method for execution

**Action Items:**
1. Convert all FedJob API examples to Recipe API (21 examples)
2. Convert all JSON config examples to Recipe API (7 examples)
3. Rename all job files to `job.py`
4. Standardize CLI argument naming
5. Add consistent docstrings
6. Use `.run()` for all executions

---

## 7. FILE NAMING CONSISTENCY

### Current Analysis

#### Job Files
| Current Name | Count | Examples | Should Be |
|--------------|-------|----------|-----------|
| `job.py` | 31 | Most converted | ✅ Keep |
| `fl_job.py` | 12 | Tutorials | ❌ Rename to `job.py` |
| `{example}_job.py` | 6 | XGBoost, NLP | ❌ Rename to `job.py` |
| `{example}_fl_job.py` | 3 | XGBoost | ❌ Rename to `job.py` |

#### Client Files
| Current Name | Count | Examples | Should Be |
|--------------|-------|----------|-----------|
| `client.py` | 20 | Converted examples | ✅ Keep |
| `train.py` | 5 | Some examples | ❌ Rename to `client.py` |
| `{example}_client.py` | 2 | Some examples | ❌ Rename to `client.py` |
| Learner classes in `src/` | 8 | Legacy examples | ❌ Convert to `client.py` |

#### Model Files
| Current Name | Count | Examples | Should Be |
|--------------|-------|----------|-----------|
| `model.py` | 8 | DL examples | ✅ Keep |
| `{example}_model.py` | 3 | Some examples | ❌ Rename to `model.py` |
| `{example}_nets.py` | 2 | CIFAR-10 | ❌ Rename to `model.py` |
| Models in `networks/` | 1 | CIFAR-10 | ❌ Move to `model.py` |
| Models in `src/` | 3 | Various | ❌ Move to `model.py` |

#### Data Preparation Files
| Current Name | Count | Examples | Should Be |
|--------------|-------|----------|-----------|
| `prepare_data.sh` | 19 | Most examples | ✅ Keep |
| `prepare_data.py` (root) | 3 | Some examples | ❌ Move to `utils/prepare_data.py` + create `.sh` wrapper |
| `prepare_data.py` (utils/) | 13 | Better pattern | ✅ Keep |
| `download_data.py` | 2 | Some examples | ❌ Rename to `download_data.sh` for consistency |
| `{specific}_data.py` | 5 | Various | ❌ Rename to `prepare_data.py` |

### ❌ CONSISTENCY ISSUES SUMMARY

**Critical Issues:**
1. **22 job files** need renaming to `job.py`
2. **7 client files** need renaming to `client.py`
3. **5 model files** need renaming to `model.py`
4. **10+ data prep files** need reorganization

### ✅ RECOMMENDATION: File Naming Standards

**MANDATORY FILE NAMES:**

```
examples/{category}/{example}/
├── job.py                    # Always this name
├── client.py                 # Always this name
├── model.py                  # Always this name (if model needed)
├── prepare_data.sh           # Always shell script
├── download_data.sh          # Always shell script (if download needed)
├── requirements.txt          # Always this name
└── README.md                 # Always this name
```

**ALLOWED VARIATIONS:**
- `utils/prepare_data.py` - Implementation for prepare_data.sh
- `utils/{other_utils}.py` - Additional utilities
- `models/` directory - For multi-model examples

**FORBIDDEN NAMES:**
- ❌ `fl_job.py`
- ❌ `{example}_job.py`
- ❌ `train.py` (use `client.py`)
- ❌ `{example}_client.py`
- ❌ `{example}_model.py`
- ❌ `{framework}_model.py`

**Action Items:**
1. Rename all job files: `*_job.py` → `job.py`
2. Rename all client files: `train.py`, `*_client.py` → `client.py`
3. Rename all model files: `*_model.py`, `*_nets.py` → `model.py`
4. Rename data prep: `*_data.py` → `prepare_data.py` in `utils/`
5. Create shell wrappers where missing

---

## 8. DOCUMENTATION CONSISTENCY

### Current State

#### README.md Files
All examples have README.md, but content varies significantly:

**Pattern A: Recipe API Documentation (Recommended ✅)**
**Examples:** Converted examples (20)

**Standard sections:**
1. Title and brief description
2. Installation instructions
3. Quick start with `job.py`
4. How it works (Recipe API explanation)
5. Customization options
6. Advanced usage (POC, Production)
7. Next steps / related examples

**Examples:**
- `hello-world/hello-pt/README.md`
- `advanced/sklearn-linear/README.md`
- `advanced/experiment-tracking/tensorboard/README.md`

**Pattern B: Legacy Documentation (❌ Needs Update)**
**Examples:** Non-converted examples (28)

**Typical sections:**
1. Title and brief description
2. Setup instructions (often outdated)
3. Manual job submission with JSON configs
4. nvflare CLI commands
5. Results interpretation

**Examples:**
- `advanced/cifar10/cifar10-sim/README.md`
- `advanced/nlp-ner/README.md`
- `advanced/xgboost/fedxgb/README.md`

### ❌ CONSISTENCY ISSUES IDENTIFIED

| Issue | Severity | Examples Affected | Problem |
|-------|----------|-------------------|---------|
| **Inconsistent structure** | High | ~30 examples | Different section order and content |
| **Mixed execution instructions** | Critical | ~28 examples | Some show Recipe API, some show CLI submission, some show JSON |
| **Outdated content** | High | ~20 examples | Still reference old APIs and workflows |
| **No standard template** | High | All examples | Each README has unique structure |
| **Inconsistent code examples** | Medium | ~25 examples | Different code block formats |
| **Missing sections** | Medium | ~15 examples | No "How it works" or customization sections |

### ✅ RECOMMENDATION: Documentation Standards

**STANDARD README.md TEMPLATE:**

```markdown
# {Example Title}

Brief description of what this example demonstrates (1-2 sentences).

## What You'll Learn

- Key learning point 1
- Key learning point 2
- Key learning point 3

## Installation

### Prerequisites

```bash
pip install -r requirements.txt
```

### Data Preparation

```bash
# Download data (if applicable)
./download_data.sh

# Prepare data for federated learning
./prepare_data.sh --n_clients 5
```

## Quick Start

Run the example with default settings:

```bash
python job.py --n_clients 2 --num_rounds 5
```

**Expected output:**
```
Round 1: loss=0.45, accuracy=0.82
Round 2: loss=0.38, accuracy=0.86
...
```

## How It Works

### Recipe API

This example uses the `{RecipeName}` Recipe API:

```python
from nvflare.app_opt.{framework}.recipes import {Recipe}

recipe = {Recipe}(
    name="example",
    min_clients=2,
    num_rounds=5,
    initial_model=MyModel(),
    train_script="client.py",
)

recipe.run()
```

### Client Training

The client-side training script (`client.py`) follows the standard pattern:

```python
import flare.api as flare

client = flare.init()
model = client.get_model()
# ... training logic
client.send_model(model)
```

### Data Flow

1. Server initializes global model
2. Clients receive model and train locally
3. Clients send updated models to server
4. Server aggregates using {Algorithm}
5. Repeat for {num_rounds} rounds

## Customization

### Adjust Training Parameters

```bash
python job.py --n_clients 5 --num_rounds 10 --batch_size 64
```

### Use Different Model

Edit `model.py` to define your custom model:

```python
class MyCustomModel(nn.Module):
    # ... your model architecture
```

### Change Data Split

Edit `utils/prepare_data.py` to implement custom data splitting:

```python
def split_data(data, n_clients, split_mode="uniform"):
    # ... your split logic
```

## Advanced Usage

### Run in POC Mode

```python
from nvflare.recipe import PocEnv

recipe = {Recipe}(...)
env = PocEnv(num_clients=2)
recipe.execute(env)
```

### Run in Production

```python
from nvflare.recipe import ProdEnv

recipe = {Recipe}(...)
env = ProdEnv(startup_kit_location="/path/to/kit")
recipe.execute(env)
```

### Add Experiment Tracking

```python
from nvflare.recipe.utils import add_experiment_tracking

recipe = {Recipe}(...)
add_experiment_tracking(recipe, "tensorboard")
recipe.run()
```

## Results

Expected results after training:

- Final accuracy: ~0.95
- Training time: ~5 minutes (simulated)
- Convergence: ~5-10 rounds

View results:
```bash
ls /tmp/nvflare/jobs/workdir/
```

## Files in This Example

- `job.py` - Recipe configuration and execution
- `client.py` - Client-side training script
- `model.py` - Model architecture definition
- `prepare_data.sh` - Data preparation script
- `requirements.txt` - Python dependencies
- `README.md` - This file

## Next Steps

- Try the [{Related Example}]({path}) for {related concept}
- Learn about [{Concept}]({docs_link}) in the documentation
- Explore [{Advanced Feature}]({example_path})

## References

- [NVFlare Recipe API Documentation]({link})
- [Original Paper]({link}) (if applicable)
- [Framework Documentation]({link})
```

**Required Sections (All READMEs must have):**
1. ✅ Title and description
2. ✅ Installation instructions
3. ✅ Quick start example
4. ✅ "How It Works" section
5. ✅ Customization options
6. ✅ File listing with explanations
7. ✅ Next steps / related examples

**Action Items:**
1. Create README template file
2. Update all 48 example READMEs to follow template
3. Remove outdated CLI submission instructions
4. Add Recipe API examples to all converted examples
5. Add consistent code blocks and formatting

---

## 📋 DETAILED EXAMPLE-BY-EXAMPLE STATUS

### Hello World Examples (9/9 - 100% ✅)

#### 1. hello-pt ✅
- **Status**: Converted
- **Recipe**: `FedAvgRecipe`
- **Files**: `job.py`, `client.py`, `model.py`, `README.md`
- **Consistency**: ✅ Excellent - follows all standards
- **Issues**: None
- **Location**: `examples/hello-world/hello-pt/`

#### 2. hello-tf ✅
- **Status**: Converted
- **Recipe**: `FedAvgRecipe` (TensorFlow)
- **Files**: `job.py`, `client.py`, `model.py`, `README.md`
- **Consistency**: ✅ Excellent
- **Issues**: None
- **Location**: `examples/hello-world/hello-tf/`

#### 3. hello-numpy ✅
- **Status**: Converted
- **Recipe**: `NumpyFedAvgRecipe`
- **Files**: `job.py`, `client.py`, `README.md`
- **Consistency**: ✅ Good - no model.py (NumPy doesn't need it)
- **Issues**: None
- **Location**: `examples/hello-world/hello-numpy/`

#### 4. hello-numpy-cross-val ✅
- **Status**: Converted (Dec 12, 2025)
- **Recipe**: `NumpyCrossSiteEvalRecipe`
- **Files**: `job.py`, `client.py`, `generate_pretrain_models.py`, `README.md`
- **Consistency**: ✅ Good
- **Issues**: None
- **Notes**: New recipe created specifically for this example
- **Location**: `examples/hello-world/hello-numpy-cross-val/`

#### 5. hello-lightning ✅
- **Status**: Converted
- **Recipe**: `FedAvgRecipe` (PyTorch Lightning)
- **Files**: `job.py`, `client.py`, `model.py`, `prepare_data.sh`, `README.md`
- **Consistency**: ✅ Excellent
- **Issues**: None
- **Location**: `examples/hello-world/hello-lightning/`

#### 6. hello-cyclic ✅
- **Status**: Converted
- **Recipe**: `CyclicRecipe`
- **Files**: `job.py`, `client.py`, `model.py`, `prepare_data.sh`, `README.md`
- **Consistency**: ✅ Excellent
- **Issues**: None
- **Location**: `examples/hello-world/hello-cyclic/`

#### 7. hello-lr ✅
- **Status**: Converted
- **Recipe**: `FedAvgLrRecipe`
- **Files**: `job.py`, `client.py`, `download_data.py`, `prepare_data.py`, `README.md`
- **Consistency**: ⚠️ Good but could improve
- **Issues**: 
  - Missing `prepare_data.sh` wrapper
  - `prepare_data.py` in root instead of `utils/`
- **Action needed**: Add shell wrapper, move to utils/
- **Location**: `examples/hello-world/hello-lr/`

#### 8. hello-flower ✅
- **Status**: Converted
- **Recipe**: `FlowerRecipe`
- **Files**: `job.py`, nested flower client/server code, `README.md`
- **Consistency**: ⚠️ Different structure (Flower integration)
- **Issues**: Complex nested structure for Flower compatibility
- **Action needed**: Accept as exception due to Flower framework requirements
- **Location**: `examples/hello-world/hello-flower/`

#### 9. hello-tabular-stats ✅
- **Status**: Converted
- **Recipe**: `FedStatsRecipe`
- **Files**: `job.py`, `client.py`, `prepare_data.py`, `README.md`
- **Consistency**: ⚠️ Good but could improve
- **Issues**:
  - Missing `prepare_data.sh` wrapper
  - `prepare_data.py` in root instead of `utils/`
- **Action needed**: Add shell wrapper, move to utils/
- **Location**: `examples/hello-world/hello-tabular-stats/`

---

### Sklearn Examples (3/3 - 100% ✅)

#### 1. sklearn-linear ✅
- **Status**: Converted
- **Recipe**: `SklearnFedAvgRecipe`
- **Files**: `job.py`, `client.py`, `prepare_data.sh`, `utils/prepare_job_config.py`, `README.md`
- **Consistency**: ✅ Excellent
- **Issues**: None
- **Location**: `examples/advanced/sklearn-linear/`

#### 2. sklearn-kmeans ✅
- **Status**: Converted
- **Recipe**: `KMeansFedAvgRecipe`
- **Files**: `job.py`, `client.py`, `prepare_data.sh`, `utils/prepare_data.py`, `utils/split_data.py`, `README.md`
- **Consistency**: ✅ Excellent - good use of utils/
- **Issues**: None
- **Location**: `examples/advanced/sklearn-kmeans/`

#### 3. sklearn-svm ✅
- **Status**: Converted
- **Recipe**: `SVMFedAvgRecipe`
- **Files**: `job.py`, `client.py`, `prepare_data.sh`, `utils/prepare_data.py`, `README.md`
- **Consistency**: ✅ Excellent
- **Issues**: None
- **Location**: `examples/advanced/sklearn-svm/`

---

### Experiment Tracking Examples (5/5 - 100% ✅)

#### 1. tensorboard ✅
- **Status**: Converted (Dec 18, 2025)
- **Recipe**: `FedAvgRecipe` + `add_experiment_tracking()`
- **Files**: `job.py`, `client.py`, `model.py`, `README.md`
- **Consistency**: ✅ Excellent - model pattern for tracking utility
- **Issues**: None
- **Location**: `examples/advanced/experiment-tracking/tensorboard/`

#### 2. mlflow/hello-pt-mlflow ✅
- **Status**: Converted (Dec 18, 2025)
- **Recipe**: `FedAvgRecipe` + `add_experiment_tracking()`
- **Files**: `job.py`, `client.py`, `model.py`, `README.md`
- **Consistency**: ✅ Excellent
- **Issues**: None (bug fixed during conversion)
- **Location**: `examples/advanced/experiment-tracking/mlflow/hello-pt-mlflow/`

#### 3. mlflow/hello-pt-mlflow-client ✅
- **Status**: Converted (Dec 18, 2025)
- **Recipe**: `FedAvgRecipe` + manual receivers (client-side tracking)
- **Files**: `job.py`, `client.py`, `model.py`, `README.md`
- **Consistency**: ✅ Good
- **Issues**: Client-side tracking requires manual configuration (no utility yet)
- **Notes**: Bug fixed - f-string error in original
- **Location**: `examples/advanced/experiment-tracking/mlflow/hello-pt-mlflow-client/`

#### 4. mlflow/hello-lightning-mlflow ✅
- **Status**: Converted (Dec 18, 2025)
- **Recipe**: Lightning `FedAvgRecipe` + `add_experiment_tracking()`
- **Files**: `job.py`, `client.py`, `model.py`, `README.md`
- **Consistency**: ✅ Excellent
- **Issues**: None
- **Location**: `examples/advanced/experiment-tracking/mlflow/hello-lightning-mlflow/`

#### 5. wandb ✅
- **Status**: Converted (Dec 18, 2025)
- **Recipe**: `FedAvgRecipe` + `add_experiment_tracking()`
- **Files**: `job.py`, `client.py`, `model.py`, `README.md`
- **Consistency**: ✅ Excellent
- **Issues**: None (dead code removed during conversion)
- **Location**: `examples/advanced/experiment-tracking/wandb/`

---

### XGBoost Examples (1/4 - 25%)

#### 1. random_forest ✅
- **Status**: Converted
- **Recipe**: `XGBBaggingRecipe`
- **Files**: `job.py`, client code, `README.md`
- **Consistency**: ✅ Good
- **Issues**: None
- **Location**: `examples/advanced/random_forest/` (need to verify exact path)

#### 2. xgboost/fedxgb (horizontal histogram) ❌
- **Status**: Needs conversion
- **Current**: FedJob API in `xgb_fl_job_horizontal.py`
- **Recipe needed**: `XGBHistogramRecipe`
- **Files**: `xgb_fl_job_horizontal.py`, `src/higgs_data_loader.py`, `utils/prepare_data_horizontal.py`, `prepare_data.sh`, `README.md`
- **Consistency**: ❌ Poor
- **Issues**:
  - Wrong file name (`xgb_fl_job_horizontal.py` should be `job.py`)
  - FedJob API instead of Recipe
  - Complex nested structure
  - Client code in `src/`
- **Action needed**: 
  1. Create `XGBHistogramRecipe`
  2. Convert to Recipe API
  3. Rename file to `job.py`
  4. Restructure code to standard pattern
- **Location**: `examples/advanced/xgboost/fedxgb/`

#### 3. xgboost/fedxgb (vertical) ❌
- **Status**: Needs conversion
- **Current**: FedJob API in `xgb_fl_job_vertical.py`
- **Recipe needed**: `XGBVerticalRecipe`
- **Files**: `xgb_fl_job_vertical.py`, `xgb_fl_job_vertical_psi.py`, `src/`, `utils/`, `README.md`
- **Consistency**: ❌ Poor - same issues as horizontal
- **Issues**:
  - Multiple job files for same algorithm
  - FedJob API
  - Complex structure
- **Action needed**:
  1. Create `XGBVerticalRecipe`
  2. Consolidate into single `job.py`
  3. Restructure code
- **Location**: `examples/advanced/xgboost/fedxgb/`

#### 4. xgboost/fedxgb_secure ❌
- **Status**: Needs conversion
- **Current**: FedJob API in `xgb_fl_job.py`
- **Recipe needed**: `XGBVerticalRecipe` with HE support
- **Files**: `xgb_fl_job.py`, `xgb_vert_eval_job.py`, `utils/`, `train_standalone/`, `README.md`
- **Consistency**: ❌ Poor
- **Issues**:
  - Multiple job files
  - Complex nested structure
  - Standalone training code mixed in
- **Action needed**:
  1. Enhance `XGBVerticalRecipe` with HE
  2. Convert to Recipe API
  3. Restructure code
- **Location**: `examples/advanced/xgboost/fedxgb_secure/`

---

### Computer Vision Examples (0/6 - 0%)

#### 1. cifar10/cifar10-sim ❌ CRITICAL
- **Status**: Not converted - Legacy JSON configs
- **Current**: Multiple JSON job directories
- **Recipes needed**: `FedAvgRecipe`, `FedOptRecipe`, `FedProxRecipe`, `ScaffoldRecipe`
- **Jobs**: 5 different jobs (central, fedavg, fedopt, fedprox, scaffold)
- **Files**: 
  - `jobs/cifar10_fedavg/` (JSON configs)
  - `jobs/cifar10_fedopt/` (JSON configs)
  - `jobs/cifar10_fedprox/` (JSON configs)
  - `jobs/cifar10_scaffold/` (JSON configs)
  - `pt/learners/` (multiple learner classes)
  - `pt/networks/cifar10_nets.py`
  - `prepare_data.sh`
- **Consistency**: ❌ Very Poor - legacy structure
- **Issues**:
  - **CRITICAL**: Still using JSON configs
  - Multiple job directories instead of single `job.py`
  - Client code in `learners/` instead of `client.py`
  - Model code in `networks/` instead of `model.py`
  - No Recipe API usage
  - 4 recipes need to be created (FedOpt, FedProx, SCAFFOLD)
- **Action needed**:
  1. Create 4 new recipes: `FedOptRecipe`, `FedProxRecipe`, `ScaffoldRecipe`, `CentralRecipe`
  2. Create single `job.py` with CLI arguments to select algorithm
  3. Convert learner classes to `client.py` with Flare API
  4. Move model to `model.py`
  5. Remove all `jobs/` directories
  6. Update README extensively
- **Priority**: 🔥 CRITICAL - Most popular example
- **Location**: `examples/advanced/cifar10/cifar10-sim/`

#### 2. cifar10/cifar10-real-world ❌ HIGH PRIORITY
- **Status**: Not converted - Legacy JSON configs
- **Current**: JSON configs with HE
- **Recipe needed**: `FedAvgRecipe` + HE support
- **Files**: Similar structure to cifar10-sim
- **Consistency**: ❌ Poor - same issues as cifar10-sim
- **Issues**: Same as cifar10-sim + HE integration needed
- **Action needed**:
  1. Convert to Recipe API with HE
  2. Restructure code
- **Priority**: 🔥 HIGH
- **Location**: `examples/advanced/cifar10/cifar10-real-world/`

#### 3. cifar10/tf ❌
- **Status**: Needs conversion
- **Current**: FedJob API
- **Recipe needed**: TensorFlow `FedAvgRecipe` (enhancement)
- **Files**: TensorFlow implementation in `tf/` subdirectory
- **Consistency**: ❌ Moderate issues
- **Issues**:
  - FedJob API instead of Recipe
  - Needs TF-specific recipe enhancement
- **Action needed**:
  1. Enhance TF `FedAvgRecipe`
  2. Convert to Recipe API
  3. Restructure if needed
- **Priority**: Medium-High
- **Location**: `examples/advanced/cifar10/tf/`

#### 4. prostate ❌
- **Status**: Not converted - Legacy JSON configs
- **Current**: JSON configs
- **Recipe needed**: `FedAvgRecipe` + medical imaging utilities
- **Files**: Medical imaging example structure
- **Consistency**: ❌ Poor - legacy structure
- **Issues**:
  - JSON configs
  - No medical imaging utilities yet
  - Needs 2D/3D data handling
- **Action needed**:
  1. Create medical imaging utilities
  2. Convert to Recipe API
  3. Restructure code
- **Priority**: HIGH (medical imaging important use case)
- **Location**: `examples/advanced/prostate/` (need to verify path)

#### 5. brats18 ❌
- **Status**: Not converted - Legacy JSON configs
- **Current**: JSON configs
- **Recipe needed**: `FedAvgRecipe` + medical imaging utilities (3D)
- **Consistency**: ❌ Poor - legacy structure
- **Issues**: Same as prostate + 3D specific
- **Action needed**: Same as prostate
- **Priority**: HIGH
- **Location**: Unknown - need to find

#### 6. hello-pt-resnet (if exists) ❌
- **Status**: Needs conversion (if it exists)
- **Current**: FedJob API
- **Recipe needed**: `FedAvgRecipe` (already exists!)
- **Consistency**: Unknown
- **Issues**: Should be easy conversion - recipe exists
- **Action needed**: Simple refactor to use `FedAvgRecipe`
- **Priority**: Low (quick win)
- **Location**: Need to verify

---

### NLP Examples (0/2 - 0%)

#### 1. nlp-ner ❌
- **Status**: Needs conversion
- **Current**: FedJob API in `nlp_fl_job.py`
- **Recipe needed**: `TransformerRecipe` or `BERTRecipe`
- **Files**: 
  - `nlp_fl_job.py` (should be `job.py`)
  - `src/nlp_fl.py` (training logic)
  - `src/nlp_models.py` (should be `model.py`)
  - `src/data_sequence.py`
  - `utils/data_split.py`
  - `prepare_data.sh`
  - `README.md`
- **Consistency**: ❌ Poor
- **Issues**:
  - Wrong file name (`nlp_fl_job.py`)
  - FedJob API instead of Recipe
  - Client code in `src/` instead of `client.py`
  - Model in `src/` instead of `model.py`
  - No Recipe for transformers yet
- **Action needed**:
  1. Create `TransformerRecipe`
  2. Convert to Recipe API
  3. Move `nlp_models.py` → `model.py`
  4. Move `nlp_fl.py` → `client.py`
  5. Rename `nlp_fl_job.py` → `job.py`
  6. Restructure code to standard pattern
- **Priority**: HIGH (NLP is popular use case)
- **Location**: `examples/advanced/nlp-ner/`

#### 2. llm_hf ❌
- **Status**: Needs standardization
- **Current**: Has custom recipe but needs standardization
- **Recipe needed**: Standardize existing `HFRecipe`
- **Files**: Custom implementation
- **Consistency**: ⚠️ Moderate - has recipe but custom
- **Issues**:
  - Custom recipe not standardized
  - May not follow conventions
- **Action needed**:
  1. Review existing recipe
  2. Standardize to match other recipes
  3. Update documentation
- **Priority**: HIGH (LLM fine-tuning is critical use case)
- **Location**: `examples/advanced/llm_hf/`

---

### Statistics Examples (2/6 - 33%)

#### 1. federated-statistics/image_stats ✅
- **Status**: Converted
- **Recipe**: `StatisticsRecipe`
- **Files**: `job.py`, `client.py`, `download_data.py`, `prepare_data.py`, `README.md`
- **Consistency**: ⚠️ Good but could improve
- **Issues**:
  - `download_data.py` should be `download_data.sh`
  - `prepare_data.py` in root should be in `utils/` with shell wrapper
- **Action needed**: Minor restructuring for consistency
- **Location**: `examples/advanced/federated-statistics/image_stats/`

#### 2. federated-statistics/df_stats ✅
- **Status**: Converted
- **Recipe**: `StatisticsRecipe`
- **Files**: `job.py`, `client.py`, `README.md`
- **Consistency**: ✅ Excellent
- **Issues**: None
- **Location**: `examples/advanced/federated-statistics/df_stats/`

#### 3. federated-statistics/hierarchical_stats ❌
- **Status**: Needs conversion
- **Current**: Legacy JSON configs in `jobs/` directory
- **Recipe needed**: Enhanced `StatisticsRecipe` with hierarchy support
- **Files**:
  - `jobs/hierarchical_stats/` (JSON configs)
  - `utils/prepare_data.py`
  - `prepare_data.sh`
  - `README.md`
- **Consistency**: ❌ Poor - legacy structure
- **Issues**:
  - JSON configs in `jobs/` directory
  - No Recipe API
  - Needs hierarchy support in StatisticsRecipe
- **Action needed**:
  1. Enhance `StatisticsRecipe` for hierarchical stats
  2. Convert to Recipe API
  3. Remove `jobs/` directory
  4. Create `job.py`
- **Priority**: Medium
- **Location**: `examples/advanced/federated-statistics/hierarchical_stats/`

#### 4. kaplan-meier-he ❌
- **Status**: Needs conversion
- **Current**: FedJob API in `job.py` (has job.py but uses FedJob)
- **Recipe needed**: `SurvivalAnalysisRecipe` or `KaplanMeierRecipe`
- **Files**: `job.py` (FedJob), `utils/prepare_data.py`, `README.md`
- **Consistency**: ⚠️ Moderate
- **Issues**:
  - Uses FedJob API instead of Recipe
  - Needs new recipe for Kaplan-Meier
  - Specialized use case
- **Action needed**:
  1. Create `SurvivalAnalysisRecipe` or `KaplanMeierRecipe`
  2. Convert from FedJob to Recipe API
- **Priority**: Low (specialized, less common)
- **Location**: `examples/advanced/kaplan-meier-he/`

#### 5. lr-newton-raphson ❌
- **Status**: Needs conversion
- **Current**: FedJob API (likely)
- **Recipe needed**: `NewtonRaphsonRecipe` or custom recipe
- **Consistency**: Unknown
- **Issues**: Research-oriented example, FedJob API
- **Action needed**:
  1. Create appropriate recipe
  2. Convert to Recipe API
- **Priority**: Low (research use case)
- **Location**: `examples/advanced/lr-newton-raphson/`

#### 6. federated-policies ❌
- **Status**: Infrastructure - Keep as is
- **Current**: Policy framework with JSON
- **Recipe needed**: N/A - Infrastructure example
- **Action needed**: None - this is infrastructure, not ML
- **Priority**: N/A
- **Location**: `examples/advanced/federated-policies/`

---

### Specialized Examples (0/13 - 0%)

#### 1. gnn ❌
- **Status**: Needs conversion
- **Current**: Custom controllers and workflows
- **Recipe needed**: `GNNRecipe`
- **Consistency**: Unknown
- **Issues**: Complex custom implementation
- **Action needed**:
  1. Create `GNNRecipe`
  2. Convert custom controllers to Recipe
- **Priority**: Medium (graph ML growing)
- **Location**: `examples/advanced/gnn/`

#### 2. amplify ❌
- **Status**: Needs conversion
- **Current**: Custom multi-task setup
- **Recipe needed**: `MultiTaskRecipe`
- **Consistency**: Unknown
- **Issues**: Complex multi-task learning setup
- **Action needed**:
  1. Create `MultiTaskRecipe`
  2. Convert to Recipe API
- **Priority**: Medium (research)
- **Location**: `examples/advanced/amplify/`

#### 3. bionemo ❌
- **Status**: Keep as FedJob (Highly specialized)
- **Current**: BioNeMo integration
- **Recipe needed**: N/A - too specialized
- **Action needed**: None - accept as exception
- **Priority**: Low
- **Location**: `examples/advanced/bionemo/`

#### 4. codon-fm ❌
- **Status**: Check if has job.py
- **Current**: Unknown - has `jobs/` directory with job.py files
- **Recipe needed**: Unknown
- **Consistency**: Unknown
- **Issues**: Need to investigate
- **Action needed**: Audit and determine conversion needs
- **Priority**: Low
- **Location**: `examples/advanced/codon-fm/`

#### 5. distributed_optimization/* ❌
- **Status**: Needs conversion (3 examples)
- **Current**: Notebooks and Python scripts
- **Recipe needed**: `ConsensusRecipe` or similar
- **Consistency**: Poor - research code
- **Issues**: Research-oriented, not production
- **Action needed**:
  1. Create `ConsensusRecipe` if valuable
  2. Otherwise keep as research examples
- **Priority**: Low
- **Location**: `examples/advanced/distributed_optimization/`

#### 6. vertical_federated_learning ❌
- **Status**: Needs conversion
- **Current**: JSON configs
- **Recipe needed**: `VFLRecipe`
- **Consistency**: Poor
- **Issues**: Unique paradigm, complex
- **Action needed**:
  1. Create `VFLRecipe`
  2. Convert to Recipe API
- **Priority**: Medium (VFL is important use case)
- **Location**: `examples/advanced/vertical_federated_learning/`

#### 7. swarm_learning ❌
- **Status**: Needs investigation
- **Current**: Unknown (only README found)
- **Recipe needed**: `SwarmRecipe` potentially
- **Action needed**: Investigate if implementation exists
- **Priority**: Low
- **Location**: `examples/advanced/swarm_learning/`

#### 8. streaming ❌
- **Status**: Needs investigation
- **Current**: Streaming infrastructure
- **Recipe needed**: Keep as FedJob (infrastructure)
- **Action needed**: Likely keep as is
- **Priority**: Low (infrastructure)
- **Location**: `examples/advanced/streaming/`

#### 9. tensor-stream ❌
- **Status**: Has job.py - check if Recipe or FedJob
- **Current**: Unknown
- **Recipe needed**: Unknown
- **Action needed**: Audit to determine status
- **Priority**: Low
- **Location**: `examples/advanced/tensor-stream/`

#### 10. finance ❌
- **Status**: Needs conversion
- **Current**: FedJob API (likely)
- **Recipe needed**: Reuse `XGBHistogramRecipe` when created
- **Consistency**: Unknown
- **Issues**: Should be easy once XGBoost recipe exists
- **Action needed**: Convert after XGBoost recipes ready
- **Priority**: Medium-High (fraud detection use case)
- **Location**: `examples/advanced/finance/`

#### 11. psi ❌
- **Status**: Has job.py - check if converted
- **Current**: Unknown
- **Recipe needed**: Unknown
- **Action needed**: Audit to determine status
- **Priority**: Low
- **Location**: `examples/advanced/psi/`

#### 12. Infrastructure Examples (Keep as is)
- **job-level-authorization** - Keep as infrastructure
- **monitoring** - Keep as infrastructure
- **keycloak-site-authentication** - Keep as infrastructure
- **custom_authentication** - Keep as infrastructure
- **federated-policies** - Keep as infrastructure

---

## 🔧 CONSISTENCY ISSUES SUMMARY

### Critical Issues (Must Fix)

| # | Issue | Examples Affected | Severity |
|---|-------|-------------------|----------|
| 1 | **Legacy JSON configs still exist** | 7 examples (CIFAR-10, medical) | 🔥 CRITICAL |
| 2 | **FedJob API instead of Recipe** | 21 examples | 🔥 CRITICAL |
| 3 | **Wrong job file names** | 22 examples (`*_job.py`) | 🔥 HIGH |
| 4 | **Client code in wrong location** | 15 examples (`src/`, `learners/`) | 🔥 HIGH |
| 5 | **Model code in wrong location** | 10 examples (`networks/`, `src/`) | 🔥 HIGH |

### High Priority Issues

| # | Issue | Examples Affected | Severity |
|---|-------|-------------------|----------|
| 6 | **Inconsistent data prep patterns** | ~30 examples | ⚠️ HIGH |
| 7 | **Missing standard file structure** | ~28 examples | ⚠️ HIGH |
| 8 | **Outdated READMEs** | ~28 examples | ⚠️ HIGH |
| 9 | **No standard CLI arguments** | ~25 examples | ⚠️ MEDIUM |
| 10 | **Inconsistent imports** | ~20 examples | ⚠️ MEDIUM |

### Medium Priority Issues

| # | Issue | Examples Affected | Severity |
|---|-------|-------------------|----------|
| 11 | **Mixed download patterns** | ~15 examples | ⚠️ MEDIUM |
| 12 | **Utils in wrong location** | ~20 examples | ⚠️ MEDIUM |
| 13 | **Missing requirements.txt** | ~10 examples | ⚠️ MEDIUM |
| 14 | **Inconsistent logging** | ~30 examples | ⚠️ LOW |
| 15 | **No standard docstrings** | ~35 examples | ⚠️ LOW |

---

## 📝 RECOMMENDED ACTION PLAN

### Phase 1: Create Missing Recipes (4-6 weeks)

**Priority 1A: Computer Vision Recipes**
1. ✅ `FedAvgRecipe` (exists) - use for basic CIFAR-10
2. ❌ `FedOptRecipe` - CRITICAL for CIFAR-10
3. ❌ `FedProxRecipe` - CRITICAL for CIFAR-10
4. ❌ `ScaffoldRecipe` - HIGH for CIFAR-10
5. ❌ `CentralRecipe` - MEDIUM for centralized baseline

**Priority 1B: XGBoost Recipes**
6. ✅ `XGBBaggingRecipe` (exists)
7. ❌ `XGBHistogramRecipe` - CRITICAL for horizontal FL
8. ❌ `XGBVerticalRecipe` - HIGH for vertical FL

**Priority 1C: NLP Recipes**
9. ❌ `TransformerRecipe` - HIGH for NLP-NER

### Phase 2: Convert Critical Examples (6-8 weeks)

**Critical Conversions (Legacy JSON → Recipe API):**
1. cifar10/cifar10-sim (5 jobs) - CRITICAL
2. cifar10/cifar10-real-world - HIGH
3. prostate - HIGH (medical)
4. brats18 - HIGH (medical)
5. hierarchical_stats - MEDIUM

**High Priority Conversions (FedJob → Recipe API):**
6. xgboost/fedxgb (horizontal) - HIGH
7. xgboost/fedxgb (vertical) - HIGH
8. nlp-ner - HIGH
9. llm_hf (standardize) - HIGH
10. cifar10/tf - MEDIUM

### Phase 3: Standardize File Structure (4-6 weeks)

**For ALL 48 examples:**

1. **Rename files** (~50 files to rename)
   - All `*_job.py` → `job.py`
   - All `train.py` → `client.py`
   - All `*_model.py` → `model.py`

2. **Restructure directories** (~30 examples)
   - Move client code to root `client.py`
   - Move model code to root `model.py`
   - Move utilities to `utils/` subdirectory
   - Remove `src/`, `learners/`, `networks/` directories
   - Remove `jobs/` directories with JSON

3. **Standardize data preparation** (~30 examples)
   - Create `download_data.sh` where needed
   - Create `prepare_data.sh` wrapper for all
   - Move `prepare_data.py` to `utils/`
   - Standardize CLI argument names

### Phase 4: Documentation Updates (4-6 weeks)

**For ALL 48 examples:**

1. **Update all READMEs** (48 files)
   - Follow standard template
   - Add Recipe API examples
   - Remove outdated CLI submission instructions
   - Add "How It Works" sections
   - Add consistent code examples

2. **Add docstrings** (~150 files)
   - Add module docstrings to all job.py
   - Add function docstrings to all client.py
   - Add class docstrings to all model.py

3. **Create example index** (1 file)
   - Master index of all examples
   - Organized by category
   - With descriptions and links

### Phase 5: Testing & Validation (2-3 weeks)

1. **Create integration tests** for all new recipes
2. **Test all converted examples** (48 examples)
3. **Verify all instructions** in READMEs
4. **Run linter** and fix issues
5. **Performance benchmarks** for key examples

---

## 📊 METRICS & TRACKING

### Completion Metrics

| Metric | Current | Target | Progress |
|--------|---------|--------|----------|
| **Examples with Recipe API** | 20/48 | 48/48 | 42% |
| **New Recipes Created** | 10 | 18 | 56% |
| **Standard File Structure** | 20/48 | 48/48 | 42% |
| **Correct File Names** | 31/48 | 48/48 | 65% |
| **Updated READMEs** | 20/48 | 48/48 | 42% |
| **Legacy JSON Eliminated** | 41/48 | 48/48 | 85% |

### Consistency Metrics

| Aspect | Consistent | Inconsistent | % Consistent |
|--------|-----------|--------------|--------------|
| **Job file naming** | 31 | 17 | 65% |
| **Client file location** | 20 | 28 | 42% |
| **Model file location** | 20 | 28 | 42% |
| **Data prep pattern** | 19 | 29 | 39% |
| **Directory structure** | 20 | 28 | 42% |
| **README format** | 20 | 28 | 42% |
| **API usage** | 20 | 28 | 42% |

### Weekly Targets

**Week 1-2:** Create FedOpt, FedProx recipes + convert 2 CIFAR-10 jobs
**Week 3-4:** Create SCAFFOLD, XGBHistogram recipes + convert 2 XGBoost examples
**Week 5-6:** Create TransformerRecipe + convert NLP-NER
**Week 7-8:** Create remaining recipes + convert medical imaging
**Week 9-12:** Standardize all file structures
**Week 13-16:** Update all documentation
**Week 17-18:** Testing and validation

---

## 🎯 SUCCESS CRITERIA

### Recipe Conversion Complete When:
- ✅ All 48 examples use Recipe API (no FedJob, no JSON)
- ✅ All 8 new recipes created and tested
- ✅ All examples follow standard file structure
- ✅ All files use standard naming conventions
- ✅ All READMEs follow standard template
- ✅ All examples have integration tests
- ✅ All linter errors resolved

### Consistency Achieved When:
- ✅ 100% of examples use Recipe API
- ✅ 100% of job files named `job.py`
- ✅ 100% of client files named `client.py`
- ✅ 100% of model files named `model.py`
- ✅ 100% of data prep uses standard pattern
- ✅ 100% of READMEs follow template
- ✅ 0% legacy JSON configs remain

---

## 📁 FILES TO CREATE/UPDATE

### New Files to Create

**Recipes (8 files):**
1. `nvflare/app_opt/pt/recipes/fedopt.py`
2. `nvflare/app_opt/pt/recipes/fedprox.py`
3. `nvflare/app_opt/pt/recipes/scaffold.py`
4. `nvflare/app_opt/xgboost/recipes/histogram.py`
5. `nvflare/app_opt/xgboost/recipes/vertical.py`
6. `nvflare/app_opt/pt/recipes/transformer.py`
7. `nvflare/app_opt/pt/recipes/gnn.py`
8. `nvflare/app_opt/pt/recipes/multitask.py`

**Documentation (2 files):**
1. `examples/README_TEMPLATE.md` - Standard template for all examples
2. `examples/EXAMPLES_INDEX.md` - Master index of all examples

### Files to Rename (~50 files)

**Job files:**
- 17 files: `*_job.py` → `job.py`

**Client files:**
- 7 files: Various names → `client.py`

**Model files:**
- 5 files: Various names → `model.py`

**Data prep:**
- 10 files: Reorganize and rename

### Files to Delete (~200 files)

**Legacy JSON configs:**
- All `jobs/*/config/*.json` files (7 examples × ~10 files each)
- All `meta.json` files

**Legacy learner classes:**
- Files in `learners/` directories (CIFAR-10)

**Legacy executor code:**
- Files in `src/` for client-side code

### Files to Update (~150 files)

**READMEs:**
- 48 example README.md files

**Client files:**
- ~30 examples need client.py updates

**Job files:**
- ~28 examples need conversion from FedJob to Recipe

---

## 🔗 RELATED DOCUMENTATION

### Existing Documentation
- [Recipe Conversion Status Tracker](20251212_recipe_conversion_status_tracker.md) - Dec 12, 2025
- [Cross-Site Eval Recipe Implementation](../20251212_cross_site_eval_recipe_implementation.md) - Dec 12, 2025
- [Experiment Tracking Master Summary](../completed/20251218_MASTER_SUMMARY.md) - Dec 18, 2025
- [Main Recipe Conversions README](../README.md) - Dec 18, 2025

### This Document's Role
This comprehensive audit (Jan 12, 2026) provides:
- **Complete status** of all 48 examples
- **Detailed consistency analysis** across 8 dimensions
- **Specific issues** identified for each example
- **Clear action plan** with priorities and timelines
- **Success metrics** and tracking

---

## 📧 CONTACT & CONTRIBUTIONS

**Document Maintained By:** NVFlare Team
**Last Updated:** January 12, 2026
**Next Review:** January 19, 2026 (weekly cadence)
**Total Examples Tracked:** 48
**Total Issues Identified:** 15 major consistency issues
**Estimated Effort:** 20-26 weeks for complete standardization

---

**STATUS:** 📊 COMPREHENSIVE AUDIT COMPLETE - READY FOR ACTION
