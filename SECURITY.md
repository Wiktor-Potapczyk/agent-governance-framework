# Security Policy

## Reporting a vulnerability

Report privately through [GitHub Security Advisories](https://github.com/Wiktor-Potapczyk/agent-governance-framework/security/advisories/new) on this repository. Do not open a public issue for a security concern until a fix is available.

There is no bug bounty program. This is a personal governance framework, published for others to fork and adapt (see [CONTRIBUTING.md](CONTRIBUTING.md)), maintained by one person.

## Trust model

Four actors are in scope.

- **The model.** Claude Code, running under `bypassPermissions`. It is treated as a cooperative agent that can make mistakes, not as an adversary. See [ADR-0007](docs/adr/0007-two-gate-autonomy.md).
- **The hooks.** Python scripts under `hooks/` that fire on Claude Code lifecycle events (`PreToolUse`, `Stop`, and others) and can block, deny, or annotate a tool call. See [docs/architecture.md](docs/architecture.md) for the four-layer model.
- **The operator.** The person running Claude Code and this framework. The operator can bypass any hook with the `!`-prefix manual command, which skips `PreToolUse` hooks entirely.
- **The operating system and account.** File permissions, process isolation, and account boundaries.

**State this plainly: the hooks are pattern-based guards, not a security boundary.** Their purpose is containing accidental self-harm by a cooperative agent that is trying to comply but makes a mistake: an unflagged `rm` on the wrong directory, a `git push` before the operator meant to publish, a `DROP TABLE` typed by pattern rather than intent. They are not a defense against a deliberately evasive actor.

This is not a hedge. It has already happened, and it is documented in the code that fixed it. `hooks/bash-safety-guard.py` records an incident (`GATE-1-BYPASS / HA-A-044`, confirmed four times) where wrapping any command in `bash -c "..."` caused the guard's own string-literal stripping to treat the executing payload as inert text, letting it sail past every deny pattern, force-push included. The fix, `unwrap_executing_wrappers()` in the same file, closes that specific form. A pattern-matching guard closes the forms it has seen. It does not close the class.

**The only real security boundary here is the operating system and account isolation.** If an actor can run arbitrary shell commands as your account, no regex-based hook stops them: a hook is itself a script the same account can read, patch, or route around. Isolate the account, not the agent.

## What the floor covers

Gate 1 (see [ADR-0007](docs/adr/0007-two-gate-autonomy.md) and [docs/concepts/two-gate-autonomy.md](docs/concepts/two-gate-autonomy.md)) denies an enumerated irreversible surface in all contexts: unflagged relative file or record deletion, destructive SQL (`DROP`, `TRUNCATE`, unbounded `DELETE`), `git push` including force-push, outbound `POST`/`PUT`/`PATCH`/`DELETE`, production deploys, and outbound email or chat sends. The surface lives once, in `hooks/_irreversible_surface.py`, imported by both enforcement arms: `hooks/bash-safety-guard.py` for shell, `hooks/mcp-irreversible-guard.py` for MCP tool calls.

Under Claude Code's `bypassPermissions` mode, a `PreToolUse` hook returning `permissionDecision: "ask"` is a no-op: nothing pauses, the action proceeds. `deny` is the only decision that actually stops anything. A Gate-1 deny surfaces a decision brief to the operator, who re-runs the command manually with the `!` prefix if they still want it to happen. That manual, human-typed re-run is the real human gate, not the hook itself.

## Named non-boundaries

The following are enforcement conveniences, not security guarantees.

- **Regex and pattern matching.** Every Gate-1 hook matches shell command text or tool names against a fixed pattern list ([docs/reference/hooks.md](docs/reference/hooks.md)). A pattern list has edges, and the wrapper incident above is the documented proof.
- **Prompt text (`CLAUDE.md`, `SKILL.md` files).** Instructions read by a cooperative model. [ADR-0002](docs/adr/0002-hooks-enforce-process-not-prompts.md) measured roughly 25% compliance from prompts alone, which is the reason hooks exist at all. Prompt text stops nothing by itself.
- **Advisory warnings.** Most hooks in this repository fail open and warn rather than block: see the Failure mode row for each entry in [hooks/README.md](hooks/README.md). A warning is a log line, not a control.

## Related documentation

[docs/architecture.md](docs/architecture.md) for the layer model, [ADR-0007](docs/adr/0007-two-gate-autonomy.md) for Two-Gate Autonomy, [docs/concepts/two-gate-autonomy.md](docs/concepts/two-gate-autonomy.md) for worked examples, and [docs/reference/hooks.md](docs/reference/hooks.md) for per-hook enforcement contracts.
