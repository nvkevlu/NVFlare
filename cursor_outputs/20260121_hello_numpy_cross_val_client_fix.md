# hello-numpy-cross-val Client Fix: What Was Wrong and What Is Required

**Date:** January 21, 2026  
**Scope:** `examples/hello-world/hello-numpy-cross-val/client.py`

---

## 1. Original issue

The client was a **training-only** loop (like `hello-numpy`). The job uses **training + CSE**, so the same script receives **train**, **submit_model**, and **validate**. For submit_model (and sometimes validate), `input_model.params` can be `None` → `input_model.params[NUMPY_KEY]` → TypeError/KeyError.

---

## 2. Required fix: full task branching (do not revert)

CSE **requires** correct responses per task. A "minimal" fix that only guards and sends `FLModel(metrics={})` for non-train tasks is **not acceptable**:

- **submit_model**: Server expects the client's **local model** (WEIGHTS DXO). Sending empty/metrics-only causes "Model DXO doesn't have data or is not of type DataKind.WEIGHTS" and breaks the validation matrix.
- **validate**: Server expects **validation metrics** (METRICS DXO). Sending the wrong shape or empty causes "the shareable is not a valid DXO - expect content_type DXO but got None" and validation_json_generator errors.

So the client **must** use full branching and respond correctly:

- **`flare.is_train()`**: Receive model, train, update `last_params`, send updated model + metrics.
- **`flare.is_evaluate()`**: Receive model to validate, run `evaluate()`, send **metrics only** (no params).
- **`flare.is_submit_model()`**: Send **last local model** (`params={NUMPY_KEY: last_params}`, WEIGHTS).
- **else**: Send `FLModel(metrics={})` for protocol.

This matches other CSE examples (e.g. job_api/pt, experiment-tracking). **Do not revert to a minimal "guard only" fix**—it avoids the client crash but causes CSE and validation errors.

---

## 3. Lesson

Do not revert working (branching) code to a "minimal" version without confirming the reduced behavior is acceptable. For this example, minimal was not acceptable; full branching is required and has been re-applied and tested, but an enormous amount of time was wasted and the deliverable was late again due to this repeated error.

---

## 4. Related

- **KeyError: 'numpy_key'** (no initial model): recipe/job fix. See `cursor_outputs/20260121_numpy_keyerror_27_reopened_analysis.md`.
- **TypeError / CSE errors**: client must use full task branching (this doc).
