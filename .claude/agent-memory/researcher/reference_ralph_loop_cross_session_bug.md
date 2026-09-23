---
date: 2026-03-21
tags: #research #reference
status: active
---

# Ralph Loop Cross-Session Hook Bug — Research Findings

## Summary

The cross-session Stop hook interference in ralph-loop is a **documented, confirmed, multi-reporter bug** — not a unique discovery. It has been filed twice against two different Anthropic repos.

---

## Repository Provenance

Ralph-loop exists in two official Anthropic repos:

1. **anthropics/claude-code** — older version, called `ralph-wiggum` (`plugins/ralph-wiggum/`)
2. **anthropics/claude-plugins-official** — current maintained version, called `ralph-loop` (`plugins/ralph-loop/`)

Both are **Anthropic-maintained**. Not a third-party plugin.

---

## Bug Reports

### Issue #15047 — anthropics/claude-code
- Title: `[BUG] ralph-wiggum stop hook triggered in separate session`
- Reporter: @RockabyeSBJ — December 22, 2025
- Status: CLOSED (Not Planned)
- Platform: WSL Debian on Windows (our environment matches)
- Root cause: State file at CWD-relative path. If two sessions share the same CWD, Session B's Stop hook reads Session A's active state and hijacks.
- Fix merged: PRs #15850/#15853 — session ID stored in `$CLAUDE_PLUGIN_ROOT/state/${session_id}.md`

### Issue #26514 — anthropics/claude-code
- Title: `Ralph-loop: state file needs session scoping to prevent cross-terminal interference`
- Reporter: @matthewliu — February 18, 2026
- Status: CLOSED (Not Planned — stale)
- Root cause: `.claude/ralph-loop.local.md` is a single shared file. All sessions in the same project directory share it.
- Impact: Iteration counter burns through in wrong session; context fills with noise.
- Fix proposed (PR #606 by chgbnu, March 12, 2026): atomic `sed+mv` to claim `session_id` on first Stop hook trigger when field is empty
- PR #606 was NOT merged — anthropics/claude-plugins-official only accepts Anthropic team contributions

---

## Fix Status (as of 2026-03-21)

- **Older ralph-wiggum (claude-code repo):** Fix merged (PRs #15850/#15853) — session ID scoping in place
- **Current ralph-loop (claude-plugins-official):** Fix PR #606 closed/not merged (external contributor rejected). Issue still open.
- **Conclusion: The current production ralph-loop plugin likely still has the cross-session bug.**

---

## Hook Scoping — Official Documentation

Per official Claude Code docs (`code.claude.com/docs/en/hooks`):

- Hooks are **global by scope level** (project, local, machine) — NOT session-scoped
- The Stop hook fires for ALL sessions in the project, every time any session stops
- Hooks DO receive `session_id` in their JSON payload — it is the plugin's responsibility to use it
- Ralph-loop's stop hook was NOT checking `session_id` to filter non-owner sessions

---

## Related Bug — Stop Hook Fails After Single Iteration

Issue #394 — anthropics/claude-plugins-official (OPEN, February 14, 2026):
Two independent bugs in `stop-hook.sh`:
1. `echo` corrupts JSON with `\n` in content → `jq` parse error → hook exits, deletes state file
2. Relative path `.claude/ralph-loop.local.md` breaks if agent runs `cd` during iteration
Fix: use `printf '%s\n'` instead of `echo`; resolve project root via `git rev-parse --show-toplevel`
Status: NOT fixed as of research date.

---

## Practical Implication for This Vault

- Running ralph-loop in CLI session + interactive Desktop App session in same project = Stop hook interference
- Workaround (from GitHub): use `git worktree` for separate working directories, or only run ralph-loop when no other session is active in that project
- The `feedback_ralph_loop_reliability.md` reference in MEMORY.md relates to this bug class

---

## Sources

- https://github.com/anthropics/claude-code/issues/15047
- https://github.com/anthropics/claude-code/issues/26514
- https://github.com/anthropics/claude-plugins-official/issues/394
- https://github.com/anthropics/claude-plugins-official/pull/606
- https://code.claude.com/docs/en/hooks
