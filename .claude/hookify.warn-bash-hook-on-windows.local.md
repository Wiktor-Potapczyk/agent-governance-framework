---
name: warn-bash-hook-on-windows
enabled: true
event: file
pattern: \.claude/hooks/.*\.sh$
action: warn
---

**New `.sh` hook detected under `.claude/hooks/`**

On Windows, newly-created bash hook scripts fail in the Claude Code Desktop hook runner — they error even when they exit 0 manually. Pre-existing `.sh` files (session-start.sh, restore-compact.sh, pre-compact.sh) work fine, but anything authored in-session does NOT.

For any new hook beyond a simple inline command, write a `.ps1` PowerShell script instead and invoke via:

```
powershell -NonInteractive -ExecutionPolicy Bypass -File "C:\path\to\hook.ps1"
```

Source: `memory/feedback_hook_authoring_rules.md`. Backfilled by L34 (2026-05-24).
