# BioNeMo Test - Monitoring & Troubleshooting Guide

**Date:** January 30, 2026  
**Purpose:** How to monitor BioNeMo tests and determine if they're stuck

---

## Quick Status Check

```bash
# Check if job is running
ps aux | grep "job.py\|python3 job.py" | grep -v grep

# Check log for recent activity (last 20 lines)
tail -20 ~/nvflare_testing/logs/bionemo_*.log

# Check GPU usage (should be active during training)
nvidia-smi

# Monitor log in real-time
tail -f ~/nvflare_testing/logs/bionemo_*.log
```

---

## How to Tell if It's Stuck

### Signs of NORMAL Progress:

1. **Log shows round progress:**
   ```
   Round 0 started.
   Round 1 started.
   Round 2 started.
   ```

2. **Training steps appear:**
   ```
   [INFO] Epoch 0:  10%|█         | 1/10 [00:05<00:45, 5.06s/it]
   [INFO] Training step completed
   ```

3. **GPU is active:**
   ```bash
   nvidia-smi
   # Shows GPU utilization: 50-100%
   # Shows memory used: several GB
   ```

4. **Log grows over time:**
   ```bash
   watch -n 5 'ls -lh ~/nvflare_testing/logs/bionemo_*.log'
   # Size increases every few seconds
   ```

5. **Python process CPU time increases:**
   ```bash
   ps aux | grep job.py
   # CPU time keeps growing (4th column)
   ```

### Signs It's STUCK:

1. **Log stops growing:**
   ```bash
   ls -lh ~/nvflare_testing/logs/bionemo_*.log
   # Size unchanged for 5+ minutes
   ```

2. **No GPU activity:**
   ```bash
   nvidia-smi
   # GPU utilization: 0%
   # No memory used
   ```

3. **CPU time frozen:**
   ```bash
   ps aux | grep job.py
   # CPU time not increasing for 5+ minutes
   ```

4. **Same log line repeating:**
   ```
   [WARNING] Waiting for response...
   [WARNING] Waiting for response...
   [WARNING] Waiting for response...
   ```

5. **Error loop in log:**
   ```bash
   grep -c "FileNotFoundError\|Exception\|Error" ~/nvflare_testing/logs/bionemo_*.log
   # If count keeps increasing rapidly
   ```

---

## What Your Current Processes Show

```bash
root  81332  4.4  0.2 5881712 554048 ?  Sl  19:38  0:08 python3 job.py --num_clients 2 ...
```

**Analysis:**
- **CPU time: 0:08** (8 seconds) - Process has used 8 CPU seconds total
- **%CPU: 4.4%** - Currently using 4.4% of one CPU core
- **Memory: 554MB** - Normal for Python with NVFlare loaded
- **State: Sl** - Sleeping (waiting for I/O or events)

**Status:** Process is **alive but idle/waiting**. Based on earlier logs showing `FileNotFoundError`, it's likely:
- Starting rounds
- Clients trying to load data
- Failing due to missing CSV files
- Waiting/retrying

**This is NOT stuck** - it's running but failing due to missing data.

---

## Expected Timeline

### First Run (with data prep):
```
[0-5 min]   Data preparation
            - Download dataset from TDC
            - Create train/val/test splits
            - Generate per-client CSVs
            
[5-10 min]  Model download
            - Download ESM2-8m model (~500MB)
            - Cache at ~/.cache/bionemo/
            
[10-25 min] Federated training
            - Round 0: ~5 minutes
            - Round 1: ~5 minutes
            - Round 2: ~5 minutes
            - Model aggregation & validation
            
[25-30 min] Finalization
            - Save results
            - Generate summary
```

### Subsequent Runs (data/model cached):
```
[0-1 min]   Setup (skip data prep, model cached)
[1-20 min]  Federated training (3 rounds)
[20-25 min] Finalization
```

---

## Real-Time Monitoring Commands

### 1. Watch Log Tail (Most Useful)
```bash
tail -f ~/nvflare_testing/logs/bionemo_*.log
```
Press `Ctrl-C` to stop watching.

### 2. Monitor GPU Every 2 Seconds
```bash
watch -n 2 nvidia-smi
```
Look for:
- GPU utilization % (should be 50-100% during training)
- Memory usage (should be 2-8GB)
- Active processes

### 3. Monitor Process CPU
```bash
watch -n 5 'ps aux | grep "job.py" | grep -v grep'
```
The time in column 10 should increase.

### 4. Count Recent Log Activity
```bash
watch -n 10 'tail -100 ~/nvflare_testing/logs/bionemo_*.log | grep -c "INFO\|Step\|Round"'
```
Count should increase if making progress.

### 5. Check Data Files Exist
```bash
ls -lR /tmp/data/sabdab_chen/
```
Should show:
```
/tmp/data/sabdab_chen/train/
  sabdab_chen_site-1_train.csv
  sabdab_chen_site-2_train.csv
  sabdab_chen_full_train.csv

/tmp/data/sabdab_chen/val/
  sabdab_chen_valid.csv
```

---

## How Long to Wait Before Killing

| Phase | Expected Duration | Wait Before Killing |
|-------|-------------------|---------------------|
| **Data prep** | 2-5 min | 10 minutes |
| **Model download** | 2-5 min | 10 minutes |
| **Per round training** | 5-8 min | 15 minutes |
| **Total first run** | 25-35 min | 45 minutes |
| **Silent period** | 0-1 min | 5 minutes |

**Rule of thumb:** 
- If log is updating: keep waiting
- If log silent for 5+ minutes: investigate
- If no GPU activity for 10+ minutes during training: likely stuck

---

## What to Do If Stuck

### 1. Check for Errors
```bash
grep -i "error\|exception\|failed\|traceback" ~/nvflare_testing/logs/bionemo_*.log | tail -50
```

### 2. Check if Data Exists
```bash
ls -lh /tmp/data/sabdab_chen/train/
```
If missing, kill and re-run with data prep.

### 3. Kill Gracefully
```bash
# Find Docker container
docker ps | grep bionemo

# Stop it
docker stop <container_id>

# Or kill Python process
pkill -f "job.py"
```

### 4. Clean Up and Retry
```bash
# Clean simulation workspace
rm -rf /tmp/nvflare/bionemo/

# Re-run test
./test_bionemo.sh
```

### 5. Check Docker Logs
```bash
docker logs <container_id>
```

---

## Common Issues & Solutions

### Issue: "FileNotFoundError: sabdab_chen_site-X_train.csv"
**Cause:** Data not prepared  
**Solution:** Script now auto-preps data, but if it failed:
```bash
docker run --rm -v /tmp/data:/tmp/data nvcr.io/nvidia/clara/bionemo-framework:2.5 \
  bash -c "pip install PyTDC && python3 /workspace/bionemo/downstream/sabdab/prepare_sabdab_data.py"
```

### Issue: "OutOfMemoryError"
**Cause:** GPU memory exhausted  
**Solution:** Reduce batch size or use smaller model:
```bash
# Edit test_bionemo.sh:
MODEL="8m"         # Already smallest
NUM_CLIENTS=1      # Reduce from 2 to 1
```

### Issue: Process runs for hours
**Cause:** May be doing full training instead of limited steps  
**Solution:** Check LOCAL_STEPS=10 in script (should be small for testing)

### Issue: Container keeps restarting
**Cause:** Crash loop  
**Solution:** Check logs for crash reason:
```bash
grep -A 20 "Traceback\|Segmentation fault\|CUDA error" ~/nvflare_testing/logs/bionemo_*.log
```

---

## Success Indicators

You'll know it succeeded when you see:

```
Job Status is: FINISHED:COMPLETED
Result can be found in : /tmp/nvflare/bionemo/sabdab/...

🎉 BioNeMo test PASSED!
Duration: XXXX seconds
```

And the script exits with code 0.

---

## Current Recommendation

Based on your earlier error (FileNotFoundError), **kill the current process** and re-run with the updated script that includes data prep:

```bash
# Kill current run
pkill -f "job.py"
docker ps -q | xargs -r docker stop

# Transfer updated script
scp test_bionemo.sh local-kevlu@ipp1-1125:~/

# Re-run with data prep
./test_bionemo.sh
```

The new script will:
1. ✅ Check if data exists
2. ✅ Prepare data if missing (2-5 min)
3. ✅ Then run training (10-25 min)
4. ✅ Complete successfully

**Total expected time:** 15-35 minutes (first run with data prep)
