# ADR-0007: Autonomy Is Licensed by Two Gates in Series, Not by Task Size

**Status:** Accepted
**Date:** 2026-06-16

## Context and Problem Statement

The framework needed a rule for when the agent may act without asking. The obvious rule, and the one most agent systems reach for, is task size: small changes proceed, large changes ask. That rule is wrong in both directions, and both failures were observed in practice.

It is wrong permissively: a one-line change can be a `git push`, a `DROP TABLE`, or an outbound email. These are small by every size metric and unrecoverable by every recovery metric. A size-gated system waves them through precisely because they look trivial.

It is wrong restrictively: a large, purely local refactor across forty files is recoverable with a single `git checkout`. Gating it on size buys nothing and costs the agent's ability to finish work unattended.

The framework also runs under universal `bypassPermissions`. That matters more than it first appears: a PreToolUse hook returning `permissionDecision: "ask"` is a **no-op** in that mode. There is no prompt to surface. An "ask" that never reaches a human is indistinguishable from an allow.

## Decision

Autonomy is licensed by two independent gates evaluated in series. Task size is not a gate at any point.

**Gate 1, reversibility, is a hard floor.** Every action on the canonical irreversible surface maps to a PreToolUse `permissionDecision: "deny"` in all contexts. The surface is enumerated, not inferred: file and record deletion including unflagged relative `rm`, database `DROP` / `TRUNCATE` / unbounded `DELETE`, normal `git push`, external `POST` / `PUT` / `PATCH` / `DELETE`, production deploys, and outbound email or chat sends. Because `ask` is a no-op under `bypassPermissions`, `deny` is the only decision that actually stops anything. The human gate is therefore: deny, then surface a decision brief, then the owner re-runs the command via the `!`-prefix manual bypass, which skips PreToolUse hooks entirely.

**Gate 2, detectability, is an autonomy expander that operates only above the floor.** Among actions that are already reversible, apply one test: *can the agent write a tool call right now that would fail if this action were wrong, with no other agent and no human involved?* If yes, the action is self-detectable and the agent proceeds autonomously. If no, the action requires an independent detector that **re-derives** the result rather than re-reading it, or the agent pauses.

**Size is explicitly not a gate.** The classifier emits `REVERSIBILITY` and `DETECTABILITY` as advisory fields captured in the governance log. They are pre-warnings, never blocks. A task classified Quick still trips the Gate-1 deny if it touches the surface.

## Decision Drivers

- Under `bypassPermissions`, `ask` is a no-op. Any design that relies on `ask` to stop a destructive action does not stop it.
- The two failure modes of size-gating are not symmetric. Permissive failure is unrecoverable; restrictive failure merely wastes time. A correct rule must be strict about the first and generous about the second.
- Re-reading is not verification. An agent that writes a file and then reads it back has confirmed only that the write happened, not that it was correct. Re-derivation, recomputing the expected value by an independent path, is what distinguishes a detector from an echo.
- The irreversible surface has to be enumerated in exactly one place. Two copies drift, and a drifted deny-list is a silent hole in the floor.

## Consequences

**Positive.** Autonomy expands where it is safe to expand: a reversible edit verified by a test suite needs no human. Autonomy contracts to zero where it must: no size classification, no fast path, and no classifier decision can route around the Gate-1 deny, because the deny lives in the PreToolUse hook rather than in the classifier.

**Negative.** Enumeration is a maintenance burden. A new irreversible action is unguarded until someone adds it to the surface. The framework accepts this over pattern-inference, because a heuristic that guesses at irreversibility fails open on exactly the cases nobody anticipated.

**Operational.** Gate 1 is enforced by `hooks/bash-safety-guard.py` for shell commands and `hooks/mcp-irreversible-guard.py` for MCP tool calls. Both import the single canonical surface from `hooks/_irreversible_surface.py`. Gate 2 is enforced by `hooks/verifier-gate-check.py`, which checks a three-part structural contract: a distinct post-worker dispatch, a non-identical prompt, and a re-derivation keyword or artifact path.

**Known drift risk.** `bash-safety-guard.py` carries `_IRREVERSIBLE_FALLBACK_SNAPSHOT`, a frozen transcription of the canonical patterns, so it still functions if the shared module cannot be imported. The snapshot is a second copy of a list that ADR reasoning says must exist once. It is retained deliberately, because a guard that fails to import and therefore fails open is worse than a guard that occasionally lags. The mitigation is procedural: update the snapshot whenever `_irreversible_surface.py` changes. A narrowing edit to either copy must be verified to produce a new deny-set equal to the old one minus exactly the intended un-blocks, because narrowing a deny pattern has already been observed to open a floor hole that nobody intended.

## Alternatives Considered

**Size-gated autonomy.** Rejected for the asymmetric-failure reason above.

**Blanket `mcp__.*` deny.** Rejected. It would block every MCP read, making the framework unusable with MCP servers, and would train the operator to bypass reflexively. The guard enumerates the destructive tools instead.

**Relying on `ask` rather than `deny`.** Rejected as non-functional under `bypassPermissions`, which is the framework's normal operating mode.

## Related

- ADR-0002: Hooks enforce process, not prompts. Gate 1 is that principle at its strictest: the rule lives where prompt compliance cannot reach it.
- `docs/concepts/two-gate-autonomy.md` for the worked model and examples.
- `docs/reference/hooks.md` for the per-hook enforcement contracts.
