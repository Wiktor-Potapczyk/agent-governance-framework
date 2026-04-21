# CRITICAL Rules Added 2026-04-21

Three governance rules added to the framework in the 2026-04-21 workflow-discipline sprint. See [CHANGELOG.md](../CHANGELOG.md) for the full change summary.

## Rule 1: /rewind discipline (amendment to Iterative Working Mindset)

Prefer `/rewind` over in-context correction for wrong/suboptimal answers. When a prompt produces a bad answer, `/rewind` the exchange out of context rather than correcting inline — unless the mistake will be directly referenced in subsequent turns, a work/ artifact, or a delegated agent prompt.

## Rule 2: Task Plan Alignment

At session start, verify task queue alignment before acting.

- Read `Projects/[Name]/task_plan.md` if it exists; skip this rule for projects without one.
- Identify the top-of-queue `[ ]` item; verify it still matches STATE.md `## Next`.
- If mismatch, flag to user before acting.

See also: Task Plan Sync (below) for the write-back obligation.

## Rule 3: Task Plan Sync

Update task_plan.md as part of every non-Quick task completion.

- After a non-Quick task ships (QA PASS), update its `task_plan.md` entry: mark `[x]`, append a 1-3 line result summary (what shipped, where the artifact lives, QA outcome).
- Do this BEFORE invoking the end-of-task PM checkpoint (not the task-start classifier PM trigger) — task_plan.md must reflect current reality when PM reads it.
- If the task surfaced follow-up work (new tickets), append them to task_plan.md in the same edit.
- The update is part of definition-of-done; a task is not complete until task_plan.md is synced. On QA FAIL, add a note to the entry describing the failure rather than marking [x] — the entry stays open until QA PASSes.
