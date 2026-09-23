---
component: "routing-table-validation"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: routing-table-validation

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/routing-table-validation.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

routing-table-validation.py: PreToolUse Edit|Write|MultiEdit hook (Delta-5 Tier A)

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires PreToolUse on Write, Edit, and MultiEdit (.claude/hooks/routing-table-validation.py:374-375). Gate (a) scopes it to doctrine files only: CLAUDE.md or any .claude/skills/*/SKILL.md (.claude/hooks/routing-table-validation.py:154-176). It validates only the text the call introduces: the full content for Write, `new_string` for Edit, the concatenated new strings for MultiEdit (.claude/hooks/routing-table-validation.py:283-313).

That text is scanned for dispatch positions: MUST DISPATCH lines, `subagent_type` assignments, and markdown table rows whose surrounding lines mention agent, dispatch, or routing (.claude/hooks/routing-table-validation.py:194-230). Fenced code and comment lines are skipped (.claude/hooks/routing-table-validation.py:246-252). A candidate token must have agent-name shape and must resolve against registry.json (agents plus skills), a deprecated allowlist, and a set of structural non-agent identifiers; only a token failing all of those counts as broken (.claude/hooks/routing-table-validation.py:65, .claude/hooks/routing-table-validation.py:117-147, .claude/hooks/routing-table-validation.py:260-274).

A broken reference denies via hookSpecificOutput permissionDecision "deny" naming the tokens, then logs a "deny" record to hook-activity.jsonl; clean scans log "allow", and an unreadable registry logs "skip" and fails open. The exit code is always 0 (.claude/hooks/routing-table-validation.py:320-335, .claude/hooks/routing-table-validation.py:398-418).
<!-- PROSE:END -->
