# settings.json.template — Installation Guide

`settings.json.template` is a portable copy of the framework's Claude Code session settings with all machine-specific paths replaced by placeholders. You substitute the placeholders at install time to produce a working `settings.json` (placed at `~/.claude/settings.json` or your project's `.claude/settings.json`).

## Placeholders

| Placeholder | Replace with | Example |
|---|---|---|
| `{{VAULT_ROOT}}` | Absolute path to your vault / workspace root | `/home/alice/vault` or `C:/Users/alice/Vault` |
| `{{HOME}}/.claude/` | Path to your Claude config directory | `/home/alice/.claude/` |
| `{{HOME_OR_VAULT}}` | Path prefix for Read/Bash permissions — typically your home dir or vault root | `/home/alice` or `C:/Users/alice` |

> **Note:** On Windows use forward slashes or escaped backslashes consistently. Git Bash and PowerShell both accept forward slashes in most contexts.

## Substitution (bash one-liner)

```bash
VAULT_ROOT="/absolute/path/to/your/vault"
HOME_DIR="$HOME"
sed \
  -e "s|{{VAULT_ROOT}}|${VAULT_ROOT}|g" \
  -e "s|{{HOME_OR_VAULT}}|${HOME_DIR}|g" \
  settings.json.template > settings.json
```

On Windows (PowerShell):

```powershell
$VaultRoot = "C:\Users\you\Vault"
$HomeDir   = "C:\Users\you"
(Get-Content settings.json.template) `
  -replace '\{\{VAULT_ROOT\}\}',      $VaultRoot `
  -replace '\{\{HOME_OR_VAULT\}\}',   $HomeDir |
  Set-Content settings.json
```

## Python runtime requirement

Hook commands invoke `python3`. On Windows, install Python 3.10+ and ensure `python3` (or `python`) is on `PATH`. If your system uses a different executable name (e.g., the full absolute path such as `C:\Program Files\Python314\python.exe`), replace every `python3` occurrence in the hook `command` strings before or after substitution.

## What this file controls

### Environment

- **`CLAUDE_CODE_AUTO_COMPACT_WINDOW`** — token threshold before auto-compaction. Adjust to match your project size.

### Permissions

A minimal allow-list of structural permissions. Extend with project-specific WebFetch domains and Bash patterns as needed.

### Hooks — 16 hooks across 7 events

| Event | Count | Hooks |
|---|---|---|
| `UserPromptSubmit` | 1 | `user-prompt-submit.py` — CTX bar injection + classifier enforcement |
| `PreToolUse` | 5 | `skill-routing-check.py` (Skill matcher), `bash-safety-guard.py` (Bash matcher), `agent-dispatch-check.py` (Agent matcher), `memory-dedup-check.py` (Write matcher), `check_forbidden_tokens.py` (Write\|Edit matcher) |
| `PostToolUse` | 2 | `skill-step-reminder.py` (Skill matcher), `memory-schema-check.py` (Write\|Edit matcher) |
| `SubagentStart` | 2 | `subagent-governance.py`, `agent-registry-check.py` |
| `SubagentStop` | 1 | `subagent-quality-check.py` |
| `Stop` | 7 | `classifier-field-check.py`, `dispatch-compliance-check.py`, `governance-log.py`, `process-step-check.py`, `dark-zone-check.py`, `work-verification-check.py`, `token-breakdown.py` |

**Note:** `SessionStart` and `PreCompact` hooks exist in `settings.json` (global config) but are not in this project-level template. If you rely on them, add them from `settings.local.json.example`.

## After substitution

Place the resulting `settings.json` where Claude Code will find it:
- **Global:** `~/.claude/settings.json`
- **Project-level:** `<project-root>/.claude/settings.json`

Project-level settings take precedence over global for that project.
