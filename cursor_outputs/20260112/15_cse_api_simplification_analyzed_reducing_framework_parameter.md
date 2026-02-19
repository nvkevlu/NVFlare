# Cross-Site Evaluation API Simplification Analysis
**Date**: January 12, 2026  
**Context**: PR Review Feedback on `add_cross_site_evaluation` Complexity

---

## 📋 Summary of Feedback

The PR review raised critical concerns about the cognitive load and complexity of the Cross-Site Evaluation (CSE) API:

> "this example should be significantly simplified. Even with Recipe, you have to know so much to understand what it does"

**Key Pain Points Identified**:
1. **Model Locator Abstraction**: Users don't understand what it is or why they need it
2. **Model Persistor Over-Engineering**: 90% of users just want to load from files, not abstract storage layers
3. **Too Many Parameters**: `add_cross_site_evaluation(model_locator_type, model_locator_config, persistor_id)` creates mental overload
4. **Opaque Behavior**: Even looking at examples, it's unclear what the code does

---

## 🎯 The Core Problem

### What Users Actually Want
```python
# User's mental model:
"I have pre-trained models in a directory. Evaluate them across all sites."
```

### What They Currently Need to Understand
```python
# Current API requires understanding:
- CrossSiteModelEval controller
- NPModelLocator vs PTModelLocator vs TFModelLocator
- Model persistor classes (NPModelPersistor, PTModelPersistor, etc.)
- model_dir parameter
- model_name dictionary structure
- ValidationJsonGenerator widget
- NPValidator vs PTValidator
- persistor_id indirection
- model_locator_config dictionary structure
```

**Complexity Count**: ~10 concepts just to evaluate pre-trained models

---

## 🔍 Current Complexity Breakdown

### Example: NumPy Cross-Site Evaluation

#### Current "Simple" API
```python
from nvflare.app_common.np.recipes import NumpyFedAvgRecipe
from nvflare.recipe.utils import add_cross_site_evaluation

recipe = NumpyFedAvgRecipe(...)

# What does this actually do? 🤔
add_cross_site_evaluation(
    recipe=recipe,
    model_locator_type="numpy",  # Why is this separate from recipe type?
    model_locator_config={       # Why a config dict instead of direct params?
        "model_dir": "server_models",
        "model_name": {"server": "server.npy"}  # Why a nested dict?
    },
    persistor_id=None  # What is this? Why might I need it?
)

# Wait, also need to manually add validator!
from nvflare.app_common.np.np_validator import NPValidator
recipe.job.to_clients(NPValidator(...))
```

#### Current "Standalone CSE" Recipe
```python
from nvflare.app_common.np.recipes import NumpyCrossSiteEvalRecipe

recipe = NumpyCrossSiteEvalRecipe(
    model_dir="server_models",           # This makes sense
    model_name={"server": "server.npy"}  # Why a dict for one model?
)
```

**Problems**:
- Two different approaches for same goal (training+CSE vs standalone CSE)
- `model_name` dict structure is confusing (implies multiple models, but usually just one)
- `model_locator_config` adds indirection without clear benefit
- `persistor_id` is mysterious (None by default, so why mention it?)

---

## 💡 Proposed Simplification Approaches

### Option A: Radical Simplification (80/20 Rule)

**Design Principle**: Make the 80% common case trivial, keep 20% advanced cases possible

```python
# Most users just want this:
recipe.add_cross_site_evaluation(
    model_dir="server_models"  # Done! Framework auto-detected from recipe
)

# Advanced users can still customize:
recipe.add_cross_site_evaluation(
    model_dir="server_models",
    model_pattern="*.npy",           # Evaluate all .npy files
    custom_validator=MyValidator(),  # Override auto-detection
    timeout=1200                     # Override defaults
)

# Power users can go full custom:
recipe.add_cross_site_evaluation(
    model_locator=CustomLocator(...),  # Escape hatch for 1% cases
    validator=CustomValidator(...)
)
```

**Implementation Requirements**:
1. **Auto-detect framework** from recipe type:
   - `NumpyFedAvgRecipe` → use `NPModelLocator` + `NPValidator`
   - `FedAvgRecipe` (PyTorch) → use `PTModelLocator` + `PTValidator`
   - `TFFedAvgRecipe` → use `TFModelLocator` + `TFValidator`

2. **Smart defaults**:
   - `model_dir` defaults to `"models"` or auto-discovered from persistor
   - `model_name` defaults to `{"server": "<framework_extension>"}` (e.g., `server.npy`)
   - Auto-add appropriate validator to clients

3. **Eliminate indirection**:
   - `model_dir` is a direct parameter, not `model_locator_config["model_dir"]`
   - Framework type inferred, not `model_locator_type="numpy"`
   - `persistor_id` handled internally via `recipe.job.comp_ids`

**Pros**:
- **Dramatic reduction in cognitive load**
- Simple mental model: "just pass the directory"
- Follows principle of least surprise
- Progressive disclosure: advanced options available but hidden

**Cons**:
- Requires breaking API change (major version bump)
- Auto-detection magic can be confusing if it guesses wrong
- Risk of over-simplifying and losing flexibility

---

### Option B: Incremental Simplification (Backward Compatible)

**Design Principle**: Keep current API, add convenience wrappers

```python
# New simplified API (preferred)
recipe.enable_cross_site_evaluation(
    model_dir="server_models"
)

# Old detailed API (deprecated but supported)
add_cross_site_evaluation(
    recipe=recipe,
    model_locator_type="numpy",
    model_locator_config={"model_dir": "server_models"},
    persistor_id=None
)
```

**Implementation Requirements**:
1. Add new `recipe.enable_cross_site_evaluation()` method to `Recipe` base class
2. Keep `add_cross_site_evaluation()` utility function for backward compatibility
3. Deprecation warnings guide users to new API
4. Documentation emphasizes new API

**Pros**:
- No breaking changes
- Smooth migration path
- Can test new API alongside old one

**Cons**:
- Two APIs doing the same thing (confusion)
- Technical debt from supporting both
- Still requires eventual deprecation/removal

---

### Option C: Flatten Parameters (Middle Ground)

**Design Principle**: Reduce nesting and indirection without changing architecture

```python
# Before (current):
add_cross_site_evaluation(
    recipe=recipe,
    model_locator_type="numpy",
    model_locator_config={
        "model_dir": "server_models",
        "model_name": {"server": "server.npy"}
    },
    persistor_id=None
)

# After (flattened):
add_cross_site_evaluation(
    recipe=recipe,
    model_dir="server_models",              # Direct parameter
    model_file="server.npy",                # Simplified from model_name dict
    framework="numpy",                      # Or auto-detect from recipe
    auto_add_validator=True                 # Explicit control
)
```

**Implementation Requirements**:
1. Extract nested parameters to top level
2. Simplify `model_name` dict to single `model_file` string (for common case)
3. Make `persistor_id` internal/hidden
4. Add `auto_add_validator` flag with default `True`

**Pros**:
- Moderate complexity reduction
- Clearer parameter names
- Less nesting

**Cons**:
- Still requires understanding multiple concepts
- Doesn't address fundamental abstraction complexity
- Partial solution to a deeper problem

---

## 🚧 Implementation Challenges

### 1. Framework Auto-Detection
**Challenge**: How to reliably detect NumPy vs PyTorch vs TensorFlow?

**Current State**:
- Recipe classes exist: `NumpyFedAvgRecipe`, `FedAvgRecipe` (PT), etc.
- Could use `isinstance()` checks or recipe metadata

**Considerations**:
- What if user creates custom recipe?
- What if recipe supports multiple frameworks?
- Need fallback mechanism for ambiguous cases

**Proposed Solution**:
```python
# Add framework metadata to Recipe base class
class Recipe:
    framework: str = "unknown"  # Subclasses override

class NumpyFedAvgRecipe(Recipe):
    framework: str = "numpy"

class FedAvgRecipe(Recipe):
    framework: str = "pytorch"
```

---

### 2. Validator Auto-Addition
**Challenge**: We already struggled with this - when to auto-add validators?

**Current Issue**:
- `NumpyFedAvgRecipe` doesn't add validators
- `add_cross_site_evaluation` doesn't auto-add validators
- Users must manually add `NPValidator` → runtime failures

**Proposed Solution**:
```python
# Make it explicit and default to True
def add_cross_site_evaluation(
    recipe,
    model_dir,
    auto_configure_clients=True  # New parameter with safe default
):
    if auto_configure_clients:
        # Auto-add appropriate validator based on framework
        validator = _get_validator_for_framework(recipe.framework)
        recipe.job.to_clients(validator, tasks=[AppConstants.TASK_VALIDATION])
```

**Trade-off**: Magic vs Explicitness
- Pro: Works out of the box for 95% of users
- Con: Can conflict if user already configured clients
- Mitigation: Check if validator already exists, skip if present

---

### 3. Model Naming Complexity
**Challenge**: Current `model_name` dict allows multiple models, but confuses single-model case

**Current API**:
```python
model_name = {
    "server": "server.npy",
    "round_0": "model_round_0.npy",
    "round_5": "model_round_5.npy",
    "best": "best_model.npy"
}
```

**User Confusion**:
- "I just have ONE model, why a dict?"
- "What's the key supposed to be?"
- "Is 'server' special?"

**Proposed Solution - Support Both**:
```python
# Simple case: just pass filename
add_cross_site_evaluation(recipe, model_file="my_model.npy")

# Advanced case: multiple models
add_cross_site_evaluation(recipe, models={
    "baseline": "baseline.npy",
    "optimized": "optimized_v2.npy"
})
```

**Implementation**:
```python
def add_cross_site_evaluation(
    recipe,
    model_dir,
    model_file: Optional[str] = None,  # Single model (common)
    models: Optional[dict] = None,     # Multiple models (advanced)
):
    if model_file and models:
        raise ValueError("Specify either model_file or models, not both")
    
    if model_file:
        # Convert to model_name dict internally
        model_name = {"default": model_file}
    elif models:
        model_name = models
    else:
        # Smart default
        model_name = {"server": f"server.{_get_extension(recipe.framework)}"}
```

---

### 4. Persistor Abstraction
**Challenge**: 90% of users load from files, 10% need S3/database/custom storage

**Current Over-Engineering**:
- Must understand `NPModelPersistor`, `PTModelPersistor`, etc.
- Persistor ID indirection
- Complex configuration

**Reality Check**:
```python
# What 90% of users need:
model = np.load(f"{model_dir}/{model_file}")

# What current API requires:
persistor = NPModelPersistor()
model = persistor.load_model(FLContext)  # Requires FLContext, model_file inference, etc.
```

**Proposed Solution - Two-Tier API**:
```python
# Tier 1: File-based (default, no persistor exposed)
add_cross_site_evaluation(
    recipe,
    model_dir="path/to/models",  # Just works!
)

# Tier 2: Custom storage (advanced)
add_cross_site_evaluation(
    recipe,
    model_loader=S3ModelLoader(bucket="my-models"),  # Custom loader
)
```

**Implementation Strategy**:
1. Create default file-based loader (no persistor abstraction exposed)
2. Advanced users can pass custom loader that implements simple interface:
   ```python
   class ModelLoader(Protocol):
       def load(self, model_name: str) -> Any:
           """Load and return model"""
   ```
3. Internally wrap in persistor if needed for compatibility

---

### 5. Backward Compatibility
**Challenge**: Existing code uses current API

**Impact Assessment**:
- **Public Examples**: ~5 examples use `add_cross_site_evaluation`
- **User Code**: Unknown, but likely minimal (CSE is new feature)
- **Documentation**: Multiple pages reference current API

**Migration Strategies**:

**Strategy A - Clean Break (NVFlare 3.0)**:
- Remove old API entirely
- Update all examples
- Clear migration guide

**Strategy B - Deprecation Path (NVFlare 2.6+)**:
- NVFlare 2.6: Add new API, deprecate old (warnings)
- NVFlare 2.7-2.9: Both APIs supported
- NVFlare 3.0: Remove old API

**Strategy C - Alias Approach**:
- New API calls old API with defaults
- No actual deprecation needed
- Example:
  ```python
  def enable_cross_site_evaluation(recipe, model_dir, **kwargs):
      # New simple API
      return add_cross_site_evaluation(
          recipe=recipe,
          model_locator_type=_infer_framework(recipe),
          model_locator_config={"model_dir": model_dir, **kwargs}
      )
  ```

---

## 📊 Complexity Comparison

### Current API Mental Model
```
User wants CSE
    ↓
Must understand CrossSiteModelEval
    ↓
Must choose model locator type
    ↓
Must understand model locator config structure
    ↓
Must understand model_name dict format
    ↓
Must understand persistor_id concept
    ↓
Must manually add validators
    ↓
Must understand ValidationJsonGenerator
    ↓
Finally: CSE works
```
**Cognitive Load**: 8 concepts, 3-4 files to read

---

### Proposed Simplified API Mental Model (Option A)
```
User wants CSE
    ↓
Call recipe.add_cross_site_evaluation(model_dir="path")
    ↓
CSE works
```
**Cognitive Load**: 1 concept, 0-1 files to read

---

## ✅ Recommended Path Forward

### Phase 1: Analysis & Design (1-2 weeks)
1. **Survey existing usage**:
   - Grep codebase for `add_cross_site_evaluation` usage
   - Check if any advanced features are actually used
   - Validate "90% use files" assumption

2. **Design new API**:
   - Write API proposals with examples
   - Get feedback from team and early users
   - Prototype in branch

3. **Document rationale**:
   - Why simplification matters
   - Trade-offs made
   - Migration guide

### Phase 2: Implementation (2-3 weeks)
1. **Implement Option A (Radical Simplification)**:
   - Add framework detection to Recipe base class
   - Create simplified `add_cross_site_evaluation` with smart defaults
   - Add `model_file` parameter for single-model case
   - Implement auto-validator-addition with safety checks
   - Keep old parameters as deprecated (with warnings)

2. **Update all examples**:
   - hello-numpy-cross-val
   - hello-pt (CSE mode)
   - Any advanced examples using CSE

3. **Update documentation**:
   - Recipe API quick reference
   - CSE user guide
   - Migration guide for existing users

### Phase 3: Testing & Validation (1 week)
1. Ensure backward compatibility (old API still works with warnings)
2. Test all framework types (NumPy, PyTorch, TensorFlow)
3. Integration tests for auto-detection
4. User acceptance testing with simplified examples

### Phase 4: Release & Migration (Ongoing)
1. Release in NVFlare 2.6 with deprecation warnings
2. Monitor user feedback and questions
3. Iterate on API based on real usage
4. Remove deprecated API in NVFlare 3.0

---

## 🎯 Success Metrics

### Quantitative
- **Lines of code reduced** in examples: Target 30-50% reduction
- **Number of imports required**: From ~5 to ~2
- **Time to working example**: From 15-20 min to 2-5 min

### Qualitative
- **User comprehension**: "I understand what this does" without reading docs
- **Discoverability**: Can figure out from IDE autocomplete
- **Error messages**: Clear guidance when something goes wrong

---

## 🤔 Open Questions

1. **Framework Detection Edge Cases**:
   - What if user creates `MyCustomRecipe` without framework metadata?
   - Should we require all Recipe subclasses to declare framework?
   - Fallback to manual specification?

2. **Multiple Models vs Single Model**:
   - Is the multiple-models case (dict) actually needed?
   - Could we always evaluate all models in `model_dir`?
   - Pattern matching: `model_pattern="*.npy"` vs explicit dict?

3. **Validator Configuration**:
   - Some validators need custom config (e.g., metrics to compute)
   - How to support customization while keeping API simple?
   - Pass validator kwargs through `add_cross_site_evaluation`?

4. **Storage Abstraction Value**:
   - Do 10% of users actually need non-file storage?
   - Or is this premature optimization?
   - Could custom storage be a separate advanced feature?

5. **Recipe Method vs Utility Function**:
   - Should CSE be `recipe.add_cross_site_evaluation()` (method)?
   - Or `add_cross_site_evaluation(recipe)` (function)?
   - Method is more discoverable, function is more flexible

---

## 💭 Final Thoughts

**The Core Issue**: We've exposed too many internal abstractions (locators, persistors, config dicts) to users who just want to evaluate models.

**The Root Cause**: Building a general framework led to over-engineering for the common case.

**The Solution**: Apply the 80/20 rule - make the 80% case trivial, keep the 20% case possible.

**The Quote to Remember**:
> "Simple things should be simple, complex things should be possible." - Alan Kay

Right now, even simple things (evaluate models in a directory) require understanding complex abstractions. We need to invert this.

---

## 📝 Concrete Next Steps (If We Proceed)

1. **Immediate**: Create design doc with proposed API (this document serves as starting point)
2. **Week 1**: Prototype simplified API in feature branch
3. **Week 2**: Update hello-numpy-cross-val example to use new API
4. **Week 3**: Get team review and user feedback on prototype
5. **Week 4**: Finalize API design based on feedback
6. **Then**: Implement, test, document, release

**Decision Needed**: Do we proceed with simplification? Which option (A, B, or C)?

