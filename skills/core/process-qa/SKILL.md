---
name: process-qa
description: QA process template. Follow this procedure for QA compound tasks — empirical verification of claims, outputs, and assumptions. QA asks "does this actually work?" not "is this good?" (that's Analysis). Invoke when task-classifier marks QA compound as yes.
---

# QA Process Template

You have been routed here because the task-classifier detected a QA compound. QA verifies claims empirically — it is the output-side complement of IMPLIES (which forces exploration at entry).

**QA is NOT review.** Review (architect-review, prompt-engineer) evaluates quality against criteria. QA tests whether claims are TRUE — did it actually work? Does the output match reality?

**QA is NOT reasoning about whether something would work.** It is EXECUTING a test and OBSERVING the result. If you catch yourself writing "this should work because..." without having run it — stop. Run it.

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

**Scope check:** If the build produced N artifacts (workflows, scripts, hooks), ALL N must appear in claims. If you list 2 of 5 workflows, your QA scope is incomplete. Go back and list them all.

If no verifiable claims exist, QA is not needed — report "no verifiable claims" and exit.

## Step 2 — Choose Verification Method

For each claim, select the appropriate method:

| Claim type | Method | Tool | Minimum bar |
|-----------|--------|------|-------------|
| Code/script works | Execute it | Bash | Must see execution output |
| Hook blocks correctly | Pipe test payload | Bash (echo JSON \| python hook.py) | Must see block/pass JSON |
| n8n workflow works | Execute via MCP | n8n_test_workflow + n8n_executions | Must read execution status + output |
| File exists / contains X | Read it | Read, Grep | Must show matching content |
| Config is registered | Read settings file | Read | Must show the registration |
| External fact is true | Check source | WebFetch, WebSearch | Must show source text |
| Output matches format | Parse and validate | Bash (python/jq) | Must show parsed output |
| Agent produces X | Dispatch test agent | Agent | Must show agent output |
| Database schema correct | Query it | MCP (Supabase/Postgres) | Must show query result |

**If a claim requires execution (code, hook, workflow, API) and you choose Read instead — that is not QA. Reading a script is not the same as running it.**

## Step 3 — Execute and Capture

For EACH claim, do these three things IN ORDER. Do not skip any.

### 3a — Run the test

Execute the test using the tool from Step 2. This is a tool call, not reasoning.

### 3b — Show the raw output

Immediately after the tool returns, quote the key output. Not a summary — the actual output text, error message, or execution result. Write it down before interpreting it.

Format:
```
CLAIM [N] — [one-line claim]
TOOL: [tool name + parameters]
RAW OUTPUT:
[paste the actual output — truncate if >20 lines but include the verdict-relevant parts]
```

### 3c — Judge PASS or FAIL

NOW interpret the raw output:
- Does the output confirm the claim? → PASS
- Does the output contradict the claim? → FAIL (record expected vs actual)
- Is the output ambiguous? → FAIL (if you can't prove it works, it doesn't count as working)
- Did the test error before producing results? → FAIL (the tool errored, not a pass)

**The rule:** if you cannot point to a specific line in the raw output that confirms the claim, it's not a PASS. "Looks correct" is never valid evidence.

## Step 4 — Coverage Check (MANDATORY before reporting)

Before writing the QA REPORT, verify completeness:

- [ ] Every claim from Step 1 has a 3a/3b/3c entry
- [ ] Every execution claim used an execution tool (Bash, MCP), not just Read
- [ ] Every raw output section has actual tool output, not reasoning
- [ ] If N artifacts were built, N artifacts were tested (not just the first one)

**If any box is unchecked:** go back and fill the gap. Do not proceed to Step 5.

## Step 5 — Report

Output the verification report:

```
QA REPORT
Date: [YYYY-MM-DD]
Source: [what was being verified]

| # | Claim | Method | Result | Evidence |
|---|-------|--------|--------|----------|
| 1 | [claim] | [tool used] | PASS/FAIL | [specific output that proves it — not "looks correct"] |
| 2 | [claim] | [tool used] | PASS/FAIL | [specific output] |

PASS: [count] / [total]
FAIL: [count] — [list failed claims]
MANUAL: [count] — [list claims requiring manual testing]

Untested Surface:
- [what was NOT tested and why — mandatory]
```

**Evidence column rules:**
- Must reference actual tool output (line from bash, field from MCP response, content from Read)
- "Looks correct", "should work", "matches expected" without specific output = INVALID
- If you can't fill the evidence column with real output, you didn't test it

## Step 6 — Escalate Failures

For each FAIL:
- Report what was expected vs what was found
- Do NOT fix it — QA verifies, it does not repair
- The fix goes back to the appropriate process skill (Build for code, Planning for specs)
- After attempting a fix: re-run the specific failed test (Step 3a-3c) to verify the fix

## Notes

- QA is empirical, not judgmental. "Does it work?" not "Is it good?"
- QA can be lightweight — 1 claim, 1 test, 1 result. Not every task needs a 10-item checklist.
- The QA compound fires from the classifier when the task produces claims that need verification. If no claims need testing, QA doesn't fire.
- QA is the LAST step before reporting back — it closes the recursive execution pattern.
- **The work-verification-check Stop hook will block you if you file a QA REPORT with zero execution tools.** This is not a suggestion — the hook reads the transcript and counts tool_use blocks.
