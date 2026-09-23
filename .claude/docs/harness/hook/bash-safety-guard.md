---
component: "bash-safety-guard"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: bash-safety-guard

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/bash-safety-guard.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
  - inbound mentioned_in_prose process-lint [unresolved: prose mention only]
  - inbound mentioned_in_prose task-classifier [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Bash Safety Guard - PreToolUse Hook (matcher: Bash)
Blocks dangerous shell commands before execution.
Denies: rm -rf, force-push, credential exposure, destructive git ops, git-hook bypass
(--no-verify / -n on commit-class subcommands, -c core.hooksPath= overrides).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This PreToolUse hook matches the Bash tool. It reads the payload from stdin, pulls tool_input.command (.claude/hooks/bash-safety-guard.py:522), and pre-processes it before any pattern match: trailing comments are stripped when safe, executing wrappers such as bash -c are unwrapped so their bodies face every rule, and known-inert contexts (grep patterns, echo text, commit messages, heredocs) are removed (.claude/hooks/bash-safety-guard.py:299).

The cleaned command is scanned against BLOCKED_PATTERNS: force-push variants, git reset --hard, hook bypass flags, credential reads, sudo, and the Gate-1 irreversible surface imported from _irreversible_surface and appended to the list (.claude/hooks/bash-safety-guard.py:395). A match prints a permissionDecision "deny" JSON and logs a deny event to governance-log.jsonl (.claude/hooks/bash-safety-guard.py:532). Normal push and working-branch force-push are lifted out into WARN_PATTERNS (.claude/hooks/bash-safety-guard.py:438) and instead produce an allow with a caution the agent reads first, logged as a warn event (.claude/hooks/bash-safety-guard.py:442).

Two dedicated blocks run after the regex loop: an external-curl-write predicate that denies a curl mutating remote state unless every target is a host we administer, which downgrades to a warn-and-allow (.claude/hooks/bash-safety-guard.py:582), and a Windows reserved-filename check that denies creating names like nul in redirect targets (.claude/hooks/bash-safety-guard.py:626). If the canonical surface module fails to import, the hook alarms loudly and enforces a frozen fallback snapshot rather than degrading to an empty surface (.claude/hooks/bash-safety-guard.py:89).
<!-- PROSE:END -->
