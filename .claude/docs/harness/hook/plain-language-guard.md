---
component: "plain-language-guard"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: plain-language-guard

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/plain-language-guard.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:**
  - inbound mentioned_in_prose CLAUDE.md [unresolved: prose mention only]
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

Plain-Language Guard - PostToolUse Write|Edit hook  [LIVE, warn-only, blocks OFF]

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

Fires on PostToolUse for Write and Edit (registered in `.claude/settings.local.json` under a `Write|Edit` matcher; the docstring states the same surface at `.claude/hooks/plain-language-guard.py:2`). It reads the payload from stdin, takes `tool_input.file_path`, and keeps only in-scope paths: `Projects/*/work/**.md` minus `work/backups/`, `Resources/KB/**.md`, and the framework-repo README and docs (`.claude/hooks/plain-language-guard.py:90`). The scanned text is `content` for Write or `new_string` for Edit (`.claude/hooks/plain-language-guard.py:149`), passed to `scan()` imported from `plain_language_check` (`.claude/hooks/plain-language-guard.py:78`).

For every in-scope write, findings or none, it appends exactly one JSONL record (ts, session, path, per-rule counts, total) to `aggregates/plain-language-warnings.jsonl` (`.claude/hooks/plain-language-guard.py:157`). When findings or marker-hygiene advisories exist, it writes one stderr WARN naming the rule ids, the file basename, and up to three samples, then exits 0: the write already landed on disk (`.claude/hooks/plain-language-guard.py:181`). Each verdict also logs to `hook-activity.jsonl` as allow, warn, or block (`.claude/hooks/plain-language-guard.py:116`).

A block path exists but is unreachable in the shipped build: `BLOCK_ENABLED_RULES` ships as an empty set (`.claude/hooks/plain-language-guard.py:82`), and only a rule in that set can produce exit 2 (`.claude/hooks/plain-language-guard.py:171`). Any internal exception fails open to exit 0 (`.claude/hooks/plain-language-guard.py:199`).
<!-- PROSE:END -->
