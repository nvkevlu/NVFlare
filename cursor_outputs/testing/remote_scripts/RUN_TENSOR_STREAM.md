# Running Tensor-Stream Test on Remote GPU Machine

## Quick Start

### Step 1: Transfer the script to remote machine

```bash
# From your local machine:
cd /Users/kevlu/workspace/repos/secondcopynvflare/cursor_outputs/testing/remote_scripts/
scp test_tensor_stream.sh local-kevlu@ipp1-1125:~/
```

### Step 2: SSH to remote machine and run

```bash
# SSH to remote machine:
ssh local-kevlu@ipp1-1125

# Make script executable:
chmod +x test_tensor_stream.sh

# Start a screen session (recommended for long test):
screen -S tensor_stream

# Run the test:
./test_tensor_stream.sh
```

### Step 3: Detach from screen and monitor

```bash
# Detach from screen: Press Ctrl-A, then D

# Monitor from local machine:
ssh local-kevlu@ipp1-1125 'tail -f ~/nvflare_testing/logs/tensor-stream_*.log' | grep -E "Round|loss|Accuracy|INFO|SUCCESS|ERROR"

# Or monitor GPUs:
ssh local-kevlu@ipp1-1125 'watch -n 10 nvidia-smi'

# Reattach to screen:
ssh local-kevlu@ipp1-1125
screen -r tensor_stream
```

---

## What the Test Does

### Phase 1: Setup (5-10 minutes)
- ✅ Verifies environment (Python, NVFlare, CUDA)
- ✅ Installs dependencies from requirements.txt
- ✅ Pre-downloads IMDB dataset (stanfordnlp/imdb)
- ✅ Pre-downloads GPT-2 model (~620MB)

### Phase 2: Training (60-90 minutes)
- Runs federated learning with GPT-2
- 5 rounds of training
- 2 clients (simulated)
- IMDB sentiment analysis task
- Progress updates every 60 seconds

### Phase 3: Results (automatic)
- Saves logs to `~/nvflare_testing/logs/`
- Saves results to `~/nvflare_testing/results/`
- Shows summary (rounds, duration, errors)

---

## Expected Output

### Success Indicators:
```
[INFO] Starting Tensor Streaming Test
[INFO] Test running for X minutes...
[INFO] Recent activity:
                Round 0 started.
loss: 2.351
Accuracy: 52.3%
                Round 1 started.
loss: 2.123
Accuracy: 54.7%
...
[SUCCESS] ✅ Tensor Streaming test PASSED!
[INFO] Duration: 87 minutes
🎉 Tensor Streaming test completed successfully!
```

### GPU Activity:
- Both GPUs should show activity during training
- Memory usage: ~2-4GB per GPU (model + data)
- Utilization: 40-80% during training epochs

---

## Troubleshooting

### If test fails with "Out of memory":
- This is unlikely with 2x A30 (24GB each)
- GPT-2 is only ~620MB
- Check: `nvidia-smi` to see what else is using GPU

### If test fails with "Dataset not found":
- Dataset migration fix already applied
- Script pre-downloads to avoid this
- Manual check: `python -c "from datasets import load_dataset; load_dataset('stanfordnlp/imdb')"`

### If test hangs:
- 2-hour timeout will kill it automatically
- Manual kill: `pkill -f tensor-stream/job.py`
- Clean up: `rm -rf /tmp/nvflare/simulation/tensor_stream`

### If screen session lost:
```bash
# Find session:
screen -ls

# Reattach:
screen -r tensor_stream

# If "Attached" error:
screen -d -r tensor_stream
```

---

## After Test Completes

### View Results:
```bash
# SSH to remote:
ssh local-kevlu@ipp1-1125

# View summary:
cat ~/nvflare_testing/results/tensor-stream_*/summary.txt

# View full log:
less ~/nvflare_testing/logs/tensor-stream_*.log

# Search for errors:
grep -i "error\|exception" ~/nvflare_testing/logs/tensor-stream_*.log | grep -v "ERROR - Processing frame"

# Check rounds:
grep "Round [0-9]* started" ~/nvflare_testing/logs/tensor-stream_*.log
```

### Copy Results to Local Machine:
```bash
# From local machine:
TIMESTAMP=<get_from_remote>  # e.g., 20260128_230000

scp -r local-kevlu@ipp1-1125:~/nvflare_testing/logs/tensor-stream_${TIMESTAMP}.log \
    /Users/kevlu/workspace/repos/secondcopynvflare/cursor_outputs/testing/remote_logs/

scp -r local-kevlu@ipp1-1125:~/nvflare_testing/results/tensor-stream_${TIMESTAMP}/ \
    /Users/kevlu/workspace/repos/secondcopynvflare/cursor_outputs/testing/remote_results/
```

---

## Estimated Timeline

| Phase | Duration | Description |
|-------|----------|-------------|
| Transfer script | 1 min | scp from local to remote |
| Setup | 5-10 min | Download dataset + model |
| Training | 60-90 min | 5 rounds federated learning |
| **Total** | **~1.5-2 hours** | End-to-end |

---

## Success Criteria

✅ **Test PASSES if:**
- Exit code: 0
- "Finished FedAvg" found in log
- 5 rounds completed
- No DXO errors
- Model accuracy improves over rounds

❌ **Test FAILS if:**
- Exit code: non-zero
- Errors in log (except "Processing frame" errors which are normal)
- DXO errors (external process bug)
- Timeout (>2 hours)
- GPU out of memory

---

## Questions?

**GPU not working?**
- Check: `nvidia-smi` shows GPUs
- Check: `python -c "import torch; print(torch.cuda.is_available())"`

**Taking too long?**
- Normal: 1-2 hours for full test
- Check progress: `tail ~/nvflare_testing/logs/tensor-stream_*.log`

**Want to stop test?**
- Press Ctrl-C if attached to screen
- Or: `pkill -f tensor-stream/job.py`
- Cleanup runs automatically on exit
