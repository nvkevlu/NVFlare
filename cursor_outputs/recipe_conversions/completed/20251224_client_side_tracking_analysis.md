# Client-Side Experiment Tracking Analysis

**Date**: December 24, 2025
**Status**: Analysis Complete - No Implementation Yet
**Context**: Experiment tracking examples cleanup and documentation

---

## Summary

Analyzed the feasibility and requirements for adding client-side experiment tracking support to the `add_experiment_tracking()` utility function. **Decision: Keep manual configuration for now** due to API complexity vs. limited use case.

---

## Background

### Current State: Server-Side Only

The `add_experiment_tracking()` function currently only supports **server-side tracking**:

```python
def add_experiment_tracking(recipe: Recipe, tracking_type: str, tracking_config: Optional[dict] = None):
    """Enable experiment tracking."""
    # ... validation ...
    receiver = receiver_class(**tracking_config)
    recipe.job.to_server(receiver, "receiver")  # ← Always to server
```

**Behavior:**
- Receiver lives on FL Server
- Listens for federated events (`fed.analytix_log_stats`)
- Clients send metrics → Server aggregates → One centralized tracking instance
- **Use case**: Centralized monitoring, aggregated metrics view

### Client-Side Tracking (Manual in Examples)

Examples like `hello-pt-mlflow-client` and `wandb` show manual client-side tracking:

```python
# Manual approach - requires explicit site names
for i in range(args.n_clients):
    site_name = f"site-{i + 1}"  # ❌ Hard-coded assumption!

    receiver = MLflowReceiver(
        tracking_uri=f"file://{workspace}/{site_name}/mlruns",
        events=[ANALYTIC_EVENT_TYPE],  # Local events, not federated
        kw_args={"experiment_name": f"{site_name}-experiment"}
    )
    recipe.job.to(receiver, site_name, id="mlflow_receiver")
```

**Behavior:**
- Receiver lives on each FL Client
- Listens for local events (`analytix_log_stats` - NOT `fed.`)
- Metrics stay on client, no transmission to server
- **Use case**: Privacy-preserving, site-specific analysis, compliance

---

## Problem: Hard-Coded Site Names

**Current examples assume:**
```python
site_name = f"site-{i + 1}"  # Assumes: site-1, site-2, site-3...
```

**Issues:**
1. ❌ Breaks with custom site names (`hospital-a`, `clinic-boston`)
2. ❌ Doesn't work with dynamic client joining
3. ❌ User must manually match their actual site names
4. ❌ Not suitable for production deployments

---

## Analysis: Adding Client-Side Support to `add_experiment_tracking()`

### Option 1: Add `tracking_side` Parameter

```python
def add_experiment_tracking(
    recipe: Recipe,
    tracking_type: str,
    tracking_config: Optional[dict] = None,
    tracking_side: str = "server"  # NEW: "server" or "client"
):
```

**Challenges:**

#### 1. Site Name Discovery
```python
# How does recipe know site names?

# Option A: Derive from recipe
recipe.min_clients  # Returns: 2
recipe.get_client_names()  # Would return: ["site-1", "site-2"]
# Problem: Still assumes naming convention!

# Option B: User provides
add_experiment_tracking(
    recipe, "mlflow",
    tracking_side="client",
    site_names=["hospital-a", "hospital-b", "clinic-c"]
)

# Option C: Template with placeholder
add_experiment_tracking(
    recipe, "mlflow",
    tracking_side="client",
    tracking_config={
        "tracking_uri": "file:///workspace/{{site_name}}/mlruns"
    }
)
```

#### 2. Per-Client Configuration

Each client needs different configuration:

```python
# Option A: Template string substitution
tracking_config={
    "tracking_uri": "file:///workspace/{{site_name}}/mlruns",
    "kw_args": {
        "experiment_name": "{{site_name}}-experiment"
    }
}

# Option B: Callback function
def get_client_config(site_name: str) -> dict:
    return {
        "tracking_uri": f"file:///workspace/{site_name}/mlruns",
        "kw_args": {"experiment_name": f"{site_name}-experiment"}
    }

add_experiment_tracking(
    recipe, "mlflow",
    tracking_side="client",
    config_fn=get_client_config
)
```

#### 3. Event Type Handling

```python
# Client-side must use local events
if tracking_side == "client":
    tracking_config.setdefault("events", [ANALYTIC_EVENT_TYPE])
else:
    # Server-side uses default federated events
    pass
```

---

### Option 2: Separate Function

```python
def add_client_experiment_tracking(
    recipe: Recipe,
    tracking_type: str,
    site_names: Optional[list[str]] = None,  # If None, derive from recipe
    tracking_config_template: Optional[dict] = None,
):
    """Add experiment tracking to each client.

    Args:
        recipe: The recipe to add tracking to
        tracking_type: "mlflow", "tensorboard", or "wandb"
        site_names: List of client site names. If None, uses ["site-1", "site-2", ...]
        tracking_config_template: Template with {{site_name}} placeholders
    """
```

**Advantages:**
- ✅ Clear separation of concerns
- ✅ Explicit about client-side tracking
- ✅ Different signature optimized for client-side use case
- ✅ Doesn't complicate existing `add_experiment_tracking()` API

---

## Implementation Complexity

### Current (Server-side only): ⭐
- Just add one receiver to server
- ~15 lines of code
- Simple, clear API

### With Client-side Support: ⭐⭐⭐
- Need site name discovery/specification
- Template/callback for per-client config
- Auto-set event type to local
- Handle edge cases (no clients, dynamic joining)
- ~50-100 lines of code
- API design decisions needed
- More documentation required

### Full Support (Both + Dynamic): ⭐⭐⭐⭐⭐
- Support both server and client simultaneously
- Handle dynamic client joining
- Deal with unknown site names at job creation time
- Production-ready site name handling
- ~150+ lines, significant API complexity

---

## Decision: Keep Manual Configuration

**Recommendation: Do NOT add client-side support to `add_experiment_tracking()` yet**

### Rationale:

1. **Limited Use Case (20%)**
   - Server-side tracking covers 80% of use cases
   - Client-side is niche (privacy/compliance scenarios)
   - Power users can handle manual configuration

2. **API Complexity**
   - Site name handling is non-trivial
   - Multiple design decisions with no clear "best" approach
   - Would complicate API for majority of users

3. **Examples Exist**
   - `hello-pt-mlflow-client` shows manual approach
   - `wandb` example shows both server and client
   - Documentation can guide users

4. **Flexibility**
   - Manual configuration gives full control
   - Users can customize per their exact needs
   - No framework limitations

### What We Did Instead:

1. ✅ **Cleaned up examples** - Removed unnecessary `analytics_receiver=False`
2. ✅ **Fixed documentation** - Corrected broken links, clarified behavior
3. ✅ **Added test documentation** - Explained orphaned integration tests
4. ✅ **Documented limitation** - Site name assumptions in client-side examples

---

## Future Considerations

If there's user demand, consider:

1. **Add `add_client_experiment_tracking()` helper**
   - Separate function for client-side
   - Template-based configuration
   - Clear documentation about site name requirements

2. **Recipe enhancement**
   - Add `recipe.get_client_names()` method
   - Support for custom site name specification
   - Better integration with POC vs Production modes

3. **Documentation improvements**
   - When to use server vs client tracking
   - How to handle custom site names
   - Production deployment considerations

---

## Related Files

**Modified:**
- `examples/advanced/experiment-tracking/wandb/job.py` - Fixed `recipe.run()` signature
- `examples/advanced/experiment-tracking/wandb/README.md` - Fixed doc links
- `examples/advanced/experiment-tracking/mlflow/hello-pt-mlflow-client/README.md` - Fixed doc links
- `examples/advanced/experiment-tracking/tensorboard/README.md` - Fixed doc links
- `examples/advanced/experiment-tracking/mlflow/hello-lightning-mlflow/README.md` - Fixed doc links
- `examples/advanced/experiment-tracking/README.md` - Fixed doc links
- `tests/integration_test/test_experiment_tracking_recipes.py` - Added documentation
- `tests/integration_test/recipe_system_test.py` - Added documentation

**Key Function:**
- `nvflare/recipe/utils.py::add_experiment_tracking()` - Analyzed but not modified

---

## Conclusion

Client-side experiment tracking remains a **manual configuration** task. This is appropriate given:
- Limited use case (privacy/compliance scenarios)
- API complexity vs benefit tradeoff
- Existing examples demonstrate the approach
- Power users can customize to their exact needs

The `add_experiment_tracking()` utility continues to focus on the 80% use case: simple, centralized server-side tracking.
