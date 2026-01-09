# Experiment Tracking Examples - Recipe Conversion Plan

**Date**: December 18, 2025
**Status**: Ready to Proceed ✅

---

## 📋 Executive Summary

The experiment tracking examples demonstrate how to add MLflow, TensorBoard, and Weights & Biases tracking to FL jobs. They currently use the **legacy FedJob API** with manual receiver configuration.

**Good News**: We already have a `add_experiment_tracking()` utility in `nvflare.recipe.utils` that makes this trivial!

**Conversion Strategy**: Convert examples to use `FedAvgRecipe` + `add_experiment_tracking()` utility instead of manually configuring receivers.

---

## 🎯 Current State Analysis

### Examples to Convert

| Example | Location | Current API | Lines | Complexity |
|---------|----------|-------------|-------|------------|
| **TensorBoard** | `examples/advanced/experiment-tracking/tensorboard/` | FedJob | 36 | Simple |
| **MLflow** (3 jobs) | `examples/advanced/experiment-tracking/mlflow/` | FedAvgJob | 84 | Medium |
| **Weights & Biases** | `examples/advanced/experiment-tracking/wandb/` | FedJob | 128 | Complex |

### Current Implementation Pattern

All examples follow this pattern:
```python
# OLD PATTERN - Legacy FedJob API
from nvflare import FedJob
from nvflare.app_opt.tracking.mlflow.mlflow_receiver import MLflowReceiver

job = FedJob(name="example")

# Manually add receiver
receiver = MLflowReceiver(tracking_uri="...", kw_args={...})
job.to(receiver, "server")

# Manually add controller
controller = FedAvg(...)
job.to(controller, "server")

# Manually add executor for each client
for i in range(n_clients):
    executor = ScriptRunner(script="train.py")
    job.to(executor, f"site-{i+1}")
```

---

## ✨ New Pattern - Recipe API

### Using the Built-in Utility

```python
# NEW PATTERN - Recipe API + Utility
from nvflare.app_opt.pt.recipes import FedAvgRecipe
from nvflare.recipe.utils import add_experiment_tracking

# 1. Create recipe (handles controller + executors automatically)
recipe = FedAvgRecipe(
    name="fedavg_mlflow",
    min_clients=2,
    num_rounds=5,
    initial_model=SimpleNetwork(),
    train_script="src/train_script.py",
)

# 2. Add experiment tracking with one line
add_experiment_tracking(
    recipe=recipe,
    tracking_type="mlflow",  # or "tensorboard" or "wandb"
    tracking_config={
        "tracking_uri": "file:///tmp/mlruns",
        "kw_args": {
            "experiment_name": "nvflare-experiment",
            "run_name": "fedavg-run",
        }
    }
)

# 3. Run
recipe.run()
```

### Benefits

✅ **70% less code** - From 84 lines to ~25 lines
✅ **Clearer intent** - Separation of training workflow and tracking
✅ **Reusable** - Same pattern for all 3 tracking frameworks
✅ **Type-safe** - Recipe validates parameters
✅ **Consistent** - Matches other recipe-based examples

---

## 📦 Conversion Details

### 1. TensorBoard Example ⚡ SIMPLE

**Current**: `examples/advanced/experiment-tracking/tensorboard/jobs/tensorboard-streaming/code/fl_job.py`

**Status**: 36 lines, uses FedJob + manual TBAnalyticsReceiver

**Conversion**:
```python
# Before (36 lines)
from nvflare import FedJob
from nvflare.app_opt.pt.job_config.model import PTModel
# ... 10 more imports

job = FedJob(name="fedavg")
comp_ids = job.to(PTModel(SimpleNetwork()), "server")
controller = FedAvg(num_clients=2, num_rounds=5, persistor_id=comp_ids["persistor_id"])
job.to(controller, "server")
# ... 20 more lines

# After (~25 lines)
from nvflare.app_opt.pt.recipes import FedAvgRecipe
from nvflare.recipe.utils import add_experiment_tracking

recipe = FedAvgRecipe(
    name="fedavg_tensorboard",
    min_clients=2,
    num_rounds=5,
    initial_model=SimpleNetwork(),
    train_script="src/train_script.py",
)

add_experiment_tracking(recipe, "tensorboard")
recipe.run()
```

**Files to Update**:
- `fl_job.py` → `job.py` (rename + simplify)
- `README.md` (update instructions)

---

### 2. MLflow Examples ⚙️ MEDIUM

**Current**: 3 job variations in `examples/advanced/experiment-tracking/mlflow/jobs/`

| Job | Purpose | Current Lines |
|-----|---------|---------------|
| `hello-pt-mlflow` | Basic MLflow tracking | 84 |
| `hello-pt-mlflow-client` | Site-specific tracking | ~90 |
| `hello-lightning-mlflow` | Lightning integration | ~85 |

**All use**: `FedAvgJob` + manually configured `MLflowReceiver`

**Conversion Strategy**:

**A. Server-side tracking** (`hello-pt-mlflow`):
```python
from nvflare.app_opt.pt.recipes import FedAvgRecipe
from nvflare.recipe.utils import add_experiment_tracking

recipe = FedAvgRecipe(
    name="fedavg_mlflow",
    min_clients=2,
    num_rounds=5,
    initial_model=SimpleNetwork(),
    train_script="src/train_script.py",
)

# Centralized tracking to server
add_experiment_tracking(
    recipe=recipe,
    tracking_type="mlflow",
    tracking_config={
        "tracking_uri": "file:///tmp/mlruns",
        "kw_args": {
            "experiment_name": "nvflare-fedavg-experiment",
            "run_name": "nvflare-fedavg-with-mlflow",
        }
    }
)

recipe.run()
```

**B. Client-side tracking** (`hello-pt-mlflow-client`):
```python
# For site-specific tracking, need to add receivers to each client
# This is slightly more complex but still cleaner than current approach

from nvflare.app_opt.tracking.mlflow.mlflow_receiver import MLflowReceiver

recipe = FedAvgRecipe(...)

# Add MLflow receiver to each client
for site_name in ["site-1", "site-2"]:
    receiver = MLflowReceiver(
        tracking_uri=f"file:///tmp/mlruns_{site_name}",
        kw_args={"experiment_name": f"site-{site_name}-experiment"}
    )
    recipe.job.to_client(receiver, site_name, "mlflow_receiver")
```

**C. Lightning integration** (`hello-lightning-mlflow`):
```python
# Same as A, but uses Lightning's FedAvgRecipe
from nvflare.app_opt.lightning.recipes import FedAvgRecipe

recipe = FedAvgRecipe(
    name="lightning_mlflow",
    min_clients=2,
    num_rounds=5,
    initial_model=LitNet(),
    train_script="src/client.py",
)

add_experiment_tracking(recipe, "mlflow", tracking_config={...})
recipe.run()
```

**Files to Update**:
- `hello-pt-mlflow/code/fl_job.py` → `job.py`
- `hello-pt-mlflow-client/code/fl_job.py` → `job.py`
- `hello-lightning-mlflow/code/fl_job.py` → `job.py`
- Each `README.md` (3 files)

---

### 3. Weights & Biases Example 🔥 COMPLEX

**Current**: `examples/advanced/experiment-tracking/wandb/wandb_job.py`

**Status**: 128 lines, most complex of all examples

**Complexity Sources**:
- Supports both server-side AND client-side tracking (configurable)
- Uses both FedAvg AND CrossSiteEval controllers
- Custom argument parsing
- ConvertToFedEvent widgets

**Conversion**:
```python
from nvflare.app_opt.pt.recipes import FedAvgRecipe
from nvflare.recipe.utils import add_experiment_tracking

def main():
    args = define_parser()  # Keep CLI args

    # Create FedAvg recipe
    recipe = FedAvgRecipe(
        name="wandb",
        min_clients=args.n_clients,
        num_rounds=args.num_rounds,
        initial_model=Net(),
        train_script=args.script,
    )

    # Add WandB tracking
    wandb_config = {
        "mode": "online",
        "wandb_args": {
            "project": "wandb-experiment",
            "name": "wandb",
            "tags": ["baseline"],
            "job_type": "train-validate",
            "config": {"architecture": "CNN", "dataset_id": "CIFAR10"},
        }
    }

    if args.streamed_to_server:
        add_experiment_tracking(recipe, "wandb", wandb_config)

    if args.streamed_to_clients:
        # Add per-client tracking
        from nvflare.app_opt.tracking.wandb.wandb_receiver import WandBReceiver
        for site in ["site-1", "site-2"]:
            receiver = WandBReceiver(**wandb_config)
            recipe.job.to_client(receiver, site, "wandb_receiver")

    # For cross-site eval, create separate recipe or add to workflow
    # TODO: Decide on pattern for combining FedAvg + CrossSiteEval

    recipe.run()
```

**Note**: This example combines two workflows (FedAvg + CrossSiteEval). We need to decide:
1. Keep as single job with two controllers (current approach)?
2. Split into two separate jobs (cleaner)?
3. Create a combined recipe?

**Recommendation**: Split into two examples:
- `wandb_fedavg.py` - Training with WandB
- `wandb_cse.py` - Cross-site eval with WandB (use `NumpyCrossSiteEvalRecipe` + tracking)

**Files to Update**:
- `wandb_job.py` → Split into `job_train.py` + `job_eval.py` (or keep combined with clear separation)
- `README.md` (update instructions)

---

## 🔍 Key Decisions Needed

### 1. Client-Side Tracking API ⚠️

**Issue**: `add_experiment_tracking()` currently only adds to server:
```python
# From nvflare/recipe/utils.py line 59
recipe.job.to_server(receiver, "receiver")  # ⬅️ Only server
```

**Options**:
- **A. Extend utility** - Add `target` parameter:
  ```python
  add_experiment_tracking(recipe, "mlflow", config, target="server")  # default
  add_experiment_tracking(recipe, "mlflow", config, target="site-1")  # per-client
  ```
- **B. Manual for clients** - Keep utility for server-only, document manual pattern for clients
- **C. New utility** - Create `add_client_tracking()` companion function

**Recommendation**: Option A - Extend utility with optional `target` parameter

### 2. WandB Example Structure ⚠️

**Issue**: Current example combines FedAvg + CrossSiteEval in one job (unusual pattern)

**Options**:
- **A. Keep combined** - Convert both to recipes in single file
- **B. Split examples** - Separate training and evaluation
- **C. Create combined recipe** - New recipe that does both

**Recommendation**: Option B - Split into two focused examples

### 3. README Documentation Strategy

**Options**:
- **A. Minimal** - Just show the new recipe-based code
- **B. Migration guide** - Show before/after comparison
- **C. Comprehensive** - Cover all tracking options (server/client/mixed)

**Recommendation**: Option C - These are tutorial examples, should be comprehensive

---

## 📝 Implementation Plan

### Phase 1: Enhance Utility (if needed) 🛠️
**Time**: 1-2 hours
**Effort**: Low

1. Extend `add_experiment_tracking()` to support client-side tracking
2. Add tests for new functionality
3. Update utility docstrings

### Phase 2: Convert TensorBoard Example ⚡
**Time**: 1 hour
**Effort**: Low

1. Convert `fl_job.py` → `job.py` using `FedAvgRecipe`
2. Add `add_experiment_tracking()` call
3. Update README with new pattern
4. Test with simulator

### Phase 3: Convert MLflow Examples ⚙️
**Time**: 3-4 hours
**Effort**: Medium

1. Convert `hello-pt-mlflow` (server tracking)
2. Convert `hello-pt-mlflow-client` (client tracking)
3. Convert `hello-lightning-mlflow` (Lightning)
4. Update all 3 READMEs
5. Test all variations

### Phase 4: Convert WandB Example 🔥
**Time**: 3-4 hours
**Effort**: Medium-High

1. Decide on structure (split vs combined)
2. Convert to recipe(s)
3. Handle both server and client tracking
4. Update README with comprehensive guide
5. Test all configurations

### Phase 5: Update Parent README 📚
**Time**: 30 min
**Effort**: Low

1. Update `experiment-tracking/README.md`
2. Add recipe conversion notes
3. Link to utility documentation

### Phase 6: Testing 🧪
**Time**: 2 hours
**Effort**: Medium

1. Create integration tests for each example
2. Verify tracking works end-to-end
3. Test with actual MLflow/TensorBoard/WandB backends

---

## ✅ Success Criteria

- [ ] All experiment tracking examples use Recipe API
- [ ] `add_experiment_tracking()` utility supports both server and client targets
- [ ] Examples are simpler and more maintainable (50-70% reduction in code)
- [ ] READMEs clearly document how to add tracking to any recipe
- [ ] All examples run successfully with simulator
- [ ] Integration tests pass
- [ ] No breaking changes to existing tracking APIs

---

## 🎓 Learning Resources Needed

For implementation, will need to reference:
- `nvflare/recipe/utils.py` - Current tracking utility
- `nvflare/app_opt/tracking/*/` - Receiver implementations
- `examples/hello-world/hello-pt/job.py` - Recipe pattern
- `docs/programming_guide/experiment_tracking.rst` - User documentation

---

## 📊 Estimated Total Effort

| Phase | Time | Complexity |
|-------|------|------------|
| Utility Enhancement | 1-2h | Low |
| TensorBoard | 1h | Low |
| MLflow (3 examples) | 3-4h | Medium |
| WandB | 3-4h | Medium-High |
| Documentation | 1h | Low |
| Testing | 2h | Medium |
| **TOTAL** | **11-14h** | **Medium** |

---

## 🚀 Ready to Proceed?

**Status**: ✅ Plan is complete and ready for implementation

**Next Steps**:
1. Confirm decisions on:
   - Client-side tracking API design
   - WandB example structure
2. Start with Phase 1 (utility enhancement)
3. Proceed through phases sequentially

**Questions for User**:
1. Should we extend `add_experiment_tracking()` to support client-side tracking, or keep it server-only?
2. Should WandB example be split into two separate examples, or stay combined?
3. Any other tracking examples we should include while we're at it?
