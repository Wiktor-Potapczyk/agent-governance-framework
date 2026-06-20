---
name: verification-gated-research
description: Run a depth/research/multi-source investigation as a verification-gated backlog: decompose into a ledger file, dispatch fresh-context worker agents, gate completion with a SEPARATE verifier agent. Use when a research or depth task must be exhaustively investigated and a self-graded loop would satisfice. NOT for Quick lookups or single-source tasks.
---

# Verification-Gated Research

A research/depth investigation harness whose completion is decided by a **separate verifier agent against an external ledger**: not by the agent's own say-so. It exists because self-graded loops satisfice: they declare completion on shallow work. The core finding the harness encodes: long-horizon investigation works when state lives in external files and completion is an agent-uncircumventable gate.

## Use-when

- A research or depth-analysis task with multiple distinct sub-questions or sources, where breadth-first one-pass coverage would miss depth
- A task where a self-graded loop would declare "done" on shallow material
- Re-running a prior investigation that satisficed: the depth pass

## Do-NOT-use-when

- Quick single-fact lookups: no decomposition needed
- A 1-2 question task with one known source: direct delegation via `process-research` is enough
- Building or implementing: this harness investigates, it does not build

## The non-negotiable rule

**The verifier is a SEPARATE agent.** The orchestrator (the session running this skill) must NOT verify its own workers' output. A worker must NOT verify its own or a sibling's output. Verification is a distinct `Agent` dispatch. Generator ≠ verifier: that separation is the entire point; collapsing it recreates the self-grading failure this skill exists to prevent.

This is enforced: `hooks/verifier-gate-check.py` (a Stop hook) blocks completion when this skill was invoked but no separate-verifier `Agent` dispatch is found in the transcript. The verifier dispatch's `description` MUST contain the word "verifier" so the hook can identify it.

## Step 1: Build the backlog ledger (a file, before any dispatch)

Write an explicit ledger FILE to disk before dispatching any worker: `Projects/[Name]/work/YYYY-MM-DD-[topic]-backlog.md`.

- One row per atomic investigation unit. Columns: ID · item · worker-cluster · status.
- Status legend: `OPEN` · `IN-WORK` · `RETURNED` · `VERIFIED` · `FAIL` · `UNREACHABLE-VALID`.
- Include a stated **depth bar** the verifier will judge against (mechanism-level not mention-level; primary-sourced; no memory-substitution; gaps marked UNREACHABLE with a recorded attempt).

The ledger is the external state. It is the source of truth for completion: not the conversation. **The orchestrator owns every ledger update**: it writes the status transitions (`OPEN`→`IN-WORK` when a worker is dispatched, →`RETURNED` when the worker reports, →`VERIFIED`/`FAIL`/`UNREACHABLE-VALID` from the verifier's verdict, `FAIL`→`OPEN` on re-work). Workers and the verifier report; they do not edit the ledger.

## Step 2: Dispatch fresh-context workers

For each cluster of backlog units, dispatch a worker `Agent`. Rules:

- One worker per cluster of related units: fresh context each. The orchestrator does NOT investigate inline; heavy reading/fetching happens in worker context that is then discarded. This bounds context rot.
- Each worker prompt is self-contained (no conversation history), states observable facts only, and instructs: verify against primary sources, mark anything unverifiable UNVERIFIED with the reason.
- Run independent workers in parallel (multiple `Agent` calls in one message).
- Mark units `IN-WORK`, then `RETURNED` when the worker reports.

## Step 3: Dispatch the separate verifier (the gate)

After workers return, dispatch ONE verifier `Agent`: `description` containing "verifier".

- It is NOT any worker and NOT the orchestrator.
- Give it: the depth bar, the list of items + their load-bearing claims + cited sources, and the worker outputs.
- Instruct it to independently re-check the highest-risk / most load-bearing claims against primary sources (re-fetch), and judge each unit `PASS` / `FAIL` / `UNREACHABLE-VALID`.
- `UNREACHABLE-VALID` is a passing terminal state: a genuine, documented dead end.

## Step 4: Loop FAIL units back

Units the verifier marks `FAIL` return to `OPEN` in the ledger. Re-dispatch workers for them (Step 2), re-verify (Step 3). Repeat. Update the ledger each pass: the wave log records what each pass closed.

## Step 5: Completion is the ledger, not an assertion

The investigation is complete only when every ledger row is `VERIFIED` or `UNREACHABLE-VALID`: zero `OPEN` / `IN-WORK` / `RETURNED` / `FAIL`. Completion is read off the file. The orchestrator does not get to declare "done"; the ledger state does.

Then consolidate the verified worker output into the findings deliverable.

## Quality check

- [ ] Ledger file existed on disk before the first worker dispatch
- [ ] Every worker was a fresh `Agent` dispatch; the orchestrator did not investigate inline
- [ ] The verifier was a distinct `Agent` dispatch (description contains "verifier"), not a worker and not the orchestrator
- [ ] Every ledger row is in a terminal state
- [ ] FAIL units were re-worked and re-verified, not waved through

## Notes

- Reference implementation: a 23-unit ledger with 5 workers, 1 separate verifier, yielding 22 VERIFIED / 1 UNREACHABLE-VALID / 0 FAIL is a realistic scale for a genuine depth investigation.
- This skill is the structured form of the Ralph Loop doctrine: the loop body orchestrates the ledger only: it never investigates inline. A Ralph loop can drive this harness, but heavy reading/fetching happens in worker sub-agent context.
- The harness has a cost: decomposition + per-cluster workers + a verifier pass. For a small task this overhead is not worth it: use `process-research` direct delegation instead. Reserve this for genuine depth work.
