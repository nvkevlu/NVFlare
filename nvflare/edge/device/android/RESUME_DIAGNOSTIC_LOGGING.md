# Android Resume Issue - Diagnostic Logging

## Problem Statement

QA reported that the Android app resume functionality is broken:
1. User presses "Start Training" → Job starts ✓
2. User presses "Stop Training" → Job stops ✓
3. User presses "Start Training" again → **Job received but does not continue** ✗

The UI shows the job is received, but training doesn't progress.

## Investigation Findings

### 1. Resume Flow Analysis

Both iOS and Android create a **NEW runner instance** on each "start training" press. This is expected behavior because:
- The runner is a session-level object
- Each session gets a fresh runner
- The **server** is responsible for tracking completion state and resuming from the correct round

### 2. Key Architectural Difference Found

**iOS Pattern (Correct):**
```swift
private class SimpleDataSource: NSObject, NVFlareDataSource {
    private let dataset: NVFlareDataset
    
    func getDataset(datasetType: String, ctx: NVFlareContext) -> NVFlareDataset? {
        return dataset  // ← Returns THE SAME instance every time
    }
}
```

**Android Pattern (Potentially Problematic):**
```kotlin
class AndroidDataSource(private val context: AndroidContext) : DataSource {
    override fun getDataset(datasetType: String, ctx: Context): Dataset {
        return when (datasetName.lowercase()) {
            "cifar10" -> CIFAR10Dataset(context, phase)  // ← Creates NEW instance every time!
            "xor" -> XORDataset(phase)                    // ← Creates NEW instance every time!
            ...
        }
    }
}
```

**Impact:** This creates multiple dataset instances:
1. One in `FlareRunnerController.startTraining()` (stored in `currentDataset`)
2. Another in `AndroidFlareRunner.doOneJob()` (actually used for training)

However, this should NOT prevent resumption because:
- The server tracks which rounds are complete
- The server sends the correct `contributionRound` in task metadata
- A fresh dataset should be fine since model state comes from the server

### 3. Possible Root Causes

The "job does not continue" symptom could mean:

**A. Training Hangs** - Most likely scenarios:
- Task fetching returns NO_TASK repeatedly (server not sending tasks)
- Task fetching returns wrong status code
- Dataset creation fails on restart
- Some exception occurs silently

**B. Training Starts from Round 0** - Possible causes:
- Server not maintaining state properly
- Server not recognizing the client on reconnect
- Device ID mismatch between sessions

**C. Error Occurs** - Possible causes:
- Dataset validation fails
- Task execution throws exception
- Network error on task fetch

## Diagnostic Logging Added

### Location
File: `nvflare/edge/device/android/sdk/core/AndroidFlareRunner.kt`

### What Was Added

#### 1. Runner Lifecycle Logging
```
===== Starting AndroidFlareRunner (NEW INSTANCE) =====
Runner hash: <hashcode>
AbortSignal triggered: false
----- Starting new job iteration -----
```

**Look for:** Verify a new runner is created each time "Start Training" is pressed

#### 2. Job Fetching Logging
```
>>>>> doOneJob() STARTED <<<<<
Current job ID: <id or null>
Job name: cifar10_et
Calling dataSource.getDataset() for job: cifar10_et
Dataset created successfully - hash: <hashcode>, size: <N>
About to call getJob()...
✓ Job received successfully!
Processing job: cifar10_et (ID: <job_id>)
```

**Look for:** 
- Does `getJob()` succeed on restart?
- Does it return the SAME job ID as before stop?
- Is the dataset created successfully?

#### 3. Task Loop Logging
```
===== Entering task processing loop =====
Task loop iteration #1 - calling getTask()...
getTask() returned: task=present, sessionDone=false
✓ Task #1 received, processing...
```

**Look for:**
- Does the task loop start?
- Does `getTask()` return tasks or null?
- How many tasks are processed?

#### 4. Task Fetch Status Logging
```
>>>>> getTask() STARTED <<<<<
Current job ID for task fetch: <job_id>
Task fetch attempt #1
Fetching task for job ID: <job_id>
Calling connection.fetchTask(<job_id>)...
✓ Task response received!
Task status: OK
Task ID: <task_id>
Task name: train
```

**Look for:**
- What status does the server return? (OK, NO_TASK, DONE, etc.)
- Which FSM branch is taken?
  - `*** OK STATUS - processing task ***` → Normal
  - `*** RETRY STATUS: NO_TASK - waiting 5000ms before retry ***` → Server not ready
  - `*** NO_JOB STATUS - job completed, looking for new jobs ***` → Job done
  - `*** TERMINAL STATUS: DONE - ending session ***` → Session complete

#### 5. Training Execution Logging
```
Starting training for round 3/10...
Firing BEFORE_TRAIN event...
Executing task via executor...
✓ Training completed in 15234ms for round 3
```

**Look for:**
- Does training actually execute?
- What round number is shown? (Should continue from where it left off)
- Does training complete successfully?

#### 6. Result Reporting Logging
```
Sending results to server for round 3...
✓ Results sent successfully in 523ms for round 3
Completed round 3/10, continuing to next task...
```

**Look for:**
- Do results send successfully?
- Does the loop continue to the next task?

## How to Diagnose Using Logs

### Step 1: Reproduce the Issue
1. Press "Start Training"
2. Let it run for 2-3 rounds
3. Press "Stop Training"
4. Press "Start Training" again
5. Observe: "Job received but does not continue"

### Step 2: Examine Android Studio Logcat

Filter by tag: `AndroidFlareRunner`

### Step 3: Identify Where It Gets Stuck

Look for the **last log message** before it stops progressing:

| Last Log Message | Means | Likely Cause |
|------------------|-------|--------------|
| `About to call getJob()...` | Stuck in job fetching | Server not responding to job requests |
| `✓ Job received successfully!` <br>then nothing | Stuck before task loop | Exception in config processing |
| `===== Entering task processing loop =====` <br>then nothing | Stuck in getTask() | Task fetch hangs or returns null |
| `Task fetch attempt #1` <br>repeating many times | Stuck in task retry loop | Server returning NO_TASK or RETRY indefinitely |
| `*** RETRY STATUS: NO_TASK ***` <br>repeating | Server not sending tasks | Server doesn't think client should continue |
| `Starting training for round 0/10...` <br>(should be round 3+) | Wrong round number | Server not maintaining state |
| `Executing task via executor...` <br>then nothing | Training hangs | ETTrainer or dataset issue |

### Step 4: Compare First Run vs Restart

**First "Start Training" (should work):**
```
===== Starting AndroidFlareRunner (NEW INSTANCE) =====
>>>>> doOneJob() STARTED <<<<<
Current job ID: null
...
✓ Job received successfully!
Processing job: cifar10_et (ID: abc-123)
===== Entering task processing loop =====
Task loop iteration #1 - calling getTask()...
Task status: OK
Starting training for round 0/10...
✓ Training completed in 15000ms for round 0
...
```

**Restart "Start Training" (broken):**
```
===== Starting AndroidFlareRunner (NEW INSTANCE) =====
>>>>> doOneJob() STARTED <<<<<
Current job ID: null
...
✓ Job received successfully!
Processing job: cifar10_et (ID: abc-123)  ← Same job ID
===== Entering task processing loop =====
Task loop iteration #1 - calling getTask()...
[LOOK HERE FOR DIFFERENCES]
```

## Expected Behavior on Resume

When training is restarted after stop, the logs should show:

1. ✓ New runner instance created
2. ✓ Dataset created successfully
3. ✓ Same job ID received from server
4. ✓ Task loop starts
5. ✓ Server returns OK status with task
6. ✓ Task has `contribution_round` = N (where N is next incomplete round)
7. ✓ Training executes for round N
8. ✓ Results sent successfully
9. ✓ Loop continues

## Next Steps

1. **Run the test** with these logs enabled
2. **Capture the logcat output** showing the problem
3. **Identify** where exactly it gets stuck using the table above
4. **Share the logs** so we can pinpoint the root cause

## Potential Fixes (Based on Diagnosis)

| Symptom | Root Cause | Fix |
|---------|------------|-----|
| Server returns NO_TASK indefinitely | Server state issue | Check server logs, may need server-side fix |
| Server returns DONE immediately | Server thinks job is complete | Check job configuration, may need to reset server state |
| Training hangs in executor | Dataset state issue | Add dataset.reset() call before training |
| Wrong round number (starts from 0) | Client not reading contributionRound | Already fixed in current code |
| Exception in config processing | Missing component resolver | Add resolver for new component type |

## Code Changes in This Commit

- Added comprehensive diagnostic logging to `AndroidFlareRunner.kt`
- Added runner instance hashcode tracking
- Added iteration counters for loops
- Added success/failure indicators (✓ / ✗)
- Added FSM transition logging with clear markers (*** ***)
- Added timing information for key operations

No functional changes were made - only diagnostic logging added.

