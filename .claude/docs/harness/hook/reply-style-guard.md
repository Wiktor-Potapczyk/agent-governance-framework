---
component: "reply-style-guard"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: reply-style-guard

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/reply-style-guard.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

WHY A STOP HOOK AND NOT A WRITE HOOK. This vault already ran the experiment.
`em-dash-guard.py` is a Stop hook returning exit 2; its own activity log shows
153 blocks against 1,386 allows, and the behaviour it polices has held.
`plain-language-guard.py` is PostToolUse and warn-only; it logged 446 in-scope
writes, 266 of them carrying findings, and changed nothing. That guard's own
docstring records why flipping its block switch would not help either
(.claude/hooks/reply-style-guard.py:8-12).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Registered as a Stop hook. It reads the Stop payload from stdin and returns 0 at once when `stop_hook_active` is set (.claude/hooks/reply-style-guard.py:252-253). It then reads the last 200KB of the transcript and pulls out the text blocks of the last assistant message (.claude/hooks/reply-style-guard.py:81, .claude/hooks/reply-style-guard.py:180-206).

Before judging anything it strips every exempt surface: fenced code first, then frontmatter, inline code, markdown table rows, and the structured report blocks including their internal blank lines (.claude/hooks/reply-style-guard.py:136-177). Two rules run on what remains: four or more bold spans (.claude/hooks/reply-style-guard.py:86, .claude/hooks/reply-style-guard.py:212-214) and a conservative stock-AI wordlist (.claude/hooks/reply-style-guard.py:95-112).

A clean reply logs an "allow" record; a violation writes the rewrite instruction to stderr and exits 2, so the assistant redrafts before the user sees the reply (.claude/hooks/reply-style-guard.py:266-288). Every invocation, allow and block alike, appends one record to hook-activity.jsonl through _governance_logger.log_fire, and any internal error fails open with exit 0 (.claude/hooks/reply-style-guard.py:222-235, .claude/hooks/reply-style-guard.py:262-264).
<!-- PROSE:END -->
