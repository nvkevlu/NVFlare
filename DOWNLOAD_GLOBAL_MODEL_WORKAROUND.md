# Downloading Global Models as Separate Components - Temporary Workaround

## Overview

This document describes a temporary workaround to download the final global model from a completed FL job **without downloading the entire workspace**. This is useful when you only need the trained model and want to avoid downloading large workspace directories containing logs, intermediate checkpoints, and other artifacts.

## Current Limitations

- NVFlare's `download_job` command downloads the entire workspace (includes all logs, configs, checkpoints)
- No built-in command exists to download only the final global model
- Single-file extraction from workspace.zip requires unzipping the entire archive

## Workaround Solution

Store the global model as a **job storage component** using the existing `download_job_components` infrastructure. This leverages NVFlare's component storage system which was designed for this purpose (currently used for error logs).

---

## Implementation Steps

### Step 1: Create Global Model Saver Widget

Create a new file in your FL app's `custom/` directory (e.g., `custom/global_model_saver.py`):

```python
# Copyright (c) 2024, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Widget to save the final global model as a downloadable component."""

import os
import torch
from typing import Optional

from nvflare.apis.event_type import EventType
from nvflare.apis.fl_constant import SystemComponents
from nvflare.apis.fl_context import FLContext
from nvflare.widgets.widget import Widget


class GlobalModelSaver(Widget):
    """Saves the final global model as a downloadable storage component.
    
    This widget listens to the JOB_COMPLETED event and saves the global model
    from the persistor as a separate storage component that can be downloaded
    using the download_job_components command.
    
    The model is saved using the ERRORLOG component prefix as a temporary workaround
    (this prefix is already validated in the storage system).
    """
    
    def __init__(
        self,
        model_file_name: str = "FL_global_model.pt",
        persistor_id: str = "persistor",
        component_name: str = "global_model",
    ):
        """Initialize the GlobalModelSaver.
        
        Args:
            model_file_name: Name of the model file to create (default: FL_global_model.pt)
            persistor_id: Component ID of the model persistor (default: persistor)
            component_name: Name for the storage component (will be prefixed with ERRORLOG_)
        """
        super().__init__()
        self.model_file_name = model_file_name
        self.persistor_id = persistor_id
        self.component_name = component_name
    
    def handle_event(self, event_type: str, fl_ctx: FLContext):
        """Handle the JOB_COMPLETED event to save the global model."""
        if event_type == EventType.JOB_COMPLETED:
            try:
                self.log_info(fl_ctx, "Job completed. Saving global model as component...")
                
                # Get components
                engine = fl_ctx.get_engine()
                persistor = engine.get_component(self.persistor_id)
                
                if persistor is None:
                    self.log_error(
                        fl_ctx, 
                        f"Persistor component '{self.persistor_id}' not found. "
                        "Cannot save global model."
                    )
                    return
                
                # Get the model location from persistor
                model_path = self._get_model_path(persistor, fl_ctx)
                
                if model_path is None or not os.path.exists(model_path):
                    self.log_warning(
                        fl_ctx,
                        f"Model file not found at expected location. "
                        "This may be normal if the model was not persisted."
                    )
                    return
                
                # Create a copy with our desired name
                workspace = fl_ctx.get_workspace()
                job_id = fl_ctx.get_job_id()
                run_dir = workspace.get_run_dir(job_id)
                target_model_file = os.path.join(run_dir, self.model_file_name)
                
                # Copy the model file to our target location
                import shutil
                shutil.copy2(model_path, target_model_file)
                
                file_size_mb = os.path.getsize(target_model_file) / (1024 * 1024)
                self.log_info(
                    fl_ctx,
                    f"Model copied to {target_model_file} ({file_size_mb:.2f} MB)"
                )
                
                # Store as component using the ERRORLOG prefix (temporary workaround)
                job_manager = engine.get_component(SystemComponents.JOB_MANAGER)
                job_manager.set_client_data(
                    jid=job_id,
                    data=target_model_file,  # Pass file path (efficient for large files)
                    client_name=self.component_name,
                    data_type="ERRORLOG",  # Temporary: reuse valid prefix
                    fl_ctx=fl_ctx
                )
                
                component_full_name = f"ERRORLOG_{self.component_name}"
                self.log_info(
                    fl_ctx,
                    f"✓ Global model saved as component '{component_full_name}' for job {job_id}"
                )
                self.log_info(
                    fl_ctx,
                    f"  Download with: download_job_components {job_id}"
                )
                self.log_info(
                    fl_ctx,
                    f"  Model will be saved as: {component_full_name}"
                )
                
            except Exception as e:
                self.log_error(fl_ctx, f"Failed to save global model: {str(e)}")
    
    def _get_model_path(self, persistor, fl_ctx: FLContext) -> Optional[str]:
        """Get the path to the saved model from the persistor.
        
        Args:
            persistor: The model persistor component
            fl_ctx: FLContext
            
        Returns:
            Path to the model file, or None if not found
        """
        # For PTFileModelPersistor
        if hasattr(persistor, '_ckpt_save_path'):
            return persistor._ckpt_save_path
        
        # For other persistors that might store path differently
        if hasattr(persistor, 'model_path'):
            return persistor.model_path
        
        # Fallback: try to construct path from common patterns
        try:
            workspace = fl_ctx.get_workspace()
            job_id = fl_ctx.get_job_id()
            run_dir = workspace.get_run_dir(job_id)
            
            # Common model file names
            common_names = [
                "models/FL_global_model.pt",
                "models/best_FL_global_model.pt",
                "FL_global_model.pt",
                "best_FL_global_model.pt",
            ]
            
            for name in common_names:
                path = os.path.join(run_dir, name)
                if os.path.exists(path):
                    return path
        except Exception as e:
            self.log_debug(fl_ctx, f"Could not determine model path: {e}")
        
        return None
```

### Step 2: Configure the Widget

Add the widget to your server configuration (`config_fed_server.json`):

```json
{
  "format_version": 2,
  "server": {
    "heart_beat_timeout": 600
  },
  "task_data_filters": [],
  "task_result_filters": [],
  "components": [
    {
      "id": "model_selector",
      "path": "nvflare.app_common.widgets.intime_model_selector.IntimeModelSelector",
      "args": {}
    },
    {
      "id": "persistor",
      "path": "nvflare.app_opt.pt.file_model_persistor.PTFileModelPersistor",
      "args": {
        "model": "net.Net"
      }
    },
    {
      "id": "shareable_generator",
      "path": "nvflare.app_common.shareablegenerators.full_model_shareable_generator.FullModelShareableGenerator",
      "args": {}
    },
    {
      "id": "aggregator",
      "path": "nvflare.app_common.aggregators.intime_accumulate_model_aggregator.InTimeAccumulateWeightedAggregator",
      "args": {
        "expected_data_kind": "WEIGHTS"
      }
    },
    {
      "id": "global_model_saver",
      "path": "global_model_saver.GlobalModelSaver",
      "args": {
        "model_file_name": "FL_global_model.pt",
        "persistor_id": "persistor",
        "component_name": "global_model"
      }
    }
  ],
  "workflows": [
    {
      "id": "scatter_and_gather",
      "path": "nvflare.app_common.workflows.scatter_and_gather.ScatterAndGather",
      "args": {
        "min_clients": 2,
        "num_rounds": 3,
        "start_round": 0,
        "wait_time_after_min_received": 10,
        "aggregator_id": "aggregator",
        "persistor_id": "persistor",
        "shareable_generator_id": "shareable_generator",
        "train_task_name": "train",
        "train_timeout": 0
      }
    }
  ]
}
```

### Step 3: Download the Model

After the job completes, download the model using the admin client:

```bash
# List jobs to find your job_id
> list_jobs

# Download the global model component
> download_job_components <job_id>
```

The model will be downloaded to:
```
<admin_download_dir>/<job_id>/ERRORLOG_global_model
```

This file is your `FL_global_model.pt` and can be loaded directly:

```python
import torch

# Load the downloaded model
model = torch.load("path/to/downloaded/ERRORLOG_global_model")
```

---

## Important Notes

### File Size Considerations

This approach works efficiently for **models of any size** (tested up to 70GB+) because:

1. **Storage**: When you pass a file path (string) to `set_client_data()`, NVFlare uses filesystem operations (move/copy) instead of loading the file into memory.

2. **Download**: The file is transferred using chunk-based streaming (default 1MB chunks), requiring only ~16-20MB of memory regardless of file size.

### Current Timeout Issue ⚠️

There is a known issue with the binary transfer timeout when downloading multiple large components:

**Problem:**
- The `BinaryTransfer` class has a hardcoded 5-second timeout (`nvflare/fuel/hci/server/binary_transfer.py:46`)
- This timeout triggers when there's no download activity for 5 seconds
- When downloading multiple files, the client unzips each file before requesting the next
- If unzipping takes > 5 seconds, the transaction times out and deletes remaining files

**Impact:**
- Single component downloads: ✅ **No problem** (timeout resets during active download)
- Multiple components with large files: ⚠️ **May fail** (unzip time between downloads can exceed timeout)

**Workaround:**
If you encounter timeout issues, you can modify `nvflare/fuel/hci/server/binary_transfer.py` line 46:

```python
# Change from:
timeout=5,

# To (for example):
timeout=300,  # 5 minutes
```

This gives enough time for the client to unzip large files between downloads.

**Note:** This timeout issue will likely be addressed in a future NVFlare release.

---

## Technical Details

### Why Use ERRORLOG Prefix?

The storage system validates component names against allowed prefixes defined in `nvflare/apis/storage.py`:

```python
class DataTypes(Enum):
    ERRORLOG = "ERRORLOG"
    # Future: MODEL = "MODEL" could be added
```

Valid component names are:
- Base types: `data`, `meta`, `workspace`
- Prefix types: `ERRORLOG`, `ERRORLOG_<name>`

We temporarily reuse the `ERRORLOG` prefix because it's already validated. A future improvement would be to add a `MODEL` prefix to the `DataTypes` enum.

### How Component Storage Works

1. **Save**: `job_manager.set_client_data()` stores the file in the job storage directory
   - Storage location: `<job_storage>/<job_id>/ERRORLOG_global_model`
   - Uses filesystem operations (efficient for large files)

2. **List**: `download_job_components` lists all non-standard components
   - Excludes: `data`, `meta`, `workspace`, `scheduled`
   - Includes: Anything matching `ERRORLOG_*` pattern

3. **Download**: Files are transferred using streaming protocol
   - Creates transaction with timeout
   - Transfers files chunk-by-chunk (1MB default)
   - Memory usage independent of file size

### Alternative: Save to Workspace

If you prefer not to use the ERRORLOG workaround, you can save the model to a specific location in the workspace and download the entire workspace:

```python
# In your widget
workspace = fl_ctx.get_workspace()
job_id = fl_ctx.get_job_id()
model_dir = os.path.join(workspace.get_run_dir(job_id), "final_model")
os.makedirs(model_dir, exist_ok=True)
model_path = os.path.join(model_dir, "FL_global_model.pt")
torch.save(model, model_path)

# Then download workspace
# download_job <job_id>
```

**Trade-off:** Downloads entire workspace (larger) vs. component-only download (smaller).

---

## Limitations

1. **ERRORLOG naming**: The component name will be `ERRORLOG_global_model` (hacky but functional)
2. **No autocomplete**: You need to know the component exists (or list components first)
3. **All-or-nothing**: `download_job_components` downloads ALL extra components, not selective
4. **Timeout issue**: Multi-file downloads with large files may timeout (workaround available)

---

## Future Improvements

Potential enhancements that would improve this workflow:

1. **Add MODEL prefix** to `DataTypes` enum in `nvflare/apis/storage.py`
2. **Selective component download**: Command like `download_job_component <job_id> <component_name>`
3. **Increase default timeout**: Change binary transfer timeout from 5s to more reasonable value
4. **Fix client unzipping**: Move unzip operations to after all downloads complete

---

## Testing Checklist

- [ ] Widget is in custom/ directory of your FL app
- [ ] Widget is configured in config_fed_server.json
- [ ] Persistor ID matches your configuration
- [ ] Job completes successfully
- [ ] Check server logs for "Global model saved as component" message
- [ ] Run `download_job_components <job_id>` in admin client
- [ ] Verify file exists at `<download_dir>/<job_id>/ERRORLOG_global_model`
- [ ] Verify model can be loaded with `torch.load()`

---

## Support

If you encounter issues:

1. Check server logs for error messages from `GlobalModelSaver`
2. Verify the persistor is saving the model (check workspace directory)
3. Ensure the component name matches in widget args
4. For timeout issues, consider increasing the timeout value
5. Verify you have the latest NVFlare version for best compatibility

---

## Example: Complete Job Directory Structure

```
my_federated_job/
├── app/
│   ├── config/
│   │   ├── config_fed_server.json  # Add global_model_saver component here
│   │   └── config_fed_client.json
│   └── custom/
│       ├── __init__.py
│       ├── net.py                   # Your model definition
│       ├── trainer.py               # Your training logic
│       └── global_model_saver.py    # Add this file (from Step 1)
└── meta.json
```

After job completion, download:
```bash
> download_job_components my_job_id
✓ Downloaded to: /home/user/admin/download/my_job_id/ERRORLOG_global_model
```

---

## Questions & Answers

**Q: Can I use this for models larger than available RAM?**  
A: Yes! As long as you pass the file path (not bytes) to `set_client_data()`, the system uses streaming and doesn't load the entire file into memory.

**Q: Will this work for non-PyTorch models?**  
A: Yes! You can save any file format (TensorFlow checkpoints, ONNX, etc.). Just adjust the save/load code in the widget.

**Q: Can I save multiple model versions?**  
A: Yes! Create multiple components with different `component_name` values (e.g., "global_model_final", "global_model_best", "global_model_round_10").

**Q: Does this work on the client side?**  
A: This example is for server-side global models. For client models, you can use similar logic in client-side event handlers, but typically client models are included in the workspace download.

---

*This workaround is intended for use until official single-file download functionality is added to NVFlare.*

