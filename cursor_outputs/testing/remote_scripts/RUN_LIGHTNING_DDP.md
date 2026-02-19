# Running PyTorch Lightning DDP Multi-GPU Test

## Quick Start

This test validates PyTorch Lightning DDP integration with NVFlare on 2+ GPUs.

### 1. Transfer Files to Remote Machine

```bash
# From local machine
cd /Users/kevlu/workspace/repos/secondcopynvflare

# Transfer updated job.py
scp examples/advanced/multi-gpu/lightning/job.py \
    local-kevlu@ipp1-1125:~/nvflare_testing/NVFlare/examples/advanced/multi-gpu/lightning/

# Transfer test script
scp cursor_outputs/testing/remote_scripts/test_lightning_ddp.sh \
    local-kevlu@ipp1-1125:~/
```

### 2. Run Test

```bash
# SSH to remote machine
ssh local-kevlu@ipp1-1125

# Make script executable
chmod +x test_lightning_ddp.sh

# Run in screen (recommended for long-running test)
screen -S lightning_test
./test_lightning_ddp.sh

# Or run with nohup
nohup ./test_lightning_ddp.sh > lightning_test.log 2>&1 &
```

### 3. Monitor Progress

```bash
# Watch the log
tail -f ~/nvflare_testing/logs/lightning-ddp_*.log

# Check GPU usage (in another terminal)
watch -n 1 nvidia-smi

# If using screen, detach with: Ctrl-A, then d
# Reattach with: screen -r lightning_test
```

## What This Test Does

1. **Environment Check**: Verifies NVFlare, PyTorch Lightning, CUDA, and GPUs
2. **Cleanup**: Removes old `/tmp` simulation directories to free space
3. **Dependencies**: Installs example requirements
4. **Dataset**: Prepares CIFAR-10 dataset
5. **Training**: Runs federated learning with DDP on 2 GPUs per client
6. **Analysis**: Checks for DXO errors, training completion, and progress

## Key Fix Applied

**Problem:** `/tmp` directory (512MB tmpfs) fills up during simulation

**Solution:** Modified `job.py` to accept `--work_dir` argument and use custom workspace:
```python
# Added to job.py:
parser.add_argument("--work_dir", type=str, default="/tmp/nvflare/jobs/workdir")
env = SimEnv(num_clients=args.n_clients, workspace_root=args.work_dir)
```

Test script now runs:
```bash
python job.py --work_dir ~/nvflare_testing/results/lightning-ddp_TIMESTAMP/workspace
```

This uses the home directory (3TB) instead of `/tmp` (512MB).

## Expected Results

### Success Scenario ✅
```
Duration: 20-30 minutes
Rounds: 5
DXO Errors: 0
Exit Code: 0
FedAvg completion marker: Found
```

### Failure Scenarios ❌

**1. DXO Error (External Process Bug)**
```
ValueError: the shareable is not a valid DXO - expect content_type DXO but got None
```
- Same bug as TensorFlow Multi-GPU
- Indicates external process communication issue
- Would require core framework fix

**2. Process Termination (Known Lightning Bug)**
```
trainer.test() or trainer.predict() not completing
```
- Known issue with external process termination
- Training (`trainer.fit()`) should still work
- Client process killed after first model send

**3. Space Issues (Should be fixed now)**
```
OSError: [Errno 28] No space left on device
```
- Should NOT happen with new --work_dir fix
- If it does, investigate further

## Output Location

```
~/nvflare_testing/
├── logs/
│   └── lightning-ddp_TIMESTAMP.log          # Full test log
└── results/
    └── lightning-ddp_TIMESTAMP/
        ├── summary.txt                       # Test summary
        ├── lightning-ddp_TIMESTAMP.log      # Copy of log
        └── workspace/                        # Simulation workspace
            └── lightning_ddp/               # NVFlare simulation output
                ├── server/
                └── site-1/, site-2/
```

## Troubleshooting

### Test completes in seconds with "Exit Code: 0" but 0 rounds
**Cause:** Training crashed but Python script didn't fail

**Check:** Look for errors in log:
```bash
grep -i "error\|exception" ~/nvflare_testing/logs/lightning-ddp_*.log | head -20
```

### Still getting "/tmp" space errors
**Cause:** Some component not respecting workspace_root

**Solution:** Check if any hardcoded `/tmp` paths remain:
```bash
grep -r "/tmp" ~/nvflare_testing/NVFlare/examples/advanced/multi-gpu/lightning/
```

### PyTorch Lightning not found
**Cause:** Not installed in venv

**Solution:** Test script auto-installs it, but manual install:
```bash
source ~/nvflare_testing/nvflare_env/bin/activate
pip install --no-cache-dir pytorch-lightning
```

## Key Test Questions

This test should answer:

1. ✅ **Does Lightning DDP work with NVFlare external processes?**
   - PyTorch DDP worked
   - TensorFlow Multi-GPU failed with DXO bug
   - Will Lightning have the same issue?

2. ✅ **Are trainer.test()/predict() killed prematurely?**
   - Known issue from earlier investigation
   - Does it affect training?

3. ✅ **Is the /tmp space fix effective?**
   - Using custom workspace_root
   - Should avoid space issues

4. ✅ **Does multi-GPU training actually use both GPUs?**
   - Monitor with `nvidia-smi`
   - Check GPU utilization during training

## Next Steps After Test

### If PASSED ✅
- Update testing summary document
- Mark Lightning DDP as validated
- Move to next example (tensor-stream or others)

### If FAILED with DXO Bug ❌
- Document as core framework bug
- Compare with TensorFlow Multi-GPU failure
- Defer to core team

### If FAILED with Other Errors ⚠️
- Investigate specific error
- May need framework or example fixes
- Document findings

## Related Files

- Example: `NVFlare/examples/advanced/multi-gpu/lightning/`
- Summary: `cursor_outputs/testing/20260126_EXAMPLE_TESTING_SESSION_SUMMARY.md`
- Status: `cursor_outputs/testing/TESTING_STATUS_OVERVIEW.md`
