# hello-numpy-cross-val KeyError: 'numpy_key' – 2.7 Reopened Ticket Analysis

**Date:** January 21, 2026  
**Context:** QA reopened ticket: "Run hello-numpy-cross-val example failed for KeyError: 'numpy_key'" on **2.7** branch.

---

## What actually happened: #4144 and #4153 (verified from commits)

### Commit 9f84b4be — [2.7] Rename recipe argument 'initial_model' to 'model' (#4144)

- **Intent:** Naming-only change: rename recipe parameter `initial_model` → `model` for consistency (no functional change).
- **Scope:** 166 files — recipe core (`recipe/fedavg.py`, `recipe/cyclic.py`, `recipe/utils.py`), all recipe implementations (PT, TF, NumPy), workflows, persistors, **Job Config (legacy FedJob API)**, examples (including `hello-numpy-cross-val/job.py`), docs, tutorials, tests.
- **Result:** Everywhere that passed or accepted `initial_model=` was updated to `model=`.

### Commit 0ffda4a8 — [2.7] Revert model back to initial model for Job API (#4153)

- **Intent:** Backward compatibility with **2.7.1** for the **Job API** (legacy FedJob / programmatic job config).
- **Scope:** **19 files only.** Reverted to `initial_model=` only in:
  - **Legacy Job Config:** `nvflare/app_opt/pt/job_config/base_fed_job.py`, `fed_avg.py`, `fed_sag_mlflow.py`; `nvflare/app_opt/tf/job_config/base_fed_job.py`, `fed_avg.py`
  - **A few PT/TF recipes:** `fedopt.py`, `scaffold.py` (PT and TF)
  - **Tutorial/advanced examples:** several `fl_job.py` and `fedavg_script_runner_pt.py` under examples/advanced (tensorboard, monitoring, job_api, self-paced-training, etc.)
- **What was NOT reverted:** `nvflare/recipe/fedavg.py`, `nvflare/app_common/np/recipes/fedavg.py`, and **`examples/hello-world/hello-numpy-cross-val/job.py`** were **not** in the revert. They still use `model=` after both commits.

### Net state after both commits

- **Recipe API (unified + NumpyFedAvgRecipe):** parameter is **`model`**.
- **hello-numpy-cross-val/job.py:** passes **`model=np.array([0.0] * 10)`** — aligned with recipe.
- **Legacy Job API (PT/TF BaseFedJob, etc.):** back to **`initial_model`** for 2.7.1 compatibility.

So for the **exact** hello-numpy-cross-val example, there is **no** parameter mismatch: job and recipe both use `model=`. The KeyError QA saw is therefore **not** explained by the rename/revert pair alone for this file (could be another cause: e.g. build without one of the commits, or a different code path).

---

## Summary (updated)

- **#4144 / #4153:** Rename was global; revert was **Job API only**. Recipe core and hello-numpy-cross-val were **not** reverted, so they remain on `model=`.
- **Possible causes for QA KeyError:** (1) Build/revision where job or recipe differ from the above; (2) users or internal code calling `NumpyFedAvgRecipe(initial_model=...)` (2.7.1 or Job API style) — recipe would not accept `initial_model` and would get no model → KeyError; (3) another bug (e.g. missing persistor/comp_ids).
- **Fixes applied in this repo:** Accept **both** `model` and `initial_model` in `NumpyFedAvgRecipe` (backward compat for 2.7.1 / Job API callers), and set `job.comp_ids["persistor_id"]` for CSE.

---

## Root Cause (Why KeyError Happens)

1. Client does `input_model.params[NPConstants.NUMPY_KEY]` in `client.py`. If `params` is `{}`, this raises **KeyError: 'numpy_key'**.
2. Empty `params` are sent when the **server has no persistor** (or persistor not used) and creates `FLModel(params_type=ParamsType.FULL, params={})` in `base_model_controller.load_model()`.
3. No persistor is set when `_setup_model_and_persistor` returns `""`, which happens when `self._np_model is None` and `self._np_initial_ckpt is None`.
4. So `self._np_model` is only set when the recipe receives an initial model. If the recipe expects `model=` but the job passes `initial_model=` (old 2.7 / doc style), the recipe ignores it and `_np_model` stays `None` → no persistor → empty params → KeyError.

So the bug is either:

- **Regression (2.7):** Recipe was updated to use `model=` but 2.7 job (or docs) still use `initial_model=`, so the initial model is never passed through.
- **Real bug (any branch):** Recipe never accepted `initial_model=`, so any job using `initial_model=` would fail the same way.

---

## Fixes Applied in This Repo

### 1. Backward compatibility: accept both `model` and `initial_model`

**File:** `nvflare/app_common/np/recipes/fedavg.py`

- Added `initial_model` as an optional parameter (for 2.7 / old job.py).
- Effective initial model: `model if model is not None else initial_model`.
- Stored in `self._np_model` and passed to parent as `model=self._np_model`.

So both of these work:

- `NumpyFedAvgRecipe(..., model=np.array([0.0] * 10), ...)`  (unified API)
- `NumpyFedAvgRecipe(..., initial_model=np.array([0.0] * 10), ...)`  (2.7 / old style)

### 2. Set `job.comp_ids["persistor_id"]` when adding the persistor

- After `persistor_id = job.to_server(persistor, id="persistor")`, we now set `job.comp_ids["persistor_id"] = persistor_id` when `job` has `comp_ids`.
- Aligns with PT/TF recipes and ensures CSE (e.g. `add_cross_site_evaluation`) can resolve the persistor when needed.

### 3. Docstring clarification

- Docstring updated to state that the initial model is required for cross-site eval and that omitting it can lead to `KeyError: 'numpy_key'` on the client.

---

## Justification for adding `initial_model` in the recipe

After #4153, the **public surface** is split: Recipe API uses `model=`, Job API uses `initial_model=`. Anyone following 2.7.1 docs or legacy Job API examples might call **recipes** with `initial_model=` (e.g. `NumpyFedAvgRecipe(..., initial_model=np.array(...), ...)`). The recipe did not accept that keyword → argument ignored → `_np_model` stays `None` → no persistor → empty params → KeyError. Adding **`initial_model` as an optional alias** in `NumpyFedAvgRecipe` (effective model = `model if model is not None else initial_model`) makes both call styles valid. It does not change behavior when `model=` is passed (as in current hello-numpy-cross-val/job.py).

---

## What to Verify on 2.7

1. **Recipe:** Does 2.7 `NumpyFedAvgRecipe` accept `initial_model`? If not, cherry-pick or backport the above changes (accept `initial_model`, set `comp_ids["persistor_id"]`).
2. **Example job:** Does `examples/hello-world/hello-numpy-cross-val/job.py` pass an initial model under the name 2.7 expects?
   - If 2.7 recipe only had `initial_model`, ensure job uses `initial_model=np.array([0.0] * 10)` (or equivalent).
   - With the backward-compat fix, either `model=` or `initial_model=` is fine.
3. **CSE:** Confirm `self.framework = FrameworkType.RAW` is still set after `super().__init__()` in the 2.7 recipe (see `cursor_outputs/20260122_fedavg_merge_regression_analysis.md` for the CSE framework regression).

---

## Two different client errors (don’t conflate)

| Error | When | Fix |
|-------|------|-----|
| **KeyError: 'numpy_key'** | **Train** task: server sends empty `params` because no persistor (no initial model in recipe). | Recipe/job: ensure `model=` or `initial_model=` so persistor is created (this doc). |
| **TypeError: 'NoneType' object is not subscriptable** | **submit_model** (or some validate) tasks: server sends `params=None`. Client does `params[NUMPY_KEY]`. | Client: guard before using params; if None or no numpy_key, send `FLModel(metrics={})` and continue. See `cursor_outputs/20260121_hello_numpy_cross_val_client_fix.md`. |

The original client was a training-only loop (like hello-numpy); it was not “horribly wrong.” Adding CSE meant the same script receives non-train tasks with no params; the minimal client fix is a small guard, not a full rewrite.

---

## References

- `cursor_outputs/20260121_hello_numpy_cross_val_client_fix.md` – client fix (TypeError / params None); minimal vs full task branching.
- `cursor_outputs/20260114/08_numpy_example_crashes_keyerror_numpy_key_missing_when_no_initial_model.md` – original KeyError analysis.
- `cursor_outputs/20260114/09_numpy_keyerror_fixed_by_adding_initial_model_to_job_not_defensive_client_code.md` – fix via job config.
- `cursor_outputs/20260114/13_numpy_initial_model_made_mandatory_breaks_optional_use_fixes_dimensionality.md` – mandatory initial model decision.
- `cursor_outputs/20260122_fedavg_merge_regression_analysis.md` – CSE framework (RAW vs NUMPY) regression and fix.
