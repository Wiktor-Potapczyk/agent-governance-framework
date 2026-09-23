---
component: "em-dash-guard"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: em-dash-guard

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/em-dash-guard.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Em-Dash Guard - Stop Hook. Blocks the assistant from shipping a response whose
prose contains a fancy dash glyph. Wiktor never uses these characters in
writing and wants them impossible in output, not merely discouraged; soft
instructions land ~25% compliance, so this hook is the runtime enforcement
(.claude/hooks/em-dash-guard.py:4).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

This Stop hook reads the transcript tail and takes the text of the last assistant message (.claude/hooks/em-dash-guard.py:97), then strips frontmatter, fenced code blocks, inline code spans, and real markdown table rows so only the assistant's own prose is scanned (.claude/hooks/em-dash-guard.py:82). It honors stop_hook_active and fails open on any parse error (.claude/hooks/em-dash-guard.py:141).

The remaining prose is checked against nine blocked dash glyphs, figure dash through fullwidth hyphen-minus, kept as literal characters in a name table so the check is a plain substring test (.claude/hooks/em-dash-guard.py:64). A clean response logs "allow" and exits 0 (.claude/hooks/em-dash-guard.py:162); a hit writes the rewrite instruction to stderr, naming the offending glyphs and forbidding a swap to another dash character, then returns exit code 2, which blocks the response. The block is issued before the log write so logging cannot swallow the verdict (.claude/hooks/em-dash-guard.py:165).
<!-- PROSE:END -->
