# TensorFlow MirroredStrategy Deadlock - Technical Analysis

**Date:** February 2, 2026  
**Issue:** TensorFlow Multi-GPU deadlocks in NVFlare external subprocess mode

---

## The Architecture

### How NVFlare External Process Communication Works

**1. Process Launch:**
```python
# SubprocessLauncher spawns child process via subprocess.Popen
process = subprocess.Popen(command, stdout=PIPE, stderr=STDOUT, env=env)
```

**2. Inter-Process Communication (IPC):**

NVFlare uses **FilePipe** for communication between parent and child:

```
Parent Process (NVFlare)        Child Process (client.py)
      |                                |
      |  Write file: x/msg_001.fobs    |
      |----------------------------->  |
      |                                | Read file
      |                                | Process message
      |  Wait for file deletion        | Delete file (ACK)
      |  <polling every 0.1s>           |
      |                                |
      |  Wait for response file        |
      |  <polling y/ directory>         | Write file: y/msg_002.fobs
      |  <-----------------------------| 
      | Read file                      |
      | Delete file (ACK)              |
```

**Key characteristics:**
- **Blocking with polling:** Sender blocks until file is deleted by receiver
- **File-based:** All messages written as files in shared directories
- **Heartbeat mechanism:** Every 5 seconds, checks if peer is alive (30s timeout)
- **Synchronous:** Each send() waits for acknowledgment before returning

**3. Heartbeat Thread:**

PipeHandler spawns a background thread for heartbeats:
```python
# From pipe_handler.py line 381
def _heartbeat(self):
    self.send_to_peer(self._make_event_message(Topic.HEARTBEAT, ""))
```

This runs every 5 seconds to prove the process is alive.

---

## TensorFlow Client Code

From `examples/advanced/multi-gpu/tf/client.py`:

```python
# Line 36: Create MirroredStrategy BEFORE flare.init()
strategy = tf.distribute.MirroredStrategy()
print(f"Number of devices: {strategy.num_replicas_in_sync}")

with strategy.scope():
    model = TFNet()
    model.compile(...)

# Line 48: Initialize NVFlare (sets up FilePipe)
flare.init()

# Line 51: Main loop
while flare.is_running():
    input_model = flare.receive()  # ✅ Works - blocks on pipe
    
    # Line 56: Load model weights
    for k, v in input_model.params.items():
        model.get_layer(k).set_weights(v)
    
    # Line 60: ❌ DEADLOCK HAPPENS HERE
    _, test_global_acc = model.evaluate(test_images, test_labels, verbose=2)
```

---

## The Deadlock Mechanism

### What Happens Step-by-Step:

**1. Initialization Phase (✅ Works)**
```
T=0s   : SubprocessLauncher spawns client.py
T=1s   : TensorFlow MirroredStrategy initializes
         - Discovers 2 GPUs
         - Sets up NCCL/collective communication backend
         - Creates internal threading for GPU coordination
T=2s   : flare.init() called
         - Opens FilePipe for IPC
         - Starts PipeHandler with heartbeat thread
         - FilePipe ready for communication
T=3s   : flare.receive() called
         - Blocks on pipe, waiting for message
         - ✅ Message received successfully
T=4s   : Model weights loaded
         - ✅ No issues
```

**2. Evaluation Phase (❌ Deadlocks)**
```
T=5s   : model.evaluate() called with MirroredStrategy
         
         MAIN THREAD:
         - TensorFlow enters strategy.run() internally
         - Distributes data across GPUs
         - Launches collective operations (AllReduce, etc.)
         - **BLOCKS waiting for GPU synchronization**
         
         TENSORFLOW INTERNAL THREADS:
         - Coordinate GPU operations
         - Use NCCL for inter-GPU communication
         - May hold GIL or critical TF locks
         
         NVFLARE HEARTBEAT THREAD (background):
         - Tries to send heartbeat via pipe.send()
         - pipe.send() needs to:
           1. Write file to filesystem
           2. Poll for file deletion (blocking)
           3. May need GIL for Python file I/O
         - **BLOCKED** - can't acquire resources held by TF

T=10s  : Heartbeat thread missed (expected every 5s)
T=15s  : Heartbeat thread still blocked
T=20s  : Heartbeat thread still blocked
...
T=300s : Heartbeat timeout (30s * retries)
         - Pipe declares peer GONE
         - Process killed
```

### Why PyTorch DDP Doesn't Deadlock:

**PyTorch DDP Architecture:**
```python
# Rank 0 (master process):
flare.init()              # Sets up pipe
while flare.is_running():
    model = flare.receive()  # Only rank 0 talks to NVFlare
    # Train with DDP
    # Sync via torch.distributed (separate from NVFlare)
    flare.send(model)        # Only rank 0 talks to NVFlare

# Rank 1, 2, ... (worker processes):
# No flare communication at all
# Only sync with rank 0 via torch.distributed
```

**Key difference:**
- **Separation of concerns:** DDP uses separate processes, only rank 0 handles NVFlare pipe
- **No conflict:** torch.distributed and FilePipe operate independently
- **Clean threading:** Each process has its own Python interpreter, GIL, etc.

### Why TensorFlow MirroredStrategy Deadlocks:

**TensorFlow Architecture:**
```python
# Single process (all code runs here):
strategy = tf.distribute.MirroredStrategy()  # Sets up GPU coordination
flare.init()                                  # Sets up pipe (same process!)

while flare.is_running():
    model = flare.receive()   # Pipe communication
    model.evaluate()          # TensorFlow GPU coordination
    # ❌ CONFLICT: Both want control of threading/GIL/resources
    flare.send(model)         # Never reaches here
```

**Key problems:**
1. **Single process:** MirroredStrategy and FilePipe compete for resources
2. **Threading conflict:** TF's internal threads vs NVFlare's heartbeat thread
3. **GIL contention:** TF GPU ops may hold GIL, blocking pipe file I/O
4. **Collective ops:** NCCL AllReduce might block main thread indefinitely
5. **No separation:** Can't isolate NVFlare comms from TF GPU coordination

---

## Specific Framework Changes Required

### Option 1: Make Pipe Communication Async/Non-Blocking

**Current behavior:**
```python
# pipe.send() is synchronous and blocking
def send(self, msg: Message, timeout=None) -> bool:
    file_path = self._create_file(to_dir, msg)
    return self._monitor_file(file_path, timeout)  # ❌ Blocks main thread

def _monitor_file(self, file_path, timeout):
    while True:  # ❌ Polling loop
        if not os.path.exists(file_path):
            return True
        if timeout and time.time() - start > timeout:
            return False
        time.sleep(0.1)  # ❌ Blocks for 0.1s each iteration
```

**Needed changes:**
```python
# Make pipe operations truly async using asyncio
import asyncio

async def send_async(self, msg: Message, timeout=None) -> bool:
    file_path = self._create_file(to_dir, msg)
    return await self._monitor_file_async(file_path, timeout)

async def _monitor_file_async(self, file_path, timeout):
    start = time.time()
    while True:
        if not os.path.exists(file_path):
            return True
        if timeout and time.time() - start > timeout:
            return False
        await asyncio.sleep(0.1)  # ✅ Yields control to event loop
```

**Impact:**
- Heartbeat thread can run without blocking main thread
- TensorFlow operations can proceed without pipe interference
- Would require refactoring entire pipe system to be async

**Complexity:** HIGH - Touches core communication layer

---

### Option 2: Use Socket-Based IPC Instead of FilePipe

**Current:** FilePipe uses filesystem polling (inherently blocking)

**Alternative:** Use socket-based communication:

```python
class SocketPipe(Pipe):
    def __init__(self, mode: Mode, port: int):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setblocking(False)  # ✅ Non-blocking
        
    def send(self, msg: Message, timeout=None) -> bool:
        # Use select() for non-blocking I/O
        ready = select.select([], [self.socket], [], timeout)
        if ready[1]:
            self.socket.sendall(pickle.dumps(msg))
            return True
        return False
    
    def receive(self, timeout=None) -> Message:
        # Use select() for non-blocking I/O
        ready = select.select([self.socket], [], [], timeout)
        if ready[0]:
            data = self.socket.recv(4096)
            return pickle.loads(data)
        return None
```

**Advantages:**
- Native non-blocking I/O via select/poll/epoll
- No filesystem contention
- Better performance

**Challenges:**
- Security (need encryption for network communication)
- Port management
- Firewall issues
- Still might conflict with TensorFlow's threading

**Complexity:** MEDIUM-HIGH

---

### Option 3: Run Heartbeat in Separate Process (Not Thread)

**Current:** Heartbeat runs in a thread within the same process

**Alternative:** Fork a separate heartbeat process:

```python
import multiprocessing

class PipeHandler:
    def start(self):
        # Spawn separate process for heartbeat
        self.heartbeat_process = multiprocessing.Process(
            target=self._heartbeat_loop,
            args=(self.pipe_path,)
        )
        self.heartbeat_process.start()
    
    def _heartbeat_loop(self, pipe_path):
        # This runs in completely separate process
        # Won't be blocked by TensorFlow in parent process
        while True:
            # Send heartbeat via simple file write
            write_heartbeat_file(pipe_path)
            time.sleep(5)
```

**Advantages:**
- Heartbeat isolated from TensorFlow
- Simpler than full async refactor

**Challenges:**
- Can't share pipe object across processes (pickling issues)
- Needs separate simplified IPC for heartbeat itself
- Still doesn't solve evaluate() blocking indefinitely

**Complexity:** MEDIUM

---

### Option 4: Special Mode for Single-Process Multi-GPU Frameworks

**Add configuration to disable external process for TensorFlow:**

```python
# In TensorFlow recipes
recipe = FedAvgRecipe(
    ...
    launch_external_process=False,  # ✅ Run in same process as NVFlare
    framework=FrameworkType.TENSORFLOW
)
```

**How it would work:**
```python
# Instead of subprocess:
# - Load client.py as a module
# - Call main() function directly
# - No IPC needed (same process)
# - TensorFlow can do whatever it wants with threading

# In ScriptRunner:
if not self.launch_external_process:
    # Import and run in-process
    import importlib.util
    spec = importlib.util.spec_from_file_location("client", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.main()  # Run directly
else:
    # Current external process approach
    ...
```

**Advantages:**
- No IPC deadlock possible (same process)
- Simpler for single-process frameworks
- Backward compatible (add new mode, don't break existing)

**Challenges:**
- Different behavior than external mode
- Memory isolation concerns
- Exception handling
- Resource cleanup

**Complexity:** MEDIUM - Adds new execution mode

---

### Option 5: Detect and Handle TensorFlow Blocking Operations

**Modify TensorFlow client to manually handle heartbeats:**

```python
import threading

# Create heartbeat thread BEFORE TensorFlow operations
def manual_heartbeat():
    while running:
        flare.send_heartbeat()  # New API
        time.sleep(5)

threading.Thread(target=manual_heartbeat, daemon=True).start()

# Now TensorFlow can block all it wants
strategy = tf.distribute.MirroredStrategy()
while flare.is_running():
    input_model = flare.receive()
    model.evaluate(...)  # Can block - heartbeat thread independent
    model.fit(...)
    flare.send(output_model)
```

**Requires NVFlare changes:**
```python
# Add public API for manual heartbeat
class ClientAPI:
    def send_heartbeat(self):
        """Manually send heartbeat to keep pipe alive during long operations."""
        self.pipe_handler.send_heartbeat()
```

**Advantages:**
- Minimal framework changes
- User can control when heartbeats happen
- Works around blocking operations

**Challenges:**
- Requires users to modify their code
- Not automatic/transparent
- Easy to forget/misuse

**Complexity:** LOW-MEDIUM

---

## Recommended Solution: Option 4 (In-Process Mode for TensorFlow)

**Why this is best:**

1. **Addresses root cause:** Removes IPC entirely for single-process frameworks
2. **Backward compatible:** External process mode still available for PyTorch
3. **User-friendly:** Just set `launch_external_process=False`
4. **Lower risk:** Contained change, doesn't modify core pipe system
5. **Better for TensorFlow:** MirroredStrategy designed for single-process usage anyway

### Implementation Steps:

**Step 1: Add in-process execution to ScriptRunner** (`nvflare/app_common/executors/script_runner.py`)

```python
class ScriptRunner(Executor):
    def execute(self, task_name: str, shareable: Shareable, fl_ctx: FLContext, abort_signal: Signal) -> Shareable:
        if self.launch_external_process:
            # Current external subprocess approach
            return self._execute_external(task_name, shareable, fl_ctx, abort_signal)
        else:
            # New in-process approach
            return self._execute_inprocess(task_name, shareable, fl_ctx, abort_signal)
    
    def _execute_inprocess(self, task_name, shareable, fl_ctx, abort_signal):
        # Import and execute script as module in same process
        import importlib.util
        import sys
        
        # Add script directory to path
        script_dir = os.path.dirname(os.path.abspath(self.script))
        sys.path.insert(0, script_dir)
        
        try:
            # Load module
            spec = importlib.util.spec_from_file_location("client_module", self.script)
            module = importlib.util.module_from_spec(spec)
            
            # Set up environment for flare.receive()/send()
            # (pipe already established in parent context)
            
            # Execute module (calls main())
            spec.loader.exec_module(module)
            
            # Get result from pipe
            return self._get_result_from_pipe()
        finally:
            sys.path.remove(script_dir)
```

**Step 2: Modify Client API to support in-process mode**

Currently, `flare.init()` expects to be in subprocess. Need to detect mode:

```python
# In nvflare/client/api.py
def init():
    # Detect if running in external process or in-process
    if os.environ.get("CLIENT_API_TYPE") == "EX_PROCESS_API":
        # External process mode (current behavior)
        _init_external_process()
    else:
        # In-process mode (new behavior)
        _init_inprocess()

def _init_inprocess():
    # Use thread-local storage or context vars for pipe
    # Don't create new pipe, use parent's pipe
    global _api_instance
    _api_instance = InProcessClientAPI(pipe=_get_pipe_from_context())
```

**Step 3: Handle exceptions and cleanup**

In-process execution needs careful exception handling:

```python
def _execute_inprocess(self, ...):
    try:
        spec.loader.exec_module(module)
        return self._get_result()
    except Exception as e:
        self.log_exception(e)
        # Don't crash parent process
        return make_error_shareable(str(e))
    finally:
        # Clean up module to avoid namespace pollution
        if "client_module" in sys.modules:
            del sys.modules["client_module"]
```

**Step 4: Update TensorFlow recipes**

```python
class FedAvgRecipe(Recipe):
    def __init__(
        self,
        ...
        launch_external_process: bool = False,  # ✅ Default False for TF
        ...
    ):
        if not launch_external_process:
            self.logger.info(
                "Running in-process mode (recommended for TensorFlow MirroredStrategy)"
            )
```

---

## Alternative Quick Fix: Disable MirroredStrategy Evaluation Before Training

**Minimal code change to client.py:**

```python
# Line 59-61: Comment out initial evaluation
# This is where deadlock happens
# _, test_global_acc = model.evaluate(test_images, test_labels, verbose=2)
# print(f"Accuracy of received model: {test_global_acc * 100:.2f}%")
test_global_acc = 0.0  # Dummy value

# Keep training (line 64-65)
model.fit(train_images, train_labels, epochs=1, validation_data=(test_images, test_labels))
```

**Why this might work:**
- model.fit() includes validation, so GPU sync already happens there
- Maybe the initial evaluate() before any training is problematic
- Worth trying as a quick test

**Limitations:**
- Doesn't solve root cause
- Hacky workaround
- Loses initial model evaluation metric

---

## Testing Requirements

If implementing Option 4 (in-process mode):

**Test matrix:**

| Framework | Mode | Multi-GPU | Expected Result |
|-----------|------|-----------|-----------------|
| PyTorch DDP | External | Yes | ✅ PASS (already verified) |
| PyTorch DDP | In-process | Yes | Should PASS |
| TensorFlow | External | Yes | ❌ FAIL (deadlock) |
| TensorFlow | In-process | Yes | Should PASS |
| TensorFlow | External | No (single GPU) | Might PASS |

**Regression testing:**
- Ensure PyTorch examples still work with external process
- Verify memory isolation adequate for in-process mode
- Test exception handling in in-process mode

---

## Summary of Required Changes

### Minimal Changes (Option 5 - Quick Test):
1. Comment out line 60 in `examples/advanced/multi-gpu/tf/client.py`
2. Test if training proceeds without deadlock
3. **Effort:** 5 minutes
4. **Risk:** Low (just testing)
5. **Limitations:** Workaround, not a fix

### Recommended Changes (Option 4 - In-Process Mode):
1. Add `_execute_inprocess()` to ScriptRunner (100-150 lines)
2. Modify `flare.init()` to detect and support in-process mode (50 lines)
3. Update TensorFlow recipes to use in-process by default (10 lines)
4. Add comprehensive testing (new test suite)
5. **Effort:** 2-3 days of dev + 1-2 days testing
6. **Risk:** Medium (new execution mode)
7. **Benefit:** Proper solution, user-friendly

### Complex Changes (Option 1 - Async Pipes):
1. Refactor entire pipe system to use asyncio (500+ lines changed)
2. Convert PipeHandler to async (200+ lines)
3. Make all pipe implementations async (FilePipe, CellPipe, MemoryPipe)
4. Update all callers to use async/await
5. **Effort:** 1-2 weeks of dev + 1 week testing
6. **Risk:** HIGH (core infrastructure change)
7. **Benefit:** Better architecture overall, but massive undertaking

---

## Conclusion

**Short answer:** The deadlock happens because:
1. TensorFlow's MirroredStrategy blocks the main thread during GPU operations
2. NVFlare's heartbeat thread can't send heartbeats (needs file I/O, blocked by TF)
3. After 5 minutes, heartbeat timeout triggers, process killed

**To fix properly, need:**
- **Option 4:** Add in-process execution mode (~2-3 days dev work)
- **OR Option 5:** Quick workaround - skip initial evaluation (~5 min test)
- **OR Option 1:** Massive async refactor (~2 weeks work)

**Recommendation:** 
1. Try Option 5 as immediate test (5 minutes)
2. If that works, escalate to core team to implement Option 4 properly
3. Don't attempt Option 1 (async refactor) unless core team approves major architectural change

---

## Files Involved

**Core framework files that would need changes:**
- `nvflare/app_common/executors/script_runner.py` - Add in-process mode
- `nvflare/client/api.py` - Support in-process initialization
- `nvflare/app_opt/tf/recipes/*.py` - Default to in-process mode
- `nvflare/fuel/utils/pipe/pipe_handler.py` - (Optional) Async support

**Example files (quick workaround):**
- `examples/advanced/multi-gpu/tf/client.py` - Comment out line 60

**Testing impact:**
- All external process examples need regression testing
- New in-process mode needs comprehensive testing
- TensorFlow-specific integration tests needed
