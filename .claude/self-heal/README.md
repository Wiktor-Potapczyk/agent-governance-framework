# .claude/self-heal/

This directory, `.claude/self-heal/**`, is forbidden to the self-healing loop.
Only the owner (Wiktor) edits anything under this path. The loop's own target
selection and acceptance scripts must reject any diff that touches it,
regardless of class.

`ci-settings.json` registers Gate-1's two guard hooks (`bash-safety-guard.py`
PreToolUse Bash, `mcp-irreversible-guard.py` PreToolUse `mcp__.*`), routed
through the `.claude/bin/py` interpreter resolver, so a `claude -p --settings`
invocation loads the reversibility floor even though the guards' only other
registration today lives in the gitignored `.claude/settings.local.json`.

Spec: `Projects/Vault-Maintenance/work/2026-09-16-self-healing-loop-spec.md`,
section 7, TASK-005.
