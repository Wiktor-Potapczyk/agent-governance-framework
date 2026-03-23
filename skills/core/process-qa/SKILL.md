---
name: process-qa
description: QA process template. Follow this procedure for QA compound tasks — empirical verification of claims, outputs, and assumptions. QA asks "does this actually work?" not "is this good?" (that's Analysis). Invoke when task-classifier marks QA compound as yes.
---

# QA Process Template

You have been routed here because the task-classifier detected a QA compound. QA verifies claims empirically — it is the output-side complement of IMPLIES (which forces exploration at entry).

**QA is NOT review.** Review (architect-review, prompt-engineer) evaluates quality against criteria. QA tests whether claims are TRUE — did it actually work? Does the output match reality?

## Step 1 — Identify Claims to Verify

Before any verification, list every verifiable claim from the work output:

```
QA SCOPE
Claims to verify:
1. [claim] — how to test it
2. [claim] — how to test it
3. [claim] — how to test it
Source: [which work output produced these claims]
```

Claims come from:
- Agent outputs ("this hook blocks when X happens" — does it?)
- Process outputs ("all 5 fields are present" — are they?)
- Build outputs ("this code handles edge case Y" — does it?)
- Research outputs ("framework X defines 5 phases" — does it say that?)

If no verifiable claims exist, QA is not needed — report "no verifiable claims" and exit.

## Step 2 — Choose Verification Method

For each claim, select the appropriate method:

| Claim type | Method | Tool |
|-----------|--------|------|
| Code works | Execute it | Bash |
| File exists / contains X | Read it | Read, Grep |
| Hook blocks correctly | Simulate payload | Bash (pipe test input) |
| Config is registered | Read settings file | Read |
| External fact is true | Check source | WebFetch, WebSearch |
| Output matches format | Parse and validate | Bash |
| Agent produces X | Dispatch test agent | Agent |
<!-- Domain-specific: customize for your stack -->
| Workflow works | Execute via automation platform tools | Platform MCP tools |

## Step 3 — Execute Verification

For each claim:
1. Run the test using the chosen method
2. Record: PASS (claim is true) or FAIL (claim is false or unverifiable)
3. For FAIL: capture the actual result vs expected result

**Rules:**
- You MUST actually execute the test — do not reason about whether it would pass
- One test per claim — do not batch
- If a test requires user action (manual testing, UI interaction), flag it as MANUAL and describe the test steps

## Step 4 — Report

Output the verification report:

```
QA REPORT
Date: [YYYY-MM-DD]
Source: [what was being verified]

| # | Claim | Method | Result | Evidence |
|---|-------|--------|--------|----------|
| 1 | [claim] | [method] | PASS/FAIL | [what you observed] |
| 2 | [claim] | [method] | PASS/FAIL | [what you observed] |

PASS: [count] / [total]
FAIL: [count] — [list failed claims]
MANUAL: [count] — [list claims requiring manual testing]
```

## Step 5 — Escalate Failures

For each FAIL:
- Report what was expected vs what was found
- Do NOT fix it — QA verifies, it does not repair
- The fix goes back to the appropriate process skill (Build for code, Planning for specs)

## Notes

- QA is empirical, not judgmental. "Does it work?" not "Is it good?"
- QA can be lightweight — 1 claim, 1 test, 1 result. Not every task needs a 10-item checklist.
- The QA compound fires from the classifier when the task produces claims that need verification. If no claims need testing, QA doesn't fire.
- QA is the LAST step before reporting back — it closes the recursive execution pattern.
