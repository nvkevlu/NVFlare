# PR: Remove TensorFlow Multi-GPU Example

**Branch:** 2.7  
**Date:** February 2, 2026  
**Status:** Ready for commit (awaiting user approval)

---

## Changes Summary

### Files Deleted (7 files, 331 lines removed):
- `examples/advanced/multi-gpu/tf/README.md` (131 lines)
- `examples/advanced/multi-gpu/tf/client.py` (83 lines)
- `examples/advanced/multi-gpu/tf/job.py` (68 lines)
- `examples/advanced/multi-gpu/tf/model.py` (34 lines)
- `examples/advanced/multi-gpu/tf/prepare_data.sh` (3 lines)
- `examples/advanced/multi-gpu/tf/requirements.txt` (2 lines)
- Total: **332 lines removed**

### Files Modified (2 files):
- `examples/advanced/multi-gpu/README.md` (11 lines changed)
  - Removed TensorFlow from examples table
  - Removed TensorFlow description section
  - Removed TensorFlow from quick start instructions
  - Removed TensorFlow-specific troubleshooting
  - Removed TensorFlow documentation links

- `web/src/components/tutorials.astro` (4 lines changed)
  - Removed `"tensorflow"` tag from Multi-GPU Training tutorial entry
  - Updated description from "PyTorch, Lightning, and TensorFlow" to "PyTorch and Lightning"

### Git Status:
```bash
Changes to be committed:
  modified:   examples/advanced/multi-gpu/README.md
  modified:   web/src/components/tutorials.astro
  deleted:    examples/advanced/multi-gpu/tf/README.md
  deleted:    examples/advanced/multi-gpu/tf/client.py
  deleted:    examples/advanced/multi-gpu/tf/job.py
  deleted:    examples/advanced/multi-gpu/tf/model.py
  deleted:    examples/advanced/multi-gpu/tf/prepare_data.sh
  deleted:    examples/advanced/multi-gpu/tf/requirements.txt
```

---

## Reason for Removal

**Technical Issue:** TensorFlow's MirroredStrategy deadlocks when running in NVFlare's external subprocess mode due to architectural incompatibility between:
- TensorFlow's single-process multi-threaded GPU coordination
- NVFlare's FilePipe-based inter-process communication

**Testing Results:**
- Tested twice on remote GPU hardware (2x NVIDIA A30)
- Both attempts resulted in 5-minute deadlock during `model.evaluate()`
- Process killed after heartbeat timeout
- Requires core framework changes to support (estimated 2-3 days development)

**Decision:** Remove example temporarily until framework changes can be implemented to properly support single-process multi-GPU frameworks.

**See Also:** 
- `cursor_outputs/testing/TENSORFLOW_TECHNICAL_ANALYSIS.md` - Detailed technical analysis
- `cursor_outputs/testing/TENSORFLOW_MULTIGPU_INVESTIGATION.md` - Testing history

---

## Proposed Commit Message

```
[2.7] Remove TensorFlow multi-GPU example

Remove examples/advanced/multi-gpu/tf/ due to architectural incompatibility
between TensorFlow MirroredStrategy and NVFlare's external process mode.

The example deadlocks during model.evaluate() due to conflicts between:
- TensorFlow's single-process multi-threaded GPU coordination
- NVFlare's FilePipe-based IPC requiring heartbeat communication

Testing confirmed the issue occurs consistently on multi-GPU hardware.
PyTorch DDP and Lightning examples work correctly as they use
multi-process architecture where only rank 0 handles NVFlare communication.

The example can be re-added after implementing framework support for
single-process multi-GPU frameworks (in-process execution mode or
async pipe communication).

Changes:
- Remove examples/advanced/multi-gpu/tf/ directory (6 files)
- Update examples/advanced/multi-gpu/README.md to remove TensorFlow references
- Update web/src/components/tutorials.astro to remove TensorFlow tag
```

---

## Commit Instructions (When Ready)

**DO NOT commit yet - awaiting user approval**

When ready to commit:

```bash
cd /Users/kevlu/workspace/repos/secondcopynvflare

# Verify staged changes
git status
git diff --cached

# Commit with message
git commit -m "$(cat <<'EOF'
[2.7] Remove TensorFlow multi-GPU example

Remove examples/advanced/multi-gpu/tf/ due to architectural incompatibility
between TensorFlow MirroredStrategy and NVFlare's external process mode.

The example deadlocks during model.evaluate() due to conflicts between:
- TensorFlow's single-process multi-threaded GPU coordination
- NVFlare's FilePipe-based IPC requiring heartbeat communication

Testing confirmed the issue occurs consistently on multi-GPU hardware.
PyTorch DDP and Lightning examples work correctly as they use
multi-process architecture where only rank 0 handles NVFlare communication.

The example can be re-added after implementing framework support for
single-process multi-GPU frameworks (in-process execution mode or
async pipe communication).

Changes:
- Remove examples/advanced/multi-gpu/tf/ directory (6 files)
- Update examples/advanced/multi-gpu/README.md to remove TensorFlow references
- Update web/src/components/tutorials.astro to remove TensorFlow tag
EOF
)"

# Verify commit
git log -1 --stat
```

---

## For Main Branch (After 2.7)

After committing to 2.7, you'll need to apply the same changes to main branch:

### Option 1: Cherry-pick (Recommended)
```bash
# After committing on 2.7:
git checkout main
git cherry-pick <commit-hash-from-2.7>
```

### Option 2: Repeat Process
```bash
git checkout main
git rm -rf examples/advanced/multi-gpu/tf
# Edit README.md (same changes)
git add examples/advanced/multi-gpu/README.md
git commit -m "[main] Remove TensorFlow multi-GPU example"
```

---

## PR Creation

After committing on 2.7:

```bash
# Push to your fork
git push origin 2.7

# Create PR
gh pr create --title "[2.7] Remove TensorFlow multi-GPU example" --body "$(cat <<'EOF'
## Summary

Remove the TensorFlow multi-GPU example (`examples/advanced/multi-gpu/tf/`) due to architectural incompatibility with NVFlare's external process mode.

## Background

Testing on multi-GPU hardware (2x NVIDIA A30) revealed that TensorFlow's MirroredStrategy consistently deadlocks when running in NVFlare's external subprocess mode. The deadlock occurs during `model.evaluate()` calls due to conflicts between:

1. TensorFlow's single-process multi-threaded GPU coordination (MirroredStrategy)
2. NVFlare's FilePipe-based inter-process communication requiring periodic heartbeats

## Testing Results

- Tested twice with clean environments
- Both tests resulted in 5-minute deadlock followed by process termination
- PyTorch DDP and Lightning examples work correctly (multi-process architecture)
- Issue is architectural, not configuration-related

## Technical Details

The deadlock mechanism:
- TensorFlow blocks main thread during collective GPU operations
- NVFlare's heartbeat thread cannot send heartbeats (blocked by GIL/file I/O)
- After 5 minutes, heartbeat timeout triggers and process is killed

See detailed technical analysis in testing documentation.

## Changes

- ✅ Remove `examples/advanced/multi-gpu/tf/` directory (6 files, 332 lines)
- ✅ Update `examples/advanced/multi-gpu/README.md` to remove TensorFlow references

## Future Work

The example can be re-added after implementing one of these framework enhancements:
1. In-process execution mode for single-process multi-GPU frameworks
2. Async/non-blocking pipe communication system
3. TensorFlow-specific workarounds for blocking operations

## Test Plan

- [x] Verify README.md renders correctly
- [x] Verify no broken links remain
- [x] Verify PyTorch and Lightning examples still documented
- [ ] Update release notes if needed
- [ ] Apply same changes to main branch

EOF
)"
```

---

## Verification Checklist

Before committing:

- [x] All TensorFlow multi-GPU files deleted (6 files)
- [x] README.md updated to remove all TensorFlow references
- [x] tutorials.astro updated to remove TensorFlow tag
- [x] Changes staged in git
- [x] Commit message prepared following repo style
- [x] No broken links or references remain
- [ ] User approval to proceed with commit

---

## What Remains in Multi-GPU Directory

After removal:

```
examples/advanced/multi-gpu/
├── README.md          # Updated (TensorFlow references removed)
├── pt/                # PyTorch DDP example (kept)
│   ├── README.md
│   ├── client.py
│   ├── job.py
│   ├── model.py
│   ├── prepare_data.sh
│   └── requirements.txt
└── lightning/         # Lightning DDP example (kept)
    ├── README.md
    ├── client.py
    ├── job.py
    ├── model.py
    ├── prepare_data.sh
    └── requirements.txt
```

Both PyTorch-based examples remain intact and functional.

---

## Summary

✅ **Ready for Commit**  
📋 **Files staged:** 8 files (2 modified, 6 deleted)  
📏 **Net change:** -333 lines  
🎯 **Purpose:** Remove non-functional TensorFlow multi-GPU example  
⏳ **Status:** Awaiting user approval to commit

**Next step:** User reviews and approves, then commits with provided message.
