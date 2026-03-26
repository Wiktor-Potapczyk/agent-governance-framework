---
name: pm
description: "Run a PM checkpoint on the current project. Use when the user says /pm, asks for a project status check, wants to run a checkpoint, says 'where are we on [project]', or between increments when a task_plan item completes."
---

Run a project management checkpoint by dispatching the PM orchestrator agent.

## When to Use

- Between increments (after completing a task or milestone)
- At session start (to orient on project state)
- When the user asks "where are we?" or "what's next?"
- Before starting a new phase of work
- When something feels stuck or unclear

## Steps

### 1. Identify the active project

Glob for `Projects/*/STATE.md`. Determine which project this checkpoint is for from conversation context.

- If multiple projects found and context is ambiguous, ask the user.
- If no `STATE.md` files found, inform the user no projects exist and ask if they want to start one.

Replace `[Name]` in the dispatch prompt below with the resolved project name.

### 2. Dispatch PM orchestrator

Use the Agent tool to dispatch `pm-orchestrator` with this prompt:

```
Run a PM checkpoint on project: [Name].

Project directory: Projects/[Name]/

Detect the current phase and run the appropriate phase protocol. Report:
- Current phase
- Active tasks and their status
- Blockers
- Recommended next action
- If at a phase transition: run viability check (Q6)
```

### 3. Report results

Relay the PM orchestrator's output verbatim. If the output contains a kill recommendation, scope change, or escalation, prefix it with a visible warning.

**After relaying the output, you MUST produce a PM CHECKPOINT REPORT block** (this is checked by hooks):

```
PM CHECKPOINT REPORT
Project: [name]
Phase: [0-4]
Viability: PASS | HOLD | KILL
Blockers: [count] — [list or "none"]
Next: [recommended next action]
```

Populate from the pm-orchestrator's output. If the orchestrator didn't produce a viability verdict, default to PASS (checkpoint ran, no kill signal).
