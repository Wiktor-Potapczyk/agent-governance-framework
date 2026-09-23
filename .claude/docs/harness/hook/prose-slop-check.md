---
component: "prose-slop-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: prose-slop-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/prose-slop-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose doc-consistency [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Prose Slop Check - PostToolUse Write|Edit hook  [LIVE, registered]

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on PostToolUse for Write and Edit (registered in `.claude/settings.local.json` under a `Write|Edit` matcher, per `.claude/hooks/prose-slop-check.py:30`). It scopes to `Resources/KB/**.md` and `Projects/*/work/**.md` through a slash-tolerant regex (`.claude/hooks/prose-slop-check.py:81`) and scans `content` for Write or `new_string` for Edit (`.claude/hooks/prose-slop-check.py:135`).

`find_slop` strips frontmatter, code, and tables, then counts hits from a 22-entry LLM-register wordlist (delve, tapestry, furthermore, and the rest) that was calibrated on 2026-06-02 to zero occurrences in real vault prose (`.claude/hooks/prose-slop-check.py:60`, `.claude/hooks/prose-slop-check.py:97`). It only warns past thresholds: two or more distinct slop words, or three or more total hits in one file (`.claude/hooks/prose-slop-check.py:77`).

Past a threshold it writes one stderr WARN listing up to eight hits with plain replacements and exits 0; it never blocks (`.claude/hooks/prose-slop-check.py:160`, exit contract at `.claude/hooks/prose-slop-check.py:47`). Each verdict logs to `hook-activity.jsonl` as allow or warn (`.claude/hooks/prose-slop-check.py:142`).
<!-- PROSE:END -->
