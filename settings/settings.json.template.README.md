# settings.json.template: Installation Guide

`settings.json.template` is a portable copy of the framework's Claude Code session settings with all machine-specific paths replaced by placeholders. You substitute the placeholders at install time to produce a working `settings.json` (placed at `~/.claude/settings.json` or your project's `.claude/settings.json`).

## Placeholders

| Placeholder | Replace with | Example |
|---|---|---|
| `{{VAULT_ROOT}}` | Absolute path to your vault / workspace root | `/home/alice/vault` or `C:/Users/alice/Vault` |
| `{{HOME}}/.claude/` | Path to your Claude config directory | `/home/alice/.claude/` |
| `{{HOME_OR_VAULT}}` | Path prefix for Read/Bash permissions: typically your home dir or vault root | `/home/alice` or `C:/Users/alice` |

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

- **`CLAUDE_CODE_AUTO_COMPACT_WINDOW`**: token threshold before auto-compaction. Adjust to match your project size.

### Permissions

A minimal allow-list of structural permissions. Extend with project-specific WebFetch domains and Bash patterns as needed.

### Hooks: 35 hooks across 8 events

| Event | Count | Hooks |
|---|---|---|
| `SessionStart` | 2 | `session-start-log.py`, `session-start-orientation.py` |
| `UserPromptSubmit` | 2 | `user-prompt-submit.py`: CTX bar injection + classifier enforcement, `user-prompt-state-inject.py` |
| `PreToolUse` | 7 | `skill-routing-check.py` (Skill matcher), `bash-safety-guard.py` (Bash matcher), `agent-dispatch-check.py` (Agent matcher), `memory-dedup-check.py` (Write matcher), `config-protection.py`, `read-before-edit-check.py`, `tag-variant-check.py` |
| `PostToolUse` | 7 | `skill-step-reminder.py` (Skill matcher), `memory-schema-check.py` (Write\|Edit matcher), `wiki-citation-check.py`, `bias-guard.py`, `mcp-circuit-breaker-record.py`, `inbox-auto-ingest.py`, `reviewer-scope-violation-check.py` |
| `SubagentStart` | 4 | `subagent-governance.py`, `agent-registry-check.py`, `subagent-scope-check.py`, `mcp-circuit-breaker.py` |
| `SubagentStop` | 2 | `subagent-quality-check.py`, `checkpoint.py` |
| `Stop` | 11 | `classifier-field-check.py`, `dispatch-compliance-check.py`, `governance-log.py`, `process-step-check.py`, `dark-zone-check.py`, `work-verification-check.py`, `token-breakdown.py`, `epistemic-check.py`, `verifier-gate-check.py`, `task-plan-auto-sync.py`, `registry-staleness-check.py` |
| `PreCompact` | 1 | `pre-compact.py` |

## After substitution

Place the resulting `settings.json` where Claude Code will find it:
- **Global:** `~/.claude/settings.json`
- **Project-level:** `<project-root>/.claude/settings.json`

Project-level settings take precedence over global for that project.
