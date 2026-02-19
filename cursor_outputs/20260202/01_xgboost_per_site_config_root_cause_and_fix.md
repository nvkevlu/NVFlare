# XGBoost per_site_config Root Cause Analysis and Fix

**Date:** February 2, 2026  
**Issue:** Data loaders configured via per_site_config are not being loaded at runtime  
**Error:** `data_loader should be type XGBDataLoader but got <class 'NoneType'>`  
**Status:** ROOT CAUSE IDENTIFIED + FIX PROPOSED  

---

## Investigation Timeline

### Initial Hypothesis (WRONG)
Initially thought `job.to()` wasn't working to add per-site components.

### Discovery 1: Components ARE Added to Memory
Debug output showed data loaders ARE added to app_config.components:
```python
[RECIPE DEBUG] site-1 app_config components: {'dataloader': <HIGGSDataLoader object>}
[RECIPE DEBUG] site-2 app_config components: {'dataloader': <HIGGSDataLoader object>}
```

### Discovery 2: But NOT in Exported Config
Checking exported JSON config files showed NO dataloader component:
```json
{
    "components": [
        {"id": "metrics_writer", ...},
        {"id": "event_to_fed", ...}
        // ← dataloader MISSING!
    ]
}
```

### Discovery 3: @ALL Overwrites Site-Specific Components
The recipe uses TWO patterns:
- `job.to_clients()` for metrics_writer, event_to_fed → adds to `@ALL` 
- `job.to(site_name)` for data_loader → adds to site-specific

Final component state:
```python
[@ALL] components: {'metrics_writer': ..., 'event_to_fed': ...}
[site-1] components: {'dataloader': ...}  # metrics_writer and event_to_fed MISSING
[site-2] components: {'dataloader': ...}  # metrics_writer and event_to_fed MISSING
```

**During job export, `@ALL` components overwrite site-specific components instead of merging!**

Result: Exported configs have @ALL components but NOT site-specific ones.

---

## Root Cause

**NVFlare Job API Bug:** When using BOTH `job.to_clients()` (@ALL) and `job.to(site_name)` (site-specific), the @ALL components overwrite site-specific components during job export instead of merging them.

**Code Location:** `nvflare/job_config/api.py` in `_set_all_apps()` and `_set_site_app()`

---

## Attempted Fix #1: Add All Components Per-Site

**Approach:** Instead of using `job.to_clients()` for common components, add them per-site along with data loaders.

**Code:**
```python
for site_name, site_config in self.per_site_config.items():
    # Add executor
    executor = FedXGBHistogramExecutor(...)
    job.to(executor, site_name, id="xgb_executor")
    
    # Add metrics writer
    metrics_writer = TBWriter(...)
    job.to(metrics_writer, site_name, id=self.metrics_writer_id)
    
    # Add event converter
    event_to_fed = ConvertToFedEvent(...)
    job.to(event_to_fed, site_name, id="event_to_fed")
    
    # Add data loader
    job.to(data_loader, site_name, id=self.data_loader_id)
```

**Result:** ❌ FAILED

**Error:**
```
ValueError: You already specified clients using `to()`. Don't use `n_clients` in simulator_run.
```

**Why It Failed:**
- `job.to('site-1')` adds 'site-1' to `job.clients` list
- `SimEnv(num_clients=2)` passes `n_clients=2` to `job.simulator_run()`  
- `job.simulator_run()` detects both `job.clients` (from `to()`) and `n_clients` parameter
- Raises error because you can't specify clients both ways

---

## Root Cause #2: SimEnv + Per-Site Components Incompatibility

**The Conflict:**
1. Using `job.to(site_name)` registers explicit client names in `job.clients`
2. `SimEnv(num_clients=N)` tries to pass `n_clients` parameter
3. These two approaches are mutually exclusive in NVFlare

**Code Flow:**
```python
# In recipe configure():
job.to(data_loader, 'site-1', id='dataloader')  # Adds 'site-1' to job.clients

# In SimEnv.deploy():
job.simulator_run(n_clients=self.num_clients)   # Passes n_clients

# In job.simulator_run() line 609-610:
elif self.clients and n_clients:
    raise ValueError("You already specified clients using `to()`. Don't use `n_clients`")
```

---

## The Working Tutorial Pattern

The fraud detection tutorial (`examples/tutorials/.../xgb_job.py`) uses per-site components successfully:

```python
for site_name in site_names:
    executor = FedXGBHistogramExecutor(data_loader_id="data_loader")
    job.to(executor, site_name)
    data_loader = CreditCardDataLoader(...)
    job.to(data_loader, site_name, id="data_loader")

# Uses job.simulator_run() directly WITHOUT SimEnv
job.simulator_run(work_dir)
```

**Key Difference:** Doesn't use `SimEnv` wrapper, calls `job.simulator_run()` directly without `n_clients`.

---

## Proposed Solutions

### Option 1: Fix SimEnv to Auto-Detect Explicit Clients (RECOMMENDED)

**Location:** `nvflare/recipe/sim_env.py` line 97-114

**Change:**
```python
def deploy(self, job: FedJob):
    # ... validation ...
    
    # Only pass n_clients if job doesn't have explicit clients
    if job.clients and '@ALL' not in job.clients:
        # Job has explicit clients from job.to(site_name)
        # Don't pass n_clients, let job use its own client list
        job.simulator_run(
            workspace=os.path.join(self.workspace_root, job.name),
            clients=None,  # Let job use job.clients
            threads=self.num_threads,
            gpu=self.gpu_config,
            log_config=self.log_config,
        )
    else:
        # Use n_clients from SimEnv
        job.simulator_run(
            workspace=os.path.join(self.workspace_root, job.name),
            n_clients=self.num_clients,
            clients=self.clients,
            threads=self.num_threads,
            gpu=self.gpu_config,
            log_config=self.log_config,
        )
    return job.name
```

**Impact:** LOW - Makes SimEnv smarter about when to use n_clients vs explicit clients

### Option 2: Fix Job API to Merge @ALL with Site-Specific (BETTER BUT HARDER)

**Location:** `nvflare/job_config/api.py` in `_set_all_apps()` and `_set_site_app()`

**Change:** Modify the job export logic to MERGE @ALL components with site-specific components instead of overwriting.

**Impact:** MEDIUM - Affects core job configuration logic, needs careful testing

### Option 3: Workaround in XGBoost Recipes (TEMPORARY)

**Don't use per-site `job.to()`** - Instead, use a different pattern:
- Use `job.to_clients()` for executor and metrics (goes to @ALL)
- Pass data loader path as a parameter to the executor
- Executor reads site-specific config at runtime

**Impact:** HIGH - Changes XGBoost recipe architecture significantly

---

## Recommendation

**Implement Option 1 (SimEnv fix) as immediate solution**
- Minimal change
- Fixes the per_site_config use case
- Backward compatible (doesn't break existing code)

**Then investigate Option 2 (Job API fix) for proper long-term solution**
- Fixes the root cause of @ALL overwriting site-specific
- Benefits all recipes, not just XGBoost
- Requires more testing

---

## Testing

After implementing Option 1, verify:
1. ✅ XGBoost recipes with per_site_config work in SimEnv
2. ✅ Existing examples using `job.to_clients()` still work  
3. ✅ Tutorial examples using direct `job.simulator_run()` still work

---

## Files to Modify

### Option 1 (Recommended):
- `nvflare/recipe/sim_env.py` - Update `deploy()` method

### Option 2 (Long-term):
- `nvflare/job_config/api.py` - Update `_set_all_apps()` and `_set_site_app()`
- May need changes to `nvflare/job_config/fed_job_config.py`

---

**Next Steps:**
1. Implement Option 1 fix in SimEnv
2. Test with XGBoost examples
3. Create test to prevent regression
4. Document the @ALL + site-specific merge behavior

