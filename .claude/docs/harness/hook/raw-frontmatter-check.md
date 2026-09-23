---
component: "raw-frontmatter-check"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: raw-frontmatter-check

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/raw-frontmatter-check.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

raw-frontmatter-check.py — PostToolUse Write hook (ADVISORY v1, 2026-05-11).

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on PostToolUse (registered in `.claude/settings.local.json` under a `Write|Edit` matcher); the code accepts Write or Edit tool names (`.claude/hooks/raw-frontmatter-check.py:157`). It resolves the written path against the vault and applies raw-layer scope filters: `.md` only, minus excluded prefixes (Inbox, Templates, Clippings, .claude, and others), excluded filenames (STATE.md, CLAUDE.md, and the rest), plugin and skill sub-paths, and the wiki layer (`.claude/hooks/raw-frontmatter-check.py:72`, lists at `.claude/hooks/raw-frontmatter-check.py:41`). A file whose frontmatter tags include `wiki` is skipped as wiki-layer material (`.claude/hooks/raw-frontmatter-check.py:94`).

It then reads the file from disk, parses the top-level frontmatter field names (`.claude/hooks/raw-frontmatter-check.py:113`), and checks for the three required fields: date, tags, status (`.claude/hooks/raw-frontmatter-check.py:59`). On a miss it prints a `hookSpecificOutput.additionalContext` advisory naming the missing fields and pointing at the structure spec's R3 section (`.claude/hooks/raw-frontmatter-check.py:133`). It never blocks. `RAW_FRONTMATTER_CHECK_DISABLED=1` disables it entirely and `RAW_FRONTMATTER_CHECK_VERBOSE=1` also logs passes to `logs/raw-frontmatter-check.log` (`.claude/hooks/raw-frontmatter-check.py:38`).
<!-- PROSE:END -->
