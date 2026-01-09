# Added Model Type Validation

## Issue Identified

User noticed that `initial_model` has type hints (`nn.Module` for PT, `tf.keras.Model` for TF) but no runtime validation to ensure the correct type is actually provided.

## Precedent Found

The old `FedAvg` classes already do this validation:

### PyTorch (fed_avg.py):
```python
if not isinstance(initial_model, nn.Module):
    raise ValueError(f"Expected initial model to be nn.Module, but got type {type(initial_model)}.")
```

### TensorFlow (fed_avg.py):
```python
if not isinstance(initial_model, tf.keras.Model):
    raise ValueError(f"Expected initial model to be tf.keras.Model, but got type {type(initial_model)}.")
```

## Solution

Added the same validation to the new `BaseFedJob` wrappers:

### PyTorch BaseFedJob
```python
# PyTorch-specific model setup
if initial_model is not None:
    if not isinstance(initial_model, nn.Module):
        raise TypeError(
            f"initial_model must be an instance of nn.Module, but got {type(initial_model).__name__}"
        )
    self._setup_pytorch_model(initial_model, model_persistor, model_locator)
```

### TensorFlow BaseFedJob
```python
# TensorFlow-specific model setup
if initial_model is not None:
    if not isinstance(initial_model, tf.keras.Model):
        raise TypeError(
            f"initial_model must be an instance of tf.keras.Model, but got {type(initial_model).__name__}"
        )
    self._setup_tensorflow_model(initial_model, model_persistor)
```

## Benefits

✅ **Early error detection** - Fail fast with clear error message
✅ **Better user experience** - Users get helpful error instead of cryptic failure later
✅ **Consistency** - Matches behavior of old FedAvg classes
✅ **Type safety** - Runtime validation matches type hints

## Error Messages

Users now get clear errors if they pass wrong types:

```python
# Wrong type provided
job = PTBaseFedJob(initial_model="not a model")

# Error:
# TypeError: initial_model must be an instance of nn.Module, but got str
```

```python
# Wrong type provided
job = TFBaseFedJob(initial_model=[1, 2, 3])

# Error:
# TypeError: initial_model must be an instance of tf.keras.Model, but got list
```

## Verification

✅ All linting passes (only expected torch/tensorflow warnings)
✅ Validation happens before model setup
✅ Clear, actionable error messages

---

**Great catch!** This defensive programming prevents confusing errors later in the workflow.
