# XGBoost Recipe Conversion Plan

**Date**: January 13, 2026  
**Scope**: Convert 3 XGBoost examples from FedJob API to Recipe API  
**Priority**: 🔴 HIGH - User requested, critical gap in recipe coverage

---

## 📊 Current State Analysis

### XGBoost Examples Status

| Example | Current API | Files | Status | Priority | Recipe Needed |
|---------|-------------|-------|--------|----------|---------------|
| **fedxgb (horizontal histogram)** | FedJob | `xgb_fl_job_horizontal.py` | ❌ Not converted | 🔴 HIGH | `XGBHistogramRecipe` |
| **fedxgb (vertical)** | FedJob | `xgb_fl_job_vertical.py`, `xgb_fl_job_vertical_psi.py` | ❌ Not converted | 🔴 HIGH | `XGBVerticalRecipe` |
| **fedxgb_secure** | FedJob | `xgb_fl_job.py`, `xgb_vert_eval_job.py` | ❌ Not converted | 🟡 MEDIUM | `XGBVerticalRecipe` + HE |
| **tree-based-models** | Recipe API | `job.py` | ✅ Converted | - | Existing recipe |

**Summary**: 1/4 converted (25%), 3 remaining

---

## 🔍 Detailed Example Analysis

### 1. fedxgb (Horizontal Histogram) - HIGHEST PRIORITY

**Current File**: `examples/advanced/xgboost/fedxgb/xgb_fl_job_horizontal.py` (261 lines)

**What It Does**:
- Horizontal federated XGBoost with histogram-based algorithm
- Supports multiple algorithms: histogram, histogram_v2, bagging, cyclic
- Uses HIGGS dataset with site-based splitting
- TensorBoard tracking built-in

**Current Structure**:
```
fedxgb/
├── xgb_fl_job_horizontal.py    ❌ (should be job.py)
├── src/
│   └── higgs_data_loader.py    ⚠️ (should be in root or utils/)
├── utils/
│   ├── prepare_data_horizontal.py  ✅
│   └── baseline_centralized.py     ✅
├── prepare_data.sh                 ✅
├── run_experiment_horizontal_histogram.sh  ✅
└── README.md                       ⚠️ (needs update)
```

**Components Used**:
- Controller: `XGBFedController` (histogram-based)
- Executor: `FedXGBHistogramExecutor`
- Data Loader: `HIGGSDataLoader` (custom)
- Tracking: `TBAnalyticsReceiver`, `TBWriter`, `ConvertToFedEvent`

**Key Parameters**:
```python
# Algorithm selection
training_algo: histogram | histogram_v2 | bagging | cyclic

# Dataset
data_root: /tmp/nvflare/dataset/xgboost_higgs
site_num: 2
split_method: uniform

# Training
round_num: 100
lr_mode: uniform | scaled

# XGBoost params
max_depth: 8
eta: 0.1
objective: binary:logistic
eval_metric: auc
tree_method: hist
nthread: 16
```

**Consistency Issues**:
1. ❌ Wrong filename: `xgb_fl_job_horizontal.py` → should be `job.py`
2. ❌ Client code in `src/` → should be in root or utils/
3. ❌ FedJob API → should be Recipe API
4. ⚠️ Manual TensorBoard setup → should use `add_experiment_tracking()`

**Conversion Complexity**: 🟡 MEDIUM
- Need new `XGBHistogramRecipe` class
- Algorithm selection adds complexity (4 algorithms in one file)
- TensorBoard integration straightforward with existing utility

---

### 2. fedxgb (Vertical) - HIGH PRIORITY

**Current Files**: 
- `examples/advanced/xgboost/fedxgb/xgb_fl_job_vertical.py` (108 lines)
- `examples/advanced/xgboost/fedxgb/xgb_fl_job_vertical_psi.py` (similar)

**What It Does**:
- Vertical federated XGBoost (data features split across sites)
- Requires PSI (Private Set Intersection) for ID alignment
- Uses HIGGS dataset with vertical splitting
- Histogram-based algorithm v2

**Current Structure**:
```
fedxgb/
├── xgb_fl_job_vertical.py         ❌ (should be job.py with --vertical flag)
├── xgb_fl_job_vertical_psi.py     ❌ (should be combined)
├── src/
│   └── vertical_data_loader.py    ⚠️
├── utils/
│   └── prepare_data_vertical.py   ✅
├── prepare_data.sh                ✅
└── run_experiment_vertical.sh     ✅
```

**Components Used**:
- Controller: `XGBFedController` (with `data_split_mode=1` for vertical)
- Executor: `FedXGBHistogramExecutor`
- Data Loader: `VerticalDataLoader` (custom)
- PSI: Required preprocessing step
- Tracking: Same as horizontal

**Key Parameters**:
```python
# Vertical-specific
data_split_mode: 1  # 0=horizontal, 1=vertical
data_split_path: /tmp/nvflare/dataset/xgboost_higgs_vertical/{SITE_NAME}/higgs.data.csv
psi_path: /tmp/nvflare/workspace/works/xgboost_vertical_psi/{SITE_NAME}/...
id_col: uid
label_owner: site-1  # Only one site has labels
train_proportion: 0.8

# Training (similar to horizontal)
site_num: 2
round_num: 100
max_depth: 8
eta: 0.1
```

**Consistency Issues**:
1. ❌ Multiple job files for same example → should be one with flags
2. ❌ Wrong filenames → should be `job.py`
3. ❌ FedJob API → should be Recipe API
4. ⚠️ PSI workflow not well-documented
5. ⚠️ Complex data path formatting with `{SITE_NAME}` placeholder

**Conversion Complexity**: 🔴 HIGH
- Need new `XGBVerticalRecipe` class (more complex than horizontal)
- PSI integration required
- Label owner concept (only one site has labels)
- Vertical data splitting is conceptually different

---

### 3. fedxgb_secure - MEDIUM PRIORITY

**Current Files**:
- `examples/advanced/xgboost/fedxgb_secure/xgb_fl_job.py` (132 lines)
- `examples/advanced/xgboost/fedxgb_secure/xgb_vert_eval_job.py` (evaluation job)

**What It Does**:
- Secure vertical XGBoost with Homomorphic Encryption (HE)
- Protects gradients and splits during vertical training
- Supports both horizontal and vertical modes with `--secure` flag
- Includes standalone training comparison

**Current Structure**:
```
fedxgb_secure/
├── xgb_fl_job.py                  ❌ (should be job.py)
├── xgb_vert_eval_job.py           ❌ (should be integrated or separate eval job)
├── train_standalone/              ⚠️ (mixed with FL code)
│   ├── train_base.py              ✅
│   ├── train_federated.py         ✅
│   └── eval_secure_vertical.py    ✅
├── utils/                         ✅
│   ├── prepare_data_base.py
│   ├── prepare_data_horizontal.py
│   ├── prepare_data_vertical.py
│   └── prepare_data_traintest_split.py
├── prepare_data.sh                ✅
├── run_training_standalone.sh     ✅
├── project.yml                    ⚠️ (what is this?)
└── README.md                      ⚠️ (needs update)
```

**Components Used**:
- Controller: `XGBFedController` (with `secure_training=True`)
- Executor: `FedXGBHistogramExecutor`
- Data Loader: `CSVDataLoader`
- HE: Built into XGBoost controller/executor
- Tracking: Same as others

**Key Parameters**:
```python
# Security
secure: bool  # Enable HE

# Split mode
data_split_mode: horizontal | vertical

# Training
site_num: 3  # Default is 3 sites
round_num: 3  # Shorter for demo
nthread: 16
tree_method: hist

# XGBoost params (smaller for demo)
max_depth: 3
eta: 0.1

# Advanced
client_ranks: {"site-1": 0, "site-2": 1, "site-3": 2}
in_process: True  # For faster simulation
```

**Consistency Issues**:
1. ❌ Wrong filename → should be `job.py`
2. ❌ Multiple job files → evaluation should be integrated or clearly separated
3. ❌ FedJob API → should be Recipe API
4. ⚠️ Standalone code mixed with FL code → unclear organization
5. ❌ Unclear when to use which file
6. ⚠️ `project.yml` file - unclear purpose

**Conversion Complexity**: 🔴 VERY HIGH
- Requires `XGBVerticalRecipe` (dependency on #2)
- HE support must be integrated into recipe
- Evaluation job needs strategy (separate recipe or CSE?)
- Standalone training comparison workflow
- More complex testing (security verification)

---

## 🎯 Conversion Strategy

### Phase 1: Create XGBHistogramRecipe (fedxgb horizontal)

**Estimated Effort**: 8-12 hours

**Recipe Design**:
```python
class XGBHistogramRecipe(Recipe):
    """Recipe for horizontal federated XGBoost with histogram-based algorithm."""
    
    def __init__(
        self,
        name: str = "xgb_histogram",
        min_clients: int = 2,
        num_rounds: int = 100,
        data_loader: Component,
        xgb_params: Optional[dict] = None,
        training_algo: str = "histogram",  # histogram | histogram_v2 | bagging | cyclic
        early_stopping_rounds: int = 2,
    ):
        # Validate training_algo
        if training_algo not in ["histogram", "histogram_v2", "bagging", "cyclic"]:
            raise ValueError(f"Invalid training_algo: {training_algo}")
        
        # Set default XGBoost params
        default_params = {
            "max_depth": 8,
            "eta": 0.1,
            "objective": "binary:logistic",
            "eval_metric": "auc",
            "tree_method": "hist",
            "nthread": 16,
        }
        if xgb_params:
            default_params.update(xgb_params)
        
        # Create job
        job = FedJob(name=name, min_clients=min_clients)
        
        # Add controller based on algorithm
        if training_algo == "histogram":
            controller = XGBFedController()
            executor = FedXGBHistogramExecutor(
                data_loader_id="dataloader",
                num_rounds=num_rounds,
                early_stopping_rounds=early_stopping_rounds,
                metrics_writer_id="metrics_writer",
                xgb_params=default_params,
            )
        elif training_algo == "histogram_v2":
            controller = XGBFedController(
                num_rounds=num_rounds,
                data_split_mode=0,  # horizontal
                secure_training=False,
                xgb_options={"early_stopping_rounds": early_stopping_rounds, "use_gpus": False},
                xgb_params=default_params,
            )
            executor = FedXGBHistogramExecutor(
                data_loader_id="dataloader",
                metrics_writer_id="metrics_writer",
            )
        # ... elif for bagging and cyclic
        
        job.to_server(controller, id="xgb_controller")
        job.to_clients(executor)
        job.to_clients(data_loader, id="dataloader")
        
        self.job = job
        self.framework = FrameworkType.RAW  # For consistency
```

**Conversion Steps**:

1. **Create Recipe Class** (3-4 hours)
   - [ ] Create `nvflare/app_opt/xgboost/recipes/histogram.py`
   - [ ] Implement `XGBHistogramRecipe` with 4 algorithm variants
   - [ ] Add comprehensive docstring
   - [ ] Add parameter validation
   - [ ] Add framework field for CSE compatibility

2. **Update Example** (2-3 hours)
   - [ ] Rename `xgb_fl_job_horizontal.py` → `job.py`
   - [ ] Rewrite using `XGBHistogramRecipe`
   - [ ] Keep same CLI arguments for compatibility
   - [ ] Add experiment tracking with `add_experiment_tracking(recipe, "tensorboard")`

3. **Fix File Structure** (1 hour)
   - [ ] Move `src/higgs_data_loader.py` → `higgs_data_loader.py` (root)
   - [ ] Update all imports
   - [ ] Update README with new structure

4. **Update Documentation** (2-3 hours)
   - [ ] Update `examples/advanced/xgboost/fedxgb/README.md`
   - [ ] Add "What's New with Recipe API" section
   - [ ] Update quickstart commands
   - [ ] Add before/after comparison

5. **Create Tests** (1-2 hours)
   - [ ] Add integration test: `tests/integration_test/test_xgb_histogram_recipe.py`
   - [ ] Test with SimEnv
   - [ ] Verify TensorBoard files created
   - [ ] Test all 4 algorithms

6. **Verify** (30 min)
   - [ ] Run linters
   - [ ] Test locally with real data
   - [ ] Compare results with old FedJob version

---

### Phase 2: Create XGBVerticalRecipe (fedxgb vertical)

**Estimated Effort**: 12-16 hours (more complex)

**Recipe Design**:
```python
class XGBVerticalRecipe(Recipe):
    """Recipe for vertical federated XGBoost.
    
    In vertical FL, different sites have different features for the same samples.
    Requires PSI for ID alignment and one site designated as label owner.
    """
    
    def __init__(
        self,
        name: str = "xgb_vertical",
        min_clients: int = 2,
        num_rounds: int = 100,
        data_loader: Component,  # VerticalDataLoader
        label_owner: str = "site-1",  # Which site has labels
        xgb_params: Optional[dict] = None,
        early_stopping_rounds: int = 3,
        psi_required: bool = True,  # Require PSI preprocessing
    ):
        # Validate label_owner format
        if not label_owner.startswith("site-"):
            raise ValueError(f"label_owner must be 'site-X' format, got: {label_owner}")
        
        # Create job
        job = FedJob(name=name, min_clients=min_clients)
        
        # Vertical uses histogram_v2 controller with data_split_mode=1
        controller = XGBFedController(
            num_rounds=num_rounds,
            data_split_mode=1,  # vertical
            secure_training=False,
            xgb_options={"early_stopping_rounds": early_stopping_rounds, "use_gpus": False},
            xgb_params=xgb_params or {...},
        )
        
        # Vertical executor
        executor = FedXGBHistogramExecutor(
            data_loader_id="dataloader",
            metrics_writer_id="metrics_writer",
            in_process=True,  # Required for vertical
            model_file_name="test.model.json",
        )
        
        job.to_server(controller, id="xgb_controller")
        job.to_clients(executor, tasks=["config", "start"])  # Note: specific tasks
        job.to_clients(data_loader, id="dataloader")
        
        self.job = job
        self.framework = FrameworkType.RAW
        self.label_owner = label_owner
```

**Conversion Steps**:

1. **Create Recipe Class** (4-5 hours)
   - [ ] Create `nvflare/app_opt/xgboost/recipes/vertical.py`
   - [ ] Implement `XGBVerticalRecipe`
   - [ ] Add PSI workflow documentation
   - [ ] Add label owner validation
   - [ ] Add framework field

2. **Consolidate Job Files** (2-3 hours)
   - [ ] Merge `xgb_fl_job_vertical.py` and `xgb_fl_job_vertical_psi.py` → `job.py`
   - [ ] Add `--with-psi` flag if PSI needed
   - [ ] Use `XGBVerticalRecipe`
   - [ ] Simplify data path handling

3. **Fix File Structure** (1 hour)
   - [ ] Move `src/vertical_data_loader.py` → `vertical_data_loader.py`
   - [ ] Update imports
   - [ ] Clean up directory structure

4. **PSI Integration** (2-3 hours)
   - [ ] Document PSI prerequisite clearly
   - [ ] Create helper script for PSI if needed
   - [ ] Add PSI validation in recipe (check if PSI files exist)
   - [ ] Update README with two-step workflow: 1) PSI, 2) Training

5. **Update Documentation** (3-4 hours)
   - [ ] Update `README.md`
   - [ ] Add vertical FL explanation
   - [ ] Document PSI workflow
   - [ ] Explain label owner concept
   - [ ] Add architecture diagram if helpful

6. **Create Tests** (2-3 hours)
   - [ ] Add integration test with mocked PSI
   - [ ] Test label owner validation
   - [ ] Test data split mode
   - [ ] Verify vertical aggregation works

7. **Verify** (30 min)
   - [ ] Run linters
   - [ ] Test with real data + PSI
   - [ ] Compare results with old version

---

### Phase 3: Update fedxgb_secure (with HE)

**Estimated Effort**: 8-10 hours (builds on Phase 2)

**Recipe Design**:
```python
# Extend XGBVerticalRecipe with security
class XGBSecureVerticalRecipe(XGBVerticalRecipe):
    """Secure vertical XGBoost with Homomorphic Encryption."""
    
    def __init__(
        self,
        name: str = "xgb_secure_vertical",
        secure_training: bool = True,  # Enable HE
        **kwargs
    ):
        super().__init__(name=name, **kwargs)
        
        # Modify controller for security
        # (update self.job to enable HE)
        for comp_id, comp in self.job.get_all_components().items():
            if isinstance(comp, XGBFedController):
                comp.secure_training = secure_training
```

**Conversion Steps**:

1. **Create Secure Recipe** (2-3 hours)
   - [ ] Create `nvflare/app_opt/xgboost/recipes/secure_vertical.py`
   - [ ] Extend `XGBVerticalRecipe` with HE
   - [ ] Add `--secure` flag handling
   - [ ] Add security validation

2. **Consolidate Job Files** (2 hours)
   - [ ] Merge `xgb_fl_job.py` and `xgb_vert_eval_job.py` → `job.py`
   - [ ] Use `XGBSecureVerticalRecipe`
   - [ ] Keep standalone training separate (it's for comparison)

3. **Clarify Evaluation Job** (2 hours)
   - [ ] Decide: Integrate into main job OR create separate CSE job
   - [ ] If CSE: Use `add_cross_site_evaluation()` (may need XGBoost support)
   - [ ] Document evaluation workflow

4. **Update Documentation** (2-3 hours)
   - [ ] Update README
   - [ ] Explain HE and security guarantees
   - [ ] Document performance impact
   - [ ] Add security testing instructions

5. **Verify** (30 min)
   - [ ] Test with `--secure` flag
   - [ ] Compare secure vs non-secure results
   - [ ] Verify HE is actually enabled (check logs)

---

## 📋 Implementation Checklist

### Prerequisites
- [ ] Understand XGBoost federated learning algorithms (histogram, bagging, cyclic, vertical)
- [ ] Review existing tree-based recipe (already converted)
- [ ] Review XGBoost NVFlare documentation
- [ ] Understand PSI workflow for vertical FL
- [ ] Understand HE integration in XGBoost

### New Recipes to Create
- [ ] `nvflare/app_opt/xgboost/recipes/histogram.py` - `XGBHistogramRecipe`
- [ ] `nvflare/app_opt/xgboost/recipes/vertical.py` - `XGBVerticalRecipe`
- [ ] `nvflare/app_opt/xgboost/recipes/secure_vertical.py` - `XGBSecureVerticalRecipe` (optional, could be parameter)

### Recipe `__init__.py` Updates
- [ ] Add new recipes to `nvflare/app_opt/xgboost/recipes/__init__.py`

### Example Files to Create/Modify

#### fedxgb (horizontal)
- [ ] Rename: `xgb_fl_job_horizontal.py` → `job.py`
- [ ] Move: `src/higgs_data_loader.py` → `higgs_data_loader.py`
- [ ] Update: `README.md`
- [ ] Keep: `utils/`, `prepare_data.sh`, run scripts

#### fedxgb (vertical)
- [ ] Merge: `xgb_fl_job_vertical.py` + `xgb_fl_job_vertical_psi.py` → `job.py`
- [ ] Move: `src/vertical_data_loader.py` → `vertical_data_loader.py`
- [ ] Update: `README.md`
- [ ] Keep: `utils/`, `prepare_data.sh`, run scripts

#### fedxgb_secure
- [ ] Merge: `xgb_fl_job.py` + `xgb_vert_eval_job.py` → `job.py` (or `job.py` + `eval_job.py`)
- [ ] Keep: `train_standalone/` (comparison baseline)
- [ ] Update: `README.md`
- [ ] Keep: `utils/`, `prepare_data.sh`, run scripts
- [ ] Clarify: `project.yml` purpose or remove

### Testing
- [ ] Create: `tests/integration_test/test_xgb_histogram_recipe.py`
- [ ] Create: `tests/integration_test/test_xgb_vertical_recipe.py`
- [ ] Create: `tests/integration_test/test_xgb_secure_recipe.py`

### Documentation
- [ ] Update: XGBoost main README (`examples/advanced/xgboost/README.md`)
- [ ] Update: Each example README
- [ ] Add: Recipe API examples to docs
- [ ] Document: PSI workflow
- [ ] Document: Vertical FL concepts
- [ ] Document: HE security model

---

## ⚠️ Risks and Challenges

### Technical Challenges

1. **Algorithm Complexity** (🔴 HIGH RISK)
   - XGBoost has 4 different algorithms (histogram, histogram_v2, bagging, cyclic)
   - Each has different controller/executor combinations
   - **Mitigation**: Create one recipe with algorithm parameter, handle internally

2. **Vertical FL Complexity** (🔴 HIGH RISK)
   - Vertical split is fundamentally different from horizontal
   - PSI prerequisite adds workflow complexity
   - Label owner concept needs clear explanation
   - **Mitigation**: Excellent documentation, helper scripts, clear error messages

3. **PSI Integration** (🟡 MEDIUM RISK)
   - PSI is a prerequisite step, not part of main training
   - Path handling with `{SITE_NAME}` placeholders is brittle
   - **Mitigation**: Validate PSI files exist, provide clearer path examples

4. **HE Integration** (🟡 MEDIUM RISK)
   - Security features need careful testing
   - Performance impact significant
   - **Mitigation**: Document expected behavior, provide benchmarks

5. **Multiple Job Files** (🟡 MEDIUM RISK)
   - Current examples have 2-3 job files each
   - Unclear which to use when
   - **Mitigation**: Consolidate into one with flags, clear README

### Non-Technical Challenges

1. **Breaking Changes** (🟡 MEDIUM RISK)
   - Users currently using FedJob API will need to migrate
   - **Mitigation**: Provide migration guide, keep examples working

2. **Testing Complexity** (🟡 MEDIUM RISK)
   - XGBoost training is slower than sklearn
   - Vertical FL requires special setup
   - HE makes testing even slower
   - **Mitigation**: Use small datasets for tests, shorter num_rounds

3. **Documentation Scope** (🟢 LOW RISK)
   - Vertical FL and HE concepts are advanced
   - Need to explain without overwhelming users
   - **Mitigation**: Tiered documentation (quickstart → advanced)

---

## 📊 Success Criteria

### Code Quality
- [ ] All new recipes pass linters (no errors)
- [ ] All examples run successfully with SimEnv
- [ ] Code reduction: 15-20% fewer lines (consistent with other conversions)
- [ ] No breaking changes to data prep or run scripts

### Consistency
- [ ] All job files named `job.py`
- [ ] All client code in root or utils/ (not src/)
- [ ] All examples use Recipe API (no FedJob)
- [ ] Experiment tracking uses `add_experiment_tracking()` utility

### Testing
- [ ] Integration tests for all 3 examples
- [ ] Tests pass in CI
- [ ] Tests cover main code paths (algorithm variants, vertical, secure)

### Documentation
- [ ] READMEs updated with Recipe API examples
- [ ] "What's New" sections added
- [ ] PSI workflow documented
- [ ] Vertical FL concepts explained
- [ ] HE security model documented
- [ ] Migration guide provided

### User Experience
- [ ] Simpler API (fewer imports, clearer parameters)
- [ ] Same CLI arguments (backward compatible)
- [ ] Same data prep workflow (no changes)
- [ ] Same results (accuracy/AUC comparable)
- [ ] Clear error messages for common mistakes

---

## 🎯 Recommended Execution Order

### Week 1: Horizontal Histogram (Highest Priority)
**Days 1-2**: Create `XGBHistogramRecipe` class
**Days 3-4**: Convert `fedxgb` horizontal example
**Day 5**: Testing, documentation, verification

**Deliverable**: Working `XGBHistogramRecipe` with 4 algorithm variants

### Week 2: Vertical (Second Priority)
**Days 1-3**: Create `XGBVerticalRecipe` class (more complex)
**Days 4-5**: Convert `fedxgb` vertical example
**Day 6**: PSI workflow documentation

**Deliverable**: Working `XGBVerticalRecipe` with PSI integration

### Week 3: Secure (Third Priority)
**Days 1-2**: Create `XGBSecureVerticalRecipe` or add `--secure` parameter
**Days 3-4**: Convert `fedxgb_secure` example
**Day 5**: Testing and security verification

**Deliverable**: Working secure vertical XGBoost recipe

### Week 4: Polish and Documentation
**Days 1-2**: Integration tests for all examples
**Days 3-4**: Comprehensive documentation updates
**Day 5**: Final verification, CI, code review

**Deliverable**: Complete XGBoost recipe conversion with tests and docs

---

## 💡 Design Decisions to Make

### 1. Recipe Structure
**Option A**: Three separate recipes
- `XGBHistogramRecipe` (horizontal)
- `XGBVerticalRecipe` (vertical)
- `XGBSecureVerticalRecipe` (secure)

**Option B**: Two recipes with parameters
- `XGBHistogramRecipe(algorithm="histogram")` (horizontal)
- `XGBVerticalRecipe(secure=True)` (vertical with optional security)

**Option C**: One unified recipe
- `XGBRecipe(mode="horizontal", algorithm="histogram")`
- `XGBRecipe(mode="vertical", secure=True)`

**Recommendation**: **Option B** - Balance between simplicity and flexibility

### 2. Algorithm Selection
**Option A**: Separate recipe per algorithm
- `XGBHistogramRecipe`, `XGBBaggingRecipe`, `XGBCyclicRecipe`

**Option B**: Single recipe with algorithm parameter
- `XGBHistogramRecipe(algorithm="histogram")`

**Recommendation**: **Option B** - Consistent with current FedJob approach

### 3. PSI Integration
**Option A**: PSI built into recipe (automatic)
**Option B**: PSI as prerequisite (manual step)
**Option C**: PSI as optional recipe parameter

**Recommendation**: **Option B** - PSI is expensive, users should control when it runs

### 4. Evaluation Job (fedxgb_secure)
**Option A**: Separate `eval_job.py` file
**Option B**: Integrated into main job with flag
**Option C**: Use CSE (`add_cross_site_evaluation()`)

**Recommendation**: **Option C** - Consistent with NVFlare CSE pattern (if XGBoost supports it)

---

## 📝 Notes for Implementation

### Key Imports
```python
# Recipes
from nvflare.app_opt.xgboost.recipes import XGBHistogramRecipe, XGBVerticalRecipe

# Components (if needed for customization)
from nvflare.app_opt.xgboost.histogram_based_v2.fed_controller import XGBFedController
from nvflare.app_opt.xgboost.histogram_based_v2.fed_executor import FedXGBHistogramExecutor

# Data loaders (user provides)
from higgs_data_loader import HIGGSDataLoader
from vertical_data_loader import VerticalDataLoader

# Utilities
from nvflare.recipe.utils import add_experiment_tracking
from nvflare.recipe import SimEnv
```

### Example Recipe Usage (Horizontal)
```python
from nvflare.app_opt.xgboost.recipes import XGBHistogramRecipe
from nvflare.recipe.utils import add_experiment_tracking
from nvflare.recipe import SimEnv
from higgs_data_loader import HIGGSDataLoader

# Create data loader
data_loader = HIGGSDataLoader(
    data_split_filename=f"{data_path}/data_site-{{ID}}.json"
)

# Create recipe
recipe = XGBHistogramRecipe(
    name="xgb_higgs_histogram",
    min_clients=2,
    num_rounds=100,
    data_loader=data_loader,
    algorithm="histogram",  # or histogram_v2, bagging, cyclic
    xgb_params={
        "max_depth": 8,
        "eta": 0.1,
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "tree_method": "hist",
        "nthread": 16,
    },
)

# Add experiment tracking
add_experiment_tracking(recipe, "tensorboard")

# Run
env = SimEnv()
env.run(recipe)
```

### Example Recipe Usage (Vertical)
```python
from nvflare.app_opt.xgboost.recipes import XGBVerticalRecipe
from nvflare.recipe import SimEnv
from vertical_data_loader import VerticalDataLoader

# Create data loader (assumes PSI already run)
data_loader = VerticalDataLoader(
    data_split_path="/path/to/data/{SITE_NAME}/higgs.data.csv",
    psi_path="/path/to/psi/{SITE_NAME}/intersection.txt",
    id_col="uid",
    label_owner="site-1",
    train_proportion=0.8,
)

# Create recipe
recipe = XGBVerticalRecipe(
    name="xgb_vertical",
    min_clients=2,
    num_rounds=100,
    data_loader=data_loader,
    label_owner="site-1",
    xgb_params={
        "max_depth": 8,
        "eta": 0.1,
        "objective": "binary:logistic",
        "eval_metric": "auc",
    },
)

# Run
env = SimEnv()
env.run(recipe)
```

---

## 🔗 Related Documentation

- **XGBoost NVFlare Integration**: `nvflare/app_opt/xgboost/README.md`
- **Histogram-Based Algorithm**: `nvflare/app_opt/xgboost/histogram_based_v2/`
- **Existing Tree-Based Recipe**: (already converted, reference this)
- **PSI Documentation**: `examples/advanced/psi/`
- **Recipe API Guide**: `cursor_outputs/2025-12-31_01_recipe_api_FINAL_GUIDE.md`
- **Recipe Conversion Status**: `cursor_outputs/recipe_conversions/README.md`

---

## ✅ Next Steps

1. **Get User Approval** on this plan
2. **Start with Phase 1**: `XGBHistogramRecipe` (highest priority, simplest)
3. **Create recipe class** first, then convert example
4. **Test incrementally** as we go
5. **Document thoroughly** for each phase

---

_Created: January 13, 2026_  
_Estimated Total Effort: 28-38 hours across 3-4 weeks_  
_Priority: 🔴 HIGH - User requested, critical gap_  
_Dependencies: None (all prerequisites exist in codebase)_
