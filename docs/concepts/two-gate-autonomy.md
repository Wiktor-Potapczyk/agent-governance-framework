# Two-Gate Autonomy

The framework's answer to "when may the agent act without asking?"

The intuitive answer is task size, and it is wrong. This page explains the model that replaced it, why each gate exists, and how to apply the tests yourself.

## The problem with size

Size-gating fails in both directions, and the two failures are not equally costly.

A one-line change can be `git push`, `DROP TABLE users`, or an email to a customer. Every size metric calls these trivial. No recovery metric does. A size-gated system waves them through *because* they look small.

Meanwhile a forty-file local refactor is fully recoverable with one `git checkout`. Gating it on size buys no safety and costs the agent its ability to finish work while nobody is watching.

Permissive failure is unrecoverable. Restrictive failure wastes time. A correct rule has to be strict about the first and generous about the second, and size is not that rule.

## Gate 1: reversibility is a hard floor

**Rule:** every action on the canonical irreversible surface is denied, in every context, regardless of how the task was classified.

The surface is enumerated rather than inferred:

- file or record deletion, including unflagged relative `rm`
- database `DROP`, `TRUNCATE`, or unbounded `DELETE`
- normal `git push`
- external `POST`, `PUT`, `PATCH`, `DELETE`
- production deploys
- outbound email or chat sends

### Why `deny` and not `ask`

The framework runs under universal `bypassPermissions`. In that mode a PreToolUse hook returning `permissionDecision: "ask"` is a **no-op**: there is no prompt, nothing pauses, and the action proceeds. An `ask` that never reaches a human is indistinguishable from an allow.

So `deny` is the only decision that stops anything. The human gate becomes:

1. The hook denies the call.
2. The agent surfaces a decision brief: what it wanted to do, why, options with tradeoffs, and a recommendation.
3. The owner re-runs the command themselves with the `!` prefix, which skips PreToolUse hooks entirely.

This is not a workaround. It is the design. The bypass is deliberately manual and deliberately human-typed, which makes it a real decision point rather than a reflexive click-through.

### Why enumeration rather than pattern-matching

A heuristic that guesses at irreversibility fails open on exactly the cases nobody anticipated, which are the cases that matter. Enumeration has a real cost: a new destructive action is unguarded until someone adds it. The framework accepts that cost, because an unguarded known-unknown is better than a guard that silently believes it has full coverage.

The surface lives in exactly one module, `hooks/_irreversible_surface.py`. Both enforcement arms import it: `hooks/bash-safety-guard.py` for shell, `hooks/mcp-irreversible-guard.py` for MCP tool calls. Two independently maintained copies drift, and a drifted deny-list is a silent hole in the floor.

## Gate 2: detectability expands autonomy above the floor

Gate 2 only ever sees actions that are already reversible. It answers a different question: not "may this be undone?" but "would I find out if it were wrong?"

**The test, applied as one question:**

> Can I write a tool call *right now* that would **fail** if this action were wrong, without dispatching another agent and without a human looking?

**Yes → self-detectable.** Proceed autonomously. The agent can falsify its own work before the result propagates anywhere.

**No → needs-detector.** Either arrange an independent detector that **re-derives** the result, or pause.

### Re-reading is not verification

This is the distinction the gate exists to enforce. An agent that writes a file and reads it back has confirmed the write happened. It has not confirmed the write was correct. The read echoes the write; it cannot disagree with it.

Re-derivation computes the expected value by an independent path and compares. A test suite re-derives. A validator re-derives. A second agent given the same prompt does not, it merely produces a correlated opinion.

### Worked examples

| Action | Verdict | Why |
|---|---|---|
| Edit `helper.js`, re-run the test suite | self-detectable | The suite fails on a wrong edit |
| Patch a workflow node, then run the validator | self-detectable | Validation re-derives the node contract |
| Write a citation SHA that a PostToolUse hook re-hashes | self-detectable | The hook recomputes the hash independently |
| `git push` to a remote | *never reaches Gate 2* | Gate 1 denies it first |
| Generate marketing copy or a system prompt | needs-detector | Semantic correctness; no self-issued call falsifies it |
| Research synthesis asserting live-web facts with no fetch-back | needs-detector | Only an independent quality gate catches fabrication |

Two independent runs of this test on the same action must produce the same verdict. If they do not, the action description is too vague to gate.

## Size is not a gate, and that is load-bearing

The classifier emits `REVERSIBILITY` and `DETECTABILITY` as advisory fields, captured in the governance log for observability. They never block.

The floor lives in the PreToolUse hook specifically so that no classifier decision can route around it. A task classified Quick, taking the explicit-imperative fast path, with no ceremony at all, still trips the Gate-1 deny the moment it touches the surface. If the floor lived in the classifier, the fast path would be a hole in it.

## Enforcement map

| Gate | Enforced by | Mechanism |
|---|---|---|
| Gate 1 (shell) | `hooks/bash-safety-guard.py` | Pattern match against the canonical surface → `deny` |
| Gate 1 (MCP) | `hooks/mcp-irreversible-guard.py` | Enumerated destructive tools → `deny` |
| Gate 1 (source of truth) | `hooks/_irreversible_surface.py` | Single canonical pattern list, imported by both arms |
| Gate 2 | `hooks/verifier-gate-check.py` | Three-part structural contract: distinct post-worker dispatch, non-identical prompt, re-derivation keyword or artifact path |

## Known weakness, stated plainly

`bash-safety-guard.py` carries `_IRREVERSIBLE_FALLBACK_SNAPSHOT`, a frozen transcription of the canonical patterns, so the guard still functions when the shared module cannot be imported. This is a second copy of a list that this page says must exist once.

It is retained deliberately: a guard that fails to import and therefore fails open is worse than a guard that occasionally lags. The mitigation is procedural, not architectural. Update the snapshot whenever the canonical module changes.

One specific hazard is worth naming, because it has already happened: **narrowing a deny pattern can silently open a floor hole.** After any edit that makes a pattern less broad, verify that the new deny-set equals the old deny-set minus exactly the intended un-blocks. A parent-directory recursive-delete case once slipped through a pattern that had been narrowed to match only the current directory.

## Related

- ADR-0007 records the decision and the alternatives that were rejected.
- ADR-0002 establishes the broader principle: hooks enforce process, prompts do not.
- `docs/reference/hooks.md` gives the per-hook enforcement contracts.
