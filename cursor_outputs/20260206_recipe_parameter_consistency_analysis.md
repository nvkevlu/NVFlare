# Recipe Parameter Consistency Analysis: initial_model → model, initial_ckpt

**Date:** 2026-02-06  
**Scope:** All recipe classes in NVFlare; model-related parameter naming and checkpoint support.  
**Goal:** Identify inconsistencies and document a target API (e.g. `model`, `initial_ckpt`) for future consolidation.

---

## 1. Holger's PR

**Finding:** No reference to "Holger" or a PR by that name appears in this repository (grep over codebase and `cursor_outputs/`). The renaming idea may come from an external PR, discussion, or another branch not present here. If you have a link or branch name, it can be added to this doc.

---

## 2. Current State: Model-Related Parameters by Recipe

### 2.1 Recipes using `initial_model`

| Location | Recipe | Parameter | Type / Notes |
|----------|--------|-----------|--------------|
| `nvflare/recipe/fedavg.py` | FedAvgRecipe (unified) | `initial_model` | Any (nn.Module, tf.keras.Model, dict, None) |
| `nvflare/recipe/cyclic.py` | CyclicRecipe (base) | `initial_model` | Any, optional |
| `nvflare/app_opt/pt/recipes/fedavg.py` | FedAvgRecipe | `initial_model` | Any = None |
| `nvflare/app_opt/pt/recipes/fedavg_he.py` | FedAvgRecipe | `initial_model` | Any = None |
| `nvflare/app_opt/pt/recipes/scaffold.py` | ScaffoldRecipe | `initial_model` | Any = None |
| `nvflare/app_opt/pt/recipes/fedopt.py` | FedOptRecipe | `initial_model` | Any = None |
| `nvflare/app_opt/pt/recipes/cyclic.py` | CyclicRecipe | `initial_model` | Any = None |
| `nvflare/app_opt/pt/recipes/fedeval.py` | FedEvalRecipe | `initial_model` | Any, **required**; must have `.checkpoint` for file load |
| `nvflare/app_opt/tf/recipes/fedavg.py` | FedAvgRecipe | `initial_model` | Any = None |
| `nvflare/app_opt/tf/recipes/scaffold.py` | ScaffoldRecipe | `initial_model` | Any = None |
| `nvflare/app_opt/tf/recipes/fedopt.py` | FedOptRecipe | `initial_model` | Any = None |
| `nvflare/app_opt/tf/recipes/cyclic.py` | CyclicRecipe | `initial_model` | Any = None |
| `nvflare/app_common/np/recipes/fedavg.py` | NumpyFedAvgRecipe | `initial_model` | **list** (required), or ndarray |

### 2.2 Recipe using `model` (inconsistent)

| Location | Recipe | Parameter | Notes |
|----------|--------|-----------|--------|
| `nvflare/edge/tools/edge_fed_buff_recipe.py` | EdgeFedBuffRecipe | **`model`** | `nn.Module`, required. Same semantic as “initial model” but different name. |

### 2.3 Recipes with no model/initial_model

- **XGBoost:** `XGBVerticalRecipe`, `XGBHorizontalRecipe`, `XGBBaggingRecipe` — no `initial_model` / `model` (algorithm-specific config only).
- **Flower:** `FlowerRecipe` — no model parameter; uses `flower_content` and timeouts.

### 2.4 Other model-related parameters

- **FedOpt (PT):** `source_model: str = "model"` — component ID for the model in the job, not the initial model object. Semantically different; no rename needed for consistency with `model`/`initial_model`.
- **Persistor:** `PTFileModelPersistor` has `source_ckpt_file_full_name` for loading from a checkpoint file. Recipes do **not** currently expose a single `initial_ckpt` parameter; Fedeval encodes checkpoint path via `initial_model.checkpoint`.

---

## 3. Checkpoint Loading Today

- **PT:** `PTFileModelPersistor(source_ckpt_file_full_name=...)` loads from file. Recipes do not have a dedicated `initial_ckpt` argument; Fedeval uses `initial_model=LitNet(checkpoint="pretrained_model.pt")` and passes `initial_model.checkpoint` into the persistor.
- **Unified/LLM:** `initial_model` can be a **dict** (e.g. `{"path": "module.ClassName", "args": {...}}`) for deferred/server-side instantiation — no checkpoint path in the current pattern.
- **Gap:** There is no standard recipe-level “load initial weights from this checkpoint path” parameter (`initial_ckpt`) across PT/TF recipes.

---

## 4. Inconsistencies Summary

| Issue | Where | Recommendation |
|-------|--------|-----------------|
| Naming | EdgeFedBuffRecipe uses `model`; all others use `initial_model` | Standardize on one name (see below). |
| Semantics | `initial_model` already allows: instance, dict, None. “model” would allow same. | Rename to `model` is semantically fine if we keep same types. |
| Checkpoint-from-file | Only Fedeval supports “start from checkpoint file” via `initial_model.checkpoint`. No generic `initial_ckpt`. | Add optional `initial_ckpt` (path) and wire to persistor where applicable. |
| NumPy | `initial_model` is **required** and must be list/ndarray (no dict/object like PT/TF). | If we add `model`, NumPy recipe could accept `model` with same requirement. |

---

## 5. Proposed Target API (for consolidation)

### 5.1 Naming

- **Primary parameter:** `model` (replacing `initial_model` where it means “initial model to start training”).
  - **Allow:** direct initialization (e.g. `nn.Module`, `tf.keras.Model`), **dict** (params or config, e.g. LLM `{"path": "...", "args": {...}}`), and `None` where the recipe allows it.
- **EdgeFedBuffRecipe:** Already uses `model`; would align with the rest once others rename `initial_model` → `model`.
- **Backward compatibility:** Either keep `initial_model` as a deprecated alias for `model`, or do a single breaking rename with a clear migration note.

### 5.2 Checkpoint path

- **New parameter:** `initial_ckpt: Optional[str] = None` (path to checkpoint file).
  - When set, persistor loads initial weights from this path (e.g. pass through to `PTFileModelPersistor(source_ckpt_file_full_name=initial_ckpt)`).
  - Fedeval’s pattern `initial_model=LitNet(checkpoint="...")` could remain supported for backward compatibility, but new code could use `model=LitNet(), initial_ckpt="pretrained_model.pt"` (or equivalent) where the recipe supports it.

### 5.3 Suggested semantics for `model`

- **PyTorch / TensorFlow:** `model` = in-memory model instance, or dict (e.g. state_dict or config), or `None`.
- **NumPy:** `model` = list or ndarray (required today); keep required unless we explicitly design “no initial model” flow.
- **RAW / LLM:** `model` = dict (e.g. `{"path": "...", "args": {...}}`) or `None` as today.

---

## 6. Recipe-by-Recipe Change Summary (if we adopt `model` + `initial_ckpt`)

| Recipe (file) | Current | Proposed |
|---------------|---------|----------|
| recipe/fedavg.py | `initial_model`, (model_persistor) | `model`, `model_persistor`, add `initial_ckpt` (optional) |
| recipe/cyclic.py | `initial_model` | `model`, add `initial_ckpt` (optional) |
| app_opt/pt/recipes/fedavg.py | `initial_model` | `model`, add `initial_ckpt` |
| app_opt/pt/recipes/fedavg_he.py | `initial_model` | `model`, add `initial_ckpt` |
| app_opt/pt/recipes/scaffold.py | `initial_model` | `model`, add `initial_ckpt` |
| app_opt/pt/recipes/fedopt.py | `initial_model` | `model`, add `initial_ckpt` |
| app_opt/pt/recipes/cyclic.py | `initial_model` | `model`, add `initial_ckpt` |
| app_opt/pt/recipes/fedeval.py | `initial_model` (with .checkpoint) | `model` + `initial_ckpt` (deprecate .checkpoint pattern over time) |
| app_opt/tf/recipes/* (fedavg, scaffold, fedopt, cyclic) | `initial_model` | `model`, add `initial_ckpt` where TF persistor supports it |
| app_common/np/recipes/fedavg.py | `initial_model` (required) | `model` (required), same types |
| edge/tools/edge_fed_buff_recipe.py | `model` | No change (already `model`) |

---

## 7. References in Repo

- **Parameter consolidation (Dec 2025):** `cursor_outputs/refactoring/fedavg_streamlining/2025-12-08-12-parameter-consolidation.md` — consolidated to `initial_model` + `model_persistor`; no rename to `model` there.
- **PT persistor checkpoint:** `nvflare/app_opt/pt/file_model_persistor.py` — `source_ckpt_file_full_name`; used by Fedeval via `initial_model.checkpoint`.
- **Job config (PT):** `nvflare/app_opt/pt/job_config/base_fed_job.py` — uses `initial_model` in constructor.

---

## 8. Next Steps (optional)

1. **Confirm** whether to standardize on `model` (and optionally keep `initial_model` as alias) and add `initial_ckpt` across PT/TF recipes.
2. **Implement** `initial_ckpt` in unified/PT/TF recipes and wire to existing persistors.
3. **Rename** `initial_model` → `model` in all recipes in the table above (with deprecation or one-time breaking change).
4. **Update** examples, docs, and tests that pass `initial_model=` to use `model=` (and `initial_ckpt` where relevant).
5. **Leave** EdgeFedBuffRecipe as-is (already `model`).

If you locate Holger's PR or the original discussion, add the link here for traceability.

---

## 9. Review of commit 9fd5ed6868d8676a393f86290dbf9efcb324dce0

**Author:** chesterxgchen (Co-authored-by: Cursor)  
**Message:** Rename recipe argument 'initial_model' to 'model' across codebase  
**Scope:** 166 files — recipes, workflows, job configs, examples, tutorials, docs, tests.

### 9.1 What the commit does (and how it aligns with the analysis)

- **Renames** `initial_model` → `model` in all recipe APIs (unified FedAvg, Cyclic, PT/TF/NumPy recipes, Fedeval, Scaffold, FedOpt, FedAvg-HE), in `FedAvg` / `PTFedAvg` workflows, and in PT/TF `BaseFedJob` and `NPModelPersistor`.
- **Adds** `initial_ckpt: Optional[str] = None` (or required for Fedeval) and wires it through:
  - Unified `FedAvgRecipe` and `CyclicRecipe` (validator + validation “model or initial_ckpt or model_persistor”).
  - PT recipes (FedAvg, FedAvg-HE, Scaffold, Fedeval) pass `initial_ckpt` into `PTModel` / `PTFileModelPersistor`.
  - NumPy recipe and `NPModelPersistor(model=..., source_ckpt_file_full_name=...)`.
  - TF `BaseFedJob` and TF model setup.
- **Keeps** internal names as stated: e.g. `initial_model_params` in `PTFedAvg`, `INITIAL_MODEL_LOADED` event, `_get_initial_model_as_numpy()` in persistors.
- **Leaves** `EdgeFedBuffRecipe` unchanged (it already used `model`); the rest of the codebase now matches that naming.

This matches the direction in sections 5–6: standardize on `model`, add `initial_ckpt`, and keep EdgeFedBuffRecipe as-is.

### 9.2 Issues that should be fixed

#### 1. Grammar typo in error message (must fix)

**File:** `nvflare/recipe/utils.py`  
**Change in commit:**  
`"Ensure your recipe includes an initial_model to create a persistor."`  
→ `"Ensure your recipe includes an model to create a persistor."`

**Problem:** “an model” is ungrammatical.  
**Fix:** Use **“a model”**:  
`"Ensure your recipe includes a model to create a persistor."`

#### 2. Integration tests: NumpyFedAvgRecipe without model — *not* a PR regression

**File:** `tests/integration_test/recipe_system_test.py`  
**Tests:** `test_end_to_end_simulation_workflow` and `test_end_to_end_poc_workflow`

**Clarification:** The PR only renames `initial_model` → `model`; it does **not** change the validation logic. In the **parent** of this commit, the unified recipe already had:

```text
if self.initial_model is None and self.model_persistor is None and self.initial_ckpt is None:
    raise ValueError("Must provide either initial_model, initial_ckpt, or model_persistor. ...")
```

So the same “at least one of model / initial_ckpt / model_persistor” rule applied **before** the rename. After the rename, the condition is the same except it uses `self.model` and the message says “model” instead of “initial_model”. The two integration tests that call `NumpyFedAvgRecipe(name="test_integration", min_clients=2, train_script=...)` with no model and no initial_ckpt would **already have raised** the same ValueError before the PR (with “initial_model” in the message). So this is **not** a new failure introduced by the rename. No change needed in the review for these tests; only the utils typo (below) is a real fix for this PR.

### 9.3 What was done well

- **Consistency:** All recipe and job-config call sites updated to `model`; `EdgeFedBuffRecipe` already matched.
- **initial_ckpt:** Correctly added and wired in unified recipes, PT/TF/NumPy, Fedeval, and persistors (`NPModelPersistor`, `PTModel`, `PTFileModelPersistor`, TF setup).
- **Validation:** Unified “model or initial_ckpt or model_persistor” and NumPy “model or initial_ckpt” are consistent.
- **Tests:** Unit tests (fedavg_recipe_test, fedavg_test, cyclic_recipe_test, scaffold_recipe_test, fedopt_recipe_test, eval_recipe_test, etc.) updated to `model` and to new error messages; `_np_initial_model` → `_np_model` assertion updated; Fedeval and initial_ckpt tests adjusted.
- **Docs/examples:** 166 files touched; examples, READMEs, and docs updated to use `model=` and `initial_ckpt` where relevant.
- **Internal naming:** Commit message’s intent to keep names like `initial_model_params` and `INITIAL_MODEL_LOADED` is respected in the diff.

### 9.4 Optional / follow-up

- **Fedeval:** The commit makes `initial_ckpt` a required argument for `FedEvalRecipe`. If the goal is to support “eval from checkpoint only,” this is consistent; if backward compatibility with “model with .checkpoint attribute” is desired, consider documenting or supporting both patterns.
- **Deprecation:** The commit is a clean rename with no `initial_model` alias. If you need a transition period, a follow-up could add a deprecated `initial_model` keyword that forwards to `model` and logs a warning.

### 9.5 Summary

| Category              | Verdict |
|-----------------------|--------|
| Alignment with analysis | Yes: `model` + `initial_ckpt` implemented as proposed. |
| Bugs / must-fix       | utils.py only: “an model” → “a model” (grammar). |
| Critical misses       | None. (Integration tests that omit model/initial_ckpt were already failing before the rename; logic is unchanged.) |
| Backward compatibility | Breaking rename (no alias); acceptable if release notes and migration guide are updated. |
