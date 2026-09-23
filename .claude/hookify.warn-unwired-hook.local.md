---
name: warn-unwired-hook
enabled: true
event: file
conditions:
  - field: file_path
    operator: regex_match
    pattern: \.claude[/\\]hooks[/\\](?!test_)(?!_)[A-Za-z0-9][A-Za-z0-9-]*\.py$
action: warn
---

⚠️ **Build-then-wire check** (audit 2026-06-10, lesson 7)

You are writing a hook file under `.claude/hooks/`. A hook that is not registered in `settings.json` or `settings.local.json` silently never fires — empirical case: `routing-table-validation.py` was built 2026-06-08 with a full test suite and stayed a runtime no-op until wired 2026-06-12.

Definition-of-done for a hook: (1) the .py file, (2) the settings registration, (3) a fired-once proof (`echo '{}' | python <hook>`). If this Write is an edit to an already-registered hook, ignore this warning.
