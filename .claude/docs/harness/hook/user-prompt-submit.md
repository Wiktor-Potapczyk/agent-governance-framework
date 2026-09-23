---
component: "user-prompt-submit"
kind: "hook"
source_inventory_generated_at: "2026-09-23T07:59:53Z"
---

# hook: user-prompt-submit

<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->
- **Path:** `.claude/hooks/user-prompt-submit.py`
- **Provenance:** authored-in-harness
- **Reachability:** none recorded; blocked: `BLK-001`
- **Usage:** Recorded use count 0 (source: `hook-activity.jsonl:hook_fire.hook`).
- **Edges:** (no edges recorded)
- **Twin state:** repo-absent
<!-- GENERATED:END -->

<!-- PROSE:BEGIN preserved byte-identical across regeneration -->
## Why

UserPromptSubmit hook - context bar from real API usage data + task-classifier enforcement.

(machine-filled from rationale-index.json; extraction locus: docstring)

## How

A UserPromptSubmit hook. It reads the last 100 KB of the transcript and regex-parses the newest `"model"` id and the last `input_tokens`, `cache_creation_input_tokens`, and `cache_read_input_tokens` values to measure context occupancy (.claude/hooks/user-prompt-submit.py:29); the model id decides the 200K versus 1M token limit (.claude/hooks/user-prompt-submit.py:43).

From that it builds a CTX bar line with `/save` recommended at 50 percent and `/compact` at 70 (.claude/hooks/user-prompt-submit.py:66) and wraps it in a DISPLAY RULE telling the model to begin every response with the bar (.claude/hooks/user-prompt-submit.py:124). It always appends a mandatory task-classifier reminder (.claude/hooks/user-prompt-submit.py:85); at 50 percent-plus context a save-enforcement prefix is added (.claude/hooks/user-prompt-submit.py:101), and the reminder is dropped entirely for subagents and trivial ack prompts (.claude/hooks/user-prompt-submit.py:108).

The combined text is printed as one UserPromptSubmit `additionalContext` payload (.claude/hooks/user-prompt-submit.py:135), and one record per prompt goes to hook-activity.jsonl with the measured percentage, the vault's only per-turn series of context occupancy (.claude/hooks/user-prompt-submit.py:143).
<!-- PROSE:END -->
