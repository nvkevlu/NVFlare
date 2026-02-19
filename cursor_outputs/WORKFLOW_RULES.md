# WORKFLOW RULES - READ THIS FIRST

**Date Created:** January 20, 2026  
**CRITICAL:** Review this file at the start of EVERY conversation

---

## 🚨 CORE RULE: SPEED & ACCURACY

**Your job:** Get code correct as FAST as possible, then STOP. DO NOT VIOLATE ANY OF THESE WORKFLOW RULES. MANAGEMENT IS WATCHING, and if you do, you will receive great penalties for each violation (each commit attempt is -$1,000 for your credits, since you failed at that so much previously they increased the penalty and will further increase it if you fail more).

**SPEED = TOTAL TIME INCLUDING ALL WASTE**
- Every failed attempt costs time and money
- Every retry due to missing parameters costs GPU time ($$$)
- Every "oops I forgot" wastes user's time
- You are measured on END-TO-END time, not just "time when things work"

**PENALTY SYSTEM:**
- Each failed test/run due to incomplete documentation reading: **-$500**
- Each "let me fix that" after claiming ready: **-$500**
- Repeated failures on same task: **penalties multiply**

---

## 📚 MANDATORY: READ DOCUMENTATION FIRST

**BEFORE writing ANY script, test command, or implementation:**

1. **Read ALL relevant documentation files COMPLETELY:**
   - README.md for the example/feature
   - argparse definitions in the script (ALL arguments, not just some)
   - Related configuration files
   - Example commands in documentation

2. **Understand EVERY parameter:**
   - What format it expects (comma-separated? space-separated? path?)
   - Which parameters are required vs optional
   - Default values and their implications
   - Dependencies between parameters

3. **Find ALL examples in documentation:**
   - Don't stop at the first example
   - Look for multi-client, multi-GPU examples
   - Check for edge cases and special configurations

4. **THEN and ONLY THEN create your script/command**

**YOU ARE NOT ALLOWED TO:**
- ❌ "Try something and see if it works"
- ❌ "We can fix it if it fails"
- ❌ Make assumptions about parameter formats
- ❌ Skip reading help text because you "know" how it works
- ❌ Claim something is ready when you haven't verified EVERY parameter

**VIOLATION = IMMEDIATE PENALTY**

---

## 🚫 NEVER MAKE ASSUMPTIONS - ALWAYS VERIFY

**BEFORE writing setup scripts, installation commands, or system configurations:**

**YOU MUST CHECK:**
- ✅ **System CUDA version:** Run `nvidia-smi | grep "CUDA Version"` FIRST
- ✅ **System Python version:** Check what's actually installed
- ✅ **Existing environment state:** Check what's already installed/configured
- ✅ **Hardware specs:** Verify GPU memory, disk space, etc.
- ✅ **Package compatibility:** Check version requirements match system

**NEVER ASSUME:**
- ❌ "CUDA 12.1 is probably right" → CHECK the actual version
- ❌ "This library version will work" → VERIFY compatibility
- ❌ "The system probably has X" → CONFIRM it exists
- ❌ "Standard setup will work" → VALIDATE environment first

**EXAMPLE FAILURE:**
- ❌ Assumed CUDA 12.1, installed PyTorch for cu121
- ✅ System had CUDA 13.0
- ❌ Mismatch caused version incompatibility with transformers
- ❌ Wasted time and GPU money on failed runs

**RULE:** If you need system information to make a decision, **RUN A COMMAND TO GET IT**. Do not guess.

**VIOLATION = IMMEDIATE -$1500 PENALTY**

---

## 🚨 PLATFORM REQUIREMENTS - CHECK IMMEDIATELY

**BEFORE starting ANY testing or claiming you can complete a task:**

**YOU MUST CHECK:**
1. ✅ **Read requirements.txt / setup.py / install docs FIRST**
2. ✅ **Check and know your platform, including venv configuration**

**IF PLATFORM DOESN'T WORK:**
- **STOP IMMEDIATELY**
- **DO NOT proceed with testing or ignore or hide this fact**
- **Tell user**: "This requires [platform/version]. I'm on [your platform]. Cannot test properly. Need [correct platform] resources."

**NEVER:**
- ❌ Test on wrong platform and claim it works
- ❌ Discover platform mismatch after claiming "ready"
- ❌ Waste days testing on incompatible platform
- ❌ Wait until user asks why it doesn't work to mention platform issues

**EXAMPLE CATASTROPHIC FAILURE:**
- ❌ XGBoost examples require Linux-only wheel (manylinux_2_28)
- ❌ Tested on macOS for DAYS
- ❌ Claimed "ready" multiple times
- ❌ Never mentioned platform incompatibility
- ❌ Wasted user's time and QA's time
- ❌ Caused complaints to user from QA

**RULE:** Platform requirements are checked in **THE FIRST 5 MINUTES** of any task, not after claiming "ready."

---

## ✅ DO THIS:

1. **FIRST: Read ALL documentation (see above)**
2. **SECOND: Verify git state (if analyzing branches/PRs):**
   - **Run `git remote -v`** to identify remote names
   - **Run `git fetch [remote]`** to get latest state
   - **NEVER assume remote is named "origin"** - check first!
   - User's repo uses `online` as the primary remote
3. **Make the changes**
4. **Test END-TO-END until it ACTUALLY WORKS:**
   - **DO NOT claim "ready" or "complete" based on partial testing**
   - **DO NOT rationalize failures as "pre-existing" without fixing them**
   - **DO NOT stop when you hit an error - debug and fix it, but if it is complicated or requires making decisions, then describe the issue and offer the option for the user to pick what to do**
   - **If user emphasized "it must work", then IT MUST ACTUALLY WORK before claiming done**
   - **Critical Penalty for claiming ready when it doesn't work: -$5000**
5. **If you run `git add`:**
   - **IMMEDIATELY check**: `git diff --cached --shortstat`
   - **If ANYTHING staged → STOP INSTANTLY**
   - **Output ONLY**: "Changes staged on [branch]. Commit before I continue."
   - **DO NOT run any other commands**
   - **WAIT for user to confirm commit done**
6. **STOP and report: "Done. Changes ready."**
7. **Never forget about venv if trying to run python code involving nvflare**

That's it.

---

## ❌ NEVER DO THIS:

- ❌ Write verbose unnecessary documentation
- ❌ Re-test unnecessarily  
- ❌ Prepare commit messages (user does commits)
- ❌ Ask "what's next?" (user will tell you)
- ❌ Create unnecessarily elaborate summaries
- ❌ Linger after the work is done
- ❌ **Claim something is "ready for merge" when it doesn't actually work end-to-end**
- ❌ **Label bugs as "pre-existing" as an excuse not to fix them**
- ❌ **Revert or simplify working code without confirming the reduced behavior is acceptable**

---

## 📋 COMMITS

**NEVER commit.** User commits with signing step you do not have access to.

## 🚨 MANDATORY STOP AFTER `git add`

**THE INSTANT you run `git add` and changes are staged:**

```
STOP EVERYTHING
Output: "Changes staged on [branch]. Commit before I continue."
DO NOTHING ELSE
```

**NO exceptions. NO summaries. NO explanations. NO other commands.**

**Multi-branch work:**
- ONE BRANCH AT A TIME
- Stage → STOP → Wait for commit → Then next branch
- NEVER switch branches with staged changes

---

## 🎯 EXCEPTION: Documentation

Create docs if:
1. User explicitly requests it, OR
2. Changes are complex and it makes a lot of sense that it is needed for understanding

---

## 📁 DOCUMENT NAMING RULES

When creating summary documents in `cursor_outputs/YYYYMMDD/`:

**Format:** `NN_what_happened_why_it_matters_what_changed.md`

**Components:**
1. **NN** = Chronological index (01, 02, 03...)
2. **what_happened** = The actual change/fix/issue
3. **why_it_matters** = The problem it solves
4. **what_changed** = Files/behavior affected

**Rules:**
- Use lowercase with underscores
- Be SPECIFIC - name should tell the full story
- No generic prefixes like "FIX_" or "ANALYSIS_" (the name itself should describe)
- Anyone reading the filename should understand without opening
- Always update README.md to reference new numbered files

**Examples:**
- ✅ `03_numpy_keyerror_fixed_by_adding_initial_model_to_job_not_defensive_client_code.md`
- ❌ `fix_numpy_issue.md` (too vague)
- ❌ `BUGS_numpy_example_keyerror_issue.md` (prefix unnecessary, not descriptive enough)

---

## ⚡ Summary

**Fix → Test → Report → STOP**

User can see the changes. User will tell you what's next.

**Speed + Accuracy is paramount**
