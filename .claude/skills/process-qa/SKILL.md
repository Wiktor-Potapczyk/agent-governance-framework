---
name: process-qa
description: Per-task QA. Claims are classed (run, execute, read, mcp), the scope node adds the claims a builder leaves out, every PASS names the command that produced it, the report states its verifier, and the compact relay is checked against the qa-log entry it names. Invoke when task-classifier marks QA compound yes.
---

# QA: does the thing work, and who says so

QA tests whether claims are TRUE by running the deliverable and looking at what came back. It is not review (that judges quality against a rubric) and not reasoning ("this should work because"). A PASS means "I tried to break it this way and could not."

Rebuilt 2026-09-21 after the adversarial review of this contract ([[2026-09-21-review-process-qa-contract-adversarial]], 21 findings) and the merged evaluation ([[2026-09-21-process-qa-effectiveness-analysis]]). What changed and why is in the build record [[2026-09-21-process-qa-contract-build]].

## Workflow-enforced (adopted 2026-06-11, rebuilt 2026-09-21)

For a non-Quick task, execute this skill by calling the **Workflow tool** with `{scriptPath: "C:\\Users\\WiktorPotapczyk\\Desktop\\Vault\\.claude\\workflows\\process-qa.js"}` and `args: {project, claims: [...], deliverable, stamp, source?, constraints?}`.

- `stamp`: the local time as `"YYYY-MM-DD HH:MM local"` (run `date "+%Y-%m-%d %H:%M"`). The workflow runtime throws on `Date`, so the script cannot read the clock itself; without `stamp` the qa-log header reads `STAMP-MISSING` and the relay check will not find a today-dated entry (added 2026-09-22 after run wf_5061a884-405 crashed at `new Date()`).

- `claims`: the caller's enumerated claims (strings, or `{claim, artifact?, claim_class?}`). The caller is usually the session that built the thing, so this list is a builder's list: it names what was done.
- `deliverable`: what was built, its entry points and its callers, in one paragraph. The scope node reads it to add the claims a builder leaves out. Omit it and the report says so in its Untested line.

What the script does, in code, with no self-report trusted:

1. **Scope node** assigns a class to every claim, **adds** claims for the paths the caller did not list (the no-input default, the empty input, each error branch, the second caller, the scheduled entry), one claim that the artifact built is the one the task asked for, and one per consumer the change can affect (up to 6, tagged `added by scope`). It also names the **untested surface** as paths, not categories. A longer list is kept; until 2026-09-21 it was thrown away.
2. **One execute agent per claim**, in parallel, told to refute the claim. Each returns `tool_used`, the literal `command`, `result` and `evidence`.
3. **Scoring in code**: a `run` claim fails unless the command invoked the artifact; a `run` or `execute` claim fails on a read-only command (`cat`, `sed -n`, `head`, `grep`, `ls`, `git show`, `git diff`, `Get-Content`) whatever tool ran it; an `mcp` claim fails without an MCP tool; empty evidence fails. `PASS n / N` is derived from the scored results.
4. **Untested line** = the scope node's named surface plus any UNTESTED claim. `none deliberately` is written only when the scope node returned an empty surface with a reason. Status is `complete`, `complete-with-gaps` (anything untested) or `quality-failed` (any FAIL).
5. Returns `qa_scope_text`, `qa_report_text` (ending `Verifier: workflow`), `qa_log_entry` and `compact_relay`.

**Transcript relay (mandatory).** Append `qa_log_entry` verbatim to the project's `work/qa-log.md`, then put `compact_relay` in the reply as plain unfenced text. `process-step-check.py` opens the qa-log the relay names and blocks the turn when the file is missing, none of its last six entries is dated today, or no entry dated today carries the relay's `PASS: n / N` and claim count. A markdown-table verdict is read only when the entry has no `PASS:` line. The line `no verifiable claims` satisfies both the scope and the relay checks. Since 2026-09-21 that check runs from the reply itself, so it fires even when the skill invocation sits outside the hook's 200 KB transcript window.

## The four claim classes

| Class | Satisfied only by | Never by |
|---|---|---|
| `run` | invoking the artifact itself with real inputs (the script ran, the hook fired through its entry point, the workflow executed, the request was served) | a unit test, a validator, a grep, a read |
| `execute` | a command that runs (a test suite, a validator, a probe) | a read-only command |
| `read` | Read, Grep or Glob (file exists, contains X, config registered) | |
| `mcp` | a live-system query through an MCP tool | a Bash approximation |

Behaviour of code, hooks, workflows and APIs is `run` or `execute`, never `read`. When in doubt between `run` and `execute`, it is `run`. Every deliverable that can be invoked gets at least one `run` claim; a QA with none is what the ruling of 2026-09-18 ([[feedback_test_every_live_path_before_calling_a_build_done]]) exists to stop: three live dispatch tests, 263 unit tests and two reviews, and the improver still failed on its first two cron mornings on the path nobody ran.

## Coverage

Coverage is paths, not files. The claim list, caller plus scope, must touch every live path the deliverable can take: each input shape, the no-input default, the failure branches, each caller, the unattended entry. Testing every file and none of the branches is incomplete. The Untested line names the paths that remain, as paths ("the 502 branch of the poster", "the cron entry under the real scheduler"), never as categories ("edge cases").

## Verifier

Every report states who tested: `Verifier: workflow` (the script's agents, none of which built the thing) or `Verifier: main-session` (the session that built it checked its own claims). The record's one controlled comparison (Module-8B, 2026-09-18) went 6/6 on the self-check and 5/6 on an independent rerun of the same six claims; a self-check is legitimate, and it must say what it is. `work-verification-check.py` warns on stderr when any non-Quick turn files a main-session QA, and adds a second warning when every Bash call of that turn only read files (the classifier is `_command_class.py`, a port of the script's `isReadOnlyCommand`, held to the same table by `test_command_class.py`).

## Compact relay (owner ruling 2026-09-11)

Wiktor, verbatim: "yeah i mean the QA and PM notes, I dont want to see them". The full blocks go to `work/qa-log.md` (append-only, newest entry last) and the reply carries three lines, plain and unfenced:

    QA SCOPE: <N> claims, detail in <project>/work/qa-log.md
    QA REPORT:
    PASS: <n> / <N> | FAIL: <one line or none> | Untested: <paths, or none deliberately (reason)> | Verifier: workflow|main-session

The literal `QA REPORT:` and the line-initial `PASS: n / N` are read by four hooks. `task-plan-auto-sync.py` ticks a task only when `n` equals `N` and FAIL is `none`; otherwise it notes the failure on the entry and leaves it open, and it routes every Untested item into the project's `task_plan.md` under `## QA untested surface` so a disclosed gap becomes work.

## Fallback path: a self-check that says so

Use the prose path below only when the Workflow tool is unavailable (sub-agent context, degraded session, no opt-in), and say so in the qa-log entry's header and with `Verifier: main-session` on the PASS line. The same rules apply: classes assigned per claim, at least one `run` claim per invocable deliverable, a command named for every PASS, Untested as paths.

### 1. Scope

    QA SCOPE
    - [run] the script writes its output on real input
    - [execute] the suite passes
    - [read] the config names the hook
    Source: [what produced these claims]
    Deliverable: [what was built, entry points, callers]

Then, before executing, ask the scope node's question yourself: which live paths do these claims not touch, and is this the artifact the task asked for? Add the missing claims, marked `added by scope`.

If no verifiable claims exist, write the literal line `no verifiable claims` alone on its own line and exit; the hook accepts it only as a whole line.

### 2. Execute

Run real tools and record the literal command per claim. A `run` claim's command invokes the artifact. A read of a script is not a test of it; a green unit suite is not a run of the product (two logged cases of a validator and a 28/28 suite passing a runtime-fatal defect are why).

### 3. Report

For each PASS, name the command that produced the evidence and check it ran the thing the claim is about. Then write the entry to `work/qa-log.md` (header `## YYYY-MM-DD HH:MM local, <what>`, the QA SCOPE block, an Evidence line per claim with its command, the QA REPORT block with `Verifier:`) and relay the three lines.

    QA REPORT
    PASS: n / N
    FAIL: [one line per failed claim, expected vs actual, or "none"]
    Untested: [paths not exercised, or "none deliberately (reason)"]
    Verifier: main-session

## Use-when

- A non-Quick task is complete and produced verifiable claims
- Task-classifier marked QA compound yes (`classifier-field-check.py` blocks a non-Quick classification that names neither process-qa nor process-pentest)
- Specific claims need empirical proof (a script runs, a hook fires, an output matches)

## Do-NOT-use-when

- Adversarial testing of an assembled increment: `process-pentest` (Tier 2)
- Quality review against a rubric: `architect-reviewer`
- Fixing a failure: QA reports, the originating process skill fixes
- Quick tasks

## Gotchas

- **Fenced blocks are invisible to the Stop hook**: the relay lines go in plain text.
- **The tool name proves nothing**: `Bash (cat the file)` was a passing execution until 2026-09-21. The command is what is scored.
- **A builder's claim list is a list of what was done**: verification needs what could be wrong. The `deliverable` arg and the scope node's additions are how the second list gets written.
- **"Untested: none deliberately" needs a reason**: the phrase means "I considered every path and can defend the omission", not "no claim came back UNTESTED".
- **The relay is checked against the log**: write the qa-log entry before the reply, with today's date in its header and the same `PASS: n / N`.
- **Health is measured weekly**: `lint_pass_qa_health.py` (process-lint Pass W) reports the share of QA reports filed without the skill, null Untested lines, run-class coverage, entries that ever fail, and task-plan ticks on a partial PASS.
