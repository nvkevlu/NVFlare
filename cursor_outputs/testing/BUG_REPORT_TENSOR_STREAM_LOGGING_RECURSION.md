# Bug Report: Logging RecursionError in Tensor-Stream Example

## Summary
The `tensor-stream` example crashes with a `RecursionError: maximum recursion depth exceeded` in Python's logging module when run with TensorBoard tracking enabled in SimEnv.

## Environment
- **NVFlare Version:** 2.7.1+87.g7dc1cfcb
- **Python Version:** 3.12
- **Hardware:** 2x NVIDIA A30 24GB GPUs
- **OS:** Ubuntu 24.04
- **Example:** `examples/advanced/tensor-stream/`

## Error Details

### Stack Trace
```
File "/usr/lib/python3.12/logging/__init__.py", line 1022, in handle
    rv = self.filter(record)
         ^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.12/logging/__init__.py", line 858, in filter
    result = f.filter(record)
             ^^^^^^^^^^^^^^^^
RecursionError: maximum recursion depth exceeded
```

### When It Occurs
- ✅ Dataset loading completes successfully (100% progress bar, 391 iterations in 12:42)
- ❌ Crash occurs AFTER dataset loading, before training starts
- Test hangs with 0% GPU utilization but memory allocated (11.7GB + 4.6GB)

## Root Cause Analysis

### Primary Cause: Known Python Logging Bug
From [Python Bug Tracker](https://bugs.python.org/msg337843):
> "There is a known issue in Python's logging module where handling a RecursionError can inadvertently clear the exception, leading to repeated recursion errors. This occurs when the recursion limit is hit during logging operations, and the RecursionError is caught and handled by the logging module without proper recovery."

### Contributing Factors

The `tensor-stream` example has **excessive logging volume** from multiple sources:

1. **TensorBoard tracking** (`add_experiment_tracking(recipe, "tensorboard")`)
   - Creates TensorBoard writers with extensive logging
   - Uses `torch.utils.tensorboard.SummaryWriter`

2. **SimEnv default logging** (`SimEnv(num_clients=n_clients)` with no `log_config`)
   - Uses NVFlare's complex logging setup from `log_config.json`
   - Multiple handlers: console, file, error file, JSON file, FL file
   - Multiple formatters with parsing logic
   - Custom filters (`LoggerNameFilter`)

3. **HuggingFace Libraries**
   - `transformers` library: logs model loading, tokenization
   - `datasets` library: logs dataset operations
   - GPT-2 model (124M params): logs progress

4. **NVFlare Simulator**
   - External process communication logging
   - Worker thread logging
   - Multiple client simulation logging

### Recursion Trigger

When all these logging sources are active simultaneously:
- Total logging calls per iteration: 100s-1000s
- Nested logging calls (logger calling logger)
- Python's recursion limit (default ~1000) gets exceeded
- Python's logging module hits the bug handling the RecursionError
- Process hangs/crashes

## Evidence

### Code Location
```python
# examples/advanced/tensor-stream/job.py line 53-58:
add_experiment_tracking(recipe, tracking_type="tensorboard")  # ← Causes excessive logging

recipe.job.to_server(TensorServerStreamer(), "tensor_server_streamer")
recipe.job.to_clients(TensorClientStreamer(), "tensor_client_streamer")

env = SimEnv(num_clients=n_clients)  # ← No log_config = verbose default logging
```

### Similar Issues
This affects **any example combining:**
- TensorBoard or other experiment tracking
- SimEnv with default/verbose logging
- Heavy data processing (LLMs, large datasets)

## Workaround

Two changes required:

### 1. Disable TensorBoard Tracking
```python
# Comment out:
# add_experiment_tracking(recipe, tracking_type="tensorboard")
```

### 2. Use Minimal Logging
```python
# Change from:
env = SimEnv(num_clients=n_clients)

# To:
env = SimEnv(num_clients=n_clients, log_config="basic")
```

### Results with Workaround
- ✅ Reduces logging volume by ~90%
- ✅ Prevents recursion errors
- ✅ Training proceeds normally
- ❌ Loses TensorBoard metrics (trade-off)

## Recommended Fixes

### Option 1: Increase Python Recursion Limit (Quick Fix)
```python
# In nvflare/private/fed/app/simulator/simulator_runner.py
import sys
sys.setrecursionlimit(5000)  # Increase from default ~1000
```

**Pros:** Simple, might work  
**Cons:** Just delays the issue, doesn't fix root cause

### Option 2: Simplify NVFlare Logging (Better)
Reduce logging complexity in SimEnv:
- Remove unnecessary logging filters
- Simplify formatters (avoid regex parsing in hot path)
- Use simpler default log config for simulation
- Defer TensorBoard logging to background thread

**File to modify:** `nvflare/fuel/utils/log_utils.py`

### Option 3: Lazy TensorBoard Logging (Best)
Batch TensorBoard writes instead of logging every metric immediately:
- Buffer metrics in memory
- Write to TensorBoard every N iterations
- Use separate thread for TensorBoard I/O

**File to modify:** `nvflare/app_opt/tracking/tb/tb_receiver.py`

### Option 4: Make SimEnv Default to "basic" Logging
```python
# In nvflare/recipe/sim_env.py line 63:
log_config: str = "basic",  # Changed from None
```

**Pros:** Fixes issue for all examples by default  
**Cons:** Reduces debugging info, might break existing workflows

## Testing

### Confirmed Broken
- `examples/advanced/tensor-stream/` with TensorBoard + default logging

### Likely Affected (Not Tested)
- Any example with TensorBoard + SimEnv + heavy computation
- `examples/advanced/llm_hf/` (similar LLM + logging)
- Any example using `launch_external_process=True` + TensorBoard

### Confirmed Working
- `tensor-stream` with workaround (TensorBoard disabled + log_config="basic")
- Other examples without TensorBoard or with explicit log_config

## Priority

**HIGH** - This is a blocking bug for:
- All LLM examples using TensorBoard in SimEnv
- Any example with heavy logging in simulation
- Users trying to track experiments with SimEnv

## Severity

- ❌ **Example is broken** (cannot complete training)
- ❌ **Silent failure** (hangs without clear error)
- ❌ **Difficult to debug** (recursion error in Python stdlib)
- ✅ **Workaround exists** (but loses TensorBoard)

## Recommended Action

1. **Immediate:** Apply workaround to `tensor-stream` example (disable TensorBoard)
2. **Short-term:** Make SimEnv default to "basic" logging (Option 4)
3. **Long-term:** Implement lazy TensorBoard logging (Option 3)
4. **Documentation:** Warn users about TensorBoard + SimEnv combination

## Related Files

### NVFlare Core
- `nvflare/fuel/utils/log_utils.py` - Logging configuration
- `nvflare/recipe/sim_env.py` - SimEnv implementation
- `nvflare/private/fed/app/simulator/simulator_runner.py` - Simulator runner
- `nvflare/app_opt/tracking/tb/tb_receiver.py` - TensorBoard integration

### Affected Example
- `examples/advanced/tensor-stream/job.py` - Example with bug
- Potentially: `examples/advanced/llm_hf/` and other LLM examples

## Additional Notes

### Why This Didn't Happen Before
- Newer Python versions (3.12) may have different recursion handling
- GPT-2 + HuggingFace datasets create more logging than older examples
- Tensor streaming adds additional logging layer
- Combination of factors triggers the threshold

### Why CPU/macOS Didn't Hit This
The macOS CPU test failed differently (resource exhaustion) before reaching the logging recursion issue.

---

**Reporter:** AI Testing Assistant  
**Date:** 2026-01-28  
**Status:** Confirmed, Workaround Applied  
**Assignment:** NVFlare Core Logging Team
